"""Poster layouts on a 12-column grid.

Every layout works at any size (square, 4:5, 9:16, landscape, A-series print) because all
measurements derive from `u` = 1% of the short side, and the margins grow to clear platform
UI (stories/reels) or the printer's safe area. Type is positioned by cap height on the
grid, hierarchy comes from scale and weight rather than effects, and each layout
leaves deliberate empty space.

Layouts: editorial, swiss, split, quote, stat, event, offer.
"""
from pathlib import Path

from PIL import Image, ImageDraw

from . import imagefx as fx
from . import typo
from .brand import load_brand
from .formats import get_format, safe_zone
from .typo import Style


class Page:
    def __init__(self, w, h, brand, bleed=0, safe=0, insets=None):
        self.brand = brand
        self.bleed = bleed
        self.w, self.h = w, h
        self.W, self.H = w + 2 * bleed, h + 2 * bleed
        self.x0 = self.y0 = bleed
        self.S = min(w, h)
        self.u = self.S / 100
        self.landscape = w > h * 1.2
        self.tall = h > w * 1.6
        m = max(6.4 * self.u, safe)
        ins = insets or {}
        self.left = self.x0 + max(m, ins.get("left", 0))
        self.right = self.x0 + w - max(m, ins.get("right", 0))
        self.top = self.y0 + max(m, ins.get("top", 0))
        self.bottom = self.y0 + h - max(m, ins.get("bottom", 0))
        self.cols, self.gut = 12, 2 * self.u
        self.colw = (self.inner_w - 11 * self.gut) / 12
        self.hair = max(1, round(self.S / 640))
        self.zoom = 1.0
        self.img = Image.new("RGB", (self.W, self.H), brand.paper)
        self.draw = ImageDraw.Draw(self.img)

    # grid ---------------------------------------------------------------------------
    @property
    def inner_w(self):
        return self.right - self.left

    def col(self, i):
        return self.left + i * (self.colw + self.gut)

    def span(self, a, b):
        n = b - a
        return n * self.colw + (n - 1) * self.gut

    def bleed_rect(self, x0, y0, x1, y1):
        """Push edges that sit on the trim out to the canvas edge, so photos run into the bleed."""
        snap = lambda v, trim, edge: edge if abs(v - trim) < 1 else v
        return (snap(x0, self.x0, 0), snap(y0, self.y0, 0),
                snap(x1, self.x0 + self.w, self.W), snap(y1, self.y0 + self.h, self.H))

    # drawing ------------------------------------------------------------------------
    def fill(self, color, rect=None):
        self.draw.rectangle(rect or (0, 0, self.W, self.H), fill=color)

    def photo(self, path, rect, focus=(0.5, 0.5), look=None, grain=None, vignette=0.0, scrims=(), duotone=None,
              zoom=None):
        x0, y0, x1, y1 = (round(v) for v in self.bleed_rect(*rect))
        img = fx.cover(Image.open(path), x1 - x0, y1 - y0, focus, zoom or self.zoom)
        if duotone:
            img = fx.duotone(img, *duotone)
        else:
            img = fx.grade(img, look if look is not None else self.brand.look)
        if vignette:
            img = fx.vignette(img, vignette)
        for edge, reach, opacity, color, *hold in scrims:
            img = fx.scrim(img, edge, reach, opacity, color, hold[0] if hold else 0.0)
        g = self.brand.grain if grain is None else grain
        if g:
            img = fx.grain(img, g, size=max(1.0, self.S / 900))
        self.img.paste(img, (x0, y0))
        return (x0, y0, x1, y1)

    def text(self, text, style, x, top, width, align="left"):
        block = typo.layout(text, style, width)
        return block, typo.draw(self.draw, block, x, top, width, align)

    def rule(self, x, y, w, color, weight=None):
        self.draw.rectangle((x, y, x + w, y + (weight or self.hair) - 1), fill=color)

    # styles -------------------------------------------------------------------------
    def label_style(self, color, size=None, tracking=90):
        return Style(self.brand.mono, size or max(1.75 * self.u, 11), tracking=tracking, upper=True,
                     color=color, balance=False, leading=1.4)

    def body_style(self, color, size=None, strong=False):
        b = self.brand
        return Style(b.text_strong if strong else b.text, size or 2.9 * self.u, leading=1.4,
                     color=color, balance=False, tracking=-5)

    def display_style(self, color, size, em_color=None, leading=1.0, tracking=-12):
        b = self.brand
        return Style(b.display, size, tracking=tracking, leading=leading, color=color,
                     em_font=b.display_em, em_color=em_color)

    def label(self, text, x, top, color, width=None, align="left", size=None):
        if not text:
            return top
        st = self.label_style(color, size)
        block = typo.layout(text, st, width or self.inner_w)
        return typo.draw(self.draw, block, x, top, width or block.width, align)

    def wordmark(self, x, top, color, height=None, align="left", width=None):
        b = self.brand
        height = height or 3.6 * self.u
        if b.logo and Path(b.logo).exists():
            logo = Image.open(b.logo).convert("RGBA")
            logo.thumbnail((10_000, round(height * 1.25)), Image.LANCZOS)
            lx = x if align == "left" else x + (width or 0) - logo.width
            self.img.paste(logo, (round(lx), round(top)), logo)
            return top + logo.height
        if not b.name:
            return top
        st = Style(b.display, height * 1.3, tracking=-5, color=color)
        block = typo.layout(b.name, st, width or self.inner_w)
        return typo.draw(self.draw, block, x, top, width or block.width, align)

    def footer(self, color, rule_color, left=None, right=None, x=None, width=None):
        """Hairline + mono metadata row, bottom of the live area. Returns the rule's y."""
        b = self.brand
        left = left if left is not None else b.handle
        right = right if right is not None else b.url
        x = self.left if x is None else x
        width = width or self.right - x
        st = self.label_style(color)
        half = (width - self.gut) / 2
        blocks = [(typo.layout(t, st, half), bx, a) for t, bx, a in
                  ((left, x, "left"), (right, x + half + self.gut, "right")) if t]
        tallest = max((blk.height for blk, _, _ in blocks), default=typo.cap_height(st.font, st.size))
        for blk, bx, align in blocks:  # last baselines sit on the bottom margin
            typo.draw(self.draw, blk, bx, self.bottom - blk.height, half, align)
        rule_y = self.bottom - tallest - 2.6 * self.u
        self.rule(x, rule_y, width, rule_color)
        return rule_y

    def detail_grid(self, details, label_color, value_color, rule_color, per_row):
        """Label/value pairs, bottom-aligned to the live area. Returns the top of the rule."""
        u = self.u
        cw = (self.inner_w - (per_row - 1) * self.gut) / per_row
        lab = self.label_style(label_color)
        vs = self.body_style(value_color, 2.7 * u, strong=True)
        lab_h = typo.cap_height(lab.font, lab.size) + 2.4 * u
        cells = [(label, typo.layout(value, vs, cw)) for label, value in details]
        rows = [cells[i:i + per_row] for i in range(0, len(cells), per_row)]
        heights = [lab_h + max(v.height for _, v in row) for row in rows]
        gap = 4.2 * u
        y = self.bottom - sum(heights) - gap * (len(rows) - 1)
        top = y
        for row, h in zip(rows, heights):
            for i, (label, val) in enumerate(row):
                x = self.left + i * (cw + self.gut)
                self.label(label, x, y, label_color, cw)
                typo.draw(self.draw, val, x, y + lab_h)
            y += h + gap
        rule_y = top - 3.2 * u
        self.rule(self.left, rule_y, self.inner_w, rule_color)
        return rule_y


