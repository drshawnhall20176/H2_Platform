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
    row = E._hitter_row(raw, opp, "Guardians", "CLE @ DET (Game 1)", projected=False, opp_team_id=116)
    assert row["ISO"] == 0.24                 # .520 - .280
    assert round(row["K%"], 3) == 0.138       # 90 / 650
    assert row["Advantage"] == "Advantage"    # switch vs RHP
    assert row["Lineup"] == "Confirmed"       # projected=False
    assert row["Opp Pitcher"] == "Ace"
    assert row["_opp_id"] == 116               # the opposing TEAM's id, not the pitcher's own player id


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


# ----------------------------------------------------------------- pair_pitching_slate_by_game
def _pitching_row(team, opp, game_label, game_date=None):
    return {"Pitcher": f"{team} SP", "Team": team, "Opponent": opp, "Game": game_label,
           "_game_date": game_date}


def test_pair_pitching_slate_by_game_pairs_home_and_away():
    rows = [_pitching_row("Yankees", "Red Sox", "Red Sox @ Yankees"),
           _pitching_row("Red Sox", "Yankees", "Red Sox @ Yankees")]
    games = E.pair_pitching_slate_by_game(rows)
    assert len(games) == 1
    assert games[0]["home"]["Team"] == "Yankees" and games[0]["away"]["Team"] == "Red Sox"
    print("✓ pair_pitching_slate_by_game correctly sorts each side into home/away using the label's own away-part match")


def test_pair_pitching_slate_by_game_drops_unpaired_rows():
    # A row whose partner never came back (e.g. a data gap) should be dropped entirely, not
    # shown as a half-built game with one side missing.
    rows = [_pitching_row("Yankees", "Red Sox", "Red Sox @ Yankees")]   # away side missing
    assert E.pair_pitching_slate_by_game(rows) == []
    print("✓ pair_pitching_slate_by_game drops a game where only one side's row is present")


def test_pair_pitching_slate_by_game_multiple_games():
    rows = [
        _pitching_row("Yankees", "Red Sox", "Red Sox @ Yankees"),
        _pitching_row("Red Sox", "Yankees", "Red Sox @ Yankees"),
        _pitching_row("Dodgers", "Giants", "Giants @ Dodgers"),
        _pitching_row("Giants", "Dodgers", "Giants @ Dodgers"),
    ]
    games = E.pair_pitching_slate_by_game(rows)
    assert len(games) == 2
    labels = {g["label"] for g in games}
    assert labels == {"Red Sox @ Yankees", "Giants @ Dodgers"}


def test_pair_pitching_slate_by_game_empty_input():
    assert E.pair_pitching_slate_by_game([]) == []


# ----------------------------------------------------------------- build_game_lineups
def _fake_lineup_box(home_pids, away_pids):
    return {"teams": {"home": {"battingOrder": home_pids}, "away": {"battingOrder": away_pids}}}


def _fake_hitter(pid):
    return {"id": pid, "name": f"Batter {pid}", "bat_hand": "R",
           "stat": {"plateAppearances": 500, "avg": 0.260, "slg": 0.420, "obp": 0.330, "ops": 0.750,
                    "homeRuns": 15, "hits": 130, "totalBases": 210, "strikeOuts": 100},
           "vs_l": None, "vs_r": None}


def test_build_game_lineups_full_nine_batter_lineups(monkeypatch):
    home_pids = list(range(101, 110))   # 9 real pids
    away_pids = list(range(201, 210))
    box = _fake_lineup_box(home_pids, away_pids)

    monkeypatch.setattr(E, "get_pitcher_metrics",
                        lambda pid, fip_constant=E.FIP_CONSTANT_DEFAULT: E.PitcherMetrics(id=pid, name=f"SP{pid}"))
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
    monkeypatch.setattr(E, "get_hitter_raw", _fake_hitter)

    result = E.build_game_lineups(game_pk=999, home_id=10, away_id=20,
                                  home_pitcher_id=1, away_pitcher_id=2, venue_id=5)
    assert result is not None
    assert len(result["home_rows"]) == 9 and len(result["away_rows"]) == 9
    print("✓ build_game_lineups assembles a full real 9-batter lineup for both sides")


def test_build_game_lineups_home_batters_face_away_starter(monkeypatch):
    home_pids = list(range(101, 110))
    away_pids = list(range(201, 210))
    box = _fake_lineup_box(home_pids, away_pids)

    monkeypatch.setattr(E, "get_pitcher_metrics",
                        lambda pid, fip_constant=E.FIP_CONSTANT_DEFAULT: E.PitcherMetrics(id=pid, name=f"SP{pid}"))
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
    monkeypatch.setattr(E, "get_hitter_raw", _fake_hitter)

    result = E.build_game_lineups(game_pk=999, home_id=10, away_id=20,
                                  home_pitcher_id=1, away_pitcher_id=2, venue_id=5)
    # Home batters' own "_opp_pid" must reflect the AWAY starter (id=2), not home's own.
    assert all(r["_opp_pid"] == 2 for r in result["home_rows"])
    assert all(r["_opp_pid"] == 1 for r in result["away_rows"])
    # Bullpen-lookup team id: home batters' own _opp_id is the AWAY team (bullpen they'd face).
    assert all(r["_opp_id"] == 20 for r in result["home_rows"])
    assert all(r["_opp_id"] == 10 for r in result["away_rows"])
    print("✓ build_game_lineups correctly assigns each side's own OPPONENT starter/team, never swapped")


def test_build_game_lineups_none_when_lineup_incomplete(monkeypatch):
    home_pids = list(range(101, 106))   # only 5 -- an incomplete lineup
    away_pids = list(range(201, 210))
    box = _fake_lineup_box(home_pids, away_pids)

    monkeypatch.setattr(E, "get_pitcher_metrics",
                        lambda pid, fip_constant=E.FIP_CONSTANT_DEFAULT: E.PitcherMetrics(id=pid, name=f"SP{pid}"))
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
    monkeypatch.setattr(E, "get_hitter_raw", _fake_hitter)

    result = E.build_game_lineups(game_pk=999, home_id=10, away_id=20,
                                  home_pitcher_id=1, away_pitcher_id=2, venue_id=5)
    assert result is None
    print("✓ build_game_lineups returns None (not a partial/guessed lineup) when a full 9 real batters can't be assembled")


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


# ----------------------------------------------------------------- get_team_recent_form
def _fake_form_game(gamePk, game_date, home_id, home_score, away_score, status="Final"):
    return {"gamePk": gamePk, "game_date": game_date, "status": status, "home_id": home_id,
           "away_id": 999, "home_score": home_score, "away_score": away_score}


def test_get_team_recent_form_hand_verified_record_and_run_diff(monkeypatch):
    # Team 117 as home in every game here for simplicity: won 2, lost 1.
    # Game 1: 5-2 (own +3), Game 2: 1-4 (own -3), Game 3: 6-1 (own +5) -> run_diff = +5, 2-1 record
    games = [
        _fake_form_game(1, "2026-07-10T23:10:00Z", 117, 5, 2),
        _fake_form_game(2, "2026-07-12T23:10:00Z", 117, 1, 4),
        _fake_form_game(3, "2026-07-14T23:10:00Z", 117, 6, 1),
    ]
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    form = E.get_team_recent_form(117, "2026-07-18", games_back=15)
    assert form == {"games": 3, "wins": 2, "losses": 1, "win_pct": 0.667,
                    "run_diff": 5, "avg_run_diff": 1.67,
                    "runs_scored": 4.0, "runs_allowed": 2.33}   # 12/3, 7/3 rounded
    print("✓ get_team_recent_form hand-verifies the exact record and run differential from 3 games")


