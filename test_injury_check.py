import injury_check as IC
import long_shots_scan as LSS


def test_classify_reads_status_and_report():
    assert IC.classify("Out", "") == "out"
    assert IC.classify("Day-To-Day", "Barrett (hamstring) is out for Wednesday's game against the Wizards") == "out"
    assert IC.classify("Day-To-Day", "Wade (hamstring) has been downgraded to questionable for Wednesday's game") == "questionable"
    assert IC.classify("Day-To-Day", "Maxey closed Monday's win with 24 points, nine assists") is None
    assert IC._norm("Michael Porter Jr.") == "michael porter"


def _row(player, chance, price=500):
    return {"Player": player, "Bet": "45+ PRA", "pick": f"{player} 45+ PRA", "Price": price, "EV per $1": 0.5,
            "Honest chance": chance, "Projection": 40, "Main line": 38, "Flags": []}


def test_saved_long_shots_drop_players_ruled_out_after_the_scan():
    """Nov 18: RJ Barrett topped the 4:13 PM scan; he was ruled out at 5:55 PM."""
    saved = {"at": "x", "rows": [_row("RJ Barrett", 0.31), _row("Dean Wade", 0.27), _row("Davion Mitchell", 0.30),
                                 _row("Isaiah Hartenstein", 0.26)]}
    saved["top"] = LSS.pick_top(saved["rows"])
    st = {"RJ Barrett": "out", "Dean Wade": "questionable"}.get
    got = LSS.recheck(saved, "NBA", status=st)
    assert [r["Player"] for r in got["top"]] == ["Davion Mitchell", "Isaiah Hartenstein"]
    assert "RJ Barrett" not in {r["Player"] for r in got["rows"]}
    wade = next(r for r in got["rows"] if r["Player"] == "Dean Wade")
    assert "(questionable)" in wade["pick"] and wade["Flags"]
    assert LSS.recheck(saved, "NBA", status=lambda n: None) is saved
    assert LSS.load("NBA", "d", get=lambda k: saved) is saved              # tests' store: no live check


def test_report_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(IC, "_fetch", lambda s: calls.append(s) or {"rj barrett": "out"})
    IC._cache.clear()
    assert IC.report("NBA", now=1000) == {"rj barrett": "out"} and IC.report("NBA", now=1300)
    assert calls == ["NBA"]
    IC.report("NBA", now=2000)
    assert calls == ["NBA", "NBA"]
    IC._cache.clear()
