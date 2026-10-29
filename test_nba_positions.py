"""nba_positions: the beta five-position breakout (display only)."""
import nba_positions as NP


def pg(game, team, opp, pid, pos, pts, order="2026-10-20"):
    return dict(game=game, order=order, team=team, opp=opp, pid=pid, name=str(pid), pos=pos,
                stats=dict(min=30, pts=pts, reb=0, ast=0, fg3m=0))


def sample():
    out = []
    for t in range(10):                         # defense D0 is soft on PGs, tough on SGs; both "G" on the roster
        for i in range(4):
            g = f"{t}-{i}"
            out += [pg(g, f"O{t}", f"D{t}", f"p{t}", "G", 30 if t == 0 else 20, f"2026-10-1{i}"),
                    pg(g, f"O{t}", f"D{t}", f"s{t}", "G", 10 if t == 0 else 20, f"2026-10-1{i}"),
                    pg(g, f"O{t}", f"D{t}", f"x{t}", "F", 5, f"2026-10-1{i}")]   # unlabelled bench forward
    return out


def labels():
    return {**{f"p{t}": "PG" for t in range(10)}, **{f"s{t}": "SG" for t in range(10)}}


def test_positions_split_what_the_group_hides():
    allowed = NP.allowed_by_position(sample(), labels())
    season = NP.summarize(allowed)
    assert season["D0"]["pos"]["PG"]["pra"] == 30 and season["D0"]["pos"]["SG"]["pra"] == 10
    assert season["D0"]["grp"]["G"]["pra"] == 40 and season["D0"]["grp"]["F"]["pra"] == 5   # unlabelled -> roster group
    assert season["D0"]["pos"]["SF"]["pra"] == 0                                           # nobody there = zero
    depth = {"PG": [{"pid": "p0", "name": "Lead"}], "SG": [{"pid": "s0", "name": "Wing"}, {"pid": "z", "name": "B1"}]}
    rows = {r["pos"]: r for r in NP.breakout_rows("D0", depth, season, NP.summarize(allowed, 4), sample())}
    assert rows["PG"]["rank"] == 1 and rows["PG"]["tier"] == "Soft"
    assert rows["SG"]["rank"] == 10 and rows["SG"]["tier"] == "Tough"
    assert rows["PG"]["grp_pct"] == 0                                   # the guard group as a whole is average
    assert 0 < rows["PG"]["blend_pct"] < rows["PG"]["pos_pct"]          # small sample pulled toward the group
    d = {r["Pos"]: r for r in NP.display(list(rows.values()))}
    assert d["SG"]["Starter"] == "Wing" and d["SG"]["Backups"] == "B1" and d["PG"]["Verdict"] == "🟢 Soft"


def test_blend_weights_and_feed_parsing():
    assert NP.blended_pct(50, 0, 10) == 25 and NP.blended_pct(None, 5, 3) == 5 and NP.blended_pct(5, None, 3) == 5
    feed = {"depthchart": [{"positions": {"pg": {"athletes": [{"id": "12", "displayName": "A"}, {"id": "x", "displayName": "B"}]}}}]}
    assert NP.depth_lists(feed) == {"PG": [{"pid": 12, "name": "A"}, {"pid": "x", "name": "B"}]}
    assert NP.depth_lists(None) == {}
    assert NP.label_players({1: {5: {"pos": "SF"}, 6: {"pos": "??"}}}) == {5: "SF"}
