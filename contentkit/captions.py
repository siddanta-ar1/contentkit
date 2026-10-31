"""Word-by-word social captions (the bouncy "active word" style) as an ASS subtitle file.

Timings come from faster-whisper when installed (`pip install faster-whisper`), which
transcribes any audio. Without it, words from a known script are spread over the audio
duration by length, which lines up well enough for TTS voiceovers.
"""
import re
import subprocess

from pathlib import Path

from .fonts import family, is_italic, weight


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
        words = []
        for seg in segments:
            for w in seg.words:
                text = w.word.strip()
                if not text:
                    continue
                # Whisper splits "12,000" into "12" + ",000": glue punctuation-led tokens back on
                if words and (text[0] in ",.%:;!?'’)" or (w.word[:1] != " " and words[-1][2][-1:].isdigit())):
                    words[-1] = (words[-1][0], w.end, words[-1][2] + text)
                else:
                    words.append((w.start, w.end, text))
        return words
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


# Caption looks. Sizes are fractions of frame width; `dim` is the alpha of words that
# aren't being spoken (0 = opaque, 255 = invisible).
STYLES = {
    # Loud uppercase with the spoken word in the accent colour. Talking-head growth content.
    "pop":   {"font": "Inter Display:black", "size": 0.085, "upper": True, "words": 3, "outline": 1 / 12,
              "shadow": 1 / 20, "dim": 0, "pop": True},
    # Sentence case, quiet, readable: brand, product, interview content.
    # Translucent plate, so it stays legible on light frames too.
    "clean": {"font": "Inter:semibold", "size": 0.056, "upper": False, "words": 6, "box": True,
              "box_alpha": 0x48, "dim": 0x70, "pop": False},
    # Solid plate behind the line: works over busy footage, accessible.
    "boxed": {"font": "Inter:semibold", "size": 0.058, "upper": False, "words": 4, "box": True,
              "dim": 0, "pop": False},
    # Editorial serif, spoken word in italic accent: lifestyle, food, fashion.
    "serif": {"font": "Instrument Serif", "size": 0.088, "upper": False, "words": 4, "outline": 0,
              "shadow": 1 / 18, "dim": 0x50, "pop": False, "italic_active": True},
}


def write_ass(words, out, w, h, font=None, color="#ffffff", accent="#ffd400", words_per_line=None,
              position=0.72, uppercase=None, size=None, style="pop", box_color="#111111"):
    """position: vertical centre of captions as a fraction of height (0.72 = lower third)."""
    st = STYLES[style]
    font = font or st["font"]
    size = size or round(w * st["size"])
    upper = st["upper"] if uppercase is None else uppercase
    per = words_per_line or st["words"]
    margin_v = max(round(h * (1 - position)) - size // 2, 0)
    if st.get("box"):
        a = st.get("box_alpha", 0)
        border, outline, shadow = 3, round(size * 0.28), 0
        outline_col, back = _ass_color(box_color, a), _ass_color(box_color, a)
    else:
        border, outline, shadow = 1, round(size * st["outline"]), round(size * st["shadow"])
        outline_col, back = "&H00000000", "&H96000000"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{family(font)},{size},{_ass_color(color, st["dim"])},{_ass_color(accent)},{outline_col},{back},{weight(font)},{-1 if is_italic(font) else 0},0,0,100,100,0,0,{border},{outline},{shadow},2,{round(w * 0.08)},{round(w * 0.08)},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    hi = _ass_color(accent)
    on = "\\1a&H00&" + ("\\i1" if st.get("italic_active") else "")
    for group in chunk(words, per):
        texts = [g[2].upper() if upper else g[2] for g in group]
        chunk_end = group[-1][1]
        for i, (start, end, _) in enumerate(group):
            end = group[i + 1][0] if i + 1 < len(group) else chunk_end
            parts = [(f"{{\\c{hi}{on}}}{t}{{\\r}}" if j == i else t) for j, t in enumerate(texts)]
            pop = r"{\fscx112\fscy112\t(0,90,\fscx100\fscy100)}" if i == 0 and st["pop"] else ""
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{pop}{' '.join(parts)}")
    out.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return out


def _srt_ts(t):
    ms = round(max(t, 0) * 1000)
    return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"


def _two_lines(text, max_chars):
    if len(text) <= max_chars:
        return text
    words = text.split()
    best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    return " ".join(words[:best]) + "\n" + " ".join(words[best:])


def write_srt(words, out, max_chars=42, max_dur=6.0, min_dur=1.0):
    """Sentence-aware subtitle file for platform upload / accessibility: at most 2 lines of
    42 characters, at most 6 s per cue (broadcast subtitling conventions)."""
    cues, cur = [], []
    for item in words:
        trial = " ".join(w[2] for w in cur + [item])
        if cur and (len(trial) > max_chars * 2 or item[1] - cur[0][0] > max_dur):
            cues.append(cur)
            cur = []
        cur.append(item)
        if re.search(r"[.!?]$", item[2]) and cur[-1][1] - cur[0][0] >= min_dur:
            cues.append(cur)
            cur = []
    if cur:
        cues.append(cur)
    blocks = []
    for n, cue in enumerate(cues, 1):
        end = cue[-1][1]
        if n < len(cues):
            end = min(max(end, cue[0][0] + min_dur), cues[n][0][0])
        text = _two_lines(" ".join(w[2] for w in cue), max_chars)
        blocks.append(f"{n}\n{_srt_ts(cue[0][0])} --> {_srt_ts(end)}\n{text}\n")
    Path(out).write_text("\n".join(blocks), encoding="utf-8")
    return Path(out)
