"""QA: frame where each key passes 50% depth vs the frame containing its onset (60 fps)."""
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import anim
from lib import FPS

hist, worst = {}, []
for k, lst in enumerate(anim.KEYS):
    for n in lst:
        onset_f = math.ceil(n.on * FPS - 1e-9)
        thr = 0.5
        found = None
        for f in range(onset_f - 4, onset_f + 5):
            if anim.key_depth_frac(k, f / FPS) > thr and anim.key_depth_frac(k, (f - 1) / FPS) <= thr:
                found = f
                break
        d = 99 if found is None else found - onset_f
        hist[d] = hist.get(d, 0) + 1
        if abs(d) > 1:
            worst.append((round(n.on, 3), k + 21, d))
print("KEYQA notes", sum(hist.values()), "hist", dict(sorted(hist.items())))
print("KEYQA outside +-1 frame:", worst[:20])
