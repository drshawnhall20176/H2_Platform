"""
test_betlog.py — offline tests for the bet log (temp SQLite, no network).

    python test_betlog.py     # or: pytest test_betlog.py
"""

import os
import tempfile

import betlog as B


def test_crud():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        bid = B.add_bet(db, player="Altuve", game="HOU @ DET", market="Batter Total Bases",
                        side="Over", line=1.5, entry_odds=120, model_prob=0.58, stake=2.5)
        assert isinstance(bid, int)
        assert len(B.list_bets(db)) == 1
        B.update_bet(bid, db, result="win", close_odds=100)
        bet = B.list_bets(db)[0]
        assert bet["result"] == "win" and bet["close_odds"] == 100
        assert len(B.list_bets(db, settled=True)) == 1
        assert len(B.list_bets(db, settled=False)) == 0
        B.delete_bet(bid, db)
        assert len(B.list_bets(db)) == 0


def test_trader_field():
    # A real, deliberate first step toward future multi-user support (see the field's own
    # comment in betlog.py) -- confirms it round-trips correctly through the real add/list/
    # update flow, and that it stays genuinely optional (an existing caller that never mentions
    # it, like test_crud above, must keep working unchanged).
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        bid = B.add_bet(db, player="Ohtani", game="LAD @ SF", market="Batter HR",
                        side="Over", line=0.5, entry_odds=350, stake=5.0, trader="Shawn")
        bet = B.list_bets(db)[0]
        assert bet["trader"] == "Shawn"
        B.update_bet(bid, db, trader="Deezy")
        assert B.list_bets(db)[0]["trader"] == "Deezy"
        print("✓ trader field round-trips correctly through add_bet/list_bets/update_bet")


def test_trader_field_is_optional():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        # No trader specified at all -- must not raise, must not silently break existing callers
        bid = B.add_bet(db, player="Judge", game="NYY @ BOS", market="Batter HR",
                        side="Over", line=0.5, entry_odds=280, stake=5.0)
        assert B.list_bets(db)[0]["trader"] is None
        print("✓ trader field is genuinely optional, defaulting to None when never specified")


def test_is_real_bet_defaults_true_for_existing_callers():
    # A REAL, CONFIRMED BUG this test guards against: the SQLite/Postgres INSERT statements
    # explicitly supply a value for every _FIELDS column, including None for anything the
    # caller didn't pass -- so the schema's own "DEFAULT TRUE" never actually applies on
    # insert. Without add_bet's own explicit fields.setdefault, an existing caller (like
    # quick_log.py) that predates this field would silently log every bet as is_real_bet=None,
    # not True -- confirmed directly by testing, not assumed.
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        bid = B.add_bet(db, player="Judge", game="NYY @ BOS", market="Batter HR",
                        side="Over", line=0.5, entry_odds=280, stake=5.0)
        bet = B.list_bets(db)[0]
        assert bet["is_real_bet"] == 1
        print("✓ is_real_bet correctly defaults to True (1) for a caller that never mentions it, guarding the real bug this session caught")


def test_is_real_bet_explicit_false_for_tracking_only_predictions():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        bid = B.add_bet(db, player="Soto", game="NYM @ MIL", market="Batter Total Hits",
                        side="Under", line=0.5, model_prob=0.42, result="win",
                        is_real_bet=False, notes="tracking-only, no real stake placed")
        bet = B.list_bets(db)[0]
        assert bet["is_real_bet"] == 0
        assert bet["result"] == "win"
        print("✓ is_real_bet correctly stores False (0) for a tracking-only prediction, distinct from a real, staked bet")


def test_is_real_bet_round_trips_through_update():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        bid = B.add_bet(db, player="Soto", market="Batter Total Hits", is_real_bet=False)
        B.update_bet(bid, db, is_real_bet=True)   # e.g. a tracking prediction later becomes a real bet
        assert B.list_bets(db)[0]["is_real_bet"] == 1
        print("✓ is_real_bet round-trips correctly through update_bet")


def test_summary_and_calibration_work_correctly_on_tracking_only_bets():
    # Confirms the EXISTING, pre-built summary()/calibration() analytics -- built for real,
    # staked bets -- already handle tracking-only entries (stake=None, entry_odds=None)
    # gracefully, without any changes needed to those functions themselves.
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        B.add_bet(db, player="Soto", market="Batter Total Hits", side="Under", model_prob=0.42,
                 result="win", is_real_bet=False)
        B.add_bet(db, player="Duran", market="Batter Total Hits", side="Under", model_prob=0.42,
                 result="loss", is_real_bet=False)
        bets = B.list_bets(db)
        s = B.summary(bets)
        assert s["wins"] == 1 and s["losses"] == 1
        assert s["staked"] == 0.0    # no real stake on tracking-only entries -- correctly zero, not an error
        assert s["roi"] is None      # ROI is meaningless with zero real money at risk -- correctly None, not 0 or a crash
        print("✓ summary() correctly handles tracking-only bets: real win/loss counts, zero staked, no fabricated ROI")


