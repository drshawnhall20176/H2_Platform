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


def test_a_game_model_leaning_home_raises_a_warning():
    """Nov 22: the college model rated home teams 7.2 too high in close games for days unnoticed."""
    import data_checks as DC
    from datetime import datetime, timezone
    now = datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc)
    past = [{"kickoff": f"2026-11-{d:02d}T23:00:00Z", "model_margin": 8.0 + (i % 3), "home_spread": -2.0,
             "final_home": 70 + (i % 5), "final_away": 69} for i, d in enumerate([15, 16, 17, 18, 19, 20, 21] * 6)]
    upcoming = [{"kickoff": "2026-11-22T23:00:00Z", "model_margin": 6.0, "home_spread": -2.0} for _ in range(14)]
    out = DC.check_bias("2026-11-22", load=lambda lg: past + upcoming if lg == "NCAAMB" else [], now=now)
    text = " ".join(i["detail"] for i in out)
    assert "NCAAMB game model rates home teams" in text and "leans home on 14 of 14" in text
    fair = [dict(r, final_home=r["final_away"] + r["model_margin"] + (1 if i % 2 else -1)) for i, r in enumerate(past)]
    mixed = [dict(r, model_margin=6.0 if i % 2 else -6.0) for i, r in enumerate(upcoming)]
    assert DC.check_bias("2026-11-22", load=lambda lg: fair + mixed if lg == "NCAAMB" else [], now=now) == []


def test_too_extreme_margins_and_high_totals_warn():
    import data_checks as DC
    from datetime import datetime, timezone
    now = datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc)
    recs = []
    for i in range(70):
        m = (i % 14) - 7.0                                         # model margins -7..+6
        recs.append({"kickoff": f"2026-11-{15 + i % 7:02d}T23:00:00Z", "model_margin": m * 2, "model_total": 150.0,
                     "final_home": 70 + m + (1 if i % 2 else -1), "final_away": 70.0})
    text = " ".join(i["detail"] for i in DC.check_bias("2026-11-22", load=lambda lg: recs if lg == "NBA" else [], now=now))
    assert "margins are too extreme" in text and "totals run" in text and "high" in text


def test_shown_picks_running_high_warn():
    import data_checks as DC
    rows = {f"k{i}": {"sport": "NBA", "earned": 0.57, "price": None, "pickem_only": True,
                      "result": "win" if i % 5 < 2 else "loss"} for i in range(60)}
    load = lambda kind, sp, day: {"rows": rows} if (kind, day) == ("strong", "2026-11-20") else {"rows": {}}
    text = " ".join(i["detail"] for i in DC.check_shown("2026-11-22", load))
    assert "NBA pick'em picks shown said 57% and hit 40%" in text
