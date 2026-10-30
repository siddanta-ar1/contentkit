"""Regenerate the demo music loop (CC0, synthesized here) so the examples run offline.

The photographs in assets/photos are CC0 / public domain; see assets/CREDITS.md.
"""
from pathlib import Path

from contentkit import ff

HERE = Path(__file__).parent / "assets"

# 8-second 90 BPM loop: kick on the beat, offbeat hats, A-minor pad.
beat = 0.6667
expr = (f"0.9*sin(2*PI*(45+110*exp(-mod(t,{beat})*30))*mod(t,{beat}))*exp(-mod(t,{beat})*7)"
        f"+0.12*(random(0)*2-1)*exp(-mod(t+{beat / 2},{beat})*70)"
        f"+0.07*(sin(2*PI*220*t)+sin(2*PI*261.63*t)+sin(2*PI*329.63*t))*(0.7+0.3*sin(2*PI*t/{beat * 4}))")
ff.run(["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d=8",
        "-af", "aformat=channel_layouts=stereo,lowpass=f=9000,alimiter=limit=0.8", HERE / "loop.wav"])
print("wrote", HERE / "loop.wav")
