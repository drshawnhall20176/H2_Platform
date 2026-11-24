import json

import h2h as H


class _R:
    def __init__(self, j):
        self.status_code, self._j = 200, j

    def json(self):
        return self._j


def _ev(d, me, op, ms, os_):
    return {"date": d + "T00:00Z", "competitions": [{"status": {"type": {"completed": True}}, "competitors": [
        {"id": me, "score": {"value": ms}}, {"id": op, "score": {"value": os_}}]}]}


def _http(url, params=None, timeout=None):
    if url.endswith("/teams"):
        return _R({"sports": [{"leagues": [{"teams": [{"team": {"id": "1", "displayName": "Boston Celtics"}},
                                                      {"team": {"id": "2", "displayName": "New York Knicks"}}]}]}]})
    if params.get("season") == "2027":
        return _R({"events": [_ev("2026-11-01", "1", "2", 110, 100), _ev("2026-11-05", "1", "3", 90, 99)]})
    return _R({"events": [_ev("2026-03-01", "1", "2", 95, 101), _ev("2026-01-10", "1", "2", 120, 104)]})


def test_build_reads_the_home_teams_schedule_for_both_seasons():
    out = H.build("NBA", [{"home": "Boston Celtics", "away": "New York Knicks"}], "2026-11-24", http=_http)
    txt = out["Boston Celtics|New York Knicks"]
    assert txt.startswith("Boston Celtics won 2 of 3") and "last: Boston Celtics by 10, Nov 1, 2026" in txt


def test_describe_handles_no_meetings_and_a_split():
    assert H.describe("A", "B", []) == "No meetings in the last year"
    t = H.describe("A", "B", [{"date": "2026-11-01", "margin": 5}, {"date": "2026-02-01", "margin": -2}])
    assert t.startswith("Split 1–1")


def test_refresh_saves_one_blob_per_league_and_lookup_reads_it():
    saved = {}
    H.refresh("2026-11-24", leagues=("NBA",), http=_http,
              load=lambda lg: [{"home": "Boston Celtics", "away": "New York Knicks", "kickoff": "2026-11-25T00:30:00Z"}],
              save=saved.update, out=lambda *a: None)
    assert "NBA|2026-11-24" in saved
    H._MEM.clear()
    got = H.lookup("NBA", "Boston Celtics", "New York Knicks", day="2026-11-24", load=saved.get)
    assert got.startswith("Boston Celtics won 2 of 3")
    assert H.lookup("NBA", "X", "Y", day="2026-11-24", load=saved.get) == "—"
