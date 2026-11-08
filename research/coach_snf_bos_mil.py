import os, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD, betlog as B, coach as CO, pick_records as PR, todays_best as TB, football_weather as FW
day = "2026-11-08"
bets = B.list_bets()
wl = TB.winner_rows(day)
for sport, keys in (("NFL", ("CHI", "TB", "Bears", "Buccaneers")), ("NBA", ("Celtics", "Bucks", "BOS", "MIL", "Boston", "Milwaukee"))):
    plays, meta, _ = BBD.load_generic_best_bets_board(sport, day, BBD.O.DEFAULT_BOOK)
    c = CO.prop_candidates(sport, plays, meta)
    rows = [r for r in wl if r.get("sport") == sport]
    PR.annotate_leans(rows); c += CO.lean_candidates(rows)
    c = [x for x in c if any(k in str(x.get("game")) for k in keys)]
    out = CO.finder(c, bets, PR.tag_records(sport))
    print("CS", sport, len(out), Counter(r["signal"] for r in out), sorted({r["game"] for r in out}))
    if sport == "NFL" and out:
        print("CS weather", FW.label_for("NFL", day, out[0]["game"]))
    for r in out:
        if r["verdict"].startswith("🔴"):
            continue
        print("CS", r["signal"], "|", r["time"], r["game"], "|", r["pick"], r.get("price"), r.get("book"), "| model", CO.pct(r.get("model_chance")), "real", CO.pct(r.get("real_chance")), "needs", CO.pct(r.get("need")), "edge", CO.pts(r.get("edge")), "|", r.get("use"), "|", r["why"][:260])
    near = [r for r in out if r["verdict"].startswith("🔴") and (r.get("model_chance") or 0) >= 0.58][:6]
    for r in near:
        print("CS NEAR-SKIP", r["pick"], r.get("price"), CO.pct(r.get("model_chance")), "|", r["why"][:200])
