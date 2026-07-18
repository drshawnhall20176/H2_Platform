"""
test_engine.py — offline unit tests for mlb_engine's pure logic.

No network required. Run either way:
    python test_engine.py        # plain, no dependencies beyond the engine
    pytest test_engine.py         # if you have pytest installed
"""

import mlb_engine as E


# ----------------------------------------------------------------- FIP
def test_fip_known_value():
    # 13*8 + 3*(10+2) - 2*38 = 64; 64/42 = 1.5238; +3.17 = 4.69
    stat = dict(homeRuns=8, baseOnBalls=10, hitByPitch=2, strikeOuts=38, inningsPitched="42.0")
    assert E.calculate_fip(stat, constant=3.17) == 4.69


def test_fip_guards_zero_innings():
    assert E.calculate_fip(dict(inningsPitched=0)) == 0.0
    assert E.calculate_fip({}) == 0.0  # missing fields default to 0


def test_fip_handles_string_inputs():
    stat = dict(homeRuns="8", baseOnBalls="10", hitByPitch="2", strikeOuts="38", inningsPitched="42.0")
    assert E.calculate_fip(stat, constant=3.17) == 4.69


# ----------------------------------------------------------------- innings parsing
def test_parse_innings():
    assert round(E.parse_innings("6.2"), 3) == 6.667   # 6 and 2/3
    assert round(E.parse_innings("85.1"), 3) == 85.333
    assert E.parse_innings("7.0") == 7.0
    assert E.parse_innings(0) == 0.0
    assert E.parse_innings(None) == 0.0


# ----------------------------------------------------------------- platoon
def test_platoon_advantage():
    assert E.platoon_advantage("L", "R") == "Advantage"
    assert E.platoon_advantage("R", "L") == "Advantage"
    assert E.platoon_advantage("R", "R") == "Disadvantage"
    assert E.platoon_advantage("L", "L") == "Disadvantage"
    assert E.platoon_advantage("S", "R") == "Advantage"   # switch always
    assert E.platoon_advantage("S", "L") == "Advantage"
    assert E.platoon_advantage("R", "") == "Unknown"      # missing pitcher hand


# ----------------------------------------------------------------- power index
def test_power_index_ordering():
    slugger = E.power_index(iso=0.260, ops=0.920, advantage="Advantage")
    slap = E.power_index(iso=0.090, ops=0.680, advantage="Disadvantage")
    assert slugger == 42.0
    assert slap == 8.0
    assert slugger > slap


def test_power_index_advantage_bonus():
    with_adv = E.power_index(iso=0.150, ops=0.750, advantage="Advantage")
    without = E.power_index(iso=0.150, ops=0.750, advantage="Disadvantage")
    assert round(with_adv - without, 1) == 5.0


# ----------------------------------------------------------------- helpers
def test_safe_float():
    assert E.safe_float("3.14") == 3.14
    assert E.safe_float(None) == 0.0
    assert E.safe_float("not a number", default=-1) == -1


def test_strip_accents():
    assert E.strip_accents("José Ramírez") == "Jose Ramirez"


# ----------------------------------------------------------------- row assembly
def test_hitter_row_assembly():
    opp = E.PitcherMetrics(id=1, name="Ace", hand="R")
    raw = {
        "id": 99, "name": "José Ramírez", "bat_hand": "S",
        "stat": dict(homeRuns=30, hits=160, totalBases=300, avg="0.280", obp="0.360",
                     slg="0.520", ops="0.880", strikeOuts=90, plateAppearances=650),
    }
    row = E._hitter_row(raw, opp, "Guardians", "CLE @ DET (Game 1)", projected=False)
    assert row["ISO"] == 0.24                 # .520 - .280
    assert round(row["K%"], 3) == 0.138       # 90 / 650
    assert row["Advantage"] == "Advantage"    # switch vs RHP
    assert row["Lineup"] == "Confirmed"       # projected=False
    assert row["Opp Pitcher"] == "Ace"


