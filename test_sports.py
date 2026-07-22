"""Tests for sports.py — the sport registry and Stage 2 routing helpers (active sport lookup,
the require_live_engine guard that lets engine-backed pages degrade gracefully for sports that
aren't wired end-to-end yet) — plus the owner/public audience gate in streamlit_app.py."""

import re
from pathlib import Path

import sports as S

_HERE = Path(__file__).parent


def test_registry_has_all_seven_leagues():
    assert set(S.REGISTRY.keys()) == {"MLB", "NFL", "WNBA", "NBA", "NHL", "NCAAF", "NCAAMB"}
    print("✓ all 7 leagues registered")


def test_mlb_wnba_nba_ncaamb_nfl_enabled_today():
    live = {s.key for s in S.enabled_sports()}
    assert live == {"MLB", "WNBA", "NBA", "NCAAMB", "NFL"}, f"expected MLB+WNBA+NBA+NCAAMB+NFL live, got {live}"
    print("✓ MLB, WNBA, NBA, NCAAMB, and NFL are the enabled/live sports (NFL confirmed live 2026-07-17)")


def test_get_falls_back_to_default_for_unknown_key():
    assert S.get("XFL").key == S.DEFAULT_SPORT
    print("✓ unknown sport key falls back to the default (MLB)")


def test_active_defaults_to_mlb_outside_streamlit():
    # No st.session_state available here (no Streamlit runtime) -> active() must not crash,
    # and should fall back to the default sport.
    assert S.active_key() == "MLB"
    assert S.active().key == "MLB"
    print("✓ active()/active_key() degrade to MLB default without a Streamlit runtime")


def test_require_live_engine_true_for_mlb(monkeypatch):
    import streamlit as st
    st.session_state["sport"] = "MLB"
    assert S.require_live_engine("Edge Board") is True
    print("✓ require_live_engine passes for MLB (markets configured)")


def test_require_live_engine_true_for_wnba(monkeypatch):
    import streamlit as st
    st.session_state["sport"] = "WNBA"
    assert S.require_live_engine("Edge Board") is True
    st.session_state["sport"] = "MLB"   # reset for other tests
    print("✓ require_live_engine passes for WNBA now that Core 4 markets are wired")


def test_require_live_engine_false_for_unwired_sport(monkeypatch):
    import streamlit as st
    st.session_state["sport"] = "NHL"   # markets=[] (not wired) — NFL now has real markets, so
                                        # this test needs a genuinely-still-unwired sport instead
    assert S.require_live_engine("Edge Board") is False
    st.session_state["sport"] = "MLB"   # reset for other tests
    print("✓ require_live_engine blocks a sport with no markets configured yet, no crash")


def test_market_map_present_for_live_sports_only():
    for key in ("MLB", "WNBA", "NBA", "NCAAMB", "NFL"):
        assert S.REGISTRY[key].market_map, f"{key} must have a market_map (CLV capture depends on it)"
    for key in ("NHL", "NCAAF"):
        assert S.REGISTRY[key].market_map == {}, f"{key} should still be a placeholder"
    print("✓ MLB, WNBA, NBA, NCAAMB, and NFL have filled market_maps; the rest are honest placeholders")


