"""Edit critique: measure a finished video the way a short-form editor would judge it.

Measures with ffmpeg, then scores against targets for the kind of video:
  hook        time to the first cut (viewers decide in about a second)
  pacing      average and longest shot length
  dead air    silences inside the programme
  loudness    integrated LUFS and true peak against the -14 / -1 delivery spec
  defects     black frames, frozen stretches (unintended), wrong aspect / low resolution

Targets are working rules from short-form editing practice, not platform rules; the
report says which rule produced each note so the editor can overrule it.
"""
import json
import re
import subprocess
from pathlib import Path

from . import ff
from .audio import measure

KINDS = {
    #            first cut  avg shot     longest  ideal length
    "meme":       {"hook": 1.2, "avg": (0.4, 1.8), "max": 3.0, "len": (6, 20)},
    "remix":      {"hook": 1.5, "avg": (0.4, 1.6), "max": 2.5, "len": (7, 30)},
    "commentary": {"hook": 2.0, "avg": (1.2, 4.0), "max": 7.0, "len": (15, 60)},
    "brand":      {"hook": 2.0, "avg": (1.5, 4.0), "max": 6.0, "len": (10, 45)},
}


def _stderr(args):
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *map(str, args)], capture_output=True,
                          text=True).stderr


def _scene_scores(src, width, blur=0.0):
    vf = f"scale={width}:-2" + (f",gblur=sigma={blur}" if blur else "") + ",scdet=threshold=1,metadata=print:file=-"
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-an", "-vf", vf, "-f", "null", "-"],
                          capture_output=True, text=True)
    scores, t = {}, None
    for line in proc.stdout.splitlines():
        if "pts_time:" in line:
            t = round(float(line.rsplit("pts_time:", 1)[1]), 3)
        elif line.startswith("lavfi.scd.score=") and t is not None:
            scores[t] = float(line.split("=", 1)[1])
    return scores


def _periodic(times, tol=0.05, min_run=4):
    """Times that sit on a regular grid (beat pulses): the most common spacing between
    neighbours, if at least `min_run` gaps share it."""
    if len(times) < min_run + 1:
        return set()
    gaps = [b - a for a, b in zip(times, times[1:])]
    best, period = 0, None
    for g in gaps:
        if g < 0.2:
            continue
        n = sum(1 for h in gaps if any(abs(h - k * g) <= tol for k in (1, 2, 3)))
        if n > best:
            best, period = n, g
    if best < min_run:
        return set()
    # local test (a neighbour one or two periods away) so tempo-vs-frame drift doesn't matter
    return {t for t in times
            if any(abs(abs(t - u) - k * period) <= tol for u in times if u != t for k in (1, 2))}


def cuts(src, min_gap=0.2):
    """Perceptible cuts.

    Two views of each frame change: a blurred 48-px thumbnail (ignores grain, zoom pulses
    and small moves; a real cut to new content scores >= 5) and a 270-px frame (also sees
    punch-ins and reframes, but beat pulses score just as high there). Changes that repeat
    on a regular grid are beat pulses and only count if the blurred view also sees a cut;
    one-off changes count when both views agree something moved. A jump between two
    near-identical framings of the same action still doesn't count; viewers don't read it
    as a new shot either."""
    coarse = _scene_scores(src, 48, 1.5)
    medium = _scene_scores(src, 270)
    candidates = sorted(t for t, sc in medium.items() if sc >= 7 and t > 0.1)
    pulses = _periodic(candidates)
    times, last = [], None
    for t in sorted(set(candidates) | {t for t, sc in coarse.items() if sc >= 5 and t > 0.1}):
        c = coarse.get(t, 0)
        is_cut = c >= 5 or (t not in pulses and t in candidates and c >= 2)
        if is_cut and (last is None or t - last >= min_gap):
            times.append(t)
            last = t
    return times


