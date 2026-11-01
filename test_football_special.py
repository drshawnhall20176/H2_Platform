

def test_market_units_for_the_best_bets_group_picker():
    import football_props as FP
    assert FP.market_unit("Receptions") == "Offense" and FP.market_unit("Interceptions") == "Offense"
    assert FP.market_unit("Sacks") == "Defense" and FP.market_unit("Solo Tackles") == "Defense"
    assert FP.market_unit("FG Made") == "Special Teams" and FP.market_unit("PATs Made") == "Special Teams"
    assert FP.market_unit("Points") is None
