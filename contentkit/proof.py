"""Client review sheets: a timecoded contact sheet for videos, a board for stills.

Editors send these for sign-off before the final upload; they're also the fastest way
to check a render without scrubbing through it.
"""
import datetime
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from . import ff, typo
from .brand import load_brand
from .typo import Style


def _timecode(t, fps=30):
    return f"{int(t // 60):02d}:{int(t % 60):02d}:{int(round((t % 1) * fps)) % fps:02d}"


def _frame(src, t, width):
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1",
                          "-vf", f"scale={width}:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                         capture_output=True, check=True).stdout
    from io import BytesIO
    return Image.open(BytesIO(out)).convert("RGB")


def _sheet(tiles, captions, title, subtitle, cols, brand, tile_w):
    pad, gap = 48, 28
    tile_h = max(t.height for t in tiles)
    lab = Style(brand.mono, 15, tracking=60, upper=True, color=brand.muted, balance=False)
    head = Style(brand.display, 44, color=brand.ink, tracking=-10)
    rows = (len(tiles) + cols - 1) // cols
    cap_h = 34
    W = pad * 2 + cols * tile_w + (cols - 1) * gap
    H = pad * 2 + 110 + rows * (tile_h + cap_h) + (rows - 1) * gap
    sheet = Image.new("RGB", (W, H), brand.paper)
    d = ImageDraw.Draw(sheet)
    typo.draw(d, typo.layout(title, head, W - 2 * pad), pad, pad)
    typo.draw(d, typo.layout(subtitle, lab, W - 2 * pad), pad, pad + 64)
    d.rectangle((pad, pad + 92, W - pad, pad + 92), fill=brand.ink)
    for i, (tile, cap) in enumerate(zip(tiles, captions)):
        x = pad + (i % cols) * (tile_w + gap)
        y = pad + 110 + (i // cols) * (tile_h + cap_h + gap)
        sheet.paste(tile, (x, y))
        typo.draw(d, typo.layout(cap, lab, tile_w), x, y + tile.height + 12)
    return sheet


def video_sheet(src, out, count=12, cols=None, brand=None):
    src = Path(src)
    brand = load_brand(brand)
    total = ff.duration(src)
    v = next(s for s in ff.probe(src)["streams"] if s["codec_type"] == "video")
    vertical = v["height"] > v["width"]
    cols = cols or (6 if vertical else 4)
    tile_w = 260 if vertical else 420
    times = [total * (i + 0.5) / count for i in range(count)]
    tiles = [_frame(src, t, tile_w) for t in times]
    sub = (f"{v['width']}×{v['height']}  ·  {total:.1f}s  ·  {count} frames  ·  "
           f"proof {datetime.date.today():%Y-%m-%d}")
    sheet = _sheet(tiles, [_timecode(t) for t in times], src.stem, sub, cols, brand, tile_w)
    sheet.save(out, quality=90)
    return Path(out)


def image_board(paths, out, cols=4, brand=None, title="Board"):
    brand = load_brand(brand)
    tile_w = 420
    tiles = []
    for p in paths:
        im = Image.open(p).convert("RGB")
        im.thumbnail((tile_w, tile_w * 2), Image.LANCZOS)
        tiles.append(im)
    sub = f"{len(tiles)} files  ·  proof {datetime.date.today():%Y-%m-%d}"
    sheet = _sheet(tiles, [Path(p).name for p in paths], title, sub, min(cols, len(tiles)), brand, tile_w)
    sheet.save(out, quality=90)
    return Path(out)
