"""Audio post: voice cleanup, two-pass loudness mastering, silence-cut jump edits.

Voice chain (what an editor would build by hand in a DAW):
  high-pass 80 Hz          rumble, desk bumps, AC hum harmonics
  spectral denoise         steady room/fan noise, learns the noise floor as it goes
  de-mud -2 dB @ 250 Hz    boxy small-room resonance
  presence +2.5 dB @ 3.5k  intelligibility on phone speakers
  de-esser                 tames the presence boost on "s" and "sh"
  compressor 3:1           even level so captions and music ducking behave
  limiter                  no overs going into the mix
"""
import json
import re
import subprocess
from pathlib import Path

from . import ff
from .formats import ENCODE, LOUDNESS

VOICE_CHAIN = ("highpass=f=80,afftdn=nr=10:nf=-40:tn=1,"
               "equalizer=f=250:t=q:w=1.1:g=-2,equalizer=f=3500:t=q:w=1.3:g=2.5,deesser=i=0.35:f=0.55,"
               "acompressor=threshold=-21dB:ratio=3:attack=6:release=120:makeup=2.5,alimiter=limit=0.93")


def clean_voice(src, out, strength="normal"):
    chain = VOICE_CHAIN
    if strength == "light":  # already-clean sources such as TTS: no denoise, gentler dynamics
        chain = chain.replace("afftdn=nr=10:nf=-40:tn=1,", "").replace("ratio=3", "ratio=2")
    ff.run(["-i", src, "-af", f"{chain},aresample={ENCODE['audio_rate']}", "-ac", 1, out])
    return Path(out)


def measure(src, target=LOUDNESS):
    """EBU R128 first pass. Returns loudnorm's measured values."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af",
         f"loudnorm=I={target['I']}:TP={target['TP']}:LRA={target['LRA']}:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True)
    blob = proc.stderr[proc.stderr.rfind("{"):proc.stderr.rfind("}") + 1]
    return json.loads(blob)


def master(src, out, target=LOUDNESS):
    """Two-pass loudnorm: measure, then normalise linearly, so dynamics are preserved and the
    result lands on target instead of the single-pass approximation."""
    m = measure(src, target)
    ff.run(["-i", src, "-af",
            f"loudnorm=I={target['I']}:TP={target['TP']}:LRA={target['LRA']}:measured_I={m['input_i']}"
            f":measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
            f":offset={m['target_offset']}:linear=true,aresample={ENCODE['audio_rate']}",
            "-ar", ENCODE["audio_rate"], out])
    final = measure(out, target)
    return {"integrated_lufs": float(final["input_i"]), "true_peak_dbtp": float(final["input_tp"]),
            "lra": float(final["input_lra"])}


def silences(src, threshold_db=-32, min_silence=0.45):
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af",
                           f"silencedetect=noise={threshold_db}dB:d={min_silence}", "-f", "null", "-"],
                          capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[0-9.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[0-9.]+)", proc.stderr)]
    return list(zip(starts, ends + [None] * (len(starts) - len(ends))))


def keep_ranges(total, quiet, pad=0.12, min_keep=0.25):
    """Invert silences into the ranges to keep, padded so words aren't clipped."""
    keeps, cursor = [], 0.0
    for start, end in quiet:
        if start - cursor > 0:
            keeps.append((max(cursor - pad, 0), min(start + pad, total)))
        cursor = end if end is not None else total
    if total - cursor > 0:
        keeps.append((max(cursor - pad, 0), total))
    merged = []
    for a, b in keeps:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        elif b - a >= min_keep:
            merged.append((a, b))
    return merged


def silence_cut(src, out, threshold_db=-32, min_silence=0.45, pad=0.12, punch=1.0, log=print):
    """Jump-cut a talking-head recording: drop the pauses, optionally punch in on alternate cuts
    (punch=1.1 -> every other segment is a 10% closer framing, hiding the jump)."""
    src, out = Path(src), Path(out)
    total = ff.duration(src)
    keeps = keep_ranges(total, silences(src, threshold_db, min_silence), pad)
    if not keeps:
        raise SystemExit("Everything is below the silence threshold; raise --threshold.")
    vstream = next((s for s in ff.probe(src)["streams"] if s["codec_type"] == "video"), None)
    video = vstream is not None
    parts, labels = [], []
    for i, (a, b) in enumerate(keeps):
        fade = min(0.012, (b - a) / 4)
        parts.append(f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d={fade:.3f},afade=t=out:st={b - a - fade:.3f}:d={fade:.3f}[a{i}]")
        if video:
            v = f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS"
            if punch > 1 and i % 2:
                v += (f",crop=iw/{punch}:ih/{punch},scale={vstream['width']}:{vstream['height']}"
                      f":flags=lanczos,setsar=1")
            parts.append(v + f"[v{i}]")
            labels.append(f"[v{i}][a{i}]")
        else:
            labels.append(f"[a{i}]")
    n = len(keeps)
    parts.append(f"{''.join(labels)}concat=n={n}:v={1 if video else 0}:a=1" + ("[v][a]" if video else "[a]"))
    graph = out.with_suffix(".filtergraph.txt")
    graph.write_text(";\n".join(parts))
    args = ["-i", src, "-filter_complex_script", graph]
    args += (["-map", "[v]", "-c:v", "libx264", "-crf", 18, "-preset", "medium", "-pix_fmt", "yuv420p"] if video else [])
    args += ["-map", "[a]", "-c:a", "aac" if out.suffix == ".mp4" else "pcm_s16le", "-b:a", "256k", out]
    ff.run(args)
    graph.unlink()
    kept = sum(b - a for a, b in keeps)
    report = {"source": str(src), "output": str(out), "segments": [[round(a, 3), round(b, 3)] for a, b in keeps],
              "original_s": round(total, 2), "kept_s": round(kept, 2), "removed_s": round(total - kept, 2)}
    out.with_suffix(".cuts.json").write_text(json.dumps(report, indent=2))
    log(f"{n} segments, removed {total - kept:.1f}s of {total:.1f}s")
    return report
