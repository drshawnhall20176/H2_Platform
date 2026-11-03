import intl_hoops as I
import tennis_model as T


def _espn_tennis():
    def comp(cid, a, b, wa, sa, sb, status="STATUS_FINAL"):
        return {"id": cid, "date": "2025-10-12T10:00Z", "round": {"displayName": "Round 1"},
                "status": {"type": {"completed": True, "name": status}},
                "competitors": [{"athlete": {"displayName": a}, "winner": wa, "linescores": [{"value": v} for v in sa]},
                                {"athlete": {"displayName": b}, "winner": not wa, "linescores": [{"value": v} for v in sb]}]}
    return {"events": [{"name": "Mutua Madrid Open", "groupings": [
        {"grouping": {"displayName": "Men's Singles"}, "competitions": [
            comp(1, "Carlos Alcaraz", "Jannik Sinner", True, [6, 3, 7], [4, 6, 5]),
            comp(2, "A B", "C D", False, [1, 0], [6, 3], status="STATUS_RETIRED")]},
        {"grouping": {"displayName": "Men's Doubles"}, "competitions": [comp(3, "X", "Y", True, [6], [0])]}]}]}


def test_parse_day_singles_scores_and_surface():
    ms = T.parse_day(_espn_tennis(), "atp")
    assert len(ms) == 2
    m = ms[0]
    assert m["surface"] == "clay" and m["best_of"] == 3 and m["winner"] == 1
    assert (m["sets1"], m["sets2"], m["games1"], m["games2"]) == (2, 1, 16, 15)
    assert ms[1]["status"] == "retired" and ms[1]["winner"] == 2
    assert T.surface("Wimbledon") == "grass" and T.surface("Rolex Paris Masters") == "hard"
    assert T.best_of("Wimbledon", "atp") == 5 and T.best_of("Wimbledon", "wta") == 3


def test_elo_learns_the_better_player():
    ms = [{"id": f"m{i}", "date": f"2025-01-{1 + i % 28:02d}", "p1": "Strong Guy", "p2": f"Weak {i}", "winner": 1,
           "surface": "hard", "status": "final"} for i in range(30)]
    elo, rows = T.run(ms)
    assert rows[0]["p"] == 0.5 and elo.prob("Strong Guy", "Newcomer", "hard") > 0.8
    assert elo.prob("Strong Guy", "Newcomer", "clay") < elo.prob("Strong Guy", "Newcomer", "hard")
    assert elo.matches("strong guy") == 30


def test_games_fit_and_over_chance():
    rows = [{"p": 0.5 + d, "best_of": 3, "status": "final", "games1": 12 + int(20 * d), "games2": 10 - int(20 * d)}
            for d in [x / 100 for x in range(-30, 31)] * 2]
    fit = T.fit_games(rows)
    g = T.games(fit, 0.8, 3)
    assert g["margin"] > 4 and abs(T.p_over(10, 3, 10) - 0.5) < 1e-9


def test_hoops_team_matching_and_projection():
    ev = [{"home_team": "Real Madrid", "away_team": "Panathinaikos"}, {"home_team": "Fenerbahce", "away_team": "Monaco"}]
    assert I.match_event(ev, "Panathinaikos AKTOR Athens", "Real Madrid")["home_team"] == "Real Madrid"
    assert I.match_event(ev, "Olympiacos Piraeus", "Monaco") is None
    games = [{"home_team": h, "away_team": a, "home_points": hp, "away_points": ap, "neutral_site": False}
             for h, a, hp, ap in [("Real Madrid", "Monaco", 90, 80), ("Monaco", "Fenerbahce", 85, 82),
                                  ("Fenerbahce", "Real Madrid", 78, 88)] * 5]
    p = I.project(I.ratings(games, 3.0), "Real Madrid Baloncesto", "AS Monaco")
    assert p and p["margin"] > 0 and 150 < p["total"] < 190
    assert I.win_prob(0) == 0.5 and I.win_prob(10) > 0.75
    assert I.season_of("NBL", "2026-01-10") == "2025" and I.season_of("NBL", "2025-10-10") == "2025"


