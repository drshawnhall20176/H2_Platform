import sys, os, json; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, sports
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
for lg in ("NBA", "NHL", "NFL", "NCAAMB"):
    for p in MS.load_game_picks(lg):
        k = sports.game_dt(p.get("kickoff"))
        try:
            kt = datetime.fromisoformat(str(p["kickoff"]).replace("Z", "+00:00"))
        except Exception:
            continue
        if kt <= now or (kt - now).total_seconds() > 9 * 3600:
            continue
        hs, mm = p.get("home_spread"), p.get("model_margin")
        gap = None if hs is None or mm is None else round(abs(mm + hs), 2)
        mp, fh = p.get("model_p"), p.get("fair_home")
        print("A", lg, k.strftime("%I:%M %p"), p["away"], "@", p["home"], "spread", hs, "model", None if mm is None else round(mm, 2),
              "gap", gap, "winp model", None if mp is None else round(mp, 3), "market", None if fh is None else round(fh, 3),
              "total", p.get("line_total"), "mtotal", p.get("model_total"), "use", p.get("use"))
