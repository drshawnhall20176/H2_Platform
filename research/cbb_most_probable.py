import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, todays_best as TB
from datetime import datetime, timezone
import pytz
d = datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
now = datetime.now(timezone.utc)
dec = TB._dec
rows = []
for r in MS.load_game_picks("NCAAMB", ungraded=True):
    if TB._et_date(r.get("kickoff")) != d or r.get("model_p") is None:
        continue
    if datetime.fromisoformat(str(r["kickoff"]).replace("Z", "+00:00")) <= now:
        continue
    hp = float(r["model_p"]); home = hp >= 0.5
    fav = r["home"] if home else r["away"]
    mp = hp if home else 1 - hp
    bp = None if r.get("fair_home") is None else (float(r["fair_home"]) if home else 1 - float(r["fair_home"]))
    price = r.get("best_home") if home else r.get("best_away")
    dd = dec(price)
    rows.append((TB._et_time(r["kickoff"]), f"{r['away']} @ {r['home']}", fav, round(mp, 3), bp and round(bp, 3), price,
                 r.get("best_home_book") if home else r.get("best_away_book"),
                 None if dd is None else round(100 * (dd - 1), 2),          # profit on $100
                 None if dd is None or bp is None else round(bp * dd - 1, 4)))
rows.sort(key=lambda x: -(x[4] or x[3]))
print("TOP BY BOOKS' CHANCE")
for x in rows[:8]:
    print("R", " | ".join(str(v) for v in x))
print("TOP IN -150..-500")
mid = [x for x in rows if x[5] is not None and -500 <= float(x[5]) <= -150]
for x in sorted(mid, key=lambda x: -(x[4] or x[3]))[:10]:
    print("M", " | ".join(str(v) for v in x))
