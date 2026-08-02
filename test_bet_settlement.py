"""
test_bet_settlement.py — offline tests for automated Bet Log result settlement.

Mocks mlb_engine's own fetches (get_schedule, fetch_json) and betlog's own write (update_bet) --
no network, no real database required.

    python test_bet_settlement.py    # or: pytest test_bet_settlement.py
"""

import mlb_engine as E
import bet_settlement as S


def _schedule_game(gamePk=999, home="New York Yankees", away="Boston Red Sox",
                   status="Final", home_score=5, away_score=3, game_number=1):
    return {"gamePk": gamePk, "status": status, "home_name": home, "away_name": away,
           "home_score": home_score, "away_score": away_score, "home_id": 147, "away_id": 111,
           "gameNumber": game_number}


def _boxscore(home_players=None, away_players=None):
    """home_players/away_players: {pid: (name, hits, hr, tb, so, runs, rbi)}. Real-shaped
    boxscore, same convention as test_engine.py's own fake boxscore helpers."""
    def _side(players):
        out = {}
        for pid, (name, hits, hr, tb, so, runs, rbi) in (players or {}).items():
            doubles = triples = 0   # kept simple; tb derived directly below instead
            out[f"ID{pid}"] = {"person": {"id": pid, "fullName": name}, "stats": {"batting": {
                "hits": hits, "homeRuns": hr, "doubles": 0, "triples": 0, "strikeOuts": so,
                "runs": runs, "rbi": rbi}}}
            # tb isn't read directly from the boxscore -- parse_boxscore_results derives it from
            # hits/doubles/triples/hr, so keep this helper's own inputs consistent with that.
        return {"players": out}
    return {"teams": {"home": _side(home_players), "away": _side(away_players)}}


def _bet(id=1, slate_date="2026-07-24", game="Boston Red Sox @ New York Yankees",
        player=None, player_id=None, market="Batter HR", side="Over", line=0.5, result=None):
    return {"id": id, "slate_date": slate_date, "game": game, "player": player,
           "player_id": player_id, "market": market, "side": side, "line": line, "result": result}


# ----------------------------------------------------------------- build_settlement_plan: player props
def test_build_settlement_plan_player_prop_wins(monkeypatch):
    bet = _bet(player="Real Slugger", player_id=555, market="Batter HR", side="Over", line=0.5)
    box = _boxscore(away_players={555: ("Real Slugger", 1, 1, 4, 1, 1, 2)})   # 1 HR -> win

    monkeypatch.setattr(E, "get_schedule", lambda d: [_schedule_game()])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)

    plan = S.build_settlement_plan([bet])
    assert plan["still_pending"] == [] and plan["unresolved"] == []
    assert len(plan["proposed"]) == 1
    assert plan["proposed"][0] == {"bet_id": 1, "description": "Real Slugger · Batter HR Over 0.5",
                                   "old_result": "(unsettled)", "new_result": "win"}
    print("✓ build_settlement_plan correctly settles a real player-prop bet to 'win' end to end")


def test_build_settlement_plan_player_prop_void_on_dnp(monkeypatch):
    bet = _bet(player="Scratched Guy", player_id=777, market="Batter HR", side="Over", line=0.5)
    box = _boxscore(away_players={555: ("Someone Else", 2, 0, 2, 0, 1, 1)})   # 777 never appears

    monkeypatch.setattr(E, "get_schedule", lambda d: [_schedule_game()])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)

    plan = S.build_settlement_plan([bet])
    assert len(plan["proposed"]) == 1
    assert plan["proposed"][0]["new_result"] == "void"
    print("✓ build_settlement_plan correctly settles a scratched/DNP player-prop bet to 'void', not silently a loss")


def test_build_settlement_plan_game_not_final_stays_pending(monkeypatch):
    bet = _bet(player="Someone", player_id=555, market="Batter HR", side="Over", line=0.5)
    monkeypatch.setattr(E, "get_schedule", lambda d: [_schedule_game(status="In Progress")])
    fetch_calls = []
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fetch_calls.append(url) or {})

    plan = S.build_settlement_plan([bet])
    assert plan["proposed"] == [] and plan["unresolved"] == []
    assert len(plan["still_pending"]) == 1
    assert fetch_calls == []   # no boxscore fetch at all for a non-final game -- a real cost guard
    print("✓ build_settlement_plan correctly leaves a still-in-progress game's bet pending, and never fetches its boxscore at all")