def _top_of(block, last_baseline):
    return last_baseline - block.height


def _details(c):
    out = []
    for d in c.get("details") or []:
        if isinstance(d, dict):
            out.append((d.get("label", ""), str(d.get("value", ""))))
        else:
            label, _, value = str(d).partition(":")
            out.append((label.strip(), value.strip()))
    return out


# --- layouts ------------------------------------------------------------------------

def editorial(p, c):
    """Full-bleed photograph, serif headline low on the page, masthead and folio in mono."""
    b, u = p.brand, p.u
    paper = b.paper
    # Measure the text stack bottom-up first, so the scrim is exactly as tall as the type needs.
    st_lab = p.label_style(paper)
    foot_h = max(typo.layout(t, st_lab, (p.inner_w - p.gut) / 2).height
                 for t in (c.get("footer_left", b.handle), c.get("footer_right", b.url), "x") if t)
    y = p.bottom - foot_h - 2.6 * u - 5 * u
    dek = None
    if c.get("dek"):
        st = p.body_style(_alpha(paper, b.ink, 0.86), (3.0 if not p.tall else 3.4) * u)
        dek = typo.layout(c["dek"], st, p.span(0, 9 if not p.landscape else 6))
        dek_top = _top_of(dek, y)
        y = dek_top - 5.2 * u
    st = p.display_style(paper, (15 if p.tall else 12.5) * u, em_color=paper, leading=0.98)
    head = typo.fit(c["title"], st, p.span(0, 11 if not p.landscape else 8), height=p.h * 0.36, max_lines=4)
    top = _top_of(head, y)
    k = p.label_style(paper)
    kcap = typo.cap_height(k.font, k.size)
    ky = top - kcap - 4.2 * u
    text_frac = (p.h - ((ky if c.get("kicker") else top) - p.y0) + 3 * u) / p.h
    reach = min(0.98, text_frac + 0.2)
    p.photo(c["image"], (p.x0, p.y0, p.x0 + p.w, p.y0 + p.h), c.get("focus", (0.5, 0.5)), c.get("look"),
            vignette=0.16, scrims=[("bottom", reach, 0.88, b.ink, text_frac / reach), ("top", 0.24, 0.5, b.ink)])

    p.wordmark(p.left, p.top, paper, width=p.span(0, 6))
    p.label(c.get("issue"), p.col(6), p.top, paper, p.span(6, 12), "right")
    p.footer(paper, _alpha(paper, b.ink, 0.45), c.get("footer_left"), c.get("footer_right"))
    if dek:
        typo.draw(p.draw, dek, p.left, dek_top)
    typo.draw(p.draw, head, p.left, top)
    if c.get("kicker"):
        p.rule(p.left, ky + kcap / 2 - p.hair, 3.2 * u, b.accent, p.hair * 2)
        p.label(c["kicker"], p.left + 4.6 * u, ky, paper)


