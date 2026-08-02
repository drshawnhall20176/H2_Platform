"""
test_best_bets_data.py — offline tests for best_bets_data.py, the shared MLB best-bets board
loader used by both Best Bets and Command Center.

Regression guard for a real production bug: before this shared module existed, Best Bets and
Command Center each had their OWN separate copy of this loading logic. When the bullpen-blend
re-pricing fix was added, it only landed in Best Bets' own copy — Command Center's separate copy
silently kept showing the old, unblended conviction numbers for the same plays, with no error.
These tests exist to make sure that specific class of drift can't happen again: both view files
now call the exact same function, and these tests exercise that function directly.

No network required.
"""

import inspect
from unittest.mock import patch

import best_bets_data as BBD
import mlb_engine as E
import projections as P


def test_module_imports_mlb_modules_directly_not_via_sport_dispatch():
    # Regression guard for a real risk found and fixed while building this module: routing E/P
    # through sports.active() at module import time would freeze them to whatever sport was
    # active on FIRST import (Python only runs a module's top-level code once per process), a
    # real risk this module didn't have when the same logic was inline in each view file (which
    # re-runs fresh on every Streamlit page load). Confirms the actual fix, not just the intent.
    assert BBD.E is E
    assert BBD.P is P
    print("✓ best_bets_data.E/P are directly mlb_engine/projections, not sports.active()-dependent")


def test_load_mlb_best_bets_board_signature():
    sig = inspect.signature(BBD.load_mlb_best_bets_board)
    assert list(sig.parameters.keys()) == ["date_str", "fip_constant", "preferred_book",
                                           "venue_split", "time_split"]


def _fake_row_and_meta():
    fake_hitter_stat = dict(plateAppearances=600, atBats=540, hits=165, doubles=34, triples=2,
                            homeRuns=38, baseOnBalls=55, strikeOuts=140)
    bad_starter_stat = dict(gamesStarted=15, inningsPitched="75.0", battersFaced=400,
                            strikeOuts=60, baseOnBalls=45, homeRuns=20, hits=115)
    fake_row = {
        "Hitter": "Test Slugger", "Team": "Test Team", "GameLabel": "Away @ Home (Game 1)",
        "Hand": "L", "Opp Pitcher": "Bad Starter", "Opp Hand": "R", "Opp HR/9": 1.8,
        "Advantage": "Advantage", "Lineup": "Confirmed", "HR": 38, "Hits": 165, "TB": 300,
        "AVG": 0.28, "OBP": 0.36, "SLG": 0.52, "OPS": 0.88, "ISO": 0.24, "K%": 0.14,
        "PowerIndex": 50.0, "_pid": 501, "_stat": fake_hitter_stat, "_exp_pa": 4.55,
        "_venue_id": None, "_opp_stat": bad_starter_stat, "_opp_pid": 601, "_opp_id": 114,
        "_split_stat": None, "_lineup_idx": 0,
    }
    fake_meta = [{"label": "Away @ Home (Game 1)", "game_date": "2026-07-18", "venue": "Test Park",
                 "venue_id": None, "home_name": "Home Team", "away_name": "Away Team",
                 "home_id": 999, "away_id": 114,
                 "home_pm": E.PitcherMetrics(id=601, name="Bad Starter", hand="R", stat=bad_starter_stat),
                 "away_pm": E.PitcherMetrics(id=701, name="Home Starter", hand="R", stat=bad_starter_stat)}]
    return fake_row, fake_meta


def test_load_mlb_best_bets_board_full_pipeline_runs_and_blends():
    fake_row, fake_meta = _fake_row_and_meta()
    good_pen_stat = dict(strikeOuts=350, baseOnBalls=100, hitByPitch=12, homeRuns=38,
                         battersFaced=2000, hits=420, atBats=1780, earnedRuns=200,
                         inningsPitched="500.0")

    with patch.object(BBD.E, "build_slate", lambda date_str, fip: ([fake_row], fake_meta)), \
        patch.object(BBD.E, "get_bullpen_aggregate_stat",
                    lambda tid, exclude_pid=None, fip_constant=3.10: good_pen_stat), \
        patch("statcast_data.load", lambda: ({}, None)), \
        patch("weather.get_game_weather", lambda *a, **k: None):
        plays, meta, available_books = BBD.load_mlb_best_bets_board("2026-07-18", BBD.E.FIP_CONSTANT_DEFAULT)

    assert len(meta) == 1
    assert len(plays) > 0
    hr_play = next(p for p in plays if p["Market"] == "Batter HR")
    assert hr_play.get("_bullpen_blended") is True
    print("✓ load_mlb_best_bets_board runs the full pipeline end to end, including the bullpen blend")


