"""Turn LilyPond's score-timed MIDI into the performance MIDI that drives
both the audio and the visuals.

Inputs (all generated from the Mutopia LilyPond source, see Makefile):
  perf.midi           notes + score pedal marks, ticks in score time
  events-up.notes     dynamics / text markups per staff (event-listener)
  events-down.notes

Outputs:
  performance.mid     the single source of truth (absolute seconds)
  notes.json          parsed back from performance.mid for the renderer

Interpretation added on top of the score (all deterministic):
  * velocities from the score's dynamics (p/f/ff, sf accents, cresc./decresc.)
  * fermata in bar 14 held 1.8x, gentle ritardando into the final cadence
  * excerpt ends on the bar-57 downbeat cadence; pedal held for a ring-out
"""
import json
import math
import sys

import mido
import pretty_midi

QPM = 168.0                      # half = 84
WHOLE_SEC = 4 * 60.0 / QPM       # seconds per whole note at a tempo
END_MOMENT = 56.0                # bar 57 beat 1 (moments are in whole notes)
RING_OUT = 4.0                   # seconds the last chord rings under pedal

LEVELS = {"pp": 36, "p": 50, "mp": 62, "mf": 74, "f": 92, "ff": 108}
ACCENTS = {"sf", "sfz", "fz", "fp", "sfp"}


def tempo_factor(m):
    """Duration multiplier (1 = a tempo) as a function of score moment."""
    if 13.25 <= m < 14.0:          # bar 14 fermata (dotted half)
        return 1.8
    if 55.0 <= m < 56.0:           # ritardando into the bar-57 cadence
        x = (m - 55.0)
        return 1.0 + 0.22 * x * x
    return 1.0


def build_time_map(max_m, step=1 / 768):
    """Integrate tempo_factor -> table of seconds per moment step."""
    n = int(max_m / step) + 2
    secs = [0.0] * (n + 1)
    for i in range(n):
        m = (i + 0.5) * step
        secs[i + 1] = secs[i] + step * WHOLE_SEC * tempo_factor(m)
    def to_sec(m):
        f = m / step
        i = min(int(f), n - 1)
        return secs[i] + (f - i) * (secs[i + 1] - secs[i])
    return to_sec


def read_events(path):
    out = []
    for line in open(path):
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        t = parts[0].split("-")[0]        # strip grace offset
        out.append((float(t), parts[1], parts[2]))
    return out


def dynamics_curve(events):
    """Return base_level(m) and accent(m) from score dynamics.

    Dynamics in this edition sit in the upper staff and apply to both hands
    (standard piano engraving); sf-type accents apply only at their moment.
    """
    absolutes = []   # (moment, level)
    accents = set()
    hairpins = []    # (moment, +1 cresc / -1 decresc)
    for m, kind, val in events:
        if kind == "dynamic":
            if val in ACCENTS:
                accents.add(round(m, 5))
                if val in ("fp", "sfp"):
                    absolutes.append((m + 1e-4, LEVELS["p"]))
            elif val in LEVELS:
                absolutes.append((m, LEVELS[val]))
        elif kind == "text":
            v = val.strip().lower()
            if v.endswith("decresc.") or v.endswith("dim."):
                hairpins.append((m, -1))
            elif v.endswith("cresc."):
                if v.startswith("p "):
                    absolutes.append((m, LEVELS["p"]))
                hairpins.append((m, +1))
        elif kind == "cresc" and val == "-1":
            hairpins.append((m, +1))
        elif kind == "decresc" and val == "-1":
            hairpins.append((m, -1))
    absolutes.sort()
    hairpins.sort()

    def level_at_abs(m):
        lvl = LEVELS["p"]
        for am, al in absolutes:
            if am <= m:
                lvl = al
            else:
                break
        return lvl

    def next_abs(m):
        for am, al in absolutes:
            if am > m + 1e-6:
                return am, al
        return m + 4.0, LEVELS["p"]

    # piecewise ramps: from each hairpin start to the next absolute dynamic
    ramps = []
    for hm, d in hairpins:
        start = level_at_abs(hm)
        # if a previous ramp ends after hm, start from its value at hm
        for r in ramps:
            if r[0] <= hm < r[1]:
                start = r[2] + (r[3] - r[2]) * (hm - r[0]) / (r[1] - r[0])
        end_m, nxt = next_abs(hm)
        if d > 0:
            target = min(104, max(nxt, start + 28))
        else:
            target = max(LEVELS["pp"], min(nxt, start - 18))
        ramps.append((hm, end_m, start, target))

    def base(m):
        lvl = level_at_abs(m)
        for r0, r1, a, b in ramps:
            if r0 <= m < r1:
                lvl = a + (b - a) * (m - r0) / (r1 - r0)
        return lvl

    def accent(m):
        return round(m, 5) in accents

    return base, accent


def mulberry32(seed):
    a = seed & 0xFFFFFFFF
    def rnd():
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = a
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return rnd


