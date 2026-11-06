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