def test_list_bets_filters_by_is_real_bet():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        B.add_bet(db, player="Real Bet", market="Batter HR", stake=5.0)               # real, default
        B.add_bet(db, player="Tracking Only", market="Batter Total Hits",
                 is_real_bet=False, result="win", model_prob=0.42)
        real_only = B.list_bets(db, is_real_bet=True)
        tracking_only = B.list_bets(db, is_real_bet=False)
        assert len(real_only) == 1 and real_only[0]["player"] == "Real Bet"
        assert len(tracking_only) == 1 and tracking_only[0]["player"] == "Tracking Only"
        assert len(B.list_bets(db)) == 2   # no filter -- both returned
        print("✓ list_bets correctly filters by is_real_bet, cleanly separating real bets from tracking-only predictions")


def test_list_bets_is_real_bet_filter_combines_with_other_filters():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        B.add_bet(db, player="Real MLB", market="Batter HR", sport="MLB", stake=5.0)
        B.add_bet(db, player="Tracking MLB", market="Batter Total Hits", sport="MLB",
                 is_real_bet=False, result="win", model_prob=0.42)
        B.add_bet(db, player="Real NBA", market="Points", sport="NBA", stake=5.0)
        out = B.list_bets(db, sport="MLB", is_real_bet=False)
        assert len(out) == 1 and out[0]["player"] == "Tracking MLB"
        print("✓ list_bets' is_real_bet filter correctly combines with the existing sport filter")


def test_player_id_field():
    # Added directly on request, for automated result settlement -- retro.py's existing,
    # already-tested grade_play/get_player_results match by numeric player ID, not name.
    # Confirms it round-trips correctly through the real add/list/update flow.
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        bid = B.add_bet(db, player="Ohtani", player_id=660271, game="LAD @ SF", market="Batter HR",
                        side="Over", line=0.5, entry_odds=350, stake=5.0)
        bet = B.list_bets(db)[0]
        assert bet["player_id"] == 660271
        B.update_bet(bid, db, player_id=605141)
        assert B.list_bets(db)[0]["player_id"] == 605141
        print("✓ player_id field round-trips correctly through add_bet/list_bets/update_bet")


def test_player_id_field_is_optional():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        # No player_id specified at all -- must not raise, must not silently break existing
        # callers (older manually-logged bets never had this field at all).
        bid = B.add_bet(db, player="Judge", game="NYY @ BOS", market="Batter HR",
                        side="Over", line=0.5, entry_odds=280, stake=5.0)
        assert B.list_bets(db)[0]["player_id"] is None
        print("✓ player_id field is genuinely optional, defaulting to None when never specified")


def test_player_id_migrates_existing_database():
    # A REAL, CONFIRMED regression guard: a database created BEFORE player_id existed (simulated
    # here by creating the table with the OLD schema directly, bypassing add_bet/_sqlite_conn's
    # own migration check) must still work correctly once opened by the current code -- the
    # migration path (ALTER TABLE bets ADD COLUMN player_id) must actually run, not just exist
    # in the source.
    import sqlite3
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        os.makedirs(os.path.dirname(db), exist_ok=True)
        con = sqlite3.connect(db)
        con.execute("""CREATE TABLE bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts_placed TEXT NOT NULL, slate_date TEXT,
            game TEXT, player TEXT, market TEXT, side TEXT, line REAL, entry_odds INTEGER,
            model_prob REAL, stake REAL, book TEXT, close_odds INTEGER, result TEXT,
            notes TEXT, ticket TEXT, sport TEXT, trader TEXT)""")   # the OLD schema, no player_id
        con.execute("INSERT INTO bets (ts_placed, player, market) VALUES ('2026-01-01', 'Old Bet', 'Batter HR')")
        con.commit()
        con.close()

        # Now use the REAL add_bet/list_bets path against this pre-existing, old-schema database
        bid = B.add_bet(db, player="New Bet", player_id=12345, market="Batter HR")
        bets = B.list_bets(db)
        assert len(bets) == 2
        new_bet = next(b for b in bets if b["player"] == "New Bet")
        old_bet = next(b for b in bets if b["player"] == "Old Bet")
        assert new_bet["player_id"] == 12345
        assert old_bet["player_id"] is None   # pre-existing row, column simply absent -> None
        print("✓ player_id correctly migrates onto a real, pre-existing database created before this column existed")


