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


# ----------------------------------------------------------------- filter_bets_since
def test_filter_bets_since_excludes_bets_before_the_date():
    bets = [
        {"player": "Before", "ts_placed": "2026-07-15T12:00:00"},
        {"player": "On the day", "ts_placed": "2026-08-01T09:00:00"},
        {"player": "After", "ts_placed": "2026-08-05T18:30:00"},
    ]
    out = B.filter_bets_since(bets, "2026-08-01")
    names = {b["player"] for b in out}
    assert names == {"On the day", "After"}
    print("✓ filter_bets_since keeps bets placed ON the cutoff date and after, excludes earlier ones")


def test_filter_bets_since_no_filter_returns_everything_unchanged():
    bets = [{"player": "A", "ts_placed": "2026-07-15T12:00:00"},
           {"player": "B", "ts_placed": "2026-08-05T18:30:00"}]
    assert B.filter_bets_since(bets, None) == bets
    assert B.filter_bets_since(bets, "") == bets
    print("✓ filter_bets_since is a genuine no-op (not just 'returns everything' by coincidence) "
         "when no since-date is given -- the explicit 'off' state")


def test_filter_bets_since_excludes_bets_with_no_placed_date():
    # A real edge case: a bet with no ts_placed at all can't honestly be said to be "on or
    # after" any date -- must be excluded, not incorrectly included by treating missing as "0000".
    bets = [{"player": "No date"}, {"player": "Has date", "ts_placed": "2026-08-05T00:00:00"}]
    out = B.filter_bets_since(bets, "2026-08-01")
    assert len(out) == 1 and out[0]["player"] == "Has date"
    print("✓ filter_bets_since excludes a bet with no known placement date, doesn't guess it's in range")


def test_filter_bets_since_real_regression_a_since_date_actually_narrows_the_real_window():
    # Direct regression guard for the real, reported gap this closes: before this existed, there
    # was no way to check whether real results looked different after a specific date. Confirms
    # the narrowed set really IS smaller when there's real history before the cutoff.
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        B.add_bet(db, player="Old Pick", market="Batter HR", stake=5.0)
        bets = B.list_bets(db)
        bets[0]["ts_placed"] = "2026-01-01T00:00:00"   # simulate an old bet directly
        recent = B.filter_bets_since(bets, "2026-08-01")
        assert len(recent) == 0
        assert len(B.filter_bets_since(bets, None)) == 1
        print("✓ filter_bets_since genuinely narrows the real window -- the actual fix, not just "
             "a function that exists but doesn't change anything")


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
    assert B.clv_pct(100, float("nan")) is None   # NaN treated the same as None


def test_clv_pct_through_a_real_dataframe_not_just_direct_calls():
    # Regression guard for a real production bug: Bet Log's Ledger table and CSV export both do
    # `df = pd.DataFrame(bets)` before calling clv_pct row by row via df.apply(...). Once a bet
    # dict's close_odds=None sits in the same numeric column as OTHER bets' real close_odds
    # values, pandas silently upcasts the whole column to float64 and turns that None into NaN --
    # confirmed here, not assumed. `clv_pct(x, None) is None` (the test above) passed even before
    # the fix; it never exercised this NaN path, which is exactly how a real bug shipped past
    # test coverage that only ever called clv_pct directly with a literal None.
    #
    # Caught via a real user's CSV export: 34% of bets with no captured close showed a
    # fabricated, always-positive CLV% (a +252 entry with no close showed "CLV% = 252.00")
    # instead of a blank cell -- exactly (american_to_decimal(entry_odds) - 1) * 100, i.e.
    # american_to_decimal's own "invalid odds" fallback (decimal 1.0) silently standing in for
    # the missing close.
    import pandas as pd

    bets = [
        {"entry_odds": -110, "close_odds": -120},   # has a real close
        {"entry_odds": 252, "close_odds": None},    # no close captured yet
    ]
    df = pd.DataFrame(bets)
    assert df["close_odds"].dtype == float, (
        "test setup check: this only reproduces the bug if pandas actually upcast the missing "
        "value to a float column (NaN), matching the real Ledger/export code path"
    )
    df["CLV%"] = df.apply(lambda r: B.clv_pct(r.get("entry_odds"), r.get("close_odds")), axis=1)

    assert df.loc[0, "CLV%"] == 4.13    # real close: normal CLV math, unaffected
    assert pd.isna(df.loc[1, "CLV%"]), (
        f"bet with no captured close_odds should show a blank/missing CLV%, not a fabricated "
        f"number -- got {df.loc[1, 'CLV%']!r}"
    )
    print("✓ clv_pct correctly returns missing (not a fabricated number) for a NaN close_odds "
         "arriving via a real pandas DataFrame, matching Bet Log's actual Ledger/export code path")


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


def test_bet_pnl_uses_cashout_amount_when_present_regardless_of_final_result():
    # The core behavior: cashing out locks in a real dollar amount, independent of what the
    # bet's legs go on to do. Same cashed_out_amount, opposite eventual results, identical
    # actual P&L -- because what was actually realized was the cash-out, not the result.
    won_after_cashout = {"stake": 25.0, "entry_odds": 350, "result": "win", "cashed_out_amount": 14.0}
    lost_after_cashout = {"stake": 25.0, "entry_odds": 350, "result": "loss", "cashed_out_amount": 14.0}
    assert B.bet_pnl(won_after_cashout) == -11.0
    assert B.bet_pnl(lost_after_cashout) == -11.0
    print("✓ bet_pnl uses the cash-out amount as the real P&L regardless of the eventual result")


