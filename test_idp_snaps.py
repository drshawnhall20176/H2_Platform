import pandas as pd
import football_special as FS
import position_data as PD


def _g(order, tkl, snaps, pct):
    return {"order": order, "team": "KC", "name": "Nick Bolton", "pos": "LB", "pid": "x",
            "stats": {"tkl_solo": tkl, "tkl": tkl, "def_snaps": snaps, "def_pct": pct}}


def test_snap_read_sees_a_role_drop():
    games = [_g(9, 2, 30, 0.45), _g(8, 6, 66, 1.0), _g(7, 7, 66, 1.0), _g(6, 6, 66, 1.0)]
    sr = FS.snap_read(games, [2, 6, 7, 6])
    assert round(sr["delta"], 2) == -0.55
    assert sr["proj"] < FS.PE.wmean([2, 6, 7, 6])


def test_snap_read_needs_three_games():
    assert FS.snap_read([_g(9, 2, 30, 0.45), _g(8, 6, 0, 0)], [2, 6]) is None


def test_attach_def_snaps_matches_by_week_team_name():
    pg = [{"order": 8, "team": "KC", "name": "Nick Bolton", "pos": "LB", "stats": {}},
          {"order": 8, "team": "KC", "name": "Harrison Butker", "pos": "K", "stats": {}}]
    snaps = pd.DataFrame([{"week": 8, "team": "KC", "player": "Nick Bolton", "defense_snaps": 60, "defense_pct": 0.95}])
    assert PD.attach_def_snaps(pg, snaps) == 1
    assert pg[0]["stats"]["def_snaps"] == 60 and "def_snaps" not in pg[1]["stats"]


def test_snap_down_only_fires_on_a_drop():
    import football_props as FP
    g = [{"stats": {"off_snaps": 25, "off_pct": 0.40}}] + [{"stats": {"off_snaps": 55, "off_pct": 0.85}}] * 4
    sd = FP.snap_down(g, [3, 7, 8, 7, 6])
    assert sd and round(sd["before"], 2) == 0.85 and sd["opp"] < FP.PE.wmean([3, 7, 8, 7, 6])
    steady = [{"stats": {"off_snaps": 55, "off_pct": 0.85}}] * 5
    assert FP.snap_down(steady, [7, 7, 7, 7, 7]) is None
