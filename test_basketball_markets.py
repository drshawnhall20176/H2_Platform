"""Build 246: basketball combo props, steals, blocks, blocks+steals, turnovers and threes attempted (NBA, WNBA, NCAAMB)."""
import numpy as np
import pytest

import analyst as A
import basketball_engine as BB
import basketball_markets as BM
import nba_engine
import nba_projections
import ncaamb_engine
import ncaamb_projections
import odds_api as O
import retro
import sports as S
import wnba_engine
import wnba_projections

ENGINES = {"NBA": nba_engine, "WNBA": wnba_engine, "NCAAMB": ncaamb_engine}
PROJ = {"NBA": nba_projections, "WNBA": wnba_projections, "NCAAMB": ncaamb_projections}


# --------------------------------------------------------------------------- the shared module
def test_a_combo_is_the_sum_of_its_parts_and_a_missing_part_makes_it_unknown_not_zero():
    g = {"pts": 20, "reb": 5, "ast": 4, "stl": 2, "blk": 1}
    assert BM.game_value(g, "pra") == 29 and BM.game_value(g, "pr") == 25 and BM.game_value(g, "pa") == 24
    assert BM.game_value(g, "ra") == 9 and BM.game_value(g, "bs") == 3 and BM.game_value(g, "stl") == 2
    assert BM.game_value({"pts": 20, "reb": 5}, "pra") is None            # no assists on file
    assert BM.game_value({"pts": 20}, "tov") is None                      # an old log without turnovers
    assert BM.game_value({"pts": "n/a", "reb": 1, "ast": 1}, "pra") is None
    assert BM.game_value({"pts": None}, "pts") is None


def test_values_for_skips_games_without_the_stat_and_keeps_order():
    log = [{"pts": 10, "reb": 1, "ast": 1}, {"pts": 30, "reb": 2}, {"pts": 20, "reb": 3, "ast": 2}]
    assert BM.values_for(log, "pra") == [12.0, 25.0]
    assert BM.values_for(log, "pts") == [10.0, 30.0, 20.0]
    assert BM.values_for(None, "pra") == [] and BM.values_for([], "pra") == []
    assert BM.average_for(log, "pra") == 18.5 and BM.average_for(log, "stl") is None


def test_window_average_needs_a_full_window_of_games_that_all_have_the_stat():
    log = [{"pts": i, "reb": 1, "ast": 1} for i in range(6)]
    assert BM.window_average(log, "pra", 5) == sum(i + 2 for i in range(5)) / 5
    assert BM.window_average(log, "pra", 10) is None                       # only 6 games
    assert BM.window_average([{"pts": 1, "reb": 1, "ast": 1}] * 4 + [{"pts": 1}], "pra", 5) is None


def test_attempts_come_from_the_made_attempted_string():
    assert BM.parse_attempts("3-7") == 7.0 and BM.parse_attempts("0-0") == 0.0
    assert BM.parse_attempts("5") is None and BM.parse_attempts(None) is None and BM.parse_attempts("-3") is None


def test_box_stats_use_the_real_confirmed_live_nba_line_michael_porter_jr():
    # The Nets @ Clippers line pasted back during the NBA build: 22 MIN, 9 PTS, 0-4 3PT, 2 REB, 4 AST, 1 TO, 0 STL, 0 BLK.
    names = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF", "+/-"]
    stats = ["22", "9", "3-11", "0-4", "3-3", "2", "4", "1", "0", "0", "0", "2", "2", "-25"]
    assert BM.player_stats_from_box(names, stats) == {"stl": 0.0, "blk": 0.0, "tov": 1.0, "fg3a": 4.0}
    # and the real UConn/Duke Elite Eight line (Tarris Reed Jr.): 2 STL, 4 BLK, 2 TO, 0-0 from three
    n2 = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF"]
    s2 = ["32", "26", "10-16", "0-0", "6-9", "9", "3", "2", "2", "4", "4", "5", "3"]
    out = BM.player_stats_from_box(n2, s2)
    assert out == {"stl": 2.0, "blk": 4.0, "tov": 2.0, "fg3a": 0.0}


def test_a_feed_that_omits_a_stat_leaves_the_key_out_rather_than_writing_a_zero():
    assert BM.player_stats_from_box(["MIN", "PTS", "REB", "AST", "3PT"], ["36", "25", "8", "7", "3-6"]) == {"fg3a": 6.0}
    assert BM.player_stats_from_box(["MIN", "PTS"], ["36", "25"]) == {}


