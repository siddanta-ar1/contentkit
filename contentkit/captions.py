"""Word-by-word social captions (the bouncy "active word" style) as an ASS subtitle file.

Timings come from faster-whisper when installed (`pip install faster-whisper`), which
transcribes any audio. Without it, words from a known script are spread over the audio
duration by length, which lines up well enough for TTS voiceovers.
"""
import re
import subprocess

from .fonts import family


def transcribe(audio, model="small", language=None):
    try:
        import numpy as np
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    # Decode with ffmpeg ourselves: faster-whisper's PyAV path breaks on mismatched `av` versions.
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    samples = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
    try:
        segments, _ = WhisperModel(model, device="cpu", compute_type="int8").transcribe(
            samples, word_timestamps=True, language=language, vad_filter=True)
        return [(w.start, w.end, w.word.strip()) for seg in segments for w in seg.words if w.word.strip()]
    except Exception as exc:  # model download/runtime failure: fall back to script timing
        print(f"warning: transcription failed ({exc}); using script timing")
        return None


def align_script(text, total, lead=0.1, tail=0.25):
    """Approximate word timings: duration proportional to letters, extra pause after punctuation."""
    words = text.split()
    weights = [len(re.sub(r"\W", "", w)) + 2 + (4 if re.search(r"[.!?]$", w) else 2 if w.endswith(",") else 0)
               for w in words]
    span = max(total - lead - tail, 0.1)
    t, timed = lead, []
    for word, weight in zip(words, weights):
        d = span * weight / sum(weights)
        timed.append((t, t + d, word))
        t += d
    return timed


def chunk(words, size=3):
    group = []
    for item in words:
        group.append(item)
        if len(group) >= size or re.search(r"[.!?,;:]$", item[2]):
            yield group
            group = []
    if group:
        yield group


def _ass_color(hex_color, alpha=0):
    h = hex_color.lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _ts(t):
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def write_ass(words, out, w, h, font="Inter:black", color="#ffffff", accent="#ffd400",
              words_per_line=3, position=0.72, uppercase=True, size=None):
    """position: vertical centre of captions as a fraction of height (0.72 = lower third)."""
    size = size or round(w * 0.085)
    margin_v = round(h * (1 - position)) - size // 2
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{family(font)},{size},{_ass_color(color)},{_ass_color(accent)},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{max(3, size // 12)},{max(2, size // 20)},2,{round(w * 0.06)},{round(w * 0.06)},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    hi = _ass_color(accent)
    for group in chunk(words, words_per_line):
        texts = [g[2].upper() if uppercase else g[2] for g in group]
        chunk_end = group[-1][1]
        for i, (start, end, _) in enumerate(group):
            end = group[i + 1][0] if i + 1 < len(group) else chunk_end
            parts = [(f"{{\\c{hi}}}{t}{{\\r}}" if j == i else t) for j, t in enumerate(texts)]
            pop = r"{\fscx112\fscy112\t(0,90,\fscx100\fscy100)}" if i == 0 else ""
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{pop}{' '.join(parts)}")
    out.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return out