def test_owner_only_pages_match_expected_titles():
    # Regression guard for the Discord/public split: Bet Log, Media Room, Podcast Studio, Edge
    # Board, Matchup Lab, Track Record, Data Health, Suggested Parlays, Speculative Basket, and
    # Graded Picks must stay in the owner-only gate, and the gate must resolve against real page
    # titles that exist in _META (a typo here would silently fail to hide a page from the public
    # build). Graded Picks moved to owner-only directly on request, specifically to guarantee no
    # public page could ever link to it as the subscriber-only split hardens.
    src = (_HERE / "streamlit_app.py").read_text()
    m = re.search(r'owner_only_titles = \{([^}]*)\}', src)
    assert m, "streamlit_app.py must define owner_only_titles"
    gated = {t.strip().strip('"') for t in m.group(1).split(",") if t.strip()}
    assert gated == {"Bet Log", "Media Room", "Podcast Studio", "Edge Board",
                     "Matchup Lab", "Track Record", "Data Health",
                     "Suggested Parlays", "Speculative Basket", "Graded Picks"}, gated
    all_titles = set(re.findall(r'\("([^"]+)",\s*"[^"]*",\s*"[^"]*"\)', src))
    assert gated <= all_titles, f"gated titles not found in _META: {gated - all_titles}"
    print("✓ owner-only gate targets exactly Bet Log / Media Room / Podcast Studio / Edge Board / "
          "Matchup Lab / Track Record / Data Health / Suggested Parlays / Speculative Basket / "
          "Graded Picks, by real title")


def test_public_audience_defaults_safe():
    # Missing/unset AUDIENCE secret must default to "owner" (fail toward showing the owner
    # everything on unconfigured/local runs), never silently default to "public".
    src = (_HERE / "streamlit_app.py").read_text()
    assert 'st.secrets.get("AUDIENCE", "owner")' in src
    print("✓ AUDIENCE defaults to 'owner' when unset (safe default for local/dev runs)")


def test_streamlit_app_guards_direct_run():
    # streamlit_app.py must only call run() under __main__, or importing it from the second
    # entrypoint (streamlit_app_discord.py) would execute the whole app twice.
    src = (_HERE / "streamlit_app.py").read_text()
    assert 'if __name__ == "__main__":\n    run()' in src, \
        "run() must be guarded by __main__, or the Discord entrypoint double-executes it"
    print("✓ streamlit_app.py's run() is guarded — safe to import from a second entrypoint")


def test_discord_entrypoint_has_no_duplicated_logic():
    # The whole point of streamlit_app_discord.py is to hold ZERO page-building logic (that would
    # be exactly the drift this two-file setup exists to avoid). It should just import and call
    # run() from streamlit_app.py.
    src = (_HERE / "streamlit_app_discord.py").read_text()
    assert "from streamlit_app import run" in src and "run()" in src
    for forbidden in ("st.navigation", "st.Page", "_META", "OWNER_ONLY", "MLB_ONLY"):
        assert forbidden not in src, f"logic leaked into the thin entrypoint: {forbidden}"
    print("✓ streamlit_app_discord.py stays a 2-line pass-through, no duplicated page logic")


def test_require_sport_blocks_wrong_sport_even_with_markets():
    # The whole point of require_sport: unlike require_live_engine, it must block WNBA even
    # though WNBA now has real markets configured — because the page itself hasn't been ported.
    import streamlit as st
    st.session_state["sport"] = "WNBA"
    assert S.require_sport("MLB", "Media Room") is False
    st.session_state["sport"] = "MLB"
    print("✓ require_sport blocks a page for WNBA even though WNBA passes require_live_engine")


def test_require_sport_allows_matching_sport():
    import streamlit as st
    st.session_state["sport"] = "MLB"
    assert S.require_sport("MLB", "Media Room") is True
    print("✓ require_sport allows the page when the active sport matches")


def test_require_sport_accepts_a_list_of_keys():
    import streamlit as st
    st.session_state["sport"] = "NBA"
    assert S.require_sport(["WNBA", "NBA"], "Hot Hand Engine") is True
    st.session_state["sport"] = "WNBA"
    assert S.require_sport(["WNBA", "NBA"], "Hot Hand Engine") is True
    st.session_state["sport"] = "MLB"
    assert S.require_sport(["WNBA", "NBA"], "Hot Hand Engine") is False
    st.session_state["sport"] = "MLB"
    print("✓ require_sport accepts a list of acceptable sport keys, not just a single one")


