"""Meme and commentary edits for video scenes.

Timing edits (change the clip itself), applied in this order:
  speed: 0.5            slow motion (or 2 = double speed); audio follows with atempo
  reverse: true         play backwards (keep clips short: frames are buffered)
  freeze: {at, hold}    hold one frame (the "wait for it" / record-scratch moment)
  zoom_to: {at, focus, scale, hold}   snap-zoom onto a face or detail ("dramatic zoom")

Layout edits:
  header: "POV: ..."    white caption bar on top, clip below (the tweet/POV meme format)
  split: {video, start, labels}       side-by-side / stacked comparison
  pip: {video, start, corner, size}   reaction cam in a corner

Overlays (all times are seconds into the scene):
  meme: {top, bottom}   classic white-on-black-outline meme text
  texts: [{at, until, text, position: top|center|bottom, style: meme|label|plain}]
  callouts: [{at, until, shape: circle|box|arrow, rect: [x, y, w, h], label}]
                        rect in 0-1 frame fractions: the red circle around the thing
  source: "@handle"     small credit for clipped footage

Edits that come with a sound (zoom_to: vine-boom, freeze: record-scratch) add it
automatically unless `sfx: null` is set on the edit.
"""
import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from . import typo
from .formats import safe_zone
from .layouts import Page
from .typo import Style

RED = "#ff2b2b"
TIMING_SOUNDS = {"zoom_to": "vine-boom", "freeze": "record-scratch"}


def _ease(p):
    return f"(3*pow({p},2)-2*pow({p},3))"


def _atempo(speed):
    """atempo only accepts 0.5-2.0 per stage: chain stages for anything outside."""
    parts, s = [], float(speed)
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


# --- timing ---------------------------------------------------------------------------

def source_seconds(scene, dur):
    """How much of the source clip a scene consumes (speed and freeze change it)."""
    fr = scene.get("freeze")
    hold = float(fr.get("hold", 1.0)) if fr else 0.0
    return max(dur - hold, 0.1) * float(scene.get("speed", 1.0))


def timing_video(scene, fps):
    """Filters on the decoded clip before framing: speed, reverse, freeze."""
    f = []
    if scene.get("speed", 1.0) != 1.0:
        f.append(f"setpts=PTS/{float(scene['speed'])}")
    if scene.get("reverse"):
        f.append("reverse")
    f.append(f"fps={fps},setpts=PTS-STARTPTS")
    fr = scene.get("freeze")
    if fr:
        at, hold = float(fr.get("at", 1.0)), float(fr.get("hold", 1.0))
        f.append(f"loop=loop={round(hold * fps)}:size=1:start={round(at * fps)},setpts=N/{fps}/TB")
    return f


def timing_audio(scene, src_label, dur, rate):
    """Matching audio chain (speed/reverse/freeze-as-silence). Returns filter strings, output label."""
    out = []
    chain = [f"aformat=sample_rates={rate}:channel_layouts=stereo"]
    if scene.get("speed", 1.0) != 1.0:
        chain.append(_atempo(scene["speed"]))
    if scene.get("reverse"):
        chain.append("areverse")
    chain.append(f"volume={scene.get('volume', 1.0)}")
    fr = scene.get("freeze")
    if not fr:
        out.append(f"{src_label}{','.join(chain)},apad=whole_dur={dur}[a]")
        return out
    at, hold = float(fr.get("at", 1.0)), float(fr.get("hold", 1.0))
    out.append(f"{src_label}{','.join(chain)},asplit=2[fa][fb]")
    out.append(f"[fa]atrim=0:{at},asetpts=PTS-STARTPTS[fa1]")
    out.append(f"[fb]atrim={at},asetpts=PTS-STARTPTS[fb1]")
    out.append(f"anullsrc=r={rate}:cl=stereo,atrim=0:{hold}[fgap]")
    out.append(f"[fa1][fgap][fb1]concat=n=3:v=0:a=1,apad=whole_dur={dur}[a]")
    return out