def silences(src, noise=-45, d=0.8):
    err = _stderr(["-i", src, "-vn", "-af", f"silencedetect=noise={noise}dB:d={d}", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", err)]
    return list(zip(starts, ends))


def blacks(src):
    err = _stderr(["-i", src, "-an", "-vf", "blackdetect=d=0.2:pix_th=0.08", "-f", "null", "-"])
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([0-9.]+) black_end:([0-9.]+)", err)]


def freezes(src, d=1.5):
    err = _stderr(["-i", src, "-an", "-vf", f"freezedetect=n=0.002:d={d}", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"freeze_start: ([0-9.]+)", err)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([0-9.]+)", err)]
    return list(zip(starts, ends + [None] * (len(starts) - len(ends))))


def analyze(src, kind="meme"):
    src = Path(src)
    t = KINDS[kind]
    info = ff.probe(src)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    dur = float(info["format"]["duration"])
    w, h = int(v["width"]), int(v["height"])
    cut_times = cuts(src)
    bounds = [0.0] + cut_times + [dur]
    shots = [b - a for a, b in zip(bounds, bounds[1:]) if b - a > 0.04]
    loud = measure(src) if has_audio else None
    quiet = [(a, b) for a, b in silences(src) if a > 0.3 and b < dur - 0.3] if has_audio else []
    report = {
        "file": src.name, "kind": kind, "duration_s": round(dur, 2), "size": f"{w}x{h}",
        "shots": len(shots), "first_cut_s": round(cut_times[0], 2) if cut_times else None,
        "avg_shot_s": round(sum(shots) / len(shots), 2), "longest_shot_s": round(max(shots), 2),
        "lufs": float(loud["input_i"]) if loud else None, "true_peak": float(loud["input_tp"]) if loud else None,
        "dead_air": [[round(a, 2), round(b, 2)] for a, b in quiet],
        "black": [[round(a, 2), round(b, 2)] for a, b in blacks(src)],
        "frozen": [[round(a, 2), round(b, 2) if b else None] for a, b in freezes(src)],
    }

    notes, score = [], 100

    def note(sev, rule, text):
        nonlocal score
        score -= {"fix": 15, "improve": 6, "info": 0}[sev]
        notes.append({"severity": sev, "rule": rule, "note": text})

    lo, hi = t["len"]
    if dur < lo:
        note("improve", "length", f"{dur:.1f}s is short for {kind}; {lo}-{hi}s gives the joke/story room to land.")
    elif dur > hi:
        note("improve", "length", f"{dur:.1f}s is long for {kind}; trim toward {hi}s. Cut the weakest shot first.")
    fc = report["first_cut_s"]
    if fc is None:
        note("fix", "hook", "No cuts detected. One unbroken shot loses short-form viewers; cut in the first second.")
    elif fc > t["hook"]:
        note("fix", "hook", f"First cut at {fc:.1f}s. Open with the strongest moment and cut by {t['hook']:.1f}s.")
    a_lo, a_hi = t["avg"]
    if report["avg_shot_s"] > a_hi:
        note("improve", "pacing", f"Average shot {report['avg_shot_s']:.1f}s is slow for {kind} (aim {a_lo}-{a_hi}s).")
    elif report["avg_shot_s"] < a_lo:
        note("improve", "pacing", f"Average shot {report['avg_shot_s']:.1f}s is frantic; let key moments breathe.")
    if report["longest_shot_s"] > t["max"]:
        i = max(range(len(shots)), key=lambda k: shots[k])
        note("improve", "pacing", f"Shot {i + 1} runs {shots[i]:.1f}s (starts {bounds[i]:.1f}s). Split it with a "
                                  "punch-in, a zoom_to, or a cutaway.")
    if loud:
        if abs(report["lufs"] + 14) > 1:
            note("fix", "loudness", f"{report['lufs']:.1f} LUFS; deliver at -14 (contentkit master FILE).")
        if report["true_peak"] > -1:
            note("fix", "loudness", f"True peak {report['true_peak']:.1f} dBTP; keep under -1 so encoders don't clip.")
    else:
        note("fix", "audio", "No audio track. Silent short-form video loses most viewers; add music or sound.")
    for a, b in quiet:
        note("improve", "dead air", f"Silence {a:.1f}-{b:.1f}s. Fill it (sfx, music) or cut it, unless it's the joke.")
    for a, b in report["black"]:
        note("fix", "black frames", f"Black frames {a:.1f}-{b:.1f}s.")
    for a, b in report["frozen"]:
        note("info", "freeze", f"Picture static {a:.1f}-{(b or dur):.1f}s. Fine for a freeze-frame gag; otherwise add motion.")
    # --- viral readiness: what decides watch-vs-skip and replays (proxies, not a predictor)
    from . import vision
    hook_frame = vision.frame_at(src, min(0.3, dur / 3))
    tx = vision.text(hook_frame)
    fc = vision.faces(hook_frame)
    move = vision.motion(vision.frame_at(src, 0.05), vision.frame_at(src, min(1.0, dur / 2)))
    loop = vision.similarity(vision.frame_at(src, 0.05), vision.frame_at(src, max(dur - 0.08, 0)))
    report["viral"] = {"hook_text": (tx or {}).get("text") or None if tx is not None else None,
                       "hook_face": vision.framing(fc) if fc is not None else None,
                       "first_second_motion": round(move, 1) if move is not None else None,
                       "loop_similarity": round(loop, 2) if loop is not None else None}
    if tx is not None and not tx["text"] and kind in ("meme", "commentary"):
        note("improve", "hook text", "No readable text on the first frame. Most viewers watch muted at "
                                     "first: put the setup line on frame 1 (header: or texts:).")
    if fc is not None and not fc and kind in ("commentary", "brand"):
        note("info", "hook face", "No face on the first frame; a face looking at camera stops the scroll best.")
    if move is not None and move < 4:
        note("improve", "hook motion", "The first second barely moves. Open on action, a zoom or a cut.")
    if loop is not None and loop > 0.85:
        note("info", "loop", "Last frame matches the first: the video loops cleanly (replays count as watch time).")
    elif loop is not None and kind in ("meme", "remix"):
        note("info", "loop", "Doesn't loop. Ending on a frame like the opening makes replays feel seamless.")

    # --- footage QC: soft or badly exposed shots
    for k, (a, b) in enumerate(zip(bounds, bounds[1:])):
        if b - a < 0.3 or k >= 30:
            continue
        fr = vision.frame_at(src, (a + b) / 2)
        sh, ex = vision.sharpness(fr), vision.exposure(fr)
        if sh is not None and sh < 40:
            note("improve", "focus", f"Shot at {a:.1f}s looks soft (sharpness {sh:.0f}); reshoot, or keep it short.")
        if ex and ex["clipped"] > 0.25:
            note("improve", "exposure", f"Shot at {a:.1f}s has {ex['clipped']:.0%} blown highlights.")
        if ex and ex["crushed"] > 0.45:
            note("improve", "exposure", f"Shot at {a:.1f}s is {ex['crushed']:.0%} crushed black; lift it "
                                        "(look: matte) or reshoot with more light.")

    if h < w and kind in ("meme", "remix"):
        note("improve", "format", f"{w}x{h} is landscape; Reels/TikTok/Shorts want 9:16 (format: reel).")
    if min(w, h) < 1080:
        note("improve", "resolution", f"{w}x{h}; deliver at least 1080 px on the short side.")
    report["score"] = max(score, 0)
    report["notes"] = notes
    return report


def render_text(r):
    lines = [f"{r['file']}  ·  {r['kind']}  ·  score {r['score']}/100", "",
             f"  length       {r['duration_s']}s   {r['size']}",
             f"  shots        {r['shots']}   first cut {r['first_cut_s']}s   avg {r['avg_shot_s']}s   "
             f"longest {r['longest_shot_s']}s"]
    if r["lufs"] is not None:
        lines.append(f"  loudness     {r['lufs']:.1f} LUFS   true peak {r['true_peak']:.1f} dBTP")
    v = r.get("viral") or {}
    if v:
        lines.append(f"  hook frame   text: {v['hook_text'] or '-'}   face: {v['hook_face'] or '-'}   "
                     f"motion 0-1s: {v['first_second_motion']}   loop: {v['loop_similarity']}")
    lines.append("")
    if not r["notes"]:
        lines.append("  No problems found.")
    for n in r["notes"]:
        mark = {"fix": "FIX    ", "improve": "IMPROVE", "info": "note   "}[n["severity"]]
        lines.append(f"  {mark} [{n['rule']}] {n['note']}")
    return "\n".join(lines)


def save(r, path):
    Path(path).write_text(json.dumps(r, indent=2))
