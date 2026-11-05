"""research/backtest_nba_rim_protector.py — does a team score / rebound more when the OPPONENT's starting center
is out? (Nov 5) League box scores (this season + the end of last, the props model's own sample). A team's rim
protector = its center (pos C) averaging 24+ minutes over its previous 8 games; "out" = he didn't play today.
For the attacking team: points, rebounds and its own bigs' (F/C) points and rebounds vs its recent average."""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    import basketball_engine as BB
    import position_data as PD
    import sports
    from datetime import date
    eng = sports.get("NBA").engine
    notes = []
    rows = []
    for start, end in ((date(2025, 10, 21), date(2026, 4, 13)), (date(2026, 10, 20), date(2026, 11, 5))):
        ev = BB.scoreboard_events_in_window(eng.SITE_API, eng._get_json_cached, start, end)
        games = PD.parse_scoreboard_events(ev or [], end.isoformat(), start.isoformat(), lambda t: t == 2)
        gm = {g["gid"]: g for g in games}
        lines = PD._fetch_lines(eng, list(gm))
        all_lines = {gid: {"date": gm[gid].get("date"), "lines": lines.get(gid) or {}} for gid in gm}
        pos = PD._roster_positions(eng, all_lines, notes)
        rows += PD.basketball_pgames(all_lines, pos)
        print(f"{start}..{end}: {len(gm)} games")
    print("player-games:", len(rows))
    games = defaultdict(lambda: defaultdict(list))         # (game, team) -> list of lines
    for p in rows:
        games[(p["game"], p["team"])]["lines"].append(p)
    meta = {}
    for (g, t), d in games.items():
        ls = d["lines"]
        meta[(g, t)] = {"order": ls[0].get("order"), "opp": ls[0].get("opp"),
                        "pts": sum((x["stats"] or {}).get("pts") or 0 for x in ls),
                        "reb": sum((x["stats"] or {}).get("reb") or 0 for x in ls),
                        "big_pts": sum((x["stats"] or {}).get("pts") or 0 for x in ls if str(x.get("pos")) in ("C", "F")),
                        "big_reb": sum((x["stats"] or {}).get("reb") or 0 for x in ls if str(x.get("pos")) in ("C", "F")),
                        "players": {x["pid"]: (str(x.get("pos")), (x["stats"] or {}).get("min") or 0) for x in ls}}
    by_team = defaultdict(list)
    for (g, t), m in meta.items():
        by_team[t].append((str(m["order"]), g))
    for t in by_team:
        by_team[t].sort()
    idx = {(g, t): i for t, lst in by_team.items() for i, (_, g) in enumerate(lst)}

    def rim_out(g, t):
        i = idx.get((g, t))
        if i is None or i < 5:
            return None
        prev = [meta[(gg, t)] for _, gg in by_team[t][max(0, i - 8):i]]
        mins = defaultdict(list)
        for m in prev:
            for pid, (pos, mn) in m["players"].items():
                if pos == "C":
                    mins[pid].append(mn)
        regs = [pid for pid, v in mins.items() if sum(v) / len(prev) >= 24]
        if not regs:
            return None
        return any(pid not in meta[(g, t)]["players"] for pid in regs)

    acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    cnt = defaultdict(int)
    for (g, t), m in meta.items():
        opp = m["opp"]
        if (g, opp) not in meta:
            continue
        o = rim_out(g, opp)
        if o is None:
            continue
        i = idx[(g, t)]
        if i < 5:
            continue
        prev = [meta[(gg, t)] for _, gg in by_team[t][max(0, i - 10):i]]
        key = "opp rim protector OUT" if o else "opp rim protector plays"
        cnt[key] += 1
        for st in ("pts", "reb", "big_pts", "big_reb"):
            acc[key][st][0] += m[st]
            acc[key][st][1] += sum(p[st] for p in prev) / len(prev)
    for k in sorted(acc):
        print(f"{k:26s} n={cnt[k]:5d}  " + "  ".join(f"{st} {a / b - 1:+.1%}" for st, (a, b) in acc[k].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
