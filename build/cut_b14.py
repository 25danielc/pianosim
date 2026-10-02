"""Bars 1-14 cut: performance.mid -> performance_b14.mid + notes_b14.json.

Ends on the bar-14 fermata chord (G#1-G#2-G#3, sf).  Its keys rise when the
fermata releases; the damper pedal catches it and rings on, then lifts.
Times are music seconds (video = music + 0.25).
"""
import json

import pretty_midi

BAR15 = 20.85714                 # from notes.json "bars" (fermata included)
PEDAL_DOWN = 18.95               # just after the fermata chord's attack
PEDAL_UP = 22.20

pm = pretty_midi.PrettyMIDI("performance.mid")
src = pm.instruments[0]
out = pretty_midi.PrettyMIDI(initial_tempo=168)
piano = pretty_midi.Instrument(program=0, name="piano")
keep = [n for n in src.notes if n.start < BAR15 - 1e-3]
for n in keep:
    piano.notes.append(pretty_midi.Note(n.velocity, n.pitch, n.start, n.end))
release = max(n.end for n in keep)
for c in src.control_changes:
    if c.number == 64 and c.time < PEDAL_DOWN - 0.05:
        piano.control_changes.append(c)
piano.control_changes.append(pretty_midi.ControlChange(64, 127, PEDAL_DOWN))
piano.control_changes.append(pretty_midi.ControlChange(64, 0, PEDAL_UP))
out.instruments.append(piano)
out.write("performance_b14.mid")

notes = sorted(({"p": n.pitch, "on": round(n.start, 5), "off": round(n.end, 5), "v": n.velocity}
                for n in piano.notes), key=lambda d: (d["on"], d["p"]))
ped, down = [], None
for c in sorted(piano.control_changes, key=lambda c: c.time):
    if c.value >= 64 and down is None:
        down = c.time
    elif c.value < 64 and down is not None:
        ped.append({"on": round(down, 5), "off": round(c.time, 5)}); down = None
json.dump({"source": "Mutopia #276 bars 1-14", "qpm": 168.0, "bars": 14, "lastNoteOn": notes[-1]["on"],
           "end": PEDAL_UP, "release": round(release, 5), "notes": notes, "pedal": ped},
          open("notes_b14.json", "w"), indent=1)
print(f"{len(notes)} notes, last onset {notes[-1]['on']:.3f}, keys up {release:.3f}, pedal up {PEDAL_UP}")
