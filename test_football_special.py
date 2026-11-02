

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
