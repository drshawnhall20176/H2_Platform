"""Oct 30: Depth vs defense + Position breakout read in any stat; LA Clippers line matching."""
import nba_positions as NP
import position_lines as PL
import position_matchups as PM
import position_data as PD


def test_la_clippers_matches_the_books_name():
    ev = [{"home_team": "Minnesota Timberwolves", "away_team": "Los Angeles Clippers", "id": "x"}]
    assert PL.match_event(ev, "Minnesota Timberwolves", "LA Clippers")["id"] == "x"
    assert PL.match_event([{"home_team": "Minnesota Timberwolves", "away_team": "LA Clippers"}],
                          "Minnesota Timberwolves", "Los Angeles Clippers")
    assert PL.match_event(ev, "Minnesota Timberwolves", "Los Angeles Lakers") is None


def pg(game, off, de, pid, pos, **st):
    base = dict(min=30, pts=0, reb=0, ast=0, fg3m=0, stl=0, blk=0)
    base.update(st)
    return {"game": game, "order": game, "team": off, "opp": de, "pid": pid, "name": pid, "pos": pos, "stats": base}


def sample():
    out = []
    for t in range(10):
        for i in range(4):
            g = f"2026-10-1{i}-{t}"
            # D0 allows lots of guard REBOUNDS but few guard points
            out.append(pg(g, f"O{t}", f"D{t}", f"g{t}", "PG", pts=10 if t == 0 else 20, reb=12 if t == 0 else 4, ast=5))
            out.append(pg(g, f"O{t}", f"D{t}", f"c{t}", "C", pts=12, reb=10, ast=2))
    return out


def test_metric_context_changes_rankings_only_inside():
    allowed = PM.allowed_by_slot(sample(), "NBA")
    pra = PM.summarize(allowed, "NBA")["D0"]["G"]["pts"]
    with PM.using_metric("basketball", "Rebounds"):
        reb = PM.summarize(allowed, "NBA")["D0"]["G"]["pts"]
        assert PM.metric_short("basketball") == "Rebounds"
    assert reb == 12 and pra == 27 and PM.metric_short("basketball") == "PRA"
    depth = {"G": [{"pid": "g0", "name": "g0", "avg_min": 30}]}
    side = PD.build_side("NBA", "O0", "D0", depth, allowed, sample())
    with PM.using_metric("basketball", "Rebounds"):
        side_r = PD.build_side("NBA", "O0", "D0", depth, allowed, sample())
        rows = PM.display_rows_by_player(side_r["rows"])
    g_pra = [r for r in side["rows"] if r["slot"] == "G"][0]
    g_reb = [r for r in side_r["rows"] if r["slot"] == "G"][0]
    assert g_pra["tier"] == "Tough" and g_reb["tier"] == "Soft" and g_reb["rank"] == 1
    assert "Allowed / g (Rebounds)" in rows[0]


def test_breakout_summarizes_any_stat():
    labels = {f"g{t}": "PG" for t in range(10)}
    allowed = NP.allowed_by_position(sample(), labels)
    assert NP.summarize(allowed)["D0"]["pos"]["PG"]["pra"] == 27
    assert NP.summarize(allowed, keys=("reb",))["D0"]["pos"]["PG"]["pra"] == 12
    d = NP.display(NP.breakout_rows("D0", {}, NP.summarize(allowed, keys=("reb",)), {}, []), "Rebounds")
    assert "Allowed / g (Rebounds)" in d[0] and "stl" in d[0]["What it allows"]