def test_euroleague_parser():
    data = {"data": [{"identifier": "E2025_1", "played": True, "date": "2025-10-01T18:00:00",
                      "local": {"club": {"name": "Real Madrid"}, "score": 90},
                      "road": {"club": {"name": "Monaco"}, "score": 80}},
                     {"identifier": "E2025_2", "played": False, "local": {}, "road": {}}]}
    g = I.euroleague_season("E2025", fetch=lambda url, params=None: data)
    assert len(g) == 1 and g[0]["home_points"] == 90 and g[0]["date"] == "2025-10-01"


# --------------------------------------------------------------------------- live tracking (intl_picks)
from datetime import date, datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import intl_picks as IP  # noqa: E402
import model_store as MS  # noqa: E402

NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


def _ev(eid, home, away, ph, pa, spread=None, total=None, ko="2026-11-04T12:00:00Z"):
    mk = [{"key": "h2h", "outcomes": [{"name": home, "price": ph}, {"name": away, "price": pa}]}]
    if spread is not None:
        mk.append({"key": "spreads", "outcomes": [{"name": home, "price": -110, "point": spread},
                                                  {"name": away, "price": -110, "point": -spread}]})
    if total is not None:
        mk.append({"key": "totals", "outcomes": [{"name": "Over", "price": -110, "point": total},
                                                 {"name": "Under", "price": -110, "point": total}]})
    return {"id": eid, "commence_time": ko, "home_team": home, "away_team": away,
            "bookmakers": [{"key": "draftkings", "title": "DraftKings", "markets": mk}]}


def _strong_history():
    rows = []
    for i in range(40):
        rows.append({"id": f"a{i}", "date": f"2026-0{1 + i % 9}-10", "tour": "atp", "tournament": "X", "surface": "hard",
                     "best_of": 3, "p1": "Ace Server", "p2": f"Opp {i}", "winner": 1, "games1": 12, "games2": 6,
                     "status": "final"})
        rows.append({"id": f"b{i}", "date": f"2026-0{1 + i % 9}-11", "tour": "atp", "tournament": "X", "surface": "hard",
                     "best_of": 3, "p1": "Even Steven", "p2": f"Opp {i}", "winner": 1 if i % 2 else 2, "games1": 10,
                     "games2": 10, "status": "final"})
    return rows


def test_tennis_build_picks_only_rated_players_with_an_edge():
    elo, rows = T.run(_strong_history())
    recs = IP.tennis_build(elo, {}, "tennis_atp_paris_masters",
                           [_ev("e1", "Ace Server", "Even Steven", 110, -130), _ev("e2", "Ace Server", "Nobody New", -300, 250),
                            _ev("e0", "Ace Server", "Even Steven", 110, -130, ko="2026-11-02T12:00:00Z")], NOW)
    by = {r["game_id"]: r for r in recs}
    assert "e0" not in by                                       # already started
    assert by["e1"]["pick"] is None and by["e1"]["edge"] > 0.05    # picks are off (backtest: no edge)
    assert by["e2"]["pick"] is None
    import pytest
    mp = pytest.MonkeyPatch()
    mp.setattr(IP, "TENNIS_ML_EDGE", 0.05)
    try:
        again = {r["game_id"]: r for r in IP.tennis_build(elo, {}, "tennis_atp_paris_masters",
                 [_ev("e1", "Ace Server", "Even Steven", 110, -130), _ev("e2", "Ace Server", "Nobody New", -300, 250)], NOW)}
        assert again["e1"]["pick"] == "home" and again["e2"]["pick"] is None     # unrated opponent never picked
    finally:
        mp.undo()
    assert by["e1"]["surface"] == "hard" and by["e1"]["tour"] == "atp"


