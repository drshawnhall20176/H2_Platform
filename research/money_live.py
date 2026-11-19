"""Nov 19: the 💰 Money pick flag on tonight's NBA board, and its record over every graded read so far."""
import os, sys
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD, odds_api as O, props_engine as PE, todays_best as TB, model_store as MS, postgame as PG, sports
date = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
plays, meta, _ = BBD.load_generic_best_bets_board("NBA", date, O.DEFAULT_BOOK)
m = [p for p in plays if PE.play_is_money("NBA", p)]
print("ML board plays", len(plays), "money", len(m), "games", len({p.get("Game") for p in m}))
for p in sorted(m, key=lambda p: -p["EV"])[:15]:
    print("ML", p["Player"], p["Market"], p["Side"], p["Line"], p["RealPrice"], p.get("RealPriceBook"), f"edge {p['EV']:+.1%}",
          f"chance {p['ModelProb']:.0%}", "|", p.get("Use"), "|", p.get("Game"))
rows = TB.props_rows("NBA", plays)
print("ML today rows", len(rows), "money rows", sum(r["money"] for r in rows), "locks", sum(r["lock"] for r in rows))
dates = MS.snapshot_dates("NBA"); snaps = MS.load_snapshots("NBA", dates); g = []
for d in sorted({s["slate_date"] for s in snaps}):
    day = [s for s in snaps if s["slate_date"] == d]
    try:
        g += PG.grade(day, PG.fetch_results("NBA", d, sorted({(s["team"], s["opp"]) for s in day})))
    except Exception:
        pass
print("ML record", PG.money_record(g))
