"""Nov 8: does the board's chance already price blowouts? Graded board props (kickoff snapshots) by the game's
pre-game spread: actual Over rate vs the model's P(Over), per market group and favorite / underdog."""
import os, sys, json, math
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import daily_review as D, model_store as MS, script_effects as SE

out_rows = []
for sport in ("NCAAF", "NFL"):
    dates = MS.snapshot_dates(sport)
    graded = D.grade_dates(sport, dates)
    lines = SE.fetch_lines(sport, sorted(graded))
    n = 0
    for d, rows in graded.items():
        for r in rows:
            if r.get("result") not in ("hit", "miss") or r.get("chance") is None:
                continue
            teams = SE.game_teams(rows, r.get("game"))
            g = SE.game_for(teams, lines)
            strength, fav, _ = SE.line_for(teams, lines)
            if strength is None:
                continue
            fav_names = SE.fav_names(g)
            is_fav = SE.team_matches(r.get("team"), fav_names)
            p = float(r["chance"]); over = r.get("side") == "Over"
            p_over = p if over else 1 - p
            y_over = (r["result"] == "hit") == over
            out_rows.append({"sport": sport, "date": d, "market": r.get("market"), "spread": abs(float(strength)),
                             "fav": is_fav, "p_over": p_over, "y_over": int(y_over), "side": r.get("side"),
                             "use": r.get("use_tag") or r.get("use"), "player": r.get("player")})
            n += 1
    print("BR", sport, "graded rows with a spread", n, "dates", len(graded))

FAM = {"Pass Yards": "pass", "Pass Attempts": "pass", "Pass Completions": "pass", "Passing TDs": "pass",
       "Receiving Yards": "rec", "Receptions": "rec", "Rush Yards": "rush", "Rush Attempts": "rush",
       "Rush + Rec Yards": "rush", "Solo Tackles": "tkl", "Tackles + Assists": "tkl"}
def bkt(s, sport):
    cut = (3.5, 7.5, 14.5) if sport == "NFL" else (7.5, 14.5, 21.5)
    return f"<{cut[0]}" if s < cut[0] else f"{cut[0]}-{cut[1]}" if s < cut[1] else f"{cut[1]}-{cut[2]}" if s < cut[2] else f"{cut[2]}+"
cell = defaultdict(lambda: [0, 0.0, 0])
for r in out_rows:
    fam = FAM.get(r["market"], "other")
    for k in ((r["sport"], fam, "fav" if r["fav"] else "dog", bkt(r["spread"], r["sport"])),
              (r["sport"], fam, "fav" if r["fav"] else "dog", "all"), (r["sport"], "ALL", "both", bkt(r["spread"], r["sport"]))):
        c = cell[k]; c[0] += 1; c[1] += r["p_over"]; c[2] += r["y_over"]
for k, (n, ps, ys) in sorted(cell.items()):
    if n >= 15:
        print("BR", k, f"n={n} model P(over) {ps/n:.1%} actual over {ys/n:.1%} gap {(ys-ps)/n*100:+.1f} pts")
json.dump(out_rows, open("/tmp/br_rows.json", "w"))
