"""Nov 16: the football labs' scoring context and Monte Carlo sections, for every other Game Lab."""
import game_sim as GS


def test_basketball_simulation_is_centred_on_the_models_projection_and_spreads_like_real_games():
    s = GS.simulate("NBA", 6.0, 226.0, key="g1")
    assert (s["proj_home_score"], s["proj_away_score"], s["proj_spread"], s["proj_total"]) == (116.0, 110.0, 6.0, 226.0)
    assert s["n_sims"] == 20000 and s["family"] == "basketball" and s["overtime"] is None
    lo, hi = s["margin_range"]
    assert -13.5 < lo < -10.5 and 22.5 < hi < 25.5                # 6 +/- 1.28 x 14 (the NBA margin spread, Nov 18)
    tlo, thi = s["total_range"]
    assert 201 < tlo < 205 and 247 < thi < 251                    # 226 +/- 1.28 x 18
    assert 0.64 < s["sim_home_win"] < 0.69                        # agrees with a normal margin: P(N(6, 14) > 0) = 66.6%
    assert 0 < s["close"] < s["sim_home_win"] and 0 < s["blowout"] < 0.5
    assert GS.simulate("NBA", 6.0, 226.0, key="g1") == s          # the same game never flickers
    assert GS.simulate("NBA", 6.0, 226.0, key="g2") != s


def test_hockey_simulation_counts_goals_and_sends_ties_to_overtime():
    s = GS.simulate("NHL", 0.4, 6.0, key="h1")
    assert s["family"] == "hockey" and (s["proj_home_score"], s["proj_away_score"]) == (3.2, 2.8)
    assert 0.15 < s["overtime"] < 0.30 and 0.50 < s["sim_home_win"] < 0.60
    assert s["close"] > s["overtime"] and s["home_range"][0] >= 0 and float(s["home_range"][1]).is_integer()


def test_no_projection_means_no_simulation():
    assert GS.simulate("NBA", None, 220) is None and GS.simulate("NBA", 3, None) is None and GS.simulate("NBA", 3, 0) is None


def test_scoring_context_matches_the_football_labs_four_numbers():
    games = [{"date": f"2026-11-{d:02d}", "home_team": "Boston Celtics", "away_team": "X", "home_points": hp, "away_points": ap}
             for d, hp, ap in ((1, 100, 90), (2, 110, 95), (3, 120, 100), (4, 100, 110), (5, 105, 99), (6, 130, 101))]
    games += [{"date": "2026-11-07", "home_team": "Y", "away_team": "Boston Celtics", "home_points": 108, "away_points": 112},
              {"date": "2026-11-08", "home_team": "Y", "away_team": "Z", "home_points": 99, "away_points": 98},
              {"date": "2026-11-09", "home_team": "Boston Celtics", "away_team": "Z", "home_points": None, "away_points": None}]
    c = GS.scoring_context(games, "Boston Celtics")
    assert c["games"] == 7 and c["recent_n"] == 5
    assert round(c["scored"]["recent_avg"], 1) == 113.4 and round(c["scored"]["season_avg"], 1) == 111.0
    assert round(c["allowed"]["recent_avg"], 1) == 103.6 and round(c["allowed"]["season_avg"], 1) == 100.4
    assert GS.scoring_context(games, "Nobody Here") is None and GS.scoring_context([], "Y") is None


def test_game_lab_shows_the_two_sections_for_a_chosen_game(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from streamlit.testing.v1 import AppTest
    import model_store as MS
    import props_engine as PE
    import streamlit as st
    st.cache_data.clear()
    now = datetime.now(timezone.utc)
    picks = [{"sport": "NBA", "game_id": "g1", "kickoff": (now + timedelta(hours=2)).isoformat(), "home": "Boston Celtics",
              "away": "New York Knicks", "model_margin": 6.0, "model_total": 226.0, "home_spread": -4.5, "line": 4.5,
              "edge": 1.5, "line_total": 224.5, "model_p": 0.68, "fair_home": 0.64, "cover_est": None, "use": PE.USE_PASS,
              "lock": False, "result": None, "final_home": None, "final_away": None, "pick": None, "total_pick": None,
              "ml_pick": None}]
    res = [{"date": f"2026-11-{d:02d}", "home_team": "Boston Celtics", "away_team": "New York Knicks", "home_points": 110 + d,
            "away_points": 104, "season": "2026"} for d in range(1, 7)]
    monkeypatch.setattr(MS, "load_game_picks", lambda league, ungraded=False, db_path=None: picks if league == "NBA" else [])
    monkeypatch.setattr(MS, "load_results", lambda sport, since=None, db_path=None: res if sport == "NBA" else [])
    at = AppTest.from_file("views/46_NBA_Game_Lab.py", default_timeout=120)
    at.session_state["sport"] = "NBA"
    at.run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    m = {x.label: x.value for x in at.metric}
    assert m["New York Knicks ML"] == "32.0%" and m["Boston Celtics ML"] == "68.0%"       # the model's own win chance
    assert m["Projected spread"] == "Boston Celtics -6.0" and m["Projected total"] == "226.0"
    assert "Total likely range" in m and "Decided by 15+ points" in m and "Decided by 5 or fewer" in m
    assert [x.value for x in at.metric if x.label == "Recent avg scored"] == ["104.0", "114.0"]   # away, then home
    assert any(s.label == "Game to simulate" for s in at.selectbox)


def test_hockey_finishes_look_like_real_nhl_games():
    """Nov 18 (research/nhl_finish.py, 1,612 games): 24% go to overtime and 3-goal finishes are common (empty nets)."""
    s = GS.simulate("NHL", 0.0, 6.0, key="even", n=100000)
    assert 0.21 < s["overtime"] < 0.26
    assert 0.36 < s["blowout"] < 0.44 and 0.38 < s["close"] < 0.46