def zoom_filter(scene, w, h, fps):
    """Snap zoom (0.15 s ease) onto `focus`, held for `hold` s, then a hard cut back."""
    z = scene.get("zoom_to")
    if not z:
        return None
    at, hold = float(z.get("at", 1.0)), float(z.get("hold", 1.2))
    scale = float(z.get("scale", 2.0))
    fx, fy = z.get("focus", (0.5, 0.4))
    p = f"min(max((it-{at})/0.15,0),1)"
    on = f"between(it,{at},{at + hold})"
    zoom = f"if({on},1+{scale - 1}*{_ease(p)},1)"
    x = f"max(0,min(iw-iw/zoom,{fx}*iw-iw/zoom/2))"
    y = f"max(0,min(ih-ih/zoom,{fy}*ih-ih/zoom/2))"
    return f"zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={w}x{h}:fps={fps}"


def auto_cues(scene):
    """Sounds that belong to timing edits, as (name, seconds into scene, volume)."""
    cues = []
    for key, default in TIMING_SOUNDS.items():
        e = scene.get(key)
        if e and e.get("sfx", default):
            cues.append((e.get("sfx", default), float(e.get("at", 1.0)), float(e.get("sfx_volume", 0.8))))
    return cues


# --- overlay drawing --------------------------------------------------------------------

def _stroked(d, text, style, box, align="center", stroke=0, stroke_fill="#000000", valign="top"):
    """Auto-fitted text with an outline (meme text). box = (x, y, w, h)."""
    x, y, bw, bh = box
    blk = typo.fit(text, style, bw, height=bh, max_lines=4)
    font = typo.load(blk.style.font, blk.style.size)
    top = y if valign == "top" else y + bh - blk.height
    base = top + blk.cap
    for line, lw in zip(blk.lines, blk.widths):
        s = " ".join(wd.text for wd in line)
        lx = {"left": x, "center": x + (bw - lw) / 2, "right": x + bw - lw}[align]
        d.text((lx, base), s, font=font, fill=blk.style.color, anchor="ls", stroke_width=stroke,
               stroke_fill=stroke_fill)
        base += blk.lead
    return blk


def header_png(text, w, hh, brand, out):
    """White caption bar with dark text: the POV / tweet meme format."""
    img = Image.new("RGB", (w, hh), "#ffffff")
    d = ImageDraw.Draw(img)
    u = min(w, hh * 3) / 100
    pad = 6 * u
    st = Style("Inter:semibold", 7.2 * u, color="#111111", leading=1.22, balance=True, tracking=-8)
    blk = typo.fit(text, st, w - 2 * pad, height=hh - 2 * pad, max_lines=4)
    typo.draw(d, blk, pad, (hh - blk.height) / 2)
    img.save(out)
    return out


def meme_png(meme, w, h, platform, out):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    z = safe_zone(w, h, platform)
    u = min(w, h) / 100
    m = 4 * u
    st = Style("Anton", 11 * u, color="#ffffff", upper=True, leading=1.05, balance=True)
    stroke = max(3, round(u * 0.9))
    area_w = w - 2 * m - z["right"] * 0.5
    if meme.get("top"):
        _stroked(d, meme["top"], st, (m, z["top"] + m, area_w, h * 0.26), stroke=stroke)
    if meme.get("bottom"):
        _stroked(d, meme["bottom"], st, (m, h - z["bottom"] - m - h * 0.26, area_w, h * 0.26), stroke=stroke,
                 valign="bottom")
    img.save(out)
    return out


