"""
test_journey_logging.py — offline tests for the practice-phase logging fixes:

  * category + suggested_stake columns round-trip (and migrate an older SQLite DB)
  * filter_by_category never counts uncategorized rows as H2
  * stake_adherence measures "followed the platform's sizing"
  * Edge Board fills log as real prices, with the player ID and the actual book/price/stake
  * compute_edges carries PlayerId through from the projection index
  * Quick Log stamps a model-sourced category

    pytest test_journey_logging.py
"""

import os
import sqlite3
import tempfile

import betlog as B
import mlb_engine as E
import odds_api as O
import projections as P
import quick_log as QL


# --------------------------------------------------------------------------- storage
def test_category_and_suggested_stake_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        B.add_bet(db, player="Jayson Tatum", market="Points", side="Over", line=26.5,
                  entry_odds=-105, model_prob=0.62, stake=7.0, suggested_stake=7.37,
                  category="H2", entry_odds_source="book", sport="NBA")
        bet = B.list_bets(db)[0]
        assert bet["category"] == "H2"
        assert bet["suggested_stake"] == 7.37
        assert bet["entry_odds_source"] == "book"


def test_old_sqlite_db_migrates_new_columns():
    """A bets.db created before these columns existed gains them on first open, and its old rows
    read back as uncategorized with no suggested stake -- nothing is invented for them."""
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE bets (id INTEGER PRIMARY KEY AUTOINCREMENT, ts_placed TEXT NOT NULL, "
                    "player TEXT, market TEXT, side TEXT, line REAL, entry_odds INTEGER, "
                    "model_prob REAL, stake REAL, book TEXT, close_odds INTEGER, result TEXT, "
                    "notes TEXT, slate_date TEXT, game TEXT)")
        con.execute("INSERT INTO bets (ts_placed, player, stake) VALUES ('2026-10-01T00:00:00', 'Old', 2.0)")
        con.commit()
        con.close()
        rows = B.list_bets(db)
        assert len(rows) == 1
        assert rows[0]["category"] is None and rows[0]["suggested_stake"] is None
        B.add_bet(db, player="New", stake=1.0, category="OFF")
        assert {r["player"]: r["category"] for r in B.list_bets(db)} == {"Old": None, "New": "OFF"}


# --------------------------------------------------------------------------- categories
def test_default_category():
    assert B.default_category("NBA") == "H2"
    assert B.default_category("NCAAF") == "H2-beta"
    assert B.default_category("ncaaf") == "H2-beta"
    assert B.default_category("UFC", from_model=False) == "OFF"
    assert B.default_category(None) == "H2"


def test_filter_by_category_keeps_uncategorized_out_of_h2():
    bets = [{"id": 1, "category": "H2"}, {"id": 2, "category": None}, {"id": 3, "category": ""},
            {"id": 4, "category": "PARLAY"}, {"id": 5, "category": "H2-beta"}]
    assert [b["id"] for b in B.filter_by_category(bets, ["H2", "H2-beta"])] == [1, 5]
    assert [b["id"] for b in B.filter_by_category(bets, "Uncategorized")] == [2, 3]
    assert [b["id"] for b in B.filter_by_category(bets, "PARLAY")] == [4]


# --------------------------------------------------------------------------- adherence
def test_stake_adherence():
    bets = [
        {"stake": 4.50, "suggested_stake": 4.37},   # within $0.50 -> followed
        {"stake": 10.0, "suggested_stake": 5.77},   # over
        {"stake": 1.00, "suggested_stake": 6.33},   # under
        {"stake": 20.0, "suggested_stake": 19.0},   # within 10% -> followed
        {"stake": 3.00, "suggested_stake": None},   # not measurable
        {"stake": None, "suggested_stake": 3.0},    # not measurable
    ]
    a = B.stake_adherence(bets)
    assert a == {"n_measured": 4, "n_followed": 2, "rate": 50.0, "n_over": 1, "n_under": 1}
    assert B.stake_adherence([])["rate"] is None


def test_real_price_clv_counts_edge_board_fills():
    """The point of tagging Edge Board fills as "book": they now count toward real-price CLV."""
    row = {"Player": "A", "Market": "Points", "Side": "Over", "Line": 20.5, "ModelProb": 0.6,
           "Stake $": 5.0, "PlayerId": 123, "Game": "X @ Y"}
    fields = QL.edge_board_bet_fields(row, "2026-10-24", "NBA", book="fanduel", price=-105, stake=5.0)
    bet = {**fields, "close_odds": -120}
    rp = B.real_price_clv_summary([bet])
    assert rp["n_real_price"] == 1 and rp["clv_n"] == 1 and rp["avg_clv"] > 0


# --------------------------------------------------------------------------- Edge Board fill
def test_edge_board_bet_fields_records_actual_fill():
    row = {"Player": "Josh Allen", "PlayerId": 4567, "Game": "KC @ BUF", "Market": "Pass Yards",
           "Side": "Over", "Line": 254.5, "ModelProb": 0.6213, "Stake $": 7.37,
           "Book": "draftkings", "Price": -110}
    f = QL.edge_board_bet_fields(row, "2026-10-25", "NFL", book="fanduel", price=-104,
                                 stake=7.0, category="H2", notes="  usage up  ")
    assert f["book"] == "fanduel" and f["entry_odds"] == -104 and f["stake"] == 7.0
    assert f["suggested_stake"] == 7.37
    assert f["entry_odds_source"] == "book"
    assert f["player_id"] == 4567
    assert f["model_prob"] == 0.6213 and f["line"] == 254.5
    assert f["category"] == "H2" and f["notes"] == "usage up"
    assert f["sport"] == "NFL" and f["slate_date"] == "2026-10-25"