def test_build_settlement_plan_unmatched_game_label_is_unresolved(monkeypatch):
    bet = _bet(player="Someone", player_id=555, game="Nonexistent Team @ Another Fake Team")
    monkeypatch.setattr(E, "get_schedule", lambda d: [_schedule_game()])
    plan = S.build_settlement_plan([bet])
    assert len(plan["unresolved"]) == 1
    assert "couldn't match" in plan["unresolved"][0]["reason"]
    print("✓ build_settlement_plan flags a bet whose game label doesn't match any real scheduled game as unresolved, not silently dropped")


def test_build_settlement_plan_no_player_id_and_not_moneyline_is_unresolved(monkeypatch):
    bet = _bet(player="Old Manual Entry", player_id=None, market="Batter HR")
    monkeypatch.setattr(E, "get_schedule", lambda d: [_schedule_game()])
    plan = S.build_settlement_plan([bet])
    assert len(plan["unresolved"]) == 1
    assert "no player_id" in plan["unresolved"][0]["reason"]
    print("✓ build_settlement_plan flags an old bet with no player_id (and not a moneyline) as needing manual entry")


def test_build_settlement_plan_boxscore_fetched_once_per_game_not_per_bet(monkeypatch):
    # Two different bets, same real game -- the boxscore must be fetched exactly once, not twice.
    bet1 = _bet(id=1, player="Player A", player_id=555)
    bet2 = _bet(id=2, player="Player B", player_id=556, market="Batter Total Hits", side="Over", line=0.5)
    box = _boxscore(away_players={555: ("Player A", 1, 1, 4, 1, 1, 2), 556: ("Player B", 2, 0, 2, 0, 0, 1)})

    fetch_calls = []
    monkeypatch.setattr(E, "get_schedule", lambda d: [_schedule_game()])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fetch_calls.append(url) or box)

    plan = S.build_settlement_plan([bet1, bet2])
    assert len(plan["proposed"]) == 2
    assert len(fetch_calls) == 1   # the real cost guarantee -- one boxscore fetch, not two
    print("✓ build_settlement_plan fetches a game's own boxscore exactly once even when multiple bets reference it")


# ----------------------------------------------------------------- build_settlement_plan: moneylines
def test_build_settlement_plan_moneyline_settles_without_a_boxscore_fetch(monkeypatch):
    bet = _bet(player=None, player_id=None, market="Moneyline", side="New York Yankees", line=None)
    fetch_calls = []
    monkeypatch.setattr(E, "get_schedule", lambda d: [_schedule_game(home_score=5, away_score=3)])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fetch_calls.append(url) or {})

    plan = S.build_settlement_plan([bet])
    assert len(plan["proposed"]) == 1
    assert plan["proposed"][0]["new_result"] == "win"   # Yankees (home) won 5-3
    assert fetch_calls == []   # moneylines settle directly off the schedule's own score, no boxscore needed
    print("✓ build_settlement_plan settles a moneyline bet directly from the schedule's own score, with zero boxscore fetches")


def test_build_settlement_plan_moneyline_loss(monkeypatch):
    bet = _bet(player=None, player_id=None, market="Moneyline", side="Boston Red Sox", line=None)
    monkeypatch.setattr(E, "get_schedule", lambda d: [_schedule_game(home_score=5, away_score=3)])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: {})
    plan = S.build_settlement_plan([bet])
    assert plan["proposed"][0]["new_result"] == "loss"


# ----------------------------------------------------------------- build_settlement_plan: team totals
def _linescore(innings_data):
    """innings_data: [(num, home_runs, away_runs), ...] -- real MLB Stats API /linescore shape,
    same field path (innings[].num, .home.runs, .away.runs) get_game_first_n_innings_runs's own
    docstring confirms against the official MLB-StatsAPI wrapper."""
    return {"innings": [{"num": n, "home": {"runs": hr}, "away": {"runs": ar}}
                        for n, hr, ar in innings_data]}