def text_png(t, w, h, brand, platform, out):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    p = Page(w, h, brand, insets=safe_zone(w, h, platform))
    u = p.u
    style = t.get("style", "label")
    pos = t.get("position", "center")
    box_h = h * 0.22
    y = {"top": p.top, "center": (h - box_h) / 2, "bottom": p.bottom - box_h}[pos]
    valign = "bottom" if pos == "bottom" else "top"
    if style == "meme":
        st = Style("Anton", 10 * u, color="#ffffff", upper=True, leading=1.05)
        _stroked(d, t["text"], st, (p.left, y, p.inner_w, box_h), stroke=max(3, round(u * 0.9)), valign=valign)
    elif style == "plain":
        st = Style("Inter:semibold", 6 * u, color="#ffffff", leading=1.2)
        _stroked(d, t["text"], st, (p.left, y, p.inner_w, box_h), stroke=max(2, round(u * 0.45)), valign=valign)
    else:  # label: dark plate, like an analysis annotation
        st = Style("Inter:semibold", 5 * u, color="#ffffff", leading=1.2, balance=True)
        blk = typo.fit(t["text"], st, p.inner_w * 0.86, height=box_h, max_lines=3)
        pad = 2.2 * u
        bx = (w - blk.width) / 2 - pad
        by = y + (box_h - blk.height) / 2 - pad if pos == "center" else (y if pos == "top" else y + box_h - blk.height - 2 * pad)
        d.rectangle((bx, by, bx + blk.width + 2 * pad, by + blk.height + 2 * pad + blk.style.size * 0.25),
                    fill=t.get("plate", brand.ink + "e6"))
        typo.draw(d, blk, (w - blk.width) / 2, by + pad, blk.width, "center")
    img.save(out)
    return out


