"""
test_props_sports.py — offline tests for football / hockey Player props, the Scorecard backtest and the books'
game read (football_props.py, hockey_props.py, props_backtest.py, props_odds.py).

    python -m pytest test_props_sports.py
"""

import random

import football_props as FP
import hockey_props as HP
import position_matchups as PM
import props_backtest as BT
import props_engine as PE
import props_odds as PO


# --------------------------------------------------------------------------- football
def fb(week, team, opp, pid, name, pos, **stats):
    return dict(game=f"{week}-{team}", order=week, team=team, opp=opp, pid=pid, name=name, pos=pos, stats=stats)


def nfl_sample():
    out = []
    for wk in range(1, 7):
        out += [fb(wk, "PHI", f"O{wk}", "a", "A.J. Brown", "WR", tgt=9, rec=6, rec_yds=85, rec_td=0.3 if wk % 3 else 1),
                fb(wk, "PHI", f"O{wk}", "s", "DeVonta Smith", "WR", tgt=7, rec=5, rec_yds=60),
                fb(wk, "PHI", f"O{wk}", "d", "Dallas Goedert", "TE", tgt=5, rec=4, rec_yds=40),
                fb(wk, "PHI", f"O{wk}", "j", "Jahan Dotson", "WR", tgt=2, rec=1, rec_yds=12),
                fb(wk, "PHI", f"O{wk}", "r", "Saquon Barkley", "RB", rush_att=20, rush_yds=95, tgt=3, rec=2, rec_yds=15,
                   rush_td=1 if wk % 2 else 0),
                fb(wk, "PHI", f"O{wk}", "q", "Jalen Hurts", "QB", pass_att=30, pass_yds=230, pass_td=2, rush_att=8,
                   rush_yds=30)]
        for d in range(8):                       # league filler so defenses have a league average
            out.append(fb(wk, f"T{d}", f"U{d}", f"w{d}", f"W{d}", "WR", tgt=8, rec=5, rec_yds=60))
    return out


def test_football_markets_and_roster_with_promotion():
    depth = {"WR1": [{"pid": "s", "name": "DeVonta Smith", "status": None,
                      "role_change": {"from": "WR2", "for": "A.J. Brown"}}],
             "WR2": [{"pid": "j", "name": "Jahan Dotson", "status": None, "role_change": {"from": "WR3", "for": None}}],
             "TE1": [{"pid": "d", "name": "Dallas Goedert", "status": None}],
             "RB1": [{"pid": "r", "name": "Saquon Barkley", "status": None}],
             "QB": [{"pid": "q", "name": "Jalen Hurts", "status": None}]}
    roster = FP.roster_from_depth(depth)
    names = [r["name"] for r in roster]
    assert "A.J. Brown" in names and next(r for r in roster if r["name"] == "A.J. Brown")["status"] == "Out"
    pg = nfl_sample()
    allowed = PM.allowed_by_slot(pg, "NFL")
    rows = {r["player"]: r for r in FP.player_rows(roster, "PHI", "O9", "Receiving Yards", pg, allowed)}
    assert rows["A.J. Brown"]["projection"] is None
    healthy_roster = FP.roster_from_depth({"WR1": [{"pid": "s", "name": "DeVonta Smith"}],
                                           "WR2": [{"pid": "j", "name": "Jahan Dotson"}],
                                           "TE1": [{"pid": "d", "name": "Dallas Goedert"}]})
    base = {r["player"]: r for r in FP.player_rows(healthy_roster, "PHI", "O9", "Receiving Yards", pg, allowed)}
    assert rows["DeVonta Smith"]["opp"] > base["DeVonta Smith"]["opp"] + 1          # Brown's targets moved
    assert rows["Jahan Dotson"]["opp"] > base["Jahan Dotson"]["opp"]
    assert any("targets from teammates out" in f for f in rows["DeVonta Smith"]["flags"])


def test_football_game_script_and_environment():
    pg = nfl_sample()
    allowed = PM.allowed_by_slot(pg, "NFL")
    roster = [{"pid": "r", "name": "Saquon Barkley", "slot": "RB1", "status": None},
              {"pid": "q", "name": "Jalen Hurts", "slot": "QB", "status": None}]
    neutral = {r["player"]: r for r in FP.player_rows(roster, "PHI", "X", "Rush Yards", pg, allowed)}
    fav = {r["player"]: r for r in FP.player_rows(roster, "PHI", "X", "Rush Yards", pg, allowed,
                                                  context={"spread": -9.5, "implied": 28})}
    assert fav["Saquon Barkley"]["projection"] > neutral["Saquon Barkley"]["projection"] * 1.05
    assert any("Favored" in f for f in fav["Saquon Barkley"]["flags"])
    pas = FP.player_rows(roster, "PHI", "X", "Pass Yards", pg, allowed, context={"spread": 9.5})
    assert [r["player"] for r in pas] == ["Jalen Hurts"]