def test_get_team_recent_form_away_side_uses_away_score(monkeypatch):
    # Team 117 as AWAY this time: home_score=2, away_score=7 -> team 117 (away) won by +5.
    games = [{"gamePk": 1, "game_date": "2026-07-15T23:10:00Z", "status": "Final",
             "home_id": 200, "away_id": 117, "home_score": 2, "away_score": 7}]
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    form = E.get_team_recent_form(117, "2026-07-18", games_back=15)
    assert form["wins"] == 1 and form["run_diff"] == 5
    print("✓ get_team_recent_form correctly reads the away side's own score when the team is away")


def test_get_team_recent_form_skips_non_final_games(monkeypatch):
    games = [
        _fake_form_game(1, "2026-07-14T23:10:00Z", 117, 5, 2),
        _fake_form_game(2, "2026-07-16T23:10:00Z", 117, 3, 1, status="Postponed"),
    ]
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    form = E.get_team_recent_form(117, "2026-07-18", games_back=15)
    assert form["games"] == 1
    print("✓ get_team_recent_form excludes a non-Final (postponed) game from the record")


def test_get_team_recent_form_only_counts_most_recent_games_back(monkeypatch):
    games = [_fake_form_game(i, f"2026-07-{i:02d}T23:10:00Z", 117, 10, 0) for i in range(1, 11)]
    # 10 blowout wins available, but only ask for the last 3.
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    form = E.get_team_recent_form(117, "2026-07-18", games_back=3)
    assert form["games"] == 3
    print("✓ get_team_recent_form only counts the most recent games_back games, not every Final game found")


def test_get_team_recent_form_none_when_no_final_games(monkeypatch):
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: [])
    assert E.get_team_recent_form(117, "2026-07-18") is None
    print("✓ get_team_recent_form returns None (not a fabricated 0-0) when there's no real data")


def test_get_team_recent_form_none_on_bad_date():
    assert E.get_team_recent_form(117, "not-a-date") is None


def test_get_team_recent_form_venue_home_only(monkeypatch):
    games = [
        _fake_form_game(1, "2026-07-10T23:10:00Z", 117, 5, 2),          # home win
        {"gamePk": 2, "game_date": "2026-07-12T23:10:00Z", "status": "Final",
         "home_id": 200, "away_id": 117, "home_score": 9, "away_score": 1},   # away loss
        _fake_form_game(3, "2026-07-14T23:10:00Z", 117, 3, 6),          # home loss
    ]
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    form = E.get_team_recent_form(117, "2026-07-18", games_back=15, venue="home")
    assert form["games"] == 2   # only the 2 home games counted, away game excluded
    assert form["wins"] == 1 and form["losses"] == 1
    print("✓ get_team_recent_form(venue='home') correctly excludes this team's away games")


def test_get_team_recent_form_venue_away_only(monkeypatch):
    games = [
        _fake_form_game(1, "2026-07-10T23:10:00Z", 117, 5, 2),          # home win (excluded)
        {"gamePk": 2, "game_date": "2026-07-12T23:10:00Z", "status": "Final",
         "home_id": 200, "away_id": 117, "home_score": 9, "away_score": 1},   # away loss (counted)
    ]
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    form = E.get_team_recent_form(117, "2026-07-18", games_back=15, venue="away")
    assert form["games"] == 1 and form["losses"] == 1
    print("✓ get_team_recent_form(venue='away') correctly excludes this team's home games")


def test_get_team_recent_form_time_of_day_night_only(monkeypatch):
    games = [
        _fake_form_game(1, "2026-07-10T18:10:00Z", 117, 5, 2),   # 18:10 UTC = 14:10 ET -> day
        _fake_form_game(2, "2026-07-12T23:10:00Z", 117, 4, 1),   # 23:10 UTC = 19:10 ET -> night
    ]
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    night_form = E.get_team_recent_form(117, "2026-07-18", games_back=15, time_of_day="night")
    day_form = E.get_team_recent_form(117, "2026-07-18", games_back=15, time_of_day="day")
    assert night_form["games"] == 1 and day_form["games"] == 1
    print("✓ get_team_recent_form correctly splits games into day vs night using the same "
         "Eastern-hour boundary sports.slot_of already uses")


def test_get_team_recent_form_venue_and_time_of_day_combine(monkeypatch):
    games = [
        _fake_form_game(1, "2026-07-10T18:10:00Z", 117, 5, 2),   # home, day
        {"gamePk": 2, "game_date": "2026-07-11T23:10:00Z", "status": "Final",   # away, night
         "home_id": 200, "away_id": 117, "home_score": 1, "away_score": 4},
        _fake_form_game(3, "2026-07-12T23:10:00Z", 117, 3, 1),   # home, night
    ]
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    form = E.get_team_recent_form(117, "2026-07-18", games_back=15, venue="home", time_of_day="night")
    assert form["games"] == 1   # only game 3 is both home AND night
    print("✓ get_team_recent_form applies venue and time_of_day together (AND), not one overriding the other")


# ----------------------------------------------------------------- get_team_pitching_staff
def test_get_team_pitching_staff_filters_to_pitchers_and_excludes_given_id(monkeypatch):
    fake_roster = {"roster": [
        {"person": {"id": 111, "fullName": "Todays Starter"}, "position": {"abbreviation": "P"}},
        {"person": {"id": 222, "fullName": "Reliever B"}, "position": {"abbreviation": "P"}},
        {"person": {"id": 333, "fullName": "Reliever A"}, "position": {"abbreviation": "P"}},
        {"person": {"id": 444, "fullName": "Some Shortstop"}, "position": {"abbreviation": "SS"}},
    ]}
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fake_roster)
    staff = E.get_team_pitching_staff(117, exclude_pid=111)
    ids = {p["id"] for p in staff}
    assert ids == {222, 333}   # non-pitcher excluded, given exclude_pid excluded
    assert [p["name"] for p in staff] == ["Reliever A", "Reliever B"]   # sorted by name
    print("✓ get_team_pitching_staff correctly filters to pitchers and excludes the given id")


def test_get_team_pitching_staff_no_exclude(monkeypatch):
    fake_roster = {"roster": [
        {"person": {"id": 111, "fullName": "A Pitcher"}, "position": {"abbreviation": "P"}},
    ]}
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fake_roster)
    staff = E.get_team_pitching_staff(117)
    assert len(staff) == 1


def test_get_team_pitching_staff_empty_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: {})
    assert E.get_team_pitching_staff(117) == []


# ----------------------------------------------------------------- get_bullpen_aggregate_stat
def test_get_bullpen_aggregate_stat_sums_across_relievers(monkeypatch):
    fake_roster = {"roster": [
        {"person": {"id": 222, "fullName": "Reliever A"}, "position": {"abbreviation": "P"}},
        {"person": {"id": 333, "fullName": "Reliever B"}, "position": {"abbreviation": "P"}},
    ]}
    stats = {
        222: {"strikeOuts": 40, "baseOnBalls": 15, "hitByPitch": 2, "homeRuns": 5,
             "battersFaced": 200, "hits": 45, "atBats": 180, "earnedRuns": 20, "inningsPitched": "50.0"},
        333: {"strikeOuts": 30, "baseOnBalls": 10, "hitByPitch": 1, "homeRuns": 3,
             "battersFaced": 150, "hits": 35, "atBats": 135, "earnedRuns": 15, "inningsPitched": "38.0"},
    }

    def fake_metrics(pid, fip_constant):
        return E.PitcherMetrics(id=pid, name=f"P{pid}", stat=stats[pid])

    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fake_roster)
    monkeypatch.setattr(E, "get_pitcher_metrics", fake_metrics)
    agg = E.get_bullpen_aggregate_stat(117, exclude_pid=111)
    assert agg["strikeOuts"] == 70    # 40 + 30
    assert agg["homeRuns"] == 8       # 5 + 3
    assert agg["battersFaced"] == 350  # 200 + 150
    print("✓ get_bullpen_aggregate_stat correctly sums counting stats across the whole bullpen")


