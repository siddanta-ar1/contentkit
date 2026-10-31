"""Recipe -> finished, delivery-ready social video.

Pipeline
  1. voiceover   TTS or recording, cleaned (EQ, de-ess, compression), words timed once
  2. scenes      each rendered to an identical intermediate (H.264 + PCM, BT.709):
                   image  - graded with the brand look, eased camera move around a focal point
                   video  - trimmed, crop-to-fill on a focal point, graded via the look's LUT
                   layout - any poster layout (stat, quote, swiss ...) as a full-frame scene
                   card   - a typographic title card
                 + animated title / lower third overlays
  3. join        hard cuts (lossless concat) or xfade transitions with matching audio crossfades
  4. mix         scene audio + voice + ducked music + timed SFX -> two-pass -14 LUFS master
  5. finish      captions (style presets, kept inside platform safe zones), film grain,
                 progress bar, H.264 High / BT.709 tags / faststart
  6. deliver     the same edit for every format in `deliver:`, plus SRT, thumbnail, cover
                 and a manifest.json describing every file

See examples/video/*.yaml for every option.
"""
import json
import re
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import audio, edits, ff, typo
from . import imagefx as fx
from .brand import load_brand
from .captions import STYLES, align_script, transcribe, write_ass, write_srt
from .fonts import FONT_DIR
from .formats import ENCODE, get_format, safe_zone
from .layouts import Page, _alpha, compose_page
from .sfx import sfx_path
from .voice import synthesize

XFADES = {"fade", "fadeblack", "fadewhite", "dissolve", "slideleft", "slideright", "slideup", "slidedown",
          "wipeleft", "wiperight", "wipeup", "wipedown", "smoothleft", "smoothright", "smoothup", "smoothdown",
          "circleopen", "circleclose", "zoomin", "hblur", "pixelize", "radial", "squeezeh", "squeezev"}
MOVES = {"none", "in", "out", "left", "right", "up", "down"}
TRAVEL = 0.12          # Ken Burns travel; more than ~15% reads as a slideshow effect


def _ease(p):
    """Smoothstep as an ffmpeg expression: moves start and land softly, like a real camera."""
    return f"(3*pow({p},2)-2*pow({p},3))"


