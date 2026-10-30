"""Print-ready export: bleed, crop marks, slug line, CMYK with an embedded ICC profile.

The PDF is written directly so the artwork stays lossless (Flate, not JPEG) and carries
the page boxes prepress checks for: MediaBox (sheet), BleedBox (trim + 3 mm), TrimBox
(finished size). Alongside it goes a CMYK TIFF (LZW) and an RGB proof with the trim,
bleed and safe areas drawn on, for client sign-off.

Artwork is rasterised at the export DPI (300 by default), type included. That suits
posters and flyers. For fine print below ~8 pt, use a vector DTP tool.
"""
import datetime
import os
import zlib
from pathlib import Path

from PIL import Image, ImageCms, ImageDraw

from . import typo
from .brand import load_brand
from .formats import print_size
from .layouts import compose_page

# black point compensation keeps shadow detail when sRGB blacks map to ink limits
BPC = ImageCms.Flags.BLACKPOINTCOMPENSATION if hasattr(ImageCms, "Flags") else ImageCms.FLAGS["BLACKPOINTCOMPENSATION"]

ICC_DIRS = [Path("/usr/share/color/icc/colord"), Path("/usr/share/color/icc"), Path("/Library/ColorSync/Profiles"),
            Path.home() / ".contentkit" / "icc"]
PROFILES = {  # short name -> file stem, by press condition
    "fogra39": "FOGRA39L_coated",            # ISO Coated v2: Europe/Asia sheet-fed coated (default)
    "fogra47": "FOGRA47L_uncoated",          # uncoated offset
    "gracol": "GRACoL_TR006_coated",         # US commercial coated
    "swop": "SWOP_TR005_coated_5",           # US web offset
}


def find_profile(name="fogra39"):
    if name and Path(name).is_file():
        return Path(name)
    env = os.environ.get("CONTENTKIT_CMYK_ICC")
    if env and Path(env).is_file():
        return Path(env)
    stem = PROFILES.get(name, name)
    for d in ICC_DIRS:
        for f in d.glob("*.ic[cm]") if d.exists() else []:
            if f.stem.lower() == str(stem).lower():
                return f
    return None


def _mm(mm, dpi):
    return round(mm / 25.4 * dpi)