def test_bet_pnl_falls_back_to_normal_result_math_without_a_cashout():
    won = {"stake": 25.0, "entry_odds": 350, "result": "win"}
    assert B.bet_pnl(won) == 87.5   # normal win math, unaffected by the new cash-out path
    print("✓ bet_pnl behaves exactly as before for a bet that was never cashed out")


def test_pnl_if_held_ignores_cashout_and_shows_the_real_counterfactual():
    bet = {"stake": 25.0, "entry_odds": 350, "result": "win", "cashed_out_amount": 14.0}
    assert B._pnl_if_held(bet) == 87.5   # what it WOULD have paid, ignoring the cash-out
    assert B.bet_pnl(bet) == -11.0        # what was ACTUALLY realized
    print("✓ _pnl_if_held shows the real counterfactual, independent of bet_pnl's actual number")


def test_cash_out_vs_held_aggregates_correctly_and_excludes_ungraded_bets():
    left_money_on_table = {"stake": 25.0, "entry_odds": 350, "result": "win", "cashed_out_amount": 14.0}
    cashout_saved_a_loss = {"stake": 25.0, "entry_odds": 350, "result": "loss", "cashed_out_amount": 14.0}
    still_pending = {"stake": 10.0, "entry_odds": 200, "result": None, "cashed_out_amount": 8.0}
    never_cashed_out = {"stake": 10.0, "entry_odds": 200, "result": "win"}   # excluded entirely

    report = B.cash_out_vs_held(
        [left_money_on_table, cashout_saved_a_loss, still_pending, never_cashed_out])

    assert report["n"] == 2   # only the two GRADED cash-outs count; pending and non-cashed excluded
    assert report["total_actual_pnl"] == -22.0    # -11 + -11
    assert report["total_held_pnl"] == 62.5       # 87.5 + -25.0
    assert report["net_value_of_cashing_out"] == -84.5
    print("✓ cash_out_vs_held aggregates correctly and excludes still-pending or never-cashed-out bets")


def test_cashed_out_amount_persists_through_a_real_sqlite_round_trip():
    # Same "confirm against a real database round-trip" discipline this file already holds to
    # for the ticket column above -- the new column must actually survive add_bet -> list_bets,
    # not just work in isolated dict-based unit tests.
    import tempfile
    import os
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "bets.db")
        B.add_bet(db, player="Rocchio", entry_odds=350, stake=25.0, result="win",
                 cashed_out_amount=14.0)
        B.add_bet(db, player="Never Cashed", entry_odds=200, stake=10.0, result="win")
        bets = B.list_bets(db)
        rocchio = next(b for b in bets if b["player"] == "Rocchio")
        never = next(b for b in bets if b["player"] == "Never Cashed")
        assert float(rocchio["cashed_out_amount"]) == 14.0
        assert B.bet_pnl(rocchio) == -11.0
        assert never.get("cashed_out_amount") is None
        assert B.bet_pnl(never) == 20.0   # normal win math for the never-cashed-out bet (+200 on $10)
    print("✓ cashed_out_amount persists correctly through a real SQLite add_bet/list_bets round trip")


def test_real_price_clv_summary_excludes_model_fair_bets():
    # Regression guard for the actual fix: a bet whose entry_odds is really just the model's own
    # Fair price re-derived from model_prob must never count toward this specific metric, even
    # if it happens to have a close_odds recorded -- only entry_odds_source == "book" counts.
    bets = [
        {"entry_odds": -150, "close_odds": -170, "entry_odds_source": "book"},
        {"entry_odds": -110, "close_odds": -105, "entry_odds_source": "book"},
        {"entry_odds": -282, "close_odds": -260, "entry_odds_source": "model_fair"},
        {"entry_odds": +120, "close_odds": None, "entry_odds_source": "book"},
    ]
    result = B.real_price_clv_summary(bets)
    assert result["n_real_price"] == 3
    assert result["n_total"] == 4
    assert result["clv_n"] == 2   # only the 2 real-price bets that also have a close_odds
    print("✓ real_price_clv_summary correctly excludes model_fair-sourced bets from the CLV math")


def test_real_price_clv_summary_empty_when_no_real_price_bets_exist():
    # The expected state for almost every bet logged before this fix shipped.
    bets = [
        {"entry_odds": -150, "close_odds": -170, "entry_odds_source": "model_fair"},
        {"entry_odds": -110, "close_odds": -105, "entry_odds_source": None},   # legacy, pre-fix row
    ]
    result = B.real_price_clv_summary(bets)
    assert result["n_real_price"] == 0
    assert result["avg_clv"] is None
    assert result["beat_close_rate"] is None
    print("✓ real_price_clv_summary returns an honest empty result, not zero or a crash, when no "
         "bet has a real captured price yet")


def test_real_price_clv_summary_missing_entry_odds_source_treated_as_not_real():
    # A pre-existing row from before this column existed has no entry_odds_source at all
    # (None) -- must NOT be silently counted as a real price just because it's not explicitly
    # tagged "model_fair".
    bets = [{"entry_odds": -150, "close_odds": -170}]   # no entry_odds_source key at all
    result = B.real_price_clv_summary(bets)
    assert result["n_real_price"] == 0
    print("✓ a bet with no entry_odds_source at all is correctly treated as not a real price, "
         "not silently included")


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
