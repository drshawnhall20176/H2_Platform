"""
test_model_board_log.py — offline tests for logging Model Board (no odds) picks to the Bet Log.

    python -m pytest test_model_board_log.py
"""

import os
import tempfile
from pathlib import Path

import numpy as np

import betlog as B
import model_board_log as MBL
import nba_projections as NP
import projections as MLB_P

_HERE = Path(__file__).resolve().parent


def _nba_row(name="A. Player", pid=2544, pts=25):
    return {"Player": name, "Team": "Lakers", "GameLabel": "Celtics @ Lakers", "Opp": "Celtics",
            "_game_date": "2026-01-14T00:00Z", "_pid": pid,
            "_game_log": [{"pts": pts + (i % 9) - 4, "reb": 8, "ast": 7, "fg3m": 3} for i in range(18)]}


def _nba_board():
    index = NP.build_projection_index([_nba_row()], meta=[], sims=6000, seed=3)
    board = NP.default_board_from_index(index)
    return index, board


def _points_row(board):
    return next(b for b in board if b["Market"] == "Points")


# ----------------------------------------------------------------- board rows carry what logging needs
def test_board_rows_carry_player_id_and_market_key():
    _index, board = _nba_board()
    row = _points_row(board)
    assert row["PlayerId"] == 2544          # lets a Model Board pick auto-settle like any other bet
    assert row["MarketKey"] == "player_points"


def test_mlb_board_rows_carry_player_id_and_market_key():
    index = {("a hitter", "batter_hits"): {
        "dist": MLB_P._dist(np.arange(0, 5).repeat(200)), "mean": 2.0,
        "ctx": {"player": "A Hitter", "team": "NYY", "game": "BOS @ NYY", "opp": "X",
                "lineup": "Confirmed", "game_date": None, "pid": 99}}}
    row = MLB_P.default_board_from_index(index)[0]
    assert row["PlayerId"] == 99 and row["MarketKey"] == "batter_hits"


# ----------------------------------------------------------------- model probability for the actual bet
def test_unchanged_side_and_line_uses_board_probability_exactly():
    index, board = _nba_board()
    row = _points_row(board)
    p, how = MBL.model_prob_for_bet(row, index, NP, row["Side"], row["Line"])
    assert how == "board" and p == row["ModelProb"]


def test_different_line_is_repriced_in_the_right_direction():
    index, board = _nba_board()
    row = _points_row(board)
    p_board, _ = MBL.model_prob_for_bet(row, index, NP, "Over", row["Line"])
    harder, how = MBL.model_prob_for_bet(row, index, NP, "Over", row["Line"] + 3)
    easier, _ = MBL.model_prob_for_bet(row, index, NP, "Over", row["Line"] - 1)
    assert how == "repriced"
    p_over_board = p_board if row["Side"] == "Over" else 1 - p_board
    assert harder < p_over_board < easier


def test_flipped_side_at_same_line_is_the_complement():
    index, board = _nba_board()
    row = _points_row(board)
    other = MBL.flip_side(row["Side"])
    p, how = MBL.model_prob_for_bet(row, index, NP, other, row["Line"])
    assert how == "repriced"
    assert abs(p - (1 - row["ModelProb"])) < 1e-9


def test_mlb_reprice_equals_raw_distribution_when_board_is_unshrunk():
    dist = MLB_P._dist(np.arange(0, 5).repeat(200))     # P(X > 1.5) = 0.6, P(X > 2.5) = 0.4
    index = {("a hitter", "batter_hits"): {"dist": dist, "mean": 2.0,
             "ctx": {"player": "A Hitter", "team": "NYY", "game": "BOS @ NYY", "pid": 1}}}
    row = {"Player": "A Hitter", "Market": "Hits", "MarketKey": "batter_hits", "Side": "Over",
           "Line": 1.5, "ModelProb": MLB_P.prob_for_side(dist, 1.5, "Over")}
    p, how = MBL.model_prob_for_bet(row, index, MLB_P, "Over", 2.5)
    assert how == "repriced"
    assert abs(p - MLB_P.prob_for_side(dist, 2.5, "Over")) < 1e-9


def test_not_in_index_and_changed_bet_gives_no_number_not_a_guess():
    row = {"Player": "Ghost", "Market": "Points", "MarketKey": "player_points", "Side": "Over",
           "Line": 20.5, "ModelProb": 0.6}
    assert MBL.model_prob_for_bet(row, {}, NP, "Over", 24.5) == (None, "unavailable")
    assert MBL.model_prob_for_bet(row, {}, NP, "Over", 20.5) == (0.6, "board")


def test_market_key_falls_back_to_sport_market_map():
    assert MBL.market_key_for("Points", {"Points": "player_points"}) == "player_points"
    assert MBL.market_key_for("player_points", {"Points": "player_points"}) == "player_points"
    assert MBL.market_key_for("Nope", {"Points": "player_points"}) is None


def test_yes_markets_flip_to_no():
    assert MBL.flip_side("Yes") == "No" and MBL.flip_side("Over") == "Under"