def swiss(p, c):
    """Paper, one heavy grotesk, flush left, ragged right; image and dek set asymmetrically."""
    b, u = p.brand, p.u
    ink = b.ink
    p.label(c.get("kicker") or b.name, p.left, p.top, ink, p.span(0, 8))
    p.label(c.get("number"), p.col(8), p.top, ink, p.span(8, 12), "right")
    lab = p.label_style(ink)
    rule_y = p.top + typo.cap_height(lab.font, lab.size) + 2.4 * u
    p.rule(p.left, rule_y, p.inner_w, ink)

    st = Style(b.heavy, (22 if p.tall else 17) * u, tracking=-42, leading=0.9, color=ink,
               em_font=b.heavy, em_color=b.accent)
    has_img = bool(c.get("image"))
    head = typo.fit(c["title"], st, p.inner_w, height=p.h * (0.36 if has_img else 0.5), max_lines=4)
    head_top = rule_y + 6.5 * u
    last = typo.draw(p.draw, head, p.left, head_top)

    details = _details(c)
    det_top = p.bottom
    if details:
        n = len(details)
        det_top = p.detail_grid(details, b.muted, ink, ink, n if (p.landscape or n <= 3) else 2)

    area_top, area_bottom = last + 7 * u, det_top - 6 * u
    show_img = has_img and area_bottom - area_top > 18 * u
    dek_col = (0, 4) if show_img else (5, 12)
    if show_img:
        p.photo(c["image"], (p.col(4), area_top, p.x0 + p.w, area_bottom), c.get("focus", (0.5, 0.5)),
                c.get("look"), grain=b.grain * 0.6)
    if c.get("dek") and area_bottom - area_top > 4 * u:
        ds = p.body_style(ink, 2.5 * u if show_img else 2.8 * u)
        blk = typo.fit(c["dek"], ds, p.span(*dek_col), height=area_bottom - area_top, min_size=round(1.9 * u))
        if blk.height <= area_bottom - area_top:
            typo.draw(p.draw, blk, p.col(dek_col[0]), area_top)


