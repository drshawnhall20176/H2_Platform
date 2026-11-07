"""Nov 7: run the Game Script page's logic on the Nov 6 Spurs game (snapshots, ESPN line + final, minutes, results)."""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS          # noqa: E402
import postgame as PG             # noqa: E402
import props_engine as PE         # noqa: E402
import script_effects as SE       # noqa: E402
import sports                     # noqa: E402

D = "2026-11-06"
snaps = MS.load_snapshots("NBA", [D])
print("snapshots", len(snaps), Counter(s["game"] for s in snaps).most_common(12))
rows = [r for r in (SE.from_snapshot(s) for s in snaps) if r]
games = sorted({r["game"] for r in rows if "Spurs" in str(r["game"])})
print("team values", sorted({(r.get("team"), r.get("opp")) for r in rows if r["game"] in games}))
print("spurs games", games)
lines = SE.fetch_lines("NBA", ["20261106", "20261107"])
print("lines", len(lines))
try:
    slate, _ = sports.get("NBA").engine.build_slate(D)
    mins = {PE.norm_name(r.get("Player") or ""): r.get("AvgMin") for r in slate}
except Exception as e:
    print("minutes failed", e)
    mins = {}
res = PG.fetch_results("NBA", D, sorted({(s["team"], s["opp"]) for s in snaps}))
act = {(PE.norm_name(g["player"]), g["market"]): g.get("actual") for g in PG.grade(snaps, res) if g.get("actual") is not None}
for game in games:
    gp = [r for r in rows if r["game"] == game]
    teams = SE.game_teams(gp, game)
    g = SE.game_for(teams, lines)
    strength = g["strength"] if g else None
    fav = g["teams"][g["fav"]]["display"] if g else None
    FN = SE.fav_names(g)
    sh = SE.shares(strength, "NBA")
    print(f"\n=== {game} teams={teams} line={strength} fav={fav} final={g and [(t['display'], t['score']) for t in g['teams']]} happened={SE.actual_script(g, 'NBA') if g else None}")
    print("shares", {k: round(v, 3) for k, v in sh.items()})
    for cond in ("model", "fav_blowout"):
        tally = Counter()
        print(f"--- {cond}")
        out = []
        for r in gp:
            r["mins"] = mins.get(PE.norm_name(r["player"]))
            grp = SE.group("NBA", r["market"], r["mins"])
            is_fav = bool(FN) and SE.team_matches(r.get("team"), FN)
            by = SE.over_by_script(r["p_over"], grp if fav else None, is_fav, sh, "NBA")
            if cond == "model":
                u = {"side": r["side"], "chance": r["p_over"] if r["side"] == "Over" else 1 - r["p_over"], "use": r["use"], "ev": None}
            else:
                u = SE.script_use(r, by[cond], "NBA")
            a = act.get((PE.norm_name(r["player"]), r["market"]))
            resu = None
            if a is not None:
                thr = PE.threshold(r["line"])
                resu = "push" if a == thr else ("W" if (a > thr) == (u["side"] == "Over") else "L")
            tally[(u["use"], resu)] += 1
            out.append((u["use"], r["player"], "FAV" if is_fav else "dog", r.get("team"), grp, r["mins"], r["market"], r["line"], u["side"], round(u["chance"], 3),
                        None if u.get("ev") is None else round(u["ev"], 3), a, resu, (r.get("over_price"), r.get("under_price"))))
        for o in sorted(out, key=lambda o: (o[0] == PE.USE_PASS, -o[9])):
            print("  ", o)
        print("  TALLY", dict(tally))