def test_load_mlb_best_bets_board_returns_meta_not_just_count():
    # A real interface bug caught while wiring this in: Command Center needs the full meta list
    # (it never did Slot/Time enrichment at all), while Best Bets needs it to build its own
    # Slot/Time enrichment. An earlier draft returned len(meta) instead, breaking both callers'
    # actual needs. This locks in the correct return shape.
    fake_row, fake_meta = _fake_row_and_meta()

    with patch.object(BBD.E, "build_slate", lambda date_str, fip: ([fake_row], fake_meta)), \
        patch.object(BBD.E, "get_bullpen_aggregate_stat", lambda *a, **k: None), \
        patch("statcast_data.load", lambda: ({}, None)), \
        patch("weather.get_game_weather", lambda *a, **k: None):
        plays, meta, available_books = BBD.load_mlb_best_bets_board("2026-07-18", BBD.E.FIP_CONSTANT_DEFAULT)

    assert isinstance(meta, list)
    assert meta[0]["label"] == "Away @ Home (Game 1)"
    assert meta[0]["game_date"] == "2026-07-18"
    print("✓ load_mlb_best_bets_board returns the full meta list, not just its count")


def test_load_mlb_graded_picks_board_returns_rows_too():
    fake_row, fake_meta = _fake_row_and_meta()

    with patch.object(BBD.E, "build_slate", lambda date_str, fip: ([fake_row], fake_meta)), \
        patch.object(BBD.E, "get_bullpen_aggregate_stat", lambda *a, **k: None), \
        patch("statcast_data.load", lambda: ({}, None)), \
        patch("weather.get_game_weather", lambda *a, **k: None):
        plays, meta, rows, available_books = BBD.load_mlb_graded_picks_board("2026-07-18", BBD.E.FIP_CONSTANT_DEFAULT)

    assert len(plays) > 0
    assert len(meta) == 1
    assert len(rows) == 1
    assert rows[0]["Hitter"] == "Test Slugger"
    assert rows[0]["Opp HR/9"] == 1.8
    print("✓ load_mlb_graded_picks_board returns the raw hitter rows, needed for the one-sided banner")


def test_load_generic_best_bets_board_exists_on_module():
    # Regression guard for a real production bug: this function's own `def` line was silently
    # dropped during an edit, leaving its full body (docstring, build_slate call, everything)
    # as unreachable dead code trailing inside filter_by_split_situation, after its return
    # statement. The module still imported cleanly -- no syntax error -- so this shipped
    # undetected. Every call site (Best Bets, Graded Picks, Suggested Parlays, Speculative
    # Basket, Command Center) got an AttributeError at runtime for every non-MLB sport. On the
    # four pages wrapped in try/except, that AttributeError was silently swallowed and shown to
    # users as "No slate data available ... try a date when games are scheduled" -- a data
    # problem that never existed. Command Center had no try/except at all and just crashed.
    # This assertion alone would have caught it: an AttributeError, not a passing import.
    assert hasattr(BBD, "load_generic_best_bets_board"), (
        "load_generic_best_bets_board is missing from best_bets_data -- every non-MLB sport's "
        "Best Bets/Graded Picks/Suggested Parlays/Speculative Basket/Command Center page will "
        "silently show 'No slate data available' (or crash on Command Center) instead of plays."
    )
    sig = inspect.signature(BBD.load_generic_best_bets_board)
    assert list(sig.parameters.keys()) == ["sport_key", "date_str"]
    print("✓ load_generic_best_bets_board exists on best_bets_data with the expected signature")


