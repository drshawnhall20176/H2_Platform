"""Nov 19: dry run of reconcile_bets.settle_open on the real Bet Log -- nothing written."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import reconcile_bets as RB, model_store as MS
from datetime import date, timedelta
for lg in RB.archives_for("INTL"):
    rs = [g for g in MS.load_results(lg, since="2026-11-17") if g["date"][:10] >= "2026-11-17"]
    for g in rs:
        print("SD final", lg, g["date"][:10], g["away_team"], g["away_points"], "@", g["home_team"], g["home_points"])
for b, g, r in RB.settle_open(apply=False):
    print("SD settle", b["id"], b.get("game"), b.get("side"), b.get("market"), b.get("line"), "->", r, "|", g["away_team"], g["away_points"], "@", g["home_team"], g["home_points"])
