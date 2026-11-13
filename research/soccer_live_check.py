"""Nov 13: soccer leagues + live reads against live data, into a throwaway SQLite file (prod untouched)."""
import os, sys, time
from datetime import datetime, timedelta, timezone, date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("DATABASE_URL", None)
import model_store as MS
import soccer_data as D
import soccer_picks as SP
import soccer_live as SL
db = "/tmp/soccer_check.db"
api = os.environ.get("ODDS_API_KEY", "")
for lg in ("SOCCER_NWSL", "SOCCER_BRAZIL", "SOCCER_NATIONS", "SOCCER_EFLCUP", "SOCCER_EPL", "SOCCER_UCL"):
    t = time.time()
    try:
        out = SP.capture(lg, api, db_path=db)
    except Exception as e:
        out = f"ERR {type(e).__name__}: {e}"
    print(lg, out, f"{time.time() - t:.0f}s")
    ps = SP.dedupe(MS.load_game_picks(lg, db_path=db))
    for p in ps[:2]:
        print("   ", p["home"], "v", p["away"], p.get("kickoff"), "gid", p["game_id"], "model", p.get("p_home"), p.get("p_draw"),
              "sharp", p.get("mkt_home"), "best", p.get("best_home"))
    print("   unrated:", [f"{p['home']} v {p['away']}" for p in ps if not p.get("rated")][:8])
today = datetime.now(timezone.utc).date()
n = 0
for lg in D.LEAGUES:
    gs = SL.games(lg, today)
    for g in gs:
        if g["state"] == "in":
            n += 1
            pre = SL.pregame_for(g, MS.load_game_picks(lg, db_path=db))
            r = SL.pregame_rates(pre) if pre else (1.4, 1.1)
            print("LIVE", lg, g["home"], g["home_score"], "-", g["away_score"], g["away"], g["minute"], g["detail"],
                  "reds", g["red_home"], g["red_away"], {k: round(v, 3) for k, v in SL.read(g, r, 2.5).items()})
print("live now:", n)
