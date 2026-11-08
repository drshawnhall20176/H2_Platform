"""Nov 7 7:50pm: what's still ahead tonight outside the NBA -- tested game-line picks and playable props."""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD     # noqa: E402
import components as C           # noqa: E402
import props_engine as PE        # noqa: E402
import todays_best as TB         # noqa: E402

ET = pytz.timezone("US/Eastern")
D = datetime.now(ET).strftime("%Y-%m-%d")
cut = datetime.now(timezone.utc) + timedelta(minutes=10)
PLAY = {PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE}
# game lines: tested picks + leans not yet started
rows = TB.game_rows(D)
left = [r for r in rows if (C._kick_dt(r.get("kickoff") or r.get("kick")) or cut) > cut]
print("OS game rows", len(rows), "not started", len(left), "| keys", sorted(rows[0].keys()) if rows else None)
for r in sorted(left, key=lambda r: (not r.get("tested"), -(r.get("ev") or r.get("value") or 0)))[:25]:
    print("OS GL", r.get("sport"), r.get("time"), "|", r.get("game"), "|", r.get("pick"), "| tested", r.get("tested"),
          "| chance", r.get("chance"), "| value", r.get("value"), "| price", r.get("price"), "| cover_est", r.get("cover_est"))
for sp in ("NHL", "NCAAF"):
    try:
        plays, meta, _ = BBD.load_generic_best_bets_board(sp, D, BBD.O.DEFAULT_BOOK)
    except Exception as e:
        print("OS", sp, "board failed", e)
        continue
    pp = [p for p in plays if p.get("Model") == "player-props" and p.get("Use") in PLAY
          and (C._kick_dt(p.get("GameDate")) or cut) > cut]
    print(f"OS {sp}: {len(pp)} playable-tagged props not started")
    for p in sorted(pp, key=lambda p: -(p.get("EV") or p.get("Edge") or 0))[:15]:
        k = C._kick_dt(p.get("GameDate"))
        print("OS PROP", sp, k.strftime("%-I:%M %p") if k else "", "|", p.get("Game"), "|", p["Player"], p["Market"], p["Side"], p["Line"],
              p.get("RealPrice"), f"{p['ModelProb']:.0%}", "| EV", p.get("EV"), "|", p["Use"])
