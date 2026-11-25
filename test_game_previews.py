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
    assert a["Game"] == "A1 @ H1" and (a["Model has"], a["Market has"], a[GP.SIDE]) == ("H1 by 6.1", "H1 by 5", "No bet · H1 -5")
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
    assert rows[1]["Spread move"].startswith("🟢 ▲") and rows[2]["Model has"].startswith("H3")
    assert GP.spotlight([]) == []


def test_game_lab_is_one_table_with_the_previews_context_on_the_right(monkeypatch):
    # Nov 25 (owner: "unnecessary redundancy in the game tables ... it could be consolidated"): the board is the one
    # games table; the previews' context columns ride on its right; the separate previews / finals tables are gone
    from datetime import datetime, timedelta, timezone
    from streamlit.testing.v1 import AppTest
    import game_lines_table as GLT
    import model_store as MS
    now = datetime.now(timezone.utc)
    picks = [dict(_g(i, e, hs), sport="NCAAMB", game_id=str(i), kickoff=(now + timedelta(hours=2)).isoformat(),
                  line=-hs, fair_home=0.58, cover_est=0.508, cover_n=5184, use=PE.USE_PASS, lock=False, result=None,
                  final_home=None, final_away=None, pick=None, total_pick=None, ml_pick=None)
             for i, e, hs in ((1, 1.1, -10.5), (2, -19.1, -36.5))]
    monkeypatch.setattr(MS, "load_game_picks", lambda league, ungraded=False, db_path=None: picks if league == "NCAAMB" else [])
    board = [{"sport": "NCAAMB", "league": "NCAAMB", "game": f"A{i} @ H{i}", "time": "", "best": f"H{i} -5",
              "winner": f"H{i}", "chance": 0.6, "_full": p} for i, p in ((1, picks[0]), (2, picks[1]))]
    monkeypatch.setattr(GLT, "_rows", lambda league, day, past: board)
    for aud in ("commercial", "owner"):
        at = AppTest.from_file("views/45_NCAAMB_Game_Lab.py", default_timeout=120)
        at.secrets["AUDIENCE"] = aud
        at.run()
        assert not at.exception
        assert not [d for d in at.dataframe if GP.SIDE in d.value.columns]          # no separate previews table
        assert not any("Started or final" in m.value for m in at.markdown)
        assert any("Previews, not picks" in i.value for i in at.info)
        assert any(e.label.startswith("☑️ Log any side") for e in at.expander) == (aud == "owner")


def test_board_keep_and_context_columns():
    import hoops_games_page as HG
    assert HG.board_keep({"A1 @ H1", "A2 @ H2"}, {"A1 @ H1", "A2 @ H2"}) is None        # filters not narrowing
    keep = HG.board_keep({"A1 @ H1"}, {"A1 @ H1", "A2 @ H2"})
    assert keep({"game": "A1 @ H1"}) and not keep({"game": "A2 @ H2"})
    pv = GP.preview_rows("NCAAMB", [_g(1, 1.1)], RECS, lambda p: "", extras=lambda p: {"Why": "w", "Long backtest": "51%"})
    extra = HG.context_cols(pv)({"game": "A1 @ H1"})
    assert extra["Why"] == "w" and extra["Long backtest"] == "51%" and "Form (30 days)" in extra and GP.TOTAL in extra
    assert HG.context_cols(pv)({"game": "nope"}) == {}
    import game_lines_table as GLT
    df = GLT.frame([{"sport": "NCAAMB", "game": "A1 @ H1", "best": "x"}], False, extra_cols=lambda r: {"Why": "w"})
    assert list(df.columns)[-1] == "Why"


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
    assert list(t.columns[:8]) == ["Kickoff (ET)", "Game", GP.BET, GP.AGREE, GP.blow_col("NCAAF"), "Gap (pts)",
                                   "Tracking pick", "Model has"]
    assert [x.split("· ")[-1] for x in t[GP.SIDE]] == ["H1 -3", "A2 -3.5"] and list(t["Gap (pts)"]) == [7.0, 0.5]
    assert list(t["Game"]) == ["A1 @ H1", "A2 @ H2 (neutral)"] and list(t["Tracking pick"]) == ["H1 -3", "—"]


def test_blowout_risk_reads_the_market_spread():
    """Nov 23 (owner): a blowout-risk column, left of Use. From the market's spread (the model's mismatch margins run
    small): a 30-point spread is high, a pick'em low."""
    big = {"home": "H", "away": "A", "home_spread": -30.0, "model_margin": 18.0, "line_total": 140.0, "game_id": "b"}
    even = dict(big, home_spread=-1.0, model_margin=1.0, game_id="e")
    assert GP.blowout("NCAAMB", big).startswith("🟥") and GP.blowout("NCAAMB", even).startswith("🟩")
    assert GP.blowout("NCAAMB", {"home": "H", "away": "A"}) == "—"
    assert GP.blow_col("NCAAMB") == "Blowout risk (15+ pts)" and GP.blow_col("NHL") == "Blowout risk (3+ goals)"


