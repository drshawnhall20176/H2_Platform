

def test_money_picks_biggest_edge_first_one_per_player_not_started():
    import datetime as d
    import customer_today as CT
    rows = [{"kind": "Prop", "money": True, "edge": 0.07, "player": "A", "pick": "A Pts Over 20.5", "time": "7:00 PM"},
            {"kind": "Prop", "money": True, "edge": 0.12, "player": "B", "pick": "B Reb Under 9.5", "time": "8:00 PM"},
            {"kind": "Prop", "money": True, "edge": 0.10, "player": "B", "pick": "B Ast Over 4.5", "time": "8:00 PM"},
            {"kind": "Prop", "money": True, "edge": 0.14, "player": "C", "pick": "C 3PM Under 1.5", "time": "1:00 PM"},
            {"kind": "Prop", "money": False, "edge": 0.20, "player": "D", "pick": "D", "time": "9:00 PM"}]
    hour = {"7:00 PM": 19, "8:00 PM": 20, "1:00 PM": 13, "9:00 PM": 21}
    parse = lambda t: d.datetime(2026, 11, 19, hour[t])
    got = CT.money_picks(rows, parse_time=parse, now=d.datetime(2026, 11, 19, 15))
    assert [g["pick"] for g in got] == ["B Reb Under 9.5", "A Pts Over 20.5"]
