"""Edit critique: measure a finished video the way a short-form editor would judge it.

Measures with ffmpeg, then scores against targets for the kind of video:
  hook        time to the first cut (viewers decide in about a second)
  pacing      average and longest shot length
  dead air    silences inside the programme
  loudness    integrated LUFS and true peak against the -14 / -1 delivery spec
  defects     black frames, frozen stretches (unintended), wrong aspect / low resolution

Targets are working rules from short-form editing practice, not platform rules; the
report says which rule produced each note so the editor can overrule it.
"""
import json
import re
import subprocess
from pathlib import Path

from . import ff
from .audio import measure

KINDS = {
    #            first cut  avg shot     longest  ideal length
    "meme":       {"hook": 1.2, "avg": (0.4, 1.8), "max": 3.0, "len": (6, 20)},
    "remix":      {"hook": 1.5, "avg": (0.4, 1.6), "max": 2.5, "len": (7, 30)},
    "commentary": {"hook": 2.0, "avg": (1.2, 4.0), "max": 7.0, "len": (15, 60)},
    "brand":      {"hook": 2.0, "avg": (1.5, 4.0), "max": 6.0, "len": (10, 45)},
}


def _stderr(args):
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *map(str, args)], capture_output=True,
                          text=True).stderr


def cuts(src, threshold=5.0, min_gap=0.2):
    """Perceptible cuts. Frames are compared as 48-px blurred thumbnails, so on-beat zoom
    pulses, grain and small camera moves don't register; a jump between two near-identical
    framings of the same action doesn't either (viewers don't read it as a new shot)."""
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-an", "-vf",
                           "scale=48:-2,gblur=sigma=1.5,scdet=threshold=1,metadata=print:file=-",
                           "-f", "null", "-"], capture_output=True, text=True)
    times, last = [], None
    t = None
    for line in proc.stdout.splitlines():
        if "pts_time:" in line:
            t = float(line.rsplit("pts_time:", 1)[1])
            continue
        if not line.startswith("lavfi.scd.score=") or t is None:
            continue
        score = float(line.split("=", 1)[1])
        if score >= threshold and t > 0.1 and (last is None or t - last >= min_gap):
            times.append(t)
            last = t
    return times