def _luma(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# --- stills for scenes ---------------------------------------------------------------

def _insets(w, h, platform, caption_band=0):
    z = safe_zone(w, h, platform)
    return {**z, "bottom": max(z["bottom"], caption_band)}


def _card(scene, w, h, brand, platform, caption_band=0):
    """Typographic title card on the grid. Text colour follows the background's lightness."""
    bg = scene.get("color", brand.ink)
    fg = brand.ink if _luma(bg) > 0.55 else brand.paper
    p = Page(w, h, brand, insets=_insets(w, h, platform, caption_band))
    p.fill(bg)
    u = p.u
    st = p.display_style(fg, (17 if p.tall else 11) * u, em_color=brand.accent if bg != brand.accent else fg)
    title = typo.fit(scene.get("title", ""), st, p.span(0, 11), height=(p.bottom - p.top) * 0.45, max_lines=5)
    body = None
    if scene.get("body"):
        body = typo.layout(scene["body"], p.body_style(_alpha(fg, bg, 0.8), 3.0 * u), p.span(0, 10))
    lab = p.label_style(fg)
    kick_h = typo.cap_height(lab.font, lab.size) + 4 * u if scene.get("kicker") else 0
    block = kick_h + title.height + (5 * u + body.height if body else 0)
    y = p.top + (p.bottom - p.top - block) * 0.45
    if scene.get("kicker"):
        kc = brand.accent if abs(_luma(brand.accent) - _luma(bg)) > 0.25 else fg
        p.label(scene["kicker"], p.left, y, kc)
        y += kick_h
    y = typo.draw(p.draw, title, p.left, y)
    if body:
        typo.draw(p.draw, body, p.left, y + 5 * u)
    return p.img


def _alpha_ramp(h, top, bottom, strength=0.6):
    """Vertical alpha for a soft local scrim behind overlay text (eased both ends)."""
    y = np.arange(h, dtype=np.float32)
    pad = (bottom - top) * 0.6 + h * 0.05
    a = np.clip(np.minimum((y - (top - pad)) / pad, ((bottom + pad) - y) / pad), 0, 1)
    return (fx._smooth(a) * 255 * strength).astype(np.uint8)


def _title_overlay(scene, w, h, brand, platform, out):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    p = Page(w, h, brand, insets=safe_zone(w, h, platform))
    u = p.u
    st = p.display_style(brand.paper, (12 if p.tall else 9) * u, em_color=brand.paper)
    title = typo.fit(scene["title"], st, p.span(0, 11), height=(p.bottom - p.top) * 0.3, max_lines=3)
    lab = p.label_style(brand.paper)
    kick_h = typo.cap_height(lab.font, lab.size) + 3.6 * u if scene.get("kicker") else 0
    block = kick_h + title.height
    pos = scene.get("title_position", "top")
    top = {"top": p.top + 2 * u, "center": (p.top + p.bottom - block) / 2,
           "bottom": p.bottom - block - (22 * u if p.tall else 4 * u)}[pos]
    shade = Image.new("RGBA", (w, h), brand.ink)
    shade.putalpha(Image.fromarray(np.repeat(_alpha_ramp(h, top, top + block)[:, None], w, axis=1)))
    img.alpha_composite(shade)
    d = ImageDraw.Draw(img)
    if scene.get("kicker"):
        cap = typo.cap_height(lab.font, lab.size)
        d.rectangle((p.left, top + cap / 2 - p.hair, p.left + 3.2 * u, top + cap / 2 + p.hair), fill=brand.accent)
        typo.draw(d, typo.layout(scene["kicker"], lab, p.inner_w), p.left + 4.6 * u, top)
    typo.draw(d, title, p.left, top + kick_h)
    img.save(out)
    return out


def _lower_third(lt, w, h, brand, platform, out):
    """Name + role plate. Returns (png, x, y)."""
    p = Page(w, h, brand, insets=safe_zone(w, h, platform))
    u = p.u
    ns = p.body_style(brand.paper, (4.4 if p.tall else 3.4) * u, strong=True)
    name = typo.layout(lt.get("name", ""), ns, p.inner_w * 0.8)
    lab = p.label_style(_alpha(brand.paper, brand.ink, 0.72), (2.3 if p.tall else 1.75) * u)
    role = typo.layout(lt.get("role", ""), lab, p.inner_w * 0.8) if lt.get("role") else None
    pad, bar = 2.4 * u, max(3, round(0.55 * u))
    inner_h = name.height + (2.6 * u + role.height if role else 0)
    pw = round(max(name.width, role.width if role else 0) + 2 * pad + bar + pad * 0.6)
    ph = round(inner_h + 2 * pad)
    img = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, pw, ph), fill=brand.ink + "e6")
    d.rectangle((0, 0, bar - 1, ph), fill=brand.accent)
    x = bar + pad * 0.9
    y = typo.draw(d, name, x, pad)
    if role:
        typo.draw(d, role, x, y + 2.6 * u)
    img.save(out)
    y_pos = h * 0.56 - ph if p.tall else p.bottom - ph - 9 * u  # vertical: above the caption band
    return out, round(p.left), round(y_pos)


# --- scenes ---------------------------------------------------------------------------

def _scene_kind(scene):
    if scene.get("video"):
        return "video"
    if scene.get("layout"):
        return "layout"
    if scene.get("image"):
        return "image"
    return "card"


def _move_expr(move, frames, focus):
    p = f"min(on/{max(frames - 1, 1)},1)"
    e = _ease(p)
    fx_, fy_ = focus
    if move == "in":
        return f"1+{TRAVEL}*{e}", f"(iw-iw/zoom)*{fx_}", f"(ih-ih/zoom)*{fy_}"
    if move == "out":
        return f"{1 + TRAVEL}-{TRAVEL}*{e}", f"(iw-iw/zoom)*{fx_}", f"(ih-ih/zoom)*{fy_}"
    if move in ("left", "right", "up", "down"):
        t = e if move in ("right", "down") else f"(1-{e})"
        x = f"(iw-iw/zoom)*{t}" if move in ("left", "right") else f"(iw-iw/zoom)*{fx_}"
        y = f"(ih-ih/zoom)*{t}" if move in ("up", "down") else f"(ih-ih/zoom)*{fy_}"
        return f"{1 + TRAVEL}", x, y
    return None


