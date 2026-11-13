"""Nov 13: the Soccer Lab -- goals model, prices, flags, grading, bet settling, props, page."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

import soccer_data as D
import soccer_model as M
import soccer_picks as SP
import soccer_props as SPR

NOW = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)


def _sim(seed=1, weeks=50):
    rng = np.random.default_rng(seed)
    teams = [f"Team {c}" for c in "ABCDEFGHIJKLMNOPQRST"]
    att, dfn = np.exp(rng.normal(0, .3, 20)), np.exp(rng.normal(0, .25, 20))
    ms = []
    for wk in range(weeks):
        o = rng.permutation(20)
        for k in range(10):
            h, a = o[2 * k], o[2 * k + 1]
            ms.append({"home": teams[h], "away": teams[a], "hg": int(rng.poisson(1.35 * 1.25 * att[h] * dfn[a])),
                       "ag": int(rng.poisson(1.35 * att[a] * dfn[h])), "date": NOW - timedelta(days=7 * (weeks - wk))})
    return ms, teams, att


def test_fit_recovers_team_strength_and_home_edge():
    ms, teams, att = _sim()
    r = M.fit(ms, NOW)
    est = np.log([r["attack"][t] for t in teams])
    assert np.corrcoef(est, np.log(att))[0, 1] > 0.75
    assert 1.1 < r["home_adv"] < 1.4 and 1.1 < r["base"] < 1.6


def test_grid_markets_add_up():
    g = M.grid(1.6, 1.1)
    h, d, a = M.one_x_two(g)
    assert abs(h + d + a - 1) < 1e-9 and h > a
    o = M.total_outcome(g, 2.5)
    assert abs(o["win"] + o["loss"] - 1) < 1e-9 and o["push"] == 0
    q = M.total_outcome(g, 2.25)                           # half on 2, half on 2.5
    assert q["push"] > 0 and abs(q["win"] - o["win"]) < 1e-9
    ah = M.handicap_outcome(g, -0.5, "home")
    assert abs(ah["win"] - h) < 1e-9
    ah0 = M.handicap_outcome(g, 0.0, "home")               # draw no bet
    assert abs(ah0["push"] - d) < 1e-9


def _event(home="Arsenal", away="Chelsea"):
    def bk(key, h, d, a, tot=None, ah=None):
        ms = [{"key": "h2h", "outcomes": [{"name": home, "price": h}, {"name": "Draw", "price": d},
                                          {"name": away, "price": a}]}]
        if tot:
            ms.append({"key": "totals", "outcomes": [{"name": "Over", "price": tot[1], "point": tot[0]},
                                                     {"name": "Under", "price": tot[2], "point": tot[0]}]})
        if ah:
            ms.append({"key": "spreads", "outcomes": [{"name": home, "price": ah[1], "point": ah[0]},
                                                      {"name": away, "price": ah[2], "point": -ah[0]}]})
        return {"key": key, "markets": ms}
    return {"id": "ev1", "commence_time": (NOW + timedelta(days=1)).isoformat(), "home_team": home, "away_team": away,
            "bookmakers": [bk("pinnacle", -110, 270, 300, (2.5, -105, -105), (-0.5, -108, -102)),
                           bk("draftkings", -120, 280, 330, (2.5, -110, -110)),
                           bk("fanduel", -115, 260, 310, (2.5, 105, -125), (-0.5, -105, -115))]}


def test_prices_take_the_sharp_line_and_the_best_us_price():
    px = D.prices(_event(), "Arsenal", "Chelsea")
    assert px["sharp"] and abs(px["mkt_home"] + px["mkt_draw"] + px["mkt_away"] - 1) < 1e-3
    assert px["best_home"] == -115 and px["book_home"] == "fanduel"
    assert px["best_away"] == 330 and px["book_away"] == "draftkings"
    assert px["line_total"] == 2.5 and px["over_price"] == 105 and abs(px["mkt_over"] - 0.5) < 1e-3
    assert px["home_spread"] == -0.5 and px["spread_price_home"] == -105


def test_build_reads_the_model_and_flags_prices_above_the_sharp_line():
    ms, teams, _ = _sim()
    for m in ms:
        m["home"] = {"Team A": "Arsenal", "Team B": "Chelsea"}.get(m["home"], m["home"])
        m["away"] = {"Team A": "Arsenal", "Team B": "Chelsea"}.get(m["away"], m["away"])
    r = M.fit(ms, NOW)
    recs = SP.build("SOCCER_EPL", r, [_event()], NOW)
    assert len(recs) == 1
    x = recs[0]
    assert x["rated"] and abs(x["p_home"] + x["p_draw"] + x["p_away"] - 1) < 1e-3 and x["use"] == SP.PASS
    flagged = {(v["market"], v["side"]) for v in x["value"]}
    assert ("Moneyline", "away") in flagged                    # +330 vs a ~24% sharp chance
    assert ("Total", "over") in flagged                        # +105 vs 50%
    assert all(v["ev"] >= SP.VALUE_EDGE for v in x["value"])


def test_grade_and_bet_results_handle_the_draw():
    p = {"sport": "SOCCER_EPL", "game_id": "ev1", "home": "Arsenal", "away": "Chelsea", "final_home": 1,
         "final_away": 1, "result": "draw"}
    assert SP.bet_result({"market": "Moneyline", "side": "Draw"}, p) == "win"
    assert SP.bet_result({"market": "Moneyline", "side": "Arsenal"}, p) == "loss"
    assert SP.bet_result({"market": "Total", "side": "Over", "line": 2.5}, p) == "loss"
    assert SP.bet_result({"market": "Spread", "side": "Chelsea", "line": 0.0}, p) == "push"
    assert SP.bet_result({"market": "Spread", "side": "Chelsea", "line": 0.25}, p) is None     # quarter: by hand
    f = SP.bet_fields(dict(p, kickoff="2026-11-14T15:00:00Z"), "Moneyline", "draw", None, 260, 1, True)
    assert f["sport"] == "SOCCER" and f["side"] == "Draw" and f["notes"] == "gl:SOCCER_EPL:ev1"


def test_record_counts_favourites_and_flags():
    g = [{"result": "home", "p_home": .5, "p_draw": .3, "p_away": .2,
          "value": [{"market": "Moneyline", "side": "away", "price": 300, "ev": .05}]},
         {"result": "draw", "p_home": .45, "p_draw": .3, "p_away": .25, "value": []}]
    rec = SP.record(g)
    assert rec["fav"] == (1, 2) and rec["value"] == (0, 1) and rec["value_units"] == -1.0


def test_parse_day_and_summary():
    day = {"events": [{"id": "9", "date": "2026-11-08T15:00Z", "status": {"type": {"name": "STATUS_FULL_TIME", "completed": True}},
                       "competitions": [{"competitors": [
                           {"homeAway": "home", "score": "2", "team": {"displayName": "Arsenal"}},
                           {"homeAway": "away", "score": "0", "team": {"displayName": "Chelsea"}}]}]},
                      {"id": "10", "date": "2026-11-09T15:00Z", "status": {"type": {"name": "STATUS_SCHEDULED"}},
                       "competitions": [{"competitors": []}]}]}
    rows = D.parse_day(day, "SOCCER_EPL")
    assert rows == [{"id": "9", "date": "2026-11-08", "kickoff": "2026-11-08T15:00Z", "home_team": "Arsenal",
                     "away_team": "Chelsea", "home_points": 2, "away_points": 0, "neutral": False,
                     "league": "SOCCER_EPL", "status": "STATUS_FULL_TIME"}]
    sm = {"rosters": [{"team": {"displayName": "Arsenal"}, "roster": [
        {"athlete": {"displayName": "Bukayo Saka", "id": "1"}, "starter": True,
         "stats": [{"name": "totalGoals", "value": 1}, {"name": "totalShots", "value": 4}, {"name": "shotsOnTarget", "value": 2}]},
        {"athlete": {"displayName": "Bench Guy", "id": "2"}, "starter": False, "subbedIn": False, "stats": []}]}]}
    ps = D.parse_summary(sm)
    assert len(ps) == 1 and ps[0]["goals"] == 1 and ps[0]["sot"] == 2 and ps[0]["started"]


def test_props_rates_chance_and_settling():
    rows = {"m1": [{"team": "Arsenal", "player": "Bukayo Saka", "started": True, "goals": 1, "shots": 4, "sot": 2}],
            "m2": [{"team": "Arsenal", "player": "Bukayo Saka", "started": True, "goals": 0, "shots": 3, "sot": 1}]}
    rt = SPR.rates(rows, "Arsenal")["Bukayo Saka"]
    assert rt["starts"] == 2 and abs(rt["goals"] - 1 / 4) < 1e-9          # 1 goal / (2 starts + 2 prior)
    p = SPR.chance(rt, "Anytime Goal", None, 1.0)
    assert abs(p - (1 - np.exp(-0.25))) < 1e-9
    assert SPR.chance(rt, "Shots on Target", 0.5, 1.2) > SPR.chance(rt, "Shots on Target", 1.5, 1.2)
    odds = {"bookmakers": [{"key": "betrivers", "markets": [
        {"key": "player_goal_scorer_anytime", "outcomes": [{"name": "Yes", "description": "Bukayo Saka", "price": 210}]},
        {"key": "player_shots_on_target", "outcomes": [{"name": "Over", "description": "Bukayo Saka", "price": -150, "point": 0.5},
                                                       {"name": "Under", "description": "Bukayo Saka", "price": 120, "point": 0.5}]}]}]}
    pr = SPR.parse_prop_odds(odds)
    assert {(x["market"], x["line"]) for x in pr} == {("Anytime Goal", None), ("Shots on Target", 0.5)}
    summ = [{"player": "Bukayo Saka", "goals": 1, "sot": 1, "shots": 3}]
    assert SPR.prop_result({"player": "Bukayo Saka", "market": "Anytime Goal", "side": "Yes", "line": 0.5}, summ) == "win"
    assert SPR.prop_result({"player": "Bukayo Saka", "market": "Shots on Target", "side": "Over", "line": 1.5}, summ) == "loss"
    assert SPR.prop_result({"player": "Someone Else", "market": "Shots", "side": "Over", "line": 0.5}, summ) is None


def test_ticked_soccer_rows_log_as_soccer_bets():
    import todays_best as TB
    p = {"sport": "SOCCER_EPL", "game_id": "ev1", "home": "Arsenal", "away": "Chelsea",
         "kickoff": "2026-11-14T15:00:00Z"}
    it = {"sport": "SOCCER", "pick": "Draw", "price": 260, "_rec": p, "bet_market": "Moneyline", "bet_side": "draw",
          "bet_line": None, "best_tested": True, "best_chance": 0.27}
    rows = TB.bet_rows([it], 1.0, True, "soccer-lab", "2026-11-14")
    assert rows[0]["sport"] == "SOCCER" and rows[0]["side"] == "Draw" and "gl:SOCCER_EPL:ev1" in rows[0]["notes"]


def test_soccer_is_a_lab_sport():
    import sports
    assert "SOCCER" in sports.LAB_SPORTS and sports.LAB_PAGES["SOCCER"] == "55"


def test_page_renders(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import model_store as MS
    rec = {"sport": "SOCCER_EPL", "game_id": "ev1", "kickoff": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
           "home": "Arsenal", "away": "Chelsea", "p_home": .5, "p_draw": .27, "p_away": .23, "mkt_home": .52,
           "mkt_draw": .26, "mkt_away": .22, "sharp": True, "best_home": -110, "best_draw": 270, "best_away": 350,
           "line_total": 2.5, "p_over": .55, "mkt_over": .5, "xg_home": 1.7, "xg_away": 1.0, "p_btts": .5,
           "value": [{"market": "Moneyline", "side": "away", "price": 350, "book": "draftkings", "fair": .22, "ev": .21}],
           "use": SP.PASS, "result": None}
    done = dict(rec, game_id="ev0", kickoff="2026-11-08T15:00:00Z", result="home", final_home=2, final_away=0)
    monkeypatch.setattr(MS, "load_game_picks", lambda lg, **k: [rec, done] if lg == "SOCCER_EPL" else [])
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "55_Soccer_Lab.py"), default_timeout=60)
    at.session_state["sport"] = "SOCCER"
    at.run()
    assert not at.exception, at.exception
    df = at.dataframe[0].value
    assert "Arsenal vs Chelsea" in set(df["Match"]) and "📈 Chelsea +350" in df["Flags"].iloc[0]


def test_totals_use_the_main_line_not_an_alternate():
    ev = _event()
    for b in ev["bookmakers"]:
        if b["key"] == "draftkings":
            b["markets"].append({"key": "totals", "outcomes": [{"name": "Over", "price": 200, "point": 3.5},
                                                               {"name": "Under", "price": -260, "point": 3.5}]})
            b["markets"].append({"key": "totals", "outcomes": [{"name": "Over", "price": 400, "point": 4.5},
                                                               {"name": "Under", "price": -600, "point": 4.5}]})
    px = D.prices(ev, "Arsenal", "Chelsea")
    assert px["line_total"] == 2.5 and px["mkt_over"] is not None


def test_handicap_falls_back_to_the_sharp_line_without_us_prices():
    ev = _event()
    ev["bookmakers"] = [b for b in ev["bookmakers"] if b["key"] != "fanduel"]   # no US spreads
    px = D.prices(ev, "Arsenal", "Chelsea")
    assert px["home_spread"] == -0.5 and px.get("spread_price_home") is None and px["mkt_ah_home"] is not None


def test_team_aliases():
    assert SP.team(["LAFC", "Seattle Sounders FC"], "Los Angeles FC") == "LAFC"