def test_hoops_build_and_record():
    games = [{"home_team": h, "away_team": a, "home_points": hp, "away_points": ap, "neutral_site": False}
             for h, a, hp, ap in [("Real Madrid", "Monaco", 95, 75), ("Monaco", "Fenerbahce", 80, 82),
                                  ("Fenerbahce", "Real Madrid", 70, 90)] * 6]
    r = I.ratings(games, 3.0)
    recs = IP.hoops_build("EUROLEAGUE", r, [_ev("g1", "Real Madrid", "Monaco", -150, 130, spread=-2.5, total=160)], NOW)
    assert len(recs) == 1 and recs[0]["pick"] == "home" and recs[0]["edge"] >= IP.HOOPS_RULES["EUROLEAGUE"]["spread"]
    nbl = IP.hoops_build("NBL", r, [_ev("g1", "Real Madrid", "Monaco", 200, -250, spread=-2.5, total=160)], NOW)
    assert nbl[0]["pick"] is None and nbl[0]["ml_pick"] == "home"           # NBL: moneyline only
    graded = dict(recs[0], final_home=90, final_away=80, result="home", close_line=2.5)
    rec = IP.record([graded])
    assert rec["spread"]["w"] == 1 and abs(rec["spread"]["units"] - 100 / 110) < 1e-9
    lost = dict(graded, final_home=81, final_away=80)
    assert IP.record([lost])["spread"]["l"] == 1


def test_tennis_record_handles_retirements():
    p = {"sport": "TENNIS", "pick": "home", "best_home": 120, "best_away": -140, "spread_pick": "home", "home_spread": -2.5,
         "total_pick": "over", "line_total": 21.5, "over_price": -110, "under_price": -110}
    won = IP.grade_markets(dict(p, final_home=13, final_away=9, result="home"))
    assert won["ml"]["r"] == "win" and abs(won["ml"]["units"] - 1.2) < 1e-9
    assert won["spread"]["r"] == "win" and won["total"]["r"] == "win"
    assert IP.grade_markets(dict(p, final_home=3, final_away=1, result="retired")) == {}


def test_capture_end_to_end_with_a_local_store(tmp_path, monkeypatch):
    db = str(tmp_path / "m.db")
    MS.save_results("TENNIS", _strong_history(), db_path=db)
    monkeypatch.setattr(T, "crawl", lambda *a, **k: [])

    def fetch(url, params=None):
        if url.endswith("/sports"):
            return [{"key": "tennis_atp_paris_masters", "group": "Tennis", "active": True}]
        return [_ev("e1", "Ace Server", "Even Steven", 110, -130, spread=-2.5, total=21.5)]
    out = IP.tennis_capture("k", fetch=fetch, now=NOW, db_path=db)
    assert out["priced"] == 1 and out["picks"] == 0 and out["saved"] == 1
    MS.save_results("TENNIS", [{"id": "z", "date": "2026-11-04", "tour": "atp", "tournament": "Paris", "surface": "hard",
                                "best_of": 3, "p1": "Even Steven", "p2": "Ace Server", "winner": 2, "games1": 8,
                                "games2": 12, "status": "final"}], db_path=db)
    assert IP.tennis_grade(MS.load_results("TENNIS", db_path=db), db_path=db) == 1
    g = MS.load_game_picks("TENNIS", db_path=db)[0]
    assert g["result"] == "home" and g["final_home"] == 12 and IP.record([g]) == {}
    assert IP.record([dict(g, pick="home")])["ml"]["w"] == 1


def test_pages_render(monkeypatch):
    from streamlit.testing.v1 import AppTest
    up = {"sport": "TENNIS", "game_id": "e1", "kickoff": "2099-01-01T12:00:00+00:00", "tour": "atp",
          "tournament": "Paris Masters", "surface": "hard", "home": "A B", "away": "C D", "model_p": 0.6, "line": 0.5,
          "edge": 0.1, "best_home": 110, "best_away": -130, "model_total": 22.1, "line_total": 21.5, "n_home": 40,
          "n_away": 40, "pick": "home", "spread_pick": None, "total_pick": "over", "result": None}
    hoop = {"sport": "EUROLEAGUE", "game_id": "g1", "kickoff": "2099-01-01T18:00:00+00:00", "home": "Real Madrid",
            "away": "Monaco", "model_margin": 8.0, "home_spread": -2.5, "edge": 5.5, "model_total": 165.0,
            "line_total": 160.0, "model_p": 0.75, "fair_home": 0.6, "pick": "home", "result": None}
    monkeypatch.setattr(MS, "load_game_picks", lambda sport, ungraded=False, db_path=None: [up] if sport == "TENNIS" else [hoop])
    for page, needle in (("43_Tennis_Lab.py", "A B ML"), ("44_Intl_Hoops.py", "Real Madrid -2.5")):
        at = AppTest.from_file(str(Path(__file__).parent / "views" / page), default_timeout=30)
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        assert needle in at.dataframe[0].value.to_string()