def test_football_anytime_td_uses_half_line_and_count_math():
    pg = nfl_sample()
    rows = FP.player_rows([{"pid": "r", "name": "Saquon Barkley", "slot": "RB1", "status": None}], "PHI", "X",
                          "Anytime TD", pg, PM.allowed_by_slot(pg, "NFL"))
    r = rows[0]
    assert r["line"] == 0.5 and r["dist"] == "count" and 0.2 < r["p_final"] < 0.9


def test_football_book_lines_and_prices():
    pg = nfl_sample()
    offers = [{"market": "player_reception_yds", "player": "DeVonta Smith", "point": 55.5,
               "over": {"draftkings": -115}, "under": {"draftkings": -105}}]
    r = FP.player_rows([{"pid": "s", "name": "DeVonta Smith", "slot": "WR2", "status": None}], "PHI", "X",
                       "Receiving Yards", pg, PM.allowed_by_slot(pg, "NFL"), context={"offers": offers})[0]
    assert r["line"] == 55.5 and r["line_src"] == "book" and r["over_price"] == -115
    d = FP.display([r], "Receiving Yards")[0]
    assert "Tgt" in d and d["Best price"].startswith("O -115")


# --------------------------------------------------------------------------- hockey
def hk(game, date, team, opp, pid, name, pos, role="skater", **stats):
    return dict(game=game, order=date, team=team, opp=opp, pid=pid, name=name, pos=pos, role=role, stats=stats)


def nhl_sample(n=8):
    out = []
    for i in range(n):
        d = f"2026-10-{10 + i:02d}"
        g = f"g{i}"
        out += [hk(g, d, "COL", "VAN", 1, "Nathan MacKinnon", "C", toi=21, sog=5, g=1 if i % 2 else 0, a=1, pts=1 + (i % 2), blk=0.5),
                hk(g, d, "COL", "VAN", 2, "Cale Makar", "D", toi=25, sog=3, g=0, a=1, pts=1, blk=1.5),
                hk(g, d, "COL", "VAN", 3, "Artturi Lehkonen", "LW", toi=17, sog=2, g=0, a=0, pts=0, blk=1),
                hk(g, d, "COL", "VAN", 4, "Ross Colton", "C", toi=14, sog=1.5, g=0, a=0, pts=0, blk=0.5),
                hk(g, d, "COL", "VAN", 30, "Mackenzie Blackwood", "G", role="goalie", toi=60, saves=26, sa=28, ga=2, gs=True),
                hk(g, d, "VAN", "COL", 10, "Elias Pettersson", "C", toi=19, sog=3, g=0, a=1, pts=1, blk=0.5),
                hk(g, d, "VAN", "COL", 35, "Thatcher Demko", "G", role="goalie", toi=60, saves=30, sa=33, ga=3, gs=True)]
    return out


def test_hockey_rotation_and_likely_goalie():
    pg = nhl_sample()
    pg.append(hk("g7", "2026-10-17", "COL", "VAN", 31, "Backup", "G", role="goalie", toi=5, saves=2, sa=2, ga=0, gs=False))
    rot = HP.rotation(pg, "COL")
    assert [r["name"] for r in rot["skaters"]][:2] == ["Cale Makar", "Nathan MacKinnon"]
    assert rot["goalies"][0]["name"] == "Mackenzie Blackwood"            # a relief appearance isn't a start


def test_hockey_rows_count_math_rest_and_next_man_up():
    pg = nhl_sample()
    rot = HP.rotation(pg, "COL")
    rows = {r["player"]: r for r in HP.player_rows(rot, "COL", "VAN", "Shots on Goal", pg, lines={1: 4.5})}
    mac = rows["Nathan MacKinnon"]
    assert mac["dist"] == "count" and 4.0 < mac["projection"] < 6.5 and mac["p_final"] is not None
    tired = {r["player"]: r for r in HP.player_rows(rot, "COL", "VAN", "Shots on Goal", pg,
                                                    context={"rest_days": 1})}
    assert tired["Nathan MacKinnon"]["projection"] < mac["projection"] and "B2B" in tired["Nathan MacKinnon"]["flags"]
    rot_out = {"skaters": [dict(r, status="Out") if r["name"] == "Artturi Lehkonen" else r for r in rot["skaters"]],
               "goalies": rot["goalies"]}
    out = {r["player"]: r for r in HP.player_rows(rot_out, "COL", "VAN", "Shots on Goal", pg,
                                                  context={"team_games": ["g7", "g6", "g5"]})}
    assert out["Artturi Lehkonen"]["projection"] is None
    assert out["Ross Colton"]["opp"] > rows["Ross Colton"]["opp"]                       # his ice time went up
    saves = HP.player_rows(rot, "COL", "VAN", "Saves", pg, context={"rest_days": 1})
    assert saves[0]["player"] == "Mackenzie Blackwood" and "B2B: backup goalie likely" in saves[0]["flags"]
    assert 20 < saves[0]["projection"] < 32