# ----------------------------------------------------------------- sizing matches Live edges
def test_suggested_stake_is_quarter_kelly_on_shaded_prob_capped():
    import odds_api as O
    assert MBL.suggested_stake(0.60, 110, 300.0) == O.kelly_stake(0.55, 110, 300.0, 0.25, 0.05)
    assert MBL.suggested_stake(0.52, -110, 300.0) == 0.0           # no edge left after the shade
    assert MBL.suggested_stake(None, 110, 300.0) == 0.0
    assert MBL.suggested_stake(0.95, 300, 300.0) <= 15.0            # 5% cap on a $300 roll


# ----------------------------------------------------------------- what reaches the Bet Log
def test_logged_row_uses_your_price_and_is_tagged_manual():
    index, board = _nba_board()
    row = _points_row(board)
    p, _ = MBL.model_prob_for_bet(row, index, NP, row["Side"], row["Line"] + 1)
    f = MBL.build_bet_fields(row, date_str="2026-10-24", sport_key="NBA", side=row["Side"],
                             line=row["Line"] + 1, entry_odds=-115, stake=5, book="draftkings",
                             model_prob=p)
    assert f["entry_odds"] == -115 and f["entry_odds_source"] == "manual"
    assert f["line"] == row["Line"] + 1 and f["model_prob"] == round(p, 4)
    assert f["player_id"] == 2544 and f["book"] == "draftkings" and f["sport"] == "NBA"


def test_manual_price_counts_toward_clv_and_is_reported_separately():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "bets.db")
        row = {"Player": "A", "Game": "X @ Y", "Market": "Points", "Side": "Over", "Line": 20.5,
               "ModelProb": 0.6, "PlayerId": 1}
        f = MBL.build_bet_fields(row, date_str="2026-10-24", sport_key="NBA", side="Over",
                                 line=20.5, entry_odds=-110, stake=5, book="draftkings",
                                 model_prob=0.6)
        bid = B.add_bet(db_path=db, **f)
        B.update_bet(bid, db_path=db, close_odds=-130, result="win")
        bets = B.list_bets(db_path=db)
        assert bets[0]["entry_odds_source"] == "manual"
        clv = B.real_price_clv_summary(bets)
        assert clv["n_real_price"] == 1 and clv["n_manual"] == 1 and clv["n_book"] == 0 and clv["avg_clv"] > 0
        assert B.summary(bets)["wins"] == 1


def test_signature_dedups_identical_bets():
    row = {"Player": "A", "Market": "Points", "Side": "Over", "Line": 20.5, "ModelProb": 0.6}
    kw = dict(date_str="d", sport_key="NBA", side="Over", line=20.5, stake=5, book="dk", model_prob=0.6)
    a = MBL.build_bet_fields(row, entry_odds=-110, **kw)
    b = MBL.build_bet_fields(row, entry_odds=-110, **kw)
    c = MBL.build_bet_fields(row, entry_odds=-120, **kw)
    assert MBL.signature(a) == MBL.signature(b) != MBL.signature(c)


# ----------------------------------------------------------------- page wiring
def test_edge_board_model_board_has_owner_only_manual_logging():
    src = (_HERE / "views" / "15_#L01f4c8_Edge_Board.py").read_text()
    mb = src[src.index('section_header("🧮", "Model board (no odds)")'):]
    assert "Log a Model Board pick" in mb
    assert "_is_owner()" in mb and "B.add_bet(**_mb_fields)" in mb
    assert "MBL.model_prob_for_bet" in mb


# ----------------------------------------------------------------- end-to-end render (AppTest)
def _render_edge_board(monkeypatch, audience=None):
    from streamlit.testing.v1 import AppTest
    import sports

    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    nba = sports.get("NBA")
    rows = [_nba_row("Ja Morant", 1, 26), _nba_row("Jay Tatum", 2, 27)]
    monkeypatch.setattr(nba.engine, "build_slate", lambda date_str: (rows, []))
    logged = []
    monkeypatch.setattr(B, "add_bet", lambda **kw: logged.append(kw) or 1)
    at = AppTest.from_file(str(_HERE / "views" / "15_#L01f4c8_Edge_Board.py"), default_timeout=120)
    at.session_state["sport"] = "NBA"
    if audience:
        at.secrets["AUDIENCE"] = audience
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at, logged


def test_owner_can_log_a_model_board_pick_at_their_own_price(monkeypatch):
    at, logged = _render_edge_board(monkeypatch)
    assert at.selectbox(key="mb_pick")                         # the logging panel rendered
    pick = at.selectbox(key="mb_pick").value
    at.number_input(key=f"mb_odds_{pick}").set_value(-125)
    at.run()
    at.button(key="mb_log").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(logged) == 1
    bet = logged[0]
    assert bet["entry_odds"] == -125 and bet["entry_odds_source"] == "manual"
    assert bet["player_id"] in (1, 2) and bet["sport"] == "NBA" and bet["model_prob"] is not None
    assert any("Logged" in s.value for s in at.success)


def test_public_build_does_not_show_model_board_logging(monkeypatch):
    at, _ = _render_edge_board(monkeypatch, audience="public")
    assert not [s for s in at.selectbox if s.key == "mb_pick"]