def test_add_derived_adds_only_the_combos_whose_parts_are_present():
    line = BM.add_derived({"pts": 20.0, "reb": 5.0, "ast": 4.0})
    assert line["pra"] == 29 and line["pr"] == 25 and line["pa"] == 24 and line["ra"] == 9 and "bs" not in line
    assert BM.add_derived({"stl": 1.0, "blk": 2.0})["bs"] == 3.0


def test_row_columns_average_each_new_stat_and_are_none_when_the_log_lacks_it():
    log = [{"pts": 20, "reb": 6, "ast": 4, "stl": 2, "blk": 0, "tov": 3, "fg3a": 8},
           {"pts": 10, "reb": 4, "ast": 2, "stl": 0, "blk": 1, "tov": 1, "fg3a": 4}]
    cols = BM.row_columns(log)
    assert cols["PRA"] == 23.0 and cols["PR"] == 20.0 and cols["PA"] == 18.0 and cols["RA"] == 8.0
    assert cols["STL"] == 1.0 and cols["BLK"] == 0.5 and cols["BLKSTL"] == 1.5 and cols["TOV"] == 2.0 and cols["FG3A"] == 6.0
    old = BM.row_columns([{"pts": 20, "reb": 6, "ast": 4}])
    assert old["PRA"] == 30.0 and old["STL"] is None and old["TOV"] is None and old["BLKSTL"] is None


def test_the_market_tables_agree_with_each_other():
    assert len(BM.EXTRA_MARKETS) == 9
    assert len({k for k, *_ in BM.EXTRA_MARKETS}) == 9 and len({c for _k, c, *_ in BM.EXTRA_MARKETS}) == 9
    assert BM.MODEL_ONLY == {"player_threes_attempted"} and BM.MODEL_ONLY_DISPLAY == {"Threes Attempted"}
    assert "player_threes_attempted" not in BM.EXTRA_ODDS_KEYS and len(BM.EXTRA_ODDS_KEYS) == 8
    assert BM.EXTRA_DISPLAY_TO_ODDS_KEY["Pts+Reb+Ast"] == "player_points_rebounds_assists"
    assert BM.EXTRA_DISPLAY_TO_ODDS_KEY["Blocks+Steals"] == "player_blocks_steals"
    assert set(BM.DEFAULT_LINES) == {"NBA", "WNBA", "NCAAMB"}
    for league, lines in BM.DEFAULT_LINES.items():
        assert set(lines) == {c for _k, c, *_ in BM.EXTRA_MARKETS}, league
        assert all(v % 1 == 0.5 for v in lines.values()), league           # half-point lines: no pushes
    for _k, _c, _d, stat in BM.EXTRA_MARKETS:
        assert stat in BM.COMBOS or stat in BM.BASE_KEYS


def test_every_market_key_the_registry_requests_is_a_real_odds_api_market():
    # Keys checked against The Odds API's published market list (NBA/NCAAB/WNBA player props). Threes attempted is not on it.
    published = {"player_points", "player_rebounds", "player_assists", "player_threes", "player_blocks", "player_steals",
                 "player_blocks_steals", "player_turnovers", "player_points_rebounds_assists", "player_points_rebounds",
                 "player_points_assists", "player_rebounds_assists"}
    for sport in ENGINES:
        assert set(S.get(sport).markets) == published, sport


