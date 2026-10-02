"""Pull the real source excerpts + note events for the code panel."""
import json
from pathlib import Path

B = Path(__file__).resolve().parents[1] / "blender"
NAMES = ["A", "A#", "B", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#"]


def excerpt(path, start_marker, n):
    lines = (B / path).read_text().splitlines()
    i = next(i for i, l in enumerate(lines) if start_marker in l)
    return lines[i:i + n]


piano = excerpt("piano.py", "# --- keys ---", 15)
anim = excerpt("anim.py", "def key_depth_frac(k, t", 22)
code = ["# Moonlight Sonata — III. Presto agitato · Beethoven",
        "# every key, light and frame below is computed from the score", ""] + \
       [l[4:] if l.startswith("    ") else l for l in piano] + ["", "", "# --- anim.py ---"] + anim
notes = json.load(open(B.parents[1] / "build" / "notes_b14.json"))["notes"]
ev = []
for n in notes:
    t = n["on"] + 0.25
    if t < 2.80:
        p = n["p"]
        ev.append({"t": round(t, 4), "name": f"{NAMES[(p - 21) % 12]}{(p - 12) // 12}", "v": n["v"], "k": p - 21})
hl = next(i for i, l in enumerate(code) if "u = (t - n.press0)" in l)
json.dump({"code": code, "events": ev, "hl": hl}, open(Path(__file__).parent / "code_data.json", "w"), indent=1)
print(len(code), "code lines;", len(ev), "events; highlight line", hl)