def test_hockey_opponent_factor_and_pgames_builder():
    pg = nhl_sample()
    f = HP.opponent_factor(pg, "VAN", "allowed", "sog")
    assert f and f["games"] == 8 and 1.0 < f["factor"] <= HP.FACTOR_RANGE[1]   # COL outshoots the sample's average
    games = {"g1": {"date": "2026-10-20", "home": 1, "away": 2,
                    "rec": {"players": {11: {"team_id": 1, "role": "skater", "toi": 18.0, "g": 1, "a": 0, "pts": 1,
                                             "sog": 4, "blk": 1, "pos": "C"},
                                        12: {"team_id": 2, "role": "goalie", "toi": 60, "saves": 30, "sa": 31, "ga": 1,
                                             "gs": True, "pos": "G"}}}}}
    out = HP.pgames_from_games(games, {11: {"name": "Skater", "pos": "C"}})
    assert {p["name"] for p in out} == {"Skater", "#12"} and next(p for p in out if p["pid"] == 12)["stats"]["gs"]


# --------------------------------------------------------------------------- scorecard
def bb_league(seed=3):
    rng = random.Random(seed)
    out = []
    for gi in range(10):
        d = f"2026-03-{gi + 1:02d}"
        for t in range(10):
            team, opp = f"T{t}", f"T{(t + 1 + gi) % 10 if (t + 1 + gi) % 10 != t else (t + 2) % 10}"
            for k, pos in enumerate(("PG", "SF", "C", "SG", "PF")):
                base = 10 + 4 * k
                out.append(dict(game=f"{gi}-{min(team, opp)}-{max(team, opp)}", order=d, team=team, opp=opp,
                                pid=f"{team}-{k}", name=f"{team}{k}", pos=pos,
                                stats={"min": 30 - k, "pts": max(0, base + rng.gauss(0, 5)), "reb": 5, "ast": 3}))
    return out


def test_backtest_basketball_produces_a_full_scorecard():
    card = BT.backtest_basketball(bb_league(), "NBA", "Points")
    assert card["n"] > 100 and card["mae_model"] > 0 and card["mae_naive"] > 0
    assert card["brier_model"] is not None and card["buckets"] and card["dates"][0] < card["dates"][1]
    assert any("closer" in v or "further" in v for v in BT.verdict(card))


def test_backtest_hockey_and_football_run():
    h = BT.backtest_hockey(nhl_sample(10), "Shots on Goal")
    assert h["n"] > 0 and h["mae_model"] is not None
    f = BT.backtest_football(nfl_sample(), "NFL", "Receiving Yards")
    assert f["n"] > 0 and f["side_rate"] is not None
    assert BT.verdict({"n": 0}) == ["Not enough games in the sample to grade the model yet."]


def test_proxy_line_and_summary_math():
    assert BT.proxy_line([20, 21, 22]) == 21.5
    cases = [{"actual": 25, "naive": 20, "model": 24, "line": 21.5, "p_model": 0.7, "p_naive": 0.4, "lean": "Over"},
             {"actual": 18, "naive": 22, "model": 19, "line": 21.5, "p_model": 0.3, "p_naive": 0.6, "lean": "Under"}]
    s = BT.summarize(cases)
    assert s["lean_hits"] == 2 and s["mae_model"] < s["mae_naive"] and s["side_rate"] == 1.0


# --------------------------------------------------------------------------- the books' game read
def test_game_lines_parse_spread_total_and_moneyline():
    ev = {"home_team": "Boston Celtics", "away_team": "Brooklyn Nets", "bookmakers": [
        {"key": "draftkings", "markets": [
            {"key": "spreads", "outcomes": [{"name": "Boston Celtics", "point": -9.5, "price": -110},
                                            {"name": "Brooklyn Nets", "point": 9.5, "price": -110}]},
            {"key": "totals", "outcomes": [{"name": "Over", "point": 221.5, "price": -110},
                                           {"name": "Under", "point": 221.5, "price": -110}]},
            {"key": "h2h", "outcomes": [{"name": "Boston Celtics", "price": -450},
                                        {"name": "Brooklyn Nets", "price": 350}]}]}]}
    g = PO.game_lines(ev)
    assert g["spread_home"] == -9.5 and g["total"] == 221.5 and g["p_home"] > 0.75
    home, away = PE.implied_team_totals(g["total"], g["spread_home"])
    assert home == 115.5 and away == 106.0
    assert abs(PO.hockey_spread_from_ml(0.6) + 0.5) < 1e-9
    merged = PO._merge({"bookmakers": [{"key": "dk", "markets": [{"key": "spreads"}]}]},
                       {"bookmakers": [{"key": "dk", "markets": [{"key": "player_points"}]}, {"key": "fd", "markets": []}]})
    assert [m["key"] for m in merged["bookmakers"][0]["markets"]] == ["spreads", "player_points"]
    assert len(merged["bookmakers"]) == 2


def test_nhl_is_a_supported_props_only_sport():
    assert "NHL" in PM.SUPPORTED_SPORTS and PM.FAMILY_BY_SPORT["NHL"] == "hockey"
    assert "NHL" not in PM.SLOTS_BY_SPORT
