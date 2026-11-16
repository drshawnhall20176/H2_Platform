"""Nov 16: the customer's Game Lab -- previews with each lean's recent form, not a table of Pass."""
import game_previews as GP
import props_engine as PE


def _g(i, edge, hs=-5.0, total=150.0, mp=0.6):
    return {"home": f"H{i}", "away": f"A{i}", "model_margin": -hs + edge, "home_spread": hs, "edge": edge,
            "model_total": total, "line_total": 148.5, "model_p": mp}


RECS = {("Spread", 0): (10, 22), ("Spread", 1): (12, 23), ("Spread", 2): (15, 24)}


def test_form_words():
    assert GP.form_of(15, 24) == GP.HOT and GP.form_of(12, 23) == GP.EVEN and GP.form_of(10, 22) == GP.COLD
    assert GP.form_of(5, 5) == GP.NEW and GP.form_of(11, 20) == GP.HOT and GP.form_of(10, 21) == GP.EVEN
    assert GP.form_text(15, 24) == "🔥 Hot · 15–9 (62%)" and GP.form_text(0, 0) == "🆕 New · no graded games yet"
    assert GP.form_text(3, 5) == "🆕 New · 3–2 (60%)"                           # a hot-looking 3–2 is still too few


def test_preview_rows_describe_the_game_without_calling_it_a_pick():
    rows = GP.preview_rows("NCAAMB", [_g(1, 1.1, mp=0.72), _g(2, -19.1, hs=-36.5, mp=0.98)], RECS, lambda p: "7:00 PM",
                           lambda p: {"use": PE.USE_PASS})
    a, b = rows
    assert a["Game"] == "A1 @ H1" and a["Book line"] == "H1 -5" and a["Model line"] == "H1 -6.1"
    assert a["Projected score"] == "72–78" and a["Model's winner"] == "H1 72%"
    assert a["Model leans"] == "H1 -5" and a["Gap (pts)"] == 1.1 and a["Form (30 days)"] == "❄️ Cold · 10–12 (45%)"
    assert b["Model leans"] == "A2 +36.5" and b["Gap (pts)"] == 19.1 and b["Form (30 days)"] == "🔥 Hot · 15–9 (62%)"
    assert a["Pick"] == "" and b["Pick"] == ""
    shown = GP.public(rows)
    assert "Pick" not in shown[0] and not any(k.startswith("_") for k in shown[0])     # no empty Pick column


def test_a_tested_rule_still_shows_as_a_pick():
    rows = GP.preview_rows("EUROLEAGUE", [_g(1, 7.0)], {}, lambda p: "2:00 PM",
                           lambda p: {"use": PE.USE_SINGLE, "lock": False})
    assert rows[0]["Pick"] == PE.USE_SINGLE and "Pick" in GP.public(rows)[0]
    assert GP.preview_rows("NBA", [{"home": "H", "away": "A"}], {}, lambda p: "")[0]["Form (30 days)"] == "—"


def test_spotlight_prefers_hot_leans_and_never_lists_cold_ones():
    rows = GP.preview_rows("NCAAMB", [_g(1, 1.1), _g(2, 4.0), _g(3, 9.7), _g(4, -19.1), _g(5, 0.0)], RECS, lambda p: "")
    assert [r["Game"] for r in GP.spotlight(rows)] == ["A4 @ H4", "A3 @ H3", "A2 @ H2"]     # hot by gap, then even
    assert [r["Game"] for r in GP.spotlight(rows, k=5)] == ["A4 @ H4", "A3 @ H3", "A2 @ H2"]  # cold and no-gap left out
    assert GP.spotlight([]) == []


def test_game_lab_shows_previews_to_customers_and_the_pick_table_to_the_owner(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from streamlit.testing.v1 import AppTest
    import model_store as MS
    now = datetime.now(timezone.utc)
    picks = [dict(_g(i, e, hs), sport="NCAAMB", game_id=str(i), kickoff=(now + timedelta(hours=2)).isoformat(),
                  line=-hs, fair_home=0.58, cover_est=0.508, cover_n=5184, use=PE.USE_PASS, lock=False, result=None,
                  final_home=None, final_away=None, pick=None, total_pick=None, ml_pick=None)
             for i, e, hs in ((1, 1.1, -10.5), (2, -19.1, -36.5))]
    monkeypatch.setattr(MS, "load_game_picks", lambda league, ungraded=False, db_path=None: picks if league == "NCAAMB" else [])
    at = AppTest.from_file("views/45_NCAAMB_Game_Lab.py", default_timeout=120)
    at.secrets["AUDIENCE"] = "commercial"
    at.run()
    assert not at.exception
    games = [d.value for d in at.dataframe if "Model leans" in d.value.columns][0]
    assert "Use" not in games.columns and "Why" not in games.columns and "Pick" not in games.columns
    assert list(games["Model leans"]) == ["H1 -10.5", "A2 +36.5"]
    assert any("Previews, not picks" in i.value for i in at.info)
    assert not any("says Pass" in i.value for i in at.info)

    at = AppTest.from_file("views/45_NCAAMB_Game_Lab.py", default_timeout=120)
    at.secrets["AUDIENCE"] = "owner"
    at.run()
    assert not at.exception
    owner = [d.value for d in at.dataframe if "Why" in d.value.columns][0]
    assert "Use" in owner.columns and any("says Pass" in i.value for i in at.info)
