"""Nov 18: conference / division schedule boxes list games earliest to latest, with the day when a week spans days."""
from datetime import datetime

import pytz

import components as C

ET = pytz.timezone("US/Eastern")


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _St:
    def __init__(self):
        self.out = []

    def markdown(self, s, **k):
        self.out.append(s)

    def caption(self, s, **k):
        self.out.append(s)

    def container(self, **k):
        return _Ctx()

    def columns(self, n):
        return [_Ctx() for _ in range(n if isinstance(n, int) else len(n))]


def _g(away, home, d, h, m=0):
    return {"away": away, "home": home, "dt": ET.localize(datetime(2026, 11, d, h, m)), "time_known": True}


def test_week_board_sorted_with_days(monkeypatch):
    fake = _St()
    monkeypatch.setattr(C, "st", fake)
    monkeypatch.setattr(C, "section_header", lambda *a, **k: None)
    acc = [_g("Syracuse", "Boston College", 21, 12), _g("Clemson", "Duke", 20, 19, 30), _g("Virginia Tech", "Miami", 21, 19)]
    C.todays_schedule_board({"grouped": {"ACC": {None: acc}}, "other": [], "has_divisions": False}, "🏈", "NCAAF")
    html = "".join(fake.out)
    assert html.index("Clemson") < html.index("Syracuse") < html.index("Virginia Tech")
    assert "Fri 7:30 PM ET" in html and "Sat 12:00 PM ET" in html


def test_one_day_board_keeps_plain_times(monkeypatch):
    fake = _St()
    monkeypatch.setattr(C, "st", fake)
    monkeypatch.setattr(C, "section_header", lambda *a, **k: None)
    games = [_g("A", "B", 21, 19), _g("C", "D", 21, 12)]
    C.todays_schedule_board({"grouped": {"East": {None: games}}, "other": [], "has_divisions": False}, "🏀", "NBA")
    html = "".join(fake.out)
    assert html.index(">C<") < html.index(">A<") and "12:00 PM ET" in html and "Sat " not in html
