import screener as SCR


def _r(player, chance, values, line=20.5, side="Over", factor=None, slot=None, use="", market="Points", time="7:00 PM"):
    return {"player": player, "pick": f"{player} {side} {line} {market}", "chance": chance, "values": values,
            "line": line, "side": side, "factor": factor, "slot": slot, "use": use, "market": market,
            "sport": "NBA", "time": time, "price": -110}


ROWS = [_r("Hot", 0.62, [25, 24, 30, 22, 21, 10, 25, 26, 27, 28], factor=1.08, slot="G"),
        _r("Cold", 0.55, [10, 12, 30, 8, 9, 11, 12, 13, 14, 15]),
        _r("Under Guy", 0.58, [5, 6, 7, 30, 4, 5, 6, 7, 8, 9], side="Under", market="Rebounds", time="9:00 PM")]


def test_hit_rates_and_streaks_are_against_tonights_line():
    e = SCR.enrich(ROWS[0])
    assert e["_hit10"] == 0.9 and e["_hit5"] == 1.0 and e["_streak"] == 5 and e["_match"] == "soft"
    u = SCR.enrich(ROWS[2])
    assert u["_hit10"] == 0.9 and u["_streak"] == 3
    assert SCR.hit_rate([], 20.5, "Over") is None and SCR.hit_rate([1], None, "Over") is None


def test_filters_stack():
    names = lambda got: [r["player"] for r in got]
    assert names(SCR.apply(ROWS)) == ["Hot", "Cold", "Under Guy"]
    assert names(SCR.apply(ROWS, min_chance=0.57)) == ["Hot", "Under Guy"]
    assert names(SCR.apply(ROWS, min_chance=0.57, min_hit10=0.9, min_streak=4)) == ["Hot"]
    assert names(SCR.apply(ROWS, soft_only=True)) == ["Hot"]
    assert names(SCR.apply(ROWS, sides=["Under"])) == ["Under Guy"]
    assert names(SCR.apply(ROWS, markets=["Points"])) == ["Hot", "Cold"]
    assert names(SCR.apply(ROWS, bets_only=True, bet_of=lambda r: "🃏 Bet" if r["player"] == "Cold" else "Info")) == ["Cold"]


def test_table_sorts_by_start_time_then_chance():
    got = SCR.table(SCR.apply(ROWS), bet_of=lambda r: "Info only", parse_time=lambda t: {"7:00 PM": 19, "9:00 PM": 21}[t])
    assert [r["Pick"].split()[0] for r in got] == ["Hot", "Cold", "Under"]
    assert got[0]["Last 10"] == "90%" and got[0]["Price"] == "-110" and got[0]["Streak"] == 5