def test_load_generic_best_bets_board_full_pipeline_runs():
    # Full pipeline test mirroring the MLB one above, for a generic (non-MLB) sport -- catches
    # the same class of drift even if the function existed but its body were broken.
    class _FakeEngine:
        @staticmethod
        def build_slate(date_str):
            return (["fake_row"], [{"label": "Away @ Home", "game_date": "2026-07-28"}])

    class _FakeProjections:
        @staticmethod
        def build_best_bets(rows, real_lines=None, offers=None, preferred_book=None):
            assert rows == ["fake_row"]
            return [{"Player": "Test Player", "Market": "Points", "Game": "Away @ Home"}]

    class _FakeSport:
        has_projections = True
        engine = _FakeEngine()
        projections = _FakeProjections()

    with patch.object(BBD.sports, "get", lambda sport_key: _FakeSport()), \
        patch.object(BBD, "get_odds_api_key", lambda: None):
        plays, meta, available_books = BBD.load_generic_best_bets_board("WNBA", "2026-07-28")

    assert len(plays) == 1
    assert plays[0]["Player"] == "Test Player"
    assert len(meta) == 1
    assert meta[0]["label"] == "Away @ Home"
    assert isinstance(available_books, list) and len(available_books) > 0
    print("✓ load_generic_best_bets_board runs build_slate -> build_best_bets end to end for a generic sport")


def test_load_generic_best_bets_board_fetches_real_lines_for_non_nfl_sports_too():
    # Regression guard for a real, live-reported bug: a real NCAAF Best Bets board showed every
    # single play using the exact hardcoded placeholder line (219.5/49.5/54.5/4.5, matching
    # ncaaf_projections._MARKET_SPEC's own defaults exactly) -- because the real-lines fetch was
    # gated to `sport_key == "NFL"` specifically, so it was never even ATTEMPTED for anything
    # else. Not a fetch failure; a fetch that never ran. This confirms the fix: the fetch now
    # runs for a non-NFL sport too, using that sport's OWN markets/odds_sport_key/preferred-book
    # session-state key, not NFL's.
    import odds_api as O

    class _FakeEngine:
        @staticmethod
        def build_slate(date_str):
            return (["fake_row"], [{"label": "Away @ Home"}])

    class _FakeProjections:
        @staticmethod
        def build_best_bets(rows, real_lines=None, offers=None, preferred_book=None):
            # The actual proof: real_lines must be the object our mocked fetch produced, not
            # None (the old, NFL-only-gated behavior for every other sport).
            assert real_lines == {"sentinel": "real-line-was-passed-through"}
            return []

    class _FakeSport:
        has_projections = True
        markets = ["player_points"]
        odds_sport_key = "basketball_wnba"
        engine = _FakeEngine()
        projections = _FakeProjections()

    calls = {}

    def fake_fetch_slate_props(date_str, api_key, markets, sport):
        calls["fetch_slate_props"] = (date_str, api_key, markets, sport)
        return (["fake_offer"], {})

    def fake_market_lines_for_slate(offers, preferred_book):
        calls["market_lines_for_slate"] = (offers, preferred_book)
        return {"sentinel": "real-line-was-passed-through"}

    with patch.object(BBD.sports, "get", lambda sport_key: _FakeSport()), \
        patch.object(BBD, "get_odds_api_key", lambda: "FAKE_KEY"), \
        patch.object(O, "fetch_slate_props", side_effect=fake_fetch_slate_props), \
        patch.object(O, "market_lines_for_slate", side_effect=fake_market_lines_for_slate), \
        patch.object(O, "books_in_offers", return_value=[]):
        BBD.load_generic_best_bets_board("WNBA", "2026-07-28")

    assert "fetch_slate_props" in calls, (
        "fetch_slate_props was never called for a non-NFL sport -- the NFL-only gate is still there"
    )
    assert calls["fetch_slate_props"] == ("2026-07-28", "FAKE_KEY", ["player_points"], "basketball_wnba")
    print("✓ load_generic_best_bets_board now fetches real sportsbook lines for a non-NFL sport, "
         "using that sport's own markets/odds_sport_key -- the exact fix for a real reported bug")