def split(p, c):
    """Photograph on one half, typography on paper on the other."""
    b, u = p.brand, p.u
    ink = b.ink
    if p.landscape:
        mid = p.x0 + p.w * 0.5
        p.photo(c["image"], (p.x0, p.y0, mid, p.y0 + p.h), c.get("focus", (0.5, 0.5)), c.get("look"))
        x, width, top = mid + 6 * u, p.right - mid - 6 * u, p.top
    else:
        cut = p.y0 + p.h * (0.5 if not p.tall else 0.52)
        p.photo(c["image"], (p.x0, p.y0, p.x0 + p.w, cut), c.get("focus", (0.5, 0.5)), c.get("look"))
        x, width, top = p.left, p.inner_w, cut + 6.5 * u
    y = top
    if c.get("kicker"):
        y = p.label(c["kicker"], x, y, b.accent, width) + 4.2 * u
    rule_y = p.footer(b.muted, _alpha(ink, b.paper, 0.18), c.get("footer_left"), c.get("footer_right"), x, width)
    st = p.display_style(ink, 10.5 * u, em_color=b.accent, leading=1.0)
    head = typo.fit(c["title"], st, width * 0.94, height=(rule_y - y) * 0.5, max_lines=3)
    y = typo.draw(p.draw, head, x, y) + 4.8 * u
    if c.get("body"):
        bs = p.body_style(_alpha(ink, b.paper, 0.78), 2.75 * u)
        blk = typo.layout(c["body"], bs, min(width, p.span(0, 10)))
        y = typo.draw(p.draw, blk, x, y) + 4.8 * u
    if c.get("cta") and y < rule_y - 6 * u:
        cs = p.body_style(ink, 2.75 * u, strong=True)
        blk = typo.layout(f"{c['cta']}  →", cs, width)
        last = typo.draw(p.draw, blk, x, y)
        p.rule(x, last + 1.3 * u, blk.width, ink, p.hair * 2)


def quote(p, c):
    """A sentence set large, hung punctuation, attribution with a small rectangular portrait."""
    b, u = p.brand, p.u
    dark = c.get("variant", "light") == "dark"
    bg, fg = (b.ink, b.paper) if dark else (b.paper, b.ink)
    p.fill(bg)
    p.wordmark(p.left, p.top, fg, height=3 * u, width=p.span(0, 6))
    p.label(c.get("kicker"), p.col(6), p.top, b.accent, p.span(6, 12), "right")

    text = c["quote"].strip()
    if not text.startswith(("“", '"')):
        text = f"“{text}”"
    portrait_h = p.span(0, 3) * 1.25 if c.get("image") else 0
    attr_top = p.bottom - max(portrait_h, 9 * u)
    st = p.display_style(fg, 12.5 * u, em_color=b.accent, leading=1.04, tracking=-14)
    head = typo.fit(text, st, p.span(0, 12), height=attr_top - p.top - 24 * u, max_lines=7)
    typo.draw(p.draw, head, p.left, p.top + 14 * u)

    x = p.left
    if c.get("image"):
        p.photo(c["image"], (p.left, attr_top, p.left + p.span(0, 3), p.bottom), c.get("focus", (0.5, 0.35)),
                c.get("look"), grain=b.grain * 0.5)
        x = p.col(3) + p.gut * 0.5
    else:
        p.rule(p.left, attr_top - 3 * u, 6 * u, b.accent, p.hair * 2)
    ns = p.body_style(fg, 2.8 * u, strong=True)
    y = typo.draw(p.draw, typo.layout(c.get("author", ""), ns, p.right - x), x, attr_top)
    if c.get("role"):
        p.label(c["role"], x, y + 2.2 * u, _alpha(fg, bg, 0.6), p.right - x)


