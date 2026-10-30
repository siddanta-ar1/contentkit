"""Font lookup.

Bundled faces (SIL OFL, in contentkit/assets/fonts) are resolved first so output looks the
same on every machine. Anything else goes through fontconfig, so a recipe can name any
installed family (`"EB Garamond:bold"`) or point straight at a .ttf/.otf file.
"""
import subprocess
from functools import lru_cache
from pathlib import Path

FONT_DIR = Path(__file__).parent / "assets" / "fonts"

# "family:style" -> file. Styles are lowercase weights/italics.
BUNDLED = {
    "inter": "Inter-Regular.otf",
    "inter:medium": "Inter-Medium.otf",
    "inter:semibold": "Inter-SemiBold.otf",
    "inter display": "InterDisplay-SemiBold.otf",
    "inter display:medium": "InterDisplay-Medium.otf",
    "inter display:semibold": "InterDisplay-SemiBold.otf",
    "inter display:bold": "InterDisplay-Bold.otf",
    "inter display:black": "InterDisplay-Black.otf",
    "instrument serif": "InstrumentSerif-Regular.ttf",
    "instrument serif:italic": "InstrumentSerif-Italic.ttf",
    "anton": "Anton-Regular.ttf",
    "ibm plex mono": "IBMPlexMono-Regular.ttf",
    "ibm plex mono:medium": "IBMPlexMono-Medium.ttf",
}
# Older recipes used the fontconfig spelling of Inter's heavy weights.
ALIASES = {"inter:black": "inter display:black", "inter:extrabold": "inter display:black",
           "inter:bold": "inter display:bold"}

DEFAULT_FONT = "Inter Display:black"
FALLBACK = "DejaVu Sans:bold"

# libass weights for the ASS `Bold` field (captions).
WEIGHTS = {"regular": 400, "medium": 500, "semibold": 600, "bold": 700, "black": 900, "italic": 400}


@lru_cache(maxsize=None)
def font_file(spec=DEFAULT_FONT):
    if str(spec).endswith((".ttf", ".otf")):
        return str(spec)
    key = ALIASES.get(spec.lower(), spec.lower())
    if key in BUNDLED:
        return str(FONT_DIR / BUNDLED[key])
    for candidate in (spec, FALLBACK):
        try:
            path = subprocess.run(["fc-match", "-f", "%{file}", candidate],
                                  capture_output=True, text=True, check=True).stdout.strip()
            if path:
                return path
        except (OSError, subprocess.CalledProcessError):
            pass
    raise SystemExit(f"No font found for '{spec}'. Pass a .ttf/.otf path instead.")


def family(spec=DEFAULT_FONT):
    """Family name for libass (captions)."""
    if str(spec).endswith((".ttf", ".otf")):
        return Path(spec).stem.split("-")[0]
    key = ALIASES.get(spec.lower(), spec.lower())
    fam = key.split(":")[0]
    return {"inter display": "Inter Display", "inter": "Inter", "instrument serif": "Instrument Serif",
            "anton": "Anton", "ibm plex mono": "IBM Plex Mono"}.get(fam, spec.split(":")[0])


def weight(spec=DEFAULT_FONT):
    key = ALIASES.get(str(spec).lower(), str(spec).lower())
    return WEIGHTS.get(key.split(":")[1], 400) if ":" in key else 400


def is_italic(spec):
    return str(spec).lower().endswith(":italic")
