"""Brand kit: one file that keeps every post, poster and video on-brand.

```yaml
name: Ridgeline Coffee
handle: "@ridgeline.coffee"
url: ridgeline.coffee
colors: {ink: "#17130f", paper: "#f2ede4", accent: "#b4441c", muted: "#8b8279"}
type:
  display: "Instrument Serif"           # headlines
  display_em: "Instrument Serif:italic" # *emphasis* inside headlines
  heavy: "Inter Display:black"          # grotesk headlines (swiss, stat)
  condensed: "Anton"                    # posters that need volume (event)
  text: "Inter"                         # body copy
  text_strong: "Inter:semibold"
  mono: "IBM Plex Mono"                 # labels, metadata, footers
look: film          # colour grade for every photo and video (name or .cube path)
grain: 0.03         # film grain on photos (0 = off)
logo: logo.png      # optional; otherwise the name is set as a wordmark
```

Two families plus a mono is the ceiling. That restraint is most of what separates a
designed system from a generated one.
"""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_COLORS = {"ink": "#151412", "paper": "#f1eee8", "accent": "#c4451c", "muted": "#8a857d"}
DEFAULT_TYPE = {
    "display": "Instrument Serif",
    "display_em": "Instrument Serif:italic",
    "heavy": "Inter Display:black",
    "condensed": "Anton",
    "text": "Inter",
    "text_strong": "Inter:semibold",
    "mono": "IBM Plex Mono",
}

PRESETS = {
    "default": {},
    "editorial": {"colors": {"ink": "#17130f", "paper": "#f2ede4", "accent": "#b4441c", "muted": "#8b8279"},
                  "look": "film", "grain": 0.03},
    "swiss": {"colors": {"ink": "#111111", "paper": "#ecebe7", "accent": "#e2231a", "muted": "#7d7d79"},
              "type": {"display": "Inter Display:black", "display_em": "Inter Display:black"},
              "look": "natural", "grain": 0.0},
    "noir": {"colors": {"ink": "#0d0d0d", "paper": "#ebe8e1", "accent": "#d6b25e", "muted": "#7a776f"},
             "look": "noir", "grain": 0.045},
    "fresh": {"colors": {"ink": "#10261d", "paper": "#eef1ea", "accent": "#e8572a", "muted": "#7f8a83"},
              "look": "natural", "grain": 0.015},
}


@dataclass
class Brand:
    name: str = ""
    handle: str = ""
    url: str = ""
    colors: dict = field(default_factory=lambda: dict(DEFAULT_COLORS))
    type: dict = field(default_factory=lambda: dict(DEFAULT_TYPE))
    look: str = "natural"
    grain: float = 0.02
    logo: str = None
    captions: dict = field(default_factory=dict)
    lower_third: dict = field(default_factory=dict)

    def __getattr__(self, item):  # brand.ink, brand.accent, brand.mono ...
        for table in ("colors", "type"):
            values = self.__dict__.get(table, {})
            if item in values:
                return values[item]
        raise AttributeError(item)


def load_brand(spec=None, base=None):
    """spec: None, a preset name, a path to brand.yaml, or an inline dict."""
    data = {}
    if isinstance(spec, str) and spec in PRESETS:
        data = PRESETS[spec]
    elif isinstance(spec, (str, Path)):
        path = Path(spec)
        if not path.is_absolute() and base:
            path = Path(base) / path
        data = yaml.safe_load(path.read_text()) or {}
        if data.get("logo") and not Path(data["logo"]).is_absolute():
            data["logo"] = str((path.parent / data["logo"]).resolve())
        if data.get("preset"):
            data = _merge(PRESETS[data["preset"]], data)
    elif isinstance(spec, dict):
        data = _merge(PRESETS.get(spec.get("preset", "default"), {}), spec)
    brand = Brand()
    for key, value in data.items():
        if key in ("colors", "type"):
            getattr(brand, key).update(value or {})
        elif key != "preset" and hasattr(brand, key) or key in Brand.__dataclass_fields__:
            setattr(brand, key, value)
    return brand


def _merge(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = {**out.get(k, {}), **v} if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out