def test_get_bullpen_aggregate_stat_none_when_no_staff(monkeypatch):
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: {})
    assert E.get_bullpen_aggregate_stat(117) is None


def test_get_bullpen_aggregate_stat_none_when_no_usable_stats(monkeypatch):
    fake_roster = {"roster": [
        {"person": {"id": 222, "fullName": "No Data Guy"}, "position": {"abbreviation": "P"}},
    ]}
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fake_roster)
    monkeypatch.setattr(E, "get_pitcher_metrics", lambda pid, fc: E.PitcherMetrics(id=pid, stat={}))
    assert E.get_bullpen_aggregate_stat(117) is None
    print("✓ get_bullpen_aggregate_stat returns None rather than a fabricated empty line")


def test_get_bullpen_aggregate_stat_output_is_valid_pitcher_allowed_rates_input():
    # Confirms the shape really is a drop-in replacement for a single pitcher's own .stat —
    # the actual mechanism the Dinger Engine toggle depends on.
    import projections as P
    agg = {"strikeOuts": 70.0, "baseOnBalls": 25.0, "hitByPitch": 3.0, "homeRuns": 8.0,
          "battersFaced": 350.0, "hits": 80.0, "atBats": 315.0, "earnedRuns": 35.0,
          "inningsPitched": "88.0"}
    rates = P.pitcher_allowed_rates(agg)
    assert rates is not None
    assert 0 < rates["hr"] < 1
    print("✓ get_bullpen_aggregate_stat's output shape works directly with pitcher_allowed_rates")


# ----------------------------------------------------------------- enrich_bullpen_fatigue_with_metrics
def test_enrich_bullpen_fatigue_adds_era_fip_k9(monkeypatch):
    fatigue = [{"player_id": 555, "name": "Gassed Reliever", "days_since_last_appearance": 0,
               "consecutive_days": 3, "total_outs_in_window": 9, "tag": "🔴 3 straight days"}]

    def fake_metrics(pid, fip_constant):
        return E.PitcherMetrics(id=pid, name="Gassed Reliever", era=3.10, fip=2.95, k9=11.2,
                                whip=1.05, hr9=0.7, oba=0.210, has_stats=True)

    monkeypatch.setattr(E, "get_pitcher_metrics", fake_metrics)
    enriched = E.enrich_bullpen_fatigue_with_metrics(fatigue)
    assert enriched[0]["ERA"] == 3.10 and enriched[0]["FIP"] == 2.95 and enriched[0]["K9"] == 11.2
    assert enriched[0]["tag"] == "🔴 3 straight days"   # original fatigue fields preserved
    print("✓ enrich_bullpen_fatigue_with_metrics correctly adds quality metrics alongside fatigue data")


def test_enrich_bullpen_fatigue_flags_no_stats(monkeypatch):
    fatigue = [{"player_id": 999, "name": "No Data Guy", "days_since_last_appearance": 1,
               "consecutive_days": 1, "total_outs_in_window": 3, "tag": "🟡 Pitched yesterday"}]
    monkeypatch.setattr(E, "get_pitcher_metrics",
                        lambda pid, fc: E.PitcherMetrics(id=pid, name="No Data Guy", has_stats=False))
    enriched = E.enrich_bullpen_fatigue_with_metrics(fatigue)
    assert enriched[0]["has_stats"] is False


def test_enrich_bullpen_fatigue_preserves_order_and_count(monkeypatch):
    fatigue = [{"player_id": i, "name": f"P{i}", "days_since_last_appearance": i,
               "consecutive_days": 0, "total_outs_in_window": 3, "tag": "—"} for i in range(3)]
    monkeypatch.setattr(E, "get_pitcher_metrics", lambda pid, fc: E.PitcherMetrics(id=pid, name=f"P{pid}"))
    enriched = E.enrich_bullpen_fatigue_with_metrics(fatigue)
    assert [e["player_id"] for e in enriched] == [0, 1, 2]


# ----------------------------------------------------------------- get_bullpen_handedness_mix
def test_bullpen_handedness_mix_counts_correctly(monkeypatch):
    fake_roster = {"roster": [
        {"person": {"id": 1, "fullName": "Lefty A"}, "position": {"abbreviation": "P"}},
        {"person": {"id": 2, "fullName": "Righty A"}, "position": {"abbreviation": "P"}},
        {"person": {"id": 3, "fullName": "Righty B"}, "position": {"abbreviation": "P"}},
    ]}
    hands = {1: "L", 2: "R", 3: "R"}
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fake_roster)
    monkeypatch.setattr(E, "get_pitcher_metrics",
                        lambda pid, fc=E.FIP_CONSTANT_DEFAULT: E.PitcherMetrics(id=pid, hand=hands[pid]))
    mix = E.get_bullpen_handedness_mix(117)
    assert mix == {"L": 1, "R": 2, "total": 3, "pct_L": 1 / 3, "pct_R": 2 / 3}
    print("✓ get_bullpen_handedness_mix correctly counts L/R across the active bullpen")


def test_bullpen_handedness_mix_excludes_given_pid(monkeypatch):
    fake_roster = {"roster": [
        {"person": {"id": 1, "fullName": "Starter"}, "position": {"abbreviation": "P"}},
        {"person": {"id": 2, "fullName": "Reliever"}, "position": {"abbreviation": "P"}},
    ]}
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fake_roster)
    monkeypatch.setattr(E, "get_pitcher_metrics",
                        lambda pid, fc=E.FIP_CONSTANT_DEFAULT: E.PitcherMetrics(id=pid, hand="R"))
    mix = E.get_bullpen_handedness_mix(117, exclude_pid=1)
    assert mix["total"] == 1   # starter excluded, only the one reliever counted


def test_bullpen_handedness_mix_all_zero_when_no_staff(monkeypatch):
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: {})
    mix = E.get_bullpen_handedness_mix(117)
    assert mix == {"L": 0, "R": 0, "total": 0, "pct_L": 0.0, "pct_R": 0.0}
    print("✓ get_bullpen_handedness_mix returns safe all-zero counts, not None, when no staff data exists")


# ----------------------------------------------------------------- get_starter_rest_info
def _fake_box_for_pitcher(pid, name, ip):
    return {"teams": {"home": {"players": {f"ID{pid}": {
        "person": {"id": pid, "fullName": name},
        "stats": {"pitching": {"inningsPitched": ip}},
    }}}, "away": {"players": {}}}}


def test_starter_rest_standard_five_days(monkeypatch):
    games = [{"gamePk": 1, "game_date": "2026-07-13T23:10:00Z", "status": "Final", "home_id": 117}]
    box = _fake_box_for_pitcher(111, "Ace Starter", "6.0")
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
    info = E.get_starter_rest_info(111, 117, "2026-07-18")
    assert info["days_rest"] == 5
    assert "Standard rest" in info["rest_tag"]
    assert info["last_start_date"] == "2026-07-13"
    print("✓ get_starter_rest_info correctly identifies standard 5-day rest")


def test_starter_rest_short_rest_flagged(monkeypatch):
    games = [{"gamePk": 1, "game_date": "2026-07-15T23:10:00Z", "status": "Final", "home_id": 117}]
    box = _fake_box_for_pitcher(111, "Ace Starter", "6.0")
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
    info = E.get_starter_rest_info(111, 117, "2026-07-18")
    assert info["days_rest"] == 3
    assert "Short rest" in info["rest_tag"]
    print("✓ get_starter_rest_info correctly flags short rest")


def test_starter_rest_extra_rest_flagged(monkeypatch):
    games = [{"gamePk": 1, "game_date": "2026-07-10T23:10:00Z", "status": "Final", "home_id": 117}]
    box = _fake_box_for_pitcher(111, "Ace Starter", "6.0")
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
    info = E.get_starter_rest_info(111, 117, "2026-07-18")
    assert info["days_rest"] == 8
    assert "Extra rest" in info["rest_tag"]


