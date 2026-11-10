import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sports, kotc as K, todays_best as TB
sp = sports.get("NBA"); E, P = sp.engine, sp.projections
d = "2026-11-10"
rows, meta = E.build_slate(d)
opp = {o: E.get_team_recent_allowed_stats(o, d) for o in {r["_opp_id"] for r in rows if r.get("_opp_id") is not None}}
rest = {t: E.get_team_rest_info(t, d) for t in {r["_team_id"] for r in rows if r.get("_team_id") is not None}}
board = P.build_hot_hand_board(rows, opp, rest)
info = {}
for r in rows:
    log = r.get("_game_log") or []
    mins = [g.get("min") for g in log[:5] if g.get("min") is not None]
    info[(r["Player"], r["Team"])] = {"min": sum(mins) / len(mins) if mins else None,
                                      "pra": [(g.get("pts") or 0) + (g.get("reb") or 0) + (g.get("ast") or 0) for g in log[:10]]}
blow = K.blowout_by_team(TB.blowout_rows(d, sports_=("NBA",)))
outs = set()
for abbr in set(E.team_abbrs_from_meta(meta).values()):
    for p in E.get_team_injuries(abbr) or []:
        if str(p.get("status") or "").lower() in ("out", "doubtful"):
            outs.add(p.get("player"))
print("KT outs", len(outs), sorted(outs)[:12])
for r in K.build(board, info, blow, outs)[:15]:
    print("KT", f"{r['King chance']:.1%}", r["Player"], r["Team"], "| adj", r["Adj PRA"], "proj", r["Proj PRA"], "ceil", r["Ceiling (90th)"], "best", r["Best recent"], "| min", r["Minutes"], "| blow", None if r["Blowout chance"] is None else round(r["Blowout chance"], 2), "risk", r["Min at risk"], "|", r["Spread"])
