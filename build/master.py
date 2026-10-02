"""Hall reverb + loudness master for the FluidSynth render.

dry.wav (MIDI t=0 at sample 0)  ->  mix.wav (video timeline: music starts at LEAD)
"""
import json
import sys

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy.signal import fftconvolve, resample_poly, butter, sosfilt

LEAD = 0.25         # music starts almost immediately (X hook); title overlays bars 1-3
DURATION = 91.0     # total video length (s); audio is padded/trimmed to match
TARGET_LUFS = -14.0
CEILING_DBTP = -1.0
WET = 0.22          # light hall


def hall_ir(sr, rt60=2.3, predelay=0.018, seed=7):
    """Stereo hall impulse response: sparse early reflections + a
    decorrelated noise tail whose high end dies faster than its low end."""
    rng = np.random.default_rng(seed)
    n = int(sr * (rt60 * 1.2 + predelay))
    t = np.arange(n) / sr
    ir = np.zeros((n, 2))
    # early reflections (ms, gain) loosely modelled on a shoebox hall
    for ms, g in [(19, .55), (27, .42), (34, .38), (43, .30), (52, .26), (61, .22), (74, .18), (88, .15)]:
        for ch in range(2):
            k = int((ms + rng.uniform(-2.5, 2.5)) / 1000 * sr)
            ir[k, ch] += g * rng.choice([-1, 1])
    # late tail: two bands with different decay
    start = int((predelay + 0.04) * sr)
    tail_t = t[start:] - t[start]
    lo_sos = butter(2, 900, "low", fs=sr, output="sos")
    hi_sos = butter(2, 900, "high", fs=sr, output="sos")
    lp_sos = butter(1, 7000, "low", fs=sr, output="sos")
    for ch in range(2):
        noise = rng.standard_normal(n - start)
        lo = sosfilt(lo_sos, noise) * np.exp(-6.91 * tail_t / rt60)
        hi = sosfilt(hi_sos, noise) * np.exp(-6.91 * tail_t / (rt60 * 0.55))
        tail = sosfilt(lp_sos, lo + 0.6 * hi)
        fade_in = np.clip(tail_t / 0.06, 0, 1)
        ir[start:, ch] += 0.35 * tail * fade_in
    ir /= np.sqrt(np.sum(ir ** 2, axis=0, keepdims=True))   # unit energy per ch
    return ir


def true_peak_db(x, sr):
    up = resample_poly(x, 4, 1, axis=0)
    return 20 * np.log10(np.max(np.abs(up)) + 1e-12)


def soft_limit(x, sr, ceiling_db):
    """Look-ahead peak limiter (5 ms attack, 120 ms release). Only touches
    the few transients above the ceiling."""
    ceil = 10 ** (ceiling_db / 20) * 0.98
    peak = np.max(np.abs(x), axis=1)
    need = np.minimum(1.0, ceil / np.maximum(peak, 1e-9))
    la = int(0.005 * sr)
    # look-ahead: gain must already be down when the peak arrives
    from scipy.ndimage import minimum_filter1d
    g = minimum_filter1d(need, size=2 * la + 1, mode="nearest")
    rel = np.exp(-1 / (0.12 * sr))
    out = np.empty_like(g)
    cur = 1.0
    for i, v in enumerate(g):          # release smoothing
        cur = v if v < cur else v + (cur - v) * rel
        out[i] = cur
    att = np.ones(la) / la             # attack smoothing
    out = np.convolve(out, att, mode="same")
    out = np.minimum(out, g)
    return x * out[:, None], 20 * np.log10(out.min())


def main():
    meta = json.load(open("notes.json"))
    x, sr = sf.read("dry.wav", always_2d=True)
    assert sr == 48000
    # first audible sample vs MIDI t=0 (sync sanity)
    env = np.max(np.abs(x), axis=1)
    onset = np.argmax(env > 10 ** (-50 / 20)) / sr
    print(f"dry onset of first note: {onset * 1000:.1f} ms after MIDI t=0")

    end = meta["end"]
    keep = int((end + 3.0) * sr)
    x = x[:keep]
    ir = hall_ir(sr)
    wet = np.stack([fftconvolve(x[:, c], ir[:, c]) for c in range(2)], axis=1)[: len(x) + len(ir)]
    dry = np.vstack([x, np.zeros((len(wet) - len(x), 2))])
    y = (1 - WET) * dry + WET * wet * 0.9

    # place on the video timeline
    total = DURATION
    out = np.zeros((int(round(total * sr)), 2))
    s = int(round(LEAD * sr))
    n = min(len(y), len(out) - s)
    out[s : s + n] = y[:n]
    # gentle fade of whatever reverb remains 2.5 s after the pedal lifts
    f0 = int((LEAD + end + 1.0) * sr)
    f1 = int((LEAD + end + 3.0) * sr)
    out[f0:f1] *= np.linspace(1, 0, f1 - f0)[:, None] ** 2
    out[f1:] = 0

    meter = pyln.Meter(sr)
    lufs = meter.integrated_loudness(out)
    out *= 10 ** ((TARGET_LUFS - lufs) / 20)
    tp = true_peak_db(out, sr)
    gr = 0.0
    if tp > CEILING_DBTP:
        out, gr = soft_limit(out, sr, CEILING_DBTP)
        out *= 10 ** ((TARGET_LUFS - meter.integrated_loudness(out)) / 20)
        out, gr2 = soft_limit(out, sr, CEILING_DBTP)
        gr = min(gr, gr2)
    final_lufs = meter.integrated_loudness(out)
    final_tp = true_peak_db(out, sr)
    sf.write("mix.wav", out.astype(np.float32), sr, subtype="PCM_24")
    print(f"pre-gain {lufs:.2f} LUFS -> {final_lufs:.2f} LUFS, true peak {final_tp:.2f} dBTP, "
          f"max limiter GR {gr:.2f} dB, duration {len(out) / sr:.3f}s")


if __name__ == "__main__":
    sys.exit(main())
