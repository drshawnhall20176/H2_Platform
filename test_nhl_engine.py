"""
test_nhl_engine.py — offline tests for nhl_engine (no network: every ESPN call is monkeypatched).

The summary fixture below is a faithful copy of the REAL response shape confirmed live (a 2025-26
game, VAN 8 @ COL 6, gameId 401803539): boxscore.players[] -> one entry per team -> statistics[]
groups named "forwards" / "defenses" / "goalies", each with a `keys` array, a `labels` array and
athletes[].stats aligned to them. The two traps the module exists to avoid are built in on purpose:
the label "SOG" is SHOOTOUT goals (key shootoutGoals), and shots on goal is the column labelled "S"
(key shotsTotal).

    python test_nhl_engine.py     # or: pytest test_nhl_engine.py
"""

import pytest

import basketball_engine as BB
import nhl_engine as E

COL, VAN = 17, 22


# ------------------------------------------------------------------- real-shape fixtures
_SKATER_KEYS = ["timeOnIce", "shotsTotal", "shootoutGoals", "goals", "assists", "blockedShots",
                "hits", "penaltyMinutes", "powerPlayTimeOnIce"]
_SKATER_LABELS = ["TOI", "S", "SOG", "G", "A", "BS", "HT", "PIM", "PPTOI"]
_GOALIE_KEYS = ["timeOnIce", "shotsAgainst", "goalsAgainst", "saves"]
_GOALIE_LABELS = ["TOI", "SA", "GA", "SV"]


def _skater(pid, name, toi, sog, goals, assists, blk, pos="C", shootout=0):
    return {"athlete": {"id": str(pid), "displayName": name, "position": {"abbreviation": pos}},
            "stats": [toi, str(sog), str(shootout), str(goals), str(assists), str(blk), "1", "0", "2:10"]}


def _goalie(pid, name, toi, sa, ga, saves):
    return {"athlete": {"id": str(pid), "displayName": name, "position": {"abbreviation": "G"}},
            "stats": [toi, str(sa), str(ga), str(saves)]}


def _team_block(team_id, forwards, goalies, defense=()):
    stats = [{"name": "forwards", "keys": _SKATER_KEYS, "labels": _SKATER_LABELS, "athletes": forwards}]
    if defense:
        stats.append({"name": "defenses", "keys": _SKATER_KEYS, "labels": _SKATER_LABELS,
                      "athletes": list(defense)})
    stats.append({"name": "goalies", "keys": _GOALIE_KEYS, "labels": _GOALIE_LABELS, "athletes": goalies})
    return {"team": {"id": str(team_id)}, "statistics": stats}


def _summary(completed=True):
    return {
        "header": {"competitions": [{"status": {"type": {"completed": completed}}}]},
        "boxscore": {"players": [
            _team_block(VAN,
                        [_skater(1, "Elias Pettersson", "19:48", 5, 2, 1, 0),
                         _skater(2, "Depth Forward", "8:31", 0, 0, 0, 1, pos="LW")],
                        [_goalie(90, "Thatcher Demko", "58:12", 41, 6, 35),
                         _goalie(91, "Backup Goalie", "1:48", 1, 0, 1)],
                        defense=[_skater(3, "Quinn Hughes", "24:10", 3, 0, 3, 2, pos="D")]),
            _team_block(COL,
                        [_skater(10, "Nathan MacKinnon", "21:00", 8, 3, 2, 0, shootout=1)],
                        [_goalie(95, "Colorado Goalie", "60:00", 23, 8, 15)]),
        ]},
    }


def _game(gid, final=True, mackinnon_goals=1.0, mackinnon_sog=4.0, toi=20.0):
    """A compact parsed record (what parse_summary returns) for engine-level tests."""
    return {"final": final,
            "players": {
                10: {"team_id": COL, "pos": "C", "role": "skater", "toi": toi, "g": mackinnon_goals,
                     "a": 1.0, "pts": mackinnon_goals + 1.0, "sog": mackinnon_sog, "blk": 0.0},
                95: {"team_id": COL, "pos": "G", "role": "goalie", "toi": 60.0, "saves": 25.0,
                     "sa": 27.0, "ga": 2.0, "gs": True},
                96: {"team_id": COL, "pos": "G", "role": "goalie", "toi": 2.0, "saves": 1.0,
                     "sa": 1.0, "ga": 0.0, "gs": False},
                1: {"team_id": VAN, "pos": "C", "role": "skater", "toi": 19.0, "g": 0.0, "a": 0.0,
                    "pts": 0.0, "sog": 2.0, "blk": 1.0}},
            "teams": {COL: {"goals": mackinnon_goals, "assists": 1.0, "pts": mackinnon_goals + 1,
                            "sog": mackinnon_sog, "blk": 0.0, "saves": 26.0, "sa": 28.0},
                      VAN: {"goals": 0.0, "assists": 0.0, "pts": 0.0, "sog": 2.0, "blk": 1.0,
                            "saves": 20.0, "sa": 22.0}}}


