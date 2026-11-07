import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD, model_store as MS, script_effects as SE, todays_best as TB
from datetime import datetime
import pytz
d = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
plays, meta, _ = BBD.load_generic_best_bets_board("NBA", d, BBD.O.DEFAULT_BOOK)
plays = [p for p in plays if p.get("Model") == "player-props" and p.get("Side") in ("Over", "Under") and p.get("Line") is not None]
recs = [r for r in MS.load_game_picks("NBA", ungraded=True) if TB._et_date(r.get("kickoff")) == d]
print("PLAYS", len(plays), "GAMES", len({p["Game"] for p in plays}), "LINES", len(recs))
for r in sorted(recs, key=lambda r: -abs(r.get("home_spread") or 0))[:1]:
    g = next((x for x in {p["Game"] for p in plays} if r["home"] in x and r["away"] in x), None)
    sh = SE.shares(r["home_spread"]); fav = r["home"] if r["home_spread"] < 0 else r["away"]
    print("GAME", g, "spread", r["home_spread"], {k: round(v, 3) for k, v in sh.items()})
    flips = 0
    for p in [p for p in plays if p["Game"] == g]:
        log = p.get("_game_log") or []
        mins = [float(x.get("min") or 0) for x in log[-10:] if x.get("min") is not None]
        rl = SE.role(sum(mins) / len(mins) if mins else None)
        po = p["ModelProb"] if p["Side"] == "Over" else 1 - p["ModelProb"]
        by = SE.over_by_script(po, rl, p.get("Team") == fav, p["Market"], sh)
        if len({b >= 0.5 for b in by.values()}) > 1:
            flips += 1
        if p["Market"] == "Points":
            print("  ", p["Player"], p.get("Team"), rl, p["Line"], f"model O{po:.2f}", {k: round(v, 2) for k, v in by.items()})
    print("FLIPS", flips)