def _render_scene(i, scene, fmt, brand, work, lut, platform, look, caption_band=0):
    w, h, fps = fmt["w"], fmt["h"], fmt["fps"]
    dur = float(scene["duration"])
    frames = round(dur * fps)
    out = work / f"scene_{i:03d}.mkv"
    kind = _scene_kind(scene)
    focus = tuple(scene.get("focus", (0.5, 0.5)))
    inputs, keep_audio = [], False

    pre_graph, n_in = [], 1
    if kind == "video":
        src = scene["video"]
        hdr = round(h * (0.24 if h > w else 0.18)) if scene.get("header") else 0
        vh = h - hdr
        inputs += ["-ss", scene.get("start", 0), "-t", f"{edits.source_seconds(scene, dur):.3f}", "-i", src]
        timing = ",".join(edits.timing_video(scene, fps))
        if scene.get("split"):
            pre_graph.append(f"[0:v]{timing}[raw]")
            s_in, s_graph, base, n_in = edits.split_graph(scene, w, vh, fps, dur, "[raw]", n_in, brand, work, i,
                                                          focus)
            inputs += s_in
            pre_graph += s_graph
            vf = f"{base}null"
        else:
            vf = (f"[0:v]{timing},scale={w}:{vh}:force_original_aspect_ratio=increase:flags=lanczos,"
                  f"crop={w}:{vh}:(iw-{w})*{focus[0]}:(ih-{vh})*{focus[1]},setsar=1")
        zoom = edits.zoom_filter(scene, w, vh, fps)
        if zoom:
            vf += "," + zoom
        if lut and scene.get("grade", True):
            vf += f",lut3d=file='{lut}':interp=tetrahedral"
        if hdr:
            png = edits.header_png(scene["header"], w, hdr, brand, work / f"header_{i:03d}.png")
            vf += f",pad={w}:{h}:0:{hdr}:color=white[hb];"
            inputs += ["-loop", 1, "-framerate", fps, "-t", dur, "-i", png]
            vf += f"[hb][{n_in}:v]overlay=0:0"
            n_in += 1
        keep_audio = scene.get("keep_audio", False) and ff.has_audio(src)
    else:
        still = work / f"still_{i:03d}.png"
        if kind == "image":
            img = Image.open(scene["image"])
            # grade the still once in numpy instead of every zoompan frame in ffmpeg
            img = fx.grade(img, scene.get("look", look)) if scene.get("grade", True) else img.convert("RGB")
            img.save(still)
        elif kind == "layout":
            compose_page({**scene, "brand": None}, w, h, brand=brand,
                         insets=_insets(w, h, platform, caption_band)).save(still)
        else:
            _card(scene, w, h, brand, platform, caption_band).save(still)
        default_move = "in" if kind == "image" else "none"
        move = scene.get("move", {"in": "in", "out": "out", "none": "none"}.get(scene.get("zoom"), default_move))
        if move not in MOVES:
            raise SystemExit(f"Unknown move '{move}'. Choose from: {', '.join(sorted(MOVES))}")
        expr = _move_expr(move, frames, focus)
        if expr:
            z, x, y = expr
            inputs += ["-i", still]
            # 2x oversample so sub-pixel motion stays smooth
            vf = (f"[0:v]scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase:flags=lanczos,"
                  f"crop={w * 2}:{h * 2}:(iw-{w * 2})*{focus[0]}:(ih-{h * 2})*{focus[1]},"
                  f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps}")
        else:
            inputs += ["-loop", 1, "-framerate", fps, "-t", dur, "-i", still]
            vf = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
                  f"crop={w}:{h}:(iw-{w})*{focus[0]}:(ih-{h})*{focus[1]},setsar=1")

    if scene.get("fade"):
        vf += f",fade=t=in:st=0:d=0.3,fade=t=out:st={dur - 0.3}:d=0.3"
    graph, last = pre_graph + [vf + "[base]"], "[base]"
    rise = round(min(w, h) * 0.025)
    p_in, p_graph, last, n_in = edits.pip_graph(scene, w, h, fps, dur, platform, last, n_in)
    inputs += p_in
    graph += p_graph
    if scene.get("title") and kind in ("image", "video"):
        png = _title_overlay(scene, w, h, brand, platform, work / f"title_{i:03d}.png")
        inputs += ["-loop", 1, "-framerate", fps, "-t", dur, "-i", png]
        p = "min(max(t-0.15,0)/0.6,1)"
        graph.append(f"[{n_in}:v]format=rgba,fade=t=in:st=0.15:d=0.5:alpha=1[t{n_in}];"
                     f"{last}[t{n_in}]overlay=x=0:y='{rise}*(1-{_ease(p)})'[o{n_in}]")
        last, n_in = f"[o{n_in}]", n_in + 1
    if scene.get("lower_third"):
        png, lx, ly = _lower_third(scene["lower_third"], w, h, brand, platform, work / f"lt_{i:03d}.png")
        inputs += ["-loop", 1, "-framerate", fps, "-t", dur, "-i", png]
        start, hold = 0.4, max(dur - 0.9, 0.8)
        p = f"min(max(t-{start},0)/0.5,1)"
        graph.append(f"[{n_in}:v]format=rgba,fade=t=in:st={start}:d=0.4:alpha=1,"
                     f"fade=t=out:st={start + hold - 0.4}:d=0.35:alpha=1[l{n_in}];"
                     f"{last}[l{n_in}]overlay=x='{lx}-{rise * 2}*(1-{_ease(p)})':y={ly}[o{n_in}]")
        last, n_in = f"[o{n_in}]", n_in + 1
    o_in, o_graph, last, n_in = edits.overlay_graph(scene, w, h, fps, dur, brand, platform, work, i, last, n_in)
    inputs += o_in
    graph += o_graph
    # RGB stills -> BT.709 limited range explicitly; swscale's default is BT.601, which
    # shifts colours once platforms re-encode.
    graph.append(f"{last}scale={w}:{h}:out_color_matrix=bt709:out_range=tv,format=yuv420p,setsar=1[v]")

    if keep_audio:
        graph += edits.timing_audio(scene, "[0:a]", dur, ENCODE["audio_rate"])
    else:
        inputs += ["-f", "lavfi", "-t", dur, "-i", f"anullsrc=r={ENCODE['audio_rate']}:cl=stereo"]
        graph.append(f"[{n_in}:a]anull[a]")
    ff.run([*inputs, "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]", "-t", dur, "-r", fps,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", 14, "-pix_fmt", "yuv420p",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-c:a", "pcm_s16le", out])
    return out


