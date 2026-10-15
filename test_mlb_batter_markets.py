"""Home runs and stolen bases (and the other batter props the board prices): they must grade, and the Desk must be able to flag them."""
import mlb_engine as E
import retro as R

BATTER_MARKETS = {"Batter HR": "hr", "Batter Stolen Bases": "sb", "Batter Runs": "runs", "Batter RBIs": "rbi", "Batter Singles": "singles",
                  "Batter Doubles": "doubles", "Batter Triples": "triples", "Batter Walks": "bb", "Batter Total Hits": "hits",
                  "Batter Total Bases": "tb", "Batter Strikeouts": "so", "Batter Hits+Runs+RBIs": "hrr"}


def _box(**bat):
    return {"teams": {"home": {"players": {"ID7": {"person": {"id": 7, "fullName": "Speedy"}, "stats": {"batting": bat}}}}, "away": {"players": {}}}}


def test_the_boxscore_carries_a_stat_for_every_batter_market_the_board_prices():
    rec = E.parse_boxscore_results(_box(hits=3, doubles=1, triples=1, homeRuns=0, runs=2, rbi=1, stolenBases=2, baseOnBalls=1, strikeOuts=0))[7]
    assert rec["sb"] == 2 and rec["runs"] == 2 and rec["rbi"] == 1 and rec["bb"] == 1
    assert rec["singles"] == 1 and rec["doubles"] == 1 and rec["triples"] == 1
    for market, key in BATTER_MARKETS.items():
        assert R.MARKET_STAT[market] == key and key in rec, market                       # a market with no stat key grades as a void


def test_a_missing_box_score_field_is_zero_not_a_crash():
    rec = E.parse_boxscore_results(_box(hits=1))[7]
    assert rec["sb"] == 0 and rec["bb"] == 0 and rec["runs"] == 0


def test_stolen_base_and_home_run_calls_grade_over_and_under():
    assert R.grade_play("Batter Stolen Bases", "Over", 0.5, {"sb": 1}) is True
    assert R.grade_play("Batter Stolen Bases", "Over", 0.5, {"sb": 0}) is False
    assert R.grade_play("Batter Stolen Bases", "Under", 0.5, {"sb": 0}) is True
    assert R.grade_play("Batter HR", "Over", 0.5, {"hr": 1}) is True
    assert R.grade_play("Batter HR", "Over", 0.5, {"hr": 0}) is False
    assert R.grade_play("Batter Stolen Bases", "Over", 0.5, {"hits": 2}) is None          # no stat line for the market: void, not a loss


# ------------------------------------------------------------------ the Desk's long-shot rule
import analyst as A


def play(market="Batter HR", side="Over", mp=0.20, ref=0.15, **kw):
    p = {"Player": "Slugger", "Team": "NYY", "Game": "NYY @ BOS", "Market": market, "Side": side, "Line": 0.5, "ModelProb": mp,
         "Conviction": mp / ref, "ConvictionSource": "book"}
    p.update(kw)
    return p


def test_an_over_home_run_the_model_rates_20_percent_above_the_book_now_fires_the_gap_angle():
    r = A.detect_market_gap(play(mp=0.19, ref=0.15), {})                       # +4 pts: under the flat 5-point bar, but +27% on the price
    assert r and "model 19% vs market 15%" in r["evidence"] and "+27% on the price" in r["evidence"] and 0 < r["strength"] <= 1


def test_the_same_rule_covers_stolen_bases_and_is_over_only_and_long_shot_markets_only():
    assert A.detect_market_gap(play("Batter Stolen Bases", mp=0.24, ref=0.18), {})                   # +33% on the price, +6 pts
    assert A.detect_market_gap(play("Batter Stolen Bases", mp=0.22, ref=0.18), {})                   # +22% on the price, +4 pts: only the new rule
    assert A.detect_market_gap(play("Batter Stolen Bases", side="Under", mp=0.88, ref=0.85), {}) is None
    assert A.detect_market_gap(play(side="Under", mp=0.19, ref=0.15), {}) is None                    # the price-relative rule is for Over plays only
    assert A.detect_market_gap(play("Batter Total Bases", mp=0.19, ref=0.15), {}) is None            # other markets keep the flat 5-point bar
    assert A.detect_market_gap(play("Batter Total Bases", mp=0.40, ref=0.28), {})                    # …which still fires for them


