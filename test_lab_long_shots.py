"""Nov 14: lab long shots (tennis / international hoops / soccer underdogs, soccer goalscorers) and soccer rows in
Today's best."""
from datetime import datetime, timezone

import lab_long_shots as L
import todays_best as TB

NOW = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)
KO = "2026-11-14T23:00:00Z"          # 6 PM ET, not started


def test_dog_side_needs_price_and_value():
    p = {"home": "A", "away": "B", "best_home": -500, "best_away": 400, "best_away_book": "dk"}
    s = L.dog_side(p, 0.75)                   # B: 25% at +400 -> 1.25x
    assert s and s["team"] == "B" and s["price"] == 400 and s["ev"] == 0.25
    assert L.dog_side(p, 0.85) is None        # 15% at +400 -> loses
    assert L.dog_side(dict(p, best_away=250), 0.75) is None     # shorter than +300


def test_soccer_dogs_counts_the_draw():
    p = {"home": "A", "away": "B", "p_home": 0.6, "p_draw": 0.26, "p_away": 0.14,
         "best_home": -150, "best_draw": 320, "best_away": 600}
    got = {x["side"] for x in L.soccer_dogs(p)}
    assert got == {"draw"}                    # 26% x 4.2 > 1; 14% x 7.0 = 0.98 -> no
    p["best_away"] = 700                      # 14% x 8 = 1.12
    assert {x["side"] for x in L.soccer_dogs(p)} == {"draw", "away"}


def test_dog_rows_reads_the_labs_and_skips_started_games():
    recs = {
        "TENNIS": [{"home": "X", "away": "Y", "model_p": 0.7, "best_home": -400, "best_away": 350, "kickoff": KO,
                    "game_id": "t1", "tournament": "ATP Finals"},
                   {"home": "X2", "away": "Y2", "model_p": 0.7, "best_home": -400, "best_away": 350,
                    "kickoff": "2026-11-14T14:00:00Z", "game_id": "t2"}],
        "SOCCER_EPL": [{"home": "A", "away": "B", "p_home": 0.6, "p_draw": 0.26, "p_away": 0.14, "best_home": -150,
                        "best_draw": 320, "best_away": 300, "kickoff": KO, "game_id": "s1", "sport": "SOCCER_EPL"}],
    }
    out = L.dog_rows("2026-11-14", load=lambda lg: recs.get(lg, []), now=NOW, soccer_leagues=["SOCCER_EPL"])
    assert [r["pick"] for r in out["TENNIS"]] == ["Y to win"]
    assert out["TENNIS"][0]["_rec"]["game_id"] == "t1" and out["TENNIS"][0]["bet_market"] == "Moneyline"
    assert [r["pick"] for r in out["SOCCER"]] == ["Draw"]
    assert out["INTL"] == []


def test_scorer_picks_filters():
    rows = [{"market": "Anytime Goal", "player": "P1", "price": 450, "chance": 0.25, "ev": 0.375, "starts": 8},
            {"market": "Anytime Goal", "player": "P2", "price": 300, "chance": 0.3, "ev": 0.2, "starts": 8},
            {"market": "Anytime Goal", "player": "P3", "price": 500, "chance": 0.2, "ev": 0.2, "starts": 3},
            {"market": "Shots", "player": "P4", "price": 500, "chance": 0.2, "ev": 0.2, "starts": 9},
            {"market": "Anytime Goal", "player": "P5", "price": 600, "chance": 0.1, "ev": -0.3, "starts": 9}]
    assert [x["player"] for x in L.scorer_picks(rows)] == ["P1"]


def test_scorer_rows_log_as_soccer_props_that_settle():
    m = {"home": "A", "away": "B", "kickoff": KO, "game_id": "e1"}
    s = {"side": "Yes", "pick": "P1 anytime goal", "player": "P1", "chance": 0.25, "price": 450.0, "book": "dk",
         "ev": 0.375, "line": 0.5}
    r = L._row("SOCCER", "SOCCER_EPL", "Premier League", m, s, kind="Anytime Goal")
    assert "_rec" not in r and r["game"] == "B @ A"
    b = TB.bet_rows([r], 2.0, False, "long-shot,lab", "2026-11-14")[0]
    assert b["market"] == "Anytime Goal" and b["side"] == "Yes" and b["line"] == 0.5
    assert "sp:SOCCER_EPL" in b["notes"] and "long-shot" in b["notes"]


def test_top_one_per_game():
    rows = [{"game": "g1", "chance": 0.3, "EV per $1": 0.1}, {"game": "g1", "chance": 0.29, "EV per $1": 0.2},
            {"game": "g2", "chance": 0.2, "EV per $1": 0.1}]
    assert [r["chance"] for r in L.top(rows)] == [0.3, 0.2]


def test_soccer_rows_and_flags(monkeypatch):
    import model_store as MS
    rec = {"sport": "SOCCER_EPL", "game_id": "s1", "kickoff": KO, "home": "A", "away": "B", "p_home": 0.5,
           "p_draw": 0.27, "p_away": 0.23, "xg_home": 1.6, "xg_away": 1.0, "mkt_home": 0.48, "mkt_draw": 0.28,
           "mkt_away": 0.24, "sharp": True, "best_home": 110, "best_draw": 260, "best_away": 330,
           "value": [{"market": "Moneyline", "side": "home", "price": 110, "book": "fd", "fair": 0.48, "ev": 0.008},
                     {"market": "Total", "side": "over", "price": -105, "book": "dk", "fair": 0.53, "ev": 0.03,
                      "line": 2.5}]}
    monkeypatch.setattr(MS, "load_game_picks", lambda lg, ungraded=True, **k: [rec] if lg == "SOCCER_EPL" else [])
    rows = TB.soccer_rows("2026-11-14", leagues=["SOCCER_EPL"])
    assert len(rows) == 1 and rows[0]["sport"] == "SOCCER" and rows[0]["winner"] == "A"
    assert rows[0]["status"] == "tracking only" and rows[0]["best_tested"] is False
    assert rows[0]["bet_market"] == "Moneyline" and rows[0]["bet_side"] == "home"
    flags = TB.soccer_flags("2026-11-14", leagues=["SOCCER_EPL"])
    assert [f["pick"] for f in flags] == ["Over 2.5 goals", "A to win"]
    b = TB.bet_rows([dict(flags[0], best=flags[0]["pick"])], 2.0, False, "t", "2026-11-14")[0]
    assert b["sport"] == "SOCCER" and b["market"] == "Total" and b["line"] == 2.5
