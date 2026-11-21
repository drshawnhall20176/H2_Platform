"""Nov 21: the morning data checks (data_checks.py)."""
import data_checks as DC


def _bet(**kw):
    b = {"id": 1, "slate_date": "2026-11-20", "sport": "NBA", "player": "A", "player_id": 7, "market": "Points",
         "side": "Under", "line": 10.5, "result": "win", "entry_odds": -110, "close_odds": -115}
    b.update(kw)
    return b


def test_a_bet_settled_against_the_final_box_score_is_flagged():
    out = DC.check_settlement([_bet()], "2026-11-21", results=lambda sp, d: {7: {"pts": 11.0}})
    assert out and out[0]["level"] == "error" and "#1" in out[0]["detail"]
    assert DC.check_settlement([_bet()], "2026-11-21", results=lambda sp, d: {7: {"pts": 9.0}}) == []


def test_mismatched_closes_and_impossible_prices():
    assert DC.check_closes([_bet(close_odds=+300)], "2026-11-21")
    assert DC.check_prices([_bet(entry_odds=50)], [], "2026-11-21")
    assert DC.check_prices([], [{"pick": "x", "price": 25000}], "2026-11-21")
    assert DC.check_prices([_bet()], [{"pick": "x", "price": -120}], "2026-11-21") == []


def test_ungraded_ledgers_are_flagged():
    def load(kind, sp, day):
        if kind == "strong":
            return {"rows": {"a": {"pick": "x", "price": -110}}, "graded_at": None}
        return {"rows": {}, "graded_at": None}
    out = DC.check_ledgers("2026-11-21", load)
    assert out and out[0]["level"] == "error"


def test_run_collects_everything_without_saving():
    rec = DC.run("2026-11-21", bets=[_bet()], results=lambda sp, d: {7: {"pts": 11.0}},
                 ledger_load=lambda k, s, d: {"rows": {}, "graded_at": None}, save=False)
    assert rec["errors"] >= 1 and any(i["check"] == "settlement" for i in rec["issues"])
