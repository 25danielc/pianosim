"""Master the bars 1-12 cut: dry_b14.wav -> mix_b14.wav (21.0 s video timeline)."""
import json

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy.signal import fftconvolve

from master import CEILING_DBTP, LEAD, TARGET_LUFS, WET, hall_ir, soft_limit, true_peak_db

DURATION = 24.0

meta = json.load(open("notes_b14.json"))
x, sr = sf.read("dry_b14.wav", always_2d=True)
env = np.max(np.abs(x), axis=1)
print(f"dry onset of first note: {np.argmax(env > 10 ** (-50 / 20)) / sr * 1000:.1f} ms after MIDI t=0")
ir = hall_ir(sr)
wet = np.stack([fftconvolve(x[:, c], ir[:, c]) for c in range(2)], axis=1)
dry = np.vstack([x, np.zeros((len(wet) - len(x), 2))])
y = (1 - WET) * dry + WET * wet * 0.9
out = np.zeros((int(round(DURATION * sr)), 2))
s = int(round(LEAD * sr))
n = min(len(y), len(out) - s)
out[s:s + n] = y[:n]
# the hall tail fades out over the last ~1.1 s
f0 = int((LEAD + meta["end"] + 0.05) * sr)
f1 = int((DURATION - 0.05) * sr)
out[f0:f1] *= np.linspace(1, 0, f1 - f0)[:, None] ** 2
out[f1:] = 0
meter = pyln.Meter(sr)
lufs = meter.integrated_loudness(out)
out *= 10 ** ((TARGET_LUFS - lufs) / 20)
gr = 0.0
if true_peak_db(out, sr) > CEILING_DBTP:
    out, gr = soft_limit(out, sr, CEILING_DBTP)
    out *= 10 ** ((TARGET_LUFS - meter.integrated_loudness(out)) / 20)
    out, gr2 = soft_limit(out, sr, CEILING_DBTP)
    gr = min(gr, gr2)
sf.write("mix_b14.wav", out.astype(np.float32), sr, subtype="PCM_24")
print(f"{meter.integrated_loudness(out):.2f} LUFS, true peak {true_peak_db(out, sr):.2f} dBTP, "
      f"limiter {gr:.2f} dB, {len(out) / sr:.3f} s")