def test_starter_rest_ignores_brief_relief_cameo(monkeypatch):
    # A 1-inning relief appearance right before today shouldn't count as "his last start" — the
    # 9-outs floor exists exactly for this case. His REAL last start (6 innings) is further back.
    games = [
        {"gamePk": 1, "game_date": "2026-07-16T23:10:00Z", "status": "Final", "home_id": 117},  # cameo
        {"gamePk": 2, "game_date": "2026-07-12T23:10:00Z", "status": "Final", "home_id": 117},  # real start
    ]
    boxes = {1: _fake_box_for_pitcher(111, "Ace Starter", "1.0"),
            2: _fake_box_for_pitcher(111, "Ace Starter", "6.0")}
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2:
                        boxes[int(url.rsplit("/game/", 1)[1].split("/")[0])])
    info = E.get_starter_rest_info(111, 117, "2026-07-18")
    assert info["last_start_date"] == "2026-07-12"   # not the 1-inning cameo on 07-16
    assert info["days_rest"] == 6
    print("✓ get_starter_rest_info correctly ignores a brief relief cameo, finding the real last start")


def test_starter_rest_none_when_no_qualifying_start_found(monkeypatch):
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: [])
    info = E.get_starter_rest_info(111, 117, "2026-07-18")
    assert info == {"days_rest": None, "last_start_date": None, "rest_tag": "No recent start found"}
    print("✓ get_starter_rest_info returns an honest None, not a fabricated number, when no start is found")


def test_starter_rest_picks_most_recent_qualifying_start(monkeypatch):
    games = [
        {"gamePk": 1, "game_date": "2026-07-08T23:10:00Z", "status": "Final", "home_id": 117},
        {"gamePk": 2, "game_date": "2026-07-13T23:10:00Z", "status": "Final", "home_id": 117},
    ]
    boxes = {1: _fake_box_for_pitcher(111, "Ace Starter", "6.0"),
            2: _fake_box_for_pitcher(111, "Ace Starter", "7.0")}
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2:
                        boxes[int(url.rsplit("/game/", 1)[1].split("/")[0])])
    info = E.get_starter_rest_info(111, 117, "2026-07-18")
    assert info["last_start_date"] == "2026-07-13"   # the MORE recent of the two, not the older one


# ----------------------------------------------------------------- get_pitcher_starts_this_season
def _fake_gamelog(entries):
    """entries: list of (gamePk, date, gamesStarted, innings_pitched_str)."""
    return {"stats": [{"splits": [
        {"game": {"gamePk": pk}, "date": d,
        "stat": {"gamesStarted": gs, "inningsPitched": ip}}
        for pk, d, gs, ip in entries
    ]}]}


def test_get_pitcher_starts_filters_to_real_starts(monkeypatch):
    fake = _fake_gamelog([
        (1, "2026-04-05", 1, "6.0"),   # real start
        (2, "2026-04-11", 1, "5.1"),   # real start
        (3, "2026-04-15", 0, "1.0"),   # relief cameo, not a start
    ])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fake)
    starts = E.get_pitcher_starts_this_season(111, 2026)
    assert {s["gamePk"] for s in starts} == {1, 2}
    print("✓ get_pitcher_starts_this_season correctly filters to real starts, excluding a relief cameo")


def test_get_pitcher_starts_no_lookahead(monkeypatch):
    fake = _fake_gamelog([
        (1, "2026-04-05", 1, "6.0"),
        (2, "2026-07-20", 1, "6.0"),   # AFTER before_date, must be excluded
    ])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fake)
    starts = E.get_pitcher_starts_this_season(111, 2026, before_date="2026-07-18")
    assert {s["gamePk"] for s in starts} == {1}
    print("✓ get_pitcher_starts_this_season correctly excludes games on/after before_date")


def test_get_pitcher_starts_falls_back_to_outs_floor(monkeypatch):
    # gamesStarted missing/0 but real innings pitched (a data-shape variance) still counts.
    fake = _fake_gamelog([(1, "2026-04-05", 0, "7.0")])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fake)
    starts = E.get_pitcher_starts_this_season(111, 2026)
    assert len(starts) == 1
    print("✓ get_pitcher_starts_this_season falls back to the outs floor when gamesStarted is absent/zero")


def test_get_pitcher_starts_empty_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: {})
    assert E.get_pitcher_starts_this_season(111, 2026) == []


# ----------------------------------------------------------------- get_actual_starter
def _fake_live_boxscore(home_players=None, away_players=None):
    """home_players/away_players: {pid: (name, gamesStarted)}. Builds a minimal real-shaped
    live boxscore -- distinct from _fake_boxscore above, which only models innings pitched
    (get_team_bullpen_fatigue's own concern), not gamesStarted (this function's own concern)."""
    def _side(players):
        out = {}
        for pid, (name, gs) in (players or {}).items():
            out[f"ID{pid}"] = {"person": {"id": pid, "fullName": name},
                               "stats": {"pitching": {"gamesStarted": gs}}}
        return {"players": out}
    return {"teams": {"home": _side(home_players), "away": _side(away_players)}}


def test_get_actual_starter_finds_the_real_starter(monkeypatch):
    box = _fake_live_boxscore(home_players={555: ("Real Starter", 1), 556: ("Reliever", 0)})
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
    starter = E.get_actual_starter(12345, "home")
    assert starter == {"player_id": 555, "name": "Real Starter"}
    print("✓ get_actual_starter correctly identifies the pitcher with gamesStarted >= 1, not a reliever with 0")


def test_get_actual_starter_none_on_empty_boxscore(monkeypatch):
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: {})
    assert E.get_actual_starter(12345, "home") is None
    print("✓ get_actual_starter returns None (not a crash or a guess) when the boxscore has no pitching data yet -- "
         "the same honest state as a game that hasn't started")


def test_get_actual_starter_none_on_fetch_failure(monkeypatch):
    def _boom(url, params=None, retries=2):
        raise Exception("network down")
    monkeypatch.setattr(E, "fetch_json", _boom)
    assert E.get_actual_starter(12345, "home") is None


def test_get_actual_starter_does_not_guess_from_outs_alone(monkeypatch):
    # A pitcher with real innings but gamesStarted explicitly 0/absent must NOT be picked --
    # the deliberate difference from get_pitcher_starts_this_season's own season-level fallback.
    box = _fake_live_boxscore(home_players={555: ("Long Reliever", 0)})
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
    assert E.get_actual_starter(12345, "home") is None
    print("✓ get_actual_starter never falls back to an outs-based guess for one partial, in-progress game")


def test_get_actual_starter_reads_the_correct_side(monkeypatch):
    box = _fake_live_boxscore(home_players={555: ("Home SP", 1)}, away_players={556: ("Away SP", 1)})
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
    assert E.get_actual_starter(12345, "home")["player_id"] == 555
    assert E.get_actual_starter(12345, "away")["player_id"] == 556
    print("✓ get_actual_starter reads the requested side only, never mixing up home and away")


# ----------------------------------------------------------------- starter_mismatch
def test_starter_mismatch_true_when_different_people():
    assert E.starter_mismatch(111, {"player_id": 222, "name": "Someone Else"}) is True


def test_starter_mismatch_false_when_same_person():
    assert E.starter_mismatch(111, {"player_id": 111, "name": "As Expected"}) is False


def test_starter_mismatch_none_when_no_probable_id():
    assert E.starter_mismatch(None, {"player_id": 222, "name": "X"}) is None


def test_starter_mismatch_none_when_actual_starter_unknown():
    assert E.starter_mismatch(111, None) is None
    print("✓ starter_mismatch reports None (not a false True/False) whenever either side is unknown")