def main():
    mid = mido.MidiFile("perf.midi")
    tpb = mid.ticks_per_beat
    to_m = lambda ticks: ticks / (4 * tpb)

    notes = []    # (on_m, off_m, pitch, hand)
    pedal = []    # (m, value)
    for track in mid.tracks:
        hand = {"up": "R", "down": "L"}.get(track.name.rstrip(":"))
        if hand is None:
            continue
        tick, on = 0, {}
        for msg in track:
            tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                on.setdefault(msg.note, []).append(tick)
            elif msg.type in ("note_off", "note_on") and on.get(msg.note):
                s = on[msg.note].pop(0)
                notes.append((to_m(s), to_m(tick), msg.note, hand))
            elif msg.type == "control_change" and msg.control == 64:
                pedal.append((to_m(tick), msg.value))

    events = read_events("events-up.notes") + read_events("events-down.notes")
    base, accent = dynamics_curve(events)
    to_sec = build_time_map(END_MOMENT + 2)
    rnd = mulberry32(27_02)

    eps = 1e-6
    kept = [n for n in notes if n[0] <= END_MOMENT + eps]
    kept.sort(key=lambda n: (n[0], n[2]))
    end_sec = to_sec(END_MOMENT)
    final_off = end_sec + RING_OUT

    pm = pretty_midi.PrettyMIDI(resolution=960, initial_tempo=120)
    piano = pretty_midi.Instrument(program=0, name="Piano")
    for on_m, off_m, pitch, hand in kept:
        lvl = base(on_m)
        if accent(on_m):
            lvl = min(118, max(lvl + 32, 98))
        beat = (on_m * 4) % 1.0
        if abs(on_m % 1.0) < eps:
            lvl += 5                       # bar downbeat
        elif beat < eps:
            lvl += 2                       # other beats
        if hand == "L" and not accent(on_m):
            lvl -= 6                       # accompaniment under the line
        lvl += (pitch - 60) * 0.12         # light melodic contour
        lvl += (rnd() - 0.5) * 6           # seeded humanisation, +-3
        vel = int(max(20, min(120, round(lvl))))
        on_s = to_sec(on_m)
        off_s = to_sec(off_m)
        if abs(on_m - END_MOMENT) < eps:
            off_s = final_off - 0.25       # last chord: held under the pedal
        piano.notes.append(pretty_midi.Note(vel, pitch, on_s, off_s))

    for m, v in pedal:
        if m <= END_MOMENT:
            piano.control_changes.append(pretty_midi.ControlChange(64, v, to_sec(m)))
    # ring-out pedal: catch the last chord just after its attack
    piano.control_changes.append(pretty_midi.ControlChange(64, 127, end_sec + 0.03))
    piano.control_changes.append(pretty_midi.ControlChange(64, 0, final_off))
    piano.control_changes.sort(key=lambda c: c.time)
    pm.instruments.append(piano)
    pm.write("performance.mid")

    # Re-read the file we just wrote: the renderer only ever sees what the
    # synth sees.
    check = pretty_midi.PrettyMIDI("performance.mid")
    ins = check.instruments[0]
    out_notes = [
        {"p": n.pitch, "on": round(n.start, 5), "off": round(n.end, 5), "v": n.velocity}
        for n in sorted(ins.notes, key=lambda n: (n.start, n.pitch))
    ]
    ped, down = [], None
    for c in sorted(ins.control_changes, key=lambda c: c.time):
        if c.number != 64:
            continue
        if c.value >= 64 and down is None:
            down = c.time
        elif c.value < 64 and down is not None:
            ped.append({"on": round(down, 5), "off": round(c.time, 5)})
            down = None
    bars = [round(to_sec(b), 5) for b in range(0, int(END_MOMENT) + 1)]
    data = {
        "source": "Mutopia Project #276, Beethoven Op. 27 No. 2, III (CC BY-SA 2.5)",
        "qpm": QPM,
        "bars": bars,               # bars[i] = start of bar i+1, seconds
        "lastNoteOn": max(n["on"] for n in out_notes),
        "end": round(final_off, 5),
        "notes": out_notes,
        "pedal": ped,
    }
    json.dump(data, open("notes.json", "w"), separators=(",", ":"))

    vs = [n["v"] for n in out_notes]
    ps = [n["p"] for n in out_notes]
    name = pretty_midi.note_number_to_name
    print(f"notes {len(out_notes)}  pedal {len(ped)}")
    print(f"first on {out_notes[0]['on']:.3f}s  last on {data['lastNoteOn']:.3f}s  ring-out end {data['end']:.3f}s")
    print(f"pitch {min(ps)} ({name(min(ps))}) .. {max(ps)} ({name(max(ps))})")
    print(f"velocity {min(vs)}..{max(vs)}  mean {sum(vs)/len(vs):.1f}")
    print(f"bar 15 at {bars[14]:.3f}s, bar 33 at {bars[32]:.3f}s, bar 43 at {bars[42]:.3f}s, bar 57 at {to_sec(56):.3f}s")


if __name__ == "__main__":
    sys.exit(main())