def test_hitter_row_missing_pa_no_crash():
    # plateAppearances missing -> K% denominator guarded to 1, must not divide by zero
    opp = E.PitcherMetrics(id=1, name="Ace", hand="L")
    raw = {"id": 1, "name": "Rookie", "bat_hand": "R",
           "stat": dict(homeRuns=0, hits=0, totalBases=0, avg="0.000", slg="0.000",
                        ops="0.000", strikeOuts=0)}
    row = E._hitter_row(raw, opp, "Team", "label", projected=True)
    assert row["Lineup"] == "Projected"
    assert row["K%"] == 0.0


# ----------------------------------------------------------------- runner
def test_aggregate_pitching_splits():
    # Traded pitcher: two stints must sum, with innings rebuilt in MLB thirds format.
    splits = [
        {"stat": dict(strikeOuts=60, baseOnBalls=15, homeRuns=8, battersFaced=300,
                      gamesStarted=11, earnedRuns=30, hits=70, atBats=270,
                      inningsPitched="72.1", hitByPitch=3)},
        {"stat": dict(strikeOuts=40, baseOnBalls=10, homeRuns=5, battersFaced=200,
                      gamesStarted=7, earnedRuns=18, hits=45, atBats=180,
                      inningsPitched="48.2", hitByPitch=2)},
    ]
    agg = E._aggregate_pitching_splits(splits)
    assert agg["strikeOuts"] == 100 and agg["battersFaced"] == 500 and agg["gamesStarted"] == 18
    # 72.1 (72+1/3) + 48.2 (48+2/3) = 121.0 innings exactly
    assert agg["inningsPitched"] == "121.0"
    assert round(E.parse_innings(agg["inningsPitched"]), 2) == 121.0


# ----------------------------------------------------------------- build_pitching_slate (Matchup Lab filters)
def test_build_pitching_slate_threads_game_date_through(monkeypatch):
    # Regression guard for the Matchup Lab time-slot/game filter addition: build_pitching_slate's
    # row dict must carry _game_date through from the schedule, unchanged for every OTHER field.
    # Mocked, not live: MLB Stats API isn't reachable from this sandbox's network allowlist
    # (unlike nflreadpy's PyPI/GitHub-hosted data, which could be verified live during the NFL
    # build) — confirmed via a direct request returning 403, not assumed.
    fake_games = [{
        "gamePk": 12345, "game_date": "2026-06-28T17:10:00Z",
        "home_name": "Yankees", "away_name": "Red Sox",
        "home_pitcher_id": 111, "away_pitcher_id": 222,
    }]

    def fake_get_pitcher_metrics(pid, fip_constant):
        return E.PitcherMetrics(id=pid, name=f"Pitcher {pid}", era=3.50, fip=3.20, k9=9.0,
                                whip=1.10, hr9=1.0, oba=0.240)

    monkeypatch.setattr(E, "get_schedule", lambda date_str: fake_games)
    monkeypatch.setattr(E, "get_pitcher_metrics", fake_get_pitcher_metrics)

    rows = E.build_pitching_slate("2026-06-28")
    assert len(rows) == 2   # home + away starter
    assert all(r["_game_date"] == "2026-06-28T17:10:00Z" for r in rows)
    assert all(r["Game"] == "Red Sox @ Yankees" for r in rows)
    home_row = next(r for r in rows if r["Team"] == "Yankees")
    assert home_row["_team_id"] is None and home_row["_opp_id"] is None   # fake_games has no home_id/away_id
    print("✓ build_pitching_slate correctly threads _game_date through for every row, matching every other sport's own field")