# ----------------------------------------------------------------- get_pitcher_batting_order_splits
def _fake_bo_box(pitcher_id, pitcher_side, opp_batters):
    """opp_batters: list of (pid, name, battingOrder_code, batting_stat_dict)."""
    opp_side = "away" if pitcher_side == "home" else "home"
    opp_players = {f"ID{pid}": {"person": {"id": pid, "fullName": name}, "battingOrder": bo,
                                "stats": {"batting": stat}}
                  for pid, name, bo, stat in opp_batters}
    pitcher_players = {f"ID{pitcher_id}": {"person": {"id": pitcher_id, "fullName": "The Pitcher"},
                                           "stats": {"pitching": {"inningsPitched": "6.0"}}}}
    return {"teams": {pitcher_side: {"players": pitcher_players}, opp_side: {"players": opp_players}}}


def test_batting_order_splits_aggregates_across_multiple_starts(monkeypatch):
    starts = [{"gamePk": 1, "game_date": "2026-04-05"}, {"gamePk": 2, "game_date": "2026-04-11"}]
    boxes = {
        1: _fake_bo_box(111, "home", [(201, "Leadoff Guy", "100",
                                       dict(atBats=4, hits=2, doubles=1, triples=0, homeRuns=0,
                                           rbi=1, baseOnBalls=0, hitByPitch=0, strikeOuts=1, runs=1))]),
        2: _fake_bo_box(111, "away", [(201, "Leadoff Guy", "100",
                                       dict(atBats=3, hits=1, doubles=0, triples=0, homeRuns=1,
                                           rbi=1, baseOnBalls=1, hitByPitch=0, strikeOuts=0, runs=1))]),
    }
    monkeypatch.setattr(E, "get_pitcher_starts_this_season", lambda pid, s, bd=None: starts)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2:
                        boxes[int(url.rsplit("/game/", 1)[1].split("/")[0])])
    splits = E.get_pitcher_batting_order_splits(111, 2026)
    assert splits[1]["ab"] == 7.0    # 4 + 3
    assert splits[1]["h"] == 3.0     # 2 + 1
    assert splits[1]["hr"] == 1.0
    print("✓ get_pitcher_batting_order_splits correctly aggregates across multiple starts")


def test_batting_order_splits_only_counts_opponent_side(monkeypatch):
    # A hitter on the PITCHER's OWN team must never be counted, even if they'd have a
    # battingOrder field (e.g. an AL pitcher's own team's hitters in an NL park).
    starts = [{"gamePk": 1, "game_date": "2026-04-05"}]
    own_team_hitter_box = {"teams": {
        "home": {"players": {
            "ID111": {"person": {"id": 111, "fullName": "The Pitcher"},
                     "stats": {"pitching": {"inningsPitched": "6.0"}}},
            "ID999": {"person": {"id": 999, "fullName": "Own Team Hitter"}, "battingOrder": "300",
                     "stats": {"batting": dict(atBats=4, hits=2, doubles=0, triples=0, homeRuns=0,
                                              rbi=0, baseOnBalls=0, hitByPitch=0, strikeOuts=0, runs=0)}},
        }},
        "away": {"players": {
            "ID201": {"person": {"id": 201, "fullName": "Real Opponent"}, "battingOrder": "100",
                     "stats": {"batting": dict(atBats=4, hits=1, doubles=0, triples=0, homeRuns=0,
                                              rbi=0, baseOnBalls=0, hitByPitch=0, strikeOuts=0, runs=0)}},
        }},
    }}
    monkeypatch.setattr(E, "get_pitcher_starts_this_season", lambda pid, s, bd=None: starts)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: own_team_hitter_box)
    splits = E.get_pitcher_batting_order_splits(111, 2026)
    assert 3 not in splits    # the pitcher's own teammate never appears
    assert splits[1]["ab"] == 4.0
    print("✓ get_pitcher_batting_order_splits only counts the OPPONENT side, never the pitcher's own team")


def test_batting_order_splits_parses_substitution_codes_to_same_slot(monkeypatch):
    # "101" (a substitute who took over the leadoff spot mid-game) must still count as slot 1.
    starts = [{"gamePk": 1, "game_date": "2026-04-05"}]
    box = _fake_bo_box(111, "home", [(201, "Sub Leadoff", "101",
                                      dict(atBats=2, hits=1, doubles=0, triples=0, homeRuns=0,
                                          rbi=0, baseOnBalls=0, hitByPitch=0, strikeOuts=0, runs=0))])
    monkeypatch.setattr(E, "get_pitcher_starts_this_season", lambda pid, s, bd=None: starts)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
    splits = E.get_pitcher_batting_order_splits(111, 2026)
    assert 1 in splits and splits[1]["ab"] == 2.0
    print("✓ get_pitcher_batting_order_splits correctly parses a substitution code (101) to its real slot (1)")


def test_batting_order_splits_computes_rate_stats_correctly(monkeypatch):
    starts = [{"gamePk": 1, "game_date": "2026-04-05"}]
    box = _fake_bo_box(111, "home", [(201, "Hitter", "100",
                                      dict(atBats=4, hits=2, doubles=1, triples=0, homeRuns=1,
                                          rbi=2, baseOnBalls=1, hitByPitch=0, strikeOuts=1, runs=1))])
    monkeypatch.setattr(E, "get_pitcher_starts_this_season", lambda pid, s, bd=None: starts)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
    splits = E.get_pitcher_batting_order_splits(111, 2026)
    row = splits[1]
    assert row["avg"] == round(2 / 4, 3)
    assert row["obp"] == round((2 + 1 + 0) / (4 + 1 + 0), 3)
    # hits=2 total: 1 double + 1 HR accounts for both, leaving 0 singles.
    # TB = 0 singles + 2*1 double + 3*0 triples + 4*1 HR = 6, SLG = 6/4
    assert row["slg"] == round(6 / 4, 3)
    assert row["ops"] == round(row["obp"] + row["slg"], 3)
    print("✓ get_pitcher_batting_order_splits computes AVG/OBP/SLG/OPS correctly from a known example")


def test_batting_order_splits_empty_when_no_starts(monkeypatch):
    monkeypatch.setattr(E, "get_pitcher_starts_this_season", lambda pid, s, bd=None: [])
    assert E.get_pitcher_batting_order_splits(111, 2026) == {}


def test_batting_order_splits_skips_slot_with_no_real_pa(monkeypatch):
    # A slot that never came up against this pitcher (e.g. only 8 opposing hitters ever batted in
    # a given game due to a pitcher batting spot in an NL park) shouldn't appear at all.
    starts = [{"gamePk": 1, "game_date": "2026-04-05"}]
    box = _fake_bo_box(111, "home", [(201, "Hitter", "100",
                                      dict(atBats=4, hits=1, doubles=0, triples=0, homeRuns=0,
                                          rbi=0, baseOnBalls=0, hitByPitch=0, strikeOuts=0, runs=0))])
    monkeypatch.setattr(E, "get_pitcher_starts_this_season", lambda pid, s, bd=None: starts)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
    splits = E.get_pitcher_batting_order_splits(111, 2026)
    assert 9 not in splits
    print("✓ get_pitcher_batting_order_splits correctly omits slots with zero real plate appearances")


def test_get_pitcher_starts_requests_regular_season_only(monkeypatch):
    # Regression guard for the real bug found comparing this platform's output against ESPN's
    # own batting-order splits (a systematic ~11 AB overcount in every slot) — gameType="R" must
    # be explicitly requested, not left to the API's own default, which can otherwise pull in
    # spring training or other non-regular-season starts under the same season identifier.
    captured = {}

    def fake_fetch(url, params=None, retries=2):
        captured["params"] = params
        return _fake_gamelog([])

    monkeypatch.setattr(E, "fetch_json", fake_fetch)
    E.get_pitcher_starts_this_season(111, 2026)
    assert captured["params"].get("gameType") == "R"
    print("✓ get_pitcher_starts_this_season explicitly requests regular-season-only games")