def callout_png(c, w, h, out):
    """Red circle / box / arrow around a region, with an optional label."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = min(w, h) / 100
    rx, ry, rw, rh = c.get("rect", (0.35, 0.35, 0.3, 0.2))
    x0, y0, x1, y1 = rx * w, ry * h, (rx + rw) * w, (ry + rh) * h
    color = c.get("color", RED)
    lw = max(4, round(1.1 * u))
    shape = c.get("shape", "circle")
    if shape == "circle":
        pad = 1.5 * u
        d.ellipse((x0 - pad, y0 - pad, x1 + pad, y1 + pad), outline=color, width=lw)
    elif shape == "box":
        d.rectangle((x0, y0, x1, y1), outline=color, width=lw)
    if shape == "arrow" or c.get("arrow"):
        tx, ty = (x0 + x1) / 2, y0 if shape == "arrow" else y0 - 1.5 * u
        sx, sy = tx + 14 * u * (1 if tx < w / 2 else -1), ty - 16 * u
        if sy < 0:
            sy = ty + 16 * u + (y1 - y0)
            ty = y1 + 1.5 * u
        d.line((sx, sy, tx, ty), fill=color, width=lw)
        ang = math.atan2(ty - sy, tx - sx)
        head = 4.2 * u
        for da in (2.6, -2.6):
            d.line((tx, ty, tx + head * math.cos(ang + da), ty + head * math.sin(ang + da)), fill=color, width=lw)
    if c.get("label"):
        st = Style("Inter:semibold", 4.4 * u, color="#ffffff", balance=False)
        blk = typo.layout(c["label"], st, w * 0.6)
        pad = 1.6 * u
        lx = min(max(x0, 2 * u), w - blk.width - 2 * pad - 2 * u)
        ly = y1 + 2.8 * u if y1 + 2.8 * u + blk.height + 2 * pad < h * 0.8 else y0 - 2.8 * u - blk.height - 2 * pad
        d.rectangle((lx, ly, lx + blk.width + 2 * pad, ly + blk.height + 2 * pad + st.size * 0.25), fill=color)
        typo.draw(d, blk, lx + pad, ly + pad)
    img.save(out)
    return out


def source_png(text, w, h, brand, platform, out):
    p = Page(w, h, brand, insets=safe_zone(w, h, platform))
    st = Style("IBM Plex Mono:medium", max(14, 1.9 * p.u), tracking=40, color="#ffffff", balance=False)
    blk = typo.layout(text, st, w * 0.6)
    pad = 1.2 * p.u
    img = Image.new("RGBA", (round(blk.width + 2 * pad), round(blk.height + 2 * pad + st.size * 0.3)), (0, 0, 0, 150))
    typo.draw(ImageDraw.Draw(img), blk, pad, pad)
    img.save(out)
    return out, round(p.left), round(p.top)


# --- graph assembly --------------------------------------------------------------------

def overlay_graph(scene, w, h, fps, dur, brand, platform, work, i, last, n_in):
    """Timed overlays for a scene. Returns (inputs, graph parts, last label, next input index)."""
    inputs, graph = [], []

    def add_png(png, x=0, y=0, start=0.0, end=None, fade=0.12):
        nonlocal last, n_in
        inputs.extend(["-loop", 1, "-framerate", fps, "-t", dur, "-i", png])
        f = f"[{n_in}:v]format=rgba"
        if start > 0:
            f += f",fade=t=in:st={start}:d={fade}:alpha=1"
        f += f"[e{n_in}]"
        enable = f":enable='between(t,{start},{end})'" if end is not None else ""
        graph.append(f"{f};{last}[e{n_in}]overlay=x={x}:y={y}{enable}[eo{n_in}]")
        last, n_in = f"[eo{n_in}]", n_in + 1

    if scene.get("meme"):
        add_png(meme_png(scene["meme"], w, h, platform, work / f"meme_{i:03d}.png"))
    for k, t in enumerate(scene.get("texts", [])):
        add_png(text_png(t, w, h, brand, platform, work / f"text_{i:03d}_{k}.png"),
                start=float(t.get("at", 0)), end=float(t.get("until", dur)))
    for k, c in enumerate(scene.get("callouts", [])):
        add_png(callout_png(c, w, h, work / f"call_{i:03d}_{k}.png"),
                start=float(c.get("at", 0)), end=float(c.get("until", dur)), fade=0.08)
    if scene.get("source"):
        png, sx, sy = source_png(scene["source"], w, h, brand, platform, work / f"src_{i:03d}.png")
        add_png(png, sx, sy)
    return inputs, graph, last, n_in


def pip_graph(scene, w, h, fps, dur, platform, last, n_in):
    """Reaction cam in a corner. Returns (inputs, graph, last, n_in)."""
    pip = scene.get("pip")
    if not pip:
        return [], [], last, n_in
    z = safe_zone(w, h, platform)
    pw = round(w * float(pip.get("size", 0.34)) / 2) * 2
    ph = round(pw * 16 / 9 / 2) * 2 if h > w else round(pw * 9 / 16 / 2) * 2
    border = max(4, round(min(w, h) * 0.006))
    m = round(min(w, h) * 0.04)
    corner = pip.get("corner", "br")
    x = m + z["left"] if "l" in corner else w - pw - m - max(z["right"], 0)
    y = m + z["top"] if "t" in corner else h - ph - m - max(z["bottom"], 0)
    inputs = ["-ss", pip.get("start", 0), "-t", dur, "-i", pip["video"]]
    g = (f"[{n_in}:v]scale={pw}:{ph}:force_original_aspect_ratio=increase,crop={pw}:{ph},setsar=1,fps={fps},"
         f"pad={pw + 2 * border}:{ph + 2 * border}:{border}:{border}:color=white[pip{n_in}];"
         f"{last}[pip{n_in}]overlay=x={x - border}:y={y - border}:shortest=0:eof_action=pass[po{n_in}]")
    return inputs, [g], f"[po{n_in}]", n_in + 1


def split_graph(scene, w, h, fps, dur, base, n_in, brand, work, i, focus=(0.5, 0.5)):
    """Two clips stacked (vertical) or side by side, each crop-to-fill its half."""
    sp = scene.get("split")
    vertical = h > w
    hw, hh = (w, h // 2) if vertical else (w // 2, h)
    inputs = ["-ss", sp.get("start", 0), "-t", dur, "-i", sp["video"]]
    fx2, fy2 = sp.get("focus", (0.5, 0.5))
    g = [f"{base}scale={hw}:{hh}:force_original_aspect_ratio=increase,"
         f"crop={hw}:{hh}:(iw-{hw})*{focus[0]}:(ih-{hh})*{focus[1]},setsar=1[sa]",
         f"[{n_in}:v]scale={hw}:{hh}:force_original_aspect_ratio=increase,"
         f"crop={hw}:{hh}:(iw-{hw})*{fx2}:(ih-{hh})*{fy2},setsar=1,fps={fps}[sb]",
         f"[sa][sb]{'vstack' if vertical else 'hstack'}=inputs=2[sp]"]
    last, n = "[sp]", n_in + 1
    labels = sp.get("labels")
    if labels:
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        u = min(w, h) / 100
        st = Style("Inter:semibold", 4.6 * u, color="#ffffff", balance=False)
        for k, lab in enumerate(labels[:2]):
            blk = typo.layout(lab, st, w * 0.5)
            pad = 1.6 * u
            ox, oy = (0, k * hh) if vertical else (k * hw, 0)
            bx, by = ox + 3 * u, oy + 3 * u + (safe_zone(w, h)["top"] if k == 0 and vertical else 0)
            d.rectangle((bx, by, bx + blk.width + 2 * pad, by + blk.height + 2 * pad + st.size * 0.25),
                        fill=(RED if k else brand.ink + "e6"))
            typo.draw(d, blk, bx + pad, by + pad)
        png = work / f"splitlab_{i:03d}.png"
        img.save(png)
        inputs += ["-loop", 1, "-framerate", fps, "-t", dur, "-i", png]
        g.append(f"[{n}:v]format=rgba[sl];[sp][sl]overlay=0:0[spl]")
        last, n = "[spl]", n + 1
    return inputs, g, last, n


# --- premium footage fixes --------------------------------------------------------------

DENOISE = {"light": "hqdn3d=1.5:1.5:3:3", "medium": "hqdn3d=3:2.5:5:4", "strong": "nlmeans=s=3:p=5:r=11"}


def denoise_filter(scene):
    d = scene.get("denoise")
    if not d:
        return None
    return DENOISE["medium" if d is True else d]


def stabilize_prepass(scene, src, start, seconds, work, i):
    """vidstab pass 1 (motion analysis) on just the used part of the clip. Returns the
    transform filter for pass 2, or deshake when ffmpeg lacks vidstab."""
    if not scene.get("stabilize"):
        return None
    from . import ff
    filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    if "vidstabdetect" not in filters:
        return "deshake"
    trf = work / f"stab_{i:03d}.trf"
    ff.run(["-ss", start, "-t", f"{seconds:.3f}", "-i", src, "-vf",
            f"vidstabdetect=shakiness=6:accuracy=12:result={trf.name}", "-f", "null", "-"], cwd=work)
    smooth = 30 if scene["stabilize"] == "strong" else 15
    # optzoom=1 crops in just enough to hide the moving borders
    return f"vidstabtransform=input={trf.resolve()}:smoothing={smooth}:optzoom=1:interpol=bicubic"


def reframe_expr(scene, src, start, seconds, src_w, src_h, out_w, out_h, fps):
    """Auto-reframe: follow the largest face with a smoothed crop window (e.g. 16:9 -> 9:16).
    Returns (crop_w, crop_h, x_expression) or None when no faces are found."""
    from . import vision
    crop_w = min(src_w, round(src_h * out_w / out_h / 2) * 2)
    crop_h = min(src_h, round(crop_w * out_h / out_w / 2) * 2)
    if crop_w >= src_w:
        return None
    step = 0.4
    times, centers, last = [], [], 0.5
    t = 0.0
    while t <= seconds:
        f = vision.faces(vision.frame_at(src, float(start) + t, 480))
        if f is None:
            return None
        if f:
            last = f[0][0] + f[0][2] / 2
        times.append(t)
        centers.append(last)
        t += step
    if not any(c != 0.5 for c in centers):
        return None
    # smooth: moving average, so the virtual camera pans instead of jittering
    k = 3
    sm = [sum(centers[max(0, j - k):j + k + 1]) / len(centers[max(0, j - k):j + k + 1]) for j in range(len(centers))]
    xs = [min(max(c * src_w - crop_w / 2, 0), src_w - crop_w) for c in sm]
    expr = f"{xs[-1]:.1f}"
    for j in range(len(xs) - 2, -1, -1):  # piecewise-linear interpolation between samples
        t0, t1, a, b = times[j], times[j + 1], xs[j], xs[j + 1]
        expr = f"if(lt(t,{t1:.2f}),{a:.1f}+({b - a:.1f})*(t-{t0:.2f})/{t1 - t0:.2f},{expr})"
    return crop_w, crop_h, expr


# --- meme placement: green-screen clips and stickers ---------------------------------------

KEYS = {"green": "0x00d000", "blue": "0x0047bb", "black": "0x000000", "white": "0xffffff"}


def _place(position, ow, oh, w, h, platform):
    z = safe_zone(w, h, platform)
    m = round(min(w, h) * 0.04)
    pos = position or "center"
    x = {"l": m + z["left"], "c": (w - ow) // 2, "r": w - ow - m - z["right"]}
    y = {"t": m + z["top"], "c": (h - oh) // 2, "b": h - oh - m - z["bottom"]}
    key = {"center": "cc", "top": "ct", "bottom": "cb", "left": "lc", "right": "rc", "tl": "lt", "tr": "rt",
           "bl": "lb", "br": "rb", "full": "full"}[pos]
    if key == "full":
        return 0, 0
    return x[key[0]], y[key[1]]


def _cutout(image, work, i, k):
    """Background removal for stickers via rembg (pip install rembg), cached per file."""
    try:
        from rembg import remove
    except ImportError:
        raise SystemExit("`cutout: true` needs rembg: pip install 'rembg[cpu]' (or pass a PNG with transparency)")
    out = work / f"cutout_{i:03d}_{k}.png"
    out.write_bytes(remove(Path(image).read_bytes()))
    return out


def placement_graph(scene, w, h, fps, dur, platform, work, i, last, n_in):
    """`overlay:` green-screen meme clips and `stickers:` images, each with a time window."""
    inputs, graph = [], []
    for k, o in enumerate(scene.get("overlay", [])):
        at = float(o.get("at", 0))
        until = float(o.get("until", dur))
        scale = float(o.get("scale", 0.7 if o.get("position", "center") != "full" else 1.0))
        ow = round(w * scale / 2) * 2
        inputs += ["-ss", o.get("start", 0), "-t", f"{until - at:.3f}", "-i", o["video"]]
        key = o.get("key", "green")
        color = KEYS.get(key, key.replace("#", "0x"))
        sim, blend = o.get("similarity", 0.16), o.get("blend", 0.08)
        chain = f"[{n_in}:v]fps={fps},scale={ow}:-2,format=yuva420p"
        if key != "none":
            chain += f",chromakey={color}:{sim}:{blend}" + (",despill=green" if key == "green" else "")
        chain += f",setpts=PTS-STARTPTS+{at}/TB[gk{n_in}]"
        oh_guess = round(ow * 16 / 9) if o.get("tall") else round(ow * 9 / 16)
        x, y = _place(o.get("position"), ow, oh_guess, w, h, platform)
        graph.append(f"{chain};{last}[gk{n_in}]overlay=x={x}:y={y}:eof_action=pass:"
                     f"enable='between(t,{at},{until})'[go{n_in}]")
        last, n_in = f"[go{n_in}]", n_in + 1
    for k, st in enumerate(scene.get("stickers", [])):
        img = _cutout(st["image"], work, i, k) if st.get("cutout") else st["image"]
        at, until = float(st.get("at", 0)), float(st.get("until", dur))
        sw = round(w * float(st.get("scale", 0.35)) / 2) * 2
        from PIL import Image as _I
        with _I.open(img) as im:
            sh = round(sw * im.height / im.width / 2) * 2
        x, y = _place(st.get("position", "br"), sw, sh, w, h, platform)
        inputs += ["-loop", 1, "-framerate", fps, "-t", dur, "-i", img]
        graph.append(f"[{n_in}:v]format=rgba,scale={sw}:{sh}[sk{n_in}];"
                     f"{last}[sk{n_in}]overlay=x={x}:y={y}:enable='between(t,{at},{until})'[so{n_in}]")
        last, n_in = f"[so{n_in}]", n_in + 1
    return inputs, graph, last, n_in
