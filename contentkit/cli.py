"""contentkit command line. `contentkit <command> -h` for options.

Design      poster, post, print, looks, layouts, brand, safezone
Video       video, template, cut, captions, proof, analyze
Audio       beats, clean, master, tts, sfx
Assets      fetch, formats
Setup       skill, private
"""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from . import ff, sfx
from .formats import FORMATS

PATH_KEYS = ("image", "video", "file", "logo", "brand", "look", "voice", "lut", "music")


def _load(path):
    path = Path(path)
    data = yaml.safe_load(path.read_text())
    base = path.parent.resolve()

    # Resolve relative asset paths against the recipe's folder so recipes are portable.
    def fix(node):
        if isinstance(node, dict):
            return {k: (str((base / v).resolve()) if k in PATH_KEYS and isinstance(v, str)
                        and not Path(v).is_absolute() and (base / v).is_file() else fix(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [fix(v) for v in node]
        return node
    return fix(data)


def cmd_sfx(a):
    if a.action == "init":
        names = sfx.build_sfx_pack(force=a.force)
        print(f"{len(names)} sounds in {sfx.LIBRARY}:\n  " + ", ".join(names))
    elif a.action == "list":
        for name, meta in sorted(sfx.list_sfx().items()):
            print(f"{name:<16} {meta['license']:<28} {meta.get('source', '')}")
    elif a.action == "add":
        print(sfx.add_sfx(a.target, a.name, a.source or "", a.license or ""))
    elif a.action == "play":
        player = shutil.which("ffplay")
        subprocess.run([player, "-autoexit", "-nodisp", "-loglevel", "error", str(sfx.sfx_path(a.target))])


def _poster(spec, output, recipe_path):
    from .layouts import render_carousel, render_poster
    if spec.get("slides"):
        for p in render_carousel(spec, output or Path(recipe_path).stem):
            print(p)
    else:
        print(render_poster(spec, output or Path(recipe_path).with_suffix(".jpg").name))


def cmd_post(a):
    spec = _load(a.recipe)
    if spec.get("layout") or any(s.get("layout") for s in spec.get("slides", [])):
        return _poster(spec, a.output, a.recipe)
    from .post import render_carousel, render_post  # classic single-card engine
    if spec.get("slides"):
        for p in render_carousel(spec, a.output or Path(a.recipe).stem):
            print(p)
    else:
        print(render_post(spec, a.output or Path(a.recipe).with_suffix(".png").name))


def cmd_poster(a):
    spec = _load(a.recipe)
    if a.format:
        spec["format"] = a.format
    if a.layout:
        spec["layout"] = a.layout
    _poster(spec, a.output, a.recipe)


def cmd_print(a):
    from .printing import export_print
    spec = _load(a.recipe)
    base = a.output or Path(a.recipe).stem + f"-{a.size}"
    for f in export_print(spec, base, a.size, a.dpi, a.orientation, not a.no_marks, a.icc):
        print(f)


def cmd_video(a):
    from .video import render_video
    recipe = _load(a.recipe)
    if a.only:
        recipe["deliver"] = a.only.split(",")
    render_video(recipe, a.output or Path(a.recipe).stem, workdir=a.keep)


def cmd_cut(a):
    from .audio import silence_cut
    out = a.output or str(Path(a.input).with_name(Path(a.input).stem + "_cut" + Path(a.input).suffix))
    silence_cut(a.input, out, a.threshold, a.min_silence, a.pad, a.punch)
    print(out)


def cmd_clean(a):
    from .audio import clean_voice, master
    out = Path(a.output or Path(a.input).with_name(Path(a.input).stem + "_clean.wav"))
    clean_voice(a.input, out, a.strength)
    if a.master:
        print(master(out, out.with_name(out.stem + "_mastered.wav")))
    print(out)


def cmd_master(a):
    from .audio import master
    out = a.output or str(Path(a.input).with_name(Path(a.input).stem + "_master.wav"))
    print(json.dumps(master(a.input, out, {"I": a.lufs, "TP": a.tp, "LRA": 11}), indent=2))
    print(out)


def cmd_proof(a):
    from .proof import image_board, video_sheet
    paths = [Path(p) for p in a.inputs]
    if len(paths) == 1 and paths[0].suffix.lower() in (".mp4", ".mov", ".mkv", ".webm"):
        print(video_sheet(paths[0], a.output or paths[0].with_name(paths[0].stem + "-proof.jpg"), a.frames,
                          brand=a.brand))
    else:
        files = [f for p in paths for f in (sorted(p.glob("*.[jp][pn]g")) if p.is_dir() else [p])]
        print(image_board(files, a.output or "board.jpg", a.cols, brand=a.brand, title=a.title))


def cmd_safezone(a):
    from PIL import Image, ImageDraw
    from .formats import SAFE_ZONES, safe_zone
    src = Path(a.input)
    if src.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm"):
        from .proof import _frame
        img = _frame(src, a.at, ff.probe(src)["streams"][0].get("width") or 1080)
    else:
        img = Image.open(src).convert("RGB")
    w, h = img.size
    platforms = list(SAFE_ZONES) if a.platform == "all" else [a.platform]
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    colors = [(230, 30, 60), (0, 160, 255), (255, 170, 0), (60, 200, 120), (180, 80, 255)]
    for i, name in enumerate(platforms):
        z = safe_zone(w, h, name)
        c = colors[i % len(colors)]
        if len(platforms) == 1:
            for box in ((0, 0, w, z["top"]), (0, h - z["bottom"], w, h), (0, 0, z["left"], h), (w - z["right"], 0, w, h)):
                d.rectangle(box, fill=c + (90,))
        d.rectangle((z["left"], z["top"], w - z["right"], h - z["bottom"]), outline=c + (255,), width=max(2, w // 360))
        from .typo import Style, draw as tdraw, layout as tlayout
        st = Style("IBM Plex Mono:medium", max(14, w // 50), tracking=40, upper=True, color="#%02x%02x%02x" % c)
        y = w // 40 + i * st.size * 1.6
        d.rectangle((w // 40 - 6, y - 6, w // 40 + st.size * 9, y + st.size * 1.1), fill=(0, 0, 0, 150))
        tdraw(d, tlayout(name, st, w), w // 40, y)
    img = Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")
    out = a.output or str(src.with_name(src.stem + "-safezone.jpg"))
    img.save(out, quality=90)
    print(out, " ".join(platforms))


def cmd_looks(a):
    from . import imagefx as fx
    if a.preview:
        from PIL import Image
        src = Image.open(a.preview)
        src.thumbnail((640, 640))
        names = list(fx.LOOKS)
        cols = 5
        sheet = Image.new("RGB", (src.width * cols, src.height * ((len(names) + cols - 1) // cols)), "white")
        for i, n in enumerate(names):
            sheet.paste(fx.grade(src, n), ((i % cols) * src.width, (i // cols) * src.height))
        out = a.output or "looks.jpg"
        sheet.save(out, quality=90)
        print(out, "  order:", ", ".join(names))
    elif a.export:
        print(fx.write_cube(a.export, a.output or f"{a.export}.cube"))
    else:
        print("\n".join(fx.LOOKS))


def cmd_layouts(a):
    from .layouts import LAYOUTS, REQUIRED
    for name, fn in LAYOUTS.items():
        print(f"{name:<10} needs {', '.join(REQUIRED[name]):<14} {fn.__doc__.strip().splitlines()[0]}")


def cmd_brand(a):
    from .brand import PRESETS, load_brand
    if a.action == "init":
        out = Path(a.output or "brand.yaml")
        if out.exists():
            raise SystemExit(f"{out} exists; not overwriting")
        b = load_brand(a.preset)
        data = {"name": a.name or "Your Brand", "handle": "@yourbrand", "url": "yourbrand.com",
                "colors": b.colors, "type": b.type, "look": b.look, "grain": b.grain,
                "captions": {"style": "clean"}}
        out.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        print(out)
    else:
        print("presets:", ", ".join(PRESETS))


def cmd_tts(a):
    from .voice import synthesize
    path, engine = synthesize(a.text, a.output, a.engine, a.voice, a.speed)
    print(f"{path} ({engine}, {ff.duration(path):.1f}s)")


def cmd_captions(a):
    from .captions import align_script, transcribe, write_ass, write_srt
    from .fonts import FONT_DIR
    src = Path(a.input).resolve()
    words = transcribe(src, a.model) if not a.text else None
    if not words:
        if not a.text:
            raise SystemExit("Install faster-whisper (pip install faster-whisper) or pass --text with the script.")
        words = align_script(a.text, ff.duration(src))
    if a.srt:
        print(write_srt(words, src.with_suffix(".srt")))
    v = next(s for s in ff.probe(src)["streams"] if s["codec_type"] == "video")
    out = Path(a.output or src.with_name(src.stem + "_captioned.mp4")).resolve()
    with tempfile.TemporaryDirectory(prefix="contentkit-cap-") as tmp:
        work = Path(tmp)
        write_ass(words, work / "captions.ass", v["width"], v["height"], accent=a.accent,
                  words_per_line=a.words, style=a.style)
        ff.run(["-i", src, "-vf", f"ass=captions.ass:fontsdir='{FONT_DIR}'", "-c:v", "libx264", "-crf", 18,
                "-pix_fmt", "yuv420p", "-c:a", "copy", out], cwd=work)
    print(out)


def cmd_fetch(a):
    from .fetch import download, library
    if a.list is not None:
        for e in library(a.list or None):
            print(f"{e['file']}\n    {e.get('title')}  ·  {e.get('uploader')}  ·  {e.get('duration_s')}s")
        return
    start = end = None
    if a.section:
        start, end = a.section.split("-")
    path, meta = download(a.url, a.audio, a.out, a.license or "", start, end, search=a.search,
                          browser=a.browser, cookies=a.cookies)
    print(f"{path}\n{json.dumps(meta, indent=2, ensure_ascii=False)}")


def cmd_analyze(a):
    from .analyze import analyze, render_text, save
    r = analyze(a.video, a.kind)
    print(render_text(r))
    if a.json:
        save(r, a.json)


def cmd_beats(a):
    from .beats import analyze
    info = analyze(a.song, 0, 240, a.bpm, hook_window=a.window)
    bar = 4 * info["beat"]
    print(f"bpm         {info['bpm']:.1f}\nbeat        {info['beat']:.3f}s   bar {bar:.3f}s\n"
          f"first beat  {info['first_beat']:.3f}s\nhook        {info['hook']:.2f}s  "
          f"(most energetic {a.window:g}s, on a downbeat; use music.start: hook)")


def cmd_private(a):
    from . import config
    if a.state != "status":
        config.set_value("private", a.state == "on")
    on = config.private()
    print(f"private mode {'ON' if on else 'off'}: downloads are labelled "
          + ("'private use (local only)'" if on else "'UNKNOWN' until you record a license"))


def cmd_skill(a):
    src = Path(__file__).parent / "skill" / "SKILL.md"
    if a.action == "show":
        print(src.read_text())
        return
    base = Path.home() / ".claude" if a.target == "global" else Path(a.target).expanduser() / ".claude"
    dest = base / "skills" / "contentkit" / "SKILL.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print(f"installed {dest}\nAsk Claude Code for a video, reel or poster there and it will use contentkit.")


def cmd_template(a):
    tdir = Path(__file__).parent / "templates"
    if a.action == "list":
        for t in sorted(tdir.glob("*.yaml")):
            first = t.read_text().splitlines()[0].lstrip("# ")
            print(f"{t.stem:<16} {first}")
        return
    src = tdir / f"{a.name}.yaml"
    if not src.exists():
        raise SystemExit(f"No template '{a.name}'. contentkit template list")
    dest = Path(a.dest or a.name)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "media").mkdir(exist_ok=True)
    recipe = dest / "recipe.yaml"
    if recipe.exists():
        raise SystemExit(f"{recipe} exists; not overwriting")
    shutil.copy2(src, recipe)
    print(f"{recipe}\n{dest / 'media'}/   <- put photos and clips here, then fill the <...> values")


def main(argv=None):
    p = argparse.ArgumentParser(prog="contentkit", description="Open-source content studio: posters, print, video, audio")
    sub = p.add_subparsers(dest="cmd", required=True)

    def cmd(name, fn, help):
        s = sub.add_parser(name, help=help, description=help)
        s.set_defaults(fn=fn)
        return s

    s = cmd("poster", cmd_poster, "render a poster/carousel from a layout recipe")
    s.add_argument("recipe")
    s.add_argument("-o", "--output")
    s.add_argument("--format", help="override: square, portrait, reel, landscape, thumbnail, og")
    s.add_argument("--layout", help="override the recipe's layout")

    s = cmd("post", cmd_post, "render a post (layout recipes, or the classic single-card engine)")
    s.add_argument("recipe")
    s.add_argument("-o", "--output")

    s = cmd("print", cmd_print, "print-ready PDF + CMYK TIFF + proof with bleed and crop marks")
    s.add_argument("recipe")
    s.add_argument("-o", "--output", help="base name (no extension)")
    s.add_argument("--size", default="a3", help="a5 a4 a3 a2 a1 letter tabloid 18x24 24x36")
    s.add_argument("--dpi", type=int, default=300)
    s.add_argument("--orientation", default="portrait", choices=["portrait", "landscape"])
    s.add_argument("--icc", default="fogra39", help="fogra39 | fogra47 | gracol | swop | path to .icc")
    s.add_argument("--no-marks", action="store_true")

    s = cmd("video", cmd_video, "render a video (or every format in `deliver:`)")
    s.add_argument("recipe")
    s.add_argument("-o", "--output")
    s.add_argument("--only", help="comma-separated formats to render from `deliver:`")
    s.add_argument("--keep", metavar="DIR", help="keep intermediates in DIR")

    s = cmd("cut", cmd_cut, "jump-cut a talking-head recording: remove pauses, optional punch-in")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    s.add_argument("--threshold", type=float, default=-32, help="silence level in dB (default -32)")
    s.add_argument("--min-silence", type=float, default=0.45, help="shortest pause to remove (s)")
    s.add_argument("--pad", type=float, default=0.12, help="audio kept either side of each cut (s)")
    s.add_argument("--punch", type=float, default=1.0, help="zoom on alternate cuts, e.g. 1.1")

    s = cmd("clean", cmd_clean, "voice cleanup: rumble, noise, mud, presence, de-ess, compression")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    s.add_argument("--strength", default="normal", choices=["normal", "light"])
    s.add_argument("--master", action="store_true", help="also write a -14 LUFS master")

    s = cmd("master", cmd_master, "two-pass loudness master (default -14 LUFS / -1 dBTP)")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    s.add_argument("--lufs", type=float, default=-14)
    s.add_argument("--tp", type=float, default=-1.0)

    s = cmd("proof", cmd_proof, "client review sheet: timecoded frames of a video, or a board of images")
    s.add_argument("inputs", nargs="+")
    s.add_argument("-o", "--output")
    s.add_argument("--frames", type=int, default=12)
    s.add_argument("--cols", type=int, default=4)
    s.add_argument("--brand")
    s.add_argument("--title", default="Board")

    s = cmd("safezone", cmd_safezone, "overlay platform UI safe zones on an image or video frame")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    s.add_argument("--platform", default="all", help="all | universal | reels | tiktok | shorts | stories")
    s.add_argument("--at", type=float, default=1.0, help="video timestamp (s)")

    s = cmd("looks", cmd_looks, "list colour looks, preview them on a photo, or export one as .cube")
    s.add_argument("--preview", metavar="IMAGE")
    s.add_argument("--export", metavar="LOOK")
    s.add_argument("-o", "--output")

    s = cmd("layouts", cmd_layouts, "list poster layouts")

    s = cmd("brand", cmd_brand, "create a brand kit (brand.yaml) from a preset")
    s.add_argument("action", choices=["init", "presets"])
    s.add_argument("--preset", default="editorial")
    s.add_argument("--name")
    s.add_argument("-o", "--output")

    s = cmd("sfx", cmd_sfx, "sound effects library")
    s.add_argument("action", choices=["init", "list", "add", "play"])
    s.add_argument("target", nargs="?")
    s.add_argument("--name")
    s.add_argument("--source")
    s.add_argument("--license")
    s.add_argument("--force", action="store_true")

    s = cmd("tts", cmd_tts, "text to speech")
    s.add_argument("text")
    s.add_argument("-o", "--output", default="voice.wav")
    s.add_argument("--engine", default="auto", choices=["auto", "piper", "espeak"])
    s.add_argument("--voice")
    s.add_argument("--speed", type=float, default=1.0)

    s = cmd("captions", cmd_captions, "burn styled word-by-word captions onto a video (+ optional SRT)")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    s.add_argument("--text", help="script (skips transcription)")
    s.add_argument("--style", default="pop", choices=["pop", "clean", "boxed", "serif"])
    s.add_argument("--model", default="small")
    s.add_argument("--accent", default="#ffd400")
    s.add_argument("--words", type=int)
    s.add_argument("--srt", action="store_true", help="also write an .srt next to the input")

    s = cmd("fetch", cmd_fetch, "download a song or clip by URL or search (+ source record and index)")
    s.add_argument("url", nargs="?")
    s.add_argument("--search", metavar="QUERY", help="take the top YouTube result for QUERY")
    s.add_argument("--list", nargs="?", const="", metavar="FILTER", help="list downloads (optionally filtered)")
    s.add_argument("--audio", action="store_true", help="audio only, mp3")
    s.add_argument("--browser", help="use this browser's login (chrome, brave, firefox, edge) for IG/FB")
    s.add_argument("--cookies", help="cookies.txt exported from a logged-in browser")
    s.add_argument("--section", help="seconds, e.g. 12-20")
    s.add_argument("--license")
    s.add_argument("--out")

    s = cmd("analyze", cmd_analyze, "critique an edit: hook, pacing, dead air, loudness, defects, score")
    s.add_argument("video")
    s.add_argument("--kind", default="meme", choices=["meme", "remix", "commentary", "brand"])
    s.add_argument("--json", metavar="FILE", help="also write the report as JSON")

    s = cmd("beats", cmd_beats, "tempo, first beat and hook (most energetic part) of a song")
    s.add_argument("song")
    s.add_argument("--bpm", type=float, help="skip tempo detection")
    s.add_argument("--window", type=float, default=20, help="hook length in seconds")

    s = cmd("private", cmd_private, "private mode: content stays on this machine")
    s.add_argument("state", choices=["on", "off", "status"])

    s = cmd("skill", cmd_skill, "install the Claude Code skill into a project or globally")
    s.add_argument("action", choices=["install", "show"])
    s.add_argument("target", nargs="?", default="global", help="project folder, or 'global' (~/.claude)")

    s = cmd("template", cmd_template, "start a job from a template (birthday-remix, hotel-remix)")
    s.add_argument("action", choices=["list", "new"])
    s.add_argument("name", nargs="?")
    s.add_argument("dest", nargs="?")

    cmd("formats", lambda a: [print(f"{k:<10} {v['w']}x{v['h']}") for k, v in FORMATS.items()],
        "list output sizes")

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
