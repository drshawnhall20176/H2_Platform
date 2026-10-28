"""
test_form_policy.py — the one platform-wide definition of recent form (form_policy.py).

    python -m pytest test_form_policy.py
"""

import basketball_engine as BB
import form_policy as FPol


def mitchell_log():
    cur = [dict(pts=p, reb=r, src="current") for p, r in ((21, 0), (22, 1), (18, 2), (11, 0))]
    prior = [dict(pts=p, reb=r, src="prior") for p, r in ((12, 2), (15, 3), (9, 1), (12, 4))]
    return cur + prior


def test_this_season_first_topped_up_to_five_with_old_games_at_half_weight():
    log = mitchell_log()
    lines = FPol.select(log)
    assert len(lines) == 5 and [g["src"] for g in lines] == ["current"] * 4 + ["prior"]
    w = FPol.weights(lines)
    assert w[0] == 1.0 and abs(w[4] - 0.5 * 0.5) < 1e-12             # 4 games back (x0.5) and last season (x0.5)
    f = FPol.form_avg(log, "pts")
    assert 17.5 < f < 19.0                                           # not 15.7 (flat average incl. 4 April games)
    assert FPol.describe(log)["note"] == "4 games this season + 1 from last season (half weight)"


def test_a_full_season_log_ignores_last_season_and_preseason_is_a_last_resort():
    cur = [dict(pts=10, src="current") for _ in range(7)]
    assert all(g["src"] == "current" for g in FPol.select(cur + [dict(pts=40, src="prior")]))
    assert FPol.form_avg([dict(pts=8, src="preseason")], "pts") == 8
    assert FPol.form_avg([], "pts") is None
    assert FPol.form_avg([dict(pts=10)], "pts") == 10                # no src = current


def test_window_averages_top_up_from_last_season_and_say_so():
    log = mitchell_log()
    six = FPol.window_avg(log, "pts", 6)
    assert six["games"] == 6 and six["prior"] == 2 and abs(six["avg"] - 16.5) < 1e-9
    ten = FPol.window_avg(log, "pts", 10)
    assert ten["games"] == 8 and ten["prior"] == 4
    assert FPol.window_avg([], "pts", 5) == {"avg": None, "games": 0, "prior": 0}


def test_one_wording_for_rest():
    assert FPol.rest_text(1) == "back-to-back" and FPol.rest_text(2) == "1 day off"
    assert FPol.rest_text(4) == "3 days off" and FPol.rest_text(None) == "rest unknown"


def test_game_dates_are_eastern_not_utc():
    assert BB.eastern_date("2026-10-24T00:00Z") == "2026-10-23"           # an 8 PM ET Oct 23 tip
    assert BB.eastern_date("2026-10-24T23:30Z") == "2026-10-24"
    assert BB.eastern_date("2026-10-24") == "2026-10-24" and BB.eastern_date(None) == ""


def test_team_points_are_the_final_score_not_points_in_the_paint():
    data = {"gamepackageJSON": {
        "header": {"competitions": [{"competitors": [{"id": "1", "score": "112"}, {"id": "2", "score": "104"}]}]},
        "boxscore": {"teams": [
            {"team": {"id": "1"}, "statistics": [{"name": "pointsInPaint", "displayValue": "52"},
                                                 {"name": "totalRebounds", "displayValue": "44"},
                                                 {"name": "assists", "displayValue": "27"},
                                                 {"name": "threePointFieldGoalsMade-threePointFieldGoalsAttempted",
                                                  "displayValue": "13-35"}]},
            {"team": {"id": "2"}, "statistics": [{"name": "points", "displayValue": "104"},
                                                 {"name": "totalRebounds", "displayValue": "40"}]}]}}}
    out = BB.get_game_team_totals("g", "cdn", lambda url, params=None: data)
    assert out[1]["pts"] == 112 and out[2]["pts"] == 104 and out[1]["fg3m"] == 13