def test_load_generic_best_bets_board_stores_real_offers_for_quick_log_reuse():
    # Regression guard for the actual fix: Best Bets already fetches real offers internally for
    # its own board display -- this confirms those SAME offers get stored in a session-state
    # side-channel so quick_log's own real-price lookup can reuse them for free, with zero extra
    # Odds API calls, instead of always falling back to the model's own Fair odds.
    import odds_api as O

    class _FakeEngine:
        @staticmethod
        def build_slate(date_str):
            return ([], [])

    class _FakeProjections:
        @staticmethod
        def build_best_bets(rows, real_lines=None, offers=None, preferred_book=None):
            return []

    class _FakeSport:
        has_projections = True
        markets = ["batter_hits"]
        odds_sport_key = "baseball_mlb"
        engine = _FakeEngine()
        projections = _FakeProjections()

    fake_offers = [{"player": "Wade Meckler", "market": "batter_hits", "point": 0.5,
                    "over": {"draftkings": -260}, "under": {"draftkings": 210}}]
    fake_session_state = {}
    with patch.object(BBD.sports, "get", lambda sport_key: _FakeSport()), \
        patch.object(BBD, "get_odds_api_key", lambda: "FAKE_KEY"), \
        patch.object(BBD.st, "session_state", fake_session_state), \
        patch.object(O, "fetch_slate_props", return_value=(fake_offers, {})), \
        patch.object(O, "market_lines_for_slate", return_value={}), \
        patch.object(O, "books_in_offers", return_value=["draftkings"]):
        BBD.load_generic_best_bets_board("MLB", "2026-07-28")

    stored_offers = fake_session_state.get("_real_offers_MLB_2026-07-28")
    assert stored_offers == fake_offers
    print("✓ load_generic_best_bets_board stores the real fetched offers in a session-state "
         "side-channel for quick_log to reuse")


def test_load_generic_best_bets_board_offers_sidechannel_empty_when_fetch_not_attempted():
    class _FakeEngine:
        @staticmethod
        def build_slate(date_str):
            return ([], [])

    class _FakeProjections:
        @staticmethod
        def build_best_bets(rows, real_lines=None, offers=None, preferred_book=None):
            return []

    class _FakeSport:
        has_projections = True
        markets = ["batter_hits"]
        odds_sport_key = "baseball_mlb"
        engine = _FakeEngine()
        projections = _FakeProjections()

    fake_session_state = {}
    with patch.object(BBD.sports, "get", lambda sport_key: _FakeSport()), \
        patch.object(BBD, "get_odds_api_key", lambda: None), \
        patch.object(BBD.st, "session_state", fake_session_state):
        BBD.load_generic_best_bets_board("MLB", "2026-07-28")

    assert fake_session_state.get("_real_offers_MLB_2026-07-28") == []
    print("✓ the offers side-channel is an honest empty list, not missing, when no fetch was attempted")



    # The exact scenario a real user hit and couldn't tell apart from a broken fetch: the
    # real-lines fetch runs successfully (no exception, real API key) but the book/Odds API has
    # zero props posted for this sport/date yet -- common well before a season starts. The
    # diagnostic must say so explicitly (offers=0), not look identical to "fetch never ran".
    import odds_api as O

    class _FakeEngine:
        @staticmethod
        def build_slate(date_str):
            return ([], [])

    class _FakeProjections:
        @staticmethod
        def build_best_bets(rows, real_lines=None, offers=None, preferred_book=None):
            return []

    class _FakeSport:
        has_projections = True
        markets = ["player_pass_yds"]
        odds_sport_key = "americanfootball_ncaaf"
        engine = _FakeEngine()
        projections = _FakeProjections()

    fake_session_state = {}
    with patch.object(BBD.sports, "get", lambda sport_key: _FakeSport()), \
        patch.object(BBD, "get_odds_api_key", lambda: "FAKE_KEY"), \
        patch.object(BBD.st, "session_state", fake_session_state), \
        patch.object(O, "fetch_slate_props", return_value=([], {})), \
        patch.object(O, "market_lines_for_slate", return_value={}), \
        patch.object(O, "books_in_offers", return_value=[]):
        BBD.load_generic_best_bets_board("NCAAF", "2026-07-28")

    diag = fake_session_state.get("_real_lines_diag_NCAAF_2026-07-28")
    assert diag is not None
    assert diag["attempted"] is True
    assert diag["api_key_present"] is True
    assert diag["offers"] == 0
    assert diag["matched_lines"] == 0
    assert diag["error"] is None
    print("✓ the real-lines diagnostic correctly distinguishes 'fetch ran, found 0 real offers' "
         "from 'fetch never ran', which used to look identical from the outside")


