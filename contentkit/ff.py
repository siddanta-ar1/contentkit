"""Thin ffmpeg/ffprobe helpers."""
import json
import re
import shutil
import subprocess


def require(binary):
    if not shutil.which(binary):
        raise SystemExit(f"'{binary}' not found on PATH. Install it (e.g. sudo apt install {binary}).")


def run(args, cwd=None):
    require("ffmpeg")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{' '.join(cmd)}\n{proc.stderr.strip()}")


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def duration(path):
    return float(probe(path)["format"]["duration"])


def has_audio(path):
    return any(s["codec_type"] == "audio" for s in probe(path)["streams"])


def peak_db(path):
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                          capture_output=True, text=True)
    match = re.search(r"max_volume: (-?[0-9.]+) dB", proc.stderr)
    return float(match.group(1)) if match else 0.0