# ----------------------------------------------------------------- get_player_current_team
def test_get_player_current_team_real_shape(monkeypatch):
    fake_response = {"people": [{"id": 123, "fullName": "Test Catcher",
                                 "currentTeam": {"id": 109, "name": "Arizona Diamondbacks"}}]}
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fake_response)
    team = E.get_player_current_team(123)
    assert team == {"id": 109, "name": "Arizona Diamondbacks"}
    print("✓ get_player_current_team correctly extracts both id and name from currentTeam")


def test_get_player_current_team_none_when_no_current_team(monkeypatch):
    fake_response = {"people": [{"id": 123, "fullName": "Retired Player"}]}   # no currentTeam key
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fake_response)
    assert E.get_player_current_team(123) is None
    print("✓ get_player_current_team returns None, not a fabricated team, for a player with no current team")


def test_get_player_current_team_none_on_fetch_failure(monkeypatch):
    def fake_fetch(url, params=None, retries=2):
        raise ConnectionError("simulated network failure")
    monkeypatch.setattr(E, "fetch_json", fake_fetch)
    assert E.get_player_current_team(123) is None


def test_get_player_current_team_none_on_empty_people(monkeypatch):
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: {"people": []})
    assert E.get_player_current_team(123) is None


def test_get_player_current_team_requests_hydrate_currentTeam(monkeypatch):
    # Regression guard for the real, confirmed production bug: currentTeam requires explicit
    # hydration on MLB Stats API's people endpoint, not something included by default. An
    # earlier version of this function never requested it, causing a complete 0/61 failure rate
    # across every real catcher in production, including well-known active players. Confirmed
    # from two independent sources (MLB Stats API's own documented hydration values, and
    # MLB-StatsAPI's own real, working source code building "...,currentTeam" into its hydrate
    # string) before this fix, not guessed a second time.
    captured = {}

    def fake_fetch(url, params=None, retries=2):
        captured["params"] = params
        return {"people": [{"id": 123, "currentTeam": {"id": 109, "name": "Arizona Diamondbacks"}}]}

    monkeypatch.setattr(E, "fetch_json", fake_fetch)
    team = E.get_player_current_team(123)
    assert captured["params"] == {"hydrate": "currentTeam"}
    assert team == {"id": 109, "name": "Arizona Diamondbacks"}
    print("✓ get_player_current_team correctly requests hydrate=currentTeam, the actual fix for the real 0/61 production failure")


# ----------------------------------------------------------------- _find_catcher_in_boxscore_side
def test_find_catcher_picks_position_c():
    players = {
        "ID1": {"person": {"id": 1, "fullName": "The Catcher"}, "position": {"abbreviation": "C"},
               "stats": {"batting": {"plateAppearances": 4}}},
        "ID2": {"person": {"id": 2, "fullName": "The Shortstop"}, "position": {"abbreviation": "SS"},
               "stats": {"batting": {"plateAppearances": 4}}},
    }
    result = E._find_catcher_in_boxscore_side(players)
    assert result == {"id": 1, "name": "The Catcher"}
    print("✓ _find_catcher_in_boxscore_side correctly picks the position-C player")


def test_find_catcher_prefers_most_plate_appearances_when_multiple():
    players = {
        "ID1": {"person": {"id": 1, "fullName": "Backup Catcher"}, "position": {"abbreviation": "C"},
               "stats": {"batting": {"plateAppearances": 1}}},
        "ID2": {"person": {"id": 2, "fullName": "Starting Catcher"}, "position": {"abbreviation": "C"},
               "stats": {"batting": {"plateAppearances": 4}}},
    }
    result = E._find_catcher_in_boxscore_side(players)
    assert result["name"] == "Starting Catcher"
    print("✓ _find_catcher_in_boxscore_side prefers the catcher with the most plate appearances when two appeared")


def test_find_catcher_none_when_no_catcher_present():
    players = {"ID1": {"person": {"id": 1, "fullName": "Shortstop"}, "position": {"abbreviation": "SS"}}}
    assert E._find_catcher_in_boxscore_side(players) is None


# ----------------------------------------------------------------- get_pitcher_catcher_change_split
def _fake_start_with_stat(gamePk, date, bb, k, bf):
    return {"gamePk": gamePk, "game_date": date,
           "stat": {"baseOnBalls": bb, "strikeOuts": k, "battersFaced": bf}}


def _fake_box_with_catcher(pitcher_id, catcher_id, catcher_name):
    return {"teams": {"home": {"players": {
        f"ID{pitcher_id}": {"person": {"id": pitcher_id, "fullName": "The Pitcher"},
                            "stats": {"pitching": {"inningsPitched": "6.0"}}},
        f"ID{catcher_id}": {"person": {"id": catcher_id, "fullName": catcher_name},
                            "position": {"abbreviation": "C"},
                            "stats": {"batting": {"plateAppearances": 4}}},
    }}, "away": {"players": {}}}}


def test_catcher_change_split_detects_clean_transition(monkeypatch):
    # 4 starts with the OLD catcher, 4 starts with the NEW catcher — a clean transition.
    starts = [
        _fake_start_with_stat(1, "2026-04-05", bb=2, k=6, bf=25),
        _fake_start_with_stat(2, "2026-04-11", bb=3, k=5, bf=24),
        _fake_start_with_stat(3, "2026-04-17", bb=2, k=7, bf=26),
        _fake_start_with_stat(4, "2026-04-23", bb=4, k=4, bf=23),
        _fake_start_with_stat(5, "2026-05-09", bb=1, k=8, bf=26),   # new catcher starts here
        _fake_start_with_stat(6, "2026-05-15", bb=0, k=9, bf=27),
        _fake_start_with_stat(7, "2026-05-21", bb=1, k=8, bf=25),
        _fake_start_with_stat(8, "2026-05-27", bb=1, k=9, bf=26),
    ]
    boxes = {
        1: _fake_box_with_catcher(111, 201, "Old Catcher"), 2: _fake_box_with_catcher(111, 201, "Old Catcher"),
        3: _fake_box_with_catcher(111, 201, "Old Catcher"), 4: _fake_box_with_catcher(111, 201, "Old Catcher"),
        5: _fake_box_with_catcher(111, 202, "New Catcher"), 6: _fake_box_with_catcher(111, 202, "New Catcher"),
        7: _fake_box_with_catcher(111, 202, "New Catcher"), 8: _fake_box_with_catcher(111, 202, "New Catcher"),
    }
    monkeypatch.setattr(E, "get_pitcher_starts_this_season", lambda pid, s, bd=None: starts)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2:
                        boxes[int(url.rsplit("/game/", 1)[1].split("/")[0])])
    result = E.get_pitcher_catcher_change_split(111, 999, 2026)
    assert result is not None
    assert result["changed"] is True
    assert result["old_catcher"]["name"] == "Old Catcher"
    assert result["new_catcher"]["name"] == "New Catcher"
    assert result["change_date"] == "2026-05-09"
    assert result["before"]["starts"] == 4
    assert result["after"]["starts"] == 4
    # before: BB=2+3+2+4=11, BF=25+24+26+23=98 -> 11/98
    assert result["before"]["bb_pct"] == round(11 / 98, 4)
    # after: K=8+9+8+9=34, BF=26+27+25+26=104 -> 34/104
    assert result["after"]["k_pct"] == round(34 / 104, 4)
    print("✓ get_pitcher_catcher_change_split correctly detects a clean transition and computes real before/after rates")