def test_build_settlement_plan_team_total_home_side_win(monkeypatch):
    # Yankees (home) is the TEAM being bet -- "player" carries the team name, same reused-field
    # convention TEAM_TOTAL_MARKETS' own comment documents. 3 real runs over 5 real innings vs a
    # 1.5 line -> Over wins.
    bet = _bet(player="New York Yankees", player_id=None, market="First 5 Innings Total",
              side="Over", line=1.5)
    ls = _linescore([(1, 1, 0), (2, 0, 0), (3, 1, 1), (4, 0, 0), (5, 1, 0)])   # home: 3, away: 1
    monkeypatch.setattr(E, "get_schedule", lambda d: [_schedule_game()])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: ls)

    plan = S.build_settlement_plan([bet])
    assert plan["still_pending"] == [] and plan["unresolved"] == []
    assert len(plan["proposed"]) == 1
    assert plan["proposed"][0]["new_result"] == "win"
    print("✓ build_settlement_plan settles a First 5 Innings Total bet on the HOME team correctly")


def test_build_settlement_plan_team_total_away_side_loss(monkeypatch):
    # Same real game/linescore as above, but the AWAY team's own total (Red Sox: 1 run) against
    # the same 1.5 line -> Over loses.
    bet = _bet(player="Boston Red Sox", player_id=None, market="First 5 Innings Total",
              side="Over", line=1.5)
    ls = _linescore([(1, 1, 0), (2, 0, 0), (3, 1, 1), (4, 0, 0), (5, 1, 0)])   # home: 3, away: 1
    monkeypatch.setattr(E, "get_schedule", lambda d: [_schedule_game()])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: ls)

    plan = S.build_settlement_plan([bet])
    assert len(plan["proposed"]) == 1
    assert plan["proposed"][0]["new_result"] == "loss"
    print("✓ build_settlement_plan settles a First 5 Innings Total bet on the AWAY team correctly, "
         "using that team's own real runs, not the home side's")


def test_build_settlement_plan_team_total_push(monkeypatch):
    # A real whole-number line landing on an exact tie -- end to end through build_settlement_
    # plan itself, not just settle_team_total_result in isolation (test_retro.py already covers
    # that function's own push logic directly; this confirms the real runs actually reach it).
    bet = _bet(player="New York Yankees", player_id=None, market="First 5 Innings Total",
              side="Over", line=3)
    ls = _linescore([(1, 1, 0), (2, 0, 0), (3, 1, 1), (4, 0, 0), (5, 1, 0)])   # home: 3, exact tie
    monkeypatch.setattr(E, "get_schedule", lambda d: [_schedule_game()])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: ls)

    plan = S.build_settlement_plan([bet])
    assert len(plan["proposed"]) == 1
    assert plan["proposed"][0]["new_result"] == "push"
    print("✓ build_settlement_plan settles a First 5 Innings Total to a real 'push' end to end "
         "when the real runs land exactly on a whole-number line")


def test_build_settlement_plan_team_total_incomplete_window_is_unresolved(monkeypatch):
    # Real, honest guard: only 4 of the first 5 innings actually happened (e.g. a suspended
    # game) -- settling against a partial count would be a WRONG result, not just an early one,
    # so this must land in unresolved, never a guessed win/loss.
    bet = _bet(player="New York Yankees", player_id=None, market="First 5 Innings Total",
              side="Over", line=1.5)
    ls = _linescore([(1, 1, 0), (2, 0, 0), (3, 1, 1), (4, 0, 0)])   # only 4 innings on record
    monkeypatch.setattr(E, "get_schedule", lambda d: [_schedule_game()])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: ls)

    plan = S.build_settlement_plan([bet])
    assert plan["proposed"] == []
    assert len(plan["unresolved"]) == 1
    assert "couldn't determine" in plan["unresolved"][0]["reason"]
    print("✓ build_settlement_plan refuses to settle a First 5 Innings Total against a partial, "
         "less-than-5-inning linescore, even though the game itself is confirmed Final")


def test_build_settlement_plan_team_total_unmatched_team_is_unresolved(monkeypatch):
    bet = _bet(player="Chicago Cubs", player_id=None, market="First 5 Innings Total",
              side="Over", line=1.5)
    monkeypatch.setattr(E, "get_schedule", lambda d: [_schedule_game()])
    fetch_calls = []
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fetch_calls.append(url) or {})

    plan = S.build_settlement_plan([bet])
    assert len(plan["unresolved"]) == 1
    assert "couldn't match team" in plan["unresolved"][0]["reason"]
    assert fetch_calls == []   # never even fetches the linescore for a team that isn't in this game
    print("✓ build_settlement_plan flags a First 5 Innings Total bet whose team doesn't match "
         "either real side of the game, without wasting a linescore fetch on it")