def test_sport_only_page_visibility_matches_expected_config():
    # Regression guard: Pitching Lab/Dinger Engine/Matchup Lab(MLB)/Bullpen Watch must stay
    # MLB-only, Hot Hand Engine/Matchup Lab(WNBA/NBA/NCAAMB) must stay basketball-only, and
    # Matchup Lab(NFL)/Anytime TD Engine must stay NFL-only. A future page renumbering could
    # silently break this if nothing locks in which lead numbers map to which sport(s).
    src = (_HERE / "streamlit_app.py").read_text()
    m = re.search(r"sport_only_leads = \{([^}]*)\}", src, re.DOTALL)
    assert m, "streamlit_app.py must define sport_only_leads"
    pairs = {}
    for key, vals in re.findall(r'"(\d+)":\s*\(([^)]*)\)', m.group(1)):
        pairs[key] = tuple(re.findall(r'"(\w+)"', vals))
    assert pairs == {"1": ("MLB",), "2": ("MLB",), "10": ("MLB",), "21": ("MLB",),
                     "11": ("WNBA", "NBA", "NCAAMB"), "12": ("WNBA", "NBA", "NCAAMB"),
                     "13": ("NFL",), "14": ("NFL",), "15": ("NFL",)}, pairs
    print("✓ sport_only_leads matches expected config (Pitching Lab/Dinger Engine/Matchup Lab(MLB)/"
          "Bullpen Watch -> MLB, Hot Hand Engine/Matchup Lab(WNBA/NBA/NCAAMB) -> WNBA+NBA+NCAAMB, "
          "Matchup Lab(NFL)/Anytime TD Engine/QB Lab -> NFL)")


def test_hot_hand_and_matchup_lab_loaders_key_their_cache_by_sport():
    # Regression guard for a real bug found live: selecting NBA on Matchup Lab showed a WNBA
    # player ("Aliyah Boston, Indiana Fever") because @st.cache_data's cache key only considers a
    # function's own arguments — a cached loader that reads the sport-specific E/P modules via a
    # module-level closure, without sport_key as an explicit argument, silently returns the OTHER
    # sport's cached result when only the sidebar dropdown (not date_str) changed. Every other
    # sport-dispatching page (Edge Board, Best Bets, Retrospective, Media Room, Podcast Studio)
    # already follows the sport_key-as-first-arg convention; this locks in that Hot Hand Engine
    # and Matchup Lab do too, so a future edit can't silently drop the parameter again.
    for path, loaders in (
        ("views/11_Hot_Hand_Engine.py", ["load_board", "load_injuries"]),
        ("views/12_Matchup_Lab.py", ["load_slate", "load_injuries", "load_matchup"]),
    ):
        src = (_HERE / path).read_text()
        for fn in loaders:
            m = re.search(rf"@st\.cache_data\([^)]*\)\s*\ndef {fn}\(([^)]*)\)", src)
            assert m, f"{path}: couldn't find cached def {fn}(...)"
            first_param = m.group(1).split(",")[0].strip()
            assert first_param.startswith("sport_key"), (
                f"{path}:{fn} must take sport_key as its first param to key the cache by sport, "
                f"got: {first_param!r}")
    print("✓ Hot Hand Engine's and Matchup Lab's sport-dependent loaders all key their cache by sport_key")


def test_game_dt_parses_iso_utc_to_eastern():
    dt = S.game_dt("2026-07-16T23:00:00Z")
    assert dt is not None
    assert dt.tzinfo is not None
    # 23:00 UTC on Jul 16 is 19:00 (7pm) ET the same day, during EDT (summer)
    assert dt.hour == 19


def test_game_dt_none_for_missing_or_malformed():
    assert S.game_dt(None) is None
    assert S.game_dt("") is None
    assert S.game_dt("not-a-date") is None


def test_slot_of_buckets_correctly():
    afternoon = S.game_dt("2026-07-16T19:00:00Z")   # 3pm ET (summer/EDT)
    evening = S.game_dt("2026-07-16T23:00:00Z")      # 7pm ET
    late = S.game_dt("2026-07-17T02:00:00Z")         # 10pm ET
    assert S.slot_of(afternoon) == "Afternoon"
    assert S.slot_of(evening) == "Evening"
    assert S.slot_of(late) == "Late"
    assert S.slot_of(None) == "TBD"
    print("✓ slot_of correctly buckets Afternoon/Evening/Late/TBD from a US/Eastern datetime")


