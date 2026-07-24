"""
test_bet_settlement.py — offline tests for automated Bet Log result settlement.

Mocks mlb_engine's own fetches (get_schedule, fetch_json) and betlog's own write (update_bet) --
no network, no real database required.

    python test_bet_settlement.py    # or: pytest test_bet_settlement.py
"""

import mlb_engine as E
import bet_settlement as S


def _schedule_game(gamePk=999, home="New York Yankees", away="Boston Red Sox",
                   status="Final", home_score=5, away_score=3):
    return {"gamePk": gamePk, "status": status, "home_name": home, "away_name": away,
           "home_score": home_score, "away_score": away_score, "home_id": 147, "away_id": 111}


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