def test_build_settlement_plan_team_total_linescore_fetched_once_for_both_sides(monkeypatch):
    # Over AND Under on the SAME team+game (a real, common pattern -- hedging or a line move) --
    # the linescore must be fetched exactly once, not twice, same real cost guarantee the
    # existing boxscore-sharing test already establishes for player props.
    bet_over = _bet(id=1, player="New York Yankees", player_id=None, market="First 5 Innings Total",
                    side="Over", line=1.5)
    bet_under = _bet(id=2, player="New York Yankees", player_id=None, market="First 5 Innings Total",
                     side="Under", line=3.5)
    ls = _linescore([(1, 1, 0), (2, 0, 0), (3, 1, 1), (4, 0, 0), (5, 1, 0)])   # home: 3
    fetch_calls = []
    monkeypatch.setattr(E, "get_schedule", lambda d: [_schedule_game()])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fetch_calls.append(url) or ls)

    plan = S.build_settlement_plan([bet_over, bet_under])
    assert len(plan["proposed"]) == 2
    assert len(fetch_calls) == 1
    results = {p["bet_id"]: p["new_result"] for p in plan["proposed"]}
    assert results == {1: "win", 2: "win"}   # 3 runs: Over 1.5 wins, Under 3.5 also wins
    print("✓ build_settlement_plan fetches a game's own linescore exactly once even when "
         "multiple team-total bets (e.g. both sides of a line) reference it")


def test_build_settlement_plan_first_3_innings_total_settles_correctly(monkeypatch):
    # Real, confirmed DK market (verbatim from a real bet slip: "Team Total Runs - 1st 3
    # Innings") -- separate coverage from the First 5 Innings tests above, since an earlier
    # draft of this platform mistakenly treated only the 5-innings window as real. Runs after
    # inning 3 must be ignored: the away team scores 2 more in innings 4-5 here, which must NOT
    # count toward a First 3 Innings settlement.
    bet = _bet(player="Boston Red Sox", player_id=None, market="First 3 Innings Total",
              side="Over", line=0.5)
    ls = _linescore([(1, 0, 1), (2, 0, 0), (3, 0, 0), (4, 0, 1), (5, 0, 1)])   # away: 1 through
                                                                               # inning 3, 3 total
    monkeypatch.setattr(E, "get_schedule", lambda d: [_schedule_game()])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: ls)

    plan = S.build_settlement_plan([bet])
    assert len(plan["proposed"]) == 1
    assert plan["proposed"][0]["new_result"] == "win"   # 1 run through inning 3 > 0.5
    print("✓ build_settlement_plan settles a real First 3 Innings Total bet correctly, using "
         "only the first 3 innings' own runs, not the game's later innings")


def test_build_settlement_plan_first_3_and_first_5_dont_share_a_linescore_cache_entry(monkeypatch):
    # The SAME team+game, logged under BOTH windows (a real, plausible pattern -- someone bets
    # both the 1st-3 and 1st-5 team total on the same game). Each window needs its OWN linescore
    # read (a 3-inning count and a 5-inning count are genuinely different numbers), so this must
    # be 2 real fetches, not 1 -- the cache key is (gamePk, n_innings), not gamePk alone.
    bet_f3 = _bet(id=1, player="New York Yankees", player_id=None, market="First 3 Innings Total",
                 side="Over", line=0.5)
    bet_f5 = _bet(id=2, player="New York Yankees", player_id=None, market="First 5 Innings Total",
                 side="Over", line=2.5)
    ls = _linescore([(1, 1, 0), (2, 0, 0), (3, 0, 0), (4, 1, 0), (5, 1, 0)])   # home: 1 through
                                                                               # inning 3, 3 total
    fetch_calls = []
    monkeypatch.setattr(E, "get_schedule", lambda d: [_schedule_game()])
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: fetch_calls.append(url) or ls)

    plan = S.build_settlement_plan([bet_f3, bet_f5])
    assert len(fetch_calls) == 2   # NOT 1 -- (gamePk, 3) and (gamePk, 5) are genuinely different reads
    results = {p["bet_id"]: p["new_result"] for p in plan["proposed"]}
    assert results == {1: "win", 2: "win"}   # F3: 1 run > 0.5; F5: 3 runs > 2.5
    print("✓ build_settlement_plan reads the linescore separately per (game, n_innings) pair, "
         "so First 3 and First 5 Innings bets on the same game never share a stale cache entry")