def silences(src, noise=-45, d=0.8):
    err = _stderr(["-i", src, "-vn", "-af", f"silencedetect=noise={noise}dB:d={d}", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", err)]
    return list(zip(starts, ends))


def blacks(src):
    err = _stderr(["-i", src, "-an", "-vf", "blackdetect=d=0.2:pix_th=0.08", "-f", "null", "-"])
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([0-9.]+) black_end:([0-9.]+)", err)]


def freezes(src, d=1.5):
    err = _stderr(["-i", src, "-an", "-vf", f"freezedetect=n=0.002:d={d}", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"freeze_start: ([0-9.]+)", err)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([0-9.]+)", err)]
    return list(zip(starts, ends + [None] * (len(starts) - len(ends))))


def analyze(src, kind="meme"):
    src = Path(src)
    t = KINDS[kind]
    info = ff.probe(src)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    dur = float(info["format"]["duration"])
    w, h = int(v["width"]), int(v["height"])
    cut_times = cuts(src)
    bounds = [0.0] + cut_times + [dur]
    shots = [b - a for a, b in zip(bounds, bounds[1:]) if b - a > 0.04]
    loud = measure(src) if has_audio else None
    quiet = [(a, b) for a, b in silences(src) if a > 0.3 and b < dur - 0.3] if has_audio else []
    report = {
        "file": src.name, "kind": kind, "duration_s": round(dur, 2), "size": f"{w}x{h}",
        "shots": len(shots), "first_cut_s": round(cut_times[0], 2) if cut_times else None,
        "avg_shot_s": round(sum(shots) / len(shots), 2), "longest_shot_s": round(max(shots), 2),
        "lufs": float(loud["input_i"]) if loud else None, "true_peak": float(loud["input_tp"]) if loud else None,
        "dead_air": [[round(a, 2), round(b, 2)] for a, b in quiet],
        "black": [[round(a, 2), round(b, 2)] for a, b in blacks(src)],
        "frozen": [[round(a, 2), round(b, 2) if b else None] for a, b in freezes(src)],
    }

    notes, score = [], 100

    def note(sev, rule, text):
        nonlocal score
        score -= {"fix": 15, "improve": 6, "info": 0}[sev]
        notes.append({"severity": sev, "rule": rule, "note": text})

    lo, hi = t["len"]
    if dur < lo:
        note("improve", "length", f"{dur:.1f}s is short for {kind}; {lo}-{hi}s gives the joke/story room to land.")
    elif dur > hi:
        note("improve", "length", f"{dur:.1f}s is long for {kind}; trim toward {hi}s. Cut the weakest shot first.")
    fc = report["first_cut_s"]
    if fc is None:
        note("fix", "hook", "No cuts detected. One unbroken shot loses short-form viewers; cut in the first second.")
    elif fc > t["hook"]:
        note("fix", "hook", f"First cut at {fc:.1f}s. Open with the strongest moment and cut by {t['hook']:.1f}s.")
    a_lo, a_hi = t["avg"]
    if report["avg_shot_s"] > a_hi:
        note("improve", "pacing", f"Average shot {report['avg_shot_s']:.1f}s is slow for {kind} (aim {a_lo}-{a_hi}s).")
    elif report["avg_shot_s"] < a_lo:
        note("improve", "pacing", f"Average shot {report['avg_shot_s']:.1f}s is frantic; let key moments breathe.")
    if report["longest_shot_s"] > t["max"]:
        i = max(range(len(shots)), key=lambda k: shots[k])
        note("improve", "pacing", f"Shot {i + 1} runs {shots[i]:.1f}s (starts {bounds[i]:.1f}s). Split it with a "
                                  "punch-in, a zoom_to, or a cutaway.")
    if loud:
        if abs(report["lufs"] + 14) > 1:
            note("fix", "loudness", f"{report['lufs']:.1f} LUFS; deliver at -14 (contentkit master FILE).")
        if report["true_peak"] > -1:
            note("fix", "loudness", f"True peak {report['true_peak']:.1f} dBTP; keep under -1 so encoders don't clip.")
    else:
        note("fix", "audio", "No audio track. Silent short-form video loses most viewers; add music or sound.")
    for a, b in quiet:
        note("improve", "dead air", f"Silence {a:.1f}-{b:.1f}s. Fill it (sfx, music) or cut it, unless it's the joke.")
    for a, b in report["black"]:
        note("fix", "black frames", f"Black frames {a:.1f}-{b:.1f}s.")
    for a, b in report["frozen"]:
        note("info", "freeze", f"Picture static {a:.1f}-{(b or dur):.1f}s. Fine for a freeze-frame gag; otherwise add motion.")
    if h < w and kind in ("meme", "remix"):
        note("improve", "format", f"{w}x{h} is landscape; Reels/TikTok/Shorts want 9:16 (format: reel).")
    if min(w, h) < 1080:
        note("improve", "resolution", f"{w}x{h}; deliver at least 1080 px on the short side.")
    report["score"] = max(score, 0)
    report["notes"] = notes
    return report


def render_text(r):
    lines = [f"{r['file']}  ·  {r['kind']}  ·  score {r['score']}/100", "",
             f"  length       {r['duration_s']}s   {r['size']}",
             f"  shots        {r['shots']}   first cut {r['first_cut_s']}s   avg {r['avg_shot_s']}s   "
             f"longest {r['longest_shot_s']}s"]
    if r["lufs"] is not None:
        lines.append(f"  loudness     {r['lufs']:.1f} LUFS   true peak {r['true_peak']:.1f} dBTP")
    lines.append("")
    if not r["notes"]:
        lines.append("  No problems found.")
    for n in r["notes"]:
        mark = {"fix": "FIX    ", "improve": "IMPROVE", "info": "note   "}[n["severity"]]
        lines.append(f"  {mark} [{n['rule']}] {n['note']}")
    return "\n".join(lines)


def save(r, path):
    Path(path).write_text(json.dumps(r, indent=2))
