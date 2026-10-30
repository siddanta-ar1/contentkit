"""Text-to-speech, offline.

Engines, best first:
  piper    - natural neural voices, runs on CPU. `pip install piper-tts`, then download a
             voice: `python3 -m piper.download_voices en_US-lessac-medium` and point
             CONTENTKIT_PIPER_MODEL (or `voice:` in the recipe) at the .onnx file.
  espeak-ng - robotic but always available (`sudo apt install espeak-ng`). Good for drafts.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _piper_cmd():
    if shutil.which("piper"):
        return ["piper"]
    try:
        import piper  # noqa: F401
        return [sys.executable, "-m", "piper"]
    except ImportError:
        return None


def _piper_model(voice):
    for candidate in (voice, os.environ.get("CONTENTKIT_PIPER_MODEL")):
        if candidate and str(candidate).endswith(".onnx") and Path(candidate).exists():
            return candidate
    for folder in (Path.cwd(), Path.home() / ".contentkit" / "voices"):
        found = sorted(folder.glob("*.onnx")) if folder.exists() else []
        if found:
            return str(found[0])
    return None


def synthesize(text, out, engine="auto", voice=None, speed=1.0):
    out = Path(out)
    piper, model = _piper_cmd(), _piper_model(voice)
    if engine in ("auto", "piper") and piper and model:
        cmd = [*piper, "--model", model, "--output_file", str(out), "--length_scale", str(1 / speed)]
        subprocess.run(cmd, input=text, text=True, check=True, capture_output=True)
        return out, "piper"
    if engine == "piper":
        raise SystemExit("piper requested but not available: pip install piper-tts and download a .onnx voice.")
    if not shutil.which("espeak-ng"):
        raise SystemExit("No TTS engine found. Install piper-tts (recommended) or espeak-ng.")
    cmd = ["espeak-ng", "-v", voice or "en-us+m3", "-s", str(round(165 * speed)), "-w", str(out), text]
    subprocess.run(cmd, check=True, capture_output=True)
    return out, "espeak-ng"
