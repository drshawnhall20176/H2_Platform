"""Nov 16: the "Start here" shortlist above the Best Bets board."""
import props_engine as PE
import start_here as SH


def _p(player, prob, use=PE.USE_SINGLE, **kw):
    return {"Player": player, "Market": "Assists", "Side": "Over", "Line": 5.5, "ModelProb": prob, "Use": use,
            "Game": "A @ B", "Time": "7:00 PM", "RealPrice": -110, "RealPriceBook": "DraftKings", "Conviction": 1.3, **kw}


RECS = {"NBA": {PE.USE_SINGLE: (30, 50), PE.USE_PARLAY: (4, 10), PE.USE_BOTH: (8, 25)}}


def test_shortlist_leads_with_winning_pick_types_one_per_player():
    plays = [_p("A", 0.58), _p("A", 0.66), _p("B", 0.71, use=PE.USE_PARLAY), _p("C", 0.62),
             _p("D", 0.80, use=PE.USE_BOTH),                              # that pick type has been losing: left out
             _p("E", 0.75, Lean="Check news"), _p("F", 0.74, Warnings=["minutes"]), _p("G", 0.9, use=PE.USE_PASS)]
    got = SH.shortlist("NBA", plays, records_for=RECS.get)
    assert [(r["pick"].split()[0], r["standing"]) for r in got] == [("A", SH.WINNING), ("C", SH.WINNING), ("B", SH.NEW)]
    assert got[0]["chance"] == 0.66 and got[0]["price"] == "-110 · DraftKings"
    assert got[0]["record"].startswith("30–20 (60%")
    assert len(SH.shortlist("NBA", [_p(f"P{i}", 0.6 + i / 100) for i in range(9)], records_for=RECS.get)) == SH.N


def test_shortlist_falls_back_to_the_strongest_reads_when_the_board_has_no_use_tags():
    plays = [_p("A", 0.61, use=None), _p("B", 0.70, use=None), _p("C", 0.9, use=None, Conviction=1.0),
             _p("B", 0.65, use=None), _p("D", 0.55, use=None, RealPrice=None)]
    got = SH.shortlist("MLB", plays, records_for=lambda sp: {})
    assert [r["pick"].split()[0] for r in got] == ["B", "A", "D"]
    assert all(r["standing"] == SH.NO_RECORD and not r["lock"] for r in got) and got[2]["price"] == "no price yet"
    assert SH.shortlist("NBA", [], records_for=RECS.get) == [] and SH.shortlist("NBA", None) == []
