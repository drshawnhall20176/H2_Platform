import os, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD, betlog as B, coach as CO, pick_records as PR, todays_best as TB
day = "2026-11-09"
bets = B.list_bets()
wl = TB.winner_rows(day)
for sport in ("NFL", "NBA", "NHL", "NCAAMB"):
    c = []
    try:
        plays, meta, _ = BBD.load_generic_best_bets_board(sport, day, BBD.O.DEFAULT_BOOK)
        print("CC", sport, "board plays", len(plays), "priced+chance", sum(1 for p in plays if p.get("RealPrice") is not None and p.get("ModelProb") is not None),
              "uses", Counter(p.get("Use") for p in plays).most_common(6))
        c += CO.prop_candidates(sport, plays, meta)
    except Exception as e:
        print("CC", sport, "board error", type(e).__name__, e)
    rows = [r for r in wl if r.get("sport") == sport]
    PR.annotate_leans(rows); c += CO.lean_candidates(rows)
    tags = PR.tag_records(sport)
    out = CO.finder(c, bets, tags)
    print("CC", sport, "cands", len(c), "verdicts", Counter(r["verdict"] for r in out), "signals", Counter(r["signal"] for r in out))
    print("CC", sport, "tag records", tags)
    print("CC", sport, "first reasons", Counter(r["why"].split(";")[0][:70] for r in out).most_common(8))
    ok = [r for r in out if not r["verdict"].startswith("🔴")][:6]
    for r in ok:
        print("CC   ", r["signal"], r["pick"], r.get("price"), CO.pct(r.get("model_chance")), CO.pts(r.get("edge")), r.get("use"), "|", r["why"][:150])
    near = sorted([r for r in out if r["verdict"].startswith("🔴") and r.get("edge") is not None], key=lambda r: -r["edge"])[:5]
    for r in near:
        print("CC  near", r["pick"], r.get("price"), CO.pct(r.get("model_chance")), CO.pts(r.get("edge")), r.get("use"), "|", r["why"][:150])
