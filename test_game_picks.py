"""game_picks.py — college spreads ratings model v2 (Nov 2)."""
from datetime import datetime, timedelta, timezone

import game_picks as GP
import model_store as MS


def _season(n_rounds=12):
    """Round-robin-ish games among 6 teams whose true strengths are known (A best, F worst), home field +3."""
    strength = {"A": 14, "B": 7, "C": 3, "D": -3, "E": -7, "F": -14}
    teams = list(strength)
    games, k = [], 0
    for r in range(n_rounds):
        for i in range(0, len(teams), 2):
            h, a = teams[(i + r) % 6], teams[(i + 1 + 2 * r) % 6]
            if h == a:
                continue
            k += 1
            noise = ((k * 7) % 11) - 5
            margin = strength[h] - strength[a] + 3 + noise
            games.append({"id": k, "season": 2026, "week": r + 1, "home_team": h, "away_team": a,
                          "home_points": 28 + margin / 2, "away_points": 28 - margin / 2, "neutral_site": False,
                          "completed": True, "start_date": "2026-09-01T00:00:00Z"})
    return games


def test_ratings_recover_the_order_and_home_field():
    r = GP.ratings(_season(), lam=0.5)
    m, _t = GP.project(r, "A", "F", neutral=True)
    assert m > 15 and 1.0 < r["hfa"] < 5.0
    order = sorted("ABCDEF", key=lambda t: -(r["off"][t] + r["def"][t]))
    assert order[0] == "A" and order[-1] == "F"
    assert GP.project(r, "A", "Z", False) is None


def _event(home, away, home_point, total=55.5, books=3):
    return {"home_team": home, "away_team": away, "bookmakers": [
        {"key": f"b{i}", "markets": [{"key": "spreads", "outcomes": [{"name": home, "point": home_point},
                                                                    {"name": away, "point": -home_point}]},
                                     {"key": "totals", "outcomes": [{"name": "Over", "point": total},
                                                                   {"name": "Under", "point": total}]}]}
        for i in range(books)]}


def test_line_is_the_schedule_home_teams_margin_even_when_the_books_flip_it():
    ev = _event("Ohio State Buckeyes", "Purdue Boilermakers", -21.5)
    assert GP.line_from_event(ev, "Ohio State")[:2] == (21.5, 55.5)
    flipped = _event("Purdue Boilermakers", "Ohio State Buckeyes", 21.5)        # neutral site listed the other way
    assert GP.line_from_event(flipped, "Ohio State")[0] == 21.5
    assert GP.pick_label("Ohio State", "Purdue", 21.5, "away") == "Purdue +21.5"
    assert GP.pick_label("Ohio State", "Purdue", 21.5, "home") == "Ohio State -21.5"


def test_build_picks_only_past_the_edge_and_store_keeps_open_and_close(tmp_path):
    db = str(tmp_path / "m.db")
    sched = _season()
    now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
    up = [{"id": 900, "season": 2026, "week": 13, "home_team": "A", "away_team": "F", "neutral_site": False,
           "completed": False, "start_date": (now + timedelta(days=2)).isoformat()},
          {"id": 901, "season": 2026, "week": 13, "home_team": "C", "away_team": "D", "neutral_site": False,
           "completed": False, "start_date": (now + timedelta(days=2)).isoformat()}]
    r = GP.ratings(sched)
    m_af = GP.project(r, "A", "F", False)[0]
    m_cd = GP.project(r, "C", "D", False)[0]
    events = [_event("A", "F", -(m_af - 10)), _event("C", "D", -(m_cd + 1))]       # A-F: model 10 off; C-D: 1 off
    old_min = GP.MIN_GAMES
    GP.MIN_GAMES = 5
    try:
        recs = GP.build(sched + up, events, now)
    finally:
        GP.MIN_GAMES = old_min
    by = {x["game_id"]: x for x in recs}
    assert by["900"]["pick"] == "home" and abs(by["900"]["edge"] - 10) < 0.01 and by["901"]["pick"] is None
    assert MS.save_game_picks(recs, db_path=db) == 2
    moved = [dict(by["900"], line=by["900"]["line"] + 1.0, edge=by["900"]["edge"] - 1.0)]
    MS.save_game_picks(moved, db_path=db)
    p = next(x for x in MS.load_game_picks("NCAAF", db_path=db) if x["game_id"] == "900")
    assert p["open_line"] == by["900"]["line"] and p["close_line"] == by["900"]["line"] + 1.0
    assert GP.clv(p) == 1.0                                  # the line moved a point toward the home pick
    # graded against the close line
    assert GP.result(p, 40, 40 - (p["close_line"] + 0.5)) == "win"
    assert GP.result(p, 40, 40 - (p["close_line"] - 0.5)) == "loss"
    assert MS.grade_game_pick("NCAAF", "900", 45, 10, "win", db_path=db)
    assert [x["game_id"] for x in MS.load_game_picks("NCAAF", ungraded=True, db_path=db)] == ["901"]


def test_grading_from_espn_and_summary(tmp_path):
    db = str(tmp_path / "m.db")
    ko = datetime(2026, 11, 7, 20, tzinfo=timezone.utc)
    rec = {"sport": "NCAAF", "game_id": "77", "season": 2026, "week": 11, "kickoff": ko.isoformat(), "home": "Ohio State",
           "away": "Purdue", "neutral": False, "model_margin": 30.0, "model_total": 55, "line": 21.5, "line_total": 55.5,
           "books": 3, "edge": 8.5, "pick": "home", "pick_label": "Ohio State -21.5"}
    MS.save_game_picks([rec], db_path=db)
    espn = {"events": [{"competitions": [{"status": {"type": {"completed": True}}, "competitors": [
        {"homeAway": "home", "score": "38", "team": {"location": "Ohio State", "displayName": "Ohio State Buckeyes"}},
        {"homeAway": "away", "score": "10", "team": {"location": "Purdue", "displayName": "Purdue Boilermakers"}}]}]}]}
    n = GP.grade_open(fetch=lambda url, params=None: espn, now=ko + timedelta(hours=6), db_path=db)
    assert n == 1
    s = GP.summary(MS.load_game_picks("NCAAF", db_path=db))
    assert s["record"] == "1-0" and s["by_edge"][0]["edge"] == "7–10"


def test_morning_note():
    import daily_review as D
    notes = D.game_pick_notes({"yesterday": {"graded": 3, "record": "2-1"},
                               "season": {"graded": 10, "record": "6-4", "hit": 0.6, "avg_clv": 0.8}})
    assert notes[0].endswith("2-1 yesterday.") and "6-4 (60%" in notes[1] and "+0.8" in notes[1]
    assert D.game_pick_notes(None) == []