def stat(p, c):
    """One number carries the post. Source line keeps it honest."""
    b, u = p.brand, p.u
    dark = c.get("variant", "dark") == "dark"
    bg, fg = (b.ink, b.paper) if dark else (b.paper, b.ink)
    p.fill(bg)
    p.label(c.get("kicker"), p.left, p.top, b.accent, p.span(0, 8))
    p.wordmark(p.col(8), p.top, fg, height=2.6 * u, align="right", width=p.span(8, 12))
    rule_y = p.footer(_alpha(fg, bg, 0.6), _alpha(fg, bg, 0.25), c.get("source"), c.get("footer_right", ""))

    st = Style(b.heavy, 60 * u, tracking=-55, leading=0.9, color=fg)
    num = typo.fit(c["stat"], st, p.inner_w, max_lines=1)
    num_top = p.top + (p.bottom - p.top) * (0.2 if not p.landscape else 0.16)
    num_last = typo.draw(p.draw, num, p.left - num.style.size * 0.03, num_top)
    y = rule_y - 6 * u
    if c.get("context"):
        cs = p.body_style(_alpha(fg, bg, 0.72), 2.7 * u)
        ctx = typo.layout(c["context"], cs, p.span(0, 8 if not p.tall else 11))
        typo.draw(p.draw, ctx, p.left, _top_of(ctx, y))
        y = _top_of(ctx, y) - 5 * u
    if c.get("label"):
        ls = p.display_style(fg, 8.5 * u, em_color=b.accent, leading=1.02)
        lab = typo.fit(c["label"], ls, p.span(0, 11), height=max(y - num_last - 8 * u, 6 * u), max_lines=3)
        typo.draw(p.draw, lab, p.left, _top_of(lab, y))


def event(p, c):
    """Gig/launch poster: photo melts into ink, condensed title straddles the seam, info grid."""
    b, u = p.brand, p.u
    p.fill(b.ink)
    seam = p.y0 + p.h * (0.6 if not p.landscape else 0.66)
    p.photo(c["image"], (p.x0, p.y0, p.x0 + p.w, seam), c.get("focus", (0.5, 0.5)), c.get("look"),
            duotone=c.get("duotone"), vignette=0.12,
            scrims=[("bottom", 0.55, 1.0, b.ink), ("top", 0.22, 0.45, b.ink)])
    p.label(c.get("kicker"), p.left, p.top, b.paper, p.span(0, 8))
    p.wordmark(p.col(8), p.top, b.paper, height=2.6 * u, align="right", width=p.span(8, 12))

    details = _details(c)
    det_top = p.bottom + 3.2 * u
    if details:
        per_row = len(details) if (p.landscape or len(details) <= 2) else 2
        det_top = p.detail_grid(details, b.accent, b.paper, _alpha(b.paper, b.ink, 0.3), per_row)

    st = Style(b.condensed, 30 * u, tracking=0, leading=0.93, color=b.paper, upper=True, balance=True)
    title = typo.fit(c["title"], st, p.inner_w, height=p.h * 0.32, max_lines=3)
    sub_h = 0
    if c.get("subtitle"):
        ss = p.body_style(_alpha(b.paper, b.ink, 0.85), 3.0 * u)
        sub = typo.layout(c["subtitle"], ss, p.span(0, 10))
        sub_h = sub.height + 4 * u
    # centre the title on the seam, but never let it collide with the info grid
    top = min(seam - title.height * 0.55, det_top - 7 * u - sub_h - title.height)
    y = typo.draw(p.draw, title, p.left, top)
    if c.get("subtitle"):
        typo.draw(p.draw, sub, p.left, y + 4 * u)


