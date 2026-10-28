"""
test_player_props.py — offline tests for Position Matchups' basketball Player props view (player_props.py).

    python -m pytest test_player_props.py
"""

import position_matchups as PM
import player_props as PPR


def pg(game, order, team, opp, pid, name, pos, **stats):
    stats.setdefault("min", 30)
    return dict(game=game, order=order, team=team, opp=opp, pid=pid, name=name, pos=pos, stats=stats)


def league(n_def=10, games=3, soft_def=None, soft_mult=1.5):
    """n_def defenses, each giving up the same to forwards except `soft_def`, which gives up soft_mult times as much."""
    out = []
    for d in range(n_def):
        for g in range(games):
            mult = soft_mult if d == soft_def else 1.0
            out.append(pg(f"{d}-{g}", f"2026-10-0{g + 1}", f"O{d}", f"D{d}", f"f{d}", f"F{d}", "SF",
                          pts=20 * mult, reb=8 * mult, ast=4 * mult, blk=1, stl=1))
    return out


# --------------------------------------------------------------------------- markets
def test_markets_cover_the_nightly_menu_with_pra_first():
    assert list(PPR.MARKETS)[0] == "PRA" and PPR.DEFAULT_MARKET == "PRA"
    for m in ("Points", "Assists", "Rebounds", "Blocks", "Steals", "PA", "PR", "PB", "PRA"):
        assert m in PPR.MARKETS
    s = {"pts": 20, "reb": 8, "ast": 5, "blk": 2, "stl": 1}
    assert PPR.market_value(s, "PRA") == 33 and PPR.market_value(s, "PB") == 22 and PPR.market_value(s, "Steals") == 1


# --------------------------------------------------------------------------- fix 1: every rotation player
def test_rotation_lists_every_rotation_player_most_minutes_first():
    usage = {"F": [{"pid": 1, "name": "Tatum", "avg_min": 36}, {"pid": 2, "name": "George", "avg_min": 30},
                   {"pid": 3, "name": "Deep bench", "avg_min": 4}],
             "C": [{"pid": 4, "name": "Robinson", "avg_min": 22}]}
    rot = PPR.rotation(usage, {"George": "Questionable"})
    assert [r["name"] for r in rot] == ["Tatum", "George", "Robinson"]          # the 4-minute player is cut
    assert rot[1]["status"] == "Questionable" and rot[2]["slot"] == "C"


# --------------------------------------------------------------------------- fixes 2 + 3: factor, shrinkage, blend
def test_soft_defense_raises_the_factor_and_small_samples_are_shrunk():
    table = PPR.defense_allowed(PM.allowed_by_slot(league(soft_def=0), "NBA"), "PRA")
    f, n = PPR.raw_factor(table, "D0", "F")
    assert f > 1.3 and n == 3
    b = PPR.blended_factor((f, n), None, "season")
    assert 1.0 < b["factor"] < f                                   # three games only move it part of the way
    assert abs(b["season_weight"] - 3 / 13) < 1e-9


def test_blend_starts_from_last_season_and_moves_toward_this_season():
    prior = (0.85, 40)                                             # last season: a tough defense, big sample
    early = PPR.blended_factor((1.20, 2), prior, "blend")
    late = PPR.blended_factor((1.20, 40), prior, "blend")
    assert early["factor"] < 1.0 < late["factor"]                  # 2 games barely move it; 40 games mostly do
    assert PPR.blended_factor(None, prior, "prior")["basis"] == "last season"


def test_factor_is_clipped_and_needs_enough_defenses():
    assert PPR.blended_factor((3.0, 1000), None, "season")["factor"] == PPR.FACTOR_RANGE[1]
    two_teams = PPR.defense_allowed(PM.allowed_by_slot(league(n_def=2, soft_def=0), "NBA"), "PRA")
    assert PPR.raw_factor(two_teams, "D0", "F") is None              # college-style two-team sample: no league average


# --------------------------------------------------------------------------- fix 4: lines
def test_alt_ladder_lines_and_half_lines_clear_correctly():
    assert PPR.clears(40, 40) and not PPR.clears(40, 40.5) and PPR.clears(41, 40.5)


