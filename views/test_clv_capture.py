"""Tests for the closing-line capture: the clv_capture matching engine and the runner's
not-started filter. The live odds fetch and DB write can't be tested offline; these lock the
apples-to-apples matching rules that decide what counts as a valid closing line."""

from datetime import datetime, timezone

import clv_capture as C
import capture_closing_lines as R


def _offers():
    # Two players, one HR (single-line) and one Total Bases (2 books each side).
    return [
        {"market": "batter_home_runs", "player": "Aaron Judge", "point": 0.5,
         "over": {"fanduel": 240, "draftkings": 250}, "under": {"fanduel": -300}},
        {"market": "batter_total_bases", "player": "Mookie Betts", "point": 1.5,
         "over": {"draftkings": 130, "betmgm": 125}, "under": {"draftkings": -160}},
    ]


def test_bet_close_price_same_book_match():
    # Bet was FanDuel HR over on Judge -> must return FanDuel's price (240), not DK's.
    bet = {"market": "Batter HR", "player": "Aaron Judge", "side": "Over", "book": "fanduel"}
    assert C.bet_close_price(bet, _offers()) == 240
    # DraftKings TB over 1.5 on Betts -> DK price 130
    bet2 = {"market": "Batter Total Bases", "player": "Mookie Betts", "side": "Over",
            "line": 1.5, "book": "draftkings"}
    assert C.bet_close_price(bet2, _offers()) == 130
    print("✓ close price matches the SAME book (apples-to-apples)")


def test_bet_close_price_rejects_mismatches():
    offers = _offers()
    # Book we bet at isn't offering -> None (never substitute another book)
    assert C.bet_close_price({"market": "Batter HR", "player": "Aaron Judge", "side": "Over",
                              "book": "caesars"}, offers) is None
    # Line mismatch on a multi-line market -> None
    assert C.bet_close_price({"market": "Batter Total Bases", "player": "Mookie Betts",
                              "side": "Over", "line": 2.5, "book": "draftkings"}, offers) is None
    # No book recorded -> None (can't match apples-to-apples)
    assert C.bet_close_price({"market": "Batter HR", "player": "Aaron Judge", "side": "Over",
                              "book": ""}, offers) is None
    print("✓ rejects wrong book, wrong line, and missing book (no guessing)")


def test_capture_updates_report():
    open_bets = [
        {"id": 1, "market": "Batter HR", "player": "Aaron Judge", "side": "Over", "book": "fanduel"},
        {"id": 2, "market": "Batter Total Bases", "player": "Mookie Betts", "side": "Over",
         "line": 1.5, "book": "betmgm"},
        {"id": 3, "market": "Batter HR", "player": "Nobody Here", "side": "Over", "book": "fanduel"},
        {"id": 4, "market": "Batter HR", "player": "Aaron Judge", "side": "Over", "book": ""},
    ]
    rep = C.capture_updates(open_bets, _offers())
    assert rep["updates"][1] == 240 and rep["updates"][2] == 125      # matched at their books
    assert 3 in rep["no_match"]                                        # player not offered
    assert 4 in rep["no_book"]                                         # no book recorded
    print("✓ capture_updates: matches, no-match, and no-book routed correctly")


def test_runner_not_started_filter():
    now = datetime(2026, 7, 12, 22, 0, tzinfo=timezone.utc)
    events = [
        {"id": "future1", "commence_time": "2026-07-12T23:00:00Z"},
        {"id": "started", "commence_time": "2026-07-12T21:00:00Z"},
        {"id": "future2", "commence_time": "2026-07-13T02:00:00Z"},
        {"id": "bad", "commence_time": None},
    ]
    ids = sorted(e["id"] for e in R.not_started(events, now=now))
    assert ids == ["future1", "future2"]      # only not-yet-started, unparseable dropped
    print("✓ runner keeps only not-yet-started games (pre-game prices)")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(); passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