@pytest.fixture(autouse=True)
def _reset_caches():
    E._game_cache.clear()
    E._game_failed.clear()
    E._game_locks.clear()
    E._response_cache.clear()
    E._diag_seen.clear()
    yield
    E._game_cache.clear()
    E._game_failed.clear()
    E._game_locks.clear()
    E._response_cache.clear()


# ------------------------------------------------------------------- toi
def test_toi_minutes_parses_and_fails_soft():
    assert E.toi_minutes("19:48") == pytest.approx(19.8)
    assert E.toi_minutes("0:30") == pytest.approx(0.5)
    assert E.toi_minutes("12") == 12.0
    for bad in (None, "", "--", "-", "abc", "1:xx"):
        assert E.toi_minutes(bad) == 0.0


# ------------------------------------------------------------------- parse_summary (real shape)
def test_parse_summary_reads_stats_by_key_not_label():
    rec = E.parse_summary(_summary())
    mack = rec["players"][10]
    # 8 shots, 3 goals, 2 assists — and the 1 SHOOTOUT goal (label "SOG") must not become shots
    assert mack["sog"] == 8.0 and mack["g"] == 3.0 and mack["a"] == 2.0 and mack["pts"] == 5.0
    pett = rec["players"][1]
    assert (pett["sog"], pett["g"], pett["a"], pett["pts"], pett["blk"]) == (5.0, 2.0, 1.0, 3.0, 0.0)
    assert pett["toi"] == pytest.approx(19.8) and pett["role"] == "skater" and pett["team_id"] == VAN


def test_parse_summary_includes_defensemen_and_types_ids_as_int():
    rec = E.parse_summary(_summary())
    assert all(isinstance(k, int) for k in rec["players"])
    assert rec["players"][3]["pos"] == "D" and rec["players"][3]["pts"] == 3.0


def test_parse_summary_goalie_of_record_is_the_one_with_most_ice_time():
    rec = E.parse_summary(_summary())
    demko, backup = rec["players"][90], rec["players"][91]
    assert demko["role"] == "goalie" and demko["gs"] is True
    assert (demko["saves"], demko["sa"], demko["ga"]) == (35.0, 41.0, 6.0)
    assert backup["gs"] is False                       # a 1:48 relief appearance is not a start
    assert rec["players"][95]["gs"] is True


def test_parse_summary_no_goalie_of_record_below_min_toi():
    data = _summary()
    data["boxscore"]["players"][0]["statistics"][-1]["athletes"] = [
        _goalie(90, "Short Night", "9:00", 5, 2, 3)]
    rec = E.parse_summary(data)
    assert rec["players"][90]["gs"] is False           # under CFG.GOALIE_MIN_TOI


def test_parse_summary_team_totals_sum_the_player_lines():
    rec = E.parse_summary(_summary())
    van, col = rec["teams"][VAN], rec["teams"][COL]
    assert van["goals"] == 2.0 and van["assists"] == 4.0 and van["pts"] == 6.0
    assert van["sog"] == 8.0 and van["blk"] == 3.0
    assert van["saves"] == 36.0 and van["sa"] == 42.0   # both VAN goalies
    assert col["goals"] == 3.0 and col["sog"] == 8.0 and col["saves"] == 15.0


def test_parse_summary_final_flag_follows_the_completed_status():
    assert E.parse_summary(_summary(completed=True))["final"] is True
    assert E.parse_summary(_summary(completed=False))["final"] is False


def test_parse_summary_skips_did_not_play_and_zero_toi():
    data = _summary()
    fwd = data["boxscore"]["players"][0]["statistics"][0]["athletes"]
    fwd.append({"athlete": {"id": "7", "displayName": "Scratch"}, "stats": [], "didNotPlay": True})
    fwd.append(_skater(8, "Zero Toi", "0:00", 0, 0, 0, 0))
    rec = E.parse_summary(data)
    assert 7 not in rec["players"] and 8 not in rec["players"]


