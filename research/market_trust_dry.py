"""Nov 18: dry run of calibration.auto_trust_markets on the morning review's own window (nothing written)."""
import os, sys
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as D, calibration as CAL
today = date.today().isoformat()
for sp in ("NBA", "NHL", "NFL", "NCAAF"):
    days = D.WEEKLY_TREND_DAYS if sp in ("NFL", "NCAAF") else D.TREND_DAYS
    cut = (date.today() - timedelta(days=days)).isoformat()
    g = D.grade_dates(sp, [d for d in MS.snapshot_dates(sp) if cut <= d < today])
    print("SPORT", sp, "trust", CAL.trust(sp))
    for d in CAL.auto_trust_markets(sp, g, today, write=False):
        print("MT", sp, d["market"], "n", d["n"], "active", d["active"], "fit", d["new"], "passed", d.get("passed"), "/", d.get("splits"),
              "gain", round(d.get("gain") or 0, 5), "|", d["why"])