def test_team_totals_gain_steals_blocks_turnovers_threes_attempted_and_combos_when_reported():
    teams = [{"team": {"id": "20"}, "statistics": [
        {"name": "fieldGoalsMade-fieldGoalsAttempted", "displayValue": "33-82"},
        {"name": "freeThrowsMade-freeThrowsAttempted", "displayValue": "14-20"},
        {"name": "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "displayValue": "9-31"},
        {"name": "offensiveRebounds", "displayValue": "10"}, {"name": "totalTurnovers", "displayValue": "15"},
        {"name": "steals", "displayValue": "8"}, {"name": "blocks", "displayValue": "5"},
        {"name": "totalRebounds", "displayValue": "36"}, {"name": "assists", "displayValue": "20"},
        {"name": "points", "displayValue": "88"}]}]
    cdn = {"gamepackageJSON": {"boxscore": {"teams": teams}}}
    t = BB.get_game_team_totals("g1", "http://cdn", lambda url, params=None: cdn)[20]
    assert (t["stl"], t["blk"], t["tov"], t["fg3a"]) == (8.0, 5.0, 15.0, 31.0)
    assert t["pra"] == 144 and t["pr"] == 124 and t["pa"] == 108 and t["ra"] == 56 and t["bs"] == 13
    assert t["fg3m"] == 9.0 and abs(t["poss"] - 95.8) < 1e-6                  # the original fields are untouched


def test_team_totals_leave_out_a_stat_the_feed_did_not_name():
    cdn = {"gamepackageJSON": {"boxscore": {"teams": [{"team": {"id": "20"}, "statistics": [
        {"name": "points", "displayValue": "88"}, {"name": "totalRebounds", "displayValue": "36"},
        {"name": "assists", "displayValue": "20"}]}]}}}
    t = BB.get_game_team_totals("g2", "http://cdn", lambda url, params=None: cdn)[20]
    assert "stl" not in t and "blk" not in t and "fg3a" not in t and "bs" not in t and t["pra"] == 144


def test_allowed_stat_averages_keep_the_old_stats_as_zero_and_new_ones_only_when_reported():
    totals = BM.empty_team_totals()
    BM.accumulate_team_totals(totals, {"pts": 100.0, "reb": 40.0})                  # nothing else reported
    BM.accumulate_team_totals(totals, {"pts": 90.0, "reb": 30.0, "ast": 20.0, "stl": 8.0})
    assert totals["pts"] == [100.0, 90.0] and totals["ast"] == [0.0, 20.0] and totals["poss"] == [0.0, 0.0]   # as before
    assert totals["stl"] == [8.0] and totals["blk"] == [] and totals["pra"] == []   # newer stats: no fake zeros


# --------------------------------------------------------------------------- box scores, all three leagues
_NAMES = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF"]
_CDN = {"gamepackageJSON": {"boxscore": {"players": [{"team": {"id": "1"}, "statistics": [{"names": _NAMES, "athletes": [
    {"athlete": {"id": "7"}, "didNotPlay": False,
     "stats": ["32", "26", "10-16", "2-7", "6-9", "9", "3", "2", "2", "4", "4", "5", "3"]},
    {"athlete": {"id": "8"}, "didNotPlay": True, "stats": []}]}]}]}}}


@pytest.mark.parametrize("sport", ["NBA", "WNBA", "NCAAMB"])
def test_every_leagues_box_score_records_the_new_stats_and_combos(monkeypatch, sport):
    E = ENGINES[sport]
    E._response_cache.clear()
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: _CDN)
    box = E.get_game_boxscore("g1")
    assert 8 not in box
    line = box[7]
    assert (line["pts"], line["reb"], line["ast"], line["fg3m"], line["min"]) == (26.0, 9.0, 3.0, 2.0, 32.0)   # unchanged
    assert (line["stl"], line["blk"], line["tov"], line["fg3a"]) == (2.0, 4.0, 2.0, 7.0)
    assert line["pra"] == 38 and line["pr"] == 35 and line["pa"] == 29 and line["ra"] == 12 and line["bs"] == 6
    E._response_cache.clear()


@pytest.mark.parametrize("sport", ["NBA", "WNBA", "NCAAMB"])
def test_a_player_row_carries_the_new_average_columns(sport):
    log = [{"pts": 20, "reb": 6, "ast": 4, "fg3m": 2, "min": 30, "stl": 2, "blk": 0, "tov": 3, "fg3a": 8},
           {"pts": 10, "reb": 4, "ast": 2, "fg3m": 1, "min": 28, "stl": 0, "blk": 1, "tov": 1, "fg3a": 4}]
    row = ENGINES[sport].player_row({"id": 1, "name": "A"}, "T", "O", "G", None, log)
    assert row["PTS"] == 15.0 and row["PRA"] == 23.0 and row["STL"] == 1.0 and row["BLKSTL"] == 1.5 and row["FG3A"] == 6.0


@pytest.mark.parametrize("sport", ["NBA", "WNBA", "NCAAMB"])
def test_a_games_log_line_keeps_the_new_stats(monkeypatch, sport):
    E = ENGINES[sport]
    E._response_cache.clear()
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: _CDN)
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda *a, **k: [{"gameId": "g1", "date": "2026-02-01T00:00Z", "opp_id": "9", "opp_name": "X", "season_type": 2}])
    log = E.get_player_recent_games(7, 10, team_id=1, before_date="2026-02-05")
    assert log and log[0]["pra"] == 38 and log[0]["tov"] == 2.0
    E._response_cache.clear()


