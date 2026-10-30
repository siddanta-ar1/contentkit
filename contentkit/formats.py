"""Output presets for social platforms."""

FORMATS = {
    "reel":      {"w": 1080, "h": 1920, "fps": 30},  # Reels / TikTok / Shorts / Stories
    "square":    {"w": 1080, "h": 1080, "fps": 30},  # Feed post
    "portrait":  {"w": 1080, "h": 1350, "fps": 30},  # Instagram 4:5 feed
    "landscape": {"w": 1920, "h": 1080, "fps": 30},  # YouTube / X / LinkedIn
    "thumbnail": {"w": 1280, "h": 720,  "fps": 30},  # YouTube thumbnail
}

# Streaming platforms normalize to roughly -14 LUFS; mastering there avoids being turned down.
LOUDNESS = {"I": -14, "TP": -1.0, "LRA": 11}


def get_format(name):
    if name not in FORMATS:
        raise SystemExit(f"Unknown format '{name}'. Choose from: {', '.join(FORMATS)}")
    return FORMATS[name]