def test_schedule_lists_unpriced_matches_with_fair_odds():
    elo, _ = T.run(_strong_history())
    data = {"events": [{"name": "Reto Win Tennis Cali Open", "groupings": [{"grouping": {"displayName": "Women's Singles"},
            "competitions": [
                {"id": 9, "date": "2026-11-04T16:00Z", "round": {"displayName": "Round 2"}, "status": {"type": {"state": "pre"}},
                 "competitors": [{"athlete": {"displayName": "Ace Server"}}, {"athlete": {"displayName": "Even Steven"}}]},
                {"id": 10, "date": "2026-11-03T10:00Z", "status": {"type": {"state": "in"}},
                 "competitors": [{"athlete": {"displayName": "A"}}, {"athlete": {"displayName": "B"}}]}]}]}]}
    recs = IP.tennis_schedule(elo, fetch=lambda url, params=None: data if "wta" in url else {}, now=NOW)
    assert len(recs) == 1 and recs[0]["source"] == "espn" and recs[0]["surface"] == "clay" and recs[0]["pick"] is None
    assert recs[0]["model_p"] > 0.5
    dup = IP.tennis_schedule(elo, fetch=lambda url, params=None: data if "wta" in url else {}, now=NOW,
                             priced=[{"home": "Even Steven", "away": "Ace Server"}])
    assert dup == []
    assert T.fair_odds(0.75) == -300 and T.fair_odds(0.25) == 300 and T.fair_odds(1.0) is None
    graded = [dict(recs[0], result="home"), dict(recs[0], result="away", model_p=0.3), dict(recs[0], result="away")]
    fav = IP.favorite_record(graded)
    assert fav["espn"]["n"] == 3 and fav["espn"]["won"] == 2


def test_tennis_page_shows_schedule_and_checks_a_price(monkeypatch):
    from streamlit.testing.v1 import AppTest
    sch = {"sport": "TENNIS", "game_id": "espn-wta-9", "kickoff": "2099-01-01T16:00:00+00:00", "tour": "wta",
           "tournament": "Reto Win Tennis Cali Open", "round": "Round 2", "surface": "clay", "home": "Elizabeth Mandlik",
           "away": "Jazmin Ortenzi", "model_p": 0.6, "n_home": 80, "n_away": 40, "source": "espn", "result": None}
    monkeypatch.setattr(MS, "load_game_picks", lambda sport, ungraded=False, db_path=None: [sch])
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "43_Tennis_Lab.py"), default_timeout=30)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    t = at.dataframe[0].value.to_string()
    assert "Elizabeth Mandlik" in t and "-150" in t
    at.number_input(key="tl_chk_price").set_value(-120).run()
    assert any("+10.0%" in m.value for m in at.markdown)


def test_college_names_never_cross_match():
    names = ["Kentucky Wildcats", "Arizona Wildcats", "Tennessee Volunteers", "Tennessee State Tigers", "Duke Blue Devils"]
    assert I.find_team(names, "Kentucky Wildcats") == "Kentucky Wildcats"
    assert I.find_team(names, "Tennessee Volunteers") == "Tennessee Volunteers"
    assert I.find_team(names, "Wildcats") is None                       # ambiguous: no guess
    assert I.find_team(names, "Northwestern Wildcats") is None           # only "wildcats" in common
    assert I.find_team(names, "Tennessee St Tigers") == "Tennessee State Tigers"
    ev = [{"home_team": "Tennessee Volunteers", "away_team": "Wofford Terriers"},
          {"home_team": "Tennessee State Tigers", "away_team": "Wofford Terriers"}]
    assert I.match_event(ev, "Tennessee Volunteers", "Wofford Terriers") is ev[0]


