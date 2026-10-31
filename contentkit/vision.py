"""Seeing what's in a frame: faces, on-screen text, sharpness, exposure, motion.

Backends are optional and detected at run time:
  faces  OpenCV's YuNet detector (model downloaded once to ~/.contentkit/models, MIT)
  text   Tesseract OCR (eng + nep if installed: `sudo apt install tesseract-ocr tesseract-ocr-nep`)
Functions return None when a backend is missing, so callers can skip that check.
"""
import json
import os
import shutil
import subprocess
import urllib.request
from functools import lru_cache
from pathlib import Path

import numpy as np

MODELS = Path.home() / ".contentkit" / "models"
YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")


def frame_at(src, t, width=640):
    """One RGB frame as a numpy array (height follows the aspect ratio)."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i", str(src), "-frames:v", "1",
                          "-vf", f"scale={width}:-2", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    if not out:
        return None
    h = len(out) // (width * 3)
    return np.frombuffer(out[: width * h * 3], np.uint8).reshape(h, width, 3)


# --- faces ----------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _face_detector():
    try:
        import cv2
    except ImportError:
        return None
    if not hasattr(cv2, "FaceDetectorYN"):
        return None
    model = MODELS / "yunet.onnx"
    if not model.exists():
        MODELS.mkdir(parents=True, exist_ok=True)
        try:
            urllib.request.urlretrieve(YUNET_URL, model)
        except OSError:
            return None
    cv2.setLogLevel(0) if hasattr(cv2, "setLogLevel") else None
    return cv2.FaceDetectorYN.create(str(model), "", (320, 320), 0.85)


def faces(rgb):
    """Faces as [(x, y, w, h, score)] in 0-1 frame fractions, largest first. None = no backend."""
    det = _face_detector()
    if det is None or rgb is None:
        return None
    h, w = rgb.shape[:2]
    det.setInputSize((w, h))
    _, found = det.detect(np.ascontiguousarray(rgb[:, :, ::-1]))
    if found is None:
        return []
    out = [(f[0] / w, f[1] / h, f[2] / w, f[3] / h, float(f[14])) for f in found]
    return sorted(out, key=lambda f: -f[2] * f[3])


def framing(face_list):
    """Shot size from the biggest face: what an editor would call the shot."""
    if not face_list:
        return "no face"
    fh = face_list[0][3]
    return "extreme close-up" if fh > 0.45 else "close-up" if fh > 0.22 else "medium" if fh > 0.09 else "wide"


# --- text -----------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _tesseract_langs():
    if not shutil.which("tesseract"):
        return None
    out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True).stdout
    have = {l.strip() for l in out.splitlines()[1:]}
    # English by default: adding Nepali makes Tesseract read textures as Devanagari on
    # stylised frames. `contentkit config ocr_langs eng+nep` for Nepali on-screen text.
    from . import config
    want = str(config.get("ocr_langs", "eng")).split("+")
    return "+".join(l for l in want if l in have) or None


def text(rgb, min_conf=70):
    """On-screen text: {"text", "box": [x, y, w, h] (0-1), "position": top|center|bottom}, or
    None without Tesseract. Uses word confidences so textures don't read as words."""
    langs = _tesseract_langs()
    if not langs or rgb is None:
        return None
    from PIL import Image
    h, w = rgb.shape[:2]
    img = Image.fromarray(rgb).convert("L")
    # OMP_THREAD_LIMIT=1: multi-threaded Tesseract stalls (40 s+ per frame) on many CPUs;
    # single-threaded it reads a 640-px frame in ~3 s. psm 3 keeps reading order.
    proc = subprocess.run(["tesseract", "stdin", "stdout", "-l", langs, "--psm", "3", "tsv"],
                          input=_png_bytes(img), capture_output=True, timeout=60,
                          env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    rows = proc.stdout.decode("utf-8", "ignore").splitlines()[1:]
    words = []
    for r in rows:
        c = r.split("\t")
        if len(c) == 12 and c[11].strip() and float(c[10]) >= min_conf and len(c[11].strip()) > 1:
            x, y, bw, bh = (int(v) for v in c[6:10])
            words.append((c[11].strip(), x, y, bw, bh))
    if not words:
        return {"text": "", "box": None, "position": None}
    x0 = min(wd[1] for wd in words)
    y0 = min(wd[2] for wd in words)
    x1 = max(wd[1] + wd[3] for wd in words)
    y1 = max(wd[2] + wd[4] for wd in words)
    cy = (y0 + y1) / 2 / h
    return {"text": " ".join(wd[0] for wd in words), "box": [x0 / w, y0 / h, (x1 - x0) / w, (y1 - y0) / h],
            "position": "top" if cy < 0.36 else "bottom" if cy > 0.64 else "center"}


def _png_bytes(img):
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# --- image quality ----------------------------------------------------------------------

def sharpness(rgb):
    """Variance of the Laplacian on luma: < ~60 at 640 px wide reads as soft / out of focus."""
    if rgb is None:
        return None
    y = rgb.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    lap = y[1:-1, 1:-1] * -4 + y[:-2, 1:-1] + y[2:, 1:-1] + y[1:-1, :-2] + y[1:-1, 2:]
    return float(lap.var())


def exposure(rgb):
    """Share of crushed blacks and clipped whites, and mean luma (0-1)."""
    if rgb is None:
        return None
    y = rgb.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    return {"mean": float(y.mean() / 255), "crushed": float((y < 6).mean()), "clipped": float((y > 249).mean())}


def motion(a, b):
    """Mean absolute luma difference between two frames (0-255): how much is moving."""
    if a is None or b is None or a.shape != b.shape:
        return None
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def similarity(a, b):
    """1 - normalised difference of two small grey thumbnails (1.0 = identical)."""
    if a is None or b is None:
        return None
    from PIL import Image
    ta = np.asarray(Image.fromarray(a).convert("L").resize((48, 85)), np.float32)
    tb = np.asarray(Image.fromarray(b).convert("L").resize((48, 85)), np.float32)
    return float(1 - np.abs(ta - tb).mean() / 255)


def capabilities():
    return {"faces": _face_detector() is not None, "ocr": _tesseract_langs()}


if __name__ == "__main__":
    print(json.dumps(capabilities()))
