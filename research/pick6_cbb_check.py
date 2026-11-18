"""Nov 18: does the odds feed carry ANY DK Pick6 college basketball props? Ask for pick6 alone, every game today."""
import os, sys
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import odds_api as O, best_bets_data as BBD
api = BBD.get_odds_api_key()
date = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
evs = [e for e in O.fetch_events_all(api, sport="basketball_ncaab") if O._eastern_date_str(e.get("commence_time")) == date]
tot = 0
for e in evs:
    js, _ = O._get(f"sports/{O.feed_for(e, 'basketball_ncaab')}/events/{e['id']}/odds",
                   {"apiKey": api, "bookmakers": "pick6", "markets": "player_points", "oddsFormat": "american"})
    n = sum(len(m.get("outcomes", [])) for b in js.get("bookmakers", []) for m in b.get("markets", []))
    tot += n
    if n: print("P6", e.get("away_team"), "@", e.get("home_team"), n)
print("P6 games", len(evs), "pick6 outcomes", tot)
js, _ = O._get("sports/basketball_nba/events", {"apiKey": api})
e = js[0]
js, _ = O._get(f"sports/basketball_nba/events/{e['id']}/odds", {"apiKey": api, "bookmakers": "pick6", "markets": "player_points", "oddsFormat": "american"})
print("P6 NBA control", e.get("home_team"), sum(len(m.get("outcomes", [])) for b in js.get("bookmakers", []) for m in b.get("markets", [])))
