

def test_market_units_for_the_best_bets_group_picker():
    import football_props as FP
    assert FP.market_unit("Receptions") == "Offense" and FP.market_unit("Interceptions") == "Offense"
    assert FP.market_unit("Sacks") == "Defense" and FP.market_unit("Solo Tackles") == "Defense"
    assert FP.market_unit("FG Made") == "Special Teams" and FP.market_unit("PATs Made") == "Special Teams"
    assert FP.market_unit("Points") is None


def test_nfl_single_needs_5pct_edge_and_55pct_chance():
    import football_props as FP
    import props_engine as PE
    base = {"line": 30.5, "side": "Over", "projection": 33.0, "lean": "Over", "p_final": 0.57, "ev": 0.04,
            "flags": [], "out": False, "values": [30, 34, 33, 35], "book": {}}
    assert PE.use_tag(dict(base))[0] == PE.USE_SINGLE                              # other sports: +3% is enough
    nfl = FP._single_bar([dict(base)], "NFL")[0]
    assert PE.use_tag(nfl)[0] != PE.USE_SINGLE                                     # NFL: +4% isn't
    assert PE.use_tag(dict(nfl, ev=0.06))[0] == PE.USE_SINGLE
    assert PE.use_tag(dict(nfl, ev=0.08, p_final=0.53))[0] != PE.USE_SINGLE        # ... nor a 53% chance
    assert FP._single_bar([dict(base)], "NCAAF")[0].get("single_ev") is None


def test_qb_volume_counts_the_opponent_at_half_strength():
    import football_props as FP
    assert FP.DEFENSE_WEIGHT == {"Pass Attempts": 0.5, "Pass Completions": 0.5}


def _rb_games(weeks_out_for_b):
    pg = []
    for wk in range(1, 8):
        pg.append(dict(game=f"{wk}-T", order=wk, team="T", opp="O", pid="a", name="Back A", pos="RB",
                       stats=dict(rush_att=15, rush_yds=60, tgt=2, rec=1, rec_yds=8)))
        if wk not in weeks_out_for_b:
            pg.append(dict(game=f"{wk}-T", order=wk, team="T", opp="O", pid="b", name="Back B", pos="RB",
                           stats=dict(rush_att=12, rush_yds=50, tgt=1, rec=1, rec_yds=5)))
        pg.append(dict(game=f"{wk}-T", order=wk, team="T", opp="O", pid="c", name="Back C", pos="RB",
                       stats=dict(rush_att=(10 if wk in weeks_out_for_b else 3), rush_yds=30, tgt=1, rec=1, rec_yds=5)))
    return pg


def test_a_long_absence_is_not_handed_out_twice():
    import football_props as FP
    roster = [{"pid": "a", "name": "Back A", "slot": "RB1"},
              {"pid": "c", "name": "Back C", "slot": "RB2", "role_change": {"from": "RB3", "for": "Back B"}},
              {"pid": None, "name": "Back B", "slot": "RB2", "status": "Out", "replaced_by": "Back C"}]
    def proj(weeks_out):
        rows = FP.player_rows(roster, "T", "O", "Rush Attempts", _rb_games(weeks_out), {}, context={}, sport="NFL")
        return {r["player"]: r["projection"] for r in rows if r.get("projection")}
    long_out = proj({5, 6, 7})        # B out three straight weeks: C already has the role (10 a game lately)
    fresh = proj(set())               # B played every week and is out today: C inherits his carries
    assert long_out["Back C"] < 12 and fresh["Back C"] > long_out["Back C"] + 4
    assert FP.present_share({"games": [1], "missed": ["7-T", "6-T"]}, ["7-T", "6-T", "5-T"]) == 0.0
    assert FP.present_share({"games": [1], "missed": []}, ["7-T", "6-T"]) == 1.0
