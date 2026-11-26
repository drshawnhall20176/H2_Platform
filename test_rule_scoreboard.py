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