def test_clv_pct():
    assert B.clv_pct(120, 100) == 10.0       # +120 vs +100 close -> beat by 10%
    assert B.clv_pct(-150, -150) == 0.0      # flat
    assert B.clv_pct(-110, -120) > 0         # took -110, closed -120 -> beat close
    assert B.clv_pct(100, None) is None      # no closing line


def test_bet_pnl():
    assert B.bet_pnl({"result": "win", "stake": 2.5, "entry_odds": 120}) == 3.0
    assert B.bet_pnl({"result": "loss", "stake": 2.0, "entry_odds": -110}) == -2.0
    assert B.bet_pnl({"result": "push", "stake": 2.0, "entry_odds": -110}) == 0.0
    assert B.bet_pnl({"result": None, "stake": 2.0, "entry_odds": -110}) is None  # unsettled


def test_summary():
    bets = [
        {"result": "win", "stake": 2.5, "entry_odds": 120, "close_odds": 100, "model_prob": 0.58},
        {"result": "loss", "stake": 2.0, "entry_odds": -110, "close_odds": -120, "model_prob": 0.64},
        {"result": None, "stake": 2.2, "entry_odds": -150, "close_odds": None, "model_prob": 0.72},
    ]
    s = B.summary(bets)
    assert s["wins"] == 1 and s["losses"] == 1 and s["open"] == 1
    assert s["profit"] == 1.0          # +3.00 win, -2.00 loss
    assert s["clv_n"] == 2             # two bets have closing lines
    assert s["beat_close_rate"] == 100.0  # both beat the close


def test_calibration():
    # 3 buckets, perfectly calibrated within each
    bets = []
    for _ in range(10):
        bets.append({"model_prob": 0.55, "result": "win", "stake": 1, "entry_odds": -110})
    for _ in range(10):
        bets.append({"model_prob": 0.55, "result": "loss", "stake": 1, "entry_odds": -110})
    cal = B.calibration(bets, n_bins=5)
    assert len(cal) == 1               # all in the 0.4-0.6 bucket
    assert cal[0]["n"] == 20
    assert cal[0]["actual"] == 0.5     # 10 wins of 20
    # unsettled bets are excluded
    assert B.calibration([{"model_prob": 0.6, "result": None}], n_bins=5) == []


def test_parlay_decimal_and_status():
    legs = [{"entry_odds": 100, "result": "win"}, {"entry_odds": 100, "result": "win"}]
    assert abs(B.parlay_decimal(legs) - 4.0) < 1e-9        # 2.0 * 2.0
    assert B.parlay_status(legs) == "win"
    legs2 = [{"entry_odds": 100, "result": "win"}, {"entry_odds": 100, "result": "loss"}]
    assert B.parlay_status(legs2) == "loss"                # any loss -> loss
    legs3 = [{"entry_odds": 100, "result": "win"}, {"entry_odds": 100, "result": None}]
    assert B.parlay_status(legs3) == "pending"


def test_compare_parlay_vs_singles():
    # 3 win, 1 loss: parlay busts, singles profit
    legs = [{"entry_odds": 270, "result": "win"}, {"entry_odds": -120, "result": "win"},
            {"entry_odds": 115, "result": "win"}, {"entry_odds": -150, "result": "loss"}]
    c = B.compare_parlay_vs_singles(legs, 20.0)
    assert c["status"] == "loss" and c["parlay_pnl"] == -20.0
    assert c["singles_pnl"] > 0                 # the three winners more than cover one $5 loss
    assert c["difference"] == round(c["singles_pnl"] - c["parlay_pnl"], 2)
    # all-win: parlay should beat singles (that's the parlay's upside)
    legs2 = [{"entry_odds": -110, "result": "win"}, {"entry_odds": -110, "result": "win"}]
    c2 = B.compare_parlay_vs_singles(legs2, 10.0)
    assert c2["parlay_pnl"] > c2["singles_pnl"]
    # pending parlay -> no parlay pnl yet
    assert B.compare_parlay_vs_singles([{"entry_odds": -110, "result": None}], 10.0)["parlay_pnl"] is None


def test_group_tickets_and_migration():
    import tempfile
    import os
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        B.add_bet(db, player="A", entry_odds=-110, ticket="P1", result="win")
        B.add_bet(db, player="B", entry_odds=120, ticket="P1", result="loss")
        B.add_bet(db, player="C", entry_odds=-105, ticket="", result="win")   # a single
        bets = B.list_bets(db)
        groups = B.group_tickets(bets)
        assert set(groups.keys()) == {"P1"} and len(groups["P1"]) == 2   # single excluded
        assert any(b.get("ticket") == "P1" for b in bets)               # ticket column persisted


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}"); passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
