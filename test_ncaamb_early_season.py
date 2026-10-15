"""NCAA men's basketball opening week: nobody has played yet, so form comes from LAST season and the board says so."""
import ncaamb_engine as E
import ncaamb_projections as NP
import sports as S


def g(i, st, date="2026-03-01T00:00Z", opp="9"):
    return {"gameId": f"g{i}", "date": date, "opp_id": opp, "opp_name": "Opp", "season_type": st}


def box(pid, pts, minutes=28):
    return {pid: {"pts": pts, "reb": 5, "ast": 3, "fg3m": 1, "min": minutes}}


def wire(monkeypatch, current, prior, boxes, calls=None):
    def fake_ids(team_id, before_date, n=10, days_back=45):
        if calls is not None:
            calls.append((before_date, n, days_back))
        return list(prior if days_back == E.PRIOR_LOOKBACK_DAYS else current)
    monkeypatch.setattr(E, "get_team_recent_game_ids", fake_ids)
    monkeypatch.setattr(E, "get_game_boxscore", lambda gid: boxes.get(gid, {}))


def test_opening_night_pads_from_last_seasons_regular_season_and_postseason_and_skips_exhibitions(monkeypatch):
    # newest first, like the scoreboard scan: two tournament games, a prior-season exhibition, then the regular season
    prior = [g("t1", 3, "2026-03-28T00:00Z"), g("t2", 3, "2026-03-22T00:00Z"), g("x1", 1, "2026-03-10T00:00Z")] + \
            [g(f"r{i}", 2, "2026-03-0%dT00:00Z" % (9 - i)) for i in range(9)]
    pts = {"gt1": 31, "gt2": 29, "gx1": 2}
    boxes = {x["gameId"]: box(7, pts.get(x["gameId"], 20)) for x in prior}
    wire(monkeypatch, [], prior, boxes)
    log = E.get_player_recent_games(7, 10, team_id=1, before_date="2026-11-02")
    assert len(log) == 10 and {x["src"] for x in log} == {"prior"}
    assert [x["pts"] for x in log][:2] == [31, 29]                                   # the tournament games count: they are his latest form
    assert 2 not in [x["pts"] for x in log]                                          # a prior-season exhibition never does


def test_the_prior_season_lookback_reaches_the_late_february_games_of_a_team_that_went_out_early():
    from datetime import datetime, timedelta
    reach = datetime.strptime(E.SEASON_START, "%Y-%m-%d") - timedelta(days=E.PRIOR_LOOKBACK_DAYS)
    assert reach.strftime("%m-%d") <= "02-01"


def test_a_freshman_or_transfer_with_no_history_is_left_off_until_he_has_played(monkeypatch):
    wire(monkeypatch, [], [g(f"r{i}", 2) for i in range(10)], {})                     # none of those box scores include him
    assert E.get_player_recent_games(7, 10, team_id=1, before_date="2026-11-02") == []


def test_a_player_with_only_exhibition_games_falls_back_to_them(monkeypatch):
    wire(monkeypatch, [g("e1", 1), g("e2", 1)], [g(f"r{i}", 2) for i in range(10)], {"ge1": box(7, 12, 20), "ge2": box(7, 8, 18)})
    log = E.get_player_recent_games(7, 10, team_id=1, before_date="2026-11-02")
    assert [x["src"] for x in log] == ["preseason", "preseason"]


def test_after_a_few_games_current_results_lead_and_last_season_fills_the_rest(monkeypatch):
    current = [g(f"c{i}", 2, "2026-11-0%d" % (i + 2)) for i in range(3)]
    prior = [g(f"r{i}", 2) for i in range(12)]
    boxes = {x["gameId"]: box(7, 30 if x["gameId"].startswith("gc") else 18) for x in current + prior}
    wire(monkeypatch, current, prior, boxes)
    log = E.get_player_recent_games(7, 10, team_id=1, before_date="2026-11-10")
    assert [x["src"] for x in log] == ["current"] * 3 + ["prior"] * 7