def test_parse_summary_falls_back_to_labels_when_keys_are_absent():
    data = _summary()
    for pg in data["boxscore"]["players"]:
        for grp in pg["statistics"]:
            del grp["keys"]
    rec = E.parse_summary(data)
    mack = rec["players"][10]
    assert mack["sog"] == 8.0 and mack["g"] == 3.0     # "S" is shots; "SOG" is NOT shots
    assert rec["players"][90]["saves"] == 35.0


def test_parse_summary_none_when_no_boxscore():
    assert E.parse_summary(None) is None
    assert E.parse_summary({}) is None
    assert E.parse_summary({"boxscore": {"players": []}}) is None


# ------------------------------------------------------------------- REAL data (VAN 8 @ COL 6)
def _real_game():
    import json
    import pathlib
    path = pathlib.Path(__file__).parent / "test_fixtures" / "nhl_summary_401803539.json"
    return E.parse_summary(json.loads(path.read_text()))


def test_real_summary_team_goals_reconcile_to_the_final_score():
    rec = _real_game()
    assert rec["final"] is True
    assert rec["teams"][VAN]["goals"] == 8.0 and rec["teams"][COL]["goals"] == 6.0


def test_real_summary_shots_reconcile_between_skaters_and_the_opposing_goalies():
    rec = _real_game()
    # VAN goalie faced exactly the shots COL's skaters took (this is what proves shotsTotal, not the
    # "SOG"-labelled shootout column, is what we read); COL's goalies faced one fewer than VAN's 26
    # because VAN's 8th goal was into an empty net (no goalie to shoot at).
    assert rec["teams"][COL]["sog"] == 30.0 and rec["teams"][VAN]["sa"] == 30.0
    assert rec["teams"][VAN]["sog"] == 26.0 and rec["teams"][COL]["sa"] == 25.0


def test_real_summary_individual_lines():
    rec = _real_game()
    hat_trick = rec["players"][3899979]                      # VAN RW: 3 G, 1 A, 4 S
    assert (hat_trick["g"], hat_trick["a"], hat_trick["pts"], hat_trick["sog"]) == (3.0, 1.0, 4.0, 4.0)
    assert hat_trick["toi"] == pytest.approx(18 + 57 / 60)
    volume = rec["players"][3041969]                         # COL C: 1 G, 7 S, 24:21
    assert (volume["g"], volume["sog"], volume["blk"]) == (1.0, 7.0, 0.0)
    d_man = rec["players"][3114995]                          # VAN D: 1 G, 2 A, 1 S, 3 BS
    assert (d_man["pos"], d_man["pts"], d_man["blk"], d_man["sog"]) == ("D", 3.0, 3.0, 1.0)


def test_real_summary_goalie_of_record_when_the_starter_is_pulled():
    rec = _real_game()
    starter, relief = rec["players"][3904177], rec["players"][5622]   # 35:21 then 22:24
    assert starter["gs"] is True and relief["gs"] is False           # both cleared 20 min; only one "starts"
    assert (starter["saves"], starter["sa"], starter["ga"]) == (13.0, 19.0, 6.0)
    assert rec["players"][4341584]["gs"] is True                     # VAN's full-60 goalie


# ------------------------------------------------------------------- get_game caching
def test_get_game_caches_finished_games_only(monkeypatch):
    calls = []
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: calls.append(params["event"]) or _summary(True))
    assert E.get_game("1")["final"] is True
    assert E.get_game("1")["final"] is True
    assert calls == ["1"]                              # second call served from cache

    E._game_cache.clear()
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: calls.append(params["event"]) or _summary(False))
    E.get_game("2")
    E.get_game("2")
    assert calls.count("2") == 2                       # a live game is re-fetched, never frozen


def test_get_game_remembers_a_failed_fetch_for_the_build(monkeypatch):
    calls = []
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: calls.append(1) or None)
    assert E.get_game("9") is None
    assert E.get_game("9") is None
    assert len(calls) == 1


def test_get_game_uses_the_summary_endpoint(monkeypatch):
    seen = {}
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: seen.update(url=url, params=params) or _summary())
    E.get_game("401803539")
    assert seen["url"] == "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/summary"
    assert seen["params"] == {"event": "401803539"}


