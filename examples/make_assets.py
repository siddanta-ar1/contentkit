"""Generate demo assets (backgrounds + a music loop) so the examples run offline."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from contentkit import ff

HERE = Path(__file__).parent / "assets"
HERE.mkdir(exist_ok=True)


def blobs(name, colors, size=(1600, 2400)):
    img = Image.new("RGB", size, colors[0])
    d = ImageDraw.Draw(img)
    w, h = size
    for i, c in enumerate(colors[1:]):
        x, y = (0.2 + 0.5 * (i % 2)) * w, (0.25 + 0.3 * i) * h
        d.ellipse((x - w * 0.45, y - w * 0.45, x + w * 0.45, y + w * 0.45), fill=c)
    img.filter(ImageFilter.GaussianBlur(160)).save(HERE / name, quality=92)


blobs("bg1.jpg", ["#120c2e", "#6a11cb", "#2575fc", "#ff0080"])
blobs("bg2.jpg", ["#0b1d13", "#11998e", "#38ef7d", "#f9d423"])

# 8-second 90 BPM loop: kick on the beat, offbeat hats, A-minor pad. CC0, made here.
beat = 0.6667
expr = (f"0.9*sin(2*PI*(45+110*exp(-mod(t,{beat})*30))*mod(t,{beat}))*exp(-mod(t,{beat})*7)"
        f"+0.12*(random(0)*2-1)*exp(-mod(t+{beat / 2},{beat})*70)"
        f"+0.07*(sin(2*PI*220*t)+sin(2*PI*261.63*t)+sin(2*PI*329.63*t))*(0.7+0.3*sin(2*PI*t/{beat * 4}))")
ff.run(["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d=8",
        "-af", "aformat=channel_layouts=stereo,lowpass=f=9000,alimiter=limit=0.8", HERE / "loop.wav"])
print("assets in", HERE)
