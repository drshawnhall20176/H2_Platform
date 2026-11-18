"""Nov 18: tonight's NBA board as the platform shows it -- shortlist singles, game lines, one-per-game parlays."""
import os, sys, json
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import odds_api as O, best_bets_data as BBD, start_here as SH, grading, sports, todays_best as TB
date = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
print("NT now", datetime.now(ZoneInfo("America/New_York")).strftime("%H:%M"))
plays, meta, _b = BBD.load_generic_best_bets_board("NBA", date, O.DEFAULT_BOOK)
plays = [p for p in plays if sports.has_started(p.get("GameDate")) is not True]
print("NT plays not started", len(plays), "games", sorted({p.get("Game") for p in plays}))
for r in SH.shortlist("NBA", plays, n=12):
    print("NT SHORT", json.dumps(r, default=str))
tagged = [p for p in plays if p.get("Use") and p.get("Use") != "Pass"]
for p in sorted(tagged, key=lambda p: -(p.get("ModelProb") or 0))[:25]:
    print("NT TAG", p.get("Use"), "|", p.get("Player"), p.get("Market"), p.get("Side"), p.get("Line"), "| p", round(p.get("ModelProb") or 0, 3),
          "| mkt", p.get("MarketProb"), "| price", p.get("RealPrice"), p.get("RealPriceBook"), "| game", p.get("Game"), p.get("Time"),
          "| warn", p.get("Warnings"), "| lean", p.get("Lean"))
for pr in grading.build_suggested_parlays(plays, max_per_game=1):
    print("NT PARLAY", pr.get("name") or pr.get("tier"), json.dumps({k: v for k, v in pr.items() if k != "legs"}, default=str)[:400])
    for l in pr["legs"]:
        print("    leg", l.get("Player"), l.get("Market"), l.get("Side"), l.get("Line"), round(l.get("ModelProb") or 0, 3), l.get("RealPrice"), l.get("Game"))
for w in TB.winner_rows(date, leagues=["NBA"]):
    print("NT GAME", json.dumps(w, default=str)[:500])
