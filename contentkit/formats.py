"""Output presets: social canvases, print sizes, platform safe zones, encode targets."""

FORMATS = {
    "reel":      {"w": 1080, "h": 1920, "fps": 30},  # Reels / TikTok / Shorts / Stories
    "square":    {"w": 1080, "h": 1080, "fps": 30},  # Feed post
    "portrait":  {"w": 1080, "h": 1350, "fps": 30},  # Instagram / LinkedIn 4:5 feed
    "landscape": {"w": 1920, "h": 1080, "fps": 30},  # YouTube / X / LinkedIn
    "thumbnail": {"w": 1280, "h": 720,  "fps": 30},  # YouTube thumbnail
    "og":        {"w": 1200, "h": 630,  "fps": 30},  # link preview / blog header
}

# Trim sizes in millimetres (portrait). Bleed is added on export.
PRINT = {
    "a5": (148, 210), "a4": (210, 297), "a3": (297, 420), "a2": (420, 594), "a1": (594, 841),
    "letter": (215.9, 279.4), "tabloid": (279.4, 431.8),
    "18x24": (457.2, 609.6), "24x36": (609.6, 914.4),
}
BLEED_MM = 3      # standard trade-printer bleed
SAFE_MM = 5       # keep type and logos this far inside the trim
MM_PER_INCH = 25.4

# Platform UI covers parts of a 1080x1920 frame. Pixels at 1080x1920, scaled for other
# sizes. Reverse-engineered by the industry, not published by the platforms: preview with
# `contentkit safezone` and check on a phone before a campaign goes out.
SAFE_ZONES = {
    "universal": {"top": 220, "bottom": 420, "left": 60, "right": 140},
    "reels":     {"top": 220, "bottom": 400, "left": 60, "right": 130},
    "tiktok":    {"top": 160, "bottom": 480, "left": 60, "right": 150},
    "shorts":    {"top": 180, "bottom": 420, "left": 60, "right": 130},
    "stories":   {"top": 250, "bottom": 340, "left": 60, "right": 60},
}

# Streaming platforms normalize to roughly -14 LUFS; mastering there avoids being turned down.
LOUDNESS = {"I": -14, "TP": -1.0, "LRA": 11}

# Upload masters: platforms re-encode everything, so give them headroom to work from.
ENCODE = {"crf": 18, "maxrate": "16M", "bufsize": "16M", "audio_rate": 48000, "audio_bitrate": "256k"}


def get_format(name):
    if isinstance(name, dict):
        return {"fps": 30, **name}
    if name not in FORMATS:
        raise SystemExit(f"Unknown format '{name}'. Choose from: {', '.join(FORMATS)}")
    return FORMATS[name]


def safe_zone(w, h, platform="universal"):
    """Insets (top, right, bottom, left) in pixels for a vertical frame, else small margins."""
    if h / w < 1.6:  # not a 9:16 frame: no platform chrome to dodge
        return {"top": 0, "right": 0, "bottom": 0, "left": 0}
    z = SAFE_ZONES[platform]
    sx, sy = w / 1080, h / 1920
    return {"top": z["top"] * sy, "bottom": z["bottom"] * sy, "left": z["left"] * sx, "right": z["right"] * sx}


def print_size(name, dpi=300, orientation="portrait"):
    """Trim size in pixels and the bleed in pixels for a print format."""
    if name not in PRINT:
        raise SystemExit(f"Unknown print size '{name}'. Choose from: {', '.join(PRINT)}")
    w_mm, h_mm = PRINT[name]
    if orientation == "landscape":
        w_mm, h_mm = h_mm, w_mm
    px = lambda mm: round(mm / MM_PER_INCH * dpi)
    return {"w": px(w_mm), "h": px(h_mm), "bleed": px(BLEED_MM), "safe": px(SAFE_MM), "dpi": dpi,
            "mm": (w_mm, h_mm)}