def test_weighted_ratings_and_decay():
    games = [{"date": d, "home_team": h, "away_team": a, "home_points": hp, "away_points": ap, "neutral_site": False}
             for d, h, a, hp, ap in [("2026-03-01", "A", "B", 70, 80), ("2026-03-02", "B", "A", 80, 70),
                                     ("2026-11-02", "A", "B", 90, 60), ("2026-11-02", "B", "A", 60, 90)] * 5]
    w = I.decay_weights(games, "2026-11-03", "NCAAMB")
    assert w[2] > 0.95 and w[0] < 0.05                                  # 8 months old and last season
    r = I.ratings_weighted(games, w, 1.0)
    assert r["off"]["A"] > r["off"]["B"]                                 # tonight's results dominate


def test_ncaamb_game_lab_and_intl_page_render(monkeypatch):
    from streamlit.testing.v1 import AppTest
    g = {"sport": "NCAAMB", "game_id": "c1", "kickoff": "2099-01-01T23:00:00+00:00", "home": "Tennessee Volunteers",
         "away": "Wofford Terriers", "model_margin": 22.0, "home_spread": -25.5, "edge": -3.5, "model_total": 150.0,
         "line_total": 155.5, "model_p": 0.97, "fair_home": 0.98, "pick": None, "total_pick": None, "ml_pick": None,
         "result": None}
    monkeypatch.setattr(MS, "load_game_picks", lambda sport, ungraded=False, db_path=None: [g])
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "45_NCAAMB_Game_Lab.py"), default_timeout=30)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Tennessee Volunteers -25.5" in at.dataframe[0].value.to_string()
    at.text_input(key="hg_q_NCAAMB").set_value("duke").run()
    assert any("Upcoming (0)" in m.value for m in at.markdown)
    at2 = AppTest.from_file(str(Path(__file__).parent / "views" / "44_Intl_Hoops.py"), default_timeout=30)
    at2.run()
    assert not at2.exception, [e.value for e in at2.exception]


def test_ncaamb_spread_rule_is_16_points_with_use_tags():
    games = [{"home_team": h, "away_team": a, "home_points": hp, "away_points": ap, "neutral_site": False}
             for h, a, hp, ap in [("Duke Blue Devils", "Army Black Knights", 95, 55), ("Army Black Knights", "Duke Blue Devils", 50, 92),
                                  ("Army Black Knights", "Navy Midshipmen", 70, 68), ("Navy Midshipmen", "Duke Blue Devils", 55, 90)] * 5]
    r = I.ratings(games, 4.0)
    recs = IP.hoops_build("NCAAMB", r, [_ev("c1", "Duke Blue Devils", "Army Black Knights", -5000, 2000, spread=-20.5, total=140),
                                        _ev("c2", "Duke Blue Devils", "Navy Midshipmen", -5000, 2000, spread=-38.5, total=140)], NOW)
    by = {x["game_id"]: x for x in recs}
    import props_engine as PE
    c1 = by["c1"]
    assert (c1["pick"] is not None) == (abs(c1["edge"]) >= 16)
    assert by["c2"]["ml_pick"] is None and by["c2"]["total_pick"] is None
    assert IP.use_tag(IP.cover_estimate("NCAAMB", 9)["chance"])["use"] == PE.USE_PASS
    assert IP.use_tag(IP.cover_estimate("NCAAMB", -17)["chance"])["use"] == PE.USE_SINGLE
    t = IP.use_tag(IP.cover_estimate("NCAAMB", 22)["chance"])
    assert t["use"] == PE.USE_BOTH and t["lock"]
    assert IP.cover_estimate("EUROLEAGUE", 7)["chance"] > 0.55 and IP.cover_estimate("NBL", 7) is None