def test_a_use_column_that_says_no_edge_everywhere_is_dropped_for_a_note():
    """Nov 23 (owner): a Use column that's ⚪ No edge on every row tells nothing per game."""
    import pandas as pd
    flat = pd.DataFrame([{"Game": "a", "Use": "⚪ No edge"}, {"Game": "b", "Use": "⚪ No edge"}])
    df, note = GP.collapse_use(flat)
    assert "Use" not in df.columns and "comes back" in note
    mixed = pd.DataFrame([{"Game": "a", "Use": "⚪ No edge"}, {"Game": "b", "Use": "🎯 Single only"}])
    df, note = GP.collapse_use(mixed)
    assert "Use" in df.columns and note is None


def test_prop_agreement_reads_the_price_lean_against_the_model():
    import game_previews as GP
    assert GP.prop_agreement(0.6, -140) == "✅ Agree"
    assert GP.prop_agreement(0.6, 120).startswith("⚠️")
    assert GP.prop_agreement(0.6, -110).startswith("➖")
    assert GP.prop_agreement(None, -110) == "—"


def test_game_blowouts_matches_prop_games_to_saved_game_picks(monkeypatch):
    import game_previews as GP
    import model_store as MS
    monkeypatch.setattr(MS, "load_game_picks", lambda lg, ungraded=False: [
        {"home": "Boston Celtics", "away": "Detroit Pistons", "home_spread": -14.5, "line_total": 225, "game_id": "x"}])
    out = GP.game_blowouts("NBA", ["Detroit Pistons @ Boston Celtics", "Pistons @ Celtics", "Kings @ Suns"])
    assert out["Kings @ Suns"] == "—"
    assert out["Detroit Pistons @ Boston Celtics"] != "—" and out["Pistons @ Celtics"] != "—"


def test_a_weekly_board_sorts_on_the_real_kickoff():
    import game_lines_table as GLT
    sun = {"time": "1:00 PM", "_full": {"kickoff": "2026-11-29T18:00:00+00:00"}}
    wed = {"time": "8:00 PM", "_full": {"kickoff": "2026-11-26T01:00:00+00:00"}}
    rows = sorted([sun, wed], key=lambda r: (GLT._when(r) is None, str(GLT._when(r) or "")))
    assert rows == [wed, sun]


def test_games_pages_open_on_cards_with_a_game_card_per_game(monkeypatch):
    # Nov 25 (members: "keep the card theme throughout as the default"): the Games page starts on cards
    from datetime import datetime, timedelta, timezone
    from streamlit.testing.v1 import AppTest
    import game_lines_table as GLT
    import model_store as MS
    now = datetime.now(timezone.utc)
    picks = [dict(_g(1, 1.1, -10.5), sport="NCAAMB", game_id="1", kickoff=(now + timedelta(hours=2)).isoformat(),
                  line=10.5, use=PE.USE_PASS, lock=False, result=None, final_home=None, final_away=None, pick=None)]
    monkeypatch.setattr(MS, "load_game_picks", lambda league, ungraded=False, db_path=None: picks if league == "NCAAMB" else [])
    board = [{"sport": "NCAAMB", "league": "NCAAMB", "game": "A1 @ H1", "time": "7:00 PM", "best": "H1 -5",
              "winner": "H1", "chance": 0.6, "_full": picks[0]}]
    monkeypatch.setattr(GLT, "_rows", lambda league, day, past: board)
    at = AppTest.from_file("views/45_NCAAMB_Game_Lab.py", default_timeout=120)
    at.secrets["AUDIENCE"] = "owner"
    at.run()
    assert not at.exception
    assert at.segmented_control(key="view_games_NCAAMB").value == "Cards"
    assert any(b.label == "Game card →" for b in at.button)
    assert not [d for d in at.dataframe if "Line pick (model favors)" in d.value.columns]   # the table is one tap away
    at.segmented_control(key="view_games_NCAAMB").set_value("Table").run()
    assert [d for d in at.dataframe if "Line pick (model favors)" in d.value.columns]
    assert at.session_state["h2_view_pref"] == "Table"                                    # follows to every page


def test_game_card_player_list_and_prop_chips():
    import today_visual as TV
    rows = [{"player": "Jalen Brunson", "team": "NYK", "market": "Points", "side": "Over", "line": 27.5, "chance": 0.58,
             "game": "Knicks @ Celtics"},
            {"player": "Jalen Brunson", "team": "NYK", "market": "Assists", "side": "Over", "line": 6.5, "chance": 0.61,
             "game": "Knicks @ Celtics"},
            {"player": "Jaylen Brown", "team": "BOS", "market": "Points", "side": "Under", "line": 25.5, "chance": 0.55,
             "game": "Knicks @ Celtics"},
            {"player": "Other Guy", "team": "MIA", "market": "Points", "side": "Over", "line": 10.5, "game": "Heat @ Magic"}]
    w = {"game": "Knicks @ Celtics", "_full": {"home": "Celtics", "away": "Knicks"}}
    inside = TV.players_in_game(rows, w)
    assert {r["player"] for r in inside} == {"Jalen Brunson", "Jaylen Brown"}
    g = TV.team_groups(inside)
    assert set(g) == {"NYK", "BOS"} and g["NYK"][0]["market"] == "Points"             # his main stat leads
    tagged = dict(rows[0], use="🎯 Single only", chance=0.52)                            # a playable pick beats a
    assert TV.team_groups([tagged, rows[1]])["NYK"][0]["market"] == "Points"            # higher-chance read
    assert TV.market_label(rows[0]) == "Points · Over 27.5"
