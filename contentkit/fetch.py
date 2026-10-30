"""Pull reference media (sounds, clips) with yt-dlp and record where each file came from.

Every download gets a `.source.json` sidecar with the URL, uploader and the license you
declare, so you can tell later what is safe to publish.
"""
import json
import shutil
import subprocess
from pathlib import Path

ASSETS = Path.home() / ".contentkit" / "downloads"


def download(url, audio_only=False, out_dir=None, license="", start=None, end=None):
    if not shutil.which("yt-dlp"):
        raise SystemExit("yt-dlp not found: pip install -U yt-dlp")
    out_dir = Path(out_dir or ASSETS)
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["yt-dlp", "--no-playlist", "--restrict-filenames", "--print", "after_move:filepath",
           "--write-info-json", "-o", str(out_dir / "%(extractor)s_%(id)s.%(ext)s")]
    if audio_only:
        cmd += ["-x", "--audio-format", "wav"]
    else:
        cmd += ["-f", "bv*[height<=1920]+ba/b", "--merge-output-format", "mp4"]
    if start is not None or end is not None:
        cmd += ["--download-sections", f"*{start or 0}-{end or 'inf'}", "--force-keyframes-at-cuts"]
    proc = subprocess.run([*cmd, url], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip().splitlines()[-1] if proc.stderr else "yt-dlp failed")
    path = Path(proc.stdout.strip().splitlines()[-1])

    info_file = path.with_suffix(".info.json")
    info = json.loads(info_file.read_text()) if info_file.exists() else {}
    info_file.unlink(missing_ok=True)
    meta = {
        "url": url,
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "platform_license": info.get("license"),
        "license": license or info.get("license") or "UNKNOWN - reference only until cleared",
    }
    path.with_suffix(".source.json").write_text(json.dumps(meta, indent=2))
    return path, meta
