"""Bars 1-12 cut: performance.mid -> performance_b12.mid + notes_b12.json.

Keeps every note through bar 12, plus the bar-13 downbeat chord that bar 12's
line lands on.  That chord is held (keys down) and caught by the damper pedal
for a ring-out; the keys rise at RELEASE, the pedal lifts at PEDAL_UP.
Times are music seconds (video = music + 0.25).
"""
import json

import pretty_midi

B = 4 * 60 / 168                 # seconds per bar (half = 84)
BAR13 = 12 * B                   # 17.142857
RELEASE = BAR13 + 2.25           # the final chord's keys rise
PEDAL_UP = BAR13 + 2.55

pm = pretty_midi.PrettyMIDI("performance.mid")
src = pm.instruments[0]
out = pretty_midi.PrettyMIDI(initial_tempo=168)
piano = pretty_midi.Instrument(program=0, name="piano")
for n in src.notes:
    if n.start < BAR13 - 1e-4:
        piano.notes.append(pretty_midi.Note(n.velocity, n.pitch, n.start, min(n.end, BAR13 + 0.05)))
    elif abs(n.start - BAR13) < 1e-3:                       # the landing chord
        piano.notes.append(pretty_midi.Note(n.velocity, n.pitch, n.start, RELEASE))
# score pedal marks inside the excerpt, then the ring-out pedal
for c in src.control_changes:
    if c.number == 64 and c.time < BAR13 - 0.05:
        piano.control_changes.append(c)
piano.control_changes.append(pretty_midi.ControlChange(64, 0, BAR13 - 0.02))
piano.control_changes.append(pretty_midi.ControlChange(64, 127, BAR13 + 0.03))
piano.control_changes.append(pretty_midi.ControlChange(64, 0, PEDAL_UP))
out.instruments.append(piano)
out.write("performance_b12.mid")

notes = sorted(({"p": n.pitch, "on": round(n.start, 5), "off": round(n.end, 5), "v": n.velocity}
                for n in piano.notes), key=lambda d: (d["on"], d["p"]))
ped, down = [], None
for c in sorted(piano.control_changes, key=lambda c: c.time):
    if c.number != 64:
        continue
    if c.value >= 64 and down is None:
        down = c.time
    elif c.value < 64 and down is not None:
        ped.append({"on": round(down, 5), "off": round(c.time, 5)})
        down = None
json.dump({"source": "Mutopia #276 bars 1-12 (+ bar-13 downbeat)", "qpm": 168.0, "bars": 12,
           "lastNoteOn": notes[-1]["on"], "end": round(PEDAL_UP, 5), "release": round(RELEASE, 5),
           "notes": notes, "pedal": ped}, open("notes_b12.json", "w"), indent=1)
print(f"{len(notes)} notes, last onset {notes[-1]['on']:.3f}s, keys up {RELEASE:.3f}s, pedal up {PEDAL_UP:.3f}s")
