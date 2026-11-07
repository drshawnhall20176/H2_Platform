"""Nov 7: what the odds feed lists for UFC (the Fight Card page shows nothing today)."""
import os, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ufc_engine as E
key = os.environ.get("ODDS_API_KEY")
data, _ = E._get(f"sports/{E.UFC_SPORT}/events", {"apiKey": key})
print("UFC sport key", E.UFC_SPORT, "events", len(data or []))
print("UFC by ET date", sorted(Counter(E._eastern_date_str(e.get("commence_time")) for e in data or []).items())[:12])
for e in sorted(data or [], key=lambda e: e.get("commence_time") or "")[:16]:
    print("UFC", e.get("commence_time"), E._eastern_date_str(e.get("commence_time")), "|", e.get("away_team"), "vs", e.get("home_team"), "|", e.get("sport_title"))
print("UFC today", len(E.get_ufc_events(key, "2026-11-07")))
