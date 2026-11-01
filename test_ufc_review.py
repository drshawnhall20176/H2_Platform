"""ufc_review.py — UFC card graded against saved prices, Bet Log settlement, recap (Nov 1)."""
import json
import os
from datetime import datetime, timezone

import betlog as B
import daily_review as D
import model_store as MS
import ufc_review as U

HERE = os.path.dirname(os.path.abspath(__file__))
ESPN = json.load(open(os.path.join(HERE, "test_fixtures", "espn_ufc_scoreboard_20261031.json")))


def _espn(url, params=None):
    if "mma/ufc/scoreboard" in url and (params or {}).get("dates") == "20261031":
        return ESPN
    if "mma/ufc/scoreboard" in url:
        return {"events": []}
    return None


def _event(eid, a, b, pa, pb, commence="2026-11-01T02:00:00Z", point=1.5, over=-150, under=120, books=("draftkings", "fanduel")):
    return {"id": eid, "commence_time": commence, "home_team": a, "away_team": b,
            "bookmakers": [{"key": k, "markets": [
                {"key": "h2h", "outcomes": [{"name": a, "price": pa}, {"name": b, "price": pb}]},
                {"key": "totals", "outcomes": [{"name": "Over", "price": over, "point": point},
                                               {"name": "Under", "price": under, "point": point}]}]} for k in books]}


def test_results_parse_from_espn():
    bouts = U.card_results("2026-10-31", fetch=_espn)
    assert len(bouts) == 12
    by = {b["winner"]: b for b in bouts}
    assert by["Tom Nolan"]["method"] == "KO/TKO" and by["Tom Nolan"]["rounds"] == 5
    assert by["Rodrigo Sezinando"]["method"] == "KO/TKO"          # stoppage at the end of R2
    assert by["Lucia Szabová"]["method"] == "KO/TKO"
    assert by["Joe Kropschot"]["method"] == "Submission"
    assert abs(by["Joe Kropschot"]["elapsed"] - (1 + 85 / 300)) < 1e-9
    assert by["Zach Reese"]["method"] == "Decision" and by["Zach Reese"]["elapsed"] == 3
    s = U.summarize(U.grade_card(bouts, []))
    assert (s["finishes"], s["decisions"], s["ko"], s["subs"]) == (6, 6, 5, 1)
    assert s["priced"] == 0


def test_record_takes_the_median_no_vig_price():
    rec = U.record_from_event(_event("e1", "Renato Moicano", "Tom Nolan", -200, 165))
    assert rec["card_date"] == "2026-10-31"                       # 10 PM ET is still Saturday's card
    assert 0.63 < rec["p_a"] < 0.66 and rec["books"] == 2
    assert rec["total_point"] == 1.5 and 0.55 < rec["p_over"] < 0.6
    assert U.record_from_event({"home_team": "A", "away_team": "B", "bookmakers": []}) is None


def test_capture_skips_started_bouts(tmp_path):
    db = str(tmp_path / "m.db")
    now = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
    payload = [_event("e1", "Renato Moicano", "Tom Nolan", -200, 165),
               _event("e0", "Tainara Lisboa", "Lucia Szabová", -150, 125, commence="2026-10-31T22:00:00Z")]
    assert U.capture("k", fetch=lambda u, p: payload, now=now, db_path=db) == 1
    assert [r["event_id"] for r in MS.load_ufc_odds("2026-10-31", db_path=db)] == ["e1"]
    assert MS.ufc_card_dates(db_path=db) == ["2026-10-31"]