def test_player_rows_project_hit_rate_and_lean():
    cur = [pg(f"t{g}", f"2026-10-2{g}", "BOS", "X", 7, "Tatum", "SF", pts=30, reb=8, ast=5) for g in range(5)]
    rot = [{"pid": 7, "name": "Tatum", "slot": "F", "avg_min": 36, "status": None}]
    table = PPR.defense_allowed(PM.allowed_by_slot(league(soft_def=0), "NBA"), "PRA")
    rows = PPR.player_rows(rot, "D5", "PRA", table, None, cur, [], lines={7: 39.5}, mode="season")
    r = rows[0]
    assert abs(r["recent_avg"] - 43) < 1e-9 and r["hit"] == (5, 5) and r["lean"] == "Over" and r["p_over"] > 0.55
    under = PPR.player_rows(rot, "D5", "PRA", table, None, cur, [], lines={7: 50}, mode="season")[0]
    assert under["lean"] == "Under" and under["hit"] == (0, 5)
    none = PPR.player_rows(rot, "D5", "PRA", table, None, cur, [], lines={}, mode="season")[0]
    assert none["lean"] == "—" and none["p_over"] is None and none["projection"] is not None


def test_thin_season_form_is_filled_from_last_season_and_flagged():
    cur = [pg("t1", "2026-10-22", "BKN", "X", 9, "Randle", "PF", pts=20, reb=10, ast=5)]
    prior = [pg(f"p{g}", f"2026-04-0{g + 1}", "MIN", "Y", 9, "Randle", "PF", pts=22, reb=9, ast=4) for g in range(6)]
    f = PPR.form(cur, prior, 9, "PRA")
    assert f["filled"] and f["season_games"] == 1 and len(f["values"]) == 5 and f["values"][0] == 35   # topped up to 5


def test_out_players_get_no_projection_and_display_says_so():
    rot = [{"pid": 1, "name": "Hurt", "slot": "G", "avg_min": 30, "status": "Out"}]
    cur = [pg("a", "2026-10-20", "T", "X", 1, "Hurt", "PG", pts=20, reb=3, ast=5)]
    rows = PPR.player_rows(rot, "D1", "PRA", {}, None, cur, [], lines={1: 25})
    assert rows[0]["projection"] is None and rows[0]["lean"] == "—"
    assert "🚫 Out" in PPR.display(rows)[0]["Player"]


def test_plays_for_log_carry_the_market_line_side_and_a_fair_price():
    rows = [{"player": "Tatum", "pid": 7, "line": 39.5, "p_over": 0.62, "lean": "Over"},
            {"player": "Randle", "pid": 9, "line": 35.0, "p_over": 0.30, "lean": "Under"},
            {"player": "NoLine", "pid": 3, "line": None, "p_over": None, "lean": "—"}]
    plays = PPR.plays_for_log(rows, "PRA", "BKN @ BOS")
    assert [p["Player"] for p in plays] == ["Tatum", "Randle"]
    assert plays[0]["Market"] == "PRA" and plays[0]["Side"] == "Over" and plays[0]["Fair"] == PPR.american(0.62)
    assert plays[1]["Side"] == "Under" and abs(plays[1]["ModelProb"] - 0.70) < 1e-9


# --------------------------------------------------------------------------- fix 5: pace
def test_pace_flag_spots_a_high_scoring_matchup():
    games = []
    for g in range(3):
        for t, o, pts in (("A", "B1", 125), ("B1", "A", 120), ("H", "C1", 128), ("C1", "H", 122),
                          ("S1", "S2", 100), ("S2", "S1", 98), ("S3", "S4", 101), ("S4", "S3", 99)):
            games.append(pg("".join(sorted((t, o))) + str(g), f"d{g}", t, o, f"{t}p", "x", "PG", pts=pts))
    flag = PPR.pace_flag(games, "H", "A")
    assert flag["pct"] > PPR.PACE_FLAG_PCT and flag["label"].startswith("⚡")