# --------------------------------------------------------------------------- projections, all three leagues
def _log(n=10, **per_game):
    base = {"pts": 20, "reb": 6, "ast": 5, "fg3m": 2, "min": 30, "stl": 1, "blk": 1, "tov": 3, "fg3a": 6}
    base.update(per_game)
    return [dict(base) for _ in range(n)]


def _row(log, name="A. Player"):
    return {"Player": name, "Team": "T", "GameLabel": "O @ T", "Opp": "O", "_game_log": log, "_pid": 1,
            "_game_date": "2026-11-10T00:00Z", **BM.row_columns(log), "PTS": 20.0, "REB": 6.0, "AST": 5.0, "FG3M": 2.0,
            "AvgMin": 30.0}


ALL_MARKETS = {"Points", "Rebounds", "Assists", "Threes Made", "Pts+Reb+Ast", "Pts+Reb", "Pts+Ast", "Reb+Ast", "Steals",
               "Blocks", "Blocks+Steals", "Turnovers", "Threes Attempted"}


@pytest.mark.parametrize("sport", ["NBA", "WNBA", "NCAAMB"])
def test_the_board_prices_every_market_for_a_player_with_full_game_lines(sport):
    P = PROJ[sport]
    plays = P.build_best_bets([_row(_log())], sims=4000, seed=1)
    assert {p["Market"] for p in plays} == ALL_MARKETS and len(plays) == 13
    by = {p["Market"]: p for p in plays}
    assert by["Pts+Reb+Ast"]["_stat_key"] == "pra" and by["Blocks+Steals"]["_stat_key"] == "bs"
    assert by["Pts+Reb+Ast"]["Line"] == BM.DEFAULT_LINES[sport]["PRA"] and by["Pts+Reb+Ast"]["LineSource"] == "default"
    assert 0.02 <= min(p["ModelProb"] for p in plays) and max(p["ModelProb"] for p in plays) <= 0.98


@pytest.mark.parametrize("sport", ["NBA", "WNBA", "NCAAMB"])
def test_a_combo_is_drawn_a_whole_game_at_a_time_so_the_parts_keep_their_correlation(sport):
    """Points and rebounds trade off perfectly (30/10 then 10/30): every game's points+rebounds is exactly 40. Drawing the
    two stats independently would make 'Over 39.5' lose half the time; drawing whole games makes it a lock."""
    P = PROJ[sport]
    log = [{"pts": 30, "reb": 10, "ast": 0, "fg3m": 0, "min": 30}, {"pts": 10, "reb": 30, "ast": 0, "fg3m": 0, "min": 30}] * 6
    plays = P.build_best_bets([_row(log)], sims=6000, seed=2, real_lines={("a player", "player_points_rebounds"): 39.5})
    pr = next(p for p in plays if p["Market"] == "Pts+Reb")
    assert pr["Side"] == "Over" and pr["ModelProb"] > 0.8 and pr["Line"] == 39.5 and pr["LineSource"] == "book"
    # drawing points and rebounds separately would give at most 0.75 before shrinkage (0.875 here is the whole-game draw, shrunk for
    # a 12-game sample); the mean of exactly 40 is the cleaner proof
    index = P.build_projection_index([_row(log)], meta=[], sims=4000, seed=3)
    assert index[("a player", "player_points_rebounds")]["mean"] == pytest.approx(40.0, abs=0.01)


@pytest.mark.parametrize("sport", ["NBA", "WNBA", "NCAAMB"])
def test_old_game_lines_without_the_new_stats_still_price_points_rebounds_assists_and_the_combos(sport):
    P = PROJ[sport]
    old = [{"pts": 20, "reb": 6, "ast": 5, "fg3m": 2, "min": 30} for _ in range(10)]
    markets = {p["Market"] for p in P.build_best_bets([_row(old)], sims=2000, seed=1)}
    assert markets == {"Points", "Rebounds", "Assists", "Threes Made", "Pts+Reb+Ast", "Pts+Reb", "Pts+Ast", "Reb+Ast"}
    index_keys = {m for (_n, m) in P.build_projection_index([_row(old)], meta=[], sims=2000, seed=1)}
    assert "player_steals" not in index_keys and "player_points_rebounds_assists" in index_keys


