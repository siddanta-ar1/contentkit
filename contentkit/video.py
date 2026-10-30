"""Recipe -> finished social video.

Pipeline: render each scene to a uniform clip -> concat -> one final pass that burns
captions and mixes scene audio + voiceover + ducked music + timed SFX, mastered to
-14 LUFS. See examples/reel.yaml for every option.
"""
import tempfile
from pathlib import Path

from . import ff
from .captions import align_script, transcribe, write_ass
from .formats import LOUDNESS, get_format
from .post import compose, draw_text, theme_from
from .sfx import sfx_path
from .voice import synthesize

ZOOM = 0.12  # Ken Burns travel for image scenes


def _title_overlay(w, h, theme, scene, out):
    from PIL import Image
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pos = scene.get("title_position", "top")
    top = {"top": h * 0.1, "center": h * 0.35, "bottom": h * 0.55}[pos]
    m = round(w * 0.07)
    if scene.get("kicker"):
        draw_text(img, scene["kicker"].upper(), (m, top - h * 0.055, w - 2 * m, h * 0.045), theme["body_font"],
                  round(w * 0.045), color="#111111", highlight=theme["accent"], shadow=False)
    draw_text(img, scene["title"], (m, top, w - 2 * m, h * 0.22), theme["font"], round(w * 0.1),
              color=theme["text"], stroke=max(3, w // 260), valign="top")
    img.save(out)
    return out


def _cover(w, h, scale=1):
    return (f"scale={w * scale}:{h * scale}:force_original_aspect_ratio=increase,"
            f"crop={w * scale}:{h * scale},setsar=1")


def _render_scene(i, scene, fmt, theme, work):
    w, h, fps = fmt["w"], fmt["h"], fmt["fps"]
    dur = float(scene["duration"])
    frames = round(dur * fps)
    out = work / f"scene_{i:03d}.mp4"
    inputs, keep_audio = [], False

    if scene.get("video"):
        src = scene["video"]
        inputs += ["-ss", scene.get("start", 0), "-t", dur, "-i", src]
        vf = f"[0:v]{_cover(w, h)},fps={fps}"
        keep_audio = scene.get("keep_audio", False) and ff.has_audio(src)
    else:
        if scene.get("image"):
            still = scene["image"]
        else:  # text card on the theme background (or scene colour)
            card_theme = {**theme, **({"bg": scene["color"], "gradient": None, "image": None} if scene.get("color") else {})}
            still = work / f"card_{i:03d}.png"
            compose(w, h, card_theme, scene.get("title"), scene.get("body"),
                    scene.get("kicker")).convert("RGB").save(still)
            scene = {**scene, "title": None, "kicker": None}
        zoom = scene.get("zoom", "in" if scene.get("image") else "none")
        if zoom == "none":
            inputs += ["-loop", 1, "-framerate", fps, "-t", dur, "-i", still]
            vf = f"[0:v]{_cover(w, h)}"
        else:
            inputs += ["-i", still]
            z = {"in": f"1+{ZOOM}*on/{frames}", "out": f"{1 + ZOOM}-{ZOOM}*on/{frames}"}[zoom]
            # Upscale before zoompan so the slow zoom doesn't jitter.
            vf = (f"[0:v]{_cover(w, h, 2)},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                  f":d={frames}:s={w}x{h}:fps={fps}")

    if scene.get("fade"):
        vf += f",fade=t=in:st=0:d=0.25,fade=t=out:st={dur - 0.25}:d=0.25"
    vf += "[base]"
    graph = [vf]
    last = "[base]"
    if scene.get("title"):
        overlay = _title_overlay(w, h, theme, scene, work / f"title_{i:03d}.png")
        inputs += ["-loop", 1, "-t", dur, "-i", overlay]
        graph.append(f"[1:v]format=rgba,fade=t=in:st=0.1:d=0.3:alpha=1[t];{last}[t]overlay=0:0[v]")
        last = "[v]"

    audio_in = len([a for a in inputs if a == "-i"])
    if keep_audio:
        graph.append(f"[0:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={scene.get('volume', 1.0)}[a]")
    else:
        inputs += ["-f", "lavfi", "-t", dur, "-i", "anullsrc=r=44100:cl=stereo"]
        graph.append(f"[{audio_in}:a]anull[a]")

    ff.run([*inputs, "-filter_complex", ";".join(graph), "-map", last, "-map", "[a]",
            "-t", dur, "-r", fps, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", 44100, out])
    return out


def _plan_durations(scenes, voice_len):
    """Scenes without a duration share whatever voiceover time the timed scenes leave."""
    fixed = sum(float(s["duration"]) for s in scenes if s.get("duration"))
    open_scenes = [s for s in scenes if not s.get("duration")]
    if open_scenes:
        if not voice_len:
            raise SystemExit("Scenes without `duration` need a voiceover to size them.")
        share = max((voice_len + 0.4 - fixed) / len(open_scenes), 1.0)
        for s in open_scenes:
            s["duration"] = round(share, 2)
    return scenes


def render_video(recipe, out, workdir=None, log=print):
    fmt = get_format(recipe.get("format", "reel"))
    theme = theme_from(recipe.get("theme"))
    scenes = [dict(s) for s in recipe["scenes"]]
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(workdir or tempfile.mkdtemp(prefix="contentkit-")).resolve()
    work.mkdir(parents=True, exist_ok=True)

    # 1. Voiceover
    vo = recipe.get("voiceover") or {}
    voice_file, script = None, vo.get("text")
    if vo.get("file"):
        voice_file = Path(vo["file"])
    elif script:
        voice_file, engine = synthesize(script, work / "voice.wav", vo.get("engine", "auto"),
                                        vo.get("voice"), vo.get("speed", 1.0))
        log(f"voiceover: {engine}")
    voice_len = ff.duration(voice_file) if voice_file else 0
    voice_delay = float(vo.get("delay", 0.3)) if voice_file else 0

    # 2. Scenes
    _plan_durations(scenes, voice_len + voice_delay)
    clips = []
    for i, scene in enumerate(scenes):
        clips.append(_render_scene(i, scene, fmt, theme, work))
        log(f"scene {i + 1}/{len(scenes)} ({scene['duration']}s)")
    concat_list = work / "concat.txt"
    concat_list.write_text("".join(f"file '{c.name}'\n" for c in clips))
    joined = work / "joined.mp4"
    ff.run(["-f", "concat", "-safe", 0, "-i", concat_list, "-c", "copy", joined], cwd=work)
    total = sum(float(s["duration"]) for s in scenes)
    if voice_len + voice_delay > total + 0.05:
        log(f"warning: voiceover ({voice_len:.1f}s) is longer than the scenes ({total:.1f}s) and will be cut")

    # 3. Sound effects: per-scene cues plus an automatic transition sound on every cut
    cues, t = [], 0.0
    transition = recipe.get("transition_sfx", "whoosh")
    for i, scene in enumerate(scenes):
        if i and transition:
            cues.append((transition, max(t - 0.3, 0), recipe.get("transition_volume", 0.5)))
        for cue in scene.get("sfx", []):
            cue = {"name": cue} if isinstance(cue, str) else cue
            cues.append((cue["name"], t + float(cue.get("at", 0)), cue.get("volume", 0.8)))
        t += float(scene["duration"])

    # 4. Final pass: captions + audio mix + loudness
    inputs = ["-i", joined]
    graph, mix = [], ["[0:a]"]
    n = 1
    duck_key = None
    if voice_file:
        inputs += ["-i", voice_file.resolve()]
        ms = round(voice_delay * 1000)
        graph.append(f"[{n}:a]aformat=sample_rates=44100:channel_layouts=stereo,adelay={ms}|{ms},"
                     f"volume={vo.get('volume', 1.0)},asplit=2[vo][key]")
        mix.append("[vo]")
        duck_key = "[key]"
        n += 1
    music = recipe.get("music")
    if music:
        music = {"file": music} if isinstance(music, str) else music
        inputs += ["-stream_loop", -1, "-i", Path(music["file"]).resolve()]
        chain = (f"[{n}:a]aformat=sample_rates=44100:channel_layouts=stereo,atrim=0:{total},"
                 f"volume={music.get('volume', 0.3)},afade=t=in:d=0.5,afade=t=out:st={max(total - 1.5, 0)}:d=1.5")
        if duck_key and music.get("duck", True):
            graph.append(f"{chain}[mraw];[mraw]{duck_key}sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[mus]")
            duck_key = None
        else:
            graph.append(f"{chain}[mus]")
        mix.append("[mus]")
        n += 1
    if duck_key:  # voice split but nothing to duck
        graph.append(f"{duck_key}anullsink")
    for name, at, vol in cues:
        inputs += ["-i", sfx_path(name).resolve()]
        ms = round(at * 1000)
        graph.append(f"[{n}:a]aformat=sample_rates=44100:channel_layouts=stereo,adelay={ms}|{ms},volume={vol}[s{n}]")
        mix.append(f"[s{n}]")
        n += 1
    L = LOUDNESS
    graph.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,"
                 f"loudnorm=I={L['I']}:TP={L['TP']}:LRA={L['LRA']},aresample=44100[aout]")

    cap = recipe.get("captions", {"enabled": bool(voice_file)})
    cap = {"enabled": cap} if isinstance(cap, bool) else cap
    vmap = "0:v"
    if cap.get("enabled", True) and voice_file:
        words = None
        if cap.get("source", "auto") in ("auto", "whisper"):
            words = transcribe(voice_file, cap.get("model", "small"), cap.get("language"))
            if words:
                log("captions: faster-whisper")
        if not words and script:
            words = align_script(script, voice_len)
            log("captions: script timing (pip install faster-whisper for exact timing)")
        if words:
            words = [(s + voice_delay, e + voice_delay, txt) for s, e, txt in words]
            write_ass(words, work / "captions.ass", fmt["w"], fmt["h"], font=cap.get("font", theme["font"]),
                      color=cap.get("color", "#ffffff"), accent=cap.get("accent", theme["accent"]),
                      words_per_line=cap.get("words", 3), position=cap.get("position", 0.72),
                      uppercase=cap.get("uppercase", True))
            graph.append("[0:v]ass=captions.ass[vout]")
            vmap = "[vout]"

    ff.run([*inputs, "-filter_complex", ";".join(graph), "-map", vmap, "-map", "[aout]",
            "-c:v", "libx264", "-preset", recipe.get("preset", "medium"), "-crf", recipe.get("crf", 20),
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            "-t", total, out], cwd=work)
    log(f"done: {out} ({total:.1f}s, {fmt['w']}x{fmt['h']})")
    return out
