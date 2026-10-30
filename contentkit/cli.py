"""contentkit command line.

  contentkit sfx init | list | add FILE --license ... | play NAME
  contentkit post RECIPE.yaml -o out.png           (single post, or carousel if it has `slides`)
  contentkit video RECIPE.yaml -o out.mp4
  contentkit tts "text" -o voice.wav
  contentkit captions VIDEO_OR_AUDIO --text "script"   (burns captions onto a video)
  contentkit fetch URL [--audio] [--section 10-25] [--license "CC-BY 4.0"]
  contentkit formats
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


def _load(path):
    path = Path(path)
    data = yaml.safe_load(path.read_text())
    base = path.parent.resolve()

    # Resolve relative asset paths against the recipe's folder so recipes are portable.
    def fix(node):
        if isinstance(node, dict):
            return {k: (str((base / v).resolve()) if k in ("image", "video", "file", "logo") and isinstance(v, str)
                        and not Path(v).is_absolute() and (base / v).exists() else fix(v)) for k, v in node.items()}
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


def cmd_post(a):
    from .post import render_carousel, render_post
    spec = _load(a.recipe)
    if spec.get("slides"):
        out = a.output or Path(a.recipe).stem
        for p in render_carousel(spec, out):
            print(p)
    else:
        print(render_post(spec, a.output or Path(a.recipe).with_suffix(".png").name))


def cmd_video(a):
    from .video import render_video
    render_video(_load(a.recipe), a.output or Path(a.recipe).with_suffix(".mp4").name, workdir=a.keep)


def cmd_tts(a):
    from .voice import synthesize
    path, engine = synthesize(a.text, a.output, a.engine, a.voice, a.speed)
    print(f"{path} ({engine}, {ff.duration(path):.1f}s)")


def cmd_captions(a):
    from .captions import align_script, transcribe, write_ass
    src = Path(a.input).resolve()
    words = transcribe(src, a.model) if not a.text else None
    if not words:
        if not a.text:
            raise SystemExit("Install faster-whisper (pip install faster-whisper) or pass --text with the script.")
        words = align_script(a.text, ff.duration(src))
    work = Path(tempfile.mkdtemp(prefix="contentkit-cap-"))
    v = next(s for s in ff.probe(src)["streams"] if s["codec_type"] == "video")
    write_ass(words, work / "captions.ass", v["width"], v["height"], accent=a.accent, words_per_line=a.words)
    out = Path(a.output or src.with_name(src.stem + "_captioned.mp4")).resolve()
    ff.run(["-i", src, "-vf", "ass=captions.ass", "-c:v", "libx264", "-crf", 20, "-c:a", "copy", out], cwd=work)
    print(out)


def cmd_fetch(a):
    from .fetch import download
    start = end = None
    if a.section:
        start, end = a.section.split("-")
    path, meta = download(a.url, a.audio, a.out, a.license or "", start, end)
    print(f"{path}\n{json.dumps(meta, indent=2)}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="contentkit", description="Open-source social content pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sfx", help="sound effects library")
    s.add_argument("action", choices=["init", "list", "add", "play"])
    s.add_argument("target", nargs="?")
    s.add_argument("--name")
    s.add_argument("--source")
    s.add_argument("--license")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_sfx)

    s = sub.add_parser("post", help="render a post or carousel from YAML")
    s.add_argument("recipe")
    s.add_argument("-o", "--output")
    s.set_defaults(fn=cmd_post)

    s = sub.add_parser("video", help="render a reel/short/video from YAML")
    s.add_argument("recipe")
    s.add_argument("-o", "--output")
    s.add_argument("--keep", metavar="DIR", help="keep intermediate files in DIR")
    s.set_defaults(fn=cmd_video)

    s = sub.add_parser("tts", help="text to speech")
    s.add_argument("text")
    s.add_argument("-o", "--output", default="voice.wav")
    s.add_argument("--engine", default="auto", choices=["auto", "piper", "espeak"])
    s.add_argument("--voice")
    s.add_argument("--speed", type=float, default=1.0)
    s.set_defaults(fn=cmd_tts)

    s = sub.add_parser("captions", help="burn word-by-word captions onto a video")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    s.add_argument("--text", help="script (skips transcription)")
    s.add_argument("--model", default="small")
    s.add_argument("--accent", default="#ffd400")
    s.add_argument("--words", type=int, default=3)
    s.set_defaults(fn=cmd_captions)

    s = sub.add_parser("fetch", help="download a clip or sound with yt-dlp (+ source record)")
    s.add_argument("url")
    s.add_argument("--audio", action="store_true")
    s.add_argument("--section", help="seconds, e.g. 12-20")
    s.add_argument("--license")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_fetch)

    s = sub.add_parser("formats", help="list output sizes")
    s.set_defaults(fn=lambda a: [print(f"{k:<10} {v['w']}x{v['h']}") for k, v in FORMATS.items()])

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
