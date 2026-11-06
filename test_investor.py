"""Investor Relations (Nov 6): the model-performance evidence."""


def test_wilson_and_bets_needed():
    import investor as I
    lo, hi = I.wilson(60, 100)
    assert 0.50 < lo < 0.51 and 0.69 < hi < 0.70
    assert I.wilson(0, 0) == (None, None)
    assert 1500 < I.bets_for_edge(0.03) < 5000
    assert I.verdict(50, 0.7, 0.6, 0.5) == "Too early to tell"
    assert I.verdict(500, 0.66, 0.6, 0.62) == "Above what it needs, beyond chance"


def test_sections_from_records():
    import investor as I
    calls = [{"sport": "NBA", "hit": 1, "model_prob": 0.6, "call_date": "2026-11-01"},
             {"sport": "NBA", "hit": 0, "model_prob": 0.6, "call_date": "2026-11-02"},
             {"sport": "NFL", "hit": None, "model_prob": 0.6, "call_date": "2026-11-03"}]
    lc = I.locked_calls(calls)
    assert lc["locked"] == 3 and lc["n"] == 2 and lc["hit"] == 0.5 and lc["first"] == "2026-11-01"
    rep = {"NBA": {"morning": "2026-11-06", "trend": {"days": 30, "slates": 6, "use": [
        {"Use": "🎟️ Parlay + Single", "Graded": 51, "Hits": 33, "Hit rate": 0.647, "Model said": 0.62}]},
        "calibration": {"buckets": [{"range": "60%–65%", "n": 40, "shown": 0.62, "hit": 0.6}]}}}
    t = I.use_tags(rep)
    assert t[0]["n"] == 51 and abs(t[0]["hit"] - 33 / 51) < 1e-9
    assert I.calibration(rep)[0]["hit"] == 0.6


def test_page_renders(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    import analyst_ledger as AL
    import betlog as B
    import model_store as MS
    monkeypatch.setattr(AL, "fetch_calls", lambda **kw: [{"sport": "NBA", "hit": 1, "model_prob": 0.6, "call_date": "2026-11-01"}])
    monkeypatch.setattr(MS, "daily_review_mornings", lambda sp, db_path=None: ["2026-11-06"] if sp == "NBA" else [])
    monkeypatch.setattr(MS, "load_daily_review", lambda sp, m, db_path=None: {"morning": m, "trend": {"use": [
        {"Use": "🎟️ Parlay leg", "Graded": 66, "Hits": 39, "Model said": 0.61}]}, "calibration": {"buckets": []}})
    monkeypatch.setattr(B, "list_bets", lambda **kw: [])
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "49_Model_Performance.py"), default_timeout=30)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Recommendations by tag" in m.value for m in at.markdown)


def test_closing_line_drops_alt_lines_and_counts_no_move_separately():
    import investor as I
    bets = [{"slate_date": "2026-11-05", "entry_odds": -110, "close_odds": -120},    # beat
            {"slate_date": "2026-11-05", "entry_odds": -110, "close_odds": -110},    # no move
            {"slate_date": "2026-11-05", "entry_odds": -791, "close_odds": -123},    # alt line: dropped
            {"slate_date": "2026-07-28", "entry_odds": -110, "close_odds": -100}]    # before the era
    c = I.closing_line(bets)
    assert c["n"] == 2 and c["moved"] == 1 and c["beat"] == 1.0 and c["dropped"] == 1 and c["unchanged"] == 1
    assert I.closing_line(bets, since=None)["moved"] == 2


def test_desk_scans_props_model_rows_only_when_present():
    import analyst as A
    plays = [{"Model": "player-props", "Side": "Under", "ModelProb": 0.6, "Player": "A", "Market": "Points"},
             {"Model": "recent-games", "Side": "Under", "ModelProb": 0.8, "Player": "B", "Market": "Points"}]
    seen = []
    orig = dict(A.DETECTORS)
    try:
        A.DETECTORS.clear()
        A.DETECTORS["probe"] = lambda p, ctx: seen.append(p["Player"]) or None
        A.scan(plays, "NBA", "2026-11-06")
    finally:
        A.DETECTORS.clear()
        A.DETECTORS.update(orig)
    assert seen == ["A"]
