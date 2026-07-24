"""
test_settle_results.py — offline tests for settle_results.py's settlement logic.

No network, no real database — sports/betlog calls are monkeypatched. Focus is the actual real
requirement: settlement must be correct (reusing retro.py's own already-tested grade_play, not
new logic) and must skip rather than guess whenever it can't be honestly determined — a wrong
automated settlement would silently corrupt a real trade record.

    python test_settle_results.py    # or: pytest test_settle_results.py
"""

import settle_results as S


def _bet(bet_id=1, player_id=660271, market="Batter Total Hits", side="Over", line=0.5,
        slate_date="2026-07-20", sport="MLB"):
    return {"id": bet_id, "player_id": player_id, "market": market, "side": side, "line": line,
           "slate_date": slate_date, "sport": sport}


# ----------------------------------------------------------------- settle_bet
def test_settle_bet_real_win():
    results = {660271: {"name": "Test Player", "hits": 2}}
    assert S.settle_bet(_bet(market="Batter Total Hits", side="Over", line=0.5), results) == "win"
    print("✓ settle_bet correctly settles a real win via retro.grade_play")


def test_settle_bet_real_loss():
    results = {660271: {"name": "Test Player", "hits": 0}}
    assert S.settle_bet(_bet(market="Batter Total Hits", side="Over", line=0.5), results) == "loss"
    print("✓ settle_bet correctly settles a real loss via retro.grade_play")


def test_settle_bet_under_side():
    results = {660271: {"name": "Test Player", "p_k": 3}}
    assert S.settle_bet(_bet(market="Pitcher Strikeouts", side="Under", line=5.5), results) == "win"
    print("✓ settle_bet correctly settles an Under-side bet")


def test_settle_bet_missing_player_id_returns_none():
    results = {660271: {"name": "Test Player", "hits": 2}}
    bet = _bet(player_id=None)
    assert S.settle_bet(bet, results) is None
    print("✓ settle_bet correctly refuses to settle a bet with no player_id, rather than guess by name")


def test_settle_bet_player_not_in_results_returns_none():
    results = {999999: {"name": "Someone Else", "hits": 2}}   # different player entirely
    assert S.settle_bet(_bet(player_id=660271), results) is None
    print("✓ settle_bet correctly returns None when the player has no recorded result (didn't appear)")


def test_settle_bet_market_not_recognized_returns_none():
    results = {660271: {"name": "Test Player", "hits": 2}}
    bet = _bet(market="Not A Real Market")
    assert S.settle_bet(bet, results) is None
    print("✓ settle_bet correctly returns None for a market retro.MARKET_STAT doesn't recognize")


def test_settle_bet_never_returns_push():
    # A real, stated, honest limitation: settle_bet only ever returns "win"/"loss"/None, since
    # retro.grade_play's own .5-line design structurally can't push.
    results = {660271: {"name": "Test Player", "hits": 1}}
    result = S.settle_bet(_bet(line=0.5), results)
    assert result in ("win", "loss")
    print("✓ settle_bet never fabricates a push result")


# ----------------------------------------------------------------- settle_for_sport
def test_settle_for_sport_groups_by_slate_date_not_per_bet(monkeypatch):
    calls = []

    class FakeEngine:
        @staticmethod
        def get_player_results(date_str):
            calls.append(date_str)
            return {660271: {"hits": 2}, 660272: {"hits": 0}}

    class FakeSport:
        engine = FakeEngine()

    import sports
    monkeypatch.setattr(sports, "get", lambda key: FakeSport())

    bets = [
        _bet(bet_id=1, player_id=660271, slate_date="2026-07-20"),
        _bet(bet_id=2, player_id=660272, slate_date="2026-07-20"),   # SAME date as bet 1
        _bet(bet_id=3, player_id=660271, slate_date="2026-07-21"),   # a DIFFERENT date
    ]
    report = S.settle_for_sport("MLB", bets)
    assert calls == ["2026-07-20", "2026-07-21"]   # one call per DISTINCT date, not per bet
    assert report["dates_checked"] == 2
    print("✓ settle_for_sport calls get_player_results once per distinct slate date, not once per bet")


def test_settle_for_sport_real_settlement_report(monkeypatch):
    class FakeEngine:
        @staticmethod
        def get_player_results(date_str):
            return {660271: {"hits": 2}}   # only one real player has a result

    class FakeSport:
        engine = FakeEngine()

    import sports
    monkeypatch.setattr(sports, "get", lambda key: FakeSport())

    bets = [
        _bet(bet_id=1, player_id=660271, market="Batter Total Hits", side="Over", line=0.5),  # real win
        _bet(bet_id=2, player_id=None),                                                       # no player_id
        _bet(bet_id=3, player_id=999999),                                                     # no result for this player
    ]
    report = S.settle_for_sport("MLB", bets)
    assert report["settled"] == {1: "win"}
    assert report["skipped_no_player_id"] == [2]
    assert report["skipped_no_match"] == [3]
    print("✓ settle_for_sport correctly sorts real settlements, no-player-id skips, and no-match skips")


def test_settle_for_sport_no_final_games_yet_settles_nothing(monkeypatch):
    class FakeEngine:
        @staticmethod
        def get_player_results(date_str):
            return {}   # no final games yet on this date

    class FakeSport:
        engine = FakeEngine()

    import sports
    monkeypatch.setattr(sports, "get", lambda key: FakeSport())

    bets = [_bet(bet_id=1, player_id=660271)]
    report = S.settle_for_sport("MLB", bets)
    assert report["settled"] == {}
    assert report["skipped_no_match"] == []   # not even attempted -- correctly deferred to a later run
    print("✓ settle_for_sport correctly settles nothing (not even a skip) when no games are final yet")


def test_settle_for_sport_missing_slate_date_skipped():
    bets = [_bet(bet_id=1, slate_date=None)]
    report = S.settle_for_sport("MLB", bets)
    assert report["skipped_no_match"] == [1]
    print("✓ settle_for_sport correctly skips a bet with no slate_date at all, rather than crash")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            if "monkeypatch" in t.__code__.co_varnames:
                print(f"SKIP  {t.__name__} (needs pytest's monkeypatch fixture, run via pytest)")
                continue
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed (monkeypatch tests need pytest)")