@pytest.mark.parametrize("sport", ["NBA", "WNBA", "NCAAMB"])
def test_threes_attempted_is_model_only_even_when_real_lines_are_supplied_for_everything_else(sport):
    P = PROJ[sport]
    plays = P.build_best_bets([_row(_log())], sims=2000, seed=1,
                              real_lines={("a player", "player_points_rebounds_assists"): 30.5, ("a player", "player_steals"): 0.5})
    by = {p["Market"]: p for p in plays}
    assert by["Threes Attempted"]["LineSource"] == "default" and by["Threes Attempted"]["PriceSource"] == "model_fair"
    assert by["Pts+Reb+Ast"]["LineSource"] == "book" and by["Pts+Reb+Ast"]["Line"] == 30.5
    assert by["Steals"]["LineSource"] == "book" and by["Steals"]["Line"] == 0.5
    assert "player_threes_attempted" not in S.get(sport).markets


@pytest.mark.parametrize("sport", ["NBA", "WNBA", "NCAAMB"])
def test_real_book_prices_attach_to_the_new_markets(sport):
    P = PROJ[sport]
    offers = [{"market": "player_points_rebounds_assists", "player": "A. Player", "point": 30.5,
               "over": {"fanduel": -120}, "under": {"fanduel": 100}}]
    plays = P.build_best_bets([_row(_log())], sims=2000, seed=1, offers=offers,
                              real_lines={("a player", "player_points_rebounds_assists"): 30.5}, preferred_book="fanduel")
    pra = next(p for p in plays if p["Market"] == "Pts+Reb+Ast")
    assert pra["PriceSource"] == "book" and pra["RealPrice"] == -120 and pra["ConvictionSource"] == "book"


@pytest.mark.parametrize("sport", ["NBA", "WNBA", "NCAAMB"])
def test_explain_miss_works_for_a_combo_and_for_a_player_without_the_stat(sport):
    P = PROJ[sport]
    assert "avg" in P.explain_miss(_row(_log()), "Pts+Reb+Ast").lower() or "averaging" in P.explain_miss(_row(_log()), "Pts+Reb+Ast")
    assert P.explain_miss(_row([{"pts": 5, "reb": 1, "ast": 1}] * 3), "Steals") == "No recent-game data available for this player."


@pytest.mark.parametrize("sport", ["NBA", "WNBA", "NCAAMB"])
def test_hot_hand_board_lists_the_new_markets_with_a_matchup_factor(sport):
    P = PROJ[sport]
    rows = [{**_row(_log()), "_opp_id": 9, "_team_id": 1}, {**_row(_log(), name="B. Player"), "_opp_id": 8, "_team_id": 2}]
    opp = {9: {"pts": 120, "reb": 45, "ast": 28, "fg3m": 14, "poss": 100.0, "stl": 9, "blk": 6, "tov": 12, "fg3a": 40,
               "pr": 165, "pa": 148, "ra": 73, "pra": 193, "bs": 15},
           8: {"pts": 100, "reb": 40, "ast": 22, "fg3m": 10, "poss": 100.0, "stl": 6, "blk": 4, "tov": 15, "fg3a": 30,
               "pr": 140, "pa": 122, "ra": 62, "pra": 162, "bs": 10}}
    board = P.build_hot_hand_board(rows, opp)
    assert {b["Market"] for b in board} == ALL_MARKETS
    a_pra = next(b for b in board if b["Player"] == "A. Player" and b["Market"] == "Pts+Reb+Ast")
    assert a_pra["Recent Avg"] == 31.0 and a_pra["Opp Allows"] == 193.0 and a_pra["Matchup Factor"] > 1.08
    a_stl = next(b for b in board if b["Player"] == "A. Player" and b["Market"] == "Steals")
    assert a_stl["Matchup Factor"] > 1.08                                                # 9 allowed vs a slate avg of 7.5


