import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone
import model_store as MS, pick_ledger as PL, todays_best as TB
now = datetime.now(timezone.utc).isoformat()
rs=[p for p in MS.load_game_picks("NCAAMB") if str(p.get("kickoff") or "") > now and p.get("model_margin") is not None and p.get("home_spread") is not None]
e=[r["model_margin"]+r["home_spread"] for r in rs]
print(f"NCAAMB upcoming {len(rs)}: lean home {sum(x>0 for x in e)}, away {sum(x<0 for x in e)}, avg model-minus-book {sum(e)/max(1,len(e)):+.2f}, neutral {sum(bool(r.get('neutral')) for r in rs)}")
for r in TB.winner_rows("2026-11-22", leagues=["NCAAMB"]):
    if r.get("money") or "South Alabama" in r.get("game","") or "Dayton" in r.get("game",""):
        f=r.get("_full") or {}
        print("  ", r.get("time"), r.get("game"), "| 💰" if r.get("money") else "|", r.get("money_pick"), r.get("money_price"), "chance", r.get("money_chance") and round(r["money_chance"],3), "score", r.get("money_score") and round(r["money_score"],3), "| model", f.get("model_margin"), "book", f.get("home_spread"), "neutral" if f.get("neutral") else "")
cands = PL.game_candidates("2026-11-22")
print("game candidates now:", [(c.get("pick"), c.get("price"), round(c.get("earned") or 0,3)) for c in cands])
nfl=[p for p in MS.load_game_picks("NFL") if str(p.get("kickoff") or "") > now]
print("NFL upcoming", len(nfl), "neutral", sum(bool(p.get("neutral")) for p in nfl), "lean home", sum((p["model_margin"]+p["home_spread"])>0 for p in nfl if p.get("home_spread") is not None))