def test_load_generic_best_bets_board_diagnostic_reports_not_attempted_without_api_key():
    class _FakeEngine:
        @staticmethod
        def build_slate(date_str):
            return ([], [])

    class _FakeProjections:
        @staticmethod
        def build_best_bets(rows, real_lines=None, offers=None, preferred_book=None):
            return []

    class _FakeSport:
        has_projections = True
        markets = ["player_pass_yds"]
        odds_sport_key = "americanfootball_ncaaf"
        engine = _FakeEngine()
        projections = _FakeProjections()

    fake_session_state = {}
    with patch.object(BBD.sports, "get", lambda sport_key: _FakeSport()), \
        patch.object(BBD, "get_odds_api_key", lambda: None), \
        patch.object(BBD.st, "session_state", fake_session_state):
        BBD.load_generic_best_bets_board("NCAAF", "2026-07-28")

    diag = fake_session_state.get("_real_lines_diag_NCAAF_2026-07-28")
    assert diag["attempted"] is False
    assert diag["api_key_present"] is False
    print("✓ the real-lines diagnostic correctly reports 'not attempted' when no API key is configured")


def test_load_generic_best_bets_board_returns_empty_for_outcome_based_sports():
    # UFC-style sports (has_projections=False) should return empty gracefully, not error --
    # this is the path that lets the calling pages show their own dedicated messaging instead.
    class _FakeOutcomeSport:
        has_projections = False

    with patch.object(BBD.sports, "get", lambda sport_key: _FakeOutcomeSport()):
        plays, meta, available_books = BBD.load_generic_best_bets_board("UFC", "2026-07-28")

    assert plays == []
    assert meta == []
    print("✓ load_generic_best_bets_board returns empty gracefully for outcome-based sports")


def test_load_generic_best_bets_board_real_modules_every_registered_sport():
    # Regression guard for a real production bug: load_generic_best_bets_board calls
    # sport.projections.build_best_bets(rows, real_lines=real_lines) the SAME way for every
    # sport routed through this pipeline, but WNBA's, NBA's, and NCAAMB's build_best_bets were
    # never updated to accept a real_lines keyword (only NFL's was, when real-lines support was
    # added for NFL). Every call for those three sports threw TypeError: build_best_bets() got
    # an unexpected keyword argument 'real_lines' -- masked by the caller's try/except into a
    # false "No slate data available" warning on Best Bets/Graded Picks/Suggested Parlays/
    # Speculative Basket, and an outright crash on Command Center (no try/except there).
    #
    # The earlier test above (test_load_generic_best_bets_board_full_pipeline_runs) uses a FAKE
    # projections object and would NOT have caught this -- a fake's build_best_bets accepts
    # whatever signature you give it. This test calls the REAL sports.REGISTRY and the REAL
    # projections module for every enabled, stat-based sport, with only build_slate patched out
    # (network calls), so a real signature mismatch fails loudly here instead of shipping.
    import sports

    for sport_key, sport in sports.REGISTRY.items():
        if not sport.enabled or not sport.has_projections or sport_key == "MLB":
            continue  # MLB routes through load_mlb_best_bets_board, a different function/signature
        with patch.object(sport.engine, "build_slate", lambda date_str: ([], [])):
            try:
                plays, meta, available_books = BBD.load_generic_best_bets_board(sport_key, "2026-07-28")
            except TypeError as e:
                raise AssertionError(
                    f"{sport_key}'s build_best_bets raised a TypeError -- its signature doesn't "
                    f"match what load_generic_best_bets_board calls it with: {e}"
                )
        assert plays == [] and meta == []
    print("✓ every enabled, stat-based sport's real build_best_bets accepts the real_lines keyword "
         "load_generic_best_bets_board always passes")