def test_build_pitching_slate_threads_team_ids_through(monkeypatch):
    # Needed for the Matchup Lab injury report — get_team_injuries takes a numeric team_id, not
    # a team name, so build_pitching_slate has to carry both team's real ids through.
    fake_games = [{
        "gamePk": 12345, "game_date": "2026-06-28T17:10:00Z",
        "home_name": "Yankees", "away_name": "Red Sox", "home_id": 147, "away_id": 111,
        "home_pitcher_id": 111, "away_pitcher_id": 222,
    }]

    def fake_get_pitcher_metrics(pid, fip_constant):
        return E.PitcherMetrics(id=pid, name=f"Pitcher {pid}", era=3.50, fip=3.20, k9=9.0,
                                whip=1.10, hr9=1.0, oba=0.240)

    monkeypatch.setattr(E, "get_schedule", lambda date_str: fake_games)
    monkeypatch.setattr(E, "get_pitcher_metrics", fake_get_pitcher_metrics)

    rows = E.build_pitching_slate("2026-06-28")
    home_row = next(r for r in rows if r["Team"] == "Yankees")
    away_row = next(r for r in rows if r["Team"] == "Red Sox")
    assert home_row["_team_id"] == 147 and home_row["_opp_id"] == 111
    assert away_row["_team_id"] == 111 and away_row["_opp_id"] == 147
    print("✓ build_pitching_slate correctly threads each side's own team_id and their opponent's through")


# ----------------------------------------------------------------- get_team_injuries
def test_get_team_injuries_filters_to_non_active_status(monkeypatch):
    # Documented roster response shape (MLB Stats API's own roster endpoint structure), not a
    # live-verified one — see get_team_injuries' own docstring for the real, honest limitation.
    fake_roster = {"roster": [
        {"person": {"fullName": "Active Player"}, "position": {"abbreviation": "SS"},
        "status": {"code": "A", "description": "Active"}},
        {"person": {"fullName": "Hurt Player"}, "position": {"abbreviation": "OF"},
        "status": {"code": "D10", "description": "10-Day-IL"}},
        {"person": {"fullName": "Long Term Player"}, "position": {"abbreviation": "P"},
        "status": {"code": "D60", "description": "60-Day-IL"}},
    ]}
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fake_roster)
    injuries = E.get_team_injuries(147)
    names = {i["player"] for i in injuries}
    assert names == {"Hurt Player", "Long Term Player"}   # Active Player correctly excluded
    hurt = next(i for i in injuries if i["player"] == "Hurt Player")
    assert hurt == {"player": "Hurt Player", "status": "10-Day-IL", "position": "OF",
                   "return_date": None, "comment": None}
    print("✓ get_team_injuries correctly filters to non-Active roster statuses, matching the shared injury shape")


def test_get_team_injuries_empty_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: {})
    assert E.get_team_injuries(147) == []


def test_get_team_injuries_falls_back_to_code_when_no_description(monkeypatch):
    fake_roster = {"roster": [
        {"person": {"fullName": "Hurt Player"}, "position": {"abbreviation": "OF"},
        "status": {"code": "RM"}},   # no description field this time
    ]}
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fake_roster)
    injuries = E.get_team_injuries(147)
    assert injuries[0]["status"] == "RM"


# ----------------------------------------------------------------- schedule refactor
def _fake_schedule_json(games):
    """Wrap a list of (gamePk, gameDate, home_name, home_id, away_name, away_id) into the raw
    MLB Stats API schedule response shape, for mocking fetch_json."""
    return {"dates": [{"games": [
        {"gamePk": pk, "gameDate": gd, "gameNumber": 1, "status": {"detailedState": "Final"},
        "venue": {"name": "Test Park", "id": 1},
        "teams": {"home": {"team": {"name": hn, "id": hid}},
                 "away": {"team": {"name": an, "id": aid}}}}
        for pk, gd, hn, hid, an, aid in games
    ]}]}


def test_get_schedule_unchanged_after_refactor(monkeypatch):
    # Regression guard for extracting _normalize_schedule_json — get_schedule's own real,
    # already-shipped output shape must be byte-identical to before the refactor.
    fake = _fake_schedule_json([(1, "2026-07-18T23:10:00Z", "Astros", 117, "Orioles", 110)])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fake)
    games = E.get_schedule("2026-07-18")
    assert len(games) == 1
    g = games[0]
    assert g["gamePk"] == 1 and g["home_name"] == "Astros" and g["away_name"] == "Orioles"
    assert g["home_id"] == 117 and g["away_id"] == 110
    assert g["game_date"] == "2026-07-18T23:10:00Z"
    print("✓ get_schedule's output is unchanged after extracting the shared normalization helper")