def add_marks(art, trim_w, trim_h, bleed, dpi, label=""):
    """Place the artwork on a sheet with a 10 mm slug: crop marks + a slug line."""
    slug = _mm(10, dpi)
    sheet = Image.new("RGB", (art.width + 2 * slug, art.height + 2 * slug), "white")
    sheet.paste(art, (slug, slug))
    d = ImageDraw.Draw(sheet)
    lw = max(1, round(dpi * 0.25 / 72))  # 0.25 pt
    t0x, t0y = slug + bleed, slug + bleed
    t1x, t1y = t0x + trim_w, t0y + trim_h
    gap, length = bleed + _mm(1, dpi), _mm(5, dpi)

    def line(x0, y0, x1, y1):
        d.rectangle((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), fill="black")

    # marks start outside the bleed so they never print on the finished piece
    for x in (t0x, t1x):
        for y, sign in ((t0y, -1), (t1y, 1)):
            line(x - lw // 2, y + sign * gap, x + lw - 1 - lw // 2, y + sign * (gap + length))
    for y in (t0y, t1y):
        for x, sign in ((t0x, -1), (t1x, 1)):
            line(x + sign * gap, y - lw // 2, x + sign * (gap + length), y + lw - 1 - lw // 2)
    if label:
        st = typo.Style("IBM Plex Mono", _mm(2.2, dpi), color="#000000", balance=False)
        blk = typo.layout(label, st, sheet.width)
        typo.draw(d, blk, t0x, sheet.height - slug / 2 - blk.cap / 2)
    return sheet, slug


def proof(art, trim_w, trim_h, bleed, safe):
    """RGB review copy: bleed shaded, trim in cyan, safe area in magenta."""
    img = art.copy().convert("RGBA")
    shade = Image.new("RGBA", img.size, (255, 255, 255, 0))
    d = ImageDraw.Draw(shade)
    w = max(2, bleed // 12)
    for box in ((0, 0, img.width, bleed), (0, img.height - bleed, img.width, img.height),
                (0, 0, bleed, img.height), (img.width - bleed, 0, img.width, img.height)):
        d.rectangle(box, fill=(255, 255, 255, 140))
    d.rectangle((bleed, bleed, bleed + trim_w, bleed + trim_h), outline=(0, 170, 220, 255), width=w)
    s = bleed + safe
    d.rectangle((s, s, bleed + trim_w - safe, bleed + trim_h - safe), outline=(230, 0, 120, 255), width=w)
    img.alpha_composite(shade)
    return img.convert("RGB")


def to_cmyk(img, profile_path, intent=ImageCms.Intent.RELATIVE_COLORIMETRIC):
    srgb = ImageCms.createProfile("sRGB")
    cmyk = ImageCms.getOpenProfile(str(profile_path))
    transform = ImageCms.buildTransform(srgb, cmyk, "RGB", "CMYK", renderingIntent=intent,
                                        flags=BPC)
    return ImageCms.applyTransform(img.convert("RGB"), transform), cmyk


def write_pdf(path, img, dpi, trim_box, bleed_box, icc_bytes=None, title="contentkit"):
    """Single-page PDF with a lossless image and correct page boxes (points, origin bottom-left)."""
    pt = 72 / dpi
    W, H = img.width * pt, img.height * pt

    def box(b):  # pixel box (x0, y0, x1, y1) from the top-left -> PDF points from the bottom-left
        return f"[{b[0] * pt:.3f} {H - b[3] * pt:.3f} {b[2] * pt:.3f} {H - b[1] * pt:.3f}]"

    cmyk = img.mode == "CMYK"
    objs = []

    def add(body):
        objs.append(body)
        return len(objs)

    raw = zlib.compress(img.tobytes(), 6)
    if cmyk and icc_bytes:
        icc = add(b"<< /N 4 /Filter /FlateDecode /Length %d >>\nstream\n" % len(zlib.compress(icc_bytes))
                  + zlib.compress(icc_bytes) + b"\nendstream")
        cs = f"[/ICCBased {icc} 0 R]".encode()
    else:
        cs = b"/DeviceCMYK" if cmyk else b"/DeviceRGB"
    im = add(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace " % (img.width, img.height)
             + cs + b" /BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n" % len(raw) + raw
             + b"\nendstream")
    content = f"q {W:.3f} 0 0 {H:.3f} 0 0 cm /Im0 Do Q".encode()
    cont = add(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    pages_id = len(objs) + 2
    page = add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {W:.3f} {H:.3f}] "
               f"/BleedBox {box(bleed_box)} /TrimBox {box(trim_box)} "
               f"/Resources << /XObject << /Im0 {im} 0 R >> >> /Contents {cont} 0 R >>".encode())
    add(f"<< /Type /Pages /Kids [{page} 0 R] /Count 1 >>".encode())
    info = add(f"<< /Title ({title}) /Producer (contentkit) /CreationDate (D:{datetime.datetime.now():%Y%m%d%H%M%S}) >>"
               .encode())
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())

    out = bytearray(b"%PDF-1.6\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    Path(path).write_bytes(out)
    return Path(path)


def export_print(spec, out_base, size="a3", dpi=300, orientation="portrait", marks=True, profile="fogra39",
                 brand=None, log=print):
    """Render a poster recipe for print. Writes <out>.pdf, <out>-cmyk.tif and <out>-proof.jpg."""
    ps = print_size(size, dpi, orientation)
    brand = brand or load_brand(spec.get("brand"))
    art = compose_page(spec, ps["w"], ps["h"], bleed=ps["bleed"], safe=ps["safe"], brand=brand)
    out_base = Path(out_base)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    written = []

    pf = proof(art, ps["w"], ps["h"], ps["bleed"], ps["safe"])
    pf.thumbnail((2400, 2400), Image.LANCZOS)
    pf.save(out_base.with_name(out_base.name + "-proof.jpg"), quality=90)
    written.append(out_base.with_name(out_base.name + "-proof.jpg"))

    label = (f"{out_base.name}  ·  {size.upper()} {ps['mm'][0]:g}×{ps['mm'][1]:g} mm  ·  bleed 3 mm  ·  {dpi} dpi  ·  "
             f"{datetime.date.today():%Y-%m-%d}")
    sheet, slug = add_marks(art, ps["w"], ps["h"], ps["bleed"], dpi, label) if marks else (art, 0)
    trim = (slug + ps["bleed"], slug + ps["bleed"], slug + ps["bleed"] + ps["w"], slug + ps["bleed"] + ps["h"])
    bleed_box = (slug, slug, slug + art.width, slug + art.height)

    icc_path = find_profile(profile)
    if icc_path:
        cmyk, prof = to_cmyk(sheet, icc_path)
        icc_bytes = prof.tobytes()
        tif = out_base.with_name(out_base.name + "-cmyk.tif")
        cmyk.save(tif, compression="tiff_lzw", dpi=(dpi, dpi), icc_profile=icc_bytes)
        written.append(tif)
        pdf = write_pdf(out_base.with_suffix(".pdf"), cmyk, dpi, trim, bleed_box, icc_bytes, out_base.name)
        log(f"CMYK via {icc_path.name}")
    else:
        log(f"warning: no CMYK profile '{profile}' found; writing an RGB PDF (set CONTENTKIT_CMYK_ICC or --icc)")
        pdf = write_pdf(out_base.with_suffix(".pdf"), sheet, dpi, trim, bleed_box, None, out_base.name)
    written.insert(0, pdf)
    return written
