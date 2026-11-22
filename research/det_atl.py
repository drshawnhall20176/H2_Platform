import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import collections, todays_best as TB, best_bets_data as BBD, props_engine as PE, props_money as PM
day = PE._et_today()
saved = TB.load_props("NBA", day) or {}
rows = [r for r in saved.get("rows") or [] if "Detroit" in str(r.get("game")) or "Atlanta" in str(r.get("game"))]
print("saved Today's-best rows for DET-ATL:", len(rows), "| saved at", saved.get("at"))
for r in rows: print("  ROW", r.get("pick"), r.get("price"), r.get("book"), "earned", r.get("earned"), "money", r.get("money"), "lock", r.get("lock"), "use", r.get("use"))
plays, meta, _ = BBD.load_generic_best_bets_board("NBA", day, "draftkings")
g = [p for p in plays if "Detroit" in str(p.get("Game")) or "Atlanta" in str(p.get("Game"))]
print("board plays DET-ATL:", len(g), "Use:", collections.Counter(p.get("Use") for p in g).most_common())
print("money flags:", sum(bool(PE.play_is_money("NBA", p)) for p in g))
ranked = []
for p in g:
    try: e = PM.play_earned("NBA", p)
    except Exception: e = None
    need = PM.needed(p.get("RealPrice"), bool(p.get("Pickem")) or p.get("RealPrice") is None)
    if e is not None and need is not None: ranked.append((e-need, p))
ranked.sort(key=lambda x: -x[0])
for ee, p in ranked[:10]: print(f"  {ee:+.3f}", p.get("Player"), p.get("Market"), p.get("Side"), p.get("Line"), p.get("RealPrice"), p.get("Use"), "EV", p.get("EV"))
