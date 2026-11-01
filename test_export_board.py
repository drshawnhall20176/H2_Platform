import export_board as X


def test_pick_applies_the_page_filters_and_ranks_by_model_pct():
    base = dict(Model="player-props", Conviction=1.2, Slot="Afternoon", Side="Over", Use="🎟️ Parlay leg", Line=50.5,
                Game="A @ B", Player="p", Team="A", Projection=60.0, Cushion=0.18, EV=0.02, RealPrice=-110)
    plays = [dict(base, Player="a", Market="Receiving Yards", ModelProb=0.61),
             dict(base, Player="b", Market="Receptions", ModelProb=0.66),
             dict(base, Player="c", Market="Sacks", ModelProb=0.70),
             dict(base, Player="d", Market="Rush Yards", Side="Under", ModelProb=0.72),
             dict(base, Player="e", Market="Pass Yards", Slot="Evening", ModelProb=0.75),
             dict(base, Player="f", Market="Pass Yards", Use="⛔ Pass", ModelProb=0.80)]
    got = X.pick(plays, slot="Afternoon", unit="Offense", side="Over", show="All playable")
    assert [p["Player"] for p in got] == ["b", "a"]
    assert "Receptions" in X.table(got) and "| 1 |" in X.table(got)