def test_slot_order_covers_every_slot_of_output():
    # Every possible slot_of() output must have a sort position, or a future page's sorted()
    # call would silently mis-order (or crash without the .get(s, 9) fallback other pages use).
    possible_slots = {"Afternoon", "Evening", "Late", "TBD"}
    assert possible_slots <= set(S.SLOT_ORDER.keys())


def test_best_bets_and_matchup_lab_use_the_shared_time_slot_helpers():
    # Regression guard: these were duplicated in Best Bets originally, then Matchup Lab needed
    # the identical logic — extracted into sports.py specifically so a second/third copy never
    # has to exist (and never quietly drifts from the original). This checks the source actually
    # imports from sports rather than redefining its own copy.
    for path in ("views/5_#U2b50_Best_Bets.py", "views/12_Matchup_Lab.py"):
        src = (_HERE / path).read_text()
        assert "sports.game_dt" in src or "S.game_dt" in src, f"{path} should use the shared game_dt"
        assert re.search(r"^def game_dt", src, re.MULTILINE) is None, (
            f"{path} should not redefine its own game_dt — it exists in sports.py")
    print("✓ Best Bets and Matchup Lab both use the shared sports.py time-slot helpers, no local duplicates")


# ----------------------------------------------------------------- cross-sport shared contract
# THE regression guard for a real bug class found live: NFL launched with build_slate/build_best_
# bets/build_projection_index/curate_selections (what Edge Board and Best Bets need), but
# Retrospective, Podcast Studio, and Media Room ALSO call get_player_results and explain_miss —
# functions that exist on every OTHER live sport's engine/projections module, so nothing caught
# their absence until a real person hit the real crash, twice, in the same page. This test
# enumerates the full contract explicitly and checks every currently-live sport against it, so a
# future sport's launch (or a future shared page's new function call) gets caught here first.
_ENGINE_CONTRACT = ["build_slate", "get_player_results"]
_PROJECTIONS_CONTRACT = ["build_best_bets", "build_projection_index", "curate_selections", "explain_miss"]


def test_every_live_sport_implements_the_full_shared_page_contract():
    for sport in S.enabled_sports():
        if sport.key == "MLB":
            continue   # MLB uses its own dedicated *_mlb code paths in every shared page, never
                       # the generic contract these functions belong to — a different, deliberate
                       # design, not a gap (see e.g. views/6_..._Retrospective.py's load_retro_mlb
                       # vs load_retro_generic split).
        engine, proj = sport.engine, sport.projections
        missing_engine = [fn for fn in _ENGINE_CONTRACT if not callable(getattr(engine, fn, None))]
        missing_proj = [fn for fn in _PROJECTIONS_CONTRACT if not callable(getattr(proj, fn, None))]
        assert not missing_engine, f"{sport.key}'s engine is missing: {missing_engine}"
        assert not missing_proj, f"{sport.key}'s projections module is missing: {missing_proj}"
    print("✓ every live non-MLB sport implements the full engine/projections contract every shared page needs")


# ----------------------------------------------------------------- _check_trading_password
def test_check_trading_password_correct():
    assert S._check_trading_password("hunter2", "hunter2") is True


def test_check_trading_password_incorrect():
    assert S._check_trading_password("wrong", "hunter2") is False


def test_check_trading_password_fails_closed_when_no_secret_configured():
    # Regression guard for a real, deliberate design choice: an UNconfigured secret must never
    # silently grant access, regardless of what's entered -- including an empty string, which
    # could otherwise slip through a careless "not expected" check.
    assert S._check_trading_password("", None) is False
    assert S._check_trading_password("anything", None) is False
    assert S._check_trading_password("", "") is False
    print("\u2713 _check_trading_password fails closed (denies access) when no real password is configured")


