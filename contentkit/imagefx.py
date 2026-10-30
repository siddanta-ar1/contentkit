"""Photo finishing: colour looks, LUTs, grain, vignette, duotone, scrims, focal-point crops.

A look is a function on linear-ish RGB in [0, 1]. Posters apply it directly; videos get the
same function baked into a .cube LUT for ffmpeg's lut3d, so a brand's stills and motion
share one grade. Any third-party .cube LUT works in both places too.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

# Parameters per look. Colours in split toning are additive offsets, kept small on purpose:
# a grade should be felt, not noticed.
LOOKS = {
    "none": {},
    "natural": {"contrast": 0.12, "sat": 1.03},
    "film": {"lift": 0.035, "contrast": 0.22, "sat": 0.86, "temp": 0.15,
             "shadows": (-0.01, 0.012, 0.03), "highlights": (0.035, 0.015, -0.02), "rolloff": 0.25},
    "teal-orange": {"contrast": 0.28, "sat": 1.06, "shadows": (-0.03, 0.02, 0.05),
                    "highlights": (0.05, 0.02, -0.04), "rolloff": 0.2},
    "matte": {"lift": 0.075, "gain": 0.96, "contrast": 0.1, "sat": 0.8, "rolloff": 0.3},
    "warm": {"temp": 0.55, "contrast": 0.12, "sat": 1.0, "lift": 0.02},
    "cold": {"temp": -0.5, "contrast": 0.16, "sat": 0.9, "shadows": (-0.01, 0.0, 0.025)},
    "bleach": {"contrast": 0.4, "sat": 0.5, "lift": 0.01, "rolloff": 0.15},
    "noir": {"mono": True, "contrast": 0.45, "lift": 0.015, "gain": 0.98},
    "mono-warm": {"mono": True, "contrast": 0.22, "lift": 0.04,
                  "shadows": (0.0, 0.0, 0.0), "highlights": (0.03, 0.015, -0.015)},
}


def _smooth(x):
    return x * x * (3 - 2 * x)


def grade_array(x, look):
    """Apply a named look (or params dict) to float RGB array in [0, 1]."""
    p = LOOKS[look] if isinstance(look, str) else look
    if not p:
        return x
    x = x.astype(np.float32, copy=True)
    if p.get("temp"):
        t = p["temp"] * 0.06
        x[..., 0] *= 1 + t
        x[..., 2] *= 1 - t
    lum = (x @ LUMA)[..., None]
    if p.get("mono"):
        x = np.repeat(lum, 3, axis=-1)
    elif "sat" in p:
        x = lum + (x - lum) * p["sat"]
    if p.get("contrast"):
        x = np.clip(x, 0, 1)
        x = x + (_smooth(x) - x) * p["contrast"] * 2
    lift, gain = p.get("lift", 0.0), p.get("gain", 1.0)
    x = lift + x * (gain - lift)
    if "shadows" in p or "highlights" in p:
        lum = np.clip(x @ LUMA, 0, 1)[..., None]
        x = x + (1 - lum) ** 2 * np.array(p.get("shadows", (0, 0, 0)), np.float32) \
              + lum ** 2 * np.array(p.get("highlights", (0, 0, 0)), np.float32)
    if p.get("rolloff"):
        # soft shoulder: highlights compress instead of clipping
        k = p["rolloff"]
        knee = 1 - k
        over = np.maximum(x - knee, 0)
        x = np.where(x > knee, knee + k * (1 - np.exp(-over / k)), x)
    return np.clip(x, 0, 1)


# ---- .cube LUTs -----------------------------------------------------------------------

def write_cube(look, path, size=33):
    """Bake a look into a .cube file (red varies fastest, per the Adobe spec)."""
    g = np.linspace(0, 1, size, dtype=np.float32)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")
    grid = np.stack([r, gg, b], axis=-1).reshape(-1, 3)
    out = grade_array(grid, look)
    lines = [f"TITLE \"contentkit {look if isinstance(look, str) else 'custom'}\"", f"LUT_3D_SIZE {size}"]
    lines += [f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}" for v in out]
    Path(path).write_text("\n".join(lines) + "\n")
    return Path(path)


def read_cube(path):
    size, rows = None, []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.upper().startswith("LUT_3D_SIZE"):
            size = int(line.split()[1])
        elif line[0].isdigit() or line[0] in "-.":
            rows.append([float(v) for v in line.split()[:3]])
    table = np.array(rows, np.float32).reshape(size, size, size, 3)  # [b][g][r]
    return table, size


def apply_cube(x, path):
    table, n = read_cube(path)
    p = np.clip(x, 0, 1) * (n - 1)
    i0 = np.floor(p).astype(int)
    i1 = np.minimum(i0 + 1, n - 1)
    f = p - i0
    out = np.zeros_like(x)
    for dr in (0, 1):
        for dg in (0, 1):
            for db in (0, 1):
                r = i1[..., 0] if dr else i0[..., 0]
                g = i1[..., 1] if dg else i0[..., 1]
                b = i1[..., 2] if db else i0[..., 2]
                w = (f[..., 0] if dr else 1 - f[..., 0]) * (f[..., 1] if dg else 1 - f[..., 1]) \
                    * (f[..., 2] if db else 1 - f[..., 2])
                out += table[b, g, r] * w[..., None]
    return out


def lut_for(look, workdir):
    """Path to a .cube for ffmpeg: user file as-is, named looks baked on demand."""
    if not look or look == "none":
        return None
    if str(look).endswith(".cube"):
        return Path(look).resolve()
    if look not in LOOKS:
        raise SystemExit(f"Unknown look '{look}'. Choose from: {', '.join(LOOKS)} or a .cube file")
    return write_cube(look, Path(workdir) / f"look-{look}.cube")


# ---- PIL helpers ----------------------------------------------------------------------

def to_array(img):
    return np.asarray(img.convert("RGB"), dtype=np.float32) / 255


def to_image(x):
    return Image.fromarray((np.clip(x, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


def grade(img, look):
    if not look or look == "none":
        return img.convert("RGB")
    x = to_array(img)
    x = apply_cube(x, look) if str(look).endswith(".cube") else grade_array(x, look)
    return to_image(x)


def cover(img, w, h, focus=(0.5, 0.5), zoom=1.0):
    """Crop-to-fill around a focal point (0-1, 0-1); zoom > 1 punches in on that point."""
    img = img.convert("RGB")
    if zoom and zoom > 1:
        cw, ch = img.width / zoom, img.height / zoom
        cx = min(max(focus[0] * img.width, cw / 2), img.width - cw / 2)
        cy = min(max(focus[1] * img.height, ch / 2), img.height - ch / 2)
        img = img.crop((round(cx - cw / 2), round(cy - ch / 2), round(cx + cw / 2), round(cy + ch / 2)))
        focus = (0.5, 0.5)
    return ImageOps.fit(img, (int(w), int(h)), Image.LANCZOS, centering=tuple(focus))


def grain(img, amount=0.04, size=1.4, seed=7):
    """Monochrome, midtone-weighted grain: reads as film, not as digital noise."""
    w, h = img.size
    rng = np.random.default_rng(seed)
    small = rng.normal(0, 1, (max(1, int(h / size)), max(1, int(w / size)))).astype(np.float32)
    noise = np.asarray(Image.fromarray(small).resize((w, h), Image.BICUBIC), np.float32)
    x = to_array(img)
    lum = x @ LUMA
    weight = (4 * lum * (1 - lum))[..., None] * 0.75 + 0.25
    return to_image(x + noise[..., None] * amount * weight)


def vignette(img, strength=0.22, softness=0.65):
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / np.sqrt(2)
    mask = 1 - strength * _smooth(np.clip((d - (1 - softness)) / softness, 0, 1))
    return to_image(to_array(img) * mask[..., None])


def _rgb(c):
    c = c.lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], np.float32) / 255


def duotone(img, shadow, highlight, contrast=0.15):
    x = to_array(img)
    lum = np.clip(x @ LUMA, 0, 1)
    lum = lum + (_smooth(lum) - lum) * contrast * 2
    return to_image(_rgb(shadow) * (1 - lum[..., None]) + _rgb(highlight) * lum[..., None])


def scrim(img, edge="bottom", reach=0.55, opacity=0.78, color="#000000", hold=0.0):
    """Legibility gradient from an edge. Stays dense for the first `hold` fraction of its reach
    (where the type sits), then eases out, so there is no visible band where it ends."""
    w, h = img.size
    span = h if edge in ("top", "bottom") else w
    t = np.linspace(0, 1, int(span * reach), dtype=np.float32)
    if hold:
        inner = np.clip(t / hold, 0, 1)
        outer = np.clip((t - hold) / (1 - hold), 0, 1)
        alpha = np.where(t < hold, opacity * (1 - 0.18 * inner), opacity * 0.82 * (1 - _smooth(outer)) ** 1.4)
    else:
        alpha = opacity * (1 - _smooth(t)) ** 1.6
    ramp = np.zeros(span, np.float32)
    ramp[:len(alpha)] = alpha
    if edge in ("bottom", "right"):
        ramp = ramp[::-1]
    mask = np.tile(ramp[:, None], (1, w)) if edge in ("top", "bottom") else np.tile(ramp[None, :], (h, 1))
    x = to_array(img)
    return to_image(x * (1 - mask[..., None]) + _rgb(color) * mask[..., None])


def finish(img, look=None, grain_amount=0.0, vignette_strength=0.0):
    """Standard photo finishing chain used by every layout."""
    img = grade(img, look)
    if vignette_strength:
        img = vignette(img, vignette_strength)
    if grain_amount:
        img = grain(img, grain_amount)
    return img


def soften(img, radius):
    return img.filter(ImageFilter.GaussianBlur(radius))
