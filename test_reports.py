"""Reports (Nov 6): P&L statements from the Bet Log."""
from datetime import date


def _bet(i, d, stake, odds, res, **kw):
    return dict(dict(id=i, slate_date=d, stake=stake, entry_odds=odds, result=res, is_real_bet=True, sport="NBA",
                     player=f"P{i}", market="Points", side="Under", line=20.5), **kw)


def test_statement_balances_and_ignores_tracking_and_legs():
    import reports as R
    bets = [_bet(1, "2026-10-31", 10, 100, "win"),                       # before the period: in the starting balance
            _bet(2, "2026-11-05", 10, 100, "win"),
            _bet(3, "2026-11-05", 4, -110, "loss"),
            _bet(4, "2026-11-05", 5, 448, "win", market="Parlay", ticket="T1", player=None),
            _bet(5, "2026-11-05", 0, None, "win", ticket="T1"),         # a leg: no money
            _bet(6, "2026-11-05", 50, 100, "loss", is_real_bet=False),  # tracking: ignored
            _bet(7, "2026-11-06", 3, 100, None)]                          # open
    plan = {"start_bankroll": 100.0, "start_date": "2026-10-01",
            "transfers": [{"date": "2026-11-06", "amount": -20.0}, {"date": "2026-10-15", "amount": 5.0}]}
    s = R.statement(bets, "2026-11-01", "2026-11-30", plan)
    assert s["starting_balance"] == 115.0
    assert s["winnings"] == 32.4 and s["losses_amt"] == 4.0 and s["net"] == 28.4
    assert s["withdrawals"] == 20.0 and s["ending_balance"] == 123.4
    assert s["bets"] == 3 and s["open"]["bets"] == 1
    assert {r["name"] for r in s["by_type"]} == {"Single", "Parlay"}
    assert s["tax"]["deductible_cap"] == 4.0
    assert R.ledger_csv(s).startswith(b"date,sport")
    assert R.statement_pdf(s)[:4] == b"%PDF"


def test_periods():
    import reports as R
    t = date(2026, 11, 6)
    assert R.period("This month", t) == ("2026-11-01", "2026-11-06")
    assert R.period("Last month", t) == ("2026-10-01", "2026-10-31")
    assert R.period("This quarter", t) == ("2026-10-01", "2026-11-06")
    assert R.period("Last year", t) == ("2025-01-01", "2025-12-31")


def test_page_renders(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    import betlog as B
    import model_store as MS
    monkeypatch.setattr(B, "list_bets", lambda **kw: [_bet(2, "2026-11-05", 10, 100, "win")])
    monkeypatch.setattr(MS, "get_setting", lambda k, d=None: {"start_bankroll": 150.0, "start_date": "2026-11-01"})
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "48_Reports.py"), default_timeout=30)
    at.session_state["rp_period"] = "All time"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Starting balance" in m.value for m in at.markdown)