# --- timeline -------------------------------------------------------------------------

def _transition(recipe, scene):
    t = scene.get("transition", recipe.get("transition", "cut"))
    t = {"type": t} if isinstance(t, str) else dict(t or {"type": "cut"})
    if t["type"] != "cut" and t["type"] not in XFADES:
        raise SystemExit(f"Unknown transition '{t['type']}'. Use cut or one of: {', '.join(sorted(XFADES))}")
    t.setdefault("duration", 0.4)
    return t


def music_grid(recipe, log=print):
    """Analyse the music once (shared by every format): where to start it and its beat grid.
    music.start: seconds, or "hook" / "auto" for the most energetic part of the song."""
    music = recipe.get("music")
    if not music or isinstance(music, str):
        return None
    start = music.get("start", 0)
    if not (music.get("sync") or music.get("pulse") or start in ("auto", "hook")):
        return None
    from .beats import analyze
    seconds = float(recipe.get("duration") or 20)
    info = analyze(music["file"], 0, 240, music.get("bpm"), hook_window=min(max(seconds, 10), 30))
    start = info["hook"] if start in ("auto", "hook") else float(start)
    offset = (info["first_beat"] - start) % info["beat"]   # first beat inside the edit
    log(f"music: {info['bpm']:.1f} BPM, starting at {start:.2f}s"
        + (" (hook)" if music.get("start") in ("auto", "hook") else ""))
    return {"bpm": info["bpm"], "beat": info["beat"], "offset": offset, "start": start}


