"""Nov 26: the Rulebook's scoreboard -- rules collected from graded picks, metrics, gates and stages."""
import rule_scoreboard as RS


def _ps(n, wins, day0="2026-11-01", price=-110, days=12, clv=None):
    from datetime import date, timedelta
    out = []
    for i in range(n):
        d = (date.fromisoformat(day0) + timedelta(days=i % days)).isoformat()
        out.append(RS._p(d, i < wins, price, clv))
    return out


def test_metrics_and_gate1():
    ps = _ps(120, 70)
    m = RS.metrics(ps, today="2026-11-20")
    assert m["n"] == 120 and abs(m["hit"] - 70 / 120) < 1e-9 and m["days"] == 12
    g = RS.gate(m, RS.GATE1)
    assert g["Sample"][0] and g["Return"][0] == (m["roi"] >= 0.02)


def test_gate2_needs_300_and_low_end_above_zero():
    m = RS.metrics(_ps(150, 90), today="2026-11-20")
    g = RS.gate(m, RS.GATE2)
    assert not g["Sample"][0] and "150 of 300" in g["Sample"][1]


def test_weekly_sports_count_weeks():
    m = RS.metrics(_ps(120, 70, days=12), weekly=True, today="2026-11-20")
    assert m["weekly"] and m["weeks"] >= 2
    assert "weeks" in RS.gate(m, RS.GATE1)["Sample"][1]


def test_close_gap_gate():
    m = RS.metrics(_ps(72, 39), today="2026-11-26")
    g = RS.close_gap_gate(m)
    assert g["Sample"] == [False, "72 of 200 games"] or g["Sample"] == (False, "72 of 200 games")


def test_from_games_takes_paused_band_rows():
    rows = [{"sport": "NCAAMB", "money": False, "money_score": 0.06, "money_chance": 0.5, "money_market": "Spread",
             "money_result": "win", "money_price": -110, "_day": "2026-11-24"},
            {"sport": "NCAAMB", "money": False, "money_score": 0.30, "money_chance": 0.5, "money_market": "Spread",
             "money_result": "win", "money_price": -110, "_day": "2026-11-24"}]
    got = RS.from_games(rows)
    assert len(got["money_games|NCAAMB"]) == 1


def test_build_stages_and_health(monkeypatch):
    import money_score as MSC
    monkeypatch.setattr(MSC, "PAUSED", {"NCAAMB": "2026-11-22"})
    rec = RS.build({}, [], "2026-11-26", close_gap=_ps(72, 39, day0="2026-11-23", days=3))
    cg = [r for r in rec["rules"] if r["key"] == "close_gap|NCAAMB"][0]
    assert cg["stage"] == "Paper" and cg["next"] == "Close gap's gate" and not cg["ready"]
    assert RS.stage("money_games", "NCAAMB", "2026-11-26") == "Paused"
    bad = RS.metrics(_ps(200, 80), today="2026-11-20")
    assert RS.health(bad).startswith("⛔")


def test_the_page_is_an_office_page():
    import office as OF
    assert OF.is_office_page("65")


def test_page_renders(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import streamlit as st
    st.cache_data.clear()
    rec = RS.build({}, [], "2026-11-26", close_gap=_ps(72, 39, day0="2026-11-23", days=3))
    monkeypatch.setattr(RS, "load", lambda get=None: rec)
    at = AppTest.from_file("views/65_Rule_Scoreboard.py", default_timeout=60).run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]


# --------------------------------------------------------------------------- Nov 26: the proof forecast
def _picks(n, roi, dec=1.714, start="2026-10-01", per_day=5):
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    wins = round(n * (1 + roi) / dec)
    return [[(d0 + timedelta(days=i // per_day)).isoformat(), i < wins, dec, None] for i in range(n)]


def _rule(picks, stage="Live test", sport="NBA", rule="lock", ready=False):
    import rule_scoreboard as RS
    m = RS.metrics(picks)
    return {"m": m, "picks": picks, "sport": sport, "stage": stage, "rule": rule, "ready": ready}


def test_small_edge_cannot_clear_this_season():
    import rule_scoreboard as RS
    f = RS.forecast(_rule(_picks(294, 0.01)), "2026-11-26")
    assert f["state"] == "below_bar" and "below the +2%" in f["text"]
    assert RS.picks_needed(_picks(10, 0.01), 0.01, 300) > 15000     # +1% at -140 needs ~19,000 picks
    assert 600 < RS.picks_needed(_picks(10, 0.05), 0.05, 300) < 900  # +5%: ~770


def test_big_edge_is_on_track_and_losing_says_so():
    import rule_scoreboard as RS
    f = RS.forecast(_rule(_picks(120, 0.10), stage="Live test"), "2026-11-26")
    assert f["state"] == "on_track" and f["text"].startswith("On track for ~")
    assert RS.forecast(_rule(_picks(120, -0.10)), "2026-11-26")["state"] == "losing"
    slow = RS.forecast(_rule(_picks(60, 0.03, per_day=1), sport="NFL"), "2026-11-26")
    assert slow["state"] == "not_this_season" and "Not this season" in slow["text"]


def test_paper_rule_uses_gate_one_and_season_end_rolls_over():
    import rule_scoreboard as RS
    f = RS.forecast(_rule(_picks(40, 0.10), stage="Paper"), "2026-11-26")
    assert f["state"] == "on_track" and "60 more picks" in f["text"]
    assert RS.season_end("NFL", "2026-11-26").isoformat() == "2027-01-10"
    assert RS.season_end("NBA", "2026-11-26").isoformat() == "2027-04-12"
