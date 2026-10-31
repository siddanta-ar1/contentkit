"""Copy an edit, not a video: analyse a reference reel and rebuild its structure on your footage.

  contentkit reference analyze <url-or-file> -o refs/<name>
      reference.mp4, audio.wav, analysis.json, ANALYSIS.md, shots.jpg (one still per shot)
  contentkit reference recipe refs/<name>/analysis.json --media content/<job>/media -o content/<job>/recipe.yaml
      a recipe with the reference's shot count, shot lengths (or beat counts), text
      positions and timing, hook shape and music sync, filled with your media in order

What's measured per shot: start, length, framing (from the largest face), on-screen text
and where it sits, how much moves. For the whole video: cut rhythm, whether cuts land on
the music's beat, tempo, loudness, hook shape (first cut, text and face on frame 1),
loop (does the last frame match the first), optional speech transcript.

Platforms demote reposted footage and audio (Meta's originality rules, 2025): use the
reference for its structure and timing, shoot or bring your own pictures, and rewrite its
text. The generated recipe marks every borrowed line `<rewrite: ...>`; contentkit refuses to
render a recipe that still has placeholders.
"""
import json
import shutil
from pathlib import Path

from PIL import Image

from . import ff, vision
from .analyze import cuts
from .audio import measure
from .beats import analyze as beat_analyze

MEDIA_VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
MEDIA_IMAGE = {".jpg", ".jpeg", ".png", ".webp"}


def _get(src, out):
    """Local file, or download a URL into out/ with fetch."""
    if Path(src).exists():
        dest = out / ("reference" + Path(src).suffix.lower())
        if dest.resolve() != Path(src).resolve():
            shutil.copy2(src, dest)
        return dest, {"source": str(src)}
    from .fetch import download
    path, meta = download(src, out_dir=out)
    dest = out / ("reference" + path.suffix)
    path.replace(dest)
    path.with_suffix(".source.json").unlink(missing_ok=True)
    return dest, {"source": src, "title": meta.get("title"), "uploader": meta.get("uploader")}


def analyze(src, out, transcribe=False, log=print):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    video, origin = _get(src, out)
    info = ff.probe(video)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    dur = float(info["format"]["duration"])
    w, h = int(v["width"]), int(v["height"])
    log(f"reference: {w}x{h}, {dur:.1f}s")

    cut_times = cuts(video)
    bounds = [0.0] + cut_times + [dur]
    shots, stills = [], []
    caps = vision.capabilities()
    for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
        if b - a < 0.04:
            continue
        mid = vision.frame_at(video, (a + b) / 2)
        early = vision.frame_at(video, a + min(0.08, (b - a) / 4))
        late = vision.frame_at(video, b - min(0.08, (b - a) / 4))
        fc = vision.faces(mid)
        tx = vision.text(mid) if len(shots) < 40 else None
        mv = vision.motion(early, late)
        shots.append({
            "n": len(shots) + 1, "start": round(a, 3), "end": round(b, 3), "duration": round(b - a, 3),
            "framing": vision.framing(fc) if fc is not None else None,
            "face": [round(float(x), 3) for x in fc[0][:4]] if fc else None,
            "text": (tx or {}).get("text") or None, "text_position": (tx or {}).get("position"),
            "motion": round(mv, 1) if mv is not None else None,
        })
        if mid is not None:
            stills.append((Image.fromarray(mid), shots[-1]))
    log(f"  {len(shots)} shots")

    audio_wav = None
    music = {}
    if has_audio:
        audio_wav = out / "audio.wav"
        ff.run(["-i", video, "-vn", "-ac", 2, "-ar", 48000, audio_wav])
        try:
            g = beat_analyze(audio_wav, hook_window=min(dur, 20))
            beat = g["beat"]
            on = [t for t in cut_times if min((t - g["first_beat"]) % beat, beat - (t - g["first_beat"]) % beat) <= 0.07]
            music = {"bpm": g["bpm"], "first_beat": g["first_beat"],
                     "cuts_on_beat": round(len(on) / len(cut_times), 2) if cut_times else 0.0}
        except Exception as exc:  # silence, speech-only, very short audio
            music = {"error": str(exc)[:120]}
        loud = measure(audio_wav)
        music["lufs"] = float(loud["input_i"])

    first, last = vision.frame_at(video, 0.05), vision.frame_at(video, max(dur - 0.08, 0))
    hook_frame = vision.frame_at(video, min(0.3, dur / 3))  # after any 0.1-0.2 s title fade-in
    fc0 = vision.faces(hook_frame)
    tx0 = vision.text(hook_frame)
    hook = {
        "first_cut": cut_times[0] if cut_times else None,
        "text_on_first_frame": bool(tx0 and tx0["text"]), "first_frame_text": (tx0 or {}).get("text") or None,
        "face_on_first_frame": bool(fc0), "first_frame_framing": vision.framing(fc0) if fc0 is not None else None,
        "motion_first_second": vision.motion(first, vision.frame_at(video, min(1.0, dur / 2))),
        "loops": (vision.similarity(first, last) or 0) > 0.85,
    }
    words = None
    if transcribe and audio_wav:
        from .captions import transcribe as tr
        words = tr(audio_wav)
    result = {
        "origin": origin, "file": video.name, "audio": audio_wav.name if audio_wav else None,
        "duration": round(dur, 3), "size": [w, h], "fps": v.get("r_frame_rate"),
        "shots": shots, "avg_shot": round(sum(s["duration"] for s in shots) / max(len(shots), 1), 3),
        "music": music, "hook": hook, "capabilities": caps,
        "speech": " ".join(wd[2] for wd in words) if words else None,
    }
    (out / "analysis.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    _write_md(out / "ANALYSIS.md", result)
    _sheet(stills, out / "shots.jpg", result)
    log(f"  wrote {out}/analysis.json, ANALYSIS.md, shots.jpg")
    return result


def _write_md(path, r):
    m, hk = r["music"], r["hook"]
    lines = [f"# Reference: {r['origin'].get('title') or r['file']}", "",
             f"- {r['size'][0]}x{r['size'][1]}, {r['duration']}s, {len(r['shots'])} shots, average {r['avg_shot']}s",
             f"- Hook: first cut {hk['first_cut']}s; text on frame 1: {hk['text_on_first_frame']}"
             f" ({hk['first_frame_text'] or '-'}); face on frame 1: {hk['face_on_first_frame']}"
             f" ({hk['first_frame_framing']}); loops: {hk['loops']}"]
    if m.get("bpm"):
        lines.append(f"- Music: {m['bpm']:.1f} BPM, {int(m['cuts_on_beat'] * 100)}% of cuts on the beat, "
                     f"{m.get('lufs')} LUFS")
    if r.get("speech"):
        lines.append(f"- Speech: {r['speech'][:400]}")
    lines += ["", "| # | start | length | framing | motion | text (position) |", "|---|---|---|---|---|---|"]
    for s in r["shots"]:
        txt = f"{s['text']} ({s['text_position']})" if s["text"] else ""
        lines.append(f"| {s['n']} | {s['start']:.2f} | {s['duration']:.2f} | {s['framing'] or ''} | "
                     f"{s['motion'] if s['motion'] is not None else ''} | {txt.replace('|', '/')} |")
    lines += ["", "## Beat sheet (fill in)", "", "- Setup:", "- Turn:", "- Payoff:", "- Why it works:"]
    Path(path).write_text("\n".join(lines) + "\n")


def _sheet(stills, out, r):
    from .proof import _sheet as sheet
    from .brand import load_brand
    if not stills:
        return
    vertical = r["size"][1] > r["size"][0]
    tile_w = 220 if vertical else 360
    tiles = []
    for im, s in stills:
        im = im.copy()
        im.thumbnail((tile_w, tile_w * 2))
        tiles.append(im)
    caps = [f"#{s['n']} {s['start']:.1f}s +{s['duration']:.1f}" for _, s in stills]
    title = r["origin"].get("title") or r["file"]
    sub = f"{len(stills)} shots · avg {r['avg_shot']}s · {r['duration']}s"
    sheet(tiles, caps, title[:60], sub, 8 if vertical else 5, load_brand(None), tile_w).save(out, quality=88)


def _media(folder):
    files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in MEDIA_VIDEO | MEDIA_IMAGE)
    if not files:
        raise SystemExit(f"No photos or clips in {folder}")
    return files


