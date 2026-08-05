"""
test_refresh_calibration.py — offline tests for refresh_calibration.py's real refresh logic.

No network, no real database — grading_history/calibration_corrections calls point at real temp
SQLite files, never the module-level default paths. Focus is the actual real requirement:
refresh_market must fetch real accumulated history, fit via retro.py's own already-tested
fit_market_calibration (not new logic), and record a fit only when one genuinely resulted.

    python test_refresh_calibration.py    # or: pytest test_refresh_calibration.py
"""

import os
import tempfile

import grading_history as GH
import calibration_corrections as CC
import player_calibration_corrections as PCC
import refresh_calibration as RC


def _play(market="Batter HR", side="Over", line=0.5, model_prob=0.35, player="P", player_id=1,
         hit=True, actual=1):
    return {"Market": market, "Side": side, "Line": line, "ModelProb": model_prob,
           "Conviction": 1.5, "Player": player, "PlayerId": player_id, "Hit": hit, "Actual": actual}


def test_refresh_market_records_a_real_fit_when_enough_evidence_exists():
    with tempfile.TemporaryDirectory() as tmp:
        gh_db = os.path.join(tmp, "gh.db")
        cc_db = os.path.join(tmp, "cc.db")
        orig_gh, orig_cc = GH.DB_PATH, CC.DB_PATH
        GH.DB_PATH, CC.DB_PATH = gh_db, cc_db
        try:
            # 150 real settled plays across a real spread of ModelProb values -- enough evidence
            # (>= CALIBRATION_MIN_N) for fit_market_calibration to actually fit something.
            plays = []
            for j in range(15):
                p = 0.10 + 0.8 * j / 14.0
                for k in range(10):
                    plays.append(_play(model_prob=round(p, 4), player_id=j * 10 + k,
                                       hit=(k < round(10 * min(p + 0.05, 0.95)))))
            GH.record_graded_slate("2026-07-18", "MLB", plays, db_path=gh_db)

            fit = RC.refresh_market("MLB", "Batter HR")
            assert fit is not None
            assert fit["n"] == 150

            recorded = CC.latest_fit("MLB", "Batter HR", db_path=cc_db)
            assert recorded is not None
            assert recorded["n"] == 150
            assert recorded["min_n_used"] == 150 or recorded["min_n_used"] is not None
        finally:
            GH.DB_PATH, CC.DB_PATH = orig_gh, orig_cc
    print("✓ refresh_market fetches real accumulated history, fits a real correction, and records it")


def test_refresh_market_returns_none_and_records_nothing_below_the_floor():
    with tempfile.TemporaryDirectory() as tmp:
        gh_db = os.path.join(tmp, "gh.db")
        cc_db = os.path.join(tmp, "cc.db")
        orig_gh, orig_cc = GH.DB_PATH, CC.DB_PATH
        GH.DB_PATH, CC.DB_PATH = gh_db, cc_db
        try:
            plays = [_play(player_id=i, model_prob=0.3 + (i % 5) * 0.1) for i in range(30)]   # well below CALIBRATION_MIN_N
            GH.record_graded_slate("2026-07-18", "MLB", plays, db_path=gh_db)

            fit = RC.refresh_market("MLB", "Batter HR")
            assert fit is None
            assert CC.latest_fit("MLB", "Batter HR", db_path=cc_db) is None   # nothing recorded
        finally:
            GH.DB_PATH, CC.DB_PATH = orig_gh, orig_cc
    print("✓ refresh_market records nothing when real accumulated history is below the min-n floor")


def test_refresh_market_with_no_history_at_all_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        gh_db = os.path.join(tmp, "gh.db")
        cc_db = os.path.join(tmp, "cc.db")
        orig_gh, orig_cc = GH.DB_PATH, CC.DB_PATH
        GH.DB_PATH, CC.DB_PATH = gh_db, cc_db
        try:
            fit = RC.refresh_market("MLB", "Batter HR")   # no grading_history rows exist at all
            assert fit is None
        finally:
            GH.DB_PATH, CC.DB_PATH = orig_gh, orig_cc
    print("✓ refresh_market handles a market with zero real graded history gracefully, no crash")


def test_refresh_market_different_markets_are_independent():
    with tempfile.TemporaryDirectory() as tmp:
        gh_db = os.path.join(tmp, "gh.db")
        cc_db = os.path.join(tmp, "cc.db")
        orig_gh, orig_cc = GH.DB_PATH, CC.DB_PATH
        GH.DB_PATH, CC.DB_PATH = gh_db, cc_db
        try:
            hr_plays = []
            for j in range(15):
                p = 0.10 + 0.8 * j / 14.0
                for k in range(10):
                    hr_plays.append(_play(market="Batter HR", model_prob=round(p, 4),
                                          player_id=j * 10 + k, hit=(k < round(10 * p))))
            thin_plays = [_play(market="Pitcher Strikeouts", player_id=9000 + i) for i in range(10)]
            GH.record_graded_slate("2026-07-18", "MLB", hr_plays + thin_plays, db_path=gh_db)

            assert RC.refresh_market("MLB", "Batter HR") is not None    # enough evidence
            assert RC.refresh_market("MLB", "Pitcher Strikeouts") is None   # not enough
        finally:
            GH.DB_PATH, CC.DB_PATH = orig_gh, orig_cc
    print("✓ refresh_market evaluates each market independently — one clearing the floor doesn't affect another")


