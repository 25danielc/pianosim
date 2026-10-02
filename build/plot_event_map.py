import json, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
d = json.load(open("build/event_map.json"))
t = d["loudness"]["t"]
fig, (a1, a2) = plt.subplots(2, 1, figsize=(16, 6.5), sharex=True, gridspec_kw={"height_ratios": [3, 1.3]})
fig.patch.set_facecolor("#07090F")
for a in (a1, a2):
    a.set_facecolor("#0E1A2E"); a.tick_params(colors="#CFE0FF"); [s.set_color("#33415c") for s in a.spines.values()]
a1.plot(t, d["loudness"]["M"], color="#5a6e94", lw=0.7, label="momentary LUFS (0.4 s)")
a1.plot(t, d["loudness"]["S"], color="#CFE0FF", lw=1.8, label="short-term LUFS (3 s)")
a1.set_ylim(-40, -5); a1.set_ylabel("LUFS", color="#CFE0FF")
for p in d["phrases"]:
    for a in (a1, a2): a.axvline(p["t"], color="#F2EDE3", lw=0.6, alpha=0.35)
    a1.text(p["t"] + 0.2, -6.5, f"b{p['bar']}", color="#F2EDE3", fontsize=8)
for x in d["accents"]:
    a1.plot([x["t"]], [-8.5], marker="v", color="#ffffff" if x["mark"] == "ff" else "#CFE0FF", ms=4 + 6 * x["strength"])
c = d["climax"]; r = d["reassemble"]
a1.axvspan(c["t"], r["t"], color="#CFE0FF", alpha=0.08)
a1.text(c["t"] + 0.3, -36, "come-apart", color="#CFE0FF", fontsize=9)
a2.fill_between(t, d["storm"], color="#CFE0FF", alpha=0.5); a2.set_ylim(0, 1.05); a2.set_ylabel("storm", color="#CFE0FF")
a2.set_xlabel("video time (s)", color="#CFE0FF"); a2.set_xlim(0, 91)
leg = a1.legend(loc="lower right", facecolor="#07090F", edgecolor="#33415c")
[tx.set_color("#CFE0FF") for tx in leg.get_texts()]
plt.tight_layout(); plt.savefig("out/event_map.png", dpi=110, facecolor=fig.get_facecolor())
