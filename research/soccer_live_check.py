"""Nov 13: soccer_picks against live ESPN + Odds API data, into a throwaway SQLite file (prod untouched)."""
import os, sys, time
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("DATABASE_URL", None)
import model_store as MS
import soccer_data as D
import soccer_picks as SP
import soccer_props as SPR
db = "/tmp/soccer_check.db"
MS.init_db(db) if hasattr(MS, "init_db") else None
api = os.environ.get("ODDS_API_KEY", "")
for lg in ("SOCCER_EPL", "SOCCER_MLS", "SOCCER_LALIGA", "SOCCER_UCL"):
    t = time.time()
    out = SP.capture(lg, api, db_path=db)
    print(lg, out, f"{time.time() - t:.0f}s")
    rs = MS.load_results(lg, db_path=db)
    print("   results", len(rs), rs[-1] if rs else None)
    ps = MS.load_game_picks(lg, db_path=db)
    for p in ps[:3]:
        print("   ", p["home"], "v", p["away"], p.get("kickoff"), "model", p.get("p_home"), p.get("p_draw"), p.get("p_away"),
              "sharp", p.get("mkt_home"), p.get("mkt_draw"), p.get("mkt_away"), "best", p.get("best_home"), p.get("best_draw"),
              p.get("best_away"), "tot", p.get("line_total"), p.get("p_over"), p.get("mkt_over"), "ah", p.get("home_spread"),
              p.get("p_ah_home"), p.get("mkt_ah_home"), "flags", [(v["market"], v["side"], v["ev"]) for v in p.get("value", [])])
    unr = [f"{p['home']} v {p['away']}" for p in ps if not p.get("rated")]
    print("   unrated:", unr[:10])
# props for one MLS/EPL event if any
ps = MS.load_game_picks("SOCCER_MLS", db_path=db) or MS.load_game_picks("SOCCER_EPL", db_path=db)
if ps and api:
    p = ps[0]
    pr = SPR.fetch_props(p["sport"], p["game_id"], api)
    print("props", p["home"], "v", p["away"], len(pr), pr[:4])
    res = MS.load_results(p["sport"], db_path=db)
    hid = SPR.team_matches(res, p["home"]); print("home last matches", hid)
    rows = SPR.summaries(p["sport"], hid[-3:], db_path=db)
    print("summary rows", {k: len(v) for k, v in rows.items()})
    rt = SPR.rates(rows, p["home"]); print("rates sample", list(rt.items())[:3])