def plan(recipe, voice_end, fps=30, grid=None):
    """Fill open durations so the edit covers the voiceover (or the beat grid), and compute
    scene start times."""
    scenes = [dict(s) for s in recipe["scenes"]]
    for s in scenes:  # `beats: 4` sizes a scene musically (needs music with a beat grid)
        if s.get("beats") and not s.get("duration"):
            if not grid:
                raise SystemExit("`beats:` on a scene needs music with sync/pulse/start: hook")
            s["duration"] = float(s["beats"]) * grid["beat"]
    trans = [None] + [_transition(recipe, s) for s in scenes[1:]]
    # With any xfade in the edit the whole join goes through xfade, where a hard cut is a
    # one-frame fade: it overlaps by one frame, so the timeline must count it.
    mixed = any(t["type"] != "cut" for t in trans[1:])
    for t in trans[1:]:
        if t["type"] == "cut":
            t["duration"] = 1 / fps if mixed else 0.0
    overlap = sum(t["duration"] for t in trans[1:])
    fixed = sum(float(s["duration"]) for s in scenes if s.get("duration"))
    open_scenes = [s for s in scenes if not s.get("duration")]
    music = recipe.get("music") if isinstance(recipe.get("music"), dict) else {}
    sync = grid and music.get("sync")
    if open_scenes:
        if voice_end:
            share = max((voice_end + 0.6 - fixed + overlap) / len(open_scenes), 1.2)
        elif sync:
            share = grid["beat"] * float(music.get("beats_per_cut", 4 if sync == "bar" else 2))
        else:
            share = float(recipe.get("scene_duration", 2.5))
        for s in open_scenes:
            s["duration"] = round(share, 3)
    snap = lambda v: round(float(v) * fps) / fps
    for t in trans[1:]:
        t["duration"] = max(snap(t["duration"]), 1 / fps) if t["duration"] else 0.0
    if sync:
        # Cut on the beat: each scene lasts a whole number of beats (bars with sync: bar).
        # Cut times are placed on the exact grid first and only then rounded to frames, so
        # rounding never accumulates into drift; overlapping transitions are added back so
        # every incoming scene still starts on its beat.
        unit = grid["beat"] * (4 if sync == "bar" else 1)
        counts = [max(1, round(float(s["duration"]) / unit)) for s in scenes]
        cut = [grid["offset"]]
        for c in counts:
            cut.append(cut[-1] + c * unit)
        cut[0] = 0.0                     # the edit opens on frame 0
        frames = [round(c * fps) for c in cut]
        for i, s in enumerate(scenes):
            over = trans[i + 1]["duration"] if i + 1 < len(scenes) else 0.0
            s["duration"] = (frames[i + 1] - frames[i]) / fps + over
    # Snap everything to whole frames: rendered clips are frame-exact, the plan must be too.
    for s in scenes:
        s["duration"] = snap(s["duration"])
    starts, t = [], 0.0
    for i, s in enumerate(scenes):
        if i:
            t += float(scenes[i - 1]["duration"]) - trans[i]["duration"]
        starts.append(t)
    total = starts[-1] + float(scenes[-1]["duration"])
    return scenes, trans, starts, total


def _join(clips, trans, starts, fmt, work):
    joined = work / "joined.mkv"
    if all(t is None or t["type"] == "cut" for t in trans):
        lst = work / "concat.txt"
        lst.write_text("".join(f"file '{c.name}'\n" for c in clips))
        ff.run(["-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", joined], cwd=work)
        return joined
    inputs, graph = [], []
    for c in clips:
        inputs += ["-i", c.name]
    v, a = "[0:v]", "[0:a]"
    for i in range(1, len(clips)):
        t = trans[i]
        kind, d = ("fade" if t["type"] == "cut" else t["type"]), t["duration"]
        graph.append(f"{v}[{i}:v]xfade=transition={kind}:duration={d:.4f}:offset={starts[i]:.4f}[v{i}]")
        graph.append(f"{a}[{i}:a]acrossfade=d={d:.4f}:c1=tri:c2=tri[a{i}]")
        v, a = f"[v{i}]", f"[a{i}]"
    ff.run([*inputs, "-filter_complex", ";".join(graph), "-map", v, "-map", a, "-c:v", "libx264",
            "-preset", "veryfast", "-crf", 14, "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", joined], cwd=work)
    return joined


# --- audio ----------------------------------------------------------------------------

