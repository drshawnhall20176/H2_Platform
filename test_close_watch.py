"""close_watch (Nov 6): closing prices captured before each game with an open bet."""
from datetime import datetime, timedelta, timezone


EV = {"id": "e1", "home_team": "Boston Celtics", "away_team": "Milwaukee Bucks", "commence_time": "2026-11-06T00:30:00Z"}
JS = {"bookmakers": [{"key": "draftkings", "markets": [
    {"key": "spreads", "outcomes": [{"name": "Boston Celtics", "price": -120, "point": -11.5},
                                    {"name": "Milwaukee Bucks", "price": 100, "point": 11.5}]},
    {"key": "totals", "outcomes": [{"name": "Over", "price": -105, "point": 213.5}]},
    {"key": "h2h", "outcomes": [{"name": "Boston Celtics", "price": -700}]}]}]}


def _bet(i, **kw):
    b = {"id": i, "sport": "NBA", "game": "Milwaukee Bucks @ Boston Celtics", "book": "draftkings", "entry_odds": -110,
         "market": "Spread", "side": "Boston Celtics", "line": -11.5}
    b.update(kw)
    return b


def test_game_line_prices_match_book_side_and_line():
    import close_watch as W
    assert W.game_line_price(_bet(1), JS) == -120
    assert W.game_line_price(_bet(2, line=-12.5), JS) is None                      # line moved off the number
    assert W.game_line_price(_bet(3, market="Total", side="Over", line=213.5), JS) == -105
    assert W.game_line_price(_bet(4, market="Moneyline", line=0.0), JS) == -700
    assert W.game_line_price(_bet(5, book="fanduel"), JS) is None


def test_watchable_and_plan():
    import close_watch as W
    assert not W.watchable(_bet(1, notes="Live spread"))
    assert not W.watchable(_bet(2, market="Parlay", ticket="T"))
    assert W.watchable(_bet(3))
    games = W.plan([_bet(1), _bet(2, game="Somebody @ Else")], {"NBA": [EV]})
    assert len(games) == 1 and [b["id"] for b in games[0][3]] == [1]


def test_run_captures_at_each_lead(monkeypatch):
    import betlog as B
    import close_watch as W
    t = [datetime(2026, 11, 5, 23, 0, tzinfo=timezone.utc)]
    writes, fetches = [], []
    monkeypatch.setattr(B, "list_bets", lambda **kw: [_bet(1)])
    monkeypatch.setattr(B, "update_bet", lambda i, **kw: writes.append((i, kw["close_odds"])))
    monkeypatch.setattr(W, "_events", lambda key, sp: {"NBA": [EV]})
    monkeypatch.setattr(W, "capture_event", lambda e, bets, key, sp: fetches.append(t[0]) or {1: -120})
    def sleep(s):
        t[0] += timedelta(seconds=s)
    W.run("k", minutes=120, now_fn=lambda: t[0], sleep_fn=sleep)
    assert [f.strftime("%H:%M") for f in fetches] == ["23:45", "00:25"]
    assert writes == [(1, -120), (1, -120)]