def test_catcher_change_split_none_when_only_one_catcher(monkeypatch):
    starts = [_fake_start_with_stat(i, f"2026-04-{i:02d}", bb=2, k=6, bf=25) for i in range(1, 9)]
    box = _fake_box_with_catcher(111, 201, "Only Catcher")
    monkeypatch.setattr(E, "get_pitcher_starts_this_season", lambda pid, s, bd=None: starts)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
    assert E.get_pitcher_catcher_change_split(111, 999, 2026) is None
    print("✓ get_pitcher_catcher_change_split correctly returns None when only one catcher ever appeared")


def test_catcher_change_split_none_when_rotation_not_clean_transition(monkeypatch):
    # Alternating catchers every start — real rotation, not a clean one-time transition.
    starts = [_fake_start_with_stat(i, f"2026-04-{i:02d}", bb=2, k=6, bf=25) for i in range(1, 9)]
    boxes = {i: _fake_box_with_catcher(111, 201 if i % 2 == 0 else 202, "Catcher A" if i % 2 == 0 else "Catcher B")
            for i in range(1, 9)}
    monkeypatch.setattr(E, "get_pitcher_starts_this_season", lambda pid, s, bd=None: starts)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2:
                        boxes[int(url.rsplit("/game/", 1)[1].split("/")[0])])
    assert E.get_pitcher_catcher_change_split(111, 999, 2026) is None
    print("✓ get_pitcher_catcher_change_split correctly refuses to report routine rotation as a clean transition")


def test_catcher_change_split_none_when_too_few_starts(monkeypatch):
    starts = [_fake_start_with_stat(1, "2026-04-05", bb=2, k=6, bf=25)]
    monkeypatch.setattr(E, "get_pitcher_starts_this_season", lambda pid, s, bd=None: starts)
    assert E.get_pitcher_catcher_change_split(111, 999, 2026) is None


def test_catcher_change_split_requires_min_starts_each_side(monkeypatch):
    # A transition exists but the "before" block only has 2 starts, below the default floor of 3.
    starts = [
        _fake_start_with_stat(1, "2026-04-05", bb=2, k=6, bf=25),
        _fake_start_with_stat(2, "2026-04-11", bb=2, k=6, bf=25),
        _fake_start_with_stat(3, "2026-04-17", bb=2, k=6, bf=25),
        _fake_start_with_stat(4, "2026-04-23", bb=2, k=6, bf=25),
        _fake_start_with_stat(5, "2026-04-29", bb=2, k=6, bf=25),
        _fake_start_with_stat(6, "2026-05-05", bb=2, k=6, bf=25),
    ]
    boxes = {
        1: _fake_box_with_catcher(111, 201, "Old Catcher"), 2: _fake_box_with_catcher(111, 201, "Old Catcher"),
        3: _fake_box_with_catcher(111, 202, "New Catcher"), 4: _fake_box_with_catcher(111, 202, "New Catcher"),
        5: _fake_box_with_catcher(111, 202, "New Catcher"), 6: _fake_box_with_catcher(111, 202, "New Catcher"),
    }
    monkeypatch.setattr(E, "get_pitcher_starts_this_season", lambda pid, s, bd=None: starts)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2:
                        boxes[int(url.rsplit("/game/", 1)[1].split("/")[0])])
    assert E.get_pitcher_catcher_change_split(111, 999, 2026) is None   # only 2 "before" starts, below floor of 3
    print("✓ get_pitcher_catcher_change_split respects the min_starts_each_side floor")


# ----------------------------------------------------------------- compute_one_sided_banner
def _rows_for_game(game_label, team_a, hr9_a, team_b, hr9_b, n_each=3, bf_a=400, bf_b=400):
    rows = []
    for i in range(n_each):
        rows.append({"GameLabel": game_label, "Team": team_a, "Opp HR/9": hr9_a,
                    "_opp_stat": {"battersFaced": bf_a}})
    for i in range(n_each):
        rows.append({"GameLabel": game_label, "Team": team_b, "Opp HR/9": hr9_b,
                    "_opp_stat": {"battersFaced": bf_b}})
    return rows


def test_one_sided_banner_flags_real_gap():
    rows = _rows_for_game("TB @ BOS (Game 1)", "Tampa Bay Rays", 1.10, "Boston Red Sox", 1.65)
    result = E.compute_one_sided_banner(rows, "TB @ BOS (Game 1)")
    assert result is not None
    assert result["favored_team"] == "Boston Red Sox"   # faces the WEAKER (higher HR/9) pitcher
    assert result["favored_opp_hr9"] == 1.65
    assert result["other_team"] == "Tampa Bay Rays"
    assert result["diff"] == 0.55
    print("✓ compute_one_sided_banner correctly identifies the favored side facing the weaker pitcher")


def test_one_sided_banner_none_when_thin_sample():
    # Regression guard for the real, reported bug: a starter with a thin sample (a call-up, a
    # handful of innings) can show a misleadingly "elite" HR/9 that's really just noise, not
    # skill -- the exact real-world case that produced a banner contradicting the actual per-
    # hitter grades shown right below it. Must be rejected the same way pitcher_allowed_rates
    # already rejects a thin sample for the real HR% math (same >=40 BF floor).
    rows = _rows_for_game("PIT @ CLE (Game 2)", "Pittsburgh Pirates", 0.00, "Cleveland Guardians", 0.97,
                          bf_a=15, bf_b=380)   # Pittsburgh's opposing starter has a real, thin sample
    assert E.compute_one_sided_banner(rows, "PIT @ CLE (Game 2)") is None
    print("✓ compute_one_sided_banner correctly refuses to trust a thin-sample starter's misleadingly elite HR/9")


def test_one_sided_banner_flags_when_both_samples_real():
    # The same real-world gap (0.97 vs 0.00), but now BOTH starters have a real sample -- should
    # correctly fire, confirming the fix rejects thin samples specifically, not HR/9 gaps in general.
    rows = _rows_for_game("PIT @ CLE (Game 2)", "Pittsburgh Pirates", 0.00, "Cleveland Guardians", 0.97,
                          bf_a=350, bf_b=380)
    result = E.compute_one_sided_banner(rows, "PIT @ CLE (Game 2)")
    assert result is not None
    assert result["favored_team"] == "Cleveland Guardians"


def test_one_sided_banner_none_when_gap_too_small():
    rows = _rows_for_game("TB @ BOS (Game 1)", "Tampa Bay Rays", 1.20, "Boston Red Sox", 1.35)
    assert E.compute_one_sided_banner(rows, "TB @ BOS (Game 1)") is None
    print("✓ compute_one_sided_banner correctly says nothing for a genuinely close matchup")


def test_one_sided_banner_exactly_at_threshold_not_flagged():
    # diff == threshold exactly should NOT be excluded (uses < for the skip check, i.e. >=
    # threshold required) -- confirms the boundary itself, not just values clearly on either side.
    rows = _rows_for_game("TB @ BOS (Game 1)", "Tampa Bay Rays", 1.00, "Boston Red Sox", 1.40)
    result = E.compute_one_sided_banner(rows, "TB @ BOS (Game 1)")
    assert result is not None   # diff of exactly 0.4 should clear (>=), not be excluded
    assert result["diff"] == 0.4


def test_one_sided_banner_none_when_game_not_found():
    rows = _rows_for_game("TB @ BOS (Game 1)", "Tampa Bay Rays", 1.10, "Boston Red Sox", 1.65)
    assert E.compute_one_sided_banner(rows, "NYY @ HOU (Game 1)") is None


def test_one_sided_banner_none_when_nan_hr9():
    rows = [
        {"GameLabel": "G1", "Team": "A", "Opp HR/9": float("nan"), "_opp_stat": {"battersFaced": 400}},
        {"GameLabel": "G1", "Team": "B", "Opp HR/9": 1.50, "_opp_stat": {"battersFaced": 400}},
    ]
    assert E.compute_one_sided_banner(rows, "G1") is None
    print("✓ compute_one_sided_banner correctly handles a NaN HR/9 (no stats yet) without crashing or fabricating")


