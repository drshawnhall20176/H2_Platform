"""Nov 13: international hoops live (FIBA pages + FIBA LiveStats), the today/tomorrow slate, the capture guard."""
from datetime import date, datetime, timedelta, timezone

import intl_hoops as I
import intl_picks as IP
import live_games as LG

NOW = datetime(2026, 11, 13, 18, 30, tzinfo=timezone.utc)


def test_clock_parsing():
    assert LG._clock_min("05:12") == 5.2
    assert abs(LG._clock_min("02:53:00") - (2 + 53 / 60)) < 1e-9
    assert LG._clock_min("PT04M30S") == 4.5
    assert LG._clock_min("") is None


def test_genius_live_games(monkeypatch):
    feed = [{"matchId": 1, "matchTimeUTC": "2026-11-13 18:00:00", "matchStatus": "IN_PROGRESS", "live": 1,
             "homename": "Tindastoll", "awayname": "Keflavik", "homescore": 37, "awayscore": 33, "period": 2,
             "clock": "02:53:00", "periodType": "REGULAR"},
            {"matchId": 2, "matchTimeUTC": "2026-11-14 12:10:00", "matchStatus": "SCHEDULED", "live": 0,
             "homename": "A", "awayname": "B", "homescore": "", "awayscore": ""},
            {"matchId": 3, "matchTimeUTC": "2026-11-01 12:10:00", "matchStatus": "COMPLETE", "live": 0,
             "homename": "C", "awayname": "D", "homescore": "80", "awayscore": "70"}]
    monkeypatch.setattr(I, "genius_games", lambda lg, fetch=None: feed)
    gs = LG.genius_live_games("ICELAND", NOW.date(), now=NOW)
    assert [g["state"] for g in gs] == ["in"]           # tomorrow (17 h away) and Nov 1 are outside the live board
    g = gs[0]
    assert g["home_score"] == 37 and g["period"] == 2 and abs(g["clock_left"] - 2.883) < 0.01 and g["detail"] == "Q2 02:53"


def test_fiba_live_games(monkeypatch):
    page = [{"gameId": 9, "gameDateTimeUTC": "2026-11-13T17:30:00", "isLive": True, "teamAScore": 50, "teamBScore": 48,
             "currentPeriod": "Q3", "chrono": "04:10", "teamA": {"shortName": "Tenerife"}, "teamB": {"shortName": "Unicaja"},
             "statusCode": "VALID"}]
    monkeypatch.setattr(I, "fiba_season", lambda *a, **k: page)
    g = LG.fiba_live_games("BCL", NOW.date(), now=NOW)[0]
    assert g["state"] == "in" and g["period"] == 3 and abs(g["clock_left"] - 4.1667) < 0.01 and g["home"] == "Tenerife"


def test_slate_window_and_round_trip():
    picks = [{"kickoff": "2026-11-13T23:00:00+00:00"}, {"kickoff": "2026-11-15T03:00:00+00:00"},   # today, tmrw night
             {"kickoff": "2026-11-16T18:00:00+00:00"}, {"kickoff": "2026-11-12T18:00:00+00:00"}]   # too late / earlier
    assert IP.games_in_window(picks, NOW) == 2
    store = {}
    IP.save_slate({"ICELAND": 1, "EUROLEAGUE": 3}, save=store.__setitem__)
    assert IP.slate_leagues(get=store.get) == ["EUROLEAGUE", "ICELAND"]
    assert IP.slate_leagues(get=lambda k: None) is None


def test_triggered_runs_wait_150_minutes():
    recent = (NOW - timedelta(minutes=60)).isoformat()
    old = (NOW - timedelta(minutes=200)).isoformat()
    assert IP.too_soon(get=lambda k: recent, now=NOW)
    assert not IP.too_soon(get=lambda k: old, now=NOW)
    assert not IP.too_soon(get=lambda k: None, now=NOW)


def test_intl_hoops_page_shows_only_slate_leagues(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    import model_store as MS
    monkeypatch.setattr(IP, "slate_leagues", lambda get=None: ["ICELAND", "EUROLEAGUE"])
    monkeypatch.setattr(MS, "load_game_picks", lambda *a, **k: [])
    monkeypatch.setattr(LG, "games", lambda lg, day, fetch=None: [
        {"league": lg, "id": "1", "home": "Tindastoll", "away": "Keflavik", "home_score": 37, "away_score": 33,
         "state": "in", "period": 2, "clock_left": 2.9, "detail": "Q2 02:53", "kickoff": NOW.isoformat(),
         "halftime": False}] if lg == "ICELAND" else [])
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "44_Intl_Hoops.py"), default_timeout=60)
    at.session_state["sport"] = "INTL"
    at.session_state["ih_league"] = "ICELAND"
    at.run()
    assert not at.exception, at.exception
    assert list(at.radio[0].options) == ["Iceland Premier League", "EuroLeague"] or \
        set(at.radio[0].options) == {"Iceland Premier League", "EuroLeague"}
    assert any("In progress" in m.value for m in at.markdown)