def test_padding_stops_a_month_after_the_opener_and_for_season_baselines_and_full_logs(monkeypatch):
    current = [g(f"c{i}", 2) for i in range(6)]
    calls = []
    wire(monkeypatch, current, [g("r1", 2)], {**{x["gameId"]: box(7, 30) for x in current}, "gr1": box(7, 5)}, calls)
    assert {x["src"] for x in E.get_player_recent_games(7, 10, team_id=1, before_date="2026-12-15")} == {"current"}
    assert not [c for c in calls if c[2] == E.PRIOR_LOOKBACK_DAYS]
    assert len(E.get_player_recent_games(7, 10, team_id=1, before_date="2026-11-10", pad_prior=False)) == 6
    seen = {}
    monkeypatch.setattr(E, "get_player_recent_games",
                        lambda pid, last_n=0, team_id=None, before_date=None, days_back=0, pad_prior=True: seen.update(pad=pad_prior) or [])
    E.get_player_season_games(7, 1, "2026-11-10")
    assert seen["pad"] is False


def test_the_prior_season_is_looked_up_before_the_opener_not_before_today(monkeypatch):
    calls = []
    wire(monkeypatch, [], [g(f"r{i}", 2) for i in range(10)], {f"gr{i}": box(7, 20) for i in range(10)}, calls)
    E.get_player_recent_games(7, 10, team_id=1, before_date="2026-11-10")
    assert [c for c in calls if c[2] == E.PRIOR_LOOKBACK_DAYS][0][0] == E.SEASON_START


def test_the_opening_night_slate_is_no_longer_empty(monkeypatch):
    """The reported-before-it-happened failure: no team has a game in the last 45 days, so every player's log was empty and
    build_slate returned zero players."""
    monkeypatch.setattr(E, "get_schedule", lambda d: [{"gameId": "1", "game_date": "2026-11-03T00:00Z", "home_id": 1, "home_name": "Home U",
                                                       "away_id": 2, "away_name": "Away U", "home_abbr": "HOM", "away_abbr": "AWY"}])
    monkeypatch.setattr(E, "get_team_roster", lambda tid: [{"id": 10 * tid + k, "name": f"P{tid}{k}", "pos": "G"} for k in range(3)])
    prior = {1: [g(f"a{i}", 2) for i in range(10)], 2: [g(f"b{i}", 2) for i in range(10)]}

    def ids(team_id, before_date, n=10, days_back=45):
        return list(prior[team_id]) if days_back == E.PRIOR_LOOKBACK_DAYS else []
    monkeypatch.setattr(E, "get_team_recent_game_ids", ids)
    allbox = {}
    for tid, games in prior.items():
        for x in games:
            allbox[x["gameId"]] = {10 * tid + k: {"pts": 12 + k, "reb": 4, "ast": 2, "fg3m": 1, "min": 25} for k in range(3)}
    monkeypatch.setattr(E, "get_game_boxscore", lambda gid: allbox.get(gid, {}))
    rows, meta = E.build_slate("2026-11-02")
    assert len(rows) == 6 and len(meta) == 1 and {len(r["_game_log"]) for r in rows} == {10}
    plays = NP.build_best_bets(rows)
    assert plays and all(p["PriorGames"] == 10 for p in plays) and all("10 of last 10 games are from last season" in p["Why"] for p in plays)


def test_the_why_note_says_how_many_games_are_from_last_season():
    assert NP.data_note_for([{"src": "current"}] * 3 + [{"src": "prior"}] * 7) == (7, 0, " [7 of last 10 games are from last season]")
    assert NP.data_note_for([{"src": "preseason"}] * 2)[2].startswith(" [only 2 preseason game(s)")
    assert NP.data_note_for([{"pts": 1}] * 4) == (0, 0, "")                                   # untagged logs read as all current