# ----------------------------------------------------------------- fetch_mlb_real_lines
def test_fetch_mlb_real_lines_returns_real_lines_offers_and_books():
    # fetch_mlb_real_lines itself must NEVER touch session_state -- a real, confirmed bug fix:
    # it used to write session_state directly, but being @st.cache_data-wrapped means that write
    # only reliably fires for whichever session triggered the real fetch. See
    # ensure_mlb_offers_session_state for the actual, session-safe fix.
    fake_offers = [{"player": "Wade Meckler", "market": "batter_total_bases", "point": 1.5,
                    "over": {"draftkings": -140}, "under": {"draftkings": 115}}]
    with patch.object(BBD.O, "fetch_slate_props", return_value=(fake_offers, {})), \
        patch.object(BBD.O, "market_lines_for_slate", return_value={("wade meckler", "batter_total_bases"): 1.5}), \
        patch.object(BBD.O, "books_in_offers", return_value=["draftkings"]):
        real_lines, real_offers, available_books = BBD.fetch_mlb_real_lines(
            "2026-07-28", "FAKE_KEY", preferred_book="draftkings")
    assert real_lines == {("wade meckler", "batter_total_bases"): 1.5}
    assert real_offers == fake_offers
    assert available_books == ["draftkings"]
    print("✓ fetch_mlb_real_lines returns real lines/offers/books, and touches no session_state "
         "of its own")


def test_fetch_mlb_real_lines_no_api_key_returns_honest_empty_state():
    real_lines, real_offers, available_books = BBD.fetch_mlb_real_lines("2026-07-28", None)
    assert real_lines is None   # never attempted, not an empty-but-real {}
    assert real_offers == []
    assert available_books == list(BBD.O.US_BOOKS.keys())
    print("✓ fetch_mlb_real_lines returns an honest None (not attempted) with no API key, not "
         "a fabricated empty result")


def test_fetch_mlb_real_lines_fetch_failure_degrades_gracefully():
    with patch.object(BBD.O, "fetch_slate_props", side_effect=Exception("network error")):
        real_lines, real_offers, available_books = BBD.fetch_mlb_real_lines("2026-07-28", "FAKE_KEY")
    assert real_lines is None
    assert real_offers == []
    print("✓ fetch_mlb_real_lines degrades to an honest None on a real fetch failure, never "
         "crashing the page")


# ----------------------------------------------------------------- ensure_mlb_offers_session_state
def test_ensure_mlb_offers_session_state_writes_the_real_side_channel():
    fake_offers = [{"player": "X", "market": "batter_total_bases", "point": 1.5,
                    "over": {"draftkings": -140}, "under": {"draftkings": 115}}]
    fake_session_state = {}
    with patch.object(BBD, "fetch_mlb_real_lines", return_value=(None, fake_offers, [])), \
        patch.object(BBD.st, "session_state", fake_session_state):
        BBD.ensure_mlb_offers_session_state("2026-07-28", "FAKE_KEY")
    assert fake_session_state.get("_real_offers_MLB_2026-07-28") == fake_offers
    print("✓ ensure_mlb_offers_session_state correctly writes the real-offers side-channel")


def test_ensure_mlb_offers_session_state_is_never_cache_decorated():
    # The actual regression guard for the real, confirmed cross-session bug: this function must
    # NEVER be wrapped in @st.cache_data, or its whole reason for existing (guaranteeing the
    # write fires for THIS session, every time, regardless of whether the underlying fetch was a
    # cache hit) breaks the exact same way fetch_mlb_real_lines' own internal write used to.
    import inspect
    # A cache-wrapped function's __wrapped__/cache-related attributes give this away; a plain
    # function does not carry Streamlit's cache-decorator markers.
    assert not hasattr(BBD.ensure_mlb_offers_session_state, "clear"), (
        "ensure_mlb_offers_session_state appears to be @st.cache_data-wrapped (has a .clear() "
        "cache-management method) -- this would silently reintroduce the exact cross-session "
        "bug this function exists to fix. It must remain a plain, uncached function."
    )
    print("✓ ensure_mlb_offers_session_state is confirmed NOT cache-decorated, preserving the "
         "guarantee that its session_state write fires for every real caller")