# ------------------------------------------------------------------- schedule
def _event(eid, date, home=(COL, "Colorado Avalanche", "COL"), away=(VAN, "Vancouver Canucks", "VAN"),
           state="pre", desc="Scheduled"):
    def comp(t, ha):
        return {"homeAway": ha, "team": {"id": str(t[0]), "displayName": t[1], "abbreviation": t[2],
                                         "logo": f"https://logo/{t[2]}.png"}}
    return {"id": eid, "date": date, "competitions": [{
        "status": {"type": {"state": state, "description": desc}},
        "competitors": [comp(home, "home"), comp(away, "away")]}]}


def test_get_schedule_parses_and_narrows_to_the_eastern_day(monkeypatch):
    by_date = {
        "20261021": {"events": [_event("A", "2026-10-21T23:00Z")]},           # 7 PM ET on the 21st
        "20261022": {"events": [_event("B", "2026-10-23T02:30Z",              # 10:30 PM ET on the 22nd
                                       home=(2, "Boston Bruins", "BOS"), away=(3, "Buffalo Sabres", "BUF")),
                                _event("A", "2026-10-21T23:00Z")]},           # duplicate id, other query
        "20261020": {"events": [_event("C", "2026-10-20T23:00Z", home=(4, "X", "X"), away=(5, "Y", "Y"))]},
    }
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: by_date.get(params["dates"], {"events": []}))
    games = E.get_schedule("2026-10-21")
    assert [g["gameId"] for g in games] == ["A"]
    g = games[0]
    assert (g["home_id"], g["home_abbr"], g["away_id"], g["away_name"]) == (COL, "COL", VAN, "Vancouver Canucks")
    assert g["status_state"] == "pre" and g["home_logo"].endswith("COL.png")
    # the 10:30 PM ET puck drop is the NEXT UTC day but still the 22nd in Eastern time
    assert [g["gameId"] for g in E.get_schedule("2026-10-22")] == ["B"]


def test_get_schedule_empty_when_every_fetch_fails(monkeypatch):
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    assert E.get_schedule("2026-10-21") == []


def test_get_schedule_makes_three_single_date_queries_not_a_range(monkeypatch):
    seen = []
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: seen.append(params["dates"]) or {"events": []})
    E.get_schedule("2026-10-31")
    assert seen == ["20261030", "20261031", "20261101"]   # month boundary handled; no START-END range


def test_get_schedule_skips_a_malformed_event(monkeypatch):
    bad = {"id": "Z", "date": "2026-10-21T23:00Z", "competitions": [{"competitors": [{"homeAway": "home"}]}]}
    monkeypatch.setattr(E, "_get_json", lambda url, params=None:
                        {"events": [bad, _event("A", "2026-10-21T23:00Z")]} if params["dates"] == "20261021"
                        else {"events": []})
    assert [g["gameId"] for g in E.get_schedule("2026-10-21")] == ["A"]


def test_team_abbrs_from_meta():
    assert E.team_abbrs_from_meta([{"home_id": 1, "home_abbr": "COL", "away_id": 2, "away_abbr": "VAN"}]) \
        == {1: "COL", 2: "VAN"}


# ------------------------------------------------------------------- rosters
def test_get_team_roster_handles_the_position_grouped_shape(monkeypatch):
    payload = {"athletes": [
        {"position": "Centers", "items": [{"id": "10", "displayName": "Nathan MacKinnon",
                                           "position": {"abbreviation": "C"}}]},
        {"position": "Goalies", "items": [{"id": "95", "displayName": "Colorado Goalie",
                                           "position": {"abbreviation": "G"}},
                                          {"id": "bad", "displayName": "Broken Id"},
                                          {"displayName": "No Id"}]},
    ]}
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: payload)
    roster = E.get_team_roster(COL)
    assert roster == [{"id": 10, "name": "Nathan MacKinnon", "pos": "C", "is_goalie": False},
                      {"id": 95, "name": "Colorado Goalie", "pos": "G", "is_goalie": True}]


def test_get_team_roster_handles_a_flat_list_and_a_failed_fetch(monkeypatch):
    monkeypatch.setattr(E, "_get_json", lambda url, params=None:
                        {"athletes": [{"id": "5", "displayName": "Flat Guy", "position": {"abbreviation": "D"}}]})
    assert E.get_team_roster(1)[0]["id"] == 5
    monkeypatch.setattr(E, "_get_json", lambda url, params=None: None)
    assert E.get_team_roster(1) == []


