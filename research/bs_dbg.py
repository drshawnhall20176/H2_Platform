import sys
from datetime import date, timedelta
sys.path.insert(0, ".")
import bankroll_sim as BS, daily_review as DR, model_store as MS, todays_best as TB, money_score as MSC, props_engine as PE
today = PE._et_today(); since = (date.fromisoformat(today) - timedelta(days=60)).isoformat()
gb = {}
for sp in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"):
    g = DR.grade_dates(sp, [d for d in MS.snapshot_dates(sp) if since <= d < today])
    gb[sp] = [r for rs in g.values() for r in rs]
    m = [r for r in gb[sp] if r.get("result") in ("hit", "miss") and PE.snapshot_is_money(sp, r)]
    print("BD", sp, len(gb[sp]), "money", len(m), "days", len({r['slate_date'] for r in m}))
games = []
d0 = date.fromisoformat(since)
while d0 < date.fromisoformat(today):
    games += [dict(r, _day=d0.isoformat()) for r in TB.winner_rows(d0.isoformat(), leagues=list(MSC.MONEY_LEAGUES), past=True)]
    d0 += timedelta(days=1)
gm = [r for r in games if r.get("money") and r.get("money_result") in ("win", "loss")]
print("BD games", len(games), "money graded", len(gm), "days", len({r['_day'] for r in gm}))
days = BS.day_picks(gb, games)
print("BD days", len(days), "picks", sum(len(v) for v in days.values()))
rec = BS.run(gb, games)
print("BD rec", rec)