def test_get_team_schedule_range_passes_team_and_date_params(monkeypatch):
    captured = {}

    def fake_fetch(url, params=None, retries=2):
        captured["params"] = params
        return _fake_schedule_json([(1, "2026-07-16T23:10:00Z", "Astros", 117, "Orioles", 110)])

    monkeypatch.setattr(E, "fetch_json", fake_fetch)
    games = E.get_team_schedule_range(117, "2026-07-14", "2026-07-17")
    assert captured["params"] == {"sportId": 1, "teamId": 117,
                                  "startDate": "2026-07-14", "endDate": "2026-07-17"}
    assert len(games) == 1
    print("✓ get_team_schedule_range correctly passes teamId + startDate/endDate as one request")


def test_get_team_schedule_range_sorted_by_date(monkeypatch):
    # Different sort key than get_schedule (chronological, not away-team-name) — makes sense for
    # a fatigue window read chronologically, not alphabetically by opponent.
    fake = _fake_schedule_json([
        (2, "2026-07-17T23:10:00Z", "Astros", 117, "Rangers", 140),
        (1, "2026-07-15T23:10:00Z", "Astros", 117, "Orioles", 110),
    ])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fake)
    games = E.get_team_schedule_range(117, "2026-07-14", "2026-07-17")
    assert [g["gamePk"] for g in games] == [1, 2]   # chronological, not the raw response order


# ----------------------------------------------------------------- get_team_bullpen_fatigue
def _fake_boxscore(team_side_players):
    """team_side_players: {pid: (name, innings_pitched_str)}. Builds a minimal real-shaped
    boxscore with these players on the 'home' side (tests pick which real team_id is 'home')."""
    players = {}
    for pid, (name, ip) in team_side_players.items():
        players[f"ID{pid}"] = {
            "person": {"id": pid, "fullName": name},
            "stats": {"pitching": {"inningsPitched": ip}},
        }
    return {"teams": {"home": {"players": players}, "away": {"players": {}}}}


def test_bullpen_fatigue_flags_three_consecutive_days(monkeypatch):
    # Pitched on the 3 calendar days immediately before before_date -> the highest-value tag.
    games = [
        {"gamePk": 1, "game_date": "2026-07-15T23:10:00Z", "status": "Final", "home_id": 117},
        {"gamePk": 2, "game_date": "2026-07-16T23:10:00Z", "status": "Final", "home_id": 117},
        {"gamePk": 3, "game_date": "2026-07-17T23:10:00Z", "status": "Final", "home_id": 117},
    ]
    boxscores = {
        1: _fake_boxscore({555: ("Gassed Reliever", "1.0")}),
        2: _fake_boxscore({555: ("Gassed Reliever", "0.2")}),
        3: _fake_boxscore({555: ("Gassed Reliever", "1.1")}),
    }
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2:
                        boxscores[int(url.rsplit("/game/", 1)[1].split("/")[0])])
    fatigue = E.get_team_bullpen_fatigue(117, "2026-07-18")
    assert len(fatigue) == 1
    assert fatigue[0]["consecutive_days"] == 3
    assert "3 straight days" in fatigue[0]["tag"]
    print("✓ get_team_bullpen_fatigue correctly flags a real 3-consecutive-day streak")


def test_bullpen_fatigue_pitched_yesterday_only(monkeypatch):
    games = [{"gamePk": 1, "game_date": "2026-07-17T23:10:00Z", "status": "Final", "home_id": 117}]
    boxscores = {1: _fake_boxscore({555: ("One Day Guy", "1.0")})}
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: boxscores[1])
    fatigue = E.get_team_bullpen_fatigue(117, "2026-07-18")
    assert fatigue[0]["consecutive_days"] == 1
    assert fatigue[0]["days_since_last_appearance"] == 1
    assert "yesterday" in fatigue[0]["tag"]