# ------------------------------------------------------------------- recent games / logs
def _gi(gid, date="2026-10-15T00:00Z", opp_id=VAN, opp="Vancouver Canucks", score="4", opp_score="2"):
    return {"gameId": gid, "date": date, "opp_id": opp_id, "opp_name": opp, "score": score, "opp_score": opp_score}


def test_get_team_recent_game_ids_goes_through_the_shared_window_scan(monkeypatch):
    captured = {}

    def fake(team_id, before_date, site_api, fetch, diag, n=10, days_back=45, diag_seen=None):
        captured.update(site_api=site_api, n=n, days_back=days_back, team=team_id)
        return [_gi("1")]
    monkeypatch.setattr(BB, "get_team_recent_game_ids", fake)
    out = E.get_team_recent_game_ids(COL, "2026-10-21", 7, days_back=30)
    assert out == [_gi("1")]
    assert captured == {"site_api": E.SITE_API, "n": 7, "days_back": 30, "team": COL}
    assert "hockey/nhl" in captured["site_api"]


def test_player_log_skater_reads_pure_lookups(monkeypatch):
    monkeypatch.setattr(E, "get_game", lambda gid: {"1": _game("1", mackinnon_goals=2.0, mackinnon_sog=6.0),
                                                    "2": _game("2", mackinnon_goals=0.0, mackinnon_sog=2.0)}[gid])
    log = E.player_log_from_games(10, [_gi("1"), _gi("2")], is_goalie=False)
    assert [(g["goals"], g["sog"], g["pts"], g["ast"]) for g in log] == [(2.0, 6.0, 3.0, 1.0), (0.0, 2.0, 1.0, 1.0)]
    assert log[0]["toi"] == log[0]["min"] == 20.0 and log[0]["opp"] == "Vancouver Canucks"


def test_player_log_skips_games_the_player_missed_and_honors_last_n(monkeypatch):
    monkeypatch.setattr(E, "get_game", lambda gid: _game(gid) if gid != "2" else
                        {"final": True, "players": {}, "teams": {}})
    log = E.player_log_from_games(10, [_gi("1"), _gi("2"), _gi("3"), _gi("4")], False, last_n=2)
    assert len(log) == 2


def test_player_log_goalie_only_counts_starts(monkeypatch):
    monkeypatch.setattr(E, "get_game", lambda gid: _game(gid))
    starter = E.player_log_from_games(95, [_gi("1"), _gi("2")], is_goalie=True)
    relief = E.player_log_from_games(96, [_gi("1"), _gi("2")], is_goalie=True)
    assert len(starter) == 2 and starter[0]["saves"] == 25.0 and starter[0]["sa"] == 27.0
    assert relief == []                                # a relief period is not a start
    # a skater id asked for as a goalie (or vice versa) yields nothing rather than a wrong shape
    assert E.player_log_from_games(10, [_gi("1")], is_goalie=True) == []
    assert E.player_log_from_games(95, [_gi("1")], is_goalie=False) == []


def test_get_player_recent_games_needs_team_and_date():
    assert E.get_player_recent_games(10) == []
    assert E.get_player_recent_games(10, team_id=COL) == []


def test_get_player_recent_games_end_to_end(monkeypatch):
    monkeypatch.setattr(E, "get_team_recent_game_ids", lambda *a, **k: [_gi("1"), _gi("2")])
    monkeypatch.setattr(E, "get_game", lambda gid: _game(gid))
    assert len(E.get_player_recent_games(10, team_id=COL, before_date="2026-10-21")) == 2


# ------------------------------------------------------------------- team trends
def test_team_recent_stats_average_own_and_opponent_totals(monkeypatch):
    monkeypatch.setattr(E, "get_team_recent_game_ids", lambda *a, **k: [_gi("1"), _gi("2")])
    monkeypatch.setattr(E, "get_game", lambda gid: _game(gid, mackinnon_goals=1.0 if gid == "1" else 3.0))
    own = E.get_team_recent_scored_stats(COL, "2026-10-21")
    allowed = E.get_team_recent_allowed_stats(COL, "2026-10-21")
    assert own["goals"] == pytest.approx(2.0)          # COL's own goals: (1 + 3) / 2
    assert allowed["goals"] == 0.0 and allowed["sog"] == 2.0   # what the opponent (VAN) put up


