"""Nov 21: the shown-picks ledger (pick_ledger.py) -- first sighting wins, no picks after the start, graded records."""
from datetime import datetime, timezone

import pick_ledger as PL


class Store(dict):
    def get_(self, k, d=None):
        return self.get(k, d)

    def save(self, k, v):
        self[k] = v


def _p(**kw):
    r = {"sport": "NBA", "kind": "Prop", "pick": "A Points Under 10.5", "player": "A", "pid": 1, "market": "Points",
         "side": "Under", "line": 10.5, "price": -110, "chance": 0.6, "money": True, "time": "7:30 PM"}
    r.update(kw)
    return r


NOON = datetime(2026, 11, 21, 17, 0, tzinfo=timezone.utc)            # noon New York
NIGHT = datetime(2026, 11, 22, 3, 0, tzinfo=timezone.utc)            # 10 PM New York


def test_first_sighting_wins_and_later_reads_never_overwrite():
    s = Store()
    assert PL.add("money", "NBA", "2026-11-21", [_p()], NOON, s.get_, s.save) == 1
    assert PL.add("money", "NBA", "2026-11-21", [_p(line=11.5, price=-130)], NOON, s.get_, s.save) == 0
    rows = PL.rows("money", "NBA", "2026-11-21", s.get_)
    assert len(rows) == 1 and rows[0]["line"] == 10.5 and rows[0]["price"] == -110 and rows[0]["first_seen"]


def test_started_games_are_not_added():
    assert not PL.started("2026-11-21", _p(), NOON)
    assert PL.started("2026-11-21", _p(), NIGHT)
    assert not PL.started("2026-11-21", _p(time="12:30 AM"), NIGHT)          # after midnight: the next morning
    assert PL.started("2026-11-21", {"kickoff": "2026-11-21T23:00:00Z"}, NIGHT)


def test_record_strong_takes_the_top_15_still_to_start(monkeypatch):
    s = Store()
    monkeypatch.setattr(PL, "_get", lambda k, get=None: s.get(k) or {})
    monkeypatch.setattr(PL, "_save", lambda k, v, save=None: s.save(k, v))
    picks = [_p(pid=i, player=f"P{i}", chance=0.5 + i / 100, time="1:00 PM" if i == 19 else "7:30 PM")
             for i in range(20)]
    n = PL.record_strong("2026-11-21", datetime(2026, 11, 21, 19, 0, tzinfo=timezone.utc), keys=["NBA"],
                         load_props=lambda k, d: {"rows": picks})
    got = PL.rows("strong", "ALL", "2026-11-21", s.get)
    assert n == 14 and len(got) == 14                           # top 15 = P5..P19; P19's game had started
    assert {r["player"] for r in got} == {f"P{i}" for i in range(5, 19)}


def test_record_is_none_until_graded_and_counts_at_the_shown_price():
    s = Store()
    PL.add("money", "NBA", "2026-11-21", [_p(), _p(pid=2, price=+150)], NOON, s.get_, s.save)
    assert PL.record("money", "NBA", "2026-11-21", s.get_) is None
    k = PL.KEY.format(kind="money", sport="NBA", day="2026-11-21")
    rows = s[k]["rows"]
    for r in rows.values():
        r["result"] = "loss" if r["pid"] == 1 else "win"
    s[k]["graded_at"] = "x"
    rec = PL.record("money", "NBA", "2026-11-21", s.get_)
    assert (rec["hits"], rec["misses"]) == (1, 1) and abs(rec["units"] - 0.5) < 1e-9
    assert PL.record("money", "NBA", "2026-11-20", s.get_) is None             # before the ledger existed


def test_grade_prop_uses_final_box_scores_then_snapshot_actuals():
    assert PL.grade_prop(_p(), {1: {"pts": 11.0}}) == "loss"
    assert PL.grade_prop(_p(), {1: {"pts": 9.0}}) == "win"
    assert PL.grade_prop(_p(line=10.0, side="Over"), {1: {"pts": 10.0}}) == "win"     # whole line = 10+
    assert PL.grade_prop(_p(pid=None), {}, {("a", "Points"): 12.0}) == "loss"
    assert PL.grade_prop(_p(pid=7), {}) is None


def test_grade_games_uses_the_final_score():
    rows = [{"game_id": "g", "money_market": "Spread", "money_side": "away", "money_line": 4.5}]
    PL.grade_games("2026-11-21", rows, recs={"g": {"final_home": 70, "final_away": 68}})
    assert rows[0]["result"] == "win"


def test_strongest_ranks_by_earned_edge_and_drops_negative_edges():
    picks = [{"kind": "Prop", "pick": "a", "chance": 0.80, "earned": 0.55, "price": -150},     # needs 60%: -5
             {"kind": "Prop", "pick": "b", "chance": 0.62, "earned": 0.57, "price": -110},     # needs 52.4%: +4.6
             {"kind": "Prop", "pick": "c", "chance": 0.66, "earned": 0.56, "price": None, "pickem_only": True}]  # +1.75
    got = PL.strongest(picks)
    assert [r["pick"] for r in got] == ["b", "c"]


def test_strongest_falls_back_to_chance_without_earned():
    picks = [{"kind": "Prop", "pick": "a", "chance": 0.6}, {"kind": "Prop", "pick": "b", "chance": 0.7}]
    assert [r["pick"] for r in PL.strongest(picks)] == ["b", "a"]


def test_strongest_takes_at_most_five_from_one_sport():
    picks = [{"kind": "Prop", "sport": "NCAAF", "pick": f"f{i}", "earned": 0.60, "price": -110} for i in range(8)]
    picks += [{"kind": "Prop", "sport": "NBA", "pick": "n", "earned": 0.55, "price": -110}]
    got = PL.strongest(picks)
    assert sum(r["sport"] == "NCAAF" for r in got) == 5 and got[-1]["pick"] == "n"


