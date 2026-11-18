from datetime import date
import lab_schedule as LS


def _p(league, home, away, ko, **kw):
    d = {"sport": league, "home": home, "away": away, "kickoff": ko}
    d.update(kw)
    return d


def test_rows_filter_by_eastern_date_sort_and_dedupe():
    picks = {"EUROLEAGUE": [_p("EUROLEAGUE", "Real Madrid", "Olympiacos", "2026-11-19T19:45:00+00:00"),
                            _p("EUROLEAGUE", "Real Madrid", "Olympiacos", "2026-11-19T19:45:00+00:00"),   # duplicate capture
                            _p("EUROLEAGUE", "Fenerbahce", "Monaco", "2026-11-19T17:15:00+00:00"),
                            _p("EUROLEAGUE", "Late", "Game", "2026-11-20T03:30:00+00:00")]}               # 10:30 pm ET on the 19th
    r = LS.rows("INTL", picks, date(2026, 11, 19))
    assert [x["Match"] for x in r] == ["Monaco @ Fenerbahce", "Olympiacos @ Real Madrid", "Game @ Late"]
    assert all(x["Status"] == "Scheduled" for x in r)


def test_tennis_rows_and_final_status():
    picks = {"TENNIS": [_p("TENNIS", "Sinner", "Alcaraz", "2026-11-19T13:00:00+00:00", tour="ATP",
                           tournament="Finals", final_home=2, final_away=1, result="W")]}
    r = LS.rows("TENNIS", picks, date(2026, 11, 19))
    assert r[0]["Match"] == "Sinner vs Alcaraz" and r[0]["Event"] == "ATP · Finals" and r[0]["Status"].startswith("Final")


def test_load_uses_loader_per_league():
    got = LS.load("TENNIS", loader=lambda lg: [{"kickoff": "2026-11-19T13:00:00+00:00", "home": "A", "away": "B"}])
    assert list(got) == ["TENNIS"] and len(got["TENNIS"]) == 1
