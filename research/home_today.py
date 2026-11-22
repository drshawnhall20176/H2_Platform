import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
rs=[p for p in MS.load_game_picks("NCAAMB") if str(p.get("kickoff") or "")[:10] in ("2026-11-22","2026-11-23") and p.get("model_margin") is not None and p.get("home_spread") is not None]
e=[r["model_margin"]+r["home_spread"] for r in rs]
print("today games", len(rs), "lean home", sum(x>0 for x in e), "lean away", sum(x<0 for x in e), "avg model-minus-book home %+.2f" % (sum(e)/len(e)), "neutral", sum(bool(r.get("neutral")) for r in rs))
for r in sorted(rs, key=lambda r: r["kickoff"])[:12]: print("  ", r["kickoff"][11:16], r["away"], "@", r["home"], "neutral" if r.get("neutral") else "", "model", r["model_margin"], "book", -r["home_spread"], "use", r.get("use"))