def test_team_recent_stats_zero_not_fabricated_when_no_games(monkeypatch):
    monkeypatch.setattr(E, "get_team_recent_game_ids", lambda *a, **k: [])
    assert set(E.get_team_recent_scored_stats(COL, "2026-10-21").values()) == {0.0}


def test_team_recent_scoring_reads_the_scoreboard_scores_without_any_boxscore(monkeypatch):
    monkeypatch.setattr(E, "get_team_recent_game_ids", lambda *a, **k: [
        _gi("1", score="5", opp_score="2"), _gi("2", score="1", opp_score="4"), _gi("3", score=None, opp_score="x")])
    monkeypatch.setattr(E, "get_game", lambda gid: pytest.fail("scoring trend must not download boxscores"))
    out = E.get_team_recent_scoring(COL, "2026-10-21")
    assert out == {"goals_for": 3.0, "goals_against": 3.0, "games": 2}   # the malformed row is skipped


def test_team_recent_scoring_empty_is_games_zero(monkeypatch):
    monkeypatch.setattr(E, "get_team_recent_game_ids", lambda *a, **k: [])
    assert E.get_team_recent_scoring(COL, "2026-10-21")["games"] == 0


def test_rest_and_injuries_are_wired_to_the_nhl_site_api(monkeypatch):
    seen = {}
    monkeypatch.setattr(BB, "get_team_rest_info",
                        lambda tid, bd, site_api, fetch, diag, days_back=10, diag_seen=None:
                        seen.update(rest=site_api) or {"rest_days": 1})
    monkeypatch.setattr(BB, "get_team_injuries",
                        lambda abbr, site_api, fetch, diag, diag_seen=None: seen.update(inj=site_api) or [])
    E.get_team_rest_info(COL, "2026-10-21")
    E.get_team_injuries("COL")
    assert seen["rest"] == seen["inj"] == E.SITE_API


# ------------------------------------------------------------------- results (grading contract)
def test_get_player_results_final_games_only_with_grading_keys(monkeypatch):
    monkeypatch.setattr(E, "get_schedule", lambda d: [{"gameId": "1"}, {"gameId": "2"}])
    monkeypatch.setattr(E, "get_game", lambda gid: _game(gid, mackinnon_goals=2.0) if gid == "1"
                        else _game(gid, final=False))
    res = E.get_player_results("2026-10-21")
    assert res[10] == {"pts": 3.0, "ast": 1.0, "goals": 2.0, "sog": 4.0, "blk": 0.0}
    assert res[95] == {"saves": 25.0, "sa": 27.0, "ga": 2.0}
    assert all(isinstance(k, int) for k in res)


def test_results_grade_through_retro_for_every_nhl_market():
    import retro
    res = {10: {"pts": 3.0, "ast": 1.0, "goals": 2.0, "sog": 4.0, "blk": 0.0}, 95: {"saves": 25.0}}
    assert retro.grade_play("Goals", "Over", 0.5, res[10]) is True
    assert retro.grade_play("Shots on Goal", "Over", 3.5, res[10]) is True
    assert retro.grade_play("Shots on Goal", "Under", 3.5, res[10]) is False
    assert retro.grade_play("Blocked Shots", "Over", 0.5, res[10]) is False
    assert retro.grade_play("Points", "Over", 2.5, res[10]) is True
    assert retro.grade_play("Assists", "Over", 0.5, res[10]) is True
    assert retro.grade_play("Saves", "Over", 24.5, res[95]) is True
    # a player who has no recorded actual is never graded, never guessed
    assert retro.grade_play("Goals", "Over", 0.5, None) is None


# ------------------------------------------------------------------- pure row logic
def _log(toi=20.0, pts=1.0, ast=0.5, goals=0.5, sog=3.0, blk=1.0, saves=0.0):
    return {"pts": pts, "ast": ast, "goals": goals, "sog": sog, "blk": blk, "saves": saves,
            "toi": toi, "min": toi, "opp": "X", "date": "d"}


