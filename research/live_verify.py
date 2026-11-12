"""Nov 12: Live Games on real games right now -- every league: state, clock, pre-game source, the live read, and
(tennis) the live scorecard read. Read-only."""
import os
import sys
from datetime import datetime
import pytz
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import live_games as LG     # noqa: E402
import model_store as MS    # noqa: E402

day = datetime.now(pytz.timezone("US/Eastern")).date()
for lg in ("NHL", "EUROLEAGUE", "EUROCUP", "NBL", "NBA", "NCAAMB", "NFL", "NCAAF"):
    try:
        gs = LG.games(lg, day)
    except Exception as e:                                       # noqa: BLE001
        print("LV", lg, "feed error", type(e).__name__, e)
        continue
    st = {k: sum(g["state"] == k for g in gs) for k in ("pre", "in", "post")}
    print("LV", lg, st)
    picks = MS.load_game_picks(lg) if lg not in ("NFL", "NCAAF") else []
    for g in [x for x in gs if x["state"] == "in"][:4] + [x for x in gs if x["state"] == "post"][:2]:
        pre = LG.pregame_for(g, picks) or LG.espn_pregame(lg, g.get("event_id"))
        r = LG.read_game(g, pre)
        if r:
            rd = r["read"]
            print(f"LV   {g['away']} {g['away_score']:.0f} @ {g['home']} {g['home_score']:.0f} [{LG.clock_text(g)}] "
                  f"pre={'books' if (pre or {}).get('source') == 'books' else 'lab'} home win {rd['win_home']:.0%} "
                  f"proj {rd['total'] - rd['margin']:.0f}-{rd['total'] + rd['margin']:.0f} poss {g.get('possession')}"
                  .replace("proj ", "proj (away-home)x2 "))
        else:
            print(f"LV   {g['away']} @ {g['home']} [{LG.clock_text(g)}] no read (pre={bool(pre)})")
ms = LG.tennis_matches(day)
picks = MS.load_game_picks("TENNIS")
live = [m for m in ms if m["state"] == "in"]
print("LV TENNIS", len(ms), "matches,", len(live), "live,", sum(1 for m in ms if m.get("void")), "void")
for m in live[:6]:
    p1 = LG.tennis_pregame(m, picks)
    r = LG.read_tennis(m, p1)
    print(f"LV   {m['p1']} vs {m['p2']} {LG.set_text(m)} server={m.get('server')} pre={p1} "
          f"live={'—' if not r else round(r['read']['win_a'], 3)}")
