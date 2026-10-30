"""Font lookup via fontconfig, so recipes can say `font: "Inter:bold"`."""
import subprocess
from functools import lru_cache

DEFAULT_FONT = "Inter:extrabold"
FALLBACK = "DejaVu Sans:bold"


@lru_cache(maxsize=None)
def font_file(spec=DEFAULT_FONT):
    if spec.endswith((".ttf", ".otf")):
        return spec
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
    return spec.split(":")[0] if not spec.endswith((".ttf", ".otf")) else "Inter"