def test_ensure_mlb_offers_session_state_fixes_the_real_cross_session_bug():
    # Direct proof the actual bug is fixed: simulate TWO separate user sessions both calling
    # ensure_mlb_offers_session_state for the same date -- a real second/third caller hitting a
    # warm fetch_mlb_real_lines cache must STILL get their own session_state populated, not just
    # whichever session happened to trigger the real fetch first.
    fake_offers = [{"player": "X", "market": "batter_total_bases", "point": 1.5,
                    "over": {"draftkings": -140}, "under": {"draftkings": 115}}]

    session_a = {}
    session_b = {}
    # fetch_mlb_real_lines mocked to always return the "already cached" result (as it would for
    # a real cache hit) -- confirming ensure_mlb_offers_session_state's own write still fires
    # every time regardless, since it is never itself cached.
    with patch.object(BBD, "fetch_mlb_real_lines", return_value=(None, fake_offers, [])):
        with patch.object(BBD.st, "session_state", session_a):
            BBD.ensure_mlb_offers_session_state("2026-07-28", "FAKE_KEY")
        with patch.object(BBD.st, "session_state", session_b):
            BBD.ensure_mlb_offers_session_state("2026-07-28", "FAKE_KEY")
    assert session_a.get("_real_offers_MLB_2026-07-28") == fake_offers
    assert session_b.get("_real_offers_MLB_2026-07-28") == fake_offers
    print("✓ ensure_mlb_offers_session_state correctly populates a SECOND session's own "
         "session_state even when the underlying fetch was already cached from a first session "
         "-- the actual, direct fix for the real cross-session bug")


def test_build_mlb_board_uses_the_shared_fetch_mlb_real_lines_not_a_duplicate():
    # Regression guard for the actual structural fix: build_mlb_board itself now calls the
    # shared fetch_mlb_real_lines function rather than maintaining its own separate inline copy
    # of the same fetch logic -- confirms there's genuinely one source of truth, not two.
    called_with = {}
    def fake_fetch(date_str, odds_api_key, preferred_book=BBD.O.DEFAULT_BOOK):
        called_with["date_str"] = date_str
        called_with["odds_api_key"] = odds_api_key
        return None, [], list(BBD.O.US_BOOKS.keys())
    with patch.object(BBD, "fetch_mlb_real_lines", side_effect=fake_fetch):
        try:
            BBD.build_mlb_board("2026-07-28", 3.15, odds_api_key="FAKE_KEY")
        except Exception:
            pass   # this test only cares whether fetch_mlb_real_lines got called, not the full pipeline
    assert called_with.get("date_str") == "2026-07-28"
    assert called_with.get("odds_api_key") == "FAKE_KEY"
    print("✓ build_mlb_board calls the shared fetch_mlb_real_lines function, confirming it's no "
         "longer maintaining its own separate, potentially-drifting copy of the fetch logic")