@pytest.mark.parametrize("sport", ["NBA", "WNBA", "NCAAMB"])
def test_hot_hand_leaves_a_market_off_when_the_players_game_lines_lack_the_stat(sport):
    P = PROJ[sport]
    old_log = [{"pts": 20, "reb": 6, "ast": 5, "fg3m": 2, "min": 30}] * 5
    row = {"Player": "Old Cache", "Team": "T", "GameLabel": "O @ T", "Opp": "O", "_opp_id": 9, "_team_id": 1,
           "PTS": 20.0, "REB": 6.0, "AST": 5.0, "FG3M": 2.0, **BM.row_columns(old_log)}
    board = P.build_hot_hand_board([row], {9: {"pts": 100, "reb": 40, "ast": 20, "fg3m": 10, "poss": 100.0}})
    assert {b["Market"] for b in board} == {"Points", "Rebounds", "Assists", "Threes Made", "Pts+Reb+Ast", "Pts+Reb", "Pts+Ast", "Reb+Ast"}


@pytest.mark.parametrize("sport", ["NBA", "WNBA", "NCAAMB"])
def test_matchup_profile_covers_the_new_markets_and_suppressed_only_looks_at_the_four_base_stats(sport):
    P = PROJ[sport]
    season = _log(20)
    # H2H: points collapse, everything else normal -> Points is "suppressed"; the PRA combo (which also drops) must not steal it
    h2h = _log(3, pts=8)
    row = _row(season)
    profile = P.build_matchup_profile(row, h2h, {}, {}, season_log=season)
    by = {p["Market"]: p for p in profile}
    assert set(by) == ALL_MARKETS
    assert by["Points"]["Suppressed"] is True
    assert not any(by[m]["Suppressed"] for m in ALL_MARKETS - {"Points"})
    assert by["Pts+Reb+Ast"]["H2H Avg"] == 19.0 and by["Steals"]["H2H Avg"] == 1.0
    w5 = P.build_matchup_profile(row, h2h, {}, {}, season_log=season, window_n=5)
    assert next(p for p in w5 if p["Market"] == "Turnovers")["Window Avg"] == 3.0
    # a season log from before this build has no turnovers: the average is None, never 0
    old = [{"pts": 20, "reb": 6, "ast": 5, "fg3m": 2, "min": 30}] * 12
    w = P.build_matchup_profile(row, [], {}, {}, season_log=old, window_n=10)
    assert next(p for p in w if p["Market"] == "Turnovers")["Window Avg"] is None
    assert next(p for p in w if p["Market"] == "Pts+Reb+Ast")["Window Avg"] == 31.0


def test_market_list_and_default_lines_expose_the_new_markets_in_each_league():
    for sport, P in PROJ.items():
        lst = P.market_list()
        assert len(lst) == 13 and lst[0] == ("player_points", "PTS", "Points")
        assert P.stat_key_for("PRA") == "pra" and P.stat_key_for("BLKSTL") == "bs" and P.stat_key_for("FG3A") == "fg3a"
        assert P.default_line("player_points_rebounds_assists") == BM.DEFAULT_LINES[sport]["PRA"]
        assert P.default_line("player_threes_attempted") == BM.DEFAULT_LINES[sport]["FG3A"]
    assert nba_projections.default_line("player_points_rebounds_assists") > wnba_projections.default_line("player_points_rebounds_assists")


def test_the_default_board_prices_the_new_markets_at_their_league_lines():
    row = _row(_log())
    index = nba_projections.build_projection_index([row], meta=[], sims=3000, seed=1)
    board = nba_projections.default_board_from_index(index)
    assert {b["Market"] for b in board} == ALL_MARKETS
    assert next(b for b in board if b["Market"] == "Pts+Reb+Ast")["Line"] == 35.5


# --------------------------------------------------------------------------- grading
@pytest.mark.parametrize("market,stat", [("Pts+Reb+Ast", "pra"), ("Pts+Reb", "pr"), ("Pts+Ast", "pa"), ("Reb+Ast", "ra"),
                                         ("Steals", "stl"), ("Blocks", "blk"), ("Blocks+Steals", "bs"), ("Turnovers", "tov"),
                                         ("Threes Attempted", "fg3a")])
def test_every_new_market_grades_against_its_box_score_stat(market, stat):
    assert retro.MARKET_STAT[market] == stat
    assert retro.grade_play(market, "Over", 9.5, {stat: 10.0}) is True
    assert retro.grade_play(market, "Over", 9.5, {stat: 9.0}) is False
    assert retro.grade_play(market, "Under", 9.5, {stat: 9.0}) is True
    assert retro.grade_play(market, "Over", 9.5, {"pts": 1.0}) is None             # stat missing -> ungraded, never a loss


