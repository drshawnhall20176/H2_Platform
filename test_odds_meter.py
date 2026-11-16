"""Nov 16: the Odds API credit meter, the snapshot window and the long-shots scan's saved offers."""
import os
from datetime import datetime, timedelta, timezone

import odds_meter as OM

NOW = datetime(2026, 11, 16, 15, tzinfo=timezone.utc)
ODDS = "https://api.the-odds-api.com/v4/sports/basketball_nba"


def _clear():
    with OM._lock:
        OM._pending.clear()


def test_feed_names_the_sport_and_kind_of_call():
    assert OM.feed(ODDS + "/events/abc123/odds") == "basketball_nba props"
    assert OM.feed(ODDS + "/odds") == "basketball_nba lines"
    assert OM.feed(ODDS + "/events") == "basketball_nba lists"
    assert OM.feed("https://api.the-odds-api.com/v4/historical/sports/soccer_epl/odds") == "soccer_epl historical"
    assert OM.feed("https://api.the-odds-api.com/v4/sports") == "other"


def test_job_is_the_workflow_and_marks_hand_started_runs(monkeypatch):
    for k in ("ODDS_JOB", "GITHUB_WORKFLOW", "GITHUB_EVENT_NAME", "AUDIENCE"):
        monkeypatch.delenv(k, raising=False)
    assert OM.job() == "app"
    monkeypatch.setenv("AUDIENCE", "public")
    assert OM.job() == "app-public"
    monkeypatch.setenv("GITHUB_WORKFLOW", "warm-slates")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    assert OM.job() == "warm-slates"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    assert OM.job() == "warm-slates (manual)"
    monkeypatch.setenv("ODDS_JOB", "backfill")
    assert OM.job() == "backfill"


def test_record_counts_only_odds_api_calls_and_never_raises(monkeypatch):
    _clear()
    monkeypatch.setenv("ODDS_JOB", "t")
    assert OM.record("https://site.api.espn.com/x", {"x-requests-last": "5"}, NOW) == 0
    assert OM.record(ODDS + "/events/e1/odds", {"x-requests-last": "12", "x-requests-remaining": "74000"}, NOW) == 12
    assert OM.record(ODDS + "/events/e2/odds", {"x-requests-last": "9", "x-requests-remaining": "73991"}, NOW) == 9
    assert OM.record(ODDS + "/events", {}, NOW) == 0                       # free call: counted as a call, 0 credits
    assert OM.record(ODDS + "/odds", None, NOW) == 0 and OM.record(None, object(), NOW) == 0
    got = OM.pending()
    assert got[("2026-11-16", "t", "basketball_nba props")] == [21, 2]
    assert got[("2026-11-16", "t", "basketball_nba lists")] == [0, 1]
    assert len(got) == 2
    _clear()


def test_flush_saves_adds_up_and_keeps_counts_when_nothing_was_saved(tmp_path, monkeypatch):
    import model_store as MS
    _clear()
    monkeypatch.setenv("ODDS_JOB", "warm-slates")
    db = str(tmp_path / "m.db")
    OM.record(ODDS + "/events/e1/odds", {"x-requests-last": "12", "x-requests-remaining": "500"}, NOW)
    assert OM.flush() == 0 and OM.pending()                                 # a test run never writes the real store
    assert OM.flush(db_path=db) == 1 and not OM.pending()
    OM.record(ODDS + "/events/e2/odds", {"x-requests-last": "8", "x-requests-remaining": "492"}, NOW)
    monkeypatch.setenv("ODDS_JOB", "research (manual)")
    OM.record("https://api.the-odds-api.com/v4/historical/sports/basketball_nba/odds",
              {"x-requests-last": "30", "x-requests-remaining": "462"}, NOW)
    assert OM.flush(db_path=db) == 2
    rows = MS.odds_usage("2026-11-10", db_path=db)
    assert {(r["job"], r["feed"]): (r["credits"], r["calls"]) for r in rows} == {
        ("warm-slates", "basketball_nba props"): (20, 2), ("research (manual)", "basketball_nba historical"): (30, 1)}
    assert MS.odds_usage("2026-11-17", db_path=db) == []
    assert MS.odds_remaining(db_path=db)["remaining"] == 462
    assert OM.by_job(rows)[0] == {"day": "2026-11-16", "job": "research (manual)", "credits": 30, "calls": 1}
    assert OM.by_day(rows) == [{"day": "2026-11-16", "credits": 50, "calls": 3}]