def test_grading_upsets_and_totals():
    bouts = U.card_results("2026-10-31", fetch=_espn)
    prices = [U.record_from_event(e) for e in (
        _event("e1", "Renato Moicano", "Tom Nolan", -200, 165, point=2.5),       # fav loses by KO in R3 (2.29 rounds)
        _event("e2", "Joe Kropschot", "Nick Klein", -300, 240),                 # fav wins by sub R2 -> over 1.5
        _event("e3", "Jacobe Smith", "Randy Brown", -150, 125, point=2.5))]     # fav wins decision -> over 2.5
    rows = U.grade_card(bouts, prices)
    main = next(r for r in rows if "Tom Nolan" in r["fighters"])
    assert main["fav"] == "Renato Moicano" and main["fav_won"] is False and main["over"] is False
    kro = next(r for r in rows if "Joe Kropschot" in r["fighters"])
    assert kro["fav_won"] is True and kro["over"] is False                      # 1.28 rounds < 1.5
    s = U.summarize(rows)
    assert s["favorites"]["won"] == 2 and s["favorites"]["lost"] == 1
    assert s["upsets"][0][0] == "Tom Nolan"
    assert s["totals"] == {"over": 1, "under": 2, "expected_over": s["totals"]["expected_over"]}
    text = U.recap("UFC Fight Night", "2026-10-31", s, rows)
    assert "Favorites went **2-1**" in text and "Tom Nolan" in text and "6 finishes" in text


def test_bet_results():
    bouts = U.card_results("2026-10-31", fetch=_espn)
    nolan = U.find_bout(bouts, "Renato Moicano", "Tom Nolan")
    assert U.bet_result({"market": "Moneyline", "side": "Tom Nolan"}, nolan) == "win"
    assert U.bet_result({"market": "Moneyline", "side": "Renato Moicano"}, nolan) == "loss"
    assert U.bet_result({"market": "Fight Duration", "side": "Over", "line": 2.5}, nolan) == "loss"
    assert U.bet_result({"market": "Fight Duration", "side": "Under", "line": 2.5}, nolan) == "win"
    assert U.bet_result({"market": "Win by KO/TKO", "side": "Tom Nolan"}, nolan) == "win"
    assert U.bet_result({"market": "Win by Decision", "side": "Tom Nolan"}, nolan) == "loss"
    lee = U.find_bout(bouts, "Julian Erosa", "Jeong Yeong Lee")
    assert lee is not None


def test_morning_review_settles_ufc_bets(tmp_path):
    model_db, bet_db = str(tmp_path / "m.db"), str(tmp_path / "b.db")
    MS.save_ufc_odds([U.record_from_event(_event("e1", "Renato Moicano", "Tom Nolan", -200, 165))], db_path=model_db)
    base = {"ts_placed": "2026-10-31T20:00:00", "slate_date": "2026-10-31", "sport": "UFC", "player": None,
            "game": "Renato Moicano vs. Tom Nolan", "odds": 165, "stake": 1.0}
    B.add_bet(db_path=bet_db, **dict(base, market="Moneyline", side="Tom Nolan", line=None))
    B.add_bet(db_path=bet_db, **dict(base, market="Fight Duration", side="Over", line=1.5, odds=-150))
    B.add_bet(db_path=bet_db, **dict(base, game="Someone vs. Nobody", market="Moneyline", side="Someone", line=None))
    out = D.run("2026-11-01", fetch=_espn, db_path=model_db, bet_db=bet_db, sports=("UFC",))
    rep = out["UFC"]
    assert rep["card"]["summary"]["favorites"] == {"won": 0, "lost": 1, "expected": rep["card"]["summary"]["favorites"]["expected"]}
    assert sorted(s["result"] for s in rep["settlement"]["settled"]) == ["win", "win"]
    assert len(rep["settlement"]["unresolved"]) == 1
    assert {b["result"] for b in B.list_bets(db_path=bet_db, settled=True)} == {"win"}
    assert MS.load_daily_review("UFC", "2026-11-01", db_path=model_db)["card"]["date"] == "2026-10-31"


def test_no_card_no_bets_no_report(tmp_path):
    assert U.review("2026-11-05", [], fetch=_espn, db_path=str(tmp_path / "m.db")) is None


def test_capture_window():
    import capture_ufc_odds as C
    now = datetime(2026, 10, 31, 16, 0, tzinfo=timezone.utc)
    evs = [{"commence_time": "2026-11-01T02:00:00Z"}, {"commence_time": "2026-11-08T02:00:00Z"}, {"commence_time": None}]
    assert C.upcoming(evs, now) == 1