# ----------------------------------------------------------------- build_settlement_plan: grouping
def test_build_settlement_plan_groups_by_date_fetches_schedule_once_per_date(monkeypatch):
    bet1 = _bet(id=1, slate_date="2026-07-24", player="A", player_id=555)
    bet2 = _bet(id=2, slate_date="2026-07-24", player="B", player_id=556,
               market="Batter Total Hits", side="Over", line=0.5)
    bet3 = _bet(id=3, slate_date="2026-07-25", player="C", player_id=557)

    schedule_calls = []

    def fake_schedule(d):
        schedule_calls.append(d)
        return [_schedule_game()]

    box = _boxscore(away_players={555: ("A", 1, 1, 4, 1, 1, 2), 556: ("B", 2, 0, 2, 0, 0, 1),
                                  557: ("C", 1, 1, 4, 1, 1, 2)})
    monkeypatch.setattr(E, "get_schedule", fake_schedule)
    monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)

    plan = S.build_settlement_plan([bet1, bet2, bet3])
    assert sorted(schedule_calls) == ["2026-07-24", "2026-07-25"]   # one call per real date, not per bet
    assert len(plan["proposed"]) == 3
    print("✓ build_settlement_plan fetches each real date's schedule exactly once, grouping bets correctly")


def test_build_settlement_plan_missing_slate_date_is_unresolved():
    bet = _bet(slate_date=None)
    plan = S.build_settlement_plan([bet])
    assert len(plan["unresolved"]) == 1
    assert "no slate_date" in plan["unresolved"][0]["reason"]


def test_build_settlement_plan_empty_input():
    plan = S.build_settlement_plan([])
    assert plan == {"proposed": [], "still_pending": [], "unresolved": []}


# ----------------------------------------------------------------- apply_settlement_plan
def test_apply_settlement_plan_calls_update_bet_for_each_proposed_change(monkeypatch):
    import betlog as B
    calls = []
    monkeypatch.setattr(B, "update_bet", lambda bet_id, **fields: calls.append((bet_id, fields)))

    proposed = [{"bet_id": 1, "new_result": "win", "old_result": "(unsettled)", "description": "x"},
               {"bet_id": 2, "new_result": "void", "old_result": "(unsettled)", "description": "y"}]
    count = S.apply_settlement_plan(proposed)

    assert count == 2
    assert calls == [(1, {"result": "win"}), (2, {"result": "void"})]
    print("✓ apply_settlement_plan calls update_bet exactly once per proposed change, with the correct new result")


def test_apply_settlement_plan_empty_list_does_nothing(monkeypatch):
    import betlog as B
    calls = []
    monkeypatch.setattr(B, "update_bet", lambda bet_id, **fields: calls.append(1))
    assert S.apply_settlement_plan([]) == 0
    assert calls == []


# ----------------------------------------------------------------- game-label normalization
def test_normalize_game_label_matches_abbreviation_to_full_name():
    # Regression guard for a real, confirmed bug: the Log a bet form's own placeholder text
    # ("HOU @ DET") teaches a format the schedule matcher, before this fix, could never actually
    # match (full names only, exact case) -- silently routing every manually-typed prop bet to
    # "unresolved" with a confusing "no player_id" reason that had nothing to do with the real
    # cause (the game itself was never found).
    assert S._normalize_game_label("HOU @ DET") == S._normalize_game_label("Houston Astros @ Detroit Tigers")
    assert S._normalize_game_label("hou @ det") == S._normalize_game_label("Houston Astros @ Detroit Tigers")
    assert S._normalize_game_label("houston astros @ detroit tigers") == "Houston Astros @ Detroit Tigers"
    print("✓ _normalize_game_label treats abbreviated, full-name, and mixed-case forms as identical")


def test_normalize_game_label_unrecognized_team_passes_through_honestly():
    # An unrecognized token should NOT silently match something wrong -- it passes through
    # unchanged, so a genuinely bad game label still correctly lands in "unresolved" rather than
    # being incorrectly matched to some other game.
    assert S._normalize_game_label("XYZ @ DET") == "XYZ @ Detroit Tigers"
    print("✓ an unrecognized team token passes through unchanged rather than guessing a match")


