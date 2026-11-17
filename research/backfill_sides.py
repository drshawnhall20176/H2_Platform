"""Nov 17: add the Over/Under record ("sides") to each sport's latest morning review, so Today's sidebar shows it now."""
import os, sys
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as DR, postgame as PG
for sp in ("NBA", "NCAAMB", "NHL", "NFL", "NCAAF"):
    ms = MS.daily_review_mornings(sp)
    if not ms:
        print(sp, "no review"); continue
    m = ms[0]
    rep = MS.load_daily_review(sp, m) or {}
    days = DR.WEEKLY_TREND_DAYS if sp in ("NFL", "NCAAF") else DR.TREND_DAYS
    cut = (date.fromisoformat(m) - timedelta(days=days)).isoformat()
    ds = [d for d in MS.snapshot_dates(sp) if cut <= d < m]
    g = DR.grade_dates(sp, ds)
    rows = [r for rs in g.values() for r in rs]
    sides = PG.side_record(rows)
    rep.setdefault("trend", {})["sides"] = sides
    ok = MS.save_daily_review(sp, m, rep)
    print("SIDES", sp, m, sides, "saved", ok)
