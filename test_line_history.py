import model_record as MR
import postgame as PG


def _g(player, market, line, actual, result="hit", day="2026-11-24"):
    return {"slate_date": day, "player": player, "market": market, "line": line, "actual": actual, "result": result}


def test_line_record_counts_overs_unders_and_pushes_once_per_player_market_slate():
    rows = [_g("A", "Points", 20.5, 25), _g("A", "Points", 20.5, 25),          # the same read twice: counted once
            _g("B", "Points", 10.5, 8, "miss"), _g("C", "Points", 15.5, 16),
            _g("D", "Rebounds", 7.0, 7, "push"), _g("E", "Rebounds", 6.5, 9),
            _g("F", "Points", 12.5, None, "void")]
    got = {r["Market"]: r for r in PG.line_record(rows)}
    p = got["Points"]
    assert (p["Lines"], p["Went over"], p["Went under"], p["Pushes"]) == (3, 2, 1, 0)
    assert round(p["Over rate"], 3) == 0.667 and round(p["Avg vs line"], 2) == round((4.5 - 2.5 + 0.5) / 3, 2)
    r = got["Rebounds"]
    assert (r["Pushes"], r["Went over"], r["Over rate"]) == (1, 1, 1.0)
    assert PG.line_record([]) == []


def test_line_history_table_needs_twenty_lines():
    hist = {"NBA": [{"Market": "Points", "Lines": 120, "Over rate": 0.53}, {"Market": "Blocks", "Lines": 8}]}
    got = MR.line_history_table(["NBA", "NHL"], history_for=lambda s: hist.get(s, []))
    assert got == [{"Sport": "NBA", "Market": "Points", "Lines": 120, "Over rate": 0.53}]
