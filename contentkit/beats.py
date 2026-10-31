"""Tempo, beat grid and hook detection for music-driven edits.

- onset envelope: spectral flux (how much the spectrum jumps frame to frame)
- tempo: autocorrelation of the envelope, weighted toward dance tempos (~110 BPM)
- phase: the beat offset whose grid lands on the most onsets
- hook: the most energetic window of the song (usually the drop / chorus)

Good on music with a steady pulse (pop, remixes, dance, most lok remixes). Free-tempo
material (alaap, rubato intros) has no grid to find; pass `bpm:` in the recipe then.
"""
import subprocess

import numpy as np

SR = 22050
HOP = 512


def load(path, start=0.0, duration=None):
    cmd = ["ffmpeg", "-v", "error", "-ss", str(start), "-i", str(path)]
    if duration:
        cmd += ["-t", str(duration)]
    cmd += ["-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32)


N_FFT = 2048
# Frames are stamped by their start, so an attack registers ~one window-half early.
# Measured on kick/hat tracks from 90 to 140 BPM: a constant 92 ms (±8 ms spread).
LAG = 0.092


def _norm(x):
    x = x - np.convolve(x, np.ones(16) / 16, mode="same")  # remove slow loudness drift
    x = np.maximum(x, 0)
    return x / (x.max() + 1e-9)


def onset_envelope(y, low_weight=0.0):
    """Spectral flux. With low_weight > 0 the kick/bass band (< 150 Hz) is weighted up:
    the downbeat lives there, while off-beat hi-hats dominate a plain broadband flux.
    Tempo uses the broadband flux; phase uses the kick-weighted one."""
    if len(y) < N_FFT:
        return np.zeros(1, np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(y, N_FFT)[::HOP] * np.hanning(N_FFT).astype(np.float32)
    mag = np.log1p(np.abs(np.fft.rfft(frames, axis=1)) * 10)
    diff = np.maximum(np.diff(mag, axis=0), 0)
    low = int(150 / (SR / N_FFT))
    return _norm(diff.sum(axis=1)) + low_weight * _norm(diff[:, 1:low].sum(axis=1))


def tempo(env, lo=70, hi=180, prior=110):
    fps = SR / HOP
    env = env - env.mean()
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    lags = np.arange(len(ac))
    bpms = 60 * fps / np.maximum(lags, 1)
    ok = (bpms >= lo) & (bpms <= hi)
    # log-Gaussian preference for common dance tempos resolves half/double-time ambiguity
    weight = np.exp(-0.5 * (np.log2(bpms / prior) / 0.9) ** 2)
    score = np.where(ok, ac * weight, -np.inf)
    lag = float(np.argmax(score))
    i = int(lag)
    if 1 <= i < len(ac) - 1:  # parabolic interpolation for sub-frame precision
        a, b, c = ac[i - 1], ac[i], ac[i + 1]
        lag = i + 0.5 * (a - c) / (a - 2 * b + c + 1e-12)
    return float(60 * fps / lag)


def _grid_score(env, period, off):
    idx = np.round(np.arange(off, len(env), period)).astype(int)
    return env[idx[idx < len(env)]].sum()


def phase(env, bpm):
    """Offset (s) of the first beat: the grid shift that collects the most onset energy."""
    fps = SR / HOP
    period = 60 / bpm * fps
    offs = np.linspace(0, period, 64, endpoint=False)
    best = offs[int(np.argmax([_grid_score(env, period, o) for o in offs]))]
    return (best / fps + LAG) % (60 / bpm)


def refine(env, bpm, spread=0.006, steps=25):
    """Joint tempo/phase fit: a 0.1% tempo error drifts ~45 ms over a minute of beats,
    so search a narrow tempo window together with the phase."""
    fps = SR / HOP
    best = (-1.0, bpm, 0.0)
    for b in np.linspace(bpm * (1 - spread), bpm * (1 + spread), steps):
        period = 60 / b * fps
        for o in np.linspace(0, period, 48, endpoint=False):
            sc = _grid_score(env, period, o)
            if sc > best[0]:
                best = (sc, b, o)
    _, b, o = best
    return float(b), float((o / fps + LAG) % (60 / b))


def hook(y, window=20.0):
    """Start (s) of the most energetic `window` seconds of the song."""
    if len(y) / SR <= window + 13:
        return 0.0
    q = SR // 4
    rms = np.sqrt(np.convolve(y ** 2, np.ones(q) / q, mode="valid")[::q])
    energy = np.convolve(rms, np.ones(int(window * 4)), mode="valid")
    energy[:12] = 0                      # skip the first 3 s
    if len(energy) > 40:
        energy[-40:] = 0                 # and the last 10 s (fade-outs)
    return float(np.argmax(energy)) / 4


def analyze(path, start=0.0, duration=None, bpm=None, hook_window=None):
    y = load(path, start, duration)
    kick = onset_envelope(y, low_weight=2.0)
    if bpm:
        bpm, first = float(bpm), phase(kick, float(bpm))
    else:
        bpm, first = refine(kick, tempo(onset_envelope(y)))
    out = {"bpm": round(bpm, 2), "beat": 60 / bpm, "first_beat": round(float(first), 3),
           "length": round(len(y) / SR, 2)}
    if hook_window:
        h = hook(y, hook_window)
        bar = 4 * 60 / bpm  # snap to the bar so the edit starts on a downbeat
        out["hook"] = round(float(first + max(round((h - first) / bar), 0) * bar), 3)
    return out