def test_the_flat_rule_still_applies_to_home_runs_and_a_big_gap_is_a_stronger_signal():
    assert A.detect_market_gap(play(mp=0.36, ref=0.28), {})                                          # 8 points
    weak = A.detect_market_gap(play(mp=0.18, ref=0.15), {})["strength"]
    strong = A.detect_market_gap(play(mp=0.27, ref=0.15), {})["strength"]
    assert 0 < weak < strong <= 1


def test_the_long_shot_rule_needs_a_real_edge_on_the_price_in_points_and_a_book_price():
    assert A.detect_market_gap(play(mp=0.17, ref=0.15), {}) is None                                   # +13% on the price: not enough
    assert A.detect_market_gap(play(mp=0.181, ref=0.15), {})                                          # just over +20%
    assert A.detect_market_gap(play(mp=0.06, ref=0.05), {}) is None                                   # +20% but only 1 point: noise
    assert A.detect_market_gap(play(mp=0.08, ref=0.05), {})
    assert A.detect_market_gap(play(mp=0.20, ref=0.15, ConvictionSource="typical"), {}) is None       # the reference was the model's own guess, not a market


def test_a_home_run_over_the_model_likes_becomes_a_locked_call_with_the_gap_angle():
    calls = A.scan([play(mp=0.19, ref=0.15), play(mp=0.15, ref=0.15, Player="Flat Guy")], "MLB", "2026-10-15")
    assert [c["player"] for c in calls] == ["Slugger"]
    (c,) = calls
    assert c["market"] == "Batter HR" and [a["angle"] for a in c["angles"]] == ["market_gap"] and c["gem"] is False


# ------------------------------------------------------------------ boards and charts
from pathlib import Path

import sports


def test_the_single_play_boards_default_to_the_curated_markets_plus_home_runs_and_stolen_bases():
    mlb = sports.get("MLB")
    d = mlb.board_defaults()
    assert "Batter HR" in d and "Batter Stolen Bases" in d and d[:len(mlb.default_markets)] == mlb.default_markets
    assert len(d) == len(set(d)) and set(d) - set(mlb.default_markets) == {"Batter HR", "Batter Stolen Bases"}
    assert "Batter HR" not in mlb.default_markets and "Batter Stolen Bases" not in mlb.default_markets    # the parlay builders stay curated
    assert all(m in mlb.market_map for m in d)


def test_a_sport_with_no_curation_has_no_board_default_and_featured_markets_are_not_duplicated():
    assert sports.get("NFL").board_defaults() is None
    s = sports.Sport(key="X", label="X", icon="x", odds_sport_key="x", markets=[], market_map={}, default_markets=["A", "B"],
                     featured_markets=["B", "C"])
    assert s.board_defaults() == ["A", "B", "C"]


def test_best_bets_and_graded_picks_use_the_board_defaults_and_the_parlay_pages_do_not():
    root = Path(__file__).parent / "views"
    for name in ("1_#U2b50_Best_Bets.py", "2_Graded_Picks.py"):
        assert "_active.board_defaults()" in (root / name).read_text(), name
    for name in ("3_Suggested_Parlays.py", "4_Speculative_Basket.py", "37_Slip_Lab.py"):
        assert "board_defaults" not in (root / name).read_text(), name


def test_player_lines_has_a_stolen_bases_chart_and_the_recent_games_carry_the_stat(monkeypatch):
    src = (Path(__file__).parent / "views" / "26_MLB_Player_Lines.py").read_text()
    assert '("sb", "Batter Stolen Bases"' in src
    log = {"stats": [{"splits": [{"date": f"2026-10-0{i}", "isHome": True, "stat": {"plateAppearances": 4, "stolenBases": i % 3}}
                                 for i in range(1, 6)]}]}
    monkeypatch.setattr(E, "fetch_json", lambda *a, **k: log)
    games = E.get_hitter_recent_games(1, 2026)
    assert [g["sb"] for g in games] == [1, 2, 0, 1, 2]
    assert E._MARKET_TO_RECENT_GAME_FIELD["Batter Stolen Bases"] == "sb"