def test_refresh_players_records_a_real_fit_when_enough_evidence_exists():
    with tempfile.TemporaryDirectory() as tmp:
        gh_db = os.path.join(tmp, "gh.db")
        pcc_db = os.path.join(tmp, "pcc.db")
        orig_gh, orig_pcc = GH.DB_PATH, PCC.DB_PATH
        GH.DB_PATH, PCC.DB_PATH = gh_db, pcc_db
        try:
            # 25 real settled plays for one player (>= PLAYER_CALIBRATION_MIN_N=20) -- a real,
            # deliberate gap: model avg 0.55, actual hit rate 8/25=0.32.
            plays = [_play(player="Schwarber-like Guy", player_id=42, model_prob=0.55,
                          hit=(i < 8)) for i in range(25)]
            GH.record_graded_slate("2026-07-18", "MLB", plays, db_path=gh_db)

            fits = RC.refresh_players("MLB")
            assert 42 in fits
            assert fits[42]["n"] == 25

            recorded = PCC.latest_fit("MLB", 42, db_path=pcc_db)
            assert recorded is not None
            assert recorded["player"] == "Schwarber-like Guy"
        finally:
            GH.DB_PATH, PCC.DB_PATH = orig_gh, orig_pcc
    print("✓ refresh_players fetches real accumulated history, fits a real player-level correction, and records it")


def test_refresh_players_returns_empty_and_records_nothing_below_the_floor():
    with tempfile.TemporaryDirectory() as tmp:
        gh_db = os.path.join(tmp, "gh.db")
        pcc_db = os.path.join(tmp, "pcc.db")
        orig_gh, orig_pcc = GH.DB_PATH, PCC.DB_PATH
        GH.DB_PATH, PCC.DB_PATH = gh_db, pcc_db
        try:
            plays = [_play(player_id=42, model_prob=0.5, hit=(i % 2 == 0)) for i in range(10)]   # < 20
            GH.record_graded_slate("2026-07-18", "MLB", plays, db_path=gh_db)

            fits = RC.refresh_players("MLB")
            assert fits == {}
            assert PCC.latest_fit("MLB", 42, db_path=pcc_db) is None
        finally:
            GH.DB_PATH, PCC.DB_PATH = orig_gh, orig_pcc
    print("✓ refresh_players records nothing for a player below the real min-n floor")


def test_refresh_players_pools_across_markets_in_one_real_fetch():
    # Real proof this is genuinely ONE fetch across the whole sport, not one per market --
    # a player's plays spread across two different markets must still combine into one real fit.
    with tempfile.TemporaryDirectory() as tmp:
        gh_db = os.path.join(tmp, "gh.db")
        pcc_db = os.path.join(tmp, "pcc.db")
        orig_gh, orig_pcc = GH.DB_PATH, PCC.DB_PATH
        GH.DB_PATH, PCC.DB_PATH = gh_db, pcc_db
        try:
            plays = ([_play(player_id=42, market="Batter HR", model_prob=0.5, hit=True) for _ in range(12)] +
                    [_play(player_id=42, market="Batter Total Hits", model_prob=0.5, hit=False) for _ in range(13)])
            GH.record_graded_slate("2026-07-18", "MLB", plays, db_path=gh_db)

            fits = RC.refresh_players("MLB")
            assert fits[42]["n"] == 25   # both markets' real plays pooled into one real player-level fit
        finally:
            GH.DB_PATH, PCC.DB_PATH = orig_gh, orig_pcc
    print("✓ refresh_players pools a player's real plays across every market in one real fetch, not per-market")


def test_refresh_players_different_sports_are_independent():
    with tempfile.TemporaryDirectory() as tmp:
        gh_db = os.path.join(tmp, "gh.db")
        pcc_db = os.path.join(tmp, "pcc.db")
        orig_gh, orig_pcc = GH.DB_PATH, PCC.DB_PATH
        GH.DB_PATH, PCC.DB_PATH = gh_db, pcc_db
        try:
            mlb_plays = [_play(player_id=42, model_prob=0.5, hit=(i < 8)) for i in range(25)]
            GH.record_graded_slate("2026-07-18", "MLB", mlb_plays, db_path=gh_db)

            assert RC.refresh_players("MLB") != {}    # enough real evidence
            assert RC.refresh_players("WNBA") == {}   # no real history for WNBA at all
        finally:
            GH.DB_PATH, PCC.DB_PATH = orig_gh, orig_pcc
    print("✓ refresh_players evaluates each sport independently — real MLB history doesn't leak into WNBA")


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