def recipe(analysis_path, media_dir, out, use_reference_audio=False, fmt="reel"):
    """Write a recipe that rebuilds the reference's structure with your media."""
    analysis_path = Path(analysis_path)
    r = json.loads(analysis_path.read_text())
    files = _media(media_dir)
    out = Path(out)
    rel = lambda p: str(Path(p).resolve())
    m = r["music"]
    synced = bool(m.get("bpm")) and m.get("cuts_on_beat", 0) >= 0.6
    music_file = rel(analysis_path.parent / r["audio"]) if use_reference_audio and r.get("audio") \
        else "<path/to/your-song.mp3>"
    lines = [f"# Rebuilt from: {r['origin'].get('title') or r['origin'].get('source')}",
             f"# {len(r['shots'])} shots, avg {r['avg_shot']}s"
             + (f", cut on the beat at {m['bpm']:.0f} BPM" if synced else "")
             + ". Fill every <rewrite: ...> with your own words.",
             f"name: {out.parent.name or 'remake'}",
             "brand: {preset: fresh}",
             f"format: {fmt}",
             "captions: " + ("{style: pop}" if r.get("speech") else "false"),
             "transition: cut", "",
             "music:", f"  file: {music_file}",
             "  start: 0" if use_reference_audio else "  start: hook",
             "  volume: 1.0"]
    if synced:
        lines += ["  sync: beat", f"  bpm: {m['bpm']}"]
    lines += ["", "scenes:"]
    for i, s in enumerate(r["shots"]):
        f = files[i % len(files)]
        kind = "video" if f.suffix.lower() in MEDIA_VIDEO else "image"
        lines.append(f"  - {kind}: {rel(f)}        # ref shot {s['n']}: {s['framing'] or ''}"
                     + (f", moving" if (s.get('motion') or 0) > 12 else ""))
        if synced:
            lines.append(f"    beats: {max(1, round(s['duration'] / (60 / m['bpm'])))}")
        else:
            lines.append(f"    duration: {s['duration']}")
        if kind == "image":
            lines.append("    move: " + ("in" if i % 2 == 0 else "out"))
        if s.get("text"):
            pos = s.get("text_position") or "center"
            style = "label" if pos == "center" else "meme"
            orig = s["text"].replace('"', "'")[:80]
            if i == 0 and pos == "top":
                lines.append(f'    header: "<rewrite: {orig}>"')
            else:
                lines.append(f'    texts: [{{at: 0.0, until: {s["duration"]}, text: "<rewrite: {orig}>", '
                             f"style: {style}, position: {pos}}}]")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    return out