def test_a_dropped_pick_on_a_game_still_on_the_board_is_not_kept():
    import todays_best as TB
    old = [{"game": "A @ B", "pick": "x"}, {"game": "E @ F", "pick": "z"}]
    assert TB.keep_started([], old, on_board={"A @ B"}) == [{"game": "E @ F", "pick": "z"}]


def test_game_line_money_picks_join_the_strongest_list():
    full = {"sport": "NCAAMB", "home": "Siena Saints", "away": "Rider Broncs", "home_spread": -6.5, "game_id": "g1",
            "kickoff": "2026-11-21T16:00:00Z"}
    rows = [{"sport": "NCAAMB", "money": True, "money_market": "Spread", "money_side": "home", "money_line": -6.5,
             "money_price": -109, "money_chance": 0.56, "money_pick": "Siena Saints -6.5", "money_score": 0.07,
             "game": "Rider Broncs @ Siena Saints", "time": "11:00 AM", "_rec": {"game_id": "g1"}, "_full": full},
            {"sport": "NCAAMB", "money": False, "money_market": "Spread"}]
    g = PL.game_candidates("2026-11-21", rows)
    assert len(g) == 1 and g[0]["kind"] == "Game" and g[0]["bet_market"] == "Spread" and g[0]["earned"] == 0.56
    props = [{"kind": "Prop", "sport": "NBA", "pick": "p", "earned": 0.55, "price": -110}]
    got = PL.strongest(props + g)
    assert [r["pick"] for r in got] == ["Siena Saints -6.5", "p"]           # +3.8 points beats +2.6


def test_strong_ledger_grades_game_lines_on_the_final_score():
    rows = [{"game_id": "g1", "money_market": "Spread", "money_side": "home", "money_line": -6.5}]
    PL.grade_games("2026-11-21", rows, recs={"g1": {"final_home": 80, "final_away": 70}})
    assert rows[0]["result"] == "win"


def test_close_marks():
    assert PL.close_mark("prop", "Under", 4.5, -110, 3.5, -110)["clv_mark"] == "beat"       # line fell: Under agreed
    assert PL.close_mark("prop", "Over", 4.5, -110, 3.5, -110)["clv_mark"] == "lost"
    m = PL.close_mark("prop", "Under", 4.5, -110, 4.5, -130)
    assert m["clv_mark"] == "beat" and m["clv_pct"] > 0
    assert PL.close_mark("spread", None, -6.5, -110, -8.5, -110)["clv_mark"] == "beat"
    assert PL.close_mark("ml", None, None, -110, None, +300)["clv_mark"] is None              # another line's price


def test_record_counts_closing_line_value():
    from datetime import datetime, timezone
    s = {}
    get, save = (lambda k, d=None: s.get(k, d)), (lambda k, v: s.__setitem__(k, v))
    PL.add("money", "NBA", "2026-11-21", [{"sport": "NBA", "pid": 1, "market": "Points", "side": "Under", "line": 9.5,
                                           "price": -110}], datetime(2026, 11, 21, 15, tzinfo=timezone.utc), get, save)
    k = PL.KEY.format(kind="money", sport="NBA", day="2026-11-21")
    r = next(iter(s[k]["rows"].values()))
    r.update(result="win", **PL.close_mark("prop", "Under", 9.5, -110, 8.5, -110))
    s[k]["graded_at"] = "x"
    rec = PL.record("money", "NBA", "2026-11-21", get)
    assert rec["clv_beat"] == 1 and rec["clv_lost"] == 0


def test_a_player_missing_from_a_finished_game_is_void(monkeypatch):
    cache = {("final", "NBA"): [("boston celtics", "sacramento kings")]}
    r = {"sport": "NBA", "game": "Boston Celtics @ Sacramento Kings", "pid": 1}
    assert PL.dnp_void(r, "2026-11-21", cache)
    assert not PL.dnp_void(dict(r, game="LA Clippers @ Dallas Mavericks"), "2026-11-21", cache)
    cache[("fsched", "NCAAF", "2026")] = []
    assert not PL.dnp_void(dict(r, sport="NCAAF"), "2026-11-21", cache)


def test_a_football_player_with_no_stat_line_in_a_finished_game_is_void():
    """Nov 22: Elija Lofton / Caden High (CFBD lists only players with a stat) -- void, never a guessed win."""
    cache = {("fsched", "NCAAF", "2026"): [
        {"start_date": "2026-11-22T00:30:00.000Z", "completed": True, "away_team": "Stanford", "home_team": "California"},
        {"start_date": "2026-11-28T17:00:00.000Z", "completed": False, "away_team": "Boston College", "home_team": "Miami"}],
        ("fsched", "NFL", "2026"): [{"gameday": "2026-11-22", "away_team": "MIN", "home_team": "SF", "home_score": 24,
                                     "away_score": 20}]}
    r = {"sport": "NCAAF", "game": "Stanford @ California", "pid": "5231354"}
    assert PL.dnp_void(r, "2026-11-21", cache)                            # 7:30 PM ET = next day in UTC
    assert not PL.dnp_void(dict(r, game="Boston College @ Miami"), "2026-11-21", cache)   # not this week
    assert PL.dnp_void({"sport": "NFL", "game": "MIN @ SF"}, "2026-11-22", cache)
    assert not PL.dnp_void({"sport": "NFL", "game": "NYJ @ LAC"}, "2026-11-22", cache)
