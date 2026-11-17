"""Nov 17: King of the Court tonight from the model's PRA projections (the same rule the panel uses: KOTC.model_pra)."""
import os, sys, random, math
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_view as MV, kotc as K
snaps = MS = None
import model_store as MS
snaps = MS.load_snapshots("NBA", ["2026-11-17"])
reads = MV.latest_reads("NBA", "2026-11-17", snaps=snaps)
mp = K.model_pra(reads)
info = {}
for s in snaps:
    info.setdefault(MV.norm_name(s.get("player")), (s.get("player"), s.get("team"), s.get("game"), s.get("flags")))
rows = sorted(mp.items(), key=lambda kv: -kv[1])[:25]
# PRA book lines where posted
pra_line = {p: r.get("line") for (p, mk), r in reads.items() if mk == "PRA"}
random.seed(7)
names = [p for p, _ in rows]; mus = [v for _, v in rows]; sds = [max(4.0, 0.18 * v) for v in mus]
wins = [0] * len(names); N = 20000
for _ in range(N):
    draws = [random.gauss(m, s) for m, s in zip(mus, sds)]
    wins[draws.index(max(draws))] += 1
for i, (p, v) in enumerate(rows[:15]):
    pl, team, game, fl = info.get(p, (p, "", "", ""))
    print(f"K {pl:24} {team:22} proj {v:5.1f} book PRA {pra_line.get(p)} king {wins[i]/N:.1%} | {game} | {str(fl)[:90]}")