def test_odds_api_get_reports_to_the_meter(monkeypatch):
    import odds_api as O
    _clear()
    monkeypatch.setenv("ODDS_JOB", "t")

    class R:
        status_code = 200
        headers = {"x-requests-last": "3", "x-requests-remaining": "10", "x-requests-used": "90"}

        def json(self):
            return []
    monkeypatch.setattr(O.requests, "get", lambda *a, **k: R())
    data, hdr = O._get("sports/icehockey_nhl/odds", {"apiKey": "k"})
    assert data == [] and hdr == {"remaining": "10", "used": "90"}
    assert sum(c for c, _n in OM.pending().values()) == 3
    assert any(k[2] == "icehockey_nhl lines" for k in OM.pending())
    _clear()


def test_snapshots_only_price_games_starting_within_a_day():
    import capture_line_snapshots as CLS
    iso = lambda h: (NOW + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")   # noqa: E731
    evs = [{"id": "started", "commence_time": iso(-1)}, {"id": "tonight", "commence_time": iso(6)},
           {"id": "edge", "commence_time": iso(24)}, {"id": "sunday", "commence_time": iso(100)},
           {"id": "bad", "commence_time": "?"}]
    assert [e["id"] for e in CLS.starting_soon(evs, now=NOW)] == ["tonight", "edge"]
    assert CLS.SNAPSHOT_HOURS == 24


def test_scan_reuses_a_fresh_saved_board_and_fetches_when_it_is_old(monkeypatch):
    import best_bets_data as BBD
    offers = [{"market": "player_assists", "player": "A", "point": 5.5, "over": {"draftkings": -110}, "under": {}}]
    store = {BBD.OFFERS_KEY.format(sport="NBA", date="2026-11-16"): {"at": (NOW - timedelta(minutes=10)).isoformat(),
                                                                    "offers": offers}}
    assert BBD.saved_offers("NBA", "2026-11-16", now=NOW, get=store.get) == offers
    assert BBD.saved_offers("NBA", "2026-11-16", now=NOW + timedelta(hours=2), get=store.get) is None
    assert BBD.saved_offers("NHL", "2026-11-16", now=NOW, get=store.get) is None
    assert BBD.saved_offers("NBA", "2026-11-16", now=NOW, get=lambda k: {"at": "junk", "offers": offers}) is None
    calls = []
    monkeypatch.setattr(BBD, "fetch_generic_offers", lambda s, d, k: calls.append(s) or ["live"])
    monkeypatch.setattr(BBD, "saved_offers", lambda s, d: offers if s == "NBA" else None)
    assert BBD.recent_offers("NBA", "2026-11-16", "k") == offers and calls == []
    assert BBD.recent_offers("NHL", "2026-11-16", "k") == ["live"] and calls == ["NHL"]


def test_only_scheduled_jobs_save_the_board_offers(monkeypatch):
    import best_bets_data as BBD
    import model_store as MS
    saved = {}
    monkeypatch.setattr(MS, "save_setting", lambda k, v, db_path=None: saved.__setitem__(k, v) or True)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    BBD._keep_offers("NBA", "2026-11-16", [{"player": "A"}])
    assert saved == {}
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    BBD._keep_offers("NBA", "2026-11-16", [])
    assert saved == {}
    BBD._keep_offers("NBA", "2026-11-16", [{"player": "A"}])
    assert saved["slate_offers:NBA:2026-11-16"]["offers"] == [{"player": "A"}]
