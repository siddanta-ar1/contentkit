"""Typesetting: the part that makes type look set by a designer instead of dropped in.

- Tracking that keeps the font's kerning (advances measured on prefixes, not per glyph).
- Balanced line breaks for display type, no widows, greedy + widow fix for body copy.
- Blocks are positioned by cap height, so the top of the capitals sits exactly on a grid
  line instead of the invisible ascender box.
- `*word*` switches to the emphasis face (e.g. serif italic inside a serif headline).
- Smart quotes, apostrophes, dashes and ellipses; optional hanging opening quotes.
"""
import re
from dataclasses import dataclass, field
from functools import lru_cache

from PIL import ImageFont

from .fonts import font_file


@lru_cache(maxsize=512)
def load(spec, size):
    return ImageFont.truetype(font_file(spec), max(1, int(round(size))))


def smarten(text):
    text = re.sub(r"(^|[\s(\[{—–-])\"", "\\1\u201c", text)
    text = text.replace('"', "\u201d")
    text = re.sub(r"(^|[\s(\[{—–-])'", "\\1\u2018", text)
    text = text.replace("'", "\u2019")
    text = text.replace("---", "\u2014").replace("--", "\u2013").replace("...", "\u2026")
    return re.sub(r"(\d)-(\d)", "\\1\u2013\\2", text)


@dataclass
class Style:
    font: str = "Inter"
    size: float = 32
    tracking: float = 0          # thousandths of an em, like InDesign (-20 = tight display)
    leading: float = 1.2         # line height as a multiple of size
    color: str = "#111111"
    upper: bool = False
    em_font: str = None          # face for *emphasis*
    em_color: str = None
    balance: bool = True         # balanced lines (display); False = greedy (body copy)
    hang: bool = True            # hang opening quotes into the margin

    def scaled(self, size):
        return Style(**{**self.__dict__, "size": size})


@dataclass
class Word:
    text: str
    em: bool = False


@dataclass
class Block:
    lines: list
    style: Style
    widths: list = field(default_factory=list)

    @property
    def cap(self):
        return cap_height(self.style.font, self.style.size)

    @property
    def lead(self):
        return self.style.size * self.style.leading

    @property
    def height(self):
        """Cap top of the first line to baseline of the last."""
        return self.cap + self.lead * (len(self.lines) - 1) if self.lines else 0

    @property
    def width(self):
        return max(self.widths, default=0)


def cap_height(spec, size):
    box = load(spec, size).getbbox("H", anchor="ls")
    return -box[1]


def _font(style, em):
    return load(style.em_font if em and style.em_font else style.font, style.size)


def _track(style):
    return style.tracking / 1000 * style.size


def text_width(text, font, track):
    return font.getlength(text) + track * max(len(text) - 1, 0)


def _words(text, style):
    text = smarten(str(text))
    if style.upper:
        text = text.upper()
    words, em = [], False
    for raw in text.split():
        start = raw.startswith("*")
        end = raw.rstrip(".,;:!?\u201d\u2019)").endswith("*")
        clean = raw.replace("*", "")
        if start:
            em = True
        words.append(Word(clean, em and bool(style.em_font or style.em_color)))
        if end:
            em = False
    return words


def _line_width(words, style):
    track = _track(style)
    space = load(style.font, style.size).getlength(" ") + track
    return sum(text_width(w.text, _font(style, w.em), track) for w in words) + space * (len(words) - 1)


def _break(words, style, width):
    n = len(words)
    if not n:
        return []
    fits = lambda i, j: _line_width(words[i:j], style) <= width or j == i + 1
    if not style.balance:
        lines, start = [], 0
        for j in range(1, n + 1):
            if not fits(start, j):
                lines.append(words[start:j - 1])
                start = j - 1
        lines.append(words[start:])
        if len(lines) > 1 and len(lines[-1]) == 1 and len(lines[-2]) > 2:  # pull a word down to kill the widow
            lines[-1].insert(0, lines[-2].pop())
        return lines
    # Balanced: minimise squared slack over all lines, so headlines read as a shape.
    best = [0.0] + [float("inf")] * n
    prev = [0] * (n + 1)
    for j in range(1, n + 1):
        for i in range(j - 1, -1, -1):
            if not fits(i, j):
                break
            slack = width - _line_width(words[i:j], style)
            cost = best[i] + slack ** 2
            if j == n and j - i == 1 and n > 2:
                cost += width ** 2  # widow
            if cost < best[j]:
                best[j], prev[j] = cost, i
    lines, j = [], n
    while j > 0:
        lines.insert(0, words[prev[j]:j])
        j = prev[j]
    return lines


def layout(text, style, width):
    lines = _break(_words(text, style), style, width)
    return Block(lines, style, [_line_width(l, style) for l in lines])


def fit(text, style, width, height=None, max_lines=None, min_size=10):
    """Largest size (<= style.size) whose block fits width/height/max_lines."""
    lo, hi, best = min_size, int(style.size), None
    while lo <= hi:
        size = (lo + hi) // 2
        block = layout(text, style.scaled(size), width)
        ok = block.width <= width + 0.5 and (height is None or block.height <= height) \
            and (max_lines is None or len(block.lines) <= max_lines)
        if ok:
            best, lo = block, size + 1
        else:
            hi = size - 1
    return best or layout(text, style.scaled(min_size), width)


def _draw_run(draw, x, baseline, text, font, track, fill):
    if not track:
        draw.text((x, baseline), text, font=font, fill=fill, anchor="ls")
        return font.getlength(text)
    for i, ch in enumerate(text):
        # prefix advance keeps kerning pairs intact
        draw.text((x + font.getlength(text[:i]) + track * i, baseline), ch, font=font, fill=fill, anchor="ls")
    return text_width(text, font, track)


def draw(draw_ctx, block, x, top, width=None, align="left", color=None):
    """Draw with the first line's cap height at `top`. Returns the last baseline y."""
    st = block.style
    track = _track(st)
    space = load(st.font, st.size).getlength(" ") + track
    baseline = top + block.cap
    width = width or block.width
    for line, lw in zip(block.lines, block.widths):
        lx = {"left": x, "center": x + (width - lw) / 2, "right": x + width - lw}[align]
        if align == "left" and st.hang and line and line[0].text[:1] in "\u201c\u2018\"'":
            lx -= _font(st, line[0].em).getlength(line[0].text[0])
        for k, w in enumerate(line):
            fill = (st.em_color if w.em and st.em_color else None) or color or st.color
            lx += _draw_run(draw_ctx, lx, baseline, w.text, _font(st, w.em), track, fill)
            if k < len(line) - 1:
                lx += space
        baseline += block.lead
    return baseline - block.lead