def test_logged_game_lab_bets_settle_from_the_graded_game(tmp_path, monkeypatch):
    import betlog as B
    db, bdb = str(tmp_path / "m.db"), str(tmp_path / "b.db")
    monkeypatch.setattr(B, "list_bets", lambda *a, _l=B.list_bets, **k: _l(db_path=bdb, **{x: y for x, y in k.items() if x != "db_path"}))
    monkeypatch.setattr(B, "add_bet", lambda *a, _a=B.add_bet, **k: _a(bdb, **k))
    monkeypatch.setattr(B, "update_bet", lambda bid, _u=B.update_bet, **k: _u(bid, bdb, **k))
    rec = {"sport": "NCAAMB", "game_id": "c9", "kickoff": "2026-11-03T23:00:00+00:00", "home": "Duke Blue Devils",
           "away": "Army Black Knights", "line": 20.5, "edge": 9.0, "home_spread": -20.5, "line_total": 140.0,
           "best_home": -5000, "best_away": 2000, "model_p": 0.97}
    MS.save_game_picks([rec], db_path=db)
    for mk, side, line, odds in (("Spread", "home", -20.5, -110), ("Spread", "away", 20.5, -110),
                                 ("Total", "over", 140.0, -110), ("Moneyline", "away", None, 2000)):
        f = IP.bet_fields(rec, mk, side, line, odds, 5, True)
        assert f["sport"] == "NCAAMB" and f["notes"] == "gl:NCAAMB:c9"
        B.add_bet(**f)
    MS.grade_game_pick("NCAAMB", "c9", 90, 60, "home", db_path=db)
    assert IP.settle_logged("NCAAMB", db_path=db) == 4
    got = {(b["market"], b["side"]): b["result"] for b in B.list_bets()}
    assert got == {("Spread", "Duke Blue Devils"): "win", ("Spread", "Army Black Knights"): "loss",
                   ("Total", "Over"): "win", ("Moneyline", "Army Black Knights"): "loss"}


def test_game_lab_log_panel_logs_the_tracking_pick(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import betlog as B
    g = {"sport": "NCAAMB", "game_id": "c1", "kickoff": "2099-01-01T23:00:00+00:00", "home": "Duke Blue Devils",
         "away": "Army Black Knights", "model_margin": 30.0, "home_spread": -20.5, "spread_price": -110, "edge": 9.5,
         "model_total": 150.0, "line_total": 140.0, "over_price": -110, "under_price": -110, "model_p": 0.97,
         "fair_home": 0.95, "best_home": -5000, "best_away": 2000, "pick": "home", "total_pick": None, "ml_pick": None,
         "result": None}
    got = []
    monkeypatch.setattr(MS, "load_game_picks", lambda sport, ungraded=False, db_path=None: [g])
    monkeypatch.setattr(B, "add_bet", lambda *a, **k: got.append(k) or 77)
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "45_NCAAMB_Game_Lab.py"), default_timeout=30)
    at.run()
    at.button(key="hg_log_go_NCAAMB").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert got and got[0]["side"] == "Duke Blue Devils" and got[0]["line"] == -20.5 and got[0]["market"] == "Spread"
    assert any("Logged #77" in s.value for s in at.success)


def test_game_lab_shows_model_side_gap_and_tags(monkeypatch):
    from streamlit.testing.v1 import AppTest
    g = {"sport": "NCAAMB", "game_id": "c1", "kickoff": "2099-01-01T23:00:00+00:00", "home": "Duke Blue Devils",
         "away": "Army Black Knights", "model_margin": 3.0, "home_spread": -24.5, "spread_price": -110, "edge": -21.5,
         "cover_est": 0.725, "cover_n": 295, "use": "🎟️ Parlay + Single", "lock": True, "model_total": 150.0,
         "line_total": 140.0, "model_p": 0.6, "fair_home": 0.95, "pick": "away", "result": None}
    monkeypatch.setattr(MS, "load_game_picks", lambda sport, ungraded=False, db_path=None: [g])
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "45_NCAAMB_Game_Lab.py"), default_timeout=30)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    t = at.dataframe[0].value.to_string()
    assert "Army Black Knights +24.5" in t and "21.5" in t and "72%" in t and "🔒 Most probable" in t
