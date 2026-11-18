"""Oct 31: the Bet Log page renders with a parlay ticket, the parlay form, quick settle and NBA auto-settle."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

import betlog as B

PAGE = str(Path(__file__).parent / "views" / "18_#L01f4d2_Bet_Log.py")


def test_bet_log_books_a_parlay_once_and_shows_the_new_settle_tools(tmp_path, monkeypatch):
    db = str(tmp_path / "bets.db")
    monkeypatch.setattr(B, "DB_PATH", db)
    monkeypatch.setattr(B, "USING_POSTGRES", False)
    _real_add, _real_list, _real_upd = B.add_bet, B.list_bets, B.update_bet
    monkeypatch.setattr(B, "add_bet", lambda db_path=db, **f: _real_add(db, **f))
    monkeypatch.setattr(B, "list_bets", lambda db_path=db, **k: _real_list(db, **k))
    monkeypatch.setattr(B, "update_bet", lambda bet_id, db_path=db, **f: _real_upd(bet_id, db, **f))
    legs, _ = B.parse_leg_lines("John Collins | Rebounds | Over | 6.5\nPaul Reed | Points | Over | 11.5")
    out = B.log_parlay_ticket("Deezy SGP", legs, 1200, 20.0, "2026-10-30", "NBA",
                              game="Detroit Pistons @ Brooklyn Nets", db_path=db)
    for i in out["leg_ids"]:
        _real_upd(i, db, result="win")
    import streamlit as st
    monkeypatch.setattr(st, "page_link", lambda *a, **k: None)     # no st.navigation in a single-page test
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["trading_unlocked"] = True
    at.session_state["sport"] = "NBA"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    header = next(b for b in _real_list(db) if b["id"] == out["header_id"])
    assert header["result"] == "win"                              # the ticket settled itself from its legs
    record = next(m for m in at.metric if m.label == "Record")
    profit = next(m for m in at.metric if m.label == "Profit")
    assert record.value == "1-0" and profit.value == "$240.00"     # one $20 bet at +1200, not two -110 bets
    assert any(b.label == "Log parlay ticket" for b in at.button) or "Log parlay ticket" in str(at)


def test_a_logged_bet_can_be_fixed_or_removed(tmp_path, monkeypatch):
    db = str(tmp_path / "bets.db")
    monkeypatch.setattr(B, "DB_PATH", db)
    monkeypatch.setattr(B, "USING_POSTGRES", False)
    _real_add, _real_list, _real_upd, _real_del = B.add_bet, B.list_bets, B.update_bet, B.delete_bet
    monkeypatch.setattr(B, "add_bet", lambda db_path=db, **f: _real_add(db, **f))
    monkeypatch.setattr(B, "list_bets", lambda db_path=db, **k: _real_list(db, **k))
    monkeypatch.setattr(B, "update_bet", lambda bet_id, db_path=db, **f: _real_upd(bet_id, db, **f))
    monkeypatch.setattr(B, "delete_bet", lambda bet_id, db_path=db: _real_del(bet_id, db))
    a = _real_add(db, slate_date="2026-11-18", game="Trento @ Tortona", market="Spread", side="Tortona", line=-4.5,
                  entry_odds=-250, stake=3.0, sport="NBA", category="OFF")
    b = _real_add(db, slate_date="2026-11-18", game="x", market="Other", side="6-leg parlay", entry_odds=2400,
                  stake=4.0, sport="NBA", category="PARLAY")
    import streamlit as st
    monkeypatch.setattr(st, "page_link", lambda *a, **k: None)
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["trading_unlocked"] = True
    at.session_state["sport"] = "NBA"
    at.run()
    at.selectbox(key="fix_pick").set_value(a).run()
    at.selectbox(key=f"fix_cat_{a}").set_value("H2-beta")
    at.text_input(key=f"fix_mp_{a}").set_value("0.51")
    at.button(key=f"fix_save_{a}").click().run()
    assert not at.exception, [e.value for e in at.exception]
    got = next(x for x in _real_list(db) if x["id"] == a)
    assert got["category"] == "H2-beta" and abs(got["model_prob"] - 0.51) < 1e-9 and got["line"] == -4.5
    at.selectbox(key="fix_pick").set_value(b).run()
    assert at.button(key=f"fix_del_{b}").disabled                   # not removable until the box is ticked
    at.checkbox(key=f"fix_sure_{b}").check().run()
    at.button(key=f"fix_del_{b}").click().run()
    assert not any(x["id"] == b for x in _real_list(db))