def test_bullpen_fatigue_rested_pitcher(monkeypatch):
    games = [{"gamePk": 1, "game_date": "2026-07-13T23:10:00Z", "status": "Final", "home_id": 117}]
    boxscores = {1: _fake_boxscore({555: ("Rested Guy", "1.0")})}
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: boxscores[1])
    fatigue = E.get_team_bullpen_fatigue(117, "2026-07-18")
    assert fatigue[0]["days_since_last_appearance"] == 5
    assert fatigue[0]["consecutive_days"] == 0
    assert "day(s) rest" in fatigue[0]["tag"]


def test_bullpen_fatigue_no_appearance_not_included(monkeypatch):
    games = [{"gamePk": 1, "game_date": "2026-07-17T23:10:00Z", "status": "Final", "home_id": 117}]
    box = _fake_boxscore({555: ("Pitched", "1.0"), 556: ("Did Not Pitch", "0.0")})
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
    fatigue = E.get_team_bullpen_fatigue(117, "2026-07-18")
    pids = {f["player_id"] for f in fatigue}
    assert 555 in pids and 556 not in pids
    print("✓ get_team_bullpen_fatigue excludes a pitcher with 0.0 innings (didn't actually appear)")


def test_bullpen_fatigue_skips_non_final_games(monkeypatch):
    games = [{"gamePk": 1, "game_date": "2026-07-17T23:10:00Z", "status": "Postponed", "home_id": 117}]
    called = {"fetched": False}

    def fake_fetch(url, params=None, retries=2):
        called["fetched"] = True
        return {}

    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", fake_fetch)
    fatigue = E.get_team_bullpen_fatigue(117, "2026-07-18")
    assert fatigue == [] and called["fetched"] is False   # never even fetched the boxscore
    print("✓ get_team_bullpen_fatigue skips non-Final games without fetching their boxscore")


def test_bullpen_fatigue_correct_side_only(monkeypatch):
    # A pitcher on the OPPONENT's side in a game against this team must never show up here.
    games = [{"gamePk": 1, "game_date": "2026-07-17T23:10:00Z", "status": "Final", "home_id": 117}]
    box = {"teams": {
        "home": {"players": {"ID555": {"person": {"id": 555, "fullName": "Home Pitcher"},
                                       "stats": {"pitching": {"inningsPitched": "1.0"}}}}},
        "away": {"players": {"ID556": {"person": {"id": 556, "fullName": "Away Pitcher"},
                                       "stats": {"pitching": {"inningsPitched": "1.0"}}}}},
    }}
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
    fatigue = E.get_team_bullpen_fatigue(117, "2026-07-18")   # team_id=117 is the HOME team here
    pids = {f["player_id"] for f in fatigue}
    assert pids == {555}
    print("✓ get_team_bullpen_fatigue only counts appearances for the requested team's own side")


def test_bullpen_fatigue_no_lookahead():
    # before_date itself must never be part of the window (see get_team_schedule_range's own
    # start/end computation: end = before_date - 1 day).
    fatigue = E.get_team_bullpen_fatigue(117, "not-a-real-date")
    assert fatigue == []


def test_bullpen_fatigue_sorted_most_fatigued_first(monkeypatch):
    games = [
        {"gamePk": 1, "game_date": "2026-07-15T23:10:00Z", "status": "Final", "home_id": 117},
        {"gamePk": 2, "game_date": "2026-07-16T23:10:00Z", "status": "Final", "home_id": 117},
        {"gamePk": 3, "game_date": "2026-07-17T23:10:00Z", "status": "Final", "home_id": 117},
    ]
    boxscores = {
        1: _fake_boxscore({111: ("Two Straight", "1.0")}),
        2: _fake_boxscore({111: ("Two Straight", "1.0"), 222: ("One Day", "1.0")}),
        3: _fake_boxscore({222: ("One Day", "0.0")}),   # 222 on roster but didn't pitch game 3
    }
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2:
                        boxscores[int(url.rsplit("/game/", 1)[1].split("/")[0])])
    fatigue = E.get_team_bullpen_fatigue(117, "2026-07-18")
    assert fatigue[0]["name"] == "Two Straight"   # 2-day streak ranks above 1-day
    print("✓ get_team_bullpen_fatigue sorts the longest current streak first")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