def test_one_sided_banner_none_when_only_one_team_present():
    rows = [{"GameLabel": "G1", "Team": "Team A", "Opp HR/9": 1.10, "_opp_stat": {"battersFaced": 400}}] * 5
    assert E.compute_one_sided_banner(rows, "G1") is None


# ----------------------------------------------------------------- get_team_hitter_workload
def _fake_hitter_boxscore(starters, subs=None):
    """starters: {pid: (name, slot_1_to_9)} -> battingOrder ending in "00".
    subs: {pid: (name, slot_1_to_9)} -> battingOrder ending in "01" (a late-game substitute)."""
    players = {}
    for pid, (name, slot) in starters.items():
        players[f"ID{pid}"] = {"person": {"id": pid, "fullName": name},
                               "battingOrder": str(slot * 100)}
    for pid, (name, slot) in (subs or {}).items():
        players[f"ID{pid}"] = {"person": {"id": pid, "fullName": name},
                               "battingOrder": str(slot * 100 + 1)}
    return {"teams": {"home": {"players": players}, "away": {"players": {}}}}


def test_hitter_workload_flags_iron_man_streak(monkeypatch):
    # Started all 8 of the team's last 8 games -> the highest-value tag.
    games = [{"gamePk": i, "game_date": f"2026-07-{10+i:02d}T23:10:00Z", "status": "Final",
             "home_id": 117} for i in range(1, 9)]
    boxscores = {i: _fake_hitter_boxscore({501: ("Iron Man", 3)}) for i in range(1, 9)}
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2:
                        boxscores[int(url.rsplit("/game/", 1)[1].split("/")[0])])
    workload = E.get_team_hitter_workload(117, "2026-07-18", days_back=10)
    assert len(workload) == 1
    assert workload[0]["consecutive_games_started"] == 8
    assert "8 straight games" in workload[0]["tag"]
    assert "🔴" in workload[0]["tag"]
    print("✓ get_team_hitter_workload correctly flags a real 8-game iron-man streak")


def test_hitter_workload_streak_breaks_at_a_missed_game(monkeypatch):
    # Started games 3-5 (the 3 most recent), but sat out games 1-2 -> streak of 3, not 5.
    games = [{"gamePk": i, "game_date": f"2026-07-{10+i:02d}T23:10:00Z", "status": "Final",
             "home_id": 117} for i in range(1, 6)]
    boxscores = {
        1: _fake_hitter_boxscore({}),   # sat out
        2: _fake_hitter_boxscore({}),   # sat out
        3: _fake_hitter_boxscore({501: ("Rested Now", 3)}),
        4: _fake_hitter_boxscore({501: ("Rested Now", 3)}),
        5: _fake_hitter_boxscore({501: ("Rested Now", 3)}),
    }
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2:
                        boxscores[int(url.rsplit("/game/", 1)[1].split("/")[0])])
    workload = E.get_team_hitter_workload(117, "2026-07-18", days_back=10)
    assert workload[0]["consecutive_games_started"] == 3
    assert workload[0]["games_started_in_window"] == 3
    print("✓ get_team_hitter_workload correctly counts the streak backward from the most recent game, stopping at a real miss")


def test_hitter_workload_excludes_late_substitutes(monkeypatch):
    # A player who only ever entered as a late-game sub (battingOrder ending in a non-zero
    # suffix) should never count as having "started" -- a real distinction, not noise.
    games = [{"gamePk": 1, "game_date": "2026-07-17T23:10:00Z", "status": "Final", "home_id": 117}]
    boxscores = {1: _fake_hitter_boxscore(starters={}, subs={601: ("Late Sub", 3)})}
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2:
                        boxscores[int(url.rsplit("/game/", 1)[1].split("/")[0])])
    workload = E.get_team_hitter_workload(117, "2026-07-18", days_back=10)
    assert workload == []
    print("✓ get_team_hitter_workload correctly excludes a player who only ever entered as a late substitute")


def test_hitter_workload_tag_thresholds(monkeypatch):
    # 6 straight starts -> the middle "extended run" tag, not the highest-severity one.
    games = [{"gamePk": i, "game_date": f"2026-07-{10+i:02d}T23:10:00Z", "status": "Final",
             "home_id": 117} for i in range(1, 7)]
    boxscores = {i: _fake_hitter_boxscore({501: ("Regular", 3)}) for i in range(1, 7)}
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2:
                        boxscores[int(url.rsplit("/game/", 1)[1].split("/")[0])])
    workload = E.get_team_hitter_workload(117, "2026-07-18", days_back=10)
    assert workload[0]["consecutive_games_started"] == 6
    assert "🟡" in workload[0]["tag"]
    assert "extended run" in workload[0]["tag"]


def test_hitter_workload_low_streak_green_tag(monkeypatch):
    games = [{"gamePk": 1, "game_date": "2026-07-17T23:10:00Z", "status": "Final", "home_id": 117}]
    boxscores = {1: _fake_hitter_boxscore({501: ("Fresh Guy", 3)})}
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2:
                        boxscores[int(url.rsplit("/game/", 1)[1].split("/")[0])])
    workload = E.get_team_hitter_workload(117, "2026-07-18", days_back=10)
    assert "🟢" in workload[0]["tag"]


def test_hitter_workload_works_for_away_side(monkeypatch):
    games = [{"gamePk": 1, "game_date": "2026-07-17T23:10:00Z", "status": "Final", "home_id": 999}]
    box = {"teams": {"home": {"players": {}},
                     "away": {"players": {"ID501": {"person": {"id": 501, "fullName": "Away Starter"},
                                                    "battingOrder": "300"}}}}}
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
    workload = E.get_team_hitter_workload(117, "2026-07-18", days_back=10)   # 117 is the AWAY team here
    assert len(workload) == 1
    assert workload[0]["name"] == "Away Starter"
    print("✓ get_team_hitter_workload correctly reads the away side when the tracked team is the visitor")


def test_hitter_workload_skips_non_final_games(monkeypatch):
    games = [{"gamePk": 1, "game_date": "2026-07-17T23:10:00Z", "status": "In Progress", "home_id": 117}]
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2:
                        (_ for _ in ()).throw(AssertionError("should not fetch a non-final game's boxscore")))
    workload = E.get_team_hitter_workload(117, "2026-07-18", days_back=10)
    assert workload == []


def test_hitter_workload_empty_when_no_games(monkeypatch):
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: [])
    assert E.get_team_hitter_workload(117, "2026-07-18", days_back=10) == []


def test_hitter_workload_sorted_by_streak_descending(monkeypatch):
    games = [{"gamePk": i, "game_date": f"2026-07-{10+i:02d}T23:10:00Z", "status": "Final",
             "home_id": 117} for i in range(1, 4)]
    boxscores = {
        1: _fake_hitter_boxscore({501: ("Low Streak", 3), 502: ("High Streak", 4)}),
        2: _fake_hitter_boxscore({502: ("High Streak", 4)}),   # 501 sat this one out
        3: _fake_hitter_boxscore({501: ("Low Streak", 3), 502: ("High Streak", 4)}),
    }
    monkeypatch.setattr(E, "get_team_schedule_range", lambda team_id, s, e: games)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2:
                        boxscores[int(url.rsplit("/game/", 1)[1].split("/")[0])])
    workload = E.get_team_hitter_workload(117, "2026-07-18", days_back=10)
    assert workload[0]["name"] == "High Streak"   # 3-game streak (never missed) ranked first
    assert workload[1]["name"] == "Low Streak"    # 1-game streak (missed game 2) ranked second
    print("✓ get_team_hitter_workload correctly sorts the least-rested hitters first")


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
