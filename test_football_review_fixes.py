"""Oct 30 (Packers-Panthers review): football model fixes + kicking / defensive markets."""
import football_props as FP
import football_special as FS
import position_matchups as PM
import slate_props as SP


def line(wk, team, opp, pid, name, pos, **st):
    base = dict(pass_att=0, pass_cmp=0, pass_yds=0, pass_td=0, pass_int=0, rush_att=0, rush_yds=0, rush_td=0, tgt=0,
                rec=0, rec_yds=0, rec_td=0, sacked=0)
    base.update(st)
    return {"game": f"{wk}-{team}", "order": wk, "team": team, "opp": opp, "pid": pid, "name": name, "pos": pos,
            "stats": base}


def league():
    """Seven weeks for GB: Lloyd carries the load while Jacobs is out (weeks 1-6), Jacobs back for week 7."""
    pg = []
    for wk in range(1, 8):
        pg.append(line(wk, "GB", f"D{wk}", "lloyd", "MarShawn Lloyd", "RB", rush_att=13 if wk < 7 else 5, rush_yds=50))
        pg.append(line(wk, "GB", f"D{wk}", "wr", "Wide Out", "WR", tgt=8, rec=5, rec_yds=60))
        pg.append(line(wk, "GB", f"D{wk}", "wr3", "Slot Guy", "WR", tgt=0 if wk % 2 else 4, rec=0 if wk % 2 else 3,
                       rec_yds=0 if wk % 2 else 30))
    pg.append(line(7, "GB", "D7", "jacobs", "Josh Jacobs", "RB", rush_att=11, rush_yds=36))
    for t in range(8):                                     # other teams, for league rates and defense tables
        for wk in range(1, 8):
            pg.append(line(wk, f"T{t}", f"D{(t + wk) % 8}", f"rb{t}", f"Back{t}", "RB", rush_att=15, rush_yds=60, tgt=3, rec=2,
                           rec_yds=15))
    return pg


def prior():
    return [dict(line(wk, "GB", "X", "jacobs", "Josh Jacobs", "RB", rush_att=19, rush_yds=80), order=wk - 100,
                 game=f"p{wk}-GB") for wk in range(10, 16)]


ROSTER = [{"pid": "jacobs", "name": "Josh Jacobs", "slot": "RB1", "status": None, "role_change": None},
          {"pid": "lloyd", "name": "MarShawn Lloyd", "slot": "RB2", "status": None, "role_change": None},
          {"pid": "wr", "name": "Wide Out", "slot": "WR1", "status": None, "role_change": None},
          {"pid": "wr3", "name": "Slot Guy", "slot": "WR3", "status": None, "role_change": None}]


def rows(market, **kw):
    pg = league()
    return {r["player"]: r for r in FP.player_rows(ROSTER, "GB", "CAR", market, pg, PM.allowed_by_slot(pg, "NFL"), **kw)}


def test_returning_starter_borrows_last_season_and_the_backup_gives_volume_back():
    old = rows("Rush Attempts")
    new = rows("Rush Attempts", prior_pgames=prior())
    assert old["Josh Jacobs"]["opp"] < 12 < new["Josh Jacobs"]["opp"] < 19              # 1 game of 11 + last season's 19s
    assert any("last season blended" in f for f in new["Josh Jacobs"]["flags"])
    assert any("back after missing 6" in f for f in new["Josh Jacobs"]["flags"])
    assert new["MarShawn Lloyd"]["opp"] < 8 and any("Jacobs back" in f for f in new["MarShawn Lloyd"]["flags"])


def test_quiet_games_count_toward_volume():
    r = rows("Targets")
    assert 1.5 < r["Slot Guy"]["opp"] < 2.6                       # 0, 4, 0, 4... not 4 a game
    assert r["Wide Out"]["opp"] > 7.5


