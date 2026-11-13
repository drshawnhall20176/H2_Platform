"""Nov 13: what live fields FIBA pages + FIBA LiveStats (Genius) carry, and which intl leagues play today/tomorrow."""
import os, sys, json
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intl_hoops as I
now = datetime.now(timezone.utc)
for lg in ("BCL", "FEC", "EUROCUPW"):
    gs = I.fiba_season(lg, "2025")
    near = [g for g in gs if str(g.get("gameDateTimeUTC", ""))[:10] in (now.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d"))]
    live = [g for g in gs if g.get("isLive")]
    print(lg, "games", len(gs), "today/tmrw", len(near), "live", len(live))
    g = (live or near or gs[:1])[0] if gs else None
    if g:
        print("  keys:", sorted(g.keys()))
        print("  sample:", {k: g.get(k) for k in ("gameId", "gameDateTimeUTC", "isLive", "teamAScore", "teamBScore", "statusCode",
              "gameResultStatusCode", "period", "clock", "gameTime", "currentPeriod", "liveData")})
for lg in I.GENIUS_COMPS:
    ms = I.genius_games(lg)
    live = [m for m in ms if str(m.get("live")) in ("1", "True", "true")]
    near = [m for m in ms if str(m.get("matchTimeUTC", ""))[:10] in (now.strftime("%Y-%m-%d"), (now + timedelta(days=1)).strftime("%Y-%m-%d"))]
    print(lg, "matches", len(ms), "today/tmrw", len(near), "live", len(live))
    m = (live or near or ms[:1])[0] if ms else None
    if m:
        print("  keys:", sorted(m.keys()))
        print("  sample:", {k: m.get(k) for k in ("matchId", "matchTimeUTC", "matchStatus", "live", "homescore", "awayscore", "period", "clock", "periodType")})
        # per-match live data
        try:
            d = I._http(f"https://fibalivestats.dcd.shared.geniussports.com/data/{m['matchId']}/data.json")
            print("  match data keys:", sorted((d or {}).keys())[:40], {k: (d or {}).get(k) for k in ("clock", "period", "periodType", "inOT")})
        except Exception as e:
            print("  match data err", e)
# EuroLeague / EuroCup / NBL via live_games
import live_games as LG
for lg in ("EUROLEAGUE", "EUROCUP", "NBL"):
    try:
        gs = LG.euroleague_games(lg, now.date()) if lg != "NBL" else LG.espn_games(lg, now.date())
        print(lg, "today games", len(gs), [(g.get("home"), g.get("state")) for g in gs][:5])
    except Exception as e:
        print(lg, "err", e)