def prepare_voice(recipe, work, log=print):
    """Synthesize/clean the voiceover and time its words once (shared by every deliverable)."""
    vo = recipe.get("voiceover") or {}
    script = vo.get("text")
    if not (vo.get("file") or script):
        return None, 0.0, 0.0, None
    if vo.get("file"):
        raw = Path(vo["file"])
    else:
        raw, engine = synthesize(script, work / "voice_raw.wav", vo.get("engine", "auto"), vo.get("voice"),
                                 vo.get("speed", 1.0))
        log(f"voiceover: {engine}")
    voice = raw
    clean = vo.get("clean", "normal" if vo.get("file") else "light")
    if clean:
        voice = audio.clean_voice(raw, work / "voice.wav", clean)
    length = ff.duration(voice)
    delay = float(vo.get("delay", 0.3))

    cap = recipe.get("captions", True)
    cap = {"enabled": cap} if isinstance(cap, bool) else cap
    words = None
    if cap.get("enabled", True) or recipe.get("srt") or recipe.get("deliver"):
        if cap.get("source", "auto") in ("auto", "whisper"):
            words = transcribe(voice, cap.get("model", "small"), cap.get("language"))
            if words:
                log("captions: faster-whisper word timing")
        if not words and script:
            words = align_script(script, length)
            log("captions: script timing (pip install faster-whisper for exact timing)")
        if words:
            words = [(s + delay, e + delay, t) for s, e, t in words]
    return voice, length, delay, words


def _mix(recipe, joined, voice, delay, cues, total, work, grid=None):
    inputs, graph, mix, n = ["-i", joined], [], ["[0:a]"], 1
    rate = ENCODE["audio_rate"]
    fmt = f"aformat=sample_rates={rate}:channel_layouts=stereo"
    vo = recipe.get("voiceover") or {}
    duck_key = None
    if voice:
        ms = round(delay * 1000)
        inputs += ["-i", Path(voice).resolve()]
        graph.append(f"[{n}:a]{fmt},adelay={ms}|{ms},volume={vo.get('volume', 1.0)},asplit=2[vo][key]")
        mix.append("[vo]")
        duck_key, n = "[key]", n + 1
    music = recipe.get("music")
    if music:
        music = {"file": music} if isinstance(music, str) else music
        start = grid["start"] if grid else float(music.get("start", 0) or 0)
        inputs += ["-stream_loop", -1, "-ss", f"{start:.3f}", "-i", Path(music["file"]).resolve()]
        # synced edits start on a downbeat: a long fade-in would smear the first hit
        fade_in = music.get("fade_in", 0.02 if grid else 0.6)
        chain = (f"[{n}:a]{fmt},atrim=0:{total},volume={music.get('volume', 0.3)},"
                 f"afade=t=in:d={fade_in},afade=t=out:st={max(total - 1.8, 0)}:d=1.8")
        if duck_key and music.get("duck", True):
            graph.append(f"{chain}[mraw];[mraw]{duck_key}sidechaincompress=threshold=0.02:ratio=10:attack=15:"
                         f"release=350[mus]")
            duck_key = None
        else:
            graph.append(f"{chain}[mus]")
        mix.append("[mus]")
        n += 1
    if duck_key:
        graph.append(f"{duck_key}anullsink")
    for name, at, vol in cues:
        inputs += ["-i", sfx_path(name).resolve()]
        ms = round(max(at, 0) * 1000)
        graph.append(f"[{n}:a]{fmt},adelay={ms}|{ms},volume={vol}[s{n}]")
        mix.append(f"[s{n}]")
        n += 1
    graph.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,alimiter=limit=0.95[aout]")
    raw = work / "mix_raw.wav"
    ff.run([*inputs, "-filter_complex", ";".join(graph), "-map", "[aout]", "-t", total, "-ar", rate,
            "-c:a", "pcm_s24le", raw], cwd=work)
    return raw


def _cues(recipe, scenes, trans, starts, grid=None):
    cues = []
    # on a beat-synced edit the song is the transition; a whoosh only fights it
    tsfx = recipe.get("transition_sfx", None if grid else "whoosh")
    for i, scene in enumerate(scenes):
        if i and tsfx:
            lead = 0.3 if trans[i]["type"] == "cut" else 0.2
            cues.append((tsfx, starts[i] - lead, recipe.get("transition_volume", 0.45)))
        for cue in scene.get("sfx", []):
            cue = {"name": cue} if isinstance(cue, str) else cue
            cues.append((cue["name"], starts[i] + float(cue.get("at", 0)), cue.get("volume", 0.8)))
        for name, at, vol in edits.auto_cues(scene):
            cues.append((name, starts[i] + at, vol))
    return cues


