"""Nov 17: set each sport's Overs gate now (the morning review keeps it current from tomorrow)."""
import os, sys
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as DR, watch as W
gate = MS.get_setting(W.OVERS_KEY, {}) or {}
for sp in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"):
    days = DR.WEEKLY_TREND_DAYS if sp in ("NFL", "NCAAF") else DR.TREND_DAYS
    cut = (date.fromisoformat("2026-11-17") - timedelta(days=days)).isoformat()
    ds = [d for d in MS.snapshot_dates(sp) if cut <= d < "2026-11-17"]
    gate = W.judge_overs(sp, DR.grade_dates(sp, ds), gate)
    print("GATE", sp, gate[sp])
print("saved", MS.save_setting(W.OVERS_KEY, gate))