def offer(p, c):
    """Retail/promo: framed product photo, headline left, price right, terms in mono."""
    b, u = p.brand, p.u
    ink = b.ink
    if p.landscape:
        p.photo(c["image"], (p.left, p.top, p.col(7) - p.gut / 2, p.bottom), c.get("focus", (0.5, 0.5)), c.get("look"))
        x, width, y = p.col(7) + p.gut, p.span(7, 12) - p.gut, p.top
    else:
        p.wordmark(p.left, p.top, ink, height=2.8 * u, width=p.span(0, 6))
        p.label(c.get("kicker"), p.col(6), p.top, b.accent, p.span(6, 12), "right")
        ph_top = p.top + 7 * u
        ph_bottom = p.y0 + p.h * (0.52 if not p.tall else 0.54)
        p.photo(c["image"], (p.left, ph_top, p.right, ph_bottom), c.get("focus", (0.5, 0.5)), c.get("look"))
        x, width, y = p.left, p.inner_w, ph_bottom + 6 * u
    if p.landscape:
        p.wordmark(x, y, ink, height=2.8 * u, width=width)
        y += 8 * u
        if c.get("kicker"):
            y = p.label(c["kicker"], x, y, b.accent, width) + 4 * u

    title_w = width * (0.58 if not p.landscape else 1)
    st = p.display_style(ink, 9 * u, em_color=b.accent, leading=1.0)
    head = typo.fit(c["title"], st, title_w, height=p.h * 0.2, max_lines=3)
    head_last = typo.draw(p.draw, head, x, y)

    price_x = x if p.landscape else x + title_w + p.gut
    price_w = width if p.landscape else width - title_w - p.gut
    py = head_last + 6 * u if p.landscape else y
    align = "left" if p.landscape else "right"
    if c.get("was"):
        ws = p.label_style(b.muted, 2.2 * u, tracking=40)
        wb = typo.layout(c["was"], ws, price_w)
        wl = typo.draw(p.draw, wb, price_x, py, price_w, align)
        sx = price_x if align == "left" else price_x + price_w - wb.width
        p.rule(sx - 0.3 * u, wl - wb.cap * 0.5 - p.hair, wb.width + 0.6 * u, b.muted, p.hair * 2)
        py = wl + 3 * u
    if c.get("price"):
        ps = Style(b.heavy, 14 * u, tracking=-40, leading=0.9, color=ink)
        pb = typo.fit(c["price"], ps, price_w, max_lines=1)
        typo.draw(p.draw, pb, price_x, py, price_w, align)

    rule_y = p.footer(b.muted, _alpha(ink, b.paper, 0.18), c.get("terms", ""), c.get("cta", None) or b.url,
                      x, width)
    if c.get("body"):
        bs = p.body_style(_alpha(ink, b.paper, 0.75), 2.5 * u)
        blk = typo.layout(c["body"], bs, title_w)
        by = head_last + 4.5 * u
        if not p.landscape and by + blk.height < rule_y - 3 * u:
            typo.draw(p.draw, blk, x, by)


LAYOUTS = {"editorial": editorial, "swiss": swiss, "split": split, "quote": quote,
           "stat": stat, "event": event, "offer": offer}

REQUIRED = {"editorial": ("title", "image"), "swiss": ("title",), "split": ("title", "image"),
            "quote": ("quote",), "stat": ("stat",), "event": ("title", "image"), "offer": ("title", "image")}


def _alpha(fg, bg, a):
    """Blend fg over bg (opaque result): keeps text colours exact in print and video."""
    f = [int(fg.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    g = [int(bg.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x * a + y * (1 - a)):02x}" for x, y in zip(f, g))


def compose_page(spec, w, h, bleed=0, safe=0, brand=None, platform=None, insets=None):
    layout = spec.get("layout", "editorial")
    if layout not in LAYOUTS:
        raise SystemExit(f"Unknown layout '{layout}'. Choose from: {', '.join(LAYOUTS)}")
    missing = [k for k in REQUIRED[layout] if not spec.get(k)]
    if missing:
        raise SystemExit(f"Layout '{layout}' needs: {', '.join(missing)}")
    brand = brand or load_brand(spec.get("brand"))
    if insets is None and not bleed:
        insets = safe_zone(w, h, platform or spec.get("platform", "stories"))
    page = Page(w, h, brand, bleed, safe, insets)
    page.zoom = float(spec.get("zoom", 1.0))
    LAYOUTS[layout](page, spec)
    return page.img


def render_poster(spec, out, brand=None):
    fmt = get_format(spec.get("format", "portrait"))
    img = compose_page(spec, fmt["w"], fmt["h"], brand=brand)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() in (".jpg", ".jpeg"):
        img.save(out, quality=94, subsampling=0, optimize=True)
    else:
        img.save(out, optimize=True)
    return out


def render_carousel(spec, out_dir, brand=None):
    """slides: [{layout, ...}, ...] sharing brand/format. Adds a 01 / 05 counter where the
    layout has a folio (footer_right / number) unless the slide sets its own."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    brand = brand or load_brand(spec.get("brand"))
    slides = spec["slides"]
    shared = {k: v for k, v in spec.items() if k != "slides"}
    paths = []
    for i, slide in enumerate(slides, 1):
        counter = f"{i:02d} / {len(slides):02d}"
        merged = {**shared, **slide}
        merged.setdefault("footer_right", counter + ("  →" if i < len(slides) else ""))
        merged.setdefault("number", counter)
        paths.append(render_poster(merged, out_dir / f"slide_{i:02d}.jpg", brand=brand))
    return paths