# --- render ---------------------------------------------------------------------------

def _caption_cfg(recipe, brand):
    cap = recipe.get("captions", True)
    cap = {"enabled": cap} if isinstance(cap, bool) else dict(cap)
    return {**(brand.captions or {}), **cap}


def render_format(recipe, fmt_name, out, work, brand, voice_pack, log=print, grid=None):
    fmt = get_format(fmt_name)
    w, h = fmt["w"], fmt["h"]
    voice, voice_len, delay, words = voice_pack
    platform = recipe.get("platform", "universal")
    look = recipe.get("look", brand.look)
    lut = fx.lut_for(look, work)
    scenes, trans, starts, total = plan(recipe, voice_len + delay if voice else 0, fmt["fps"], grid)
    if voice and voice_len + delay > total + 0.05:
        log(f"warning: voiceover ({voice_len:.1f}s) runs past the edit ({total:.1f}s) and will be cut")

    cap = _caption_cfg(recipe, brand)
    show_caps = bool(cap.get("enabled", True) and words)
    style = cap.get("style", "pop")
    cap_size = round(w * STYLES[style]["size"])
    zone = safe_zone(w, h, platform)
    cap_pos = cap.get("position", 1 - (zone["bottom"] + cap_size * 1.6) / h if zone["bottom"] else 0.86)
    # layouts and cards keep their type above the caption band (two caption lines + air)
    band = round(h * (1 - cap_pos) + cap_size * 2.4) if show_caps else 0

    clips = []
    for i, scene in enumerate(scenes):
        clips.append(_render_scene(i, scene, fmt, brand, work, lut, platform, look, band))
        log(f"  [{fmt_name}] scene {i + 1}/{len(scenes)}  {_scene_kind(scene):<6} {float(scene['duration']):.2f}s")
    joined = _join(clips, trans, starts, fmt, work)
    got = ff.duration(joined)
    if abs(got - total) > 2 / fmt["fps"]:
        raise RuntimeError(f"joined timeline is {got:.2f}s, expected {total:.2f}s (transition longer than a scene?)")

    raw = _mix(recipe, joined, voice, delay, _cues(recipe, scenes, trans, starts, grid), total, work, grid)
    loud = audio.master(raw, work / "mix.wav")

    vf = []
    pulse = (recipe.get("music") or {}).get("pulse") if isinstance(recipe.get("music"), dict) else None
    if pulse and grid:
        # zoom kick on every beat, decaying over ~100 ms; captions are added after, so they stay still
        amt = 0.035 if pulse is True else float(pulse)
        z = f"(1+{amt}*exp(-mod(t-{grid['offset']:.4f}+{grid['beat']:.5f}*8,{grid['beat']:.5f})*14))"
        vf.append(f"scale=w='trunc(iw*{z}/2)*2':h='trunc(ih*{z}/2)*2':eval=frame:flags=bicubic,crop={w}:{h}")
    if show_caps:
        write_ass(words, work / "captions.ass", w, h, font=cap.get("font"), color=cap.get("color", "#ffffff"),
                  accent=cap.get("accent", brand.accent), words_per_line=cap.get("words"),
                  position=cap_pos, uppercase=cap.get("uppercase"), style=style, box_color=brand.ink)
        vf.append(f"ass=captions.ass:fontsdir='{FONT_DIR}'")
    grain = recipe.get("grain", brand.grain)
    if grain:
        vf.append(f"noise=c0s={min(round(grain * 160), 16)}:c0f=t")
    if recipe.get("progress"):
        bar = max(4, round(h / 320))
        y = 0 if recipe["progress"] != "bottom" else h - bar
        vf.append(f"drawbox=x=0:y={y}:w=iw*t/{total:.3f}:h={bar}:color={brand.accent}@1:t=fill")
    vf.append("format=yuv420p")

    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    ff.run(["-i", joined, "-i", work / "mix.wav", "-map", "0:v", "-map", "1:a", "-vf", ",".join(vf),
            "-c:v", "libx264", "-profile:v", "high", "-preset", recipe.get("preset", "medium"),
            "-crf", recipe.get("crf", ENCODE["crf"]), "-maxrate", ENCODE["maxrate"], "-bufsize", ENCODE["bufsize"],
            "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-color_range", "tv", "-c:a", "aac", "-b:a", ENCODE["audio_bitrate"], "-ar", ENCODE["audio_rate"],
            "-movflags", "+faststart", "-t", f"{total:.3f}", out], cwd=work)
    log(f"  [{fmt_name}] {out.name}  {total:.1f}s  {w}x{h}  {loud['integrated_lufs']} LUFS / "
        f"{loud['true_peak_dbtp']} dBTP")
    return {"file": out.name, "format": fmt_name, "width": w, "height": h, "fps": fmt["fps"],
            "duration_s": round(total, 3), "size_mb": round(out.stat().st_size / 1e6, 2), **loud}


