import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intl_hoops as I, model_store as MS
from datetime import date
for lg in ("NBA", "NHL"):
    res = MS.load_results(lg, since="2025-09-01")
    neu = [g for g in res if str(g.get("neutral_site")).lower() in ("true", "1")]
    print(lg, "results", len(res), "neutral in archive", len(neu))
    for g in neu[:12]: print("  ", g["date"], g["away_team"], "@", g["home_team"])
    print(lg, "live lookup sample", I.espn_neutral(lg, date.fromisoformat(neu[0]["date"][:10])) if neu else None)
    up = []
    for d in range(0, 40):
        dd = date(2026, 11, 23).toordinal() + d
        up += [(date.fromordinal(dd).isoformat(), x) for x in I.espn_neutral(lg, date.fromordinal(dd))]
    print(lg, "upcoming neutral next 40 days", up)
