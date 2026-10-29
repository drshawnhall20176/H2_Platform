"""
Oct 29: Cleveland starts Evan Mobley AND Jarrett Allen (both listed C). Mobley, the more perimeter of the two,
also counts as a forward: his matchup is a half-and-half blend of the center and forward numbers everywhere.
"""

import player_props as PPR
import position_matchups as PM


def line(game, i, pid, name, pos, mins, starter, pts=10, reb=5, ast=2, fg3m=0, team="CLE", opp="X"):
    return dict(game=game, order=f"2026-10-2{i}", team=team, opp=opp, pid=pid, name=name, pos=pos, starter=starter,
                stats=dict(min=mins, pts=pts, reb=reb, ast=ast, fg3m=fg3m))


def cle_games(n=4):
    out = []
    for i in range(n):
        g = f"g{i}"
        out += [line(g, i, 1, "Donovan Mitchell", "SG", 35, True, pts=25),
                line(g, i, 2, "James Harden", "PG", 35, True, ast=7),
                line(g, i, 3, "Max Strus", "SF", 28, True, fg3m=3),
                line(g, i, 4, "Evan Mobley", "C", 35, True, pts=20, reb=10, ast=3, fg3m=1),
                line(g, i, 5, "Jarrett Allen", "C", 28, True, pts=13, reb=9, ast=1, fg3m=0),
                line(g, i, 6, "Dean Wade", "PF", 18, False)]
    return out


def test_the_stretch_big_of_a_two_center_lineup_also_counts_as_a_forward():
    assert PM.secondary_slots(cle_games()) == {4: "F"}                     # Mobley, not Allen
    one_center = [p for p in cle_games() if p["pid"] != 5]
    assert PM.secondary_slots(one_center) == {}
    once = cle_games(4)
    for p in once:
        if p["pid"] == 5 and p["game"] != "g0":
            p["starter"] = False                                            # paired in only 1 of 4: not a lineup
    assert PM.secondary_slots(once) == {}


def test_depth_rotation_and_props_carry_and_use_the_blend():
    usage = PM.usage_depth(cle_games(), "CLE", "NBA")
    mobley = next(u for u in usage["C"] if u["pid"] == 4)
    assert mobley["slot2"] == "F" and next(u for u in usage["C"] if u["pid"] == 5)["slot2"] is None
    rot = PPR.rotation(usage)
    assert next(r for r in rot if r["pid"] == 4)["slot2"] == "F"
    rows = [{"slot": "C", "rank": 1, "n_teams": 30, "tier": "Soft", "allowed": 42.8, "league_avg": 26.6,
             "vs_league_pct": 61.0, "thin": False, "trend": "steady", "line": "", "role_change": None, "model_factor": 1.20,
             "players": [{"name": "Evan Mobley", "avg_min": 35, "slot2": "F", "recent": None, "h2h": None},
                         {"name": "Jarrett Allen", "avg_min": 28, "recent": None, "h2h": None}]},
            {"slot": "F", "rank": 1, "n_teams": 30, "tier": "Soft", "allowed": 84.8, "league_avg": 68.9,
             "vs_league_pct": 23.0, "thin": False, "trend": "steady", "line": "", "role_change": None, "model_factor": 0.99,
             "players": [{"name": "Mario Hezonja", "avg_min": 18, "recent": None, "h2h": None}]}]
    d = {x["Player"]: x for x in PM.display_rows_by_player(rows)}
    assert d["Evan Mobley"]["Pos"] == "C/F" and d["Evan Mobley"]["Model matchup"] == "+9% (C/F blend)"
    assert d["Jarrett Allen"]["Pos"] == "C" and d["Jarrett Allen"]["Model matchup"] == "+20%"
    assert PM.blend_factor(1.20, 0.99) == 0.5 * 1.20 + 0.5 * 0.99


def test_player_props_blend_the_matchup_for_the_double_big(monkeypatch):
    # Atlanta: very soft to centers, neutral to forwards (20 games each, so the shrink keeps most of it)
    monkeypatch.setattr(PPR, "raw_factor", lambda table, defense, slot: ({"C": 1.4, "F": 1.0}[slot], 20))
    rot = [{"pid": 4, "name": "Evan Mobley", "slot": "C", "avg_min": 35, "status": None, "slot2": "F"},
           {"pid": 5, "name": "Jarrett Allen", "slot": "C", "avg_min": 28, "status": None}]
    rows = {r["pid"]: r for r in PPR.player_rows(rot, "ATL", "PRA", {}, None, cle_games(), [], mode="season")}
    assert rows[5]["factor"] == 1.2                                            # the full (capped) center matchup
    assert abs(rows[4]["factor"] - 0.5 * (1.2 + 1.0)) < 1e-9 and "C/F blend" in rows[4]["basis"]
