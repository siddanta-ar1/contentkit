"""Image posts and carousels rendered with Pillow.

A post is a theme (background, colors, fonts) plus text slots. The same text engine
draws the title cards that videos overlay, so posts and reels share one look.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .fonts import font_file
from .formats import get_format

DEFAULT_THEME = {
    "bg": "#101014",
    "gradient": None,          # e.g. ["#ff512f", "#dd2476"]
    "image": None,             # background photo, cover-cropped
    "dim": 0.45,               # darken background image so text stays readable
    "text": "#ffffff",
    "accent": "#ffd400",
    "font": "Inter:black",
    "body_font": "Inter:semibold",
    "handle": None,
    "logo": None,
}


def theme_from(spec=None):
    theme = dict(DEFAULT_THEME)
    theme.update(spec or {})
    return theme


def _rgb(color):
    return Image.new("RGB", (1, 1), color).getpixel((0, 0))


def cover(img, w, h):
    return ImageOps.fit(img.convert("RGB"), (w, h), Image.LANCZOS)


def background(w, h, theme):
    if theme.get("image"):
        img = cover(Image.open(theme["image"]), w, h)
        if theme.get("dim"):
            img = Image.blend(img, Image.new("RGB", (w, h), "black"), float(theme["dim"]))
        return img
    if theme.get("gradient"):
        top, bottom = (_rgb(c) for c in theme["gradient"][:2])
        column = Image.new("RGB", (1, h))
        for y in range(h):
            t = y / max(h - 1, 1)
            column.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
        return column.resize((w, h))
    return Image.new("RGB", (w, h), theme["bg"])


def _wrap(draw, text, font, width):
    lines = []
    for paragraph in str(text).split("\n"):
        line = ""
        for word in paragraph.split():
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) <= width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def fit_text(draw, text, font_spec, box_w, box_h, max_size, min_size=18, spacing=0.18):
    """Largest font size whose wrapped text fits the box."""
    lo, hi, best = min_size, max_size, None
    while lo <= hi:
        size = (lo + hi) // 2
        font = ImageFont.truetype(font_file(font_spec), size)
        lines = _wrap(draw, text, font, box_w)
        line_h = size * (1 + spacing)
        widest = max(draw.textlength(l, font=font) for l in lines)
        if len(lines) * line_h <= box_h and widest <= box_w:
            best, lo = (font, lines, line_h), size + 1
        else:
            hi = size - 1
    if best is None:
        font = ImageFont.truetype(font_file(font_spec), min_size)
        best = (font, _wrap(draw, text, font, box_w), min_size * (1 + spacing))
    return best


def draw_text(img, text, box, font_spec, max_size, color="#ffffff", align="center",
              valign="center", stroke=0, stroke_color="#000000", shadow=True, highlight=None):
    """Draw auto-fitted text in box=(x, y, w, h). Returns (top, height) of the drawn block.
    `highlight` paints a pill behind each line."""
    if not text:
        return box[1], 0
    x, y, w, h = box
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font, lines, line_h = fit_text(draw, text, font_spec, w, h, max_size)
    total = len(lines) * line_h
    top = {"top": y, "center": y + (h - total) / 2, "bottom": y + h - total}[valign]
    for i, line in enumerate(lines):
        lw = draw.textlength(line, font=font)
        lx = {"left": x, "center": x + (w - lw) / 2, "right": x + w - lw}[align]
        ly = top + i * line_h
        if highlight:
            pad = font.size * 0.22
            draw.rounded_rectangle((lx - pad, ly - pad * 0.4, lx + lw + pad, ly + font.size * 1.12 + pad * 0.4),
                                   radius=pad, fill=highlight)
        draw.text((lx, ly), line, font=font, fill=color, stroke_width=stroke, stroke_fill=stroke_color)
    if shadow:
        alpha = layer.split()[3].filter(ImageFilter.GaussianBlur(max(4, font.size // 10)))
        shade = Image.new("RGBA", img.size, (0, 0, 0, 0))
        shade.putalpha(alpha.point(lambda a: int(a * 0.55)))
        img.alpha_composite(shade, (0, max(2, font.size // 18)))
    img.alpha_composite(layer)
    return top, total


def _logo(img, path, size, margin):
    logo = Image.open(path).convert("RGBA")
    logo.thumbnail((size, size), Image.LANCZOS)
    img.alpha_composite(logo, (img.width - logo.width - margin, margin))


def compose(w, h, theme, title=None, body=None, kicker=None, footer=None, transparent=False):
    """Build one RGBA frame. With transparent=True only the text is drawn (video overlays)."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0)) if transparent else background(w, h, theme).convert("RGBA")
    m = round(min(w, h) * 0.08)
    inner_w = w - 2 * m
    accent = theme["accent"]
    title_h = h * (0.38 if body else 0.6)
    title_y = (h - title_h - (h * 0.25 if body else 0)) / 2

    text_top, _ = draw_text(img, title, (m, title_y, inner_w, title_h), theme["font"], round(w * 0.12),
                            color=theme["text"], stroke=0 if not transparent else max(2, w // 300))
    if kicker:  # sits just above the title as actually drawn, not above its box
        kh = min(h * 0.05, w * 0.07)
        draw_text(img, kicker.upper(), (m, text_top - kh * 1.6, inner_w, kh), theme["body_font"],
                  round(w * 0.04), color="#111111", highlight=accent, shadow=False)
    if body:
        draw_text(img, body, (m, title_y + title_h + h * 0.03, inner_w, h * 0.25), theme["body_font"],
                  round(w * 0.05), color=theme["text"])
    footer = footer or theme.get("handle")
    if footer and not transparent:
        draw_text(img, footer, (m, h - m - h * 0.05, inner_w, h * 0.05), theme["body_font"],
                  round(w * 0.035), color=accent, shadow=False)
    if theme.get("logo") and not transparent:
        _logo(img, theme["logo"], round(w * 0.12), m // 2)
    return img


def render_post(spec, out):
    """spec: {format, theme, title, body, kicker, footer} -> PNG/JPG."""
    fmt = get_format(spec.get("format", "square"))
    theme = theme_from(spec.get("theme"))
    img = compose(fmt["w"], fmt["h"], theme, spec.get("title"), spec.get("body"),
                  spec.get("kicker"), spec.get("footer"))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, quality=95)
    return out


def render_carousel(spec, out_dir):
    """spec: {format, theme, slides: [{title, body, kicker}]} -> numbered images with a 1/N counter."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slides = spec["slides"]
    paths = []
    for i, slide in enumerate(slides, 1):
        footer = slide.get("footer") or f"{i}/{len(slides)}" + ("  →" if i < len(slides) else "")
        if spec.get("theme", {}).get("handle"):
            footer = f"{spec['theme']['handle']}   ·   {footer}"
        merged = {**spec, **slide, "footer": footer}
        merged["theme"] = {**spec.get("theme", {}), **slide.get("theme", {})}
        paths.append(render_post(merged, out_dir / f"slide_{i:02d}.png"))
    return paths