def test_player_row_builds_a_skater_row():
    player = {"id": 10, "name": "Nathan MacKinnon", "pos": "C", "is_goalie": False}
    row = E.player_row(player, "Colorado Avalanche", "Vancouver Canucks", "VAN @ COL", "2026-10-21T23:00Z",
                       [_log(20.0, sog=4.0), _log(22.0, sog=2.0)], opp_id=VAN, team_id=COL)
    assert row["Role"] == "skater" and row["AvgTOI"] == row["AvgMin"] == 21.0 and row["SOG"] == 3.0
    assert row["_pid"] == 10 and row["_opp_id"] == VAN and row["_team_id"] == COL and len(row["_game_log"]) == 2


def test_player_row_drops_a_skater_below_the_toi_bar_and_a_goalie_never_is():
    skater = {"id": 2, "name": "Depth", "pos": "LW", "is_goalie": False}
    assert E.player_row(skater, "T", "O", "g", None, [_log(toi=8.0)]) is None
    goalie = {"id": 95, "name": "G", "pos": "G", "is_goalie": True}
    row = E.player_row(goalie, "T", "O", "g", None, [_log(toi=60.0, saves=27.0)])
    assert row["Role"] == "goalie" and row["SV"] == 27.0
    assert E.player_row(skater, "T", "O", "g", None, []) is None    # no log -> no row


# ------------------------------------------------------------------- build_slate orchestration
def _wire_slate(monkeypatch, starter_ids_in_last5=(95,)):
    monkeypatch.setattr(E, "get_schedule", lambda d: [{
        "gameId": "G0", "game_date": "2026-10-21T23:00Z", "status_state": "pre",
        "home_id": COL, "home_name": "Colorado Avalanche", "home_abbr": "COL",
        "away_id": VAN, "away_name": "Vancouver Canucks", "away_abbr": "VAN"}])
    rosters = {COL: [{"id": 10, "name": "Nathan MacKinnon", "pos": "C", "is_goalie": False},
                     {"id": 11, "name": "Prospect No Games", "pos": "C", "is_goalie": False},
                     {"id": 95, "name": "Colorado Goalie", "pos": "G", "is_goalie": True},
                     {"id": 96, "name": "Never Started", "pos": "G", "is_goalie": True}],
               VAN: [{"id": 1, "name": "Elias Pettersson", "pos": "C", "is_goalie": False}]}
    monkeypatch.setattr(E, "get_team_roster", lambda tid: rosters[tid])
    monkeypatch.setattr(E, "get_team_recent_game_ids",
                        lambda tid, d, n=10, days_back=45: [_gi("R1"), _gi("R2")])
    monkeypatch.setattr(E, "get_game", lambda gid: _game(gid))


def test_build_slate_assembles_rows_and_meta(monkeypatch):
    _wire_slate(monkeypatch)
    rows, meta = E.build_slate("2026-10-21")
    by_name = {r["Player"]: r for r in rows}
    assert set(by_name) == {"Nathan MacKinnon", "Colorado Goalie", "Elias Pettersson"}
    assert by_name["Nathan MacKinnon"]["Role"] == "skater" and by_name["Colorado Goalie"]["Role"] == "goalie"
    assert by_name["Nathan MacKinnon"]["Opp"] == "Vancouver Canucks" and by_name["Elias Pettersson"]["Opp"] == "Colorado Avalanche"
    assert meta == [{"label": "Vancouver Canucks @ Colorado Avalanche", "away_name": "Vancouver Canucks",
                     "home_name": "Colorado Avalanche", "game_date": "2026-10-21T23:00Z", "game_id": "G0",
                     "home_id": COL, "home_abbr": "COL", "away_id": VAN, "away_abbr": "VAN"}]


def test_build_slate_a_goalie_needs_a_recent_start(monkeypatch):
    _wire_slate(monkeypatch)
    rows, _ = E.build_slate("2026-10-21")
    assert "Never Started" not in {r["Player"] for r in rows}      # no start in the last 5 games


def test_build_slate_empty_when_no_games(monkeypatch):
    monkeypatch.setattr(E, "get_schedule", lambda d: [])
    assert E.build_slate("2026-07-04") == ([], [])


def test_build_slate_downloads_each_distinct_game_once(monkeypatch):
    _wire_slate(monkeypatch)
    fetched = []
    monkeypatch.setattr(E, "get_game", lambda gid: fetched.append(gid) or _game(gid))
    E.build_slate("2026-10-21")
    # both teams share the same two recent games -> each is prefetched exactly once
    assert sorted(g for g in fetched[:2]) == ["R1", "R2"]
    assert fetched[:2].count("R1") == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