def _thumbnail(recipe, brand, out_dir, stem, formats):
    """Poster-layout thumbnail (16:9) and vertical cover from the same spec."""
    spec = recipe.get("thumbnail")
    if not spec:
        return []
    if spec is True:
        first = next((s for s in recipe["scenes"] if s.get("image")), None)
        if not first:
            return []
        spec = {"layout": "editorial", "image": first["image"], "focus": first.get("focus", (0.5, 0.5)),
                "title": recipe.get("title") or first.get("title", ""), "kicker": first.get("kicker")}
    spec = dict(spec)
    spec.setdefault("layout", "editorial")
    made = []
    targets = [("thumbnail", f"{stem}-thumbnail.jpg")]
    if "reel" in formats:
        targets.append(("reel", f"{stem}-cover.jpg"))
    for fmt_name, name in targets:
        fmt = get_format(fmt_name)
        img = compose_page({**spec, "brand": None}, fmt["w"], fmt["h"], brand=brand,
                           platform=recipe.get("platform", "universal"))
        img.save(out_dir / name, quality=93, subsampling=0)
        made.append(name)
    return made


def render_video(recipe, out, workdir=None, log=print):
    """Render one video, or every format in `deliver:` (out is then a folder or base name)."""
    brand = load_brand(recipe.get("brand"))
    base_work = Path(workdir or tempfile.mkdtemp(prefix="contentkit-")).resolve()
    base_work.mkdir(parents=True, exist_ok=True)
    voice_pack = prepare_voice(recipe, base_work, log)
    grid = music_grid(recipe, log)
    out = Path(out)
    formats = recipe.get("deliver")

    if not formats:
        render_format(recipe, recipe.get("format", "reel"), out, base_work, brand, voice_pack, log, grid)
        if recipe.get("srt") and voice_pack[3]:
            write_srt(voice_pack[3], out.with_suffix(".srt"))
        return out.resolve()

    out_dir = out if not out.suffix else out.parent / out.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = recipe.get("name") or (out.stem if out.suffix else out.name)
    stem = re.sub(r"[^\w.-]+", "-", stem).strip("-").lower()  # "hotel-Yak & Yeti" -> "hotel-yak-yeti"
    files = []
    for fmt_name in formats:
        work = base_work / fmt_name
        work.mkdir(exist_ok=True)
        files.append(render_format(recipe, fmt_name, out_dir / f"{stem}-{fmt_name}.mp4", work, brand,
                                   voice_pack, log, grid))
    extras = {}
    if voice_pack[3]:
        extras["captions_srt"] = write_srt(voice_pack[3], out_dir / f"{stem}.srt").name
    images = _thumbnail(recipe, brand, out_dir, stem, formats)
    if images:
        extras["images"] = images
    manifest = {"name": stem, "brand": brand.name, "look": recipe.get("look", brand.look),
                "music": {k: round(v, 3) for k, v in grid.items()} if grid else None,
                "videos": files, **extras,
                "spec": {"video": "H.264 High, yuv420p, BT.709, CRF 18 capped at 16 Mb/s (VBV 16M), faststart",
                         "audio": "AAC 256 kb/s, 48 kHz, two-pass loudnorm to -14 LUFS / -1 dBTP"}}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    log(f"delivered {len(files)} videos + {len(extras.get('images', []))} images to {out_dir}")
    return out_dir.resolve()
