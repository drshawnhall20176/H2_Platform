"""Nov 18: where tonight's four 'most probable' NBA lines come from (sportsbook, pick'em app, or neither)."""
import os, sys
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD, props_engine as PE, odds_api as O
api = BBD.get_odds_api_key()
date = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
offs = BBD.merge_offers(BBD.fetch_generic_offers("NBA", date, api))
want = {("goga bitadze", "player_rebounds"), ("javon small", "player_rebounds"), ("naji marshall", "player_rebounds"),
        ("john collins", "player_points_rebounds_assists")}
for o in offs:
    if (PE.norm_name(o["player"]), o["market"]) in want:
        print("N2", o["player"], o["market"], o["point"], "over", o.get("over"), "under", o.get("under"), "pickem", o.get("pickem"))
plays, meta, _ = BBD.load_generic_best_bets_board("NBA", date, O.DEFAULT_BOOK)
for p in plays:
    if (PE.norm_name(p.get("Player")), p.get("MarketKey")) in want:
        print("N2P", {k: p.get(k) for k in ("Player", "Market", "Side", "Line", "ModelProb", "Projection", "Use", "RealPrice", "RealPriceBook", "Source", "Basis", "LineSource", "Book", "Conviction", "Cushion", "Gap")})