def test_the_season_notice_follows_the_college_opener():
    assert S.get("NCAAMB").engine.SEASON_START == "2026-11-01"
    assert S.season_notice("NCAAMB", "2026-09-01") is None
    assert "about to start" in S.season_notice("NCAAMB", "2026-10-20") and "Nov 1" in S.season_notice("NCAAMB", "2026-10-20")
    assert S.season_notice("NCAAMB", "2026-10-17") is None and "about to start" in S.season_notice("NCAAMB", "2026-10-18")
    early = S.season_notice("NCAAMB", "2026-11-02")
    assert "Early college basketball season" in early and "Dec 1" in early and "Freshmen and transfers" in early
    assert S.season_notice("NCAAMB", "2026-12-01") is not None and S.season_notice("NCAAMB", "2026-12-02") is None
    assert S.season_notice("NCAAMB", "garbage") is None


def test_the_notice_renders_for_college_basketball_in_opening_week_and_is_gone_by_january():
    from streamlit.testing.v1 import AppTest

    def app(sport, date_str):
        import components as C
        C.season_notice(sport, date_str)

    at = AppTest.from_function(app, args=("NCAAMB", "2026-11-03"))
    at.run()
    assert any("Early college basketball season" in i.value for i in at.info)
    at = AppTest.from_function(app, args=("NCAAMB", "2027-01-10"))
    at.run()
    assert not at.info
    at = AppTest.from_function(app, args=("NCAAF", "2026-11-03"))
    at.run()
    assert not at.info


def test_every_betting_page_calls_the_notice_with_the_active_sport_so_college_basketball_gets_it_too():
    from pathlib import Path
    for name in ["1_#U2b50_Best_Bets.py", "2_Graded_Picks.py", "3_Suggested_Parlays.py", "4_Speculative_Basket.py", "37_Slip_Lab.py",
                 "15_#L01f4c8_Edge_Board.py", "21_Media_Room.py", "22_Podcast_Studio.py", "38_Position_Matchups.py", "39_Analyst_Desk.py"]:
        assert "C.season_notice(_active.key, date_str)" in (Path(__file__).parent / "views" / name).read_text(), name


def test_a_teams_recent_games_are_looked_up_once_per_slate_build_not_once_per_player(monkeypatch):
    scans = []

    def fake_window(site_api, fetch, start, end, diag, extra):
        scans.append((start, end))
        return [{"id": "1", "date": "2026-03-01T00:00Z", "season": {"type": 2}, "status": {"type": {"completed": True}},
                 "competitions": [{"competitors": [{"team": {"id": "5"}, "score": "70"}, {"team": {"id": "6", "displayName": "X"}, "score": "60"}]}]}]
    monkeypatch.setattr(E.BB, "scoreboard_events_in_window", fake_window)
    E._response_cache.clear()
    first = E.get_team_recent_game_ids(5, "2026-11-02", 60, days_back=E.PRIOR_LOOKBACK_DAYS)
    for _ in range(12):
        again = E.get_team_recent_game_ids(5, "2026-11-02", 60, days_back=E.PRIOR_LOOKBACK_DAYS)
    assert len(scans) == 1 and again == first and first[0]["gameId"] == "1"
    again[0]["gameId"] = "mutated"                                                       # a caller can't corrupt the shared answer
    assert E.get_team_recent_game_ids(5, "2026-11-02", 60, days_back=E.PRIOR_LOOKBACK_DAYS)[0]["gameId"] == "1"
    E.get_team_recent_game_ids(5, "2026-11-02", 60, days_back=45)                         # a different window is a different answer
    E.get_team_recent_game_ids(6, "2026-11-02", 60, days_back=E.PRIOR_LOOKBACK_DAYS)
    assert len(scans) == 3
    E._response_cache.clear()


def test_eight_workers_asking_for_the_same_scoreboard_at_once_download_it_once(monkeypatch):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    hits = []

    def slow(url, params=None):
        hits.append(url)
        time.sleep(0.05)
        return {"ok": True}
    monkeypatch.setattr(E, "_get_json", slow)
    E._response_cache.clear()
    E._key_locks.clear()
    with ThreadPoolExecutor(max_workers=8) as ex:
        out = list(ex.map(lambda _: E._get_json_cached("http://x/scoreboard", {"dates": "202611"}), range(8)))
    assert len(hits) == 1 and all(o == {"ok": True} for o in out)
    E._response_cache.clear()
    E._key_locks.clear()
