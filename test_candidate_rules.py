"""candidate_rules (Nov 23): the close-gap rule recorded pre-game, graded with the ledgers, shown as a forward record."""
from datetime import datetime, timezone

import pytest

import candidate_rules as CR
import game_previews as GP
import pick_ledger as PL

NOW = datetime(2026, 11, 23, 14, 0, tzinfo=timezone.utc)          # 9 AM New York


def _g(gid, hs, mm, ko="2026-11-23T16:00:00+00:00", home="H", away="A"):
    return {"game_id": gid, "kickoff": ko, "home": home, "away": away, "home_spread": hs, "model_margin": mm}


def test_only_close_unstarted_games_today_qualify_on_the_models_side():
    recs = [_g("a", -5.0, 4.3), _g("b", 3.5, -2.2), _g("c", -10.0, 4.0), _g("d", -5.0, 5.0),
            _g("e", -5.0, 4.3, ko="2026-11-23T13:00:00+00:00"), _g("f", -5.0, 4.3, ko="2026-11-24T16:00:00+00:00")]
    got = {p["game_id"]: p for p in CR.picks(recs, "2026-11-23", NOW)}
    assert set(got) == {"a", "b"}                                   # c: 6 apart; d: no side; e: started; f: tomorrow
    assert got["a"]["pick"] == "A +5" and got["a"]["money_side"] == "away" and got["a"]["money_line"] == 5.0
    assert got["b"]["pick"] == "H +3.5" and got["b"]["money_side"] == "home"


@pytest.fixture
def store(monkeypatch):
    s = {}
    import model_store as MS
    monkeypatch.setattr(MS, "get_setting", lambda k, d=None: s.get(k, d))
    monkeypatch.setattr(MS, "save_setting", lambda k, v: s.__setitem__(k, v))
    return s


def test_recorded_once_graded_and_shown_as_a_forward_record(store):
    recs = [_g("a", -5.0, 4.3)]
    assert CR.record("2026-11-23", NOW, load=lambda sp: recs) == 1
    assert CR.record("2026-11-23", NOW, load=lambda sp: recs) == 0          # first sighting wins
    key = PL.KEY.format(kind=CR.KIND, sport="NCAAMB", day="2026-11-23")
    rows = store[key]["rows"]
    PL.grade_games("2026-11-23", list(rows.values()), recs={"a": dict(recs[0], final_home=70, final_away=72)})
    store[key] = dict(store[key], graded_at="x")
    assert list(rows.values())[0]["result"] == "win"                        # A +5, lost by 2
    line = CR.status_line("NCAAMB", "2026-11-23")
    assert "1–0" in line and "Not a bet yet" in line and "200 graded games" in line
    assert CR.status_line("NHL", "2026-11-23") == ""


def test_the_agreement_column():
    assert GP.agreement(_g("a", -5.0, 4.3)) == "✅ Agree"
    assert GP.agreement(_g("a", -5.0, 9.0)) == "🟨 Same winner · 4.0 pts apart"
    assert GP.agreement(_g("a", -5.0, -2.0)) == "⚠️ Model has A winning"
    assert GP.agreement({"home": "H"}) == "—"


def _prop(pm, pmod, actual, line=4.5, book="draftkings", under=-110):
    return {"p_market": pm, "p_model": pmod, "actual": actual, "line": line, "book": book, "over_price": -110,
            "under_price": under}


def test_prop_rules_take_only_model_unders_with_the_right_agreement():
    assert CR.prop_qualifies("nfl_under_vs_fav", _prop(0.55, 0.45, 3))          # market favors Over, model Under
    assert not CR.prop_qualifies("nfl_under_vs_fav", _prop(0.45, 0.40, 3))      # both favor Under: "same"
    assert CR.prop_qualifies("ncaaf_under_same", _prop(0.45, 0.40, 3))
    assert not CR.prop_qualifies("ncaaf_under_same", _prop(0.45, 0.50, 3))      # model on the Over
    assert not CR.prop_qualifies("ncaaf_under_same", _prop(0.45, 0.40, 3, book="underdog"))   # pick'em line


def test_prop_forward_record_and_status(store):
    graded = {"2026-11-23": [_prop(0.55, 0.45, 2)],                               # before the rule starts
              "2026-11-29": [_prop(0.55, 0.45, 2), _prop(0.55, 0.45, 7), _prop(0.45, 0.40, 2)]}
    rec = CR.refresh_props("2026-12-01", grade_for={r: (lambda: graded) for r in CR.PROP_RULES})
    assert rec["nfl_under_vs_fav"] == {"n": 2, "hits": 1, "units": round(100 / 110 - 1, 2), "through": "2026-11-30"}
    line = CR.prop_status_line("NFL")
    assert "1–1" in line and "Not a bet yet" in line and "NFL player-prop Unders" in line
    assert CR.prop_status_line("NBA") == ""
def test_hockey_agreement_compares_win_chances_not_the_puck_line():
    g = {"home": "NJ", "away": "CBJ", "home_spread": -1.5, "model_margin": 1.1}
    assert GP.agreement(dict(g, model_p=0.683, fair_home=0.646), "NHL") == "✅ Agree"
    assert GP.agreement(dict(g, model_p=0.681, fair_home=0.591), "NHL") == "🟨 Same favorite · win chance 9 pts apart"
    assert GP.agreement(dict(g, model_p=0.42, fair_home=0.58), "NHL") == "⚠️ Model has CBJ winning"
    assert GP.agreement(g, "NHL") == "—"
