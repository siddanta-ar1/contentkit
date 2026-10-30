"""Sound effects library.

`build_sfx_pack()` synthesizes a starter pack with ffmpeg: no downloads, no licenses to
track, safe for monetized content. Your own sounds go in the same folder and are
registered in `library.json` with their source and license (see `add_sfx`).
"""
import json
import shutil
from pathlib import Path

from . import ff

LIBRARY = Path.home() / ".contentkit" / "sfx"

# name -> (duration seconds, aevalsrc expression, post-filter chain)
# random(0) gives white noise; filters shape it into whooshes, impacts, etc.
RECIPES = {
    "whoosh": (0.7, "(random(0)*2-1)*sin(PI*t/0.7)^2",
               "bandpass=f=900:w=1400,highpass=f=200,volume=6"),
    "swoosh-up": (0.6, "(random(0)*2-1)*(t/0.6)^2",
                  "highpass=f=600,lowpass=f=6000,volume=5,afade=t=out:st=0.5:d=0.1"),
    "pop": (0.12, "sin(2*PI*(900-5000*t)*t)*exp(-t*40)", "volume=1.2"),
    "click": (0.03, "sin(2*PI*2400*t)*exp(-t*300)", ""),
    "ding": (1.4, "(0.6*sin(2*PI*1318.5*t)+0.3*sin(2*PI*2637*t)+0.1*sin(2*PI*3955*t))*exp(-t*3.5)", ""),
    "notify": (0.5, "0.6*sin(2*PI*if(lt(t,0.15),880,1320)*t)*exp(-mod(t,0.15)*12)",
               "afade=t=out:st=0.35:d=0.15"),
    "boom": (1.6, "(sin(2*PI*(55+80*exp(-t*12))*t)+0.4*(random(0)*2-1)*exp(-t*20))*exp(-t*2.5)",
             "lowpass=f=400,volume=2"),
    "bass-drop": (2.0, "sin(2*PI*(160*exp(-t*1.5)+35)*t)*min(1,t*20)*exp(-t*0.8)",
                  "lowpass=f=300,volume=2"),
    "riser": (2.5, "(0.6*sin(2*PI*(150*t+160*t*t))+0.4*(random(0)*2-1))*(t/2.5)^2",
              "highpass=f=120,volume=1.5"),
    "glitch": (0.5, "(random(0)*2-1)*gt(sin(2*PI*23*t),0)*sgn(sin(2*PI*180*t))",
               "bandpass=f=2000:w=3000,volume=0.8"),
    "buzzer": (0.7, "0.35*sgn(sin(2*PI*110*t))+0.2*sgn(sin(2*PI*116*t))",
               "lowpass=f=1800,afade=t=out:st=0.6:d=0.1"),
    "shutter": (0.25, "(random(0)*2-1)*(exp(-t*60)+0.7*exp(-(t-0.12)*60)*gt(t,0.12))",
                "highpass=f=1500"),
    "tick": (0.05, "sin(2*PI*1600*t)*exp(-t*150)", ""),
    "sparkle": (1.2, "0.4*sin(2*PI*(2000+1500*sin(2*PI*9*t))*t)*exp(-t*2.5)",
                "aecho=0.8:0.6:60|120:0.4|0.25"),
    "heartbeat": (1.0, "sin(2*PI*55*t)*(exp(-t*25)+0.8*exp(-(t-0.28)*25)*gt(t,0.28))",
                  "lowpass=f=200,volume=3"),
}


def _manifest():
    path = LIBRARY / "library.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _save_manifest(data):
    (LIBRARY / "library.json").write_text(json.dumps(data, indent=2, sort_keys=True))


def build_sfx_pack(force=False):
    LIBRARY.mkdir(parents=True, exist_ok=True)
    manifest = _manifest()
    for name, (dur, expr, post) in RECIPES.items():
        out = LIBRARY / f"{name}.wav"
        if out.exists() and not force:
            continue
        source = f"aevalsrc='{expr}':s=44100:d={dur}"
        chain = ",".join(f for f in (post, "aformat=sample_rates=44100:channel_layouts=stereo") if f)
        raw = LIBRARY / f".{name}.raw.wav"
        ff.run(["-f", "lavfi", "-i", source, "-af", chain, raw])
        # Peak-normalize to -1 dBFS so every sound starts at a predictable level.
        gain = -1.0 - ff.peak_db(raw)
        ff.run(["-i", raw, "-af", f"volume={gain:.2f}dB", out])
        raw.unlink()
        manifest[name] = {"file": out.name, "source": "contentkit synth", "license": "CC0 (generated)"}
    _save_manifest(manifest)
    return sorted(manifest)


def add_sfx(path, name=None, source="", license=""):
    """Copy your own sound into the library and record where it came from."""
    LIBRARY.mkdir(parents=True, exist_ok=True)
    src = Path(path)
    name = name or src.stem
    dest = LIBRARY / f"{name}{src.suffix}"
    shutil.copy2(src, dest)
    manifest = _manifest()
    manifest[name] = {"file": dest.name, "source": source, "license": license or "UNKNOWN - check before publishing"}
    _save_manifest(manifest)
    return dest


def sfx_path(name):
    """Resolve a library name ('whoosh') or a file path."""
    if Path(name).exists():
        return Path(name)
    entry = _manifest().get(name)
    if entry is None and name in RECIPES:
        build_sfx_pack()
        entry = _manifest().get(name)
    if entry is None:
        raise SystemExit(f"Unknown sound '{name}'. Run `contentkit sfx list` to see the library.")
    return LIBRARY / entry["file"]


def list_sfx():
    return _manifest()
