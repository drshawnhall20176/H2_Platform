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
    # Nov 17: one sentence instead of Model leans / Model's winner / Book line / Model line
    assert a["Game"] == "A1 @ H1" and a["The model says"] == "No bet — model: H1 by 6.1 · book: H1 by 5 → leans H1 -5"
    assert "Model's winner" not in a and "Book line" not in a and "Model leans" not in a
    assert a["_lean"] == "H1 -5" and a["Gap (pts)"] == 1.1 and a["Form (30 days)"] == "❄️ Cold · 10–12 (45%)"
    assert b["_lean"] == "A2 +36.5" and b["Gap (pts)"] == 19.1 and b["Form (30 days)"] == "🔥 Hot · 15–9 (62%)"
    assert a["Pick"] == "" and b["Pick"] == ""
    shown = GP.public(rows)
    assert "Pick" not in shown[0] and not any(k.startswith("_") for k in shown[0])     # no empty Pick column


def test_a_tested_rule_still_shows_as_a_pick():
    rows = GP.preview_rows("EUROLEAGUE", [_g(1, 7.0)], {}, lambda p: "2:00 PM",
                           lambda p: {"use": PE.USE_SINGLE, "lock": False})
    assert rows[0]["Pick"] == PE.USE_SINGLE and "Pick" in GP.public(rows)[0]
    assert GP.preview_rows("NBA", [{"home": "H", "away": "A"}], {}, lambda p: "")[0]["Form (30 days)"] == "—"


def test_spotlight_lists_only_games_with_a_tested_reason():
    """Nov 17: a 'hot' lean on a Pass game is no longer spotlighted (Hofstra / Rutgers); a playable tag or a college
    basketball spread moving toward the model's side is."""
    moving = dict(_g(2, 4.0), line=5.0, open_line=3.0)            # book home margin 3 -> 5, model 9: our way
    rows = GP.preview_rows("NCAAMB", [_g(1, 1.1), moving, _g(3, 9.7), _g(4, -19.1)], RECS, lambda p: "",
                           tag=lambda p: {"use": PE.USE_SINGLE} if p["home"] == "H3" else {})
    assert [r["Game"] for r in GP.spotlight(rows)] == ["A3 @ H3", "A2 @ H2"]   # playable first, then moving our way
    assert rows[1]["Spread move"].startswith("📈 our way") and rows[2]["The model says"].startswith("model: H3")
    assert GP.spotlight([]) == []


def test_game_lab_shows_previews_on_every_build_with_the_owners_columns(monkeypatch):
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
    games = [d.value for d in at.dataframe if "The model says" in d.value.columns][0]
    assert "Use" not in games.columns and "Why" not in games.columns and "Pick" not in games.columns
    assert [x.split("leans ")[-1] for x in games["The model says"]] == ["H1 -10.5", "A2 +36.5"]
    assert any("Previews, not picks" in i.value for i in at.info)
    assert not any("says Pass" in i.value for i in at.info)

    at = AppTest.from_file("views/45_NCAAMB_Game_Lab.py", default_timeout=120)
    at.secrets["AUDIENCE"] = "owner"
    at.run()
    assert not at.exception
    owner = [d.value for d in at.dataframe if "The model says" in d.value.columns][0]
    # the same previews are the standard on the owner build, with the Use column and the owner's extra columns
    assert list(owner.columns[:5]) == ["Tip (ET)", "Game", "Use", "The model says", "Gap (pts)"]
    assert {"Long backtest", "Tracking pick", "Why"} <= set(owner.columns) and "Pick" not in owner.columns
    assert list(owner["Use"]) == [PE.USE_PASS, PE.USE_PASS] and all(x.startswith("No bet — ") for x in owner["The model says"])
    assert any("Previews, not picks" in i.value for i in at.info)
    assert any(r.label.startswith("☑️ Tick games") for r in at.radio)          # the owner still ticks rows to log


def test_owner_rows_carry_use_and_extras_and_keep_their_place_for_logging():
    rows = GP.preview_rows("NCAAMB", [_g(1, 1.1), _g(2, -19.1)], RECS, lambda p: "", use=lambda p: PE.USE_PASS,
                           extras=lambda p: {"Long backtest": "51%"})
    assert [r["_i"] for r in rows] == [0, 1] and rows[0]["Use"] == PE.USE_PASS and "Pick" not in rows[0]
    by_gap = sorted(rows, key=lambda r: -r["Gap (pts)"])
    assert [r["_i"] for r in by_gap] == [1, 0]                                 # a ticked row maps back to its game
    assert list(GP.public(rows)[0])[-1] == "Long backtest" and "_i" not in GP.public(rows)[0]


def test_sim_row_for_a_league_with_no_stored_lines():
    r = GP.sim_row("KC @ BUF", "Sun 4:25 PM", "BUF", "KC", {"home_win_prob": 0.58, "proj_spread": 2.4, "proj_total": 47.6,
                                                             "proj_home_score": 25.0, "proj_away_score": 22.6})
    assert (r["Projected score"], r["Model's winner"], r["Model spread"], r["Model total"]) == ("23–25", "BUF 58%", "BUF -2.4", 47.6)
    away = GP.sim_row("KC @ BUF", "", "BUF", "KC", {"home_win_prob": 0.44, "proj_spread": -1.5, "proj_total": 44.0,
                                                    "proj_home_score": 21.2, "proj_away_score": 22.8})
    assert away["Model's winner"] == "KC 56%" and away["Model spread"] == "KC -1.5" and away["_close"] < r["_close"]
    assert GP.sim_row("A @ B", "", "B", "A", None)["Projected score"] == "—"


def test_ncaaf_game_lab_lists_previews_with_form(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from streamlit.testing.v1 import AppTest
    import model_store as MS
    import streamlit as st
    st.cache_data.clear()
    now = datetime.now(timezone.utc)
    recs = [{"sport": "NCAAF", "game_id": str(i), "kickoff": (now + timedelta(hours=5)).isoformat(), "home": f"H{i}",
             "away": f"A{i}", "model_margin": mm, "line": line, "close_line": line, "edge": mm - line, "model_total": 55.0,
             "line_total": 52.5, "pick": None, "pick_label": lab, "result": None, "neutral": i == 2, "week": 12, "season": 2026}
            for i, mm, line, lab in ((1, 10.0, 3.0, "H1 -3"), (2, -4.0, -3.5, None))]
    monkeypatch.setattr(MS, "load_game_picks", lambda sport, ungraded=False, db_path=None: recs if sport == "NCAAF" else [])
    at = AppTest.from_file("views/32_NCAAF_Game_Lab.py", default_timeout=180)
    at.session_state["sport"] = "NCAAF"
    at.run()
    tables = [d.value for d in at.dataframe if "Form (30 days)" in d.value.columns]
    assert tables, [str(e.value)[:200] for e in at.exception]
    t = tables[0]
    assert list(t.columns[:5]) == ["Kickoff (ET)", "Game", "Tracking pick", "The model says", "Gap (pts)"]
    assert [x.split("leans ")[-1] for x in t["The model says"]] == ["H1 -3", "A2 -3.5"] and list(t["Gap (pts)"]) == [7.0, 0.5]
    assert list(t["Game"]) == ["A1 @ H1", "A2 @ H2 (neutral)"] and list(t["Tracking pick"]) == ["H1 -3", "—"]
