import matchup_card as MC


def test_bars_put_recent_then_head_to_head_oldest_left():
    rows = MC.bars([30, 20, 25], [18, 22])
    assert [r["Game"] for r in rows] == ["3 ago", "2 ago", "Last", "vs D #1", "vs D #2"]
    assert [r["Kind"] for r in rows][-2:] == ["vs this defense"] * 2
    assert MC.chart(rows, 24.0, 21.5, "PRA") is not None


def test_card_renders():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string("""
import matchup_card as MC
MC.render({"player": "A Guy", "pos": "PG (G)", "team": "BOS", "defense": "WAS", "unit": "PRA", "recent": [30, 20, 25, 28],
           "h2h": [22], "recent_avg": 25.8, "rank": "3/30", "verdict": "🟢 Soft", "allowed": 31.2, "league": 27.0,
           "vs_league": "+16%", "model": "+4%", "trend": "↗", "allows": "20 pts"}, "NBA", key="t")
""", default_timeout=30).run()
    assert not at.exception, [e.value for e in at.exception]


def test_player_form_keeps_the_values():
    import position_matchups as PM
    f = PM.player_form([{"pid": 1, "order": 2, "stats": {"pts": 10, "reb": 5, "ast": 5}},
                        {"pid": 1, "order": 1, "stats": {"pts": 20, "reb": 5, "ast": 5}}], 1, "NBA")
    assert f["vals"] == [20.0, 30.0] or f["vals"] == [20, 30]
