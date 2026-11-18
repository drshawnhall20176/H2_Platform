"""Nov 17: No-edge rename, 👀 Watch groups, No line, Over/Under record."""
import props_engine as PE
import postgame as PG
import watch as W


def test_no_edge_label_and_old_reads():
    assert PE.USE_PASS == "⚪ No edge" and PE.is_pass("⛔ Pass") and PE.is_pass(PE.USE_PASS)
    assert PE.norm_use("⛔ Pass") == PE.USE_PASS and not PE.is_pass(PE.USE_SINGLE)
    assert PE.use_tag({"line": None, "projection": 5, "side": "Over"})[0] == "No line"


def test_watch_tags_and_promotion():
    assert W.apply(PE.USE_PASS, "NBA", "Points", "Under", 18.0, 24.5, status={}) == PE.USE_WATCH     # far under
    assert W.apply(PE.USE_PASS, "NBA", "Points", "Under", 23.9, 24.5, status={}) == PE.USE_PASS      # near: not watched
    assert W.apply(PE.USE_SINGLE, "NBA", "Points", "Under", 18.0, 24.5, status={}) == PE.USE_SINGLE  # tags it never touches
    assert W.apply("⛔ Pass", "NFL", "Rush Attempts", "Under", status={"nfl_rush_att_under": {"status": "promoted"}}) \
        == PE.USE_SINGLE
    g = {"2026-11-20": [{"result": "hit", "market": "Rush Attempts", "side": "Under", "under_price": -110}] * 20
         + [{"result": "miss", "market": "Rush Attempts", "side": "Under", "under_price": -110}] * 12}
    st = W.judge("NFL", g, "2026-12-02")
    # Nov 18: 20-12 at -110 (+19% per $1) could still be luck at 32 reads -- the profit has to clear zero by a margin
    assert st["nfl_rush_att_under"]["status"] == "watch" and st["nfl_rush_att_under"]["n"] == 32
    assert st["nfl_rush_att_under"]["profit_floor"] < 0
    g = {"2026-11-20": [{"result": "hit", "market": "Rush Attempts", "side": "Under", "under_price": -110}] * 26
         + [{"result": "miss", "market": "Rush Attempts", "side": "Under", "under_price": -110}] * 10}
    st = W.judge("NFL", g, "2026-12-02")
    assert st["nfl_rush_att_under"]["status"] == "promoted" and st["nfl_rush_att_under"]["profit_floor"] > 0
    bad = {"2026-11-20": [{"result": "miss", "market": "Rush Attempts", "side": "Under", "under_price": -110}] * 31}
    assert W.judge("NFL", bad, "2026-11-25")["nfl_rush_att_under"]["status"] == "dropped"


def test_side_record_and_old_pass_rows_count_as_no_edge():
    rows = [{"side": "Over", "result": "hit", "use_tag": "🎯 Single only"}, {"side": "Over", "result": "miss",
            "use_tag": "⛔ Pass"}, {"side": "Under", "result": "hit", "use_tag": "⚪ No edge"}]
    s = {r["Side"]: r for r in PG.side_record(rows)}
    assert s["Over"]["Graded"] == 2 and s["Over"]["Bet graded"] == 1 and s["Under"]["Hits"] == 1
    u = {r["Use"]: r for r in PG.use_record([dict(r, chance=0.5) for r in rows])}
    assert u[PE.USE_PASS]["Graded"] == 2


def test_overs_gate_follows_each_sports_record():
    lose = {"d": [{"result": "miss", "side": "Over", "chance": 0.6, "over_price": -110}] * 14
            + [{"result": "hit", "side": "Over", "chance": 0.6, "over_price": -110}] * 8}
    g = W.judge_overs("NBA", lose)
    assert g["NBA"]["off"] is True and W.gate_over(PE.USE_SINGLE, "NBA", "Over", gate=g) == PE.USE_PASS
    assert W.gate_over(PE.USE_SINGLE, "NBA", "Under", gate=g) == PE.USE_SINGLE        # Unders untouched
    win = {"d": [{"result": "hit", "side": "Over", "chance": 0.6, "over_price": 150}] * 10
           + [{"result": "miss", "side": "Over", "chance": 0.6, "over_price": 150}] * 12}
    g2 = W.judge_overs("NFL", win)
    assert g2["NFL"]["off"] is False and W.gate_over(PE.USE_BOTH, "NFL", "Over", gate=g2) == PE.USE_BOTH
    few = W.judge_overs("NCAAF", {"d": lose["d"][:5]})
    assert few["NCAAF"]["off"] is False                                                # too few to switch off


def test_new_markets_are_on_probation():
    """Nov 18: steals / blocks join the props model; their bet tags show as Watch until the market earns a record."""
    import player_props as PPR
    import slate_props as SP
    assert {"player_steals", "player_blocks", "player_blocks_steals"} <= set(SP.CORE_MARKETS)
    assert PPR.MARKETS["Blocks+Steals"] == ("blk", "stl") and PPR.DIST["Blocks+Steals"] == "count"
    assert W.apply(PE.USE_SINGLE, "NBA", "Steals", "Over", status={}) == PE.USE_WATCH
    assert W.apply(PE.USE_PASS, "NBA", "Steals", "Over", status={}) == PE.USE_PASS
    assert W.apply(PE.USE_SINGLE, "NBA", "Blocks", "Under", status={"nba_blocks_new": {"status": "promoted"}}) == PE.USE_SINGLE
    assert W.apply(PE.USE_PARLAY, "NBA", "Blocks+Steals", "Over", status={"nba_stocks_new": {"status": "dropped"}}) == PE.USE_PASS
    win = {"2026-12-01": [{"result": "hit", "market": "Steals", "side": "Under", "under_price": -110,
                           "use_tag": PE.USE_WATCH}] * 28
           + [{"result": "miss", "market": "Steals", "side": "Under", "under_price": -110, "use_tag": PE.USE_WATCH}] * 8}
    st = W.judge("NBA", win, "2026-12-05")
    assert st["nba_steals_new"]["status"] == "promoted" and st["nba_steals_new"]["probation"]
    assert st["nba_blocks_new"]["n"] == 0 and st["nba_blocks_new"]["status"] == "watch"
