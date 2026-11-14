"""Nov 14: the day's long-shot scan and the public build's guards."""
import long_shots_scan as LSS


def _r(player, price, honest, ev, market="Assists", flags="", proj=6.0, main=5.5):
    return {"Player": player, "Bet": f"8+ {market}", "Market": market, "Price": price, "Honest chance": honest,
            "EV per $1": ev, "Flags": flags, "Projection": proj, "Main line": main}


def test_pick_top_most_probable_value_long_shots_one_per_player():
    rows = [_r("A", 1500, 0.12, 0.9), _r("A", 900, 0.15, 0.5), _r("B", 300, 0.30, 0.2),     # B under +400
            _r("C", 2000, 0.10, -0.1), _r("D", 1200, 0.11, 0.4, flags="check news"),          # C no value, D flagged
            _r("E", 700, 0.14, 0.1), _r("F", 450, 0.20, 0.05), _r("G", 2500, 0.05, 0.3)]
    top = LSS.pick_top(rows)
    assert [r["Player"] for r in top] == ["F", "A", "E", "G"]
    assert top[1]["Price"] == 900                                # A's most probable rung, not the +1500


def test_stale():
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 11, 14, 15, tzinfo=timezone.utc)
    assert LSS.stale(None, now) and LSS.stale({"at": (now - timedelta(hours=4)).isoformat()}, now)
    assert not LSS.stale({"at": (now - timedelta(hours=1)).isoformat()}, now)


def test_public_build_never_logs(monkeypatch):
    import components as C
    import log_ui as LU
    import pandas as pd
    monkeypatch.setattr(C, "is_owner", lambda: False)
    calls = []
    monkeypatch.setattr(LU.st, "dataframe", lambda df, **k: calls.append(k))
    assert LU.selectable(pd.DataFrame([{"a": 1}]), "k") == [] and "on_select" not in calls[0]
    monkeypatch.setattr(LU.st, "button", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no buttons")))
    LU.panel([{"sport": "NBA", "pick": "x", "price": 500}], "k", "2026-11-14")        # returns without a button


def test_props_rows_keep_every_lock(monkeypatch):
    import props_engine as PE
    import todays_best as TB
    monkeypatch.setattr(PE, "most_probable", lambda p, c, g: p >= 0.7)
    plays = [{"Player": f"L{i}", "Market": "Points", "Side": "Over", "Line": 10.5, "ModelProb": 0.75,
              "Use": PE.USE_PARLAY} for i in range(50)]
    plays += [{"Player": f"P{i}", "Market": "Points", "Side": "Over", "Line": 10.5, "ModelProb": 0.6,
               "Use": PE.USE_PARLAY} for i in range(50)]
    out = TB.props_rows("NBA", plays)
    assert sum(r["lock"] for r in out) == 50 and len(out) == 50 + TB.TOP_PER_SPORT


def test_disagreements_with_the_book_are_not_most_probable():
    sharpe = _r("Sharpe", 433, 0.49, 1.6, proj=7.5, main=4.5)          # the book knows something
    kyrie = _r("Kyrie", 420, 0.24, 0.26, market="Points", proj=25.2, main=21.5)
    threes = _r("Thomas", 471, 0.32, 0.8, market="Threes Made", proj=3.2, main=1.5)
    assert [r["Player"] for r in LSS.pick_top([sharpe, kyrie, threes])] == ["Kyrie"]
    assert not LSS.agrees({"Projection": 6.0})                          # no main line: can't tell
