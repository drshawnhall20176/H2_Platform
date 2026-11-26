"""Nov 26: the prop market watch and quotes that look off."""
from datetime import datetime, timezone

import book_check as BC
import prop_moves as PMV

NOW = datetime(2026, 11, 26, 17, 0, tzinfo=timezone.utc)
LATER = "2026-11-26T21:30:00Z"


def _r(book, line, at, start=LATER, side="Over"):
    return {"book": book, "line": line, "captured_at": at, "commence_time": start, "side": side, "game": "DAL @ PHI"}


def test_moves_median_of_books_moving_together_pregame_only():
    idx = {("Dak Prescott", "Pass Yards"): [_r("dk", 249.5, "2026-11-26T12:00Z"), _r("dk", 274.5, "2026-11-26T16:00Z"),
                                            _r("fd", 250.5, "2026-11-26T12:00Z"), _r("fd", 270.5, "2026-11-26T16:00Z"),
                                            _r("mgm", 249.5, "2026-11-26T12:00Z"), _r("mgm", 249.5, "2026-11-26T16:00Z")],
           ("Started Guy", "Points"): [_r("dk", 10.5, "2026-11-26T12:00Z", start="2026-11-26T16:00Z"),
                                       _r("dk", 30.5, "2026-11-26T16:30Z", start="2026-11-26T16:00Z"),
                                       _r("fd", 10.5, "2026-11-26T12:00Z", start="2026-11-26T16:00Z"),
                                       _r("fd", 30.5, "2026-11-26T16:30Z", start="2026-11-26T16:00Z")],
           ("One Book", "Points"): [_r("dk", 10.5, "2026-11-26T12:00Z"), _r("dk", 14.5, "2026-11-26T16:00Z")]}
    got = PMV.moves(idx, NOW)
    assert [m["player"] for m in got] == ["Dak Prescott"]
    m = got[0]
    assert m["delta"] == 22.5 and m["books"] == 2 and m["open"] == 250.0
    assert PMV.text(m) == "Dak Prescott · Pass Yards 250 → 272.5 ▲ +22.5 (2 books)"


def test_looks_off_flags_the_outlier_only_with_enough_books():
    assert PMV.looks_off({"dk": -110, "fd": -112, "mgm": -108, "novig": +150}) .keys() == {"novig"}
    assert PMV.looks_off({"dk": -110, "novig": +150}) == {}


def test_best_price_skips_a_quote_that_looks_off_and_the_verdict_says_so():
    quotes = {24.5: {"books": {"draftkings": -110, "fanduel": -112, "betmgm": -108, "novig": 150}}}
    assert BC.best_at_line(quotes, 24.5, ["draftkings", "fanduel", "betmgm", "novig"]) == ("betmgm", -108)
    row = {"line": 24.5, "side": "Over", "chance": 0.62, "kind": "🃏 Bet"}
    j = BC.judge(row, quotes, "novig", ["draftkings", "fanduel", "betmgm", "novig"])
    assert j["book_verdict"].startswith("⚠ Looks off")
    assert not BC.judge(row, quotes, "draftkings", ["draftkings"])["book_verdict"].startswith("⚠")


def test_for_sports_uses_plain_market_names(monkeypatch):
    monkeypatch.setattr(PMV, "market_names", lambda sp: {"player_pass_yds": "Pass Yards"})
    idx = {("Dak Prescott", "player_pass_yds"): [_r("dk", 249.5, "2026-11-26T12:00Z"), _r("dk", 274.5, "2026-11-26T16:00Z"),
                                                  _r("fd", 249.5, "2026-11-26T12:00Z"), _r("fd", 270.5, "2026-11-26T16:00Z")]}
    got = PMV.for_sports(["NFL"], "2026-11-26", index_for=lambda sp, d: idx, now=NOW)
    assert got[0]["market"] == "Pass Yards" and got[0]["sport"] == "NFL"