# ----------------------------------------------------------------- attach_team_trend
def test_attach_team_trend_mlb_computes_once_per_team_not_once_per_play():
    calls = []

    def fake_form(team_id, before_date, games_back=15, **kw):
        calls.append((team_id, games_back))
        if team_id == 147:
            return {"runs_scored": 6.0 if games_back == 15 else 4.0}
        return {"runs_scored": 3.0 if games_back == 15 else 5.0}

    with patch.object(E, "get_team_recent_form", fake_form):
        rows = [{"Team": "New York Yankees", "_team_id": 147},
               {"Team": "New York Yankees", "_team_id": 147},
               {"Team": "Boston Red Sox", "_team_id": 111}]
        plays = [{"Team": "New York Yankees", "Player": "A"},
                {"Team": "New York Yankees", "Player": "B"},
                {"Team": "Boston Red Sox", "Player": "C"}]
        BBD.attach_team_trend("MLB", plays, rows, "2026-08-02")

    assert plays[0]["TeamTrend"] == "📈 Hot" and plays[1]["TeamTrend"] == "📈 Hot"
    assert plays[2]["TeamTrend"] == "📉 Cold"
    # 2 unique teams x 2 calls each (recent + season) = 4 -- NOT 3 plays x 2 = 6, confirming the
    # per-team cache actually works, not just "happens to look right" for this small example.
    assert len(calls) == 4, f"expected exactly 4 engine calls (cached per team), got {len(calls)}"
    print("✓ attach_team_trend computes each team's trend exactly once, reused across every "
         "play for that team, not refetched per play")


def test_attach_team_trend_fails_soft_on_fetch_error():
    def boom(team_id, before_date, games_back=15, **kw):
        raise ConnectionError("simulated failure")

    with patch.object(E, "get_team_recent_form", boom):
        rows = [{"Team": "New York Yankees", "_team_id": 147}]
        plays = [{"Team": "New York Yankees", "Player": "A"}]
        BBD.attach_team_trend("MLB", plays, rows, "2026-08-02")   # must not raise

    assert plays[0]["TeamTrend"] == "➡️ Steady"
    assert plays[0]["TeamTrendRatio"] is None
    print("✓ attach_team_trend fails soft (honest Steady/None) on a real fetch error, never "
         "crashes the whole board over one team's bad fetch")


def test_attach_team_trend_missing_team_id_falls_back_honest():
    # A play whose Team has no matching _team_id anywhere in rows -- must not crash, must not
    # fabricate a trend.
    rows = [{"Team": "Some Other Team", "_team_id": 999}]
    plays = [{"Team": "New York Yankees", "Player": "A"}]
    BBD.attach_team_trend("MLB", plays, rows, "2026-08-02")
    assert plays[0]["TeamTrend"] == "➡️ Steady"
    assert plays[0]["TeamTrendRatio"] is None
    print("✓ attach_team_trend handles a play with no matching team_id gracefully, no crash")


def test_attach_team_trend_nfl_uses_schedule_not_team_id():
    import nfl_engine as NE
    fake_schedule = [
        {"week": 1, "home_team": "KC", "away_team": "BUF", "home_score": 30, "away_score": 20},
        {"week": 2, "home_team": "DEN", "away_team": "KC", "home_score": 10, "away_score": 17},
    ]
    with patch.object(NE, "_infer_season", lambda date_str: 2026), \
         patch.object(NE, "get_schedule", lambda season: fake_schedule), \
         patch.object(NE, "_resolve_week", lambda schedule, date_str: 3):
        rows = [{"Team": "KC", "_team_id": "KC"}]
        plays = [{"Team": "KC", "Player": "Mahomes"}]
        BBD.attach_team_trend("NFL", plays, rows, "2026-09-22")
    # KC scored 30 then 17 -- both games count as "recent" (n=4, only 2 games exist), so
    # recent_avg == season_avg == 23.5 -> Steady, confirming the real NFL codepath actually ran
    # (not silently skipped) rather than asserting a specific Hot/Cold outcome.
    assert plays[0]["TeamTrend"] == "➡️ Steady"
    assert plays[0]["TeamTrendRatio"] == 1.0
    print("✓ attach_team_trend correctly dispatches to NFL's schedule-based calling convention "
         "(not the team_id lookup the other sports use)")


def test_attach_team_trend_unsupported_sport_leaves_honest_default():
    rows = [{"Team": "Some Team", "_team_id": 1}]
    plays = [{"Team": "Some Team", "Player": "A"}]
    BBD.attach_team_trend("UFC", plays, rows, "2026-08-02")
    assert plays[0]["TeamTrend"] == "➡️ Steady"
    assert plays[0]["TeamTrendRatio"] is None
    print("✓ attach_team_trend leaves the honest default for a sport with no team-trend source "
         "(UFC), never crashes on an unrecognized sport_key")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
