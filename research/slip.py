import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
from datetime import datetime, timezone
now = datetime.now(timezone.utc).isoformat()
for p in MS.load_game_picks("NFL"):
    if str(p.get("kickoff",""))[:10] in ("2026-11-22","2026-11-23"):
        print("G", p.get("kickoff","")[11:16], p["away"], "@", p["home"], "| model home margin", p.get("model_margin"), "book home spread", p.get("home_spread"), "| model home win", p.get("model_p"), "market", round(p["fair_home"],3) if p.get("fair_home") else None, "| ML", p.get("best_home"), p.get("best_away"), "neutral" if p.get("neutral") else "")
