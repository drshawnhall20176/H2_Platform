"""Nov 12: college game pages get a player-props section from the saved Best Bets board."""
import props_section as PS

ROWS = [{"sport": "NCAAMB", "kind": "Prop", "time": "7:00 PM", "pick": "A Points Over 15.5", "game": "X @ Y",
         "price": 120, "book": "draftkings", "chance": 0.62, "use": "🎯 Single only", "player": "A",
         "market": "Points", "side": "Over", "line": 15.5},
        {"sport": "NCAAMB", "kind": "Prop", "time": "7:00 PM", "pick": "B Rebounds Over 6.5", "game": "X @ Y",
         "price": None, "book": "underdog", "chance": 0.6, "use": "🎯 Single only", "player": "B",
         "market": "Rebounds", "side": "Over", "line": 6.5}]


def test_judged_gives_every_prop_a_coach_verdict():
    out = PS.judged(ROWS, "NCAAMB", bets=[], tag_records_for=lambda sp: {})
    assert len(out) == 2
    assert {o["pick"] for o in out} == {"A Points Over 15.5", "B Rebounds Over 6.5"}
    assert [o for o in out if o["pick"].startswith("B")][0]["verdict"] == "⚪ No sportsbook price"
    assert [o for o in out if o["pick"].startswith("A")][0]["verdict"] in ("🟢 Good bet", "🟡 Maybe", "🔴 Skip", "⚪ Unchecked")


def test_ncaamb_game_lab_shows_props(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    import todays_best as TB
    import model_store as MS
    import betlog as B
    monkeypatch.setattr(TB, "load_props", lambda sp, d: {"at": "2026-11-12T21:00:00+00:00", "rows": ROWS})
    monkeypatch.setattr(MS, "load_game_picks", lambda *a, **k: [])
    monkeypatch.setattr(B, "list_bets", lambda *a, **k: [])
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "45_NCAAMB_Game_Lab.py"), default_timeout=60)
    at.session_state["sport"] = "NCAAMB"
    at.run()
    assert not at.exception, at.exception
    assert any("Player props" in m.value for m in at.markdown)
    df = at.dataframe[-1].value
    assert "A Points Over 15.5" in set(df["Pick"])
