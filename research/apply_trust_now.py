"""Nov 17: apply the market-trust calibration now (owner: 'force this'), same rule the morning review uses."""
import os, sys
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as DR, calibration as CAL
morning = "2026-11-17"
for sport in ("NBA", "NHL", "NFL", "NCAAF"):
    days = DR.WEEKLY_TREND_DAYS if sport in ("NFL", "NCAAF") else DR.TREND_DAYS
    cut = (date.fromisoformat(morning) - timedelta(days=days)).isoformat()
    ds = [d for d in MS.snapshot_dates(sport) if cut <= d < morning]
    g = DR.grade_dates(sport, ds)
    for d in CAL.auto_trust(sport, g, morning, write=True):
        print("TRUST", sport, d["side"], d["active"], "->", d["new"], "applied", d["applied"], "|", d["why"])
CAL.clear_cache()
for sport in ("NBA", "NHL", "NFL", "NCAAF"):
    print("NOW", sport, CAL.trust(sport), CAL.trust(sport, "Anytime TD"))
