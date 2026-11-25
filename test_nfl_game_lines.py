"""Nov 16: the NFL joins the ratings pipeline behind every other Game Lab (leans, gaps, form, simulation)."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import game_sim as GS
import intl_hoops as I
import intl_picks as IP
import todays_best as TB


def test_nfl_is_configured_like_the_other_pro_leagues_and_has_no_picks():
    cfg = I.LEAGUES["NFL"]
    assert cfg["odds_key"] == "americanfootball_nfl" and cfg["decay"] and cfg["sd"] == 13.0 and cfg["min_decay_games"] == 150
    assert "football/nfl/scoreboard" in I.ESPN_LEAGUE_URL["NFL"] and I.HFA_PRIOR["NFL"][0] == 1.7
    assert IP.HOOPS_RULES["NFL"] == {"spread": None, "total": None, "ml": None}          # no edge in testing -> no picks
    assert "48%" in IP.HOOPS_EVIDENCE["NFL"] and "434 games" in IP.HOOPS_EVIDENCE["NFL"]
    assert TB.MARGIN_SD["NFL"] == 13.0 and TB.TOTAL_SD["NFL"] == 13.5 and IP.TOTAL_SD["NFL"] == 13.5
    assert "NFL" in TB.WINNER_LEAGUES and "NFL" in TB.GAME_LEAGUES and IP.BET_SPORT["NFL"] == "NFL"
    assert I.season_of("NFL", "2027-01-17") == "2026" and I.season_of("NFL", "2026-09-10") == "2026"
    root = Path(__file__).parent
    assert "NBA,NHL,NFL" in (root / ".github" / "workflows" / "capture-intl.yml").read_text()   # the capture job runs it
    assert 'NBL,NCAAMB,NBA,NHL,NFL"' in (root / "intl_picks.py").read_text()
    assert (root / "research" / "nfl_ratings_backtest.py").exists()                      # the evidence behind the numbers


def test_nfl_results_parse_and_a_priced_game_gets_a_projection_but_never_a_pick():
    data = {"events": [{"season": {"type": 2}, "competitions": [{"id": 9, "date": "2026-11-15T18:00Z",
            "status": {"type": {"completed": True}}, "competitors": [
                {"homeAway": "home", "team": {"displayName": "Baltimore Ravens"}, "score": "27"},
                {"homeAway": "away", "team": {"displayName": "Los Angeles Chargers"}, "score": "20"}]}]}]}
    g = I.espn_range("NFL", date(2026, 11, 15), date(2026, 11, 15), fetch=lambda url, params=None: data)
    assert len(g) == 1 and g[0]["id"] == "nfl-9" and g[0]["home_points"] == 27
    r = {"mu": 22.0, "hfa": 1.7, "off": {"Baltimore Ravens": 4.0, "Los Angeles Chargers": 1.0},
         "def": {"Baltimore Ravens": 2.0, "Los Angeles Chargers": 0.0}}
    now = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
    ev = {"id": "e1", "commence_time": (now + timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ"),
          "home_team": "Baltimore Ravens", "away_team": "Los Angeles Chargers", "bookmakers": [{"key": "draftkings", "markets": [
              {"key": "spreads", "outcomes": [{"name": "Baltimore Ravens", "point": -3.5, "price": -110},
                                              {"name": "Los Angeles Chargers", "point": 3.5, "price": -110}]},
              {"key": "totals", "outcomes": [{"name": "Over", "point": 44.5, "price": -110}, {"name": "Under", "point": 44.5, "price": -110}]},
              {"key": "h2h", "outcomes": [{"name": "Baltimore Ravens", "price": -180}, {"name": "Los Angeles Chargers", "price": 150}]}]}]}
    recs = IP.hoops_build("NFL", r, [ev], now)
    assert len(recs) == 1
    p = recs[0]
    assert p["sport"] == "NFL" and p["home_spread"] == -3.5 and p["line_total"] == 44.5
    assert p["model_margin"] is not None and p["model_total"] is not None and 0.5 < p["model_p"] < 1
    assert p["pick"] is None and p["total_pick"] is None and p["ml_pick"] is None      # previews only
    assert IP.hoops_use("NFL", p)["use"] == "⚪ No edge"


def test_football_simulation_uses_football_sized_spreads_and_thresholds():
    s = GS.simulate("NFL", 3.0, 45.0, key="n1")
    assert s["family"] == "football" and s["overtime"] is None
    assert (s["proj_home_score"], s["proj_away_score"]) == (24.0, 21.0)
    lo, hi = s["margin_range"]
    assert -15.5 < lo < -12 and 18 < hi < 21.5                    # 3 +/- 1.28 x 13
    assert 0.56 < s["sim_home_win"] < 0.62 and GS.CLOSE["football"] == 3 and GS.BLOWOUT["football"] == 14
    assert GS.unit("NFL") == "points" and GS.range_text(-2.0, 31.4, "NFL") == "0–31"


def test_nfl_game_lab_uses_the_shared_layout_once_games_are_saved_and_the_old_page_until_then(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import model_store as MS
    import nfl_shared_cache as NSC
    import streamlit as st
    now = datetime.now(timezone.utc)
    # three days out: a weekly league lists the week from the picked date, not one day
    rec = {"sport": "NFL", "game_id": "n1", "kickoff": (now + timedelta(days=3)).isoformat(), "home": "Baltimore Ravens",
           "away": "Los Angeles Chargers", "model_margin": 5.5, "model_total": 46.0, "home_spread": -3.5, "line": 3.5,
           "edge": 2.0, "line_total": 44.5, "model_p": 0.66, "fair_home": 0.63, "cover_est": None, "use": "⚪ No edge",
           "lock": False, "result": None, "final_home": None, "final_away": None, "pick": None, "total_pick": None,
           "ml_pick": None}
    monkeypatch.setattr(NSC, "load_nfl_slate_cached", lambda d: ([], []))
    monkeypatch.setattr(MS, "load_results", lambda sport, since=None, db_path=None: [])
    st.cache_data.clear()
    monkeypatch.setattr(MS, "load_game_picks", lambda sport, ungraded=False, db_path=None: [rec] if sport == "NFL" else [])
    at = AppTest.from_file("views/34_NFL_Game_Lab.py", default_timeout=120)
    at.session_state["sport"] = "NFL"
    at.run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    import game_previews as GP
    # Nov 25: one games table (the board) -- the whole week for a weekly league
    slate = [d.value for d in at.dataframe if "Line pick (model favors)" in d.value.columns][0]
    assert list(slate["Game"]) == ["Los Angeles Chargers @ Baltimore Ravens"] and "Form (30 days)" in slate.columns
    m = {x.label: x.value for x in at.metric}
    assert m["Baltimore Ravens ML"] == "66.0%" and m["Projected spread"] == "Baltimore Ravens -5.5"
    assert "Decided by 3 or fewer" in m and "Decided by 14+ points" in m
    assert any(s.label == "Find a team" for s in at.selectbox)
    assert at.radio(key="hg_scope_NFL").value == "This week"
    assert any("Previews, not picks" in i.value for i in at.info)

    st.cache_data.clear()                                          # no saved NFL games yet: the page as it was
    monkeypatch.setattr(MS, "load_game_picks", lambda sport, ungraded=False, db_path=None: [])
    at = AppTest.from_file("views/34_NFL_Game_Lab.py", default_timeout=120)
    at.session_state["sport"] = "NFL"
    at.run()
    assert not at.exception
    assert any("No NFL games scheduled" in i.value for i in at.info) and any("Informational" in w.value for w in at.warning)