def test_a_graded_combo_uses_the_combined_total_from_a_real_parsed_box_score(monkeypatch):
    E = ncaamb_engine
    E._response_cache.clear()
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: _CDN)
    monkeypatch.setattr(E, "get_schedule", lambda d: [{"gameId": "g1"}])
    results = E.get_player_results("2026-11-10")
    assert retro.grade_play("Pts+Reb+Ast", "Over", 37.5, results[7]) is True      # 26 + 9 + 3 = 38
    assert retro.grade_play("Pts+Reb+Ast", "Over", 38.5, results[7]) is False
    assert retro.grade_play("Blocks+Steals", "Over", 5.5, results[7]) is True       # 4 + 2 = 6
    E._response_cache.clear()


# --------------------------------------------------------------------------- the Analyst Desk
def test_the_desk_reads_a_combo_play_from_the_game_lines_it_was_priced_on():
    log = [{"pts": 20, "reb": 6, "ast": 5}, {"pts": 30, "reb": 6, "ast": 5}]       # newest first for NBA? no: basketball is oldest-first here
    assert A._values({"_game_log": log, "_stat_key": "pra"}, "NBA") == [31.0, 41.0]
    assert A._values({"_game_log": [{"pts": 20}], "_stat_key": "pra"}, "NBA") == []
    assert A._values({"_game_log": [{"rushing_tds": 1, "receiving_tds": 1}], "_stat_key": "scrimmage_tds"}, "NFL") == [2.0]


def test_blowout_and_total_angles_cover_the_new_markets():
    assert {"Pts+Reb+Ast", "Pts+Reb", "Pts+Ast", "Reb+Ast", "Steals", "Blocks", "Blocks+Steals", "Turnovers"} <= A.BASKETBALL_STAT_MARKETS
    assert {"Pts+Reb+Ast", "Pts+Reb", "Pts+Ast"} <= A.BASKETBALL_SCORING_MARKETS
    assert "Steals" not in A.BASKETBALL_SCORING_MARKETS and "Turnovers" not in A.BASKETBALL_SCORING_MARKETS


# --------------------------------------------------------------------------- odds fetch safety net
def test_one_refused_market_key_does_not_blank_the_other_markets_lines(monkeypatch):
    asked = []

    def fake_props(event_id, api_key, markets, regions="us", sport=O.SPORT, bookmakers=None):
        asked.append(list(markets))
        if len(markets) > 1 or markets == ["player_blocks_steals"]:
            raise O.OddsAPIError('HTTP 422: {"message":"Invalid market","error_code":"INVALID_MARKET"}')
        mk = markets[0]
        return {"bookmakers": [{"key": "fanduel", "markets": [{"key": mk, "outcomes": [
            {"description": "A. Player", "name": "Over", "point": 1.5, "price": -110},
            {"description": "A. Player", "name": "Under", "point": 1.5, "price": -110}]}]}]}, {"remaining": "400"}

    monkeypatch.setattr(O, "fetch_events", lambda api_key, sport=O.SPORT: [{"id": "e1", "commence_time": "2026-11-10T23:00:00Z"}])
    monkeypatch.setattr(O, "fetch_event_props", fake_props)
    offers, info = O.fetch_slate_props("2026-11-10", "k", ["player_points", "player_steals", "player_blocks_steals"],
                                       sport="basketball_nba")
    assert {o["market"] for o in offers} == {"player_points", "player_steals"}
    assert info["rejected_markets"] == ["player_blocks_steals"] and info["events_fetched"] == 1 and not info["errors"]
    assert asked[0] == ["player_points", "player_steals", "player_blocks_steals"] and len(asked) == 4


def test_a_quota_error_is_still_reported_not_retried_market_by_market(monkeypatch):
    calls = []

    def fake_props(event_id, api_key, markets, **k):
        calls.append(markets)
        raise O.OddsAPIError("429 — out of quota for this period.")

    monkeypatch.setattr(O, "fetch_events", lambda api_key, sport=O.SPORT: [{"id": "e1", "commence_time": "2026-11-10T23:00:00Z"}])
    monkeypatch.setattr(O, "fetch_event_props", fake_props)
    offers, info = O.fetch_slate_props("2026-11-10", "k", ["player_points", "player_steals"], sport="basketball_nba")
    assert offers == [] and len(calls) == 1 and info["errors"] and info["rejected_markets"] == []
