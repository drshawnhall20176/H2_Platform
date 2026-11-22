"""ledger_close (Nov 22): every shown pick's close, captured minutes before its start."""
from datetime import datetime, timedelta, timezone

EV = {"id": "e9", "home_team": "Miami Hurricanes", "away_team": "Virginia Tech Hokies",
      "commence_time": "2026-11-22T00:00:00Z"}
JS = {"away_team": "Virginia Tech Hokies", "home_team": "Miami Hurricanes", "bookmakers": [
    {"key": "fanduel", "title": "FanDuel", "markets": [
        {"key": "player_receptions", "outcomes": [
            {"name": "Over", "description": "Daylyn Upshaw", "point": 4.5, "price": 110},
            {"name": "Under", "description": "Daylyn Upshaw", "point": 4.5, "price": -150},
            {"name": "Over", "description": "Eugene Wilson", "point": 2.5, "price": -105},
            {"name": "Under", "description": "Eugene Wilson", "point": 2.5, "price": -115}]},
        {"key": "h2h", "outcomes": [{"name": "Miami Hurricanes", "price": -300},
                                    {"name": "Virginia Tech Hokies", "price": 240}]},
        {"key": "spreads", "outcomes": [{"name": "Virginia Tech Hokies", "point": 8.5, "price": -110}]}]},
    {"key": "betonlineag", "title": "BetOnline.ag", "markets": [
        {"key": "h2h", "outcomes": [{"name": "Virginia Tech Hokies", "price": 255}]},
        {"key": "spreads", "outcomes": [{"name": "Virginia Tech Hokies", "point": 9.5, "price": -112}]}]}]}


def _prop(**kw):
    r = {"_key": "NCAAF|1|Receptions|Under", "_day": "2026-11-21", "sport": "NCAAF", "player": "Daylyn Upshaw",
         "market": "Receptions", "side": "Under", "line": 4.5, "price": -144, "book": "fanduel",
         "game": "Virginia Tech @ Miami", "time": "7:00 PM"}
    r.update(kw)
    return r


def _game(**kw):
    r = {"_key": "e9|Moneyline|away", "_day": "2026-11-21", "sport": "NCAAF", "money_market": "Moneyline",
         "money_side": "away", "price": 230, "book": "BetOnline.ag", "game": "Virginia Tech @ Miami",
         "game_id": "e9", "kickoff": "2026-11-22T00:00:00Z"}
    r.update(kw)
    return r


def test_team_names_and_event_match():
    import ledger_close as LC
    assert LC.same_team("Miami", "Miami Hurricanes")
    assert LC.same_team("San José St Spartans", "San Jose State Spartans")
    assert not LC.same_team("Miami", "Virginia Tech Hokies")
    kick = datetime(2026, 11, 22, 0, 0, tzinfo=timezone.utc)
    assert LC.match_event("Virginia Tech @ Miami", [EV], kick)["id"] == "e9"
    assert LC.match_event("Virginia Tech @ Miami", [EV], kick + timedelta(hours=6)) is None    # another day's game
    assert LC.match_event("anything", [EV], None, game_id="e9")["id"] == "e9"


def test_prop_close_same_line_moved_line_and_other_book():
    import ledger_close as LC
    assert LC.prop_close(_prop(), JS, "player_receptions") == {"line": 4.5, "price": -150, "book": "fanduel"}
    moved = LC.prop_close(_prop(player="Eugene Wilson", line=3.5), JS, "player_receptions")
    assert moved["line"] == 2.5 and moved["price"] == -115                      # the book's number now
    assert LC.prop_close(_prop(book="draftkings"), JS, "player_receptions") is None


def test_game_close_own_book_then_best():
    import ledger_close as LC
    assert LC.game_close(_game(), JS)["price"] == 255                           # BetOnline.ag, by its title
    assert LC.game_close(_game(book=0.61), JS)["price"] == 255                  # no book: the best price
    sp = LC.game_close(_game(money_market="Spread", money_line=8.5, book="FanDuel"), JS)
    assert sp["line"] == 8.5 and sp["price"] == -110


def test_grading_prefers_the_watched_close(monkeypatch):
    import ledger_close as LC
    import pick_ledger as PL
    caps = {"NCAAF|1|Receptions|Under|fanduel": {"line": 4.5, "price": -160, "at": "x"},
            "e9|Moneyline|away|betonlineag": {"line": None, "price": 270, "at": "y"}}
    monkeypatch.setattr(LC, "load", lambda day, get=None: caps)
    c = PL.watched_close("2026-11-21", _prop())
    assert c["clv_mark"] == "beat" and c["close_src"] == "watch"                # -144 to -160: the market agreed
    g = PL.watched_close("2026-11-21", _game())
    assert g["clv_mark"] == "lost"                                              # +230 to +270: the market went against us
    assert PL.watched_close("2026-11-21", _prop(book="draftkings")) is None     # nothing captured: the old way


def test_watcher_captures_shown_picks_until_the_start(monkeypatch):
    import betlog as B
    import close_watch as W
    t = [datetime(2026, 11, 21, 22, 30, tzinfo=timezone.utc)]
    saved, fetches = [], []
    monkeypatch.setattr(B, "list_bets", lambda **kw: [])
    monkeypatch.setattr(W, "_events", lambda key, sp: {"NCAAF": [EV]})
    monkeypatch.setattr(W, "capture_ledger", lambda e, rows, key, sp: fetches.append(t[0]) or
                        {"NCAAF|1|Receptions|Under|fanduel": {"line": 4.5, "price": -150, "at": "z"}})

    def sleep(s):
        t[0] += timedelta(seconds=s)
    W.run("k", minutes=180, now_fn=lambda: t[0], sleep_fn=sleep, ledger_fn=lambda now: [_prop()],
          save_fn=lambda d, caps: saved.append((d, dict(caps))))
    assert [f.strftime("%H:%M") for f in fetches] == ["23:00", "23:30", "23:45", "23:55"]
    assert saved[-1][0] == "2026-11-21" and saved[-1][1]["NCAAF|1|Receptions|Under|fanduel"]["lead"] == 5


def test_a_late_start_takes_only_the_latest_due_capture(monkeypatch):
    import betlog as B
    import close_watch as W
    t = [datetime(2026, 11, 21, 23, 40, tzinfo=timezone.utc)]                   # 20 minutes before the start
    fetches = []
    monkeypatch.setattr(B, "list_bets", lambda **kw: [])
    monkeypatch.setattr(W, "_events", lambda key, sp: {"NCAAF": [EV]})
    monkeypatch.setattr(W, "capture_ledger", lambda e, rows, key, sp: fetches.append(t[0]) or {})

    def sleep(s):
        t[0] += timedelta(seconds=s)
    W.run("k", minutes=60, now_fn=lambda: t[0], sleep_fn=sleep, ledger_fn=lambda now: [_prop()],
          save_fn=lambda d, caps: None)
    assert [f.strftime("%H:%M") for f in fetches] == ["23:40", "23:45", "23:55"]
