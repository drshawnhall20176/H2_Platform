"""Today's best (Nov 6): the day's top-tagged picks across sports for Home."""
import props_engine as PE


def _play(player, use, prob, cushion=0.2, **kw):
    p = {"Player": player, "Market": "Points", "Side": "Under", "Line": 20.5, "Game": "A @ B", "RealPrice": -120,
         "RealPriceBook": "draftkings", "ModelProb": prob, "Cushion": cushion, "Use": use}
    p.update(kw)
    return p


def test_props_rows_keep_playable_and_rank_locks_first():
    import todays_best as TB
    rows = TB.props_rows("NBA", [_play("A", PE.USE_SINGLE, 0.57, 0.05), _play("B", PE.USE_PARLAY, 0.62, 0.20),
                                 _play("C", PE.USE_PASS, 0.70, 0.30), _play("D", None, 0.83, 0.10),
                                 _play("E", PE.USE_BOTH, 0.61, 0.05)])
    assert [r["pick"].split()[0] for r in rows] == ["B", "E", "A"]
    assert rows[0]["lock"] and not rows[1]["lock"]


def test_game_rows_use_the_pages_tags(monkeypatch):
    import model_store as MS
    import todays_best as TB
    recs = {"EUROLEAGUE": [{"kickoff": "2026-11-06T19:00:00Z", "home": "Real Madrid", "away": "Monaco", "home_spread": -5.5,
                            "edge": 7.0, "use": PE.USE_SINGLE, "lock": False, "cover_est": 0.56},
                           {"kickoff": "2026-11-07T19:00:00Z", "home": "X", "away": "Y", "use": PE.USE_SINGLE}],
            "NBL": [{"kickoff": "2026-11-06T08:00:00Z", "home": "Sydney Kings", "away": "Perth Wildcats", "ml_pick": "away"}],
            "TENNIS": [{"kickoff": "2026-11-06T15:00:00Z", "home": "P1", "away": "P2", "model_p": 0.52, "source": "espn",
                        "n_home": 40, "n_away": 40}]}
    monkeypatch.setattr(MS, "load_game_picks", lambda lg, ungraded=False, db_path=None: recs.get(lg, []))
    rows = TB.game_rows("2026-11-06", leagues=["EUROLEAGUE", "NBL"])
    picks = {r["pick"] for r in rows}
    assert picks == {"Real Madrid -5.5", "Perth Wildcats moneyline"}
    assert all(r["sport"] == "INTL" for r in rows)


def test_home_panel_renders(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    import todays_best as TB
    monkeypatch.setattr(TB, "collect", lambda d, sp: {"rows": [{"sport": "NBA", "pick": "A Points Under 20.5", "game": "A @ B",
                                                                "price": -120, "chance": 0.62, "use": PE.USE_PARLAY,
                                                                "lock": True, "page": "Best Bets", "time": "7:00 PM"}],
                                                      "props": {"NBA": "2026-11-06T15:00:00+00:00"}})
    at = AppTest.from_file(str(Path(__file__).parent / "Home.py"), default_timeout=30)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Today's best" in (m.value or "") for m in at.markdown)
    # Nov 6: follows the picked sport -- an NBA pick doesn't show while NHL is picked, and does under All sports
    at.session_state["sport"] = "NHL"
    at.run()
    assert not at.dataframe or "A Points Under 20.5" not in at.dataframe[0].value.to_string()
    at.radio(key="home_best_scope").set_value("All sports").run()
    assert "A Points Under 20.5" in at.dataframe[0].value.to_string()


def test_warm_slates_builds_in_season_boards(monkeypatch):
    """Nov 6: the hourly job builds the Best Bets boards so Today's best fills without anyone opening a page."""
    import best_bets_data as BBD
    import sports
    import todays_best as TB
    import warm_slates as W
    built = []
    monkeypatch.setattr(sports, "in_season", lambda k, day=None: k in ("NBA", "NHL"))
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda k, d, b: built.append(k) or ([], [], []))
    monkeypatch.setattr(TB, "load_props", lambda k, d: {"rows": []})
    W.boards("2026-11-06")
    assert built == ["NBA", "NHL"]


def test_winner_rows_and_record(monkeypatch):
    import model_store as MS
    import todays_best as TB
    recs = {"NBA": [{"kickoff": "2026-11-07T00:30:00Z", "home": "Boston Celtics", "away": "Milwaukee Bucks", "model_p": 0.3,
                     "fair_home": 0.4, "best_home": 150, "best_away": -160, "best_away_book": "DraftKings"}],
            "NCAAF": [{"kickoff": "2026-11-06T23:00:00Z", "home": "Ball State", "away": "Buffalo", "model_margin": 15.5},
                      {"kickoff": "2026-10-30T23:00:00Z", "home": "A", "away": "B", "model_margin": -3,
                       "final_home": 10, "final_away": 20}]}
    monkeypatch.setattr(MS, "load_game_picks", lambda lg, ungraded=False, db_path=None:
                        [r for r in recs.get(lg, []) if not ungraded or r.get("final_home") is None])
    rows = TB.winner_rows("2026-11-06", leagues=["NBA", "NCAAF"])
    by = {r["sport"]: r for r in rows}
    assert by["NBA"]["winner"] == "Milwaukee Bucks" and abs(by["NBA"]["chance"] - 0.7) < 1e-9
    assert abs(by["NBA"]["book"] - 0.6) < 1e-9 and abs(by["NBA"]["value"] - (0.7 * (1 + 100 / 160) - 1)) < 1e-9
    assert by["NCAAF"]["winner"] == "Ball State" and 0.83 < by["NCAAF"]["chance"] < 0.85
    rec = TB.winner_record(leagues=["NCAAF"])
    assert rec["NCAAF"]["n"] == 1 and rec["NCAAF"]["won"] == 1


def test_best_line_picks_value_across_markets():
    """Nov 6: a -10000 favorite is never the best bet; a mispriced total or spread is."""
    import todays_best as TB
    p = {"home": "Oklahoma", "away": "MVSU", "best_home": -10000, "best_away": 7000, "model_p": 0.967,
         "home_spread": -34.5, "model_margin": 14.9, "edge": -19.6, "cover_est": 0.508, "use": "⛔ Pass",
         "spread_price": -105, "line_total": 155.5, "model_total": 154.5, "over_price": -110, "under_price": -110}
    assert TB.best_line(p, "NCAAMB", 0.967)["best"] is None    # +7000 dog left out; +34.5 at 50.8% isn't worth -105
    b = TB.best_line(dict(p, spread_price=110), "NCAAMB", 0.967)
    assert b["best"] == "MVSU +34.5" and abs(b["best_chance"] - 0.508) < 1e-9 and b["best_value"] > 0
    q = dict(p, cover_est=None, edge=None, model_margin=30.0, best_home=-500, best_away=350, model_total=180.0)
    b2 = TB.best_line(q, "NCAAMB", 0.9)
    assert b2["best"].startswith("Over") and not b2["best_tested"] and b2["best_chance"] == 0.60
    r = dict(p, best_home=-2000, best_away=1000, home_spread=None, line_total=None)
    assert TB.best_line(r, "NCAAMB", 0.9)["best"] is None


def test_best_line_survives_malformed_prices():
    import todays_best as TB
    p = {"home": "A", "away": "B", "home_spread": -1.5, "model_margin": 2.0, "spread_price": -7.5,
         "line_total": 6.5, "model_total": 7.0, "over_price": None, "under_price": -7.5}
    b = TB.best_line(p, "NHL", 0.6)
    assert b["best"] is None or b["best_price"] == -110
