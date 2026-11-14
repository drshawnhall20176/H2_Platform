import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, game_picks as GP, pick_records as PR
recs = MS.load_game_picks("NCAAF")
print("records", len(recs), "keys", sorted(recs[-1].keys()))
print("official", GP.summary(recs))
print("held", GP.summary(recs, held=True))
g = [p for p in recs if p.get("final_home") is not None or p.get("result")]
print("graded-ish", len(g))
# recompute: model side vs close line, all games with |edge|>=4 and finals
import collections
c = collections.Counter()
for p in recs:
    fh, fa = p.get("final_home"), p.get("final_away")
    line = p.get("close_line") if p.get("close_line") is not None else p.get("line")
    if fh is None or fa is None or line is None or p.get("model_margin") is None: continue
    e = p["model_margin"] - line
    if abs(e) < 4: continue
    d = (fh - fa) - line
    if d == 0: continue
    c[(p.get("week"), (d > 0) == (e > 0))] += 1
print(sorted(c.items()))
for p in [x for x in recs if x.get("result") in ("win","loss")][-8:]:
    print(p["week"], p["away"], "@", p["home"], "line", p.get("line"), "close", p.get("close_line"), "model", p["model_margin"],
          "pick", p.get("pick_label"), "final", p.get("final_away"), "-", p.get("final_home"), p.get("result"))