def test_build_settlement_plan_settles_a_bet_logged_with_abbreviated_team_names(monkeypatch):
    # End-to-end: a bet logged exactly the way the Log a bet form's own placeholder taught
    # ("HOU @ DET") now correctly matches and settles, instead of landing in unresolved.
    bet = _bet(player=None, player_id=None, market="Moneyline", side="Detroit Tigers", line=None,
              game="HOU @ DET")
    monkeypatch.setattr(E, "get_schedule",
                        lambda d: [_schedule_game(home="Detroit Tigers", away="Houston Astros",
                                                  home_score=5, away_score=2)])
    plan = S.build_settlement_plan([bet])
    assert len(plan["proposed"]) == 1
    assert plan["unresolved"] == []
    assert plan["proposed"][0]["new_result"] == "win"
    print("✓ build_settlement_plan correctly settles a bet logged with abbreviated team names, "
         "reproducing and confirming the fix for a real reported issue")


def test_build_settlement_plan_case_insensitive_game_label_also_matches(monkeypatch):
    bet = _bet(player=None, player_id=None, market="Moneyline", side="Detroit Tigers", line=None,
              game="houston astros @ detroit tigers")
    monkeypatch.setattr(E, "get_schedule",
                        lambda d: [_schedule_game(home="Detroit Tigers", away="Houston Astros",
                                                  home_score=5, away_score=2)])
    plan = S.build_settlement_plan([bet])
    assert len(plan["proposed"]) == 1
    print("✓ build_settlement_plan matches a lowercase-typed game label too")


# --------------------------------------------------------- (Game N) suffix (the real root cause)
def test_split_game_number_extracts_the_suffix():
    assert S._split_game_number("Houston Astros @ Detroit Tigers (Game 1)") == \
          ("Houston Astros @ Detroit Tigers", 1)
    assert S._split_game_number("Atlanta Braves @ New York Mets (Game 2)") == \
          ("Atlanta Braves @ New York Mets", 2)
    assert S._split_game_number("Houston Astros @ Detroit Tigers") == \
          ("Houston Astros @ Detroit Tigers", None)
    print("✓ _split_game_number correctly extracts a real suffix and returns None when there isn't one")


def test_build_settlement_plan_resolves_a_normal_game_despite_the_unconditional_game_1_suffix(monkeypatch):
    # Regression guard for a real, confirmed production bug, reproduced from an actual settlement
    # log: mlb_engine.py's own build_pitching_slate labels EVERY game "(Game 1)" unconditionally
    # (gameNumber defaults to 1 for every schedule entry, doubleheader or not), so a bet logged
    # from any model play carries that suffix even for a completely normal single game. Before
    # this fix, by_label's own keys never had the suffix, so this failed 6/6 times in the real
    # log this test reproduces -- not an edge case, the common case for every quick-logged bet.
    bet = _bet(player=None, player_id=None, market="Moneyline", side="Houston Astros", line=None,
              game="Houston Astros @ Los Angeles Angels (Game 1)")
    monkeypatch.setattr(E, "get_schedule",
                        lambda d: [_schedule_game(home="Los Angeles Angels", away="Houston Astros",
                                                  home_score=4, away_score=6, game_number=1)])
    plan = S.build_settlement_plan([bet])
    assert len(plan["proposed"]) == 1 and plan["unresolved"] == []
    assert plan["proposed"][0]["new_result"] == "win"
    print("✓ build_settlement_plan resolves a normal single game despite its bet's unconditional "
         "'(Game 1)' suffix, reproducing and confirming the fix for the real reported bug")


def test_build_settlement_plan_real_doubleheader_legs_settle_to_their_own_distinct_results(monkeypatch):
    # The case the fix must NOT break: a genuine doubleheader, where the two legs have real,
    # DIFFERENT results. Silently stripping the suffix and matching by team pairing alone (a
    # simpler but wrong fix) would risk grading both legs against the same one game.
    schedule = [
        _schedule_game(gamePk=1001, home="New York Mets", away="Atlanta Braves",
                       home_score=2, away_score=5, game_number=1),   # Braves win game 1
        _schedule_game(gamePk=1002, home="New York Mets", away="Atlanta Braves",
                       home_score=7, away_score=1, game_number=2),   # Braves lose game 2
    ]
    bet_g1 = _bet(id=1, player=None, player_id=None, market="Moneyline", side="Atlanta Braves",
                 line=None, game="Atlanta Braves @ New York Mets (Game 1)")
    bet_g2 = _bet(id=2, player=None, player_id=None, market="Moneyline", side="Atlanta Braves",
                 line=None, game="Atlanta Braves @ New York Mets (Game 2)")
    monkeypatch.setattr(E, "get_schedule", lambda d: schedule)
    plan = S.build_settlement_plan([bet_g1, bet_g2])
    g1 = next(p for p in plan["proposed"] if p["bet_id"] == 1)
    g2 = next(p for p in plan["proposed"] if p["bet_id"] == 2)
    assert g1["new_result"] == "win" and g2["new_result"] == "loss"
    print("✓ real doubleheader legs each settle to their own correct, distinct result")