def test_edge_board_bet_fields_missing_or_nan_player_id():
    base = {"Player": "X", "Market": "Points", "Side": "Over", "Line": 10.5, "ModelProb": 0.6,
            "Stake $": 2.0}
    for pid in (None, float("nan"), "not-a-number"):
        f = QL.edge_board_bet_fields({**base, "PlayerId": pid}, "2026-10-24", "NBA",
                                     book="draftkings", price=100, stake=2.0)
        assert f["player_id"] is None
    # numpy/pandas often hands back floats for an int column
    f = QL.edge_board_bet_fields({**base, "PlayerId": 12.0}, "2026-10-24", "NBA",
                                 book="draftkings", price=100, stake=2.0)
    assert f["player_id"] == 12


def test_edge_board_bet_fields_default_category_by_sport():
    row = {"Player": "X", "Market": "Rush Yards", "Side": "Over", "Line": 60.5,
           "ModelProb": 0.6, "Stake $": 2.0}
    assert QL.edge_board_bet_fields(row, "d", "NCAAF", book="b", price=-110, stake=1)["category"] == "H2-beta"
    assert QL.edge_board_bet_fields(row, "d", "NFL", book="b", price=-110, stake=1)["category"] == "H2"


def test_edge_board_fields_log_and_read_back():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        row = {"Player": "Connor McDavid", "PlayerId": 8478402, "Game": "EDM @ COL",
               "Market": "Shots on Goal", "Side": "Over", "Line": 3.5, "ModelProb": 0.6,
               "Stake $": 4.0}
        B.add_bet(db, **QL.edge_board_bet_fields(row, "2026-10-24", "NHL", book="betmgm",
                                                 price=115, stake=4.0))
        bet = B.list_bets(db)[0]
        assert bet["player_id"] == 8478402 and bet["book"] == "betmgm"
        assert bet["entry_odds_source"] == "book" and bet["category"] == "H2"


# --------------------------------------------------------------------------- PlayerId carry-through
def test_compute_edges_carries_player_id():
    slug = dict(plateAppearances=600, atBats=540, hits=165, doubles=34, triples=2,
                homeRuns=38, baseOnBalls=55, strikeOuts=140)
    row = {"Hitter": "José Ramírez", "Team": "CLE", "GameLabel": "CLE @ DET", "_pid": 608070,
           "Opp Pitcher": "P", "Lineup": "Confirmed", "_stat": slug, "_exp_pa": 4.5, "_venue_id": None}
    meta = [{"label": "CLE @ DET", "game_date": "2026-07-28T23:10:00Z",
             "home_pm": E.PitcherMetrics(id=None), "home_name": "DET",
             "away_pm": E.PitcherMetrics(id=None), "away_name": "CLE"}]
    index = P.build_projection_index([row], meta, sims=2000, seed=3)
    offers = [{"market": "batter_hits", "player": "Jose Ramirez", "point": 0.5,
               "over": {"fd": -200}, "under": {"fd": 160}}]
    edges, _ = O.compute_edges(index, offers)
    assert edges and all(e["PlayerId"] == 608070 for e in edges)


def test_compute_edges_player_id_none_when_absent():
    slug = dict(plateAppearances=600, atBats=540, hits=165, doubles=34, triples=2,
                homeRuns=38, baseOnBalls=55, strikeOuts=140)
    row = {"Hitter": "José Ramírez", "Team": "CLE", "GameLabel": "CLE @ DET",
           "Opp Pitcher": "P", "Lineup": "Confirmed", "_stat": slug, "_exp_pa": 4.5, "_venue_id": None}
    meta = [{"label": "CLE @ DET", "game_date": None,
             "home_pm": E.PitcherMetrics(id=None), "home_name": "DET",
             "away_pm": E.PitcherMetrics(id=None), "away_name": "CLE"}]
    index = P.build_projection_index([row], meta, sims=2000, seed=3)
    offers = [{"market": "batter_hits", "player": "Jose Ramirez", "point": 0.5,
               "over": {"fd": -200}, "under": {"fd": 160}}]
    edges, _ = O.compute_edges(index, offers)
    assert edges and all(e["PlayerId"] is None for e in edges)


# --------------------------------------------------------------------------- Quick Log
def test_quick_log_stamps_model_category():
    play = {"Game": "X @ Y", "Player": "P", "PlayerId": 1, "Market": "Points", "Side": "Over",
            "Line": 10.5, "ModelProb": 0.6}
    assert QL.bet_log_fields_from_play(play, "2026-10-24", "NBA")["category"] == "H2"
    assert QL.bet_log_fields_from_play(play, "2026-10-24", "NCAAF")["category"] == "H2-beta"


# --------------------------------------------------------------------------- calibration bins
def test_calibration_five_point_buckets_separate_prop_probabilities():
    bets = [{"model_prob": 0.56, "result": "win"}, {"model_prob": 0.58, "result": "loss"},
            {"model_prob": 0.63, "result": "win"}, {"model_prob": 0.71, "result": "win"}]
    cal = B.calibration(bets, n_bins=20)
    assert [(c["lo"], c["hi"], c["n"]) for c in cal] == [(0.55, 0.6, 2), (0.6, 0.65, 1), (0.7, 0.75, 1)]