def test_check_trading_password_coerces_secret_to_string():
    # st.secrets can return non-string types depending on how the secret was declared (e.g. a
    # bare number in secrets.toml parses as an int) -- comparison must not silently fail just
    # because the configured secret happens to be a different type than the typed-in string.
    assert S._check_trading_password("1234", 1234) is True


def test_bet_log_and_track_record_call_the_trading_gate():
    # Regression guard confirming the gate is actually WIRED IN, not just that the function
    # exists and works in isolation -- a real risk otherwise: sports.require_trading_access
    # could be perfectly correct and simply never called from either page, leaving Bet Log/
    # Track Record just as open as before with no error anywhere to reveal it.
    bet_log_src = (_HERE / "views" / "4_#L01f4d2_Bet_Log.py").read_text()
    track_record_src = (_HERE / "views" / "9_Track_Record.py").read_text()
    assert "sports.require_trading_access(" in bet_log_src
    assert "sports.require_trading_access(" in track_record_src
    print("\u2713 both Bet Log and Track Record actually call sports.require_trading_access, confirmed by reading the real source, not assumed")


def test_mlb_market_map_values_all_present_in_markets():
    # A real, meaningful consistency property: every display-market -> Odds API key mapping in
    # market_map must point at a key that's actually IN the fetched markets list -- otherwise a
    # display market could silently reference a key the platform never actually queries live
    # odds for, a real, silent bug (e.g. Bet Log showing "Batter Runs" as loggable while the
    # live-odds fetch never requests batter_runs_scored at all).
    mlb = S.get("MLB")
    assert set(mlb.market_map.values()) <= set(mlb.markets)
    print("\u2713 every MLB market_map value is a real key present in the fetched markets list")


def test_mlb_new_props_markets_present():
    # Regression guard for the real, confirmed Odds API market keys added for Runs/RBI/SB/ER --
    # confirmed directly against the-odds-api.com's own live documentation, not guessed.
    mlb = S.get("MLB")
    assert mlb.market_map["Batter Runs"] == "batter_runs_scored"
    assert mlb.market_map["Batter RBIs"] == "batter_rbis"
    assert mlb.market_map["Batter Stolen Bases"] == "batter_stolen_bases"
    assert mlb.market_map["Pitcher Earned Runs"] == "pitcher_earned_runs"
    for key in ("batter_runs_scored", "batter_rbis", "batter_stolen_bases", "pitcher_earned_runs"):
        assert key in mlb.markets
    print("\u2713 all four new MLB prop markets are correctly registered with their real, confirmed Odds API keys")


def test_mlb_second_wave_props_markets_present():
    # Same regression guard, second wave: Singles/Doubles/Triples/Walks/Hits Allowed, also
    # confirmed directly against the-odds-api.com's own live documentation, not guessed.
    mlb = S.get("MLB")
    assert mlb.market_map["Batter Singles"] == "batter_singles"
    assert mlb.market_map["Batter Doubles"] == "batter_doubles"
    assert mlb.market_map["Batter Triples"] == "batter_triples"
    assert mlb.market_map["Batter Walks"] == "batter_walks"
    assert mlb.market_map["Pitcher Hits Allowed"] == "pitcher_hits_allowed"
    for key in ("batter_singles", "batter_doubles", "batter_triples", "batter_walks",
               "pitcher_hits_allowed"):
        assert key in mlb.markets
    print("\u2713 all five second-wave MLB prop markets are correctly registered with their real, confirmed Odds API keys")


def test_mlb_hrr_market_present():
    mlb = S.get("MLB")
    assert mlb.market_map["Batter Hits+Runs+RBIs"] == "batter_hits_runs_rbis"
    assert "batter_hits_runs_rbis" in mlb.markets
    print("\u2713 Batter Hits+Runs+RBIs is correctly registered with its real, confirmed Odds API key")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(None); passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