def test_build_settlement_plan_ambiguous_suffixless_bet_on_a_real_doubleheader_stays_unresolved(monkeypatch):
    # A bet logged WITHOUT a "(Game N)" suffix, for a team pairing that genuinely has two games
    # that day, is truly ambiguous -- must stay unresolved for manual entry, never silently
    # guess which leg (and therefore which real result) the person meant.
    schedule = [
        _schedule_game(gamePk=1001, home="New York Mets", away="Atlanta Braves",
                       home_score=2, away_score=5, game_number=1),
        _schedule_game(gamePk=1002, home="New York Mets", away="Atlanta Braves",
                       home_score=7, away_score=1, game_number=2),
    ]
    bet = _bet(player=None, player_id=None, market="Moneyline", side="Atlanta Braves",
              line=None, game="Atlanta Braves @ New York Mets")
    monkeypatch.setattr(E, "get_schedule", lambda d: schedule)
    plan = S.build_settlement_plan([bet])
    assert plan["proposed"] == []
    assert len(plan["unresolved"]) == 1
    print("✓ a suffix-less bet for a genuine doubleheader correctly stays unresolved rather than "
         "guessing between two different real games")


# ----------------------------------------------------------------- retroactive player_id backfill
def test_backfill_player_id_via_update_bet_resolves_a_previously_stuck_bet(monkeypatch):
    # End-to-end regression guard for the new backfill tool's own workflow: a real bet, logged
    # with no player_id (exactly the state 5 real bets were found stuck in), first confirmed
    # unresolved with the specific "no player_id" reason, then backfilled through betlog.
    # update_bet -- the exact call the new Bet Log UI tool makes -- and re-checked to confirm it
    # NOW resolves via build_settlement_plan, using a real SQLite database round trip throughout.
    import tempfile
    import os
    import betlog as B

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        B.add_bet(db, slate_date="2026-07-28", game="Houston Astros @ Los Angeles Angels (Game 1)",
                 player="Wade Meckler", player_id=None, market="Batter Total Hits", side="Over",
                 line=0.5)
        bets = B.list_bets(db)
        assert len(bets) == 1 and bets[0].get("player_id") is None

        schedule = [_schedule_game(home="Los Angeles Angels", away="Houston Astros",
                                   home_score=4, away_score=6, game_number=1)]
        monkeypatch.setattr(E, "get_schedule", lambda d: schedule)

        # Step 1: confirm it's genuinely stuck on the missing-player_id reason before any fix.
        plan_before = S.build_settlement_plan(bets)
        assert plan_before["proposed"] == []
        assert len(plan_before["unresolved"]) == 1
        assert "no player_id" in plan_before["unresolved"][0]["reason"]

        # Step 2: the backfill tool's own action -- attach a real player_id via update_bet.
        bet_id = bets[0]["id"]
        B.update_bet(bet_id, db_path=db, player_id=663728)

        # Step 3: re-check settlement with the now-updated bet -- must resolve this time.
        updated_bets = B.list_bets(db)
        box = _boxscore(away_players={663728: ("Wade Meckler", 2, 0, 2, 0, 1, 1)})   # 2 hits -> win
        monkeypatch.setattr(E, "fetch_json", lambda url, params=None, retries=2: box)
        plan_after = S.build_settlement_plan(updated_bets)
        assert len(plan_after["proposed"]) == 1
        assert plan_after["proposed"][0]["new_result"] == "win"
        assert plan_after["unresolved"] == []
    print("✓ backfilling a player_id via update_bet (the new Bet Log tool's own action) correctly "
         "unblocks a previously-stuck bet through the real settlement pipeline")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"✗ {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