def test_pressure_reads_sacks_both_ways():
    pg = league()
    for wk in range(1, 8):
        pg.append(line(wk, "GB", f"D{wk}", "qb", "Q B", "QB", pass_att=35, sacked=1))
        pg.append(line(wk, "CAR", "PIT", "cqb", "C Q", "QB", pass_att=35, sacked=5))     # CAR's line leaks
        pg.append(line(wk, "NYJ", "GB", "nqb", "N Q", "QB", pass_att=35, sacked=4))       # GB's pass rush
        for t in range(4):
            pg.append(line(wk, f"T{t}", f"D{t}", f"q{t}", f"QB{t}", "QB", pass_att=35, sacked=2))
    assert FP.pressure(pg, "CAR", "GB") > 0.3
    assert FP.pressure(pg, "GB", "D1") < 0
    assert FP.pressure([p for p in pg if p["pos"] != "QB"], "CAR", "GB") is None


def special():
    pg = []
    for wk in range(1, 6):
        for team, opp, fg, pat in (("GB", "X", 2, 3), ("CAR", "Y", 1, 1), ("X", "GB", 1, 2), ("Y", "CAR", 2, 2)):
            st = {"fg_made": fg, "fg_att": fg, "pat_made": pat, "pat_att": pat, "kick_pts": 3 * fg + pat}
            pg.append({"game": f"{wk}-{team}", "order": wk, "team": team, "opp": opp, "pid": f"k{team}",
                       "name": f"Kicker {team}", "pos": "K", "stats": st})
            for i, (pos, tk, sk) in enumerate((("LB", 9, 0.0), ("DL", 3, 0.5), ("DB", 0.5, 0.0))):
                st = {"tkl": tk, "tkl_solo": tk * 0.6, "sacks": sk, "qb_hits": sk}
                pg.append({"game": f"{wk}-{team}", "order": wk, "team": team, "opp": opp, "pid": f"{team}{i}",
                           "name": f"{team} {pos}", "pos": pos, "stats": st})
    return pg


def test_special_roster_and_rows():
    pg = special()
    ro = FS.team_roster(pg, "GB", {"GB DL": "Questionable"})
    assert [r["slot"] for r in ro] == ["K", "LB", "DL"]                  # the 0.5-tackle DB isn't a regular
    assert ro[2]["status"] == "Questionable"
    props = {"special_roster": {"GB": ro}, "roster": {"GB": ROSTER}}
    assert FP.roster_for(props, "GB", "Sacks") == ro and FP.roster_for(props, "GB", "Receptions") == ROSTER
    sp = {"pgames": pg, "prior": []}
    k = FP.player_rows(ro, "GB", "X", "Kicking Points", [], {}, context={"implied": 27.0}, special=sp)
    assert len(k) == 1 and k[0]["slot"] == "K" and k[0]["projection"] > 9 and k[0]["group"] == "kicker"
    t = {r["player"]: r for r in FP.player_rows(ro, "GB", "X", "Tackles + Assists", [], {}, lines={"GB0": 7.5},
                                                special=sp)}
    assert set(t) == {"GB LB", "GB DL"} and t["GB LB"]["projection"] > 7.5 and t["GB LB"]["side"] == "Over"
    s = FP.player_rows(ro, "GB", "X", "Sacks", [], {}, context={"spread": -7.0}, special=sp)
    assert {r["player"] for r in s} == {"GB LB", "GB DL"}


def test_markets_by_sport_and_team_rows_wiring():
    nfl, cfb = FP.markets_for("NFL"), FP.markets_for("NCAAF")
    for m in ("Targets", "FG Made", "Kicking Points", "PATs Made", "Sacks", "Tackles + Assists", "Solo Tackles"):
        assert m in nfl and m not in cfb
    assert "Interceptions" in cfb
    keys = SP.props_markets("NFL")
    for k in ("player_kicking_points", "player_pats", "player_sacks", "player_tackles_assists", "player_solo_tackles",
              "player_field_goals", "player_pass_interceptions"):
        assert k in keys
    bundle = {"home": "GB", "away": "X", "allowed": {}, "props": {"pgames": [], "roster": {"GB": []},
                                                                  "special_roster": {"GB": FS.team_roster(special(), "GB")},
                                                                  "special": {"pgames": special(), "prior": []}}}
    r = SP.team_rows("football", "NFL", bundle, "GB", "X", "FG Made", -3.0, 47.0)
    assert len(r) == 1 and r[0]["projection"] > 1.5
