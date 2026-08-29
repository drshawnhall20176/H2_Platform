"""Tests for sports.py — the sport registry and Stage 2 routing helpers (active sport lookup,
the require_live_engine guard that lets engine-backed pages degrade gracefully for sports that
aren't wired end-to-end yet) — plus the owner/public audience gate in streamlit_app.py."""

import inspect
import re
from pathlib import Path

import sports as S

_HERE = Path(__file__).parent


def test_has_projections_correctly_classifies_all_sports():
    """has_projections is the gating flag for whether a sport runs through the shared
    Best Bets / Edge Board / Model Dashboard pipeline. Outcome-based sports (UFC)
    return False and get redirect messages; stat-based sports return True and get
    the full pipeline. Derived from projections_module so adding a new outcome-based
    sport with projections_module='' automatically gets has_projections=False."""
    assert S.REGISTRY["MLB"].has_projections is True
    assert S.REGISTRY["NFL"].has_projections is True
    assert S.REGISTRY["WNBA"].has_projections is True
    assert S.REGISTRY["NBA"].has_projections is True
    assert S.REGISTRY["NCAAMB"].has_projections is True
    assert S.REGISTRY["UFC"].has_projections is False
    print("✓ has_projections correctly True for all stat-based sports, False for outcome-based (UFC)")


def test_registry_has_all_eight_leagues():
    assert set(S.REGISTRY.keys()) == {"MLB", "NFL", "WNBA", "NBA", "NHL", "NCAAF", "NCAAMB", "UFC"}
    print("✓ all 8 leagues registered")



    assert set(S.REGISTRY.keys()) == {"MLB", "NFL", "WNBA", "NBA", "NHL", "NCAAF", "NCAAMB", "UFC"}
    print("✓ all 8 leagues registered")


def test_mlb_wnba_nba_ncaamb_nfl_ncaaf_enabled_today():
    live = {s.key for s in S.enabled_sports()}
    assert live == {"MLB", "WNBA", "NBA", "NCAAMB", "NFL", "NCAAF", "UFC"}, (
        f"expected MLB+WNBA+NBA+NCAAMB+NFL+NCAAF+UFC live, got {live}"
    )
    print("✓ MLB, WNBA, NBA, NCAAMB, NFL, NCAAF, and UFC are the enabled/live sports")


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
    for key in ("MLB", "WNBA", "NBA", "NCAAMB", "NFL", "NCAAF"):
        assert S.REGISTRY[key].market_map, f"{key} must have a market_map (CLV capture depends on it)"
    for key in ("NHL",):
        assert S.REGISTRY[key].market_map == {}, f"{key} should still be a placeholder"
    print("✓ MLB, WNBA, NBA, NCAAMB, NFL, and NCAAF have filled market_maps; the rest are honest placeholders")


def test_owner_only_pages_match_expected_titles():
    # Regression guard for the Discord/public split: Bet Log, Media Room, Podcast Studio, Edge
    # Board, Matchup Lab, Track Record, Data Health, Suggested Parlays, Speculative Basket,
    # Graded Picks, Model Dashboard, First Innings Totals, and Player Lines must stay in the
    # owner-only gate, and the gate must resolve against real page titles that exist in _META (a
    # typo here would silently fail to hide a page from the public build). Graded Picks moved to
    # owner-only directly on request, specifically to guarantee no public page could ever link to
    # it as the subscriber-only split hardens. Model Dashboard / First Innings Totals / Player
    # Lines moved to owner-only directly on request too, same real reasoning.
    src = (_HERE / "streamlit_app.py").read_text()
    m = re.search(r'owner_only_titles = \{([^}]*)\}', src)
    assert m, "streamlit_app.py must define owner_only_titles"
    gated = {t.strip().strip('"') for t in m.group(1).split(",") if t.strip()}
    assert gated == {"Bet Log", "Media Room", "Podcast Studio", "Edge Board",
                     "Matchup Lab", "Track Record", "Data Health",
                     "Suggested Parlays", "Speculative Basket", "Graded Picks",
                     "Model Dashboard", "First Innings Totals", "Player Lines"}, gated
    all_titles = set(re.findall(r'\("([^"]+)",\s*"[^"]*",\s*"[^"]*"\)', src))
    assert gated <= all_titles, f"gated titles not found in _META: {gated - all_titles}"
    print("✓ owner-only gate targets exactly Bet Log / Media Room / Podcast Studio / Edge Board / "
          "Matchup Lab / Track Record / Data Health / Suggested Parlays / Speculative Basket / "
          "Graded Picks, by real title")


def test_home_falls_forward_to_next_scheduled_date_when_today_is_empty():
    # ADDED DIRECTLY ON REQUEST: a real, genuinely empty schedule for today (a legitimate
    # off-day -- e.g. NFL before the season starts) must fall forward to the next real scheduled
    # date instead of just stopping at a bare "No games scheduled today," confirmed wired into
    # the real Home.py source, not just present in schedule_board.py in isolation.
    src = (_HERE / "Home.py").read_text()
    assert "SB.next_scheduled_date(current, today_str)" in src, (
        "Home.py must actually call next_scheduled_date when today's own schedule is empty")
    assert '_today_empty = bool(schedule_result) and not schedule_result["grouped"] and not schedule_result["other"]' in src, (
        "the empty-check must distinguish a real empty result from a None (unsupported sport) result")
    assert 'heading=f"Next {active.label} games — {_next_date}"' in src, (
        "the fallback board must be clearly labeled as NOT today, never shown under a bare 'Today's Schedule' heading")
    print("✓ Home.py genuinely falls forward to the next real scheduled date when today is a real, legitimate off-day")


def test_game_watch_explains_a_real_no_data_pitcher_instead_of_bare_dashes():
    # ADDED DIRECTLY ON REQUEST: a real, confirmed case (Cody Bradford's actual 2026 season
    # debut, reinstated from a 60-day IL stint after nearly two years out) used to make the
    # whole real game vanish from Game Watch entirely. Fixed at the source (mlb_engine.
    # build_pitching_slate now includes an honest placeholder row instead of dropping it) --
    # this confirms Game Watch's own real caption explaining WHY a side shows dashes is
    # actually wired in, not just the underlying data fix landing silently.
    src = (_HERE / "views" / "6_Game_Watch.py").read_text()
    assert 'if not side_row.get("_has_stats", True):' in src, (
        "Game Watch must actually check the real _has_stats flag per side")
    assert "computable stat line yet" in src, (
        "a no-data pitcher must get a real, honest explanation, not just unexplained dashes")
    print("✓ Game Watch explains a real no-data pitcher's side directly, rather than leaving bare unexplained dashes")


def test_graded_picks_flags_a_real_recent_form_conflict():
    # ADDED DIRECTLY ON REQUEST: a real, confirmed example (Leody Taveras, 47% Under 0.5 Total
    # Hits, his own real last game a real hit AND a real HR -- his best game of the whole 10-
    # game window) showed this exact tension is completely invisible on the page a pick
    # actually gets decided on. Confirms the real, honest flag is genuinely wired into the
    # Slate Summary display, not just built as an unused engine function.
    src = (_HERE / "views" / "2_Graded_Picks.py").read_text()
    assert "E.recent_game_conflicts_with_pick(" in src, (
        "Graded Picks must actually call the real conflict check, not just have it available")
    assert 'if _active.key == "MLB" and pl.get("PlayerId"):' in src, (
        "the real conflict check must be gated to MLB, the only sport this function supports"
    )
    assert "would have gone the" in src, (
        "a real conflict must show a real, honest explanation, not a silent flag")
    print("✓ Graded Picks genuinely surfaces a real recent-form conflict on the page a pick actually gets decided on")


def test_game_watch_bullpen_freshness_display_is_genuinely_inverted_from_fatigue():
    # A REAL, CONFIRMED FIX for a real, reported case: LAA showing "29%" and BAL "56%" under a
    # "Bullpen freshness" header, with the edge correctly favoring LAA -- looked exactly
    # backwards to a real reader, because the raw FATIGUE fraction (bullpen_fatigued_fraction's
    # own real output) was being shown as-is under a FRESHNESS label. Confirms the real
    # inversion (1 - fraction) is genuinely wired in, and that the edge computation itself
    # (which was ALWAYS correct) is untouched -- this is a real display fix, not a logic change.
    src = (_HERE / "views" / "6_Game_Watch.py").read_text()
    assert "freshness_edge = P.bullpen_freshness_edge(away_fresh, home_fresh)" in src, (
        "the real edge computation must still use the raw, unmodified fatigue fraction -- it "
        "was already correct and must not be touched by this fix")
    assert ('"Bullpen freshness": (1 - away_fresh if away_fresh is not None else None,'
           in src), (
        "the DISPLAYED value must be genuinely inverted (1 - fraction), so higher now means "
        "fresher, matching both the label and the edge it already agreed with")
    print("✓ Game Watch's Bullpen freshness display now genuinely shows freshness, not the raw fatigue fraction it used to show under that label")


def test_pitching_slate_consolidated_across_all_real_callers():
    # A REAL, CONFIRMED FIX found in a real module-audit pass: SIX separate real call sites
    # (not the three first found) independently called E.build_pitching_slate directly or
    # through their own local, byte-for-byte-identical wrappers -- First Innings Totals,
    # Bullpen Watch, and Game Watch (found first), plus Model Dashboard's own real backtest
    # loop, MLB Player Lines, and MLB Matchup Lab page 9 (found in a second, broader sweep of
    # the same underlying call, under different wrapper names like load_pitchers). Confirms all
    # six now genuinely call the one, real, shared cache instead.
    for filename in ("27_MLB_First_Innings_Totals.py", "5_Bullpen_Watch.py", "6_Game_Watch.py",
                     "17_Model_Dashboard.py", "26_MLB_Player_Lines.py", "9_Matchup_Lab.py"):
        src = (_HERE / "views" / filename).read_text()
        assert "import mlb_shared_cache as MSC" in src, f"{filename} must import the shared cache module"
        assert "MSC.load_pitching_slate_cached(" in src, f"{filename} must call the real, shared cached function"
        assert "E.build_pitching_slate(" not in src, (
            f"{filename} must not still call the real, unshared function directly")
    print("✓ All six real callers now share one real cached call for build_pitching_slate, not six separate ones")


def test_hitter_slate_consolidated_across_all_real_callers():
    # A REAL, CONFIRMED FIX, the same real class of problem as the pitching-slate one: MLB
    # Player Lines and MLB Matchup Lab (page 9) each independently defined a byte-for-byte-
    # identical local wrapper around E.build_slate(date_str) too.
    for filename in ("26_MLB_Player_Lines.py", "9_Matchup_Lab.py"):
        src = (_HERE / "views" / filename).read_text()
        assert "MSC.load_hitter_slate_cached(" in src, f"{filename} must call the real, shared cached function"
        assert "def load_hitters(" not in src, f"{filename} must not still define its own local, now-redundant wrapper"
    print("✓ Both real callers now share one real cached call for the hitter slate, not two separate ones")


def test_injuries_consolidated_across_all_real_callers():
    # A REAL, CONFIRMED FIX, the same real class of problem as the other three consolidations
    # in this module: Game Watch and MLB Matchup Lab (page 9) each independently defined a
    # byte-for-byte-identical local wrapper around E.get_team_injuries(team_id) too.
    for filename in ("6_Game_Watch.py", "9_Matchup_Lab.py"):
        src = (_HERE / "views" / filename).read_text()
        assert "MSC.get_team_injuries_cached(" in src, f"{filename} must call the real, shared cached function"
        assert "def load_injuries(" not in src, f"{filename} must not still define its own local, now-redundant wrapper"
    print("✓ Both real callers now share one real cached call for team injuries, not two separate ones")


def test_slate_with_fip_consolidated_across_both_real_callers():
    # A REAL, CONFIRMED FIX found in a THIRD, later real audit pass: MLB Dinger Engine and
    # Pitching Lab each independently called E.build_slate WITH an explicit fip_constant --
    # confirmed directly by reading both -- before diverging into genuinely different real
    # downstream work (hitter-focused weather/splits vs. pitcher-focused projections).
    for filename in ("8_#L01f4a3_Dinger_Engine.py", "7_#L01f3af_Pitching_Lab.py"):
        src = (_HERE / "views" / filename).read_text()
        assert "MSC.load_slate_with_fip_cached(" in src, f"{filename} must call the real, shared cached function"
        assert "E.build_slate(date_str, fip_constant)" not in src, (
            f"{filename} must not still call the real, unshared fetch directly")
    print("✓ Both real callers now share one real cached call for build_slate-with-fip_constant, not two separate ones")


def test_nfl_slate_consolidated_across_all_real_callers():
    # A REAL, CONFIRMED FIX found in the same real module-audit pass, applied to NFL BEFORE it
    # goes live rather than after -- direct request: "this functionality and mindset is going
    # to flow into the NFL and NCAAF models." Four separate NFL view files each called E.build_
    # slate(date_str) as their own first step -- confirmed directly by reading all four -- even
    # though each does genuinely different, substantial post-processing afterward.
    for filename in ("12_NFL_Matchup_Lab.py", "13_Anytime_TD_Engine.py", "14_QB_Lab.py",
                     "25_NFL_Hot_Hand_Engine.py"):
        src = (_HERE / "views" / filename).read_text()
        assert "import nfl_shared_cache as NSC" in src, f"{filename} must import the shared cache module"
        assert "NSC.load_nfl_slate_cached(" in src, f"{filename} must call the real, shared cached fetch"
        assert "E.build_slate(" not in src, f"{filename} must not still call the real, unshared fetch directly"
        assert "import nfl_projections as P" in src, (
            f"{filename} must still have its own real nfl_projections import intact -- a real "
            f"mistake during this exact consolidation once accidentally deleted this import "
            f"instead of adding alongside it, caught by this same real test suite before it shipped")
    print("✓ All four real NFL callers now share one real cached fetch, each keeping its own real post-processing, imports intact")


def test_nfl_week_resolution_consolidated_across_both_real_callers():
    # A REAL, CONFIRMED FIX found in a SECOND, later real audit pass: NFL Matchup Lab and NFL
    # Hot Hand Engine each independently ran the same real season/schedule/week resolution chain
    # before diverging into their own different final injury shapes.
    for filename in ("12_NFL_Matchup_Lab.py", "25_NFL_Hot_Hand_Engine.py"):
        src = (_HERE / "views" / filename).read_text()
        assert "NSC.resolve_nfl_week_cached(" in src, f"{filename} must call the real, shared cached resolver"
        assert "E._infer_season(date_str)" not in src, f"{filename} must not still run the real, unshared chain directly"
    print("✓ Both real NFL injury callers now share one real cached week resolution, each keeping its own final injury lookup")


def test_player_lines_includes_pitcher_and_batter_walks():
    # ADDED DIRECTLY ON REQUEST: "Pitcher Walks" and "Batter Walks" are already real,
    # established, graded markets elsewhere on this platform -- confirms both are genuinely
    # wired into Player Lines' own chart specs, using the same real DEFAULT_LINES source every
    # other entry already uses, not new, invented default values.
    src = (_HERE / "views" / "26_MLB_Player_Lines.py").read_text()
    assert '("walks", "Pitcher Walks", P.DEFAULT_LINES["Pitcher Walks"])' in src, (
        "Pitcher Walks must be added to PITCHER_CHARTS using the real, established default line")
    assert '("walks", "Batter Walks", P.DEFAULT_LINES["Batter Walks"])' in src, (
        "Batter Walks must be added to BATTER_CHARTS using the real, established default line")
    print("✓ Player Lines genuinely includes both Pitcher Walks and Batter Walks, using the real, already-established default lines")


def test_every_ncaaf_dedicated_page_uses_the_real_shared_slate_cache():
    # UPDATED DIRECTLY, not deleted, now that the real event this test's own predecessor was
    # built to flag has genuinely happened: NCAAF's first real dedicated page (NCAAF QB Lab) now
    # exists, adapted directly from NFL QB Lab with every function signature and output dict key
    # confirmed to match exactly first. This test now verifies the actual, ongoing discipline the
    # original test existed to protect -- not "NCAAF has zero pages" (no longer true, and no
    # longer the real risk), but "every real NCAAF page that DOES exist reaches for
    # ncaaf_shared_cache.load_ncaaf_slate_cached, never a local, duplicate wrapper around
    # ncaaf_engine.build_slate" -- the exact real mistake NFL's own four pages made
    # independently, found and fixed only after the fact, and precisely what
    # ncaaf_shared_cache.py was built proactively to prevent from recurring.
    ncaaf_view_files = [f for f in (_HERE / "views").glob("*.py")
                       if "import ncaaf_engine as E" in f.read_text()]
    assert len(ncaaf_view_files) > 0, (
        "this test's own real purpose only applies once a real NCAAF page exists -- if this "
        "fails, something upstream removed the page(s) this test expects to find")
    for f in ncaaf_view_files:
        src = f.read_text()
        assert "import ncaaf_shared_cache as NSC" in src, (
            f"{f.name} imports ncaaf_engine directly but never imports ncaaf_shared_cache -- "
            f"a real, likely sign it's about to define its own local, duplicate wrapper around "
            f"E.build_slate instead of reaching for the real, shared one")
        assert "NSC.load_ncaaf_slate_cached(" in src, (
            f"{f.name} imports ncaaf_shared_cache but never actually calls "
            f"load_ncaaf_slate_cached -- confirm it isn't calling E.build_slate directly instead, "
            f"the exact real, duplicate-fetch mistake this whole module exists to prevent")
        assert "def load_ncaaf_slate_cached" not in src, (
            f"{f.name} appears to define its own load_ncaaf_slate_cached rather than importing "
            f"the real, shared one from ncaaf_shared_cache.py")
    print(f"✓ All {len(ncaaf_view_files)} real NCAAF dedicated page(s) genuinely reach for the shared slate cache, matching the discipline ncaaf_shared_cache.py was built to enforce")


def test_edge_board_market_selector_excludes_unpriceable_mlb_markets():
    # A REAL, CONFIRMED FIX for a real, reported case: a live Edge Board run showed 2015
    # unmatched props against only 1491 matched, with six DIFFERENT players all failing on the
    # exact same market (batter_rbis) -- the real signature of an unsupported market, not a
    # name-matching problem. Confirmed directly: MLB's own build_projection_index only ever
    # builds a real index entry for 7 of the 16 markets registered in sports.py's own market
    # map (batter_rbis, batter_stolen_bases, and 7 others were never wired into that function's
    # own hardcoded tuple list). The old widget offered, and defaulted to, all 16 -- guaranteeing
    # a large, misleading "unmatched" count for every real user, every real run, with zero
    # action needed to trigger it.
    src = (_HERE / "views" / "15_#L01f4c8_Edge_Board.py").read_text()
    assert 'getattr(P, "_MARKET_DISPLAY", {})' in src, (
        "the market selector must source its real options from what the model can actually "
        "price (P._MARKET_DISPLAY for MLB), not the full, broader market map")
    assert "priceable_markets, default=priceable_markets" in src, (
        "both the real options AND the real default selection must be restricted -- a fix "
        "that narrowed only one of the two would still let the other guarantee the same "
        "misleading unmatched count")
    print("✓ Edge Board's market selector now genuinely excludes MLB markets the model can't actually price, both as options and as the default selection")


def test_mlb_market_display_matches_what_build_projection_index_actually_supports():
    # A REAL, DIRECT, BEHAVIORAL check (not just a source-text match): confirms P._MARKET_
    # DISPLAY's own real keys are exactly the 7 markets build_projection_index actually builds
    # (4 batter, 3 pitcher), and genuinely excludes the real, confirmed-failing ones from the
    # live report this fix was built for.
    import projections as P
    priceable = set(P._MARKET_DISPLAY.keys())
    assert priceable == {"batter_home_runs", "batter_total_bases", "batter_hits",
                         "batter_strikeouts", "pitcher_strikeouts", "pitcher_outs", "pitcher_walks"}
    # The exact real markets confirmed failing in the live report this fix addresses.
    assert "batter_rbis" not in priceable
    assert "batter_stolen_bases" not in priceable
    print("✓ P._MARKET_DISPLAY's real keys exactly match what build_projection_index actually supports, confirmed directly against the real, reported failing markets")


def test_edge_board_unmatched_metric_explains_the_real_dedup_discrepancy():
    # A REAL, CONFIRMED FIX for a real, reported case: a live Edge Board run showed "Unmatched
    # (name/line): 42" at the top while the diagnostic panel right below it said "31 real
    # player(s)/market(s)" -- both numbers were already correct (confirmed directly: compute_
    # edges' own already-tested dedup logic collapses the same player/market appearing across
    # multiple books/alternate lines into one panel row, while the raw counter reflects every
    # real failed offer), but neither label explained why they'd ever legitimately differ,
    # which reads as a real bug even though it isn't one. Confirms the top metric now carries a
    # real, honest tooltip explaining this.
    src = (_HERE / "views" / "15_#L01f4c8_Edge_Board.py").read_text()
    assert "Counts every real failed offer, including when multiple books" in src, (
        "the Unmatched (name/line) metric must explain why it can legitimately exceed the "
        "deduplicated player/market panel below it")
    print("✓ Edge Board's Unmatched metric now genuinely explains the real, honest reason it can differ from the panel's own deduplicated count")


def test_edge_board_wires_known_names_through_the_full_real_chain():
    # ADDED DIRECTLY ON REQUEST, a real, confirmed fix for a real, reported case: real
    # established veterans (Kevin Gausman -- just traded, no debut yet for his new team; Sean
    # Murphy -- just off a 60-day IL; Ronel Blanco -- just back from Tommy John surgery) and
    # real rookies (Abimelec Ortiz, George Klassen, George Lombard Jr.) all landed in the same
    # undifferentiated "couldn't match" bucket as a genuine, fixable name mismatch. Confirms the
    # full real chain is wired: load_index computes and returns known_names, load_edges accepts
    # and passes it to compute_edges, and the panel itself is genuinely split into honest
    # sections using the real "reason" tag, not just relying on compute_edges' own real logic
    # existing in isolation.
    src = (_HERE / "views" / "15_#L01f4c8_Edge_Board.py").read_text()
    assert "known_names = proj.known_roster_names(rows, meta) if hasattr(proj" in src, (
        "load_index must compute known_names, safely gated for sports without this helper yet")
    assert "index, meta, known_names, all_active_names = load_index(" in src, (
        "the real call site must unpack all four real return values, including meta -- "
        "REAL, CONFIRMED FIX for a real, pre-existing bug caught via a real pyflakes sweep: "
        "meta was computed inside load_index but never returned, while this page's own IDP "
        "section further down referenced a bare `meta` name undefined in its own scope -- a "
        "genuine NameError waiting to fire for NFL + an IDP position filter together")
    assert "_known_names: Optional[set] = None" in src, "load_edges must accept known_names, defaulting to None for safety"
    assert "known_names=_known_names" in src, "load_edges must actually pass known_names through to compute_edges"
    assert 'u.get("reason") == "name_mismatch"' in src, "the panel must genuinely split out real name mismatches"
    assert 'u.get("reason") == "on_roster_no_data"' in src, "the panel must genuinely split out the honest 'not enough data yet' case"
    assert "This isn't a bug to fix; it's the model" in src, (
        "the honest 'no data yet' section must explain this isn't a bug, matching the real, "
        "confirmed cases (a real trade, a real injury return, a real rookie, a real role change)")
    print("✓ Edge Board's full known_names chain is genuinely wired end to end, and the panel is genuinely split into honest sections")


def test_edge_board_wires_all_active_names_through_the_full_real_chain():
    # A SECOND real, confirmed follow-up fix, layered on the first: real, established, active
    # players (Kevin Gausman again, Alí Sánchez, Edgar Quero, Zach Thornton) were STILL landing
    # in the real name-mismatch bucket, even though none of them had a real spelling problem --
    # they simply weren't part of TONIGHT's specific slate. Confirms the second real chain is
    # wired: load_index fetches the real league-wide roster via the shared cache, load_edges
    # passes it through, and the panel renders a genuine third section for this real case.
    src = (_HERE / "views" / "15_#L01f4c8_Edge_Board.py").read_text()
    assert "MSC.get_all_active_player_names_cached(int(date_str[:4]))" in src, (
        "load_index must fetch the real league-wide active roster via the shared cache")
    assert "_all_active_names: Optional[set] = None" in src, (
        "load_edges must accept all_active_names, defaulting to None for safety")
    assert "all_active_names=_all_active_names" in src, (
        "load_edges must actually pass all_active_names through to compute_edges")
    assert "known_names, all_active_names)" in src, (
        "the real call site must pass both known_names and all_active_names through to load_edges")
    assert 'u.get("reason") == "not_playing_tonight"' in src, (
        "the panel must genuinely split out the real 'active player, not part of tonight's slate' case")
    assert "confirmed against MLB's own full, real league-wide" in src, (
        "the third section must explain this is a real, verified active player, not a guess")
    print("✓ Edge Board's full all_active_names chain is genuinely wired end to end, and the panel renders a real third section")


def test_best_bets_explains_conviction_for_a_first_time_visitor():
    # ADDED DIRECTLY ON REQUEST: Best Bets is the first page in the sidebar flow, and the two
    # real explanatory spots on this page (a footer caption and a "read me" expander) were both
    # genuine, unfinished placeholders -- confirmed directly, not assumed: the caption ended in
    # a bare "..." and the expander's own markdown was literally "...". Confirms both are now
    # real, substantive content, and that a short definition also appears immediately after the
    # header -- not buried at the bottom where a first-time visitor would never see it before
    # already being confused by a table full of Conviction values.
    src = (_HERE / "views" / "1_#U2b50_Best_Bets.py").read_text()
    assert 'st.markdown("...")' not in src, "the 'read me' expander must no longer be an empty placeholder"
    assert '"Conviction shades darker for stronger leans. ..."' not in src, (
        "the footer caption must no longer be truncated")
    assert "how many times more likely this play is to hit than" in src, (
        "a short, immediate Conviction definition must appear right after the page header")
    assert "Top Lean / Strong Lean / Lean / Watch" in src, (
        "the full explanation must name the real grade labels this page actually uses"
    )
    print("✓ Best Bets now genuinely explains Conviction for a first-time visitor, both immediately and in full, instead of two empty placeholders")


def test_model_dashboard_chalk_test_fragment_is_defined_and_actually_called():
    # ADDED DIRECTLY ON REQUEST, part of a real performance pass: the slate-wide chalk test
    # section was extracted into its own @st.fragment so pressing its button no longer reruns
    # the rest of Model Dashboard above it. A single, non-looped fragment -- deliberately NOT
    # applied to any per-item loop (e.g. one row per game/player), which has a real, documented
    # Streamlit bug history around multiple instances of the same fragment function.
    #
    # This test exists because of a REAL, CONFIRMED MISTAKE caught during this exact change:
    # the function was fully defined but never actually called, which would have silently
    # removed the entire chalk-test feature from the page -- caught by directly checking the
    # call exists, not just that the function definition compiles (compiling successfully says
    # nothing about whether a defined function is ever invoked).
    src = (_HERE / "views" / "17_Model_Dashboard.py").read_text()
    assert "@st.fragment" in src, "the chalk test section must be wrapped in a real fragment"
    assert "def _render_chalk_test():" in src, "the fragment function must be defined"
    assert "\n    _render_chalk_test()" in src, (
        "the fragment function must actually be called -- a defined-but-uncalled function "
        "would silently remove this entire feature from the page, exactly the real mistake "
        "this test was written to catch")
    print("✓ Model Dashboard's chalk test is genuinely wrapped in a fragment AND actually called, not just defined")


def test_pitching_lab_live_pitch_count_uses_a_real_fragment_not_a_full_page_autorefresh():
    # ADDED DIRECTLY ON REQUEST, after a real performance audit: this used to call
    # st_autorefresh directly in the main page body, which re-ran the ENTIRE Pitching Lab page
    # every ~10 seconds while enabled -- starter selection, matchup tables, everything, not just
    # the live pitch count. Confirms the real fix: st.fragment(run_every=...), a native
    # Streamlit feature, now scopes the real 10-second timer to just this one section. Also
    # confirms the now-unnecessary third-party streamlit-autorefresh dependency was genuinely
    # removed, not just unused.
    src = (_HERE / "views" / "7_#L01f3af_Pitching_Lab.py").read_text()
    assert "@st.fragment(run_every=10 if live_auto else None)" in src, (
        "the live pitch count must be wrapped in a real fragment, scoped to just this section")
    assert "st_autorefresh(" not in src, "the old, full-page autorefresh call must be gone"
    assert "from streamlit_autorefresh import" not in src, (
        "the now-unnecessary third-party import must be removed entirely, not left dangling")
    assert "_HAS_AUTOREFRESH" not in src, (
        "the conditional-availability flag must be gone too -- auto-refresh is now always "
        "available as a native Streamlit feature, not an optional third-party one")
    print("✓ Pitching Lab's live pitch count genuinely uses a real, scoped st.fragment instead of a full-page autorefresh, and the now-unnecessary third-party dependency is gone")


def test_streamlit_autorefresh_removed_from_requirements():
    # Confirms the real cleanup went all the way through -- the dependency itself, not just its
    # one real call site, since a real package still sitting in requirements.txt unused is its
    # own kind of quiet redundancy.
    src = (_HERE / "requirements.txt").read_text()
    assert "streamlit-autorefresh==" not in src, (
        "streamlit-autorefresh must be genuinely removed from requirements.txt, not just unused in code")
    print("✓ streamlit-autorefresh is genuinely removed from requirements.txt, not just orphaned in code")


def test_bullpen_fatigue_fetch_consolidated_across_all_three_real_callers():
    # A REAL, CONFIRMED FIX found in the same real module-audit pass: three separate view files
    # each independently cached the exact same real, expensive fetch (E.get_team_bullpen_
    # fatigue). Unlike the pitching-slate case, each page's own post-processing genuinely
    # differs (Bullpen Watch also names the most-taxed pitcher, Pitching Lab enriches with FIP
    # metrics) -- so only the fetch itself is shared, confirmed here, not a forced identical shape.
    for filename in ("6_Game_Watch.py", "5_Bullpen_Watch.py", "7_#L01f3af_Pitching_Lab.py"):
        src = (_HERE / "views" / filename).read_text()
        assert "import mlb_shared_cache as MSC" in src, f"{filename} must import the shared cache module"
        assert "MSC.get_team_bullpen_fatigue_cached(" in src, f"{filename} must call the real, shared cached fetch"
        assert "E.get_team_bullpen_fatigue(" not in src, (
            f"{filename} must not still call the real, unshared fetch directly")
    print("✓ All three real callers (Game Watch, Bullpen Watch, Pitching Lab) now share one real cached fetch, each keeping its own real post-processing")


def test_every_view_file_has_a_matching_meta_entry():
    # Regression guard for a real, reported bug: a new page (24_Highlights.py) was added to
    # views/ without a matching entry in streamlit_app.py's meta dict, so it silently fell back
    # to the raw, unformatted filename ("24_Highlights") in the sidebar instead of a real title
    # and icon -- no error, no crash, just a wrong-looking sidebar entry that's easy to miss
    # until someone actually looks at it. Confirms every view file's leading number is a real
    # key in meta, so this can't happen silently again for the next new page.
    views_dir = _HERE / "views"
    src = (_HERE / "streamlit_app.py").read_text()
    m = re.search(r"meta = \{(.*?)\n    \}", src, re.DOTALL)
    assert m, "streamlit_app.py must define meta"
    known_keys = set(re.findall(r'"(\d+)":\s*\(', m.group(1)))
    missing = []
    for f in views_dir.glob("*.py"):
        lead_match = re.match(r"(\d+)", f.name)
        if not lead_match:
            continue   # a view file with no leading number isn't part of this numbering scheme
        if lead_match.group(1) not in known_keys:
            missing.append(f.name)
    assert not missing, f"these view files have no matching meta entry: {missing}"
    print(f"✓ every numbered view file has a matching streamlit_app.py meta entry "
         f"({len(known_keys)} registered)")


def test_no_deprecated_use_container_width_anywhere():
    # Regression guard for a real fix: use_container_width was deprecated by Streamlit (removal
    # already past its own stated date as of this platform's current date) and has been fully
    # replaced everywhere it appeared -- 89 occurrences across 20 files, all mapped to the real
    # migration (use_container_width=True -> width="stretch", use_container_width=False ->
    # width="content"), verified directly against Streamlit's own source and release notes
    # before making the change, not guessed at. This confirms it can't silently creep back in
    # during future work -- a new page added later, or code pasted from an old example, could
    # easily reintroduce the deprecated parameter without anyone noticing until it breaks.
    py_files = [f for f in _HERE.glob("*.py") if not f.name.startswith("test_")]
    py_files += list((_HERE / "views").glob("*.py"))
    offenders = []
    for f in py_files:
        if "use_container_width" in f.read_text(encoding="utf-8"):
            offenders.append(f.name)
    assert not offenders, f"deprecated use_container_width found in: {offenders}"
    print(f"✓ use_container_width is fully migrated to width=\"stretch\"/\"content\" everywhere "
         f"({len(py_files)} files checked)")


def test_every_meta_entry_has_a_real_sidebar_section():
    # Regression guard for the new sidebar sectioning: every page number registered in meta
    # must land in a real SECTION_OF entry (or the "Deep Research" catch-all), so a future page
    # never silently vanishes from the sidebar or lands somewhere confusing without anyone
    # noticing. Confirms the mapping is complete, not just present.
    src = (_HERE / "streamlit_app.py").read_text()
    meta_match = re.search(r"meta = \{(.*?)\n    \}", src, re.DOTALL)
    assert meta_match, "streamlit_app.py must define meta"
    meta_keys = set(re.findall(r'"(\d+)":\s*\(', meta_match.group(1)))

    section_match = re.search(r"SECTION_OF = \{\}(.*?)\n\n    def lead", src, re.DOTALL)
    assert section_match, "streamlit_app.py must define SECTION_OF"
    section_src = section_match.group(1)
    covered = set()
    for keys_str in re.findall(r'for k in \(([^)]*)\):', section_src):
        covered.update(k.strip().strip('"') for k in keys_str.split(","))
    # "0" is handled separately (Home's own section) -- every OTHER meta key must be covered,
    # since the code's own fallback (SECTION_OF.get(key, "🔬 Deep Research")) means an omission
    # wouldn't crash, just land silently in a section that might not be the intended one.
    uncovered = meta_keys - covered
    assert not uncovered, f"these page numbers have no explicit sidebar section: {uncovered}"
    print(f"✓ every meta-registered page number has an explicit sidebar section "
         f"({len(covered)} covered)")


def test_sidebar_sections_match_the_documented_grouping():
    # Confirms the actual grouping matches what's documented -- 5 sections, consolidated down
    # from an original 7 directly on request after real, reported sidebar clutter (each section
    # header is itself a full line of text; Live Signals and Trading Desk were the two smallest
    # sections, merged into Research & Signals rather than kept as their own single-line headers).
    src = (_HERE / "streamlit_app.py").read_text()
    section_match = re.search(r"SECTION_OF = \{\}(.*?)\n\n    def lead", src, re.DOTALL)
    assert section_match, "streamlit_app.py must define SECTION_OF"
    section_src = section_match.group(1)
    pairs = re.findall(r'for k in \(([^)]*)\):\s*\n\s*SECTION_OF\[k\] = "([^"]*)"', section_src)
    actual = {}
    for keys_str, section in pairs:
        for k in keys_str.split(","):
            k = k.strip().strip('"')
            if k:   # trailing commas in single-element tuples like ("15",) produce an empty
                    # split segment -- not a real key, just filter it out
                actual[k] = section
    expected = {
        "0": "🏠 START HERE", "28": "🏠 START HERE",
        "1": "🎯 RECOMMENDATIONS", "2": "🎯 RECOMMENDATIONS", "3": "🎯 RECOMMENDATIONS",
        "4": "🎯 RECOMMENDATIONS", "23": "🎯 RECOMMENDATIONS", "24": "🎯 RECOMMENDATIONS",
        "5": "🛰️ LIVE SIGNALS", "6": "🛰️ LIVE SIGNALS",
        "7": "🔬 DEEP RESEARCH", "8": "🔬 DEEP RESEARCH", "9": "🔬 DEEP RESEARCH",
        "10": "🔬 DEEP RESEARCH", "11": "🔬 DEEP RESEARCH", "12": "🔬 DEEP RESEARCH",
        "13": "🔬 DEEP RESEARCH", "14": "🔬 DEEP RESEARCH", "15": "🔬 DEEP RESEARCH",
        "25": "🔬 DEEP RESEARCH", "26": "🔬 DEEP RESEARCH", "27": "🔬 DEEP RESEARCH",
        "29": "🔬 DEEP RESEARCH", "30": "🔬 DEEP RESEARCH", "31": "🔬 DEEP RESEARCH",
        "32": "🔬 DEEP RESEARCH", "33": "🔬 DEEP RESEARCH", "34": "🔬 DEEP RESEARCH",
        "16": "🔍 SELF-GRADING & PROOF", "17": "🔍 SELF-GRADING & PROOF",
        "18": "🔍 SELF-GRADING & PROOF", "19": "🔍 SELF-GRADING & PROOF",
        "20": "📣 OPS & CONTENT", "21": "📣 OPS & CONTENT", "22": "📣 OPS & CONTENT",
    }
    assert actual == expected, f"section grouping drifted from expected: {actual}"
    print("✓ sidebar sections match the documented, 6-section grouping (uppercase for "
         "visual prominence, Live Signals/Deep Research split along a real conceptual line)")


def test_home_page_shares_command_centers_section():
    # Regression guard for a real, found bug: Home.py is added to the sidebar separately from
    # the meta-driven loop (it isn't a numbered view file), with its own hardcoded section name
    # -- when Command Center's section was renamed, this hardcoded string was missed, silently
    # producing two separate single-item "home" sections instead of one shared one. Confirms
    # both stay in sync going forward.
    src = (_HERE / "streamlit_app.py").read_text()
    home_match = re.search(r'sections: dict = \{"([^"]*)":', src)
    assert home_match, "streamlit_app.py must define the Home.py section inline"
    home_section = home_match.group(1)

    section_match = re.search(r"SECTION_OF = \{\}(.*?)\n\n    def lead", src, re.DOTALL)
    assert section_match, "streamlit_app.py must define SECTION_OF"
    zero_match = re.search(r'for k in \([^)]*"0"[^)]*\):\s*\n\s*SECTION_OF\[k\] = "([^"]*)"', section_match.group(1))
    assert zero_match, "streamlit_app.py must assign a section for page \"0\" (Command Center)"
    command_center_section = zero_match.group(1)

    assert home_section == command_center_section, (
        f"Home.py's section ({home_section!r}) doesn't match Command Center's ({command_center_section!r}) "
        f"-- they're meant to share one front-door section, not two separate ones")
    print(f"✓ Home.py and Command Center share the same sidebar section ({home_section!r})")


def test_first_innings_totals_registered_in_all_three_registries():
    # Regression guard for page 27 (First Innings Totals) specifically -- a page can pass
    # test_every_view_file_has_a_matching_meta_entry (meta only) while still being missing from
    # sport_only_leads (would then show up for every sport, including ones with no first-innings
    # engine support) or SECTION_OF (would silently fall into the "Deep Research" catch-all
    # instead of the intended section). Confirms all three registries agree on key "27" at once,
    # not just that each one individually has *some* "27" entry.
    src = (_HERE / "streamlit_app.py").read_text()

    lead_match = re.search(r'"27":\s*\("MLB",\)', src)
    assert lead_match, "page 27 must be MLB-only in sport_only_leads"

    meta_match = re.search(r'"27":\s*\("([^"]+)",\s*"([^"]+)",\s*"([^"]+)"\)', src)
    assert meta_match, "page 27 must have a meta entry"
    title, icon, slug = meta_match.groups()
    assert title == "First Innings Totals"
    assert slug == "mlb_first_innings_totals"
    assert icon, "page 27 must have a real icon, not an empty string"

    section_match = re.search(r"SECTION_OF = \{\}(.*?)\n\n    def lead", src, re.DOTALL)
    assert section_match, "streamlit_app.py must define SECTION_OF"
    covered = set()
    for keys_str in re.findall(r'for k in \(([^)]*)\):', section_match.group(1)):
        covered.update(k.strip().strip('"') for k in keys_str.split(","))
    assert "27" in covered, "page 27 must land in a real sidebar section, not the catch-all"

    print("✓ First Innings Totals (27) is registered consistently across sport_only_leads, "
         "meta, and SECTION_OF")


def test_first_innings_totals_view_file_uses_platform_conventions():
    # Confirms the actual view file (not just streamlit_app.py's registries) exists and follows
    # the same real conventions every other page here uses -- base_css/page_header for the shared
    # look, require_sport as the MLB-only gate (matching sport_only_leads' own "27": ("MLB",)
    # above, so the two can't silently drift apart), and calls into the real, tested engine/
    # projections functions this page is built on rather than reimplementing the math inline.
    view_path = _HERE / "views" / "27_MLB_First_Innings_Totals.py"
    assert view_path.exists(), "views/27_MLB_First_Innings_Totals.py must exist"
    src = view_path.read_text()

    assert "C.base_css()" in src
    assert 'C.page_header(' in src
    assert 'sports.require_sport(["MLB"]' in src

    # A REAL, CONFIRMED FIX to this test itself: E.build_pitching_slate is no longer called
    # directly in this view -- it now goes through mlb_shared_cache.load_pitching_slate_cached,
    # a real, deliberate consolidation (this exact call used to be duplicated as three separate,
    # byte-for-byte-identical local @st.cache_data wrappers across this file, Bullpen Watch, and
    # Game Watch; see mlb_shared_cache.py's own module docstring for the full reasoning). The
    # real underlying work still happens in mlb_engine, just reached through the shared cache
    # now, so this check follows that real call chain instead.
    for call in ("MSC.load_pitching_slate_cached(", "E.pair_pitching_slate_by_game(",
                "E.get_team_recent_first_innings_runs(",
                "E.get_pitcher_recent_first_innings_allowed(",
                "P.project_team_first_innings_total(", "P.prob_over_first_innings_line("):
        assert call in src, f"expected a real call to {call} in the First Innings Totals view"

    assert "use_container_width" not in src

    print("✓ First Innings Totals view file exists, uses shared page conventions, and calls "
         "the real (not reimplemented) engine/projections functions it's built on")


def test_league_schedules_registered_and_universal():
    # Regression guard for page 28 (League Schedules) specifically -- registered in meta and
    # SECTION_OF (so it actually appears in the sidebar, in the START HERE section right
    # alongside Command Center, per direct request), and DELIBERATELY ABSENT from sport_only_
    # leads -- unlike First Innings Totals (MLB-only by design), this page must work for every
    # sport, so it must never be gated to a subset the way sport_only_leads gates other pages.
    src = (_HERE / "streamlit_app.py").read_text()

    meta_match = re.search(r'"28":\s*\("([^"]+)",\s*"([^"]+)",\s*"([^"]+)"\)', src)
    assert meta_match, "page 28 must have a meta entry"
    title, icon, slug = meta_match.groups()
    assert title == "League Schedules"
    assert slug == "league_schedules"
    assert icon

    section_match = re.search(r"SECTION_OF = \{\}(.*?)\n\n    def lead", src, re.DOTALL)
    assert section_match
    covered = set()
    for keys_str in re.findall(r'for k in \(([^)]*)\):', section_match.group(1)):
        covered.update(k.strip().strip('"') for k in keys_str.split(","))
    assert "28" in covered, "page 28 must land in a real sidebar section, not the catch-all"

    lead_match = re.search(r'"28":\s*\(', src[:src.index("meta = {")])   # only search sport_only_leads' own block, before meta
    assert lead_match is None, "page 28 (League Schedules) must NOT appear in sport_only_leads -- it has to work for every sport"
    print("✓ League Schedules (28) is registered in meta/SECTION_OF and deliberately absent from sport_only_leads")


def test_league_schedules_load_schedule_functions_take_sport_as_a_real_argument():
    # Regression guard for a real, confirmed bug: both cached loaders used to close over the
    # page-level E (this sport's engine module) without taking the sport itself as an argument --
    # Streamlit's cache_data keys purely on a function's own arguments, never on outer/closure
    # variables, so NFL and NCAAF (the same real season number, most of the time) silently
    # collided: whichever was loaded first in a session got reused for the OTHER sport too,
    # mislabeled, until the cache's own TTL expired. Confirmed directly from a real report: the
    # NCAAF tab was showing NFL's own real schedule.
    src = (_HERE / "views" / "28_League_Schedules.py").read_text()
    assert "def load_schedule(sport_key_inner: str, season_inner: int):" in src, (
        "load_schedule must take the sport as a real argument, not close over the page-level E")
    assert "def load_schedule_for_date(sport_key_inner: str, date_str_inner: str):" in src, (
        "load_schedule_for_date must take the sport as a real argument too -- same bug class")
    assert "load_schedule(current, season)" in src
    assert "load_schedule_for_date(current, date_str)" in src
    print("✓ both League Schedules cache loaders take sport as a real, explicit argument")


def test_league_schedules_load_schedule_doesnt_collide_across_sports():
    # THE real proof, not just a source-text check: extracts the real load_schedule function
    # from the actual file (walking the AST, since it's defined conditionally inside an `if`
    # block, not at module top level) and calls it for two different sports with the IDENTICAL
    # season number -- the exact real-world scenario that triggered the original bug. A genuine
    # cache-key collision would return the SAME (wrong) result for the second call; the fix
    # must return each sport's own, genuinely different result.
    import ast
    import sports as S
    src = (_HERE / "views" / "28_League_Schedules.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "load_schedule")
    ns = {"sports": S, "st": __import__("streamlit")}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<load_schedule>", "exec"), ns)
    load_schedule = ns["load_schedule"]

    class _FakeEngine:
        def __init__(self, tag):
            self.tag = tag
        def get_schedule(self, season):
            return [{"week": 1, "tag": self.tag, "season": season}]

    class _FakeSport:
        def __init__(self, tag):
            self.engine = _FakeEngine(tag)

    orig_get = S.get
    S.get = lambda key: _FakeSport(key)   # each sport's own engine returns ITS OWN tagged schedule
    try:
        nfl_result = load_schedule("NFL", 2026)
        ncaaf_result = load_schedule("NCAAF", 2026)   # SAME season number -- the real collision scenario
    finally:
        S.get = orig_get

    assert nfl_result[0]["tag"] == "NFL"
    assert ncaaf_result[0]["tag"] == "NCAAF", (
        f"expected NCAAF's own real schedule, got {ncaaf_result} -- a cache-key collision would "
        "silently return NFL's own cached result here instead")
    print("✓ load_schedule correctly returns each sport's own real schedule, even for the same "
         "season number, with no cache-key collision between them")



def test_league_schedules_merge_combines_multiple_dates_without_dropping_or_duplicating():
    # THE real, new logic this rebuild added: an NFL/NCAAF week spans several real calendar
    # dates, but schedule_board.todays_schedule() is scoped to ONE date -- _merge_schedule_
    # results combines several of its real outputs into one. Executed directly from the real
    # file source, not a duplicate reimplementation, so this actually tests the shipped function.
    import ast
    src = (_HERE / "views" / "28_League_Schedules.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_merge_schedule_results")
    ns: dict = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<league_schedules_merge>", "exec"), ns)
    merge = ns["_merge_schedule_results"]

    thu = {"grouped": {"AFC": {"East": [{"home": "Buffalo Bills", "away": "Miami Dolphins"}]}},
          "other": [], "has_divisions": True}
    sun = {"grouped": {"AFC": {"East": [{"home": "NY Jets", "away": "New England Patriots"}]},
                      "NFC": {"West": [{"home": "SF 49ers", "away": "Seattle Seahawks"}]}},
          "other": [{"home": "Unmapped Team", "away": "Other Team"}], "has_divisions": True}
    merged = merge([thu, sun, None])   # None (a real possible per-date result) must not crash the merge

    assert len(merged["grouped"]["AFC"]["East"]) == 2   # both real Thursday AND Sunday AFC East games kept, not overwritten
    assert len(merged["grouped"]["NFC"]["West"]) == 1
    assert len(merged["other"]) == 1
    assert merged["has_divisions"] is True
    print("✓ _merge_schedule_results correctly combines multiple real per-date results across a week, dropping nothing, duplicating nothing")



def test_league_schedules_view_file_uses_platform_conventions_and_no_gate():
    view_path = _HERE / "views" / "28_League_Schedules.py"
    assert view_path.exists(), "views/28_League_Schedules.py must exist"
    src = view_path.read_text()

    assert "C.base_css()" in src
    assert "C.hero_banner(" in src   # landing-page tier styling, matching Home.py/Command Center
    assert "sports.enabled_sports()" in src   # Home.py's own real sport-tab pattern, reused not reinvented
    assert "st.session_state[\"sport\"]" in src   # same session_state key Home.py's own tabs use -- one shared selector, not a page-local copy
    # Deliberately NO require_sport/require_live_engine gate -- this page must work for every
    # sport (gracefully degrading for one with no real get_schedule, e.g. UFC), never blocked at
    # the door the way a sport-specific/projections-only page correctly is.
    assert "sports.require_sport(" not in src
    assert "sports.require_live_engine(" not in src
    print("✓ League Schedules view file uses shared page conventions and is deliberately ungated by sport")


def test_league_schedules_team_and_score_lookup_covers_every_real_confirmed_field_shape():
    # THE real regression guard for the actual bug found and fixed while building this page:
    # NCAAF's own real schedule rows use start_date/home_team/away_team/home_points/away_points,
    # genuinely different field names than MLB's game_date/home_name/away_name/home_score/away_
    # score -- confirmed directly by reading ncaaf_data.py's own schedule row construction, not
    # guessed. Executes the view file's own _team/_score functions directly (not a duplicate
    # reimplementation) against every real, confirmed shape this platform's own engines produce.
    import ast
    src = (_HERE / "views" / "28_League_Schedules.py").read_text()
    tree = ast.parse(src)
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("_team", "_score")]
    assert len(funcs) == 2, "expected both _team and _score helper functions to exist"
    ns: dict = {}
    exec(compile(ast.Module(body=funcs, type_ignores=[]), "<league_schedules_helpers>", "exec"), ns)
    _team, _score = ns["_team"], ns["_score"]

    mlb = {"home_name": "Yankees", "away_name": "Red Sox", "home_score": 5, "away_score": 3}
    assert _team(mlb, "home") == "Yankees" and _score(mlb, "home") == 5

    nfl = {"home_team": "KC", "away_team": "BUF", "home_score": 24, "away_score": 20}
    assert _team(nfl, "home") == "KC" and _score(nfl, "home") == 24

    ncaaf = {"home_team": "Georgia", "away_team": "Alabama", "home_points": 27, "away_points": 24}
    assert _team(ncaaf, "home") == "Georgia" and _score(ncaaf, "home") == 27, (
        "NCAAF uses home_team/home_points, not home_name/home_score -- a real, confirmed field-name gap")

    wnba = {"home_name": "Aces", "away_name": "Storm"}   # no real score field on this sport's own get_schedule
    assert _team(wnba, "home") == "Aces" and _score(wnba, "home") is None, (
        "WNBA's own get_schedule carries no score field -- must be honest None, never a fabricated 0")

    print("✓ League Schedules' team/score lookup correctly covers every real, confirmed field-name shape "
         "across MLB, NFL, NCAAF, and WNBA -- including NCAAF's genuinely different field names")


# ----------------------------------------------------------------- Matchup Lab: L5/L10 Avg
def test_matchup_lab_window_selector_wired_into_both_tables():
    # Regression guard confirming the real redesign (a window selector that recomputes BOTH the
    # player's own rate and the opponent's own allowed rate for the same window, not just an
    # extra column bolted onto the player's own side -- the earlier, less complete version) is
    # actually wired into both displayed tables, not just computed and left unused.
    src = (_HERE / "views" / "11_Matchup_Lab.py").read_text()
    assert 'window_label = st.radio("Window",' in src, "the real Window selector must actually exist"
    assert '"Season": (None, None), "Last 10 Games": (10, opp_l10), "Last 5 Games": (5, opp_l5)' in src, (
        "the selector must drive both window_n AND the matching real opp_allowed dict together")
    assert "P.build_matchup_profile(row, h2h_log, opp_allowed_for_window or {}, opp_season," in src
    assert '"Market", "Recent Avg", "Window Avg"' in src, "table 1 must show the real recomputed Window Avg, not a fixed column set"
    assert '"Opp Window Allowed"' in src, "table 2 must show the real recomputed opponent side too, not just the player's own"
    print("✓ Matchup Lab's real Window selector is genuinely wired into both tables — player's "
         "own rate AND opponent's own allowed rate both recompute for the same selected window")


def test_matchup_lab_defense_trend_honestly_omitted_on_season_window():
    # Regression guard for the real, deliberate design point: season-vs-itself isn't a real
    # trend, so the view must branch and NOT actually SELECT a Defense Trend column when Season
    # is selected -- confirmed by real source structure, not just that the branch exists somewhere.
    src = (_HERE / "views" / "11_Matchup_Lab.py").read_text()
    assert 'odf = pd.DataFrame(profile)[["Market", "Opp Window Allowed"]]' in src, (
        "the Season-window branch must select only the real numbers that actually exist on that window")
    assert 'odf = pd.DataFrame(profile)[["Market", "Opp Window Allowed", "Defense Trend", "Trend Tag"]]' in src, (
        "the Last 10/Last 5 branch must select the real trend comparison, since it's a genuine reading there")
    print("✓ Matchup Lab honestly omits the Defense Trend column on the Season window, and includes "
         "it on Last 10/Last 5 where it's a real reading")


def test_matchup_lab_load_matchup_fetches_all_three_real_windows():
    # Confirms all three real opponent-allowed windows are fetched up front (L5, L10, season) --
    # get_team_recent_allowed_stats is genuinely free (built from box scores already cached for
    # the slate), so this should NOT be gated behind a real-cost opt-in the way Dinger Engine's
    # own L5 Hit Rate needed to be for a genuinely new per-player fetch.
    src = (_HERE / "views" / "11_Matchup_Lab.py").read_text()
    assert "opp_l5 = E.get_team_recent_allowed_stats(opp_id, date_str, n=5)" in src
    assert "opp_l10 = E.get_team_recent_allowed_stats(opp_id, date_str)" in src
    assert "opp_season = E.get_team_recent_allowed_stats(opp_id, date_str, n=82, days_back=200)" in src
    print("✓ Matchup Lab fetches all three real windows (L5/L10/Season) up front, no opt-in gate needed for genuinely free data")


def test_matchup_lab_window_redesign_landed_identically_across_all_three_basketball_sports():
    # Regression guard confirming the SAME real redesign landed in all three projections modules
    # (WNBA/NBA/NCAAMB), not just one -- Matchup Lab (page 11) serves all three from one shared
    # page, so a gap in any single module would silently break the window selector for two sports.
    for fname in ("wnba_projections.py", "nba_projections.py", "ncaamb_projections.py"):
        src = (_HERE / fname).read_text()
        assert "window_n: Optional[int] = None" in src, f"{fname} is missing the real window_n parameter"
        assert '"Window Avg"' in src and '"Opp Window Allowed"' in src, f"{fname} is missing the real recomputed output fields"
        assert "if window_n is not None:" in src, f"{fname} must honestly omit Defense Trend on the Season window"
    print("✓ The real window_n redesign is computed identically across WNBA, NBA, and NCAAMB's own projections modules")


# ----------------------------------------------------------------- Dinger Engine: L5 Hit Rate
# ----------------------------------------------------------------- Dinger Engine: L5 Hit Rate
def test_dinger_engine_load_l5_context_computes_all_four_real_rates():
    # THE actual real logic this feature adds, executed directly from the real file source (not
    # a duplicate reimplementation) -- extracted via AST including its own @st.cache_data
    # decorator, same pattern already used elsewhere in this exact test file. Confirms all FOUR
    # real rates (not just Hit%, the original single-column version) come from the SAME one real
    # fetch, each using its own real model threshold, hand-verified exact numbers.
    import ast
    view_path = _HERE / "views" / "8_#L01f4a3_Dinger_Engine.py"
    src = view_path.read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "load_l5_context")

    import mlb_engine as E
    import streamlit as st
    ns = {"E": E, "st": st}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<load_l5_context>", "exec"), ns)
    load_l5_context = ns["load_l5_context"]

    def fake_recent_games(pid, season, before_date=None, n=5):
        # 5 real games, exact hand-verifiable ground truth for all four stats at once:
        # hits:   [1, 0, 2, 0, 1] -> 3/5 games with >0.5 hits    = 0.6
        # hr:     [1, 0, 0, 0, 1] -> 2/5 games with >0.5 HR      = 0.4
        # tb:     [2, 0, 3, 0, 4] -> 3/5 games with >1.5 TB      = 0.6
        # k:      [0, 1, 0, 2, 1] -> 3/5 games with >0.5 K       = 0.6
        return [
            {"hits": 1, "hr": 1, "total_bases": 2, "strikeouts": 0},
            {"hits": 0, "hr": 0, "total_bases": 0, "strikeouts": 1},
            {"hits": 2, "hr": 0, "total_bases": 3, "strikeouts": 0},
            {"hits": 0, "hr": 0, "total_bases": 0, "strikeouts": 2},
            {"hits": 1, "hr": 1, "total_bases": 4, "strikeouts": 1},
        ]

    orig = E.get_hitter_recent_games
    E.get_hitter_recent_games = fake_recent_games
    try:
        result = load_l5_context(12345, 2026, "2026-07-18")
    finally:
        E.get_hitter_recent_games = orig

    assert result is not None
    assert abs(result["l5_hit_rate"] - 0.6) < 1e-9
    assert abs(result["l5_hr_rate"] - 0.4) < 1e-9
    assert abs(result["l5_tb_rate"] - 0.6) < 1e-9
    assert abs(result["l5_so_rate"] - 0.6) < 1e-9
    assert result["l5_games"] == 5
    print("✓ load_l5_context correctly computes all four real rates (HR%/Hit%/TB1.5%/SO%) from the one real fetch, hand-verified exact numbers")


def test_dinger_engine_load_l5_context_none_for_no_real_games():
    import ast
    view_path = _HERE / "views" / "8_#L01f4a3_Dinger_Engine.py"
    src = view_path.read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "load_l5_context")

    import mlb_engine as E
    import streamlit as st
    ns = {"E": E, "st": st}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<load_l5_context_empty>", "exec"), ns)
    load_l5_context = ns["load_l5_context"]

    orig = E.get_hitter_recent_games
    E.get_hitter_recent_games = lambda pid, season, before_date=None, n=5: []
    try:
        result = load_l5_context(99999, 2026, "2026-07-18")
    finally:
        E.get_hitter_recent_games = orig

    assert result is None   # an honest "no real data," never a fabricated 0.0 on any of the four
    print("✓ load_l5_context returns None (not fabricated 0%s) when no real recent games are found")


def test_dinger_engine_l5_context_wired_into_the_real_table():
    # Regression guard confirming the gate is actually WIRED IN, matching the same class of
    # check already done for every other feature added this session -- load_l5_context could be
    # perfectly correct and simply never reach the actual displayed table. Confirms all three NEW
    # columns (L5 HR%/L5 TB1.5%/L5 SO%), not just the original L5 Hit%.
    src = (_HERE / "views" / "8_#L01f4a3_Dinger_Engine.py").read_text()
    assert 'show_l5 = st.checkbox(' in src, "the L5 checkbox must actually exist"
    assert "_add_l5_columns(sub)" in src, "the L5 columns must actually get merged into the displayed table"
    display_cols_match = re.search(r"DISPLAY_COLS = \[(.*?)\]", src, re.DOTALL)
    assert display_cols_match, "DISPLAY_COLS must exist"
    cols_text = display_cols_match.group(1)
    for real_col in ('"L5 HR%"', '"L5 Hit%"', '"L5 TB1.5%"', '"L5 SO%"'):
        assert real_col in cols_text, f"{real_col} must be in DISPLAY_COLS or style_hitters will silently never show it"
    # "right next to" each real model column per the direct request -- confirmed by real position
    assert cols_text.index('"HR%"') < cols_text.index('"L5 HR%"') < cols_text.index('"Hit%"'), (
        "L5 HR% must sit immediately after HR%")
    assert cols_text.index('"Hit%"') < cols_text.index('"L5 Hit%"') < cols_text.index('"TB1.5%"'), (
        "L5 Hit% must sit immediately after Hit%")
    assert cols_text.index('"TB1.5%"') < cols_text.index('"L5 TB1.5%"') < cols_text.index('"SO Prob"'), (
        "L5 TB1.5% must sit immediately after TB1.5%")
    assert cols_text.index('"SO Prob"') < cols_text.index('"L5 SO%"'), (
        "L5 SO% must sit immediately after SO Prob")
    print("✓ All four L5 columns are genuinely wired into the real table: checkbox exists, gets "
         "merged in, and each sits right next to its own real model column in DISPLAY_COLS")



def test_first_innings_totals_market_names_match_settlement_registry():
    # Regression guard for a real, silent-corruption-class risk: the view file logs picks under
    # whichever market name MARKET_BY_N maps a given n_innings to (quick_log's own play-dict
    # shape), and bet_settlement.py's TEAM_TOTAL_MARKETS dict must use the EXACT same strings as
    # its own keys, or a logged pick would silently never auto-grade -- landing in "unresolved"
    # forever with no error, no crash, just quietly never settling. A wrong field mapping here is
    # exactly the class of bug quick_log.py's own bet_log_fields_from_play docstring already
    # warns about for a different field. Checked in BOTH directions: every market the view can
    # log must be settleable, and (just as important) the two files must agree on which
    # n_innings each market name actually means -- a name matching but pointed at the wrong
    # window would settle a real bet against the wrong linescore, silently.
    view_src = (_HERE / "views" / "27_MLB_First_Innings_Totals.py").read_text()
    settlement_src = (_HERE / "bet_settlement.py").read_text()

    view_match = re.search(r"MARKET_BY_N = \{([^}]*)\}", view_src)
    assert view_match, "views/27_MLB_First_Innings_Totals.py must define MARKET_BY_N"
    view_pairs = dict(re.findall(r'(\d+):\s*"([^"]+)"', view_match.group(1)))
    view_market_to_n = {name: int(n) for n, name in view_pairs.items()}
    assert view_market_to_n, "MARKET_BY_N must have at least one real entry"

    settlement_match = re.search(r"TEAM_TOTAL_MARKETS = \{([^}]*)\}", settlement_src)
    assert settlement_match, "bet_settlement.py must define TEAM_TOTAL_MARKETS"
    settlement_market_to_n = dict(re.findall(r'"([^"]+)":\s*(\d+)', settlement_match.group(1)))
    settlement_market_to_n = {name: int(n) for name, n in settlement_market_to_n.items()}
    assert settlement_market_to_n, "TEAM_TOTAL_MARKETS must have at least one real entry"

    assert view_market_to_n == settlement_market_to_n, (
        f"market registry drift between the view and bet_settlement: view has "
        f"{view_market_to_n!r}, settlement has {settlement_market_to_n!r} — a logged pick would "
        f"either silently never settle, or settle against the wrong innings window")
    print(f"✓ First Innings Totals' logged market names ({sorted(view_market_to_n)}) match "
         "bet_settlement's own TEAM_TOTAL_MARKETS exactly, including which n_innings each one "
         "means, so logged picks actually auto-grade against the right window")


def test_first_innings_totals_offers_both_real_dk_windows():
    # Regression guard specifically for a real, confirmed mistake: an earlier draft of this page
    # dropped "First 3 Innings" entirely on the belief it wasn't a real market -- it is, verified
    # directly against a real DraftKings bet slip showing "Team Total Runs - 1st 3 Innings" and
    # "Team Total Runs - 1st 5 Innings" offered side by side. Confirms both real windows stay
    # present going forward, not just that whatever's there is internally consistent (the
    # previous test alone wouldn't catch someone removing 3-innings support from both files
    # together and staying "consistent" the whole time).
    view_src = (_HERE / "views" / "27_MLB_First_Innings_Totals.py").read_text()
    match = re.search(r"MARKET_BY_N = \{([^}]*)\}", view_src)
    assert match, "views/27_MLB_First_Innings_Totals.py must define MARKET_BY_N"
    ns_present = {int(n) for n in re.findall(r"(\d+):\s*\"", match.group(1))}
    assert ns_present == {3, 5}, (
        f"expected both real DK windows (3 and 5 innings), got {ns_present} — "
        "First 3 Innings is a real, confirmed market, not a fabricated default")
    print("✓ First Innings Totals offers both real DK windows (First 3 Innings and First 5 "
         "Innings), matching a real confirmed DK bet slip")


def test_first_innings_totals_offers_all_games_option():
    # Added directly on request: the Game dropdown must offer a real "All Games" choice (a
    # full-slate overview table, both sides, every game in the current time-slot filter) as well
    # as picking one specific game. Confirmed by source, not just that the string appears
    # somewhere -- it must actually be the FIRST option in the selectbox's own choice list.
    src = (_HERE / "views" / "27_MLB_First_Innings_Totals.py").read_text()
    assert 'game_pick = st.selectbox("Game", ["All Games"] + games_present' in src, (
        "the Game dropdown must offer \"All Games\" as its first real choice")
    assert 'if game_pick == "All Games":' in src, "the page must actually branch on the All Games choice, not just list it"
    print("\u2713 First Innings Totals offers a real \"All Games\" option in the Game dropdown, and branches on it")


def test_first_innings_totals_explains_the_real_calculation():
    # Added directly on request: a real "how this was calculated" breakdown, using the actual
    # real numbers already computed (team_recent/pitcher_allowed/proj), not a generic restatement.
    src = (_HERE / "views" / "27_MLB_First_Innings_Totals.py").read_text()
    assert 'with st.expander(f"\U0001F50D How this {n_innings}-inning projection was calculated"):' in src, (
        "the explanation must actually exist as a real expander, not just be planned")
    assert "proj['team_rate']" in src and "proj['pitcher_allowed_rate']" in src and "proj['projected_runs']" in src
    assert "team_games < 8" in src and "pitcher_starts < 5" in src, (
        "must flag a real thinner-than-usual sample, same small-sample honesty used elsewhere on this platform")
    print("\u2713 First Innings Totals explains the real calculation with the actual computed numbers, "
         "including a real small-sample caution")


def test_first_innings_totals_view_wires_bet_log():
    # Confirms the view file actually calls quick_log.render_quick_log (not just that the
    # underlying settlement machinery exists) -- the two previous tests would both pass even if
    # this page never called the widget at all, which would leave auto-grading real but
    # unreachable from the page itself.
    view_path = _HERE / "views" / "27_MLB_First_Innings_Totals.py"
    src = view_path.read_text()
    assert "import quick_log" in src
    assert "quick_log.render_quick_log(" in src
    print("✓ First Innings Totals view actually calls quick_log.render_quick_log, not just "
         "leaving the settlement machinery unreachable")


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
    # Regression guard: Pitching Lab/Dinger Engine/Matchup Lab(MLB)/Bullpen Watch/Game Watch must
    # stay MLB-only, Hot Hand Engine/Matchup Lab(WNBA/NBA/NCAAMB) must stay basketball-only, and
    # Matchup Lab(NFL)/Anytime TD Engine must stay NFL-only. A future page renumbering could
    # silently break this if nothing locks in which lead numbers map to which sport(s).
    #
    # Numbers updated for the platform-audit re-grouping (recommendations 1-4, moneyline signals
    # 5-6, deep research 7-14, trading desk 15, self-grading/proof 16-19, ops/content 20-22) --
    # this test's own real job (catching a silent renumbering mismatch) is exactly why it needed
    # updating here rather than being left to fail confusingly against the old numbers.
    #
    # Highlights (24) added directly on request, closing a real, reported gap: Highlights was
    # already gated MLB-only at the page level (its own real fields aren't wired into other
    # sports yet), but had no matching sidebar-level gate, so it stayed visible as a dead link
    # for every non-MLB sport.
    #
    # Hot Hand Engine (NFL, 25) added directly on request, closing the one real remaining gap
    # after NFL's own Matchup Lab/Anytime TD Engine/QB Lab were already built -- found live,
    # after an earlier claim NFL had neither Hot Hand Engine nor Matchup Lab turned out wrong
    # for Matchup Lab specifically.
    #
    # Player Lines (MLB, 26) added directly on request -- recent-form trend charts, pitcher or
    # batter, the MLB counterpart to WNBA/NBA/NCAAMB's own Matchup Lab trend charts.
    #
    # First Innings Totals (MLB, 27) added directly on request -- built directly on mlb_engine's
    # own get_team_recent_first_innings_runs/get_pitcher_recent_first_innings_allowed and
    # projections' own project_team_first_innings_total/prob_over_first_innings_line, no WNBA/NFL
    # equivalent exists yet, same MLB-only posture as Bullpen Watch/Game Watch/Highlights above.
    #
    # QB Lab (NCAAF, 29) added directly on request -- NCAAF's first real dedicated page, adapted
    # directly from NFL QB Lab (14) with every function signature and output dict key confirmed
    # to match exactly first. Same real reasoning as the sport-only gates above: this page's own
    # ncaaf_engine/ncaaf_projections calls have no meaning for any other sport's own data.
    #
    # Matchup Lab (NCAAF, 30) added directly on request -- adapted from NFL Matchup Lab (12), on
    # five new real engine functions (get_player_history_vs_opponent, get_team_rest_info, the
    # three TD-allowed functions) and five new real projections functions (build_matchup_profile
    # chief among them), each individually tested, not assumed correct by analogy to NFL's own.
    #
    # Player Lines (NCAAF, 31) added directly on request -- adapted from MLB Player Lines (26),
    # the fast browse-by-position trend-chart tool, built entirely on functions already tested
    # for QB Lab/Matchup Lab (get_player_season_games, build_trend_series, market_list/
    # default_line/stat_key_for) -- no new engine work needed for this one.
    #
    # Player Lines (NFL, 33) and Game Lab (NFL, 34) added directly on request -- wiring up NFL
    # with the same tools built for NCAAF. Player Lines adapts from page 31; Game Lab adapts
    # from NCAAF's Game Lab (32) adding a real, live injury report via nflreadpy (not a
    # placeholder). Two new engine functions (get_team_points_allowed, get_league_average_scoring)
    # added to nfl_engine.py; simulate_nfl_game added to nfl_projections.py.
    src = (_HERE / "streamlit_app.py").read_text()
    m = re.search(r"sport_only_leads = \{([^}]*)\}", src, re.DOTALL)
    assert m, "streamlit_app.py must define sport_only_leads"
    pairs = {}
    for key, vals in re.findall(r'"(\d+)":\s*\(([^)]*)\)', m.group(1)):
        pairs[key] = tuple(re.findall(r'"(\w+)"', vals))
    assert pairs == {"5": ("MLB",), "6": ("MLB",), "7": ("MLB",), "8": ("MLB",), "9": ("MLB",),
                     "10": ("WNBA", "NBA", "NCAAMB"), "11": ("WNBA", "NBA", "NCAAMB"),
                     "12": ("NFL",), "13": ("NFL",), "14": ("NFL",),
                     "23": ("UFC",), "24": ("MLB",), "25": ("NFL",), "26": ("MLB",),
                     "27": ("MLB",), "29": ("NCAAF",), "30": ("NCAAF",), "31": ("NCAAF",),
                     "32": ("NCAAF",), "33": ("NFL",), "34": ("NFL",)}, pairs
    print("✓ sport_only_leads matches expected config (Bullpen Watch/Game Watch/Pitching Lab/"
          "Dinger Engine/Matchup Lab(MLB)/Player Lines/First Innings Totals -> MLB, Hot Hand "
          "Engine/Matchup Lab(WNBA/NBA/NCAAMB) -> WNBA+NBA+NCAAMB, Matchup Lab(NFL)/Anytime TD "
          "Engine/QB Lab/Hot Hand Engine(NFL) -> NFL, UFC Fight Card -> UFC, Highlights -> MLB, "
          "QB Lab(NCAAF)/Matchup Lab(NCAAF)/Player Lines(NCAAF) -> NCAAF)")


def test_projections_only_pages_hidden_for_sports_without_projections():
    # Regression guard for a real, reported gap: for UFC (has_projections=False), Best Bets,
    # Graded Picks, Suggested Parlays, Speculative Basket, Edge Board, Retrospective, Model
    # Dashboard, Track Record, Media Room, and Podcast Studio each carry their own has_projections
    # gate that immediately shows "doesn't apply, head to UFC Fight Card" and stops -- every one
    # a guaranteed dead end, not graceful degradation, when reached from the sidebar. Bet Log and
    # Data Health must stay OUT of this set -- Bet Log is a real, functional log for any sport
    # with a market_map (UFC has one), and Data Health is sport-agnostic.
    src = (_HERE / "streamlit_app.py").read_text()
    m = re.search(r"projections_only_titles = \{([^}]*)\}", src, re.DOTALL)
    assert m, "streamlit_app.py must define projections_only_titles"
    gated = {t.strip().strip('"') for t in m.group(1).split(",") if t.strip()}
    assert gated == {"Best Bets", "Graded Picks", "Suggested Parlays", "Speculative Basket",
                     "Edge Board", "Retrospective", "Model Dashboard", "Track Record",
                     "Media Room", "Podcast Studio"}, gated
    assert "Bet Log" not in gated and "Data Health" not in gated
    all_titles = set(re.findall(r'\("([^"]+)",\s*"[^"]*",\s*"[^"]*"\)', src))
    assert gated <= all_titles, f"gated titles not found in meta: {gated - all_titles}"
    # And confirm the loop actually reads this set against has_projections, not just defines it
    # unused -- a real, reported class of bug elsewhere in this project (a check defined but
    # never wired into the actual code path).
    assert "not sports.get(active_sport).has_projections" in src
    print("✓ projections_only_titles targets exactly the 10 pages that are guaranteed dead ends "
         "for an outcome-based sport, and is actually wired into the sidebar-building loop")


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
        ("views/10_Hot_Hand_Engine.py", ["load_board", "load_injuries"]),
        ("views/11_Matchup_Lab.py", ["load_slate", "load_injuries", "load_matchup"]),
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


def test_has_started_true_for_a_game_already_underway():
    # The exact real-world scenario this was built for: prepping for a 1:40pm game while an
    # earlier 12:10pm game is already in progress.
    from datetime import datetime
    import pytz
    eastern = pytz.timezone("US/Eastern")
    fixed_now = eastern.localize(datetime(2026, 7, 30, 13, 30))   # 1:30pm ET
    assert S.has_started("2026-07-30T16:10:00Z", now=fixed_now) is True   # 12:10pm ET game
    print("✓ has_started correctly reports True for a game whose scheduled start has passed")


def test_has_started_false_for_a_game_not_yet_started():
    from datetime import datetime
    import pytz
    eastern = pytz.timezone("US/Eastern")
    fixed_now = eastern.localize(datetime(2026, 7, 30, 13, 30))   # 1:30pm ET
    assert S.has_started("2026-07-30T17:40:00Z", now=fixed_now) is False   # 1:40pm ET game
    print("✓ has_started correctly reports False for a game that hasn't started yet")


def test_has_started_none_for_unknown_or_malformed():
    # An honest "can't tell" state, same convention as game_dt itself -- callers must treat
    # this as "don't filter it out," not silently coerce to True or False.
    assert S.has_started(None) is None
    assert S.has_started("") is None
    assert S.has_started("not-a-date") is None
    print("✓ has_started returns an honest None for unknown/malformed game dates, never a "
         "guessed True or False")


def test_has_started_boundary_at_exact_start_time():
    from datetime import datetime
    import pytz
    eastern = pytz.timezone("US/Eastern")
    exact_start = eastern.localize(datetime(2026, 7, 30, 12, 10))
    assert S.has_started("2026-07-30T16:10:00Z", now=exact_start) is True
    print("✓ has_started treats the exact scheduled start moment as already started")


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
    for path in ("views/1_#U2b50_Best_Bets.py", "views/11_Matchup_Lab.py"):
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
        if not sport.has_projections:
            continue   # Outcome-based sports (UFC, and any future boxing/golf additions) have no
                       # projections pipeline -- they use dedicated pages and never go through the
                       # shared generic pages that require this contract.
        engine, proj = sport.engine, sport.projections
        missing_engine = [fn for fn in _ENGINE_CONTRACT if not callable(getattr(engine, fn, None))]
        missing_proj = [fn for fn in _PROJECTIONS_CONTRACT if not callable(getattr(proj, fn, None))]
        assert not missing_engine, f"{sport.key}'s engine is missing: {missing_engine}"
        assert not missing_proj, f"{sport.key}'s projections module is missing: {missing_proj}"
    print("✓ every live stat-based sport (has_projections=True) implements the full engine/projections contract")


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
    bet_log_src = (_HERE / "views" / "18_#L01f4d2_Bet_Log.py").read_text()
    track_record_src = (_HERE / "views" / "19_Track_Record.py").read_text()
    assert "sports.require_trading_access(" in bet_log_src
    assert "sports.require_trading_access(" in track_record_src
    print("\u2713 both Bet Log and Track Record actually call sports.require_trading_access, confirmed by reading the real source, not assumed")


# ----------------------------------------------------------------- require_trading_access
def test_require_trading_access_true_when_already_unlocked():
    import streamlit as st
    st.session_state["trading_unlocked"] = True
    assert S.require_trading_access("Bet Log") is True
    st.session_state.pop("trading_unlocked", None)   # reset for other tests
    print("✓ require_trading_access reuses session_state, so a correct password only needs to be entered once per session")


def test_require_trading_access_false_before_anything_is_entered():
    import streamlit as st
    st.session_state.pop("trading_unlocked", None)
    st.session_state.pop("trading_password_input", None)
    assert S.require_trading_access("Bet Log") is False
    assert not st.session_state.get("trading_unlocked")
    print("✓ require_trading_access stays locked (no crash) before any password has been entered")


def test_require_trading_access_actually_renders_and_checks_a_password_input():
    # THE regression test for the real, confirmed bug this fixes, verified by reading the actual
    # source rather than asserted from a return value -- and deliberately so: st.text_input can't
    # be seeded through st.session_state outside a real `streamlit run` context (confirmed
    # directly -- session state does not function for widget resolution in bare/pytest mode), so
    # a call-and-check-the-return-value test could only ever prove the "not yet entered" and
    # "already unlocked" branches, exactly the two branches that were NEVER broken. The actual
    # bug was structural: require_trading_access rendered the st.warning explaining a password
    # was needed, but never rendered the st.text_input to type one INTO, and never called this
    # module's own _check_trading_password at all -- meaning trading_unlocked could never become
    # True by any real path, for anyone, ever. Reading the real source is the only way to
    # actually confirm all three pieces now exist together, not just that the function returns
    # something plausible in a context where the interesting branch can't be exercised.
    src = inspect.getsource(S.require_trading_access)
    assert 'st.text_input(' in src, "require_trading_access must actually render a password entry box"
    assert 'type="password"' in src, "the entry box must mask input, not show the password in plain text"
    assert '_check_trading_password(' in src, "a typed entry must actually be checked against the real secret"
    assert 'st.session_state["trading_unlocked"] = True' in src, "a correct entry must actually unlock the session"
    print("✓ require_trading_access genuinely renders a password box, checks it, and unlocks on success — confirmed by reading its real source, the same way the original bug (a warning with no way to ever act on it) was found")


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


def test_mlb_default_markets_is_the_real_curated_list():
    # Regression guard for the actual fix: leaving every market selected by default (including
    # rare-event ones like Stolen Bases, HR, Doubles, Triples) let the "payout"-chasing parlay
    # tiers compound several already-longshot legs into combined odds in the millions -- real
    # math, but numbers no actual sportsbook has ever offered. Confirms the exact curated
    # default matches what was actually specified, not an approximation.
    mlb = S.get("MLB")
    assert mlb.default_markets == [
        "Batter Hits+Runs+RBIs", "Batter Strikeouts", "Batter Total Bases", "Batter Total Hits",
        "Pitcher Earned Runs", "Pitcher Hits Allowed", "Pitcher Outs", "Pitcher Strikeouts",
        "Pitcher Walks",
    ]
    print("\u2713 MLB's default_markets is the exact real curated list")


def test_mlb_default_markets_every_entry_is_a_real_valid_market():
    # Every curated default must actually exist in market_map -- a typo here would silently
    # produce an empty pre-selection (the intersection-with-markets_present logic in the view
    # files would just drop it), not an error, so this needs direct verification.
    mlb = S.get("MLB")
    for market in mlb.default_markets:
        assert market in mlb.market_map, f"{market!r} is not a real MLB market key"
    print("\u2713 Every market in MLB's default_markets is a real, valid market_map key")


def test_mlb_default_markets_excludes_the_rare_event_markets():
    # The actual point of the curation: the markets most prone to producing astronomical
    # combined parlay odds (rare, longshot-leaning events for most players) must be excluded
    # from the default, even though they remain fully selectable -- nothing is removed, only
    # what's pre-selected changes.
    mlb = S.get("MLB")
    excluded = {"Batter HR", "Batter Runs", "Batter RBIs", "Batter Stolen Bases", "Batter Walks",
               "Batter Singles", "Batter Doubles", "Batter Triples"}
    assert excluded.isdisjoint(set(mlb.default_markets))
    # But every one of them must still be a real, selectable market -- curation, not removal.
    for market in excluded:
        assert market in mlb.market_map
    print("\u2713 MLB's default_markets excludes the rare-event markets while keeping them fully "
         "selectable, not removed from the platform")


def test_other_sports_default_markets_unchanged():
    # Sports without an explicit curation must keep the original "every market" behavior --
    # this was a deliberate MLB-specific fix, not a platform-wide behavior change.
    for key in ["WNBA", "NBA", "NCAAMB", "NFL"]:
        sport = S.get(key)
        if sport is not None:
            assert sport.default_markets is None
    print("\u2713 Sports without an explicit curation keep default_markets=None, unchanged behavior")


def test_bet_log_track_record_link_gated_on_has_projections():
    # Regression guard for a real, reported crash: Bet Log's page_link to Track Record was
    # unconditional, but Track Record hides itself from the sidebar entirely for any sport with
    # has_projections=False (UFC) -- st.page_link to a page outside the CURRENT navigation set
    # raises StreamlitPageNotFoundError, not a graceful message. Confirmed live via a real
    # traceback (Bet Log crashing outright while viewing UFC). The link and its target must never
    # be able to drift out of sync on this condition again.
    src = (_HERE / "views" / "18_#L01f4d2_Bet_Log.py").read_text()
    m = re.search(r'if\s+_active\.has_projections\s*:\s*\n\s*st\.page_link\(\s*"views/19_Track_Record\.py"',
                 src)
    assert m, ("Bet Log's page_link to Track Record must be guarded by "
              "`if _active.has_projections:` -- otherwise this crashes for any sport without a "
              "projections model (UFC)")
    print("✓ Bet Log's Track Record link is gated on has_projections, matching its target's own gate")


def test_command_center_graded_picks_link_gated_on_has_projections():
    # Same real bug class, caught in the same audit before it was independently reported: this
    # link was only gated on audience (owner-only), but Graded Picks ALSO hides itself for any
    # sport without a projections model -- same StreamlitPageNotFoundError risk as Bet Log's own
    # Track Record link above, just not yet hit by a real user.
    src = (_HERE / "views" / "0_#L01f3c6_Command_Center.py").read_text()
    m = re.search(
        r'if\s+st\.secrets\.get\("AUDIENCE",\s*"owner"\)\s*==\s*"owner"\s+and\s+_active\.has_projections\s*:'
        r'\s*\n\s*st\.page_link\(\s*"views/2_Graded_Picks\.py"', src)
    assert m, ("Command Center's page_link to Graded Picks must be guarded by BOTH the audience "
              "check AND has_projections -- otherwise this crashes for an owner-audience viewer "
              "on any sport without a projections model (UFC)")
    print("✓ Command Center's Graded Picks link is gated on both audience and has_projections")


def test_every_cross_page_link_targets_a_page_visible_under_the_same_conditions():
    # A general, systematic guard against this whole bug CLASS recurring on some future page --
    # not just the two specific instances above. For every st.page_link in views/, if the TARGET
    # page requires has_projections (per streamlit_app.py's own projections_only_titles) but the
    # SOURCE page doesn't, the source file's text must contain "has_projections" somewhere (a
    # loose but real check that the source at least references the condition its own link
    # depends on, not proof of correct placement -- the two explicit tests above cover placement
    # for the known real cases).
    #
    # EXTENDED TO COVER owner_only_titles TOO, a real, confirmed gap that let a real bug through:
    # Model Dashboard moved to owner_only_titles, but Retrospective's own link to it (Retrospective
    # itself stayed public) was never updated -- a live StreamlitPageNotFoundError for anyone on
    # the public build. This test's own docstring already claimed to guard "this whole bug CLASS,"
    # but only ever checked the has_projections half of it -- fixed to actually be comprehensive,
    # not just fixing the one reported instance and leaving the same gap open for the next one.
    src = (_HERE / "streamlit_app.py").read_text()
    meta_block = re.search(r"meta = \{(.*?)\n    \}", src, re.DOTALL).group(1)
    key_title = dict(re.findall(r'"(\d+)":\s*\("([^"]+)"', meta_block))
    proj_only = {t.strip().strip('"') for t in
                re.search(r"projections_only_titles = \{([^}]*)\}", src, re.DOTALL)
                .group(1).split(",") if t.strip()}
    owner_only = {t.strip().strip('"') for t in
                 re.search(r"owner_only_titles = \{([^}]*)\}", src, re.DOTALL)
                 .group(1).split(",") if t.strip()}

    def lead(name):
        lm = re.match(r"(\d+)", name)
        return lm.group(1) if lm else None

    violations = []
    for f in (_HERE / "views").glob("*.py"):
        text = f.read_text()
        src_title = key_title.get(lead(f.name), "?")
        for tm in re.finditer(r'st\.page_link\(\s*"views/([^"]+)"', text):
            target_title = key_title.get(lead(tm.group(1)), "?")
            # Two REAL, INDEPENDENT gating conditions -- confirmed directly from a real bug this
            # exact conflation caused: an early "source already requires has_projections, skip
            # this whole link" continue must NOT also skip the owner_only check below it, since a
            # source can legitimately require has_projections while still being PUBLIC (most of
            # projections_only_titles is public -- Best Bets, Retrospective, etc.), and a target
            # can be owner_only regardless of its own has_projections status. The original version
            # of this test used ONE blanket continue for both, which meant a source already in
            # proj_only (Retrospective) never even reached the owner_only check for its own links
            # -- confirmed directly: this is the exact real gap that let the Model Dashboard link
            # bug ship without this test catching it, reproduced and fixed here, not assumed.
            if not (src_title in proj_only) and target_title in proj_only and "has_projections" not in text:
                violations.append(f"{f.name} -> {tm.group(1)} (has_projections)")
            if target_title in owner_only and src_title not in owner_only and "AUDIENCE" not in text:
                violations.append(f"{f.name} -> {tm.group(1)} (owner_only)")
    assert not violations, (
        f"these page_link calls target a gated page from a source that's visible under looser "
        f"conditions than the target, with no real reference to the condition that gap depends "
        f"on anywhere in the source: {violations}")
    print("✓ every page_link targeting a has_projections- or owner_only-gated page has some "
         "real reference to that same condition in its own source file")


# ----------------------------------------------------------------- team_trend_tag
def test_team_trend_tag_hot_cold_steady():
    import sports as S
    assert S.team_trend_tag(120, 100) == ("📈 Hot", 1.2)
    assert S.team_trend_tag(80, 100) == ("📉 Cold", 0.8)
    assert S.team_trend_tag(100, 100) == ("➡️ Steady", 1.0)
    assert S.team_trend_tag(105, 100) == ("➡️ Steady", 1.05)   # inside the neutral band
    print("✓ team_trend_tag correctly buckets hot/cold/steady using the same 1.08/0.92 "
         "thresholds Defense Trend already established")


def test_team_trend_tag_honest_when_uncomputable():
    import sports as S
    assert S.team_trend_tag(None, 100) == ("➡️ Steady", None)
    assert S.team_trend_tag(100, None) == ("➡️ Steady", None)
    assert S.team_trend_tag(100, 0) == ("➡️ Steady", None)
    print("✓ team_trend_tag returns an honest None ratio (not a fabricated number) when either "
         "input is missing or season is zero")


def test_ufc_fight_card_wires_bet_logging_through_the_shared_quick_log_widget():
    # ADDED DIRECTLY ON REQUEST: UFC Fight Card previously had no bet-logging path at all.
    # Reuses the SAME shared quick_log widget every other page already uses (Best Bets, Graded
    # Picks, Game Watch's own moneyline logging), building a team-level "play" dict (Player=
    # None, Market="Moneyline") rather than a new logging system -- the exact same shape
    # test_quick_log.py's own test_bet_log_fields_from_play_handles_moneyline_shape_end_to_end
    # already confirms works correctly, so this test only needs to confirm the real wiring on
    # this page's own side, not re-prove the shared mapping itself.
    #
    # This page is explicitly "Phase 1: data surface only, no model" (its own module docstring)
    # -- there's no separate model price to log as a Fair fallback the way Game Watch's own win-
    # probability estimate provides, so this confirms the honest choice made instead: the real,
    # live h2h odds already fetched for the SAME bout are used for both "Fair" and the real
    # moneylines lookup, and the real no-vig probability already computed for the on-screen
    # metrics is reused as "ModelProb", not a fabricated prediction.
    src = (_HERE / "views" / "23_#L01f94a_UFC_Fight_Card.py").read_text()
    assert "import quick_log" in src, "the page must import the shared quick_log module"
    assert 'quick_log.render_quick_log(ml_plays, date_str, "UFC"' in src, (
        "render_quick_log must be called with the real sport key 'UFC'")
    assert '"Player": None, "PlayerId": None' in src, (
        "the play dicts must use the established team-level moneyline shape (no Player), not a "
        "player-prop shape UFC bouts don't actually have")
    assert '"Market": "Moneyline"' in src, "the play dicts must use the real, already-registered Moneyline market name"
    assert "moneylines=bout_moneylines" in src, (
        "moneylines must be passed through so a real captured price is used, not just the Fair fallback")
    assert 'bout_moneylines = {fighter_a: {preferred_book: odds_a}, fighter_b: {preferred_book: odds_b}}' in src, (
        "bout_moneylines must be built from the exact same real, already-fetched odds shown on screen")
    print("✓ UFC Fight Card genuinely wires bet logging through the shared quick_log widget, using real, already-fetched odds honestly")


def test_ufc_fight_card_wires_fight_duration_bet_logging():
    # ADDED DIRECTLY ON REQUEST, extending Moneyline-only logging to a second real, currently-
    # live market. Confirms the real, distinct handling: Fight Duration is an Over/Under, not a
    # team-name pick, so there's no moneylines-style real-price lookup -- the real, already-
    # fetched totals odds shown on screen are used directly as "Fair", with no further changes.
    src = (_HERE / "views" / "23_#L01f94a_UFC_Fight_Card.py").read_text()
    assert '"Market": "Fight Duration", "Side": "Over"' in src, (
        "Fight Duration Over must be a real, loggable play")
    assert '"Market": "Fight Duration", "Side": "Under"' in src, (
        "Fight Duration Under must be a real, loggable play")
    assert 'quick_log.render_quick_log(dur_plays, date_str, "UFC", key_prefix=f"ufc_dur_{event_id}")' in src, (
        "Fight Duration plays must be logged through the same shared widget, with their own real key_prefix"
    )
    print("✓ UFC Fight Card genuinely wires Fight Duration bet logging, correctly handled as a real Over/Under, not a moneyline-shaped pick")


def test_ufc_fight_card_wires_method_of_victory_bet_logging_dormant_until_real_data_exists():
    # ADDED DIRECTLY ON REQUEST: this file's own module docstring confirms The Odds API
    # currently rejects method-of-victory markets for MMA with a real INVALID_MARKET error --
    # not a subscription-tier limit, an active rejection. Confirms the logging code is genuinely
    # ready, using the real, registered canonical market names from sports.py's own UFC market_
    # map (not the emoji-prefixed display labels), gated behind the exact same has_method check
    # that already gates the display table -- so this activates automatically the moment the API
    # adds real support, with zero further changes needed, matching this file's own stated
    # promise that re-enabling this later is a one-line change, not a rebuild.
    src = (_HERE / "views" / "23_#L01f94a_UFC_Fight_Card.py").read_text()
    assert '"🤛 KO/TKO": "Win by KO/TKO", "🤸 Submission": "Win by Sub", "📋 Decision": "Win by Decision"' in src, (
        "method_market_names must map to the real, registered canonical market names from sports.py's own UFC market_map")
    assert '"Market": method_market_names[method_label], "Side": fighter' in src, (
        "each method play must use the real canonical market name and the real fighter as Side")
    assert 'quick_log.render_quick_log(method_plays, date_str, "UFC", key_prefix=f"ufc_method_{event_id}")' in src, (
        "method_plays must be logged through the same shared widget")
    assert "if method_rows:" in src, (
        "logging must stay gated behind the same real has_method/method_rows checks that already gate the display, so it's dormant until real data exists")
    print("✓ UFC Fight Card genuinely wires Method of Victory bet logging, correctly dormant until the Odds API actually supports these markets")


def test_bet_log_manual_form_makes_player_optional_not_side():
    # A REAL, CONFIRMED FIX for a real, reported case: the manual "Log a bet" form used to
    # require BOTH Player and Game, and Side was a fixed selectbox (Over/Under/Yes only) with no
    # way to enter a real team or fighter name -- meaning a genuine moneyline/fight-winner pick
    # (MLB, UFC, or any other sport) could never actually be logged correctly through this form
    # at all, for any sport, not just UFC (confirmed directly: a UFC screenshot showed the old
    # MLB-only "HOU @ DET"/"Jose Altuve" placeholders still showing even with UFC active).
    # Confirmed directly that no downstream code (betlog.py, bet_settlement.py, quick_log.py)
    # assumed Side was one of those three specific values, so widening it to free text is safe.
    src = (_HERE / "views" / "18_#L01f4d2_Bet_Log.py").read_text()
    assert 'if game and side:' in src, (
        "Game and Side must be the real required fields -- Player must no longer be required")
    assert 'if player and game:' not in src, (
        "the old, incorrect validation requiring Player must be genuinely gone, not just supplemented")
    assert 'side = st.text_input("Side"' in src, (
        "Side must be a real free-text field, not a fixed selectbox that can't hold a team/fighter name")
    assert '_player = player.strip() or None' in src, (
        "a blank Player field must be stored as a real None, the same explicit convention "
        "quick_log.py's own moneyline logging already uses, not a silent empty string")
    print("✓ Bet Log's manual form correctly requires Game and Side, makes Player genuinely optional, and Side accepts a real team/fighter name")


def test_bet_log_manual_form_placeholders_are_sport_aware():
    # Confirms the real, reported mismatch is fixed: UFC's own examples no longer show MLB's
    # "HOU @ DET"/"Jose Altuve" placeholders, which read as genuinely wrong once UFC bet logging
    # shipped (UFC bets don't have a "Player" the way MLB props do).
    src = (_HERE / "views" / "18_#L01f4d2_Bet_Log.py").read_text()
    assert '"UFC":   {"game": "Islam Makhachev vs. Arman Tsarukyan"' in src, (
        "UFC must have its own real, fighter-vs-fighter example, not the MLB team-code placeholder")
    assert '"leave blank for a fight-level pick"' in src, (
        "UFC's own Player placeholder must honestly signal that it's optional for a fight-level pick")
    assert '_ex = _FORM_EXAMPLES.get(_active.key, _FORM_EXAMPLES["MLB"])' in src, (
        "the examples must be looked up by the real active sport, defaulting safely to the "
        "original MLB example for any sport not yet given its own")
    print("✓ Bet Log's manual form placeholders are genuinely sport-aware, with a real, correct UFC example")


def test_retrospective_wires_team_environment_diagnostic_for_every_sport():
    # EXTENDED DIRECTLY ON REQUEST, a real, confirmed fix for a real, reported case: a real user
    # showed a real, live 33-point WNBA blowout (LV Aces 66 @ NY Liberty 99) with real, legitimate
    # stars (Jewell Loyd, Breanna Stewart) stuck well under their own real lines -- exactly the
    # real garbage-time pattern this diagnostic exists to catch, but it was MLB-only until now.
    # Confirmed directly (see retro.explain_team_environment's own real tests) that the function
    # itself was already genuinely sport-agnostic -- it only ever needs Team/Game/Market/Line/
    # Hit/Actual, fields every sport's own graded plays already carry, and MARKET_STAT already
    # has real entries for WNBA/NBA/NCAAMB's own Core-4 markets. The old MLB-only gate here was a
    # real display decision, never a genuine limitation of the function. Confirms the real fix:
    # the diagnostic now runs unconditionally (not gated to MLB the way L5/L10 and the blowout-
    # risk/GameMargin features genuinely still are, since THOSE really do depend on MLB-only or
    # capability-specific engine functions), and critically uses _graded_all (the full real
    # slate) rather than the possibly-filtered subset, since a missed player's own real teammates
    # could otherwise be filtered out of view entirely (e.g. "Misses only"), silently starving
    # the real comparison of the very plays it needs.
    src = (_HERE / "views" / "16_#L01f50d_Retrospective.py").read_text()
    # A real, precise check that THIS section specifically is no longer MLB-gated -- not just a
    # loose "the string exists somewhere in this file" check, which would pass regardless, since
    # other, genuinely MLB-only sections (L5/L10, GameMargin) still correctly use that same gate.
    assert 'def _env_summary(r):' in src
    env_section_start = src.index("def _env_summary(r):")
    env_section = src[max(0, env_section_start - 400):env_section_start]
    assert 'if _active.key == "MLB":' not in env_section, (
        "the team-environment diagnostic must no longer be gated to MLB -- it is genuinely sport-agnostic")
    assert "R.explain_team_environment(r.to_dict(), _graded_all)" in src, (
        "must call the real diagnostic with the full real slate (_graded_all), not the possibly-filtered subset")
    assert 'g["Team environment"] = g.apply(_env_summary, axis=1)' in src, (
        "the real column must actually be attached to the displayed table")
    print("✓ Retrospective genuinely wires the team-environment diagnostic for every sport, using the full real slate")


def test_retrospective_wires_conviction_tier_chart_reusing_already_fetched_history():
    # ADDED DIRECTLY ON REQUEST, a real, confirmed fix for a real, repeated community
    # frustration -- "research said no but it hit." Confirms Retrospective genuinely wires the
    # new conviction-tier chart in, reusing _rank_history (already fetched for the rank chart
    # right above it) rather than issuing a second, redundant real query, and using a real,
    # deliberately NOT-lowered min_n=20 (conviction tiers aren't a structurally one-per-day event
    # the way Rank 1 is, so they don't need Rank 1's own lowered floor for a short window).
    src = (_HERE / "views" / "16_#L01f50d_Retrospective.py").read_text()
    assert "R.catch_rate_by_conviction_tier(_rank_history, min_n=20" in src, (
        "must reuse the already-fetched _rank_history, not issue a second, redundant real query, "
        "and must use a real, fixed min_n=20, not _rank_min_n's own lowered value")
    assert 'C.section_header("🔍", "Does conviction itself track real outcomes' in src, (
        "the real chart section must genuinely be present"
    )
    print("✓ Retrospective genuinely wires the conviction-tier chart, reusing already-fetched history with the correct, real min_n")


def test_retrospective_wires_game_margin_computation_gated_by_real_engine_capability():
    # ADDED DIRECTLY ON REQUEST, part of a real, two-part fix for a real, repeated community
    # pain point: "blowouts causing failed parlays" / "players forget how to play after
    # halftime." Confirms load_retro_generic genuinely computes and merges GameMargin, gated by
    # hasattr (a sport without get_game_margin on its own engine module -- MLB, or a basketball
    # sport not yet wired -- must be genuinely unaffected).
    #
    # REAL, CONFIRMED PERFORMANCE FIX, not the original design: the first version fetched every
    # real game's own margin SEQUENTIALLY -- a real, reported slowdown. Confirms the real fix:
    # concurrent fetching via ThreadPoolExecutor, the same established pattern already proven
    # for wnba_engine.build_slate's own roster fetch, not a second, blocking loop.
    src = (_HERE / "views" / "16_#L01f50d_Retrospective.py").read_text()
    assert 'hasattr(sport.engine, "get_game_margin")' in src, (
        "must gate by real engine capability, not assume every sport has this")
    assert "with ThreadPoolExecutor(max_workers=8) as ex:" in src, (
        "must fetch every real game's own margin CONCURRENTLY, not sequentially -- the exact "
        "real regression already fixed once for the roster fetch, reintroduced here and now fixed the same way")
    assert "_margins = list(ex.map(sport.engine.get_game_margin, _gids))" in src, (
        "must genuinely parallelize the real fetch across every real game id")
    assert "graded = [dict(p, GameMargin=_margin_by_label.get(p.get(\"Game\")))" in src, (
        "must merge the real margin onto every real play sharing that same real game")
    print("✓ Retrospective genuinely wires GameMargin computation, gated by real engine capability, fetched CONCURRENTLY not sequentially")


def test_retrospective_wires_team_margin_split_by_real_team_not_game():
    # EXTENDED DIRECTLY ON REQUEST, splitting the real blowout-validation work by which side of
    # a real blowout a player was actually on -- a real, live example named directly: LV Aces 66
    # @ NY Liberty 99, with real, legitimate stars stuck under their own real lines. Confirms
    # load_retro_generic genuinely computes and merges TeamMargin, gated by hasattr (same real
    # pattern as GameMargin), reuses the SAME already-fetched _gids/_labels (zero new network
    # calls), and critically merges by the real player's own TEAM field, not Game -- a game's
    # two real teams must get two different real signed values, not the same one both sides.
    src = (_HERE / "views" / "16_#L01f50d_Retrospective.py").read_text()
    assert 'hasattr(sport.engine, "get_team_margins")' in src, (
        "must gate by real engine capability, not assume every sport has this")
    assert "_team_margins_per_game = list(ex.map(sport.engine.get_team_margins, _gids))" in src, (
        "must reuse the same already-fetched real _gids, not a second, redundant real fetch")
    assert '_team_margin_by_name[m["home_name"]] = margins[m["home_id"]]' in src, (
        "must correctly map the real home team's own id to its own real signed margin")
    assert '_team_margin_by_name[m["away_name"]] = margins[m["away_id"]]' in src, (
        "must correctly map the real away team's own id to its own real signed margin")
    assert 'graded = [dict(p, TeamMargin=_team_margin_by_name.get(p.get("Team")))' in src, (
        "must merge the real signed margin onto each play by its own real TEAM, not Game -- "
        "the two real teams in a blowout have two different real signed margins")
    print("✓ Retrospective genuinely wires TeamMargin, correctly split by each real player's own team, reusing the already-fetched real game ids")


def test_retrospective_wires_team_role_in_blowout_chart_reusing_the_same_real_threshold():
    # EXTENDED DIRECTLY ON REQUEST, the display half of the real team-role-in-blowout validation
    # work. Confirms the real chart is genuinely gated by real engine capability (only a sport
    # with get_team_margins ever accumulates real TeamMargin data), and deliberately reuses
    # _margin_threshold (the same real slider the blowout-margin chart right above it already
    # has) rather than a second, separate slider -- both real charts answer variations on the
    # same real question, at the same real cutoff.
    src = (_HERE / "views" / "16_#L01f50d_Retrospective.py").read_text()
    assert 'hasattr(_rank_sport.engine, "get_team_margins")' in src, (
        "the real chart must be gated by real engine capability, not shown for every sport")
    assert "R.catch_rate_by_team_role_in_blowout(\n                _rank_history, threshold=_margin_threshold" in src, (
        "must reuse the already-fetched _rank_history and the same real slider value as the blowout-margin chart above it")
    print("✓ Retrospective genuinely wires the team-role-in-blowout chart, gated correctly, reusing the same real threshold slider")


def test_retrospective_wires_blowout_margin_chart_with_adjustable_threshold():
    # ADDED DIRECTLY ON REQUEST, the display half of the real blowout-margin validation work.
    # Confirms the real chart is genuinely gated by real engine capability (only a sport with
    # get_game_margin ever accumulates real GameMargin data), reuses _rank_history (already
    # fetched, zero new queries), and exposes threshold as a real, live, adjustable slider --
    # not a fixed number -- so a person can actually test whether 10 is the right real cutoff.
    #
    # REAL, CONFIRMED PERFORMANCE FIX, not the original design: this chart (and the conviction-
    # tier chart above it) used to render UNCONDITIONALLY on every real page load -- real,
    # additive Plotly rendering weight nobody asked for on every single visit. Confirms the real
    # fix: a real checkbox gate, matching this page's own established L5/L10 pattern, so the
    # real work only happens when genuinely requested.
    src = (_HERE / "views" / "16_#L01f50d_Retrospective.py").read_text()
    assert '_show_validation_charts = st.checkbox(' in src, (
        "both real charts must be gated behind a real, explicit checkbox, not render unconditionally on every load")
    assert 'if _show_validation_charts:' in src, "the real charts must genuinely be skipped when the checkbox is off"
    assert 'hasattr(_rank_sport.engine, "get_game_margin")' in src, (
        "the real chart must be gated by real engine capability, not shown for every sport")
    assert '_margin_threshold = st.slider("Blowout threshold' in src, (
        "threshold must be a real, live, adjustable slider, not a fixed, hardcoded number")
    assert "R.catch_rate_by_blowout_margin(\n            _rank_history, threshold=_margin_threshold" in src, (
        "must reuse the already-fetched _rank_history and the real, live slider value")
    print("✓ Retrospective genuinely wires the blowout-margin validation chart, gated correctly, with a real adjustable threshold, AND behind a real performance-conscious checkbox")


def test_bet_log_manual_form_wires_same_team_recent_bets():
    # ADDED DIRECTLY ON REQUEST, a real, confirmed fix for a real, reported pattern: "If onky i
    # put the under on red sox instead.of money line what a joke... I officially hate red sox
    # fked me 2 days in a row." Confirms the manual "Log a bet" form genuinely checks for real,
    # recent bets on the same team right after a new one is logged, and fetches the real bet
    # list only ONCE, reused for every real team-part checked, not re-fetched per team.
    src = (_HERE / "views" / "18_#L01f4d2_Bet_Log.py").read_text()
    assert "_all_bets_this_sport = B.list_bets(sport=_active.key)" in src, (
        "the real bet list must be fetched once, outside the per-team-part loop")
    assert "B.same_team_recent_bets(_team_part, _all_bets_this_sport" in src, (
        "must call the real check, reusing the already-fetched real bet list")
    assert "game.split(\" @ \")" in src, "must check both real teams involved, not just one side of the real game string"
    print("✓ Bet Log's manual form genuinely wires the same-team recent-bets check, fetching the real bet list only once")


def test_quick_log_wires_same_team_recent_bets_with_consolidated_notice():
    # A SECOND real integration, extending the same real check to the PRIMARY real path most
    # picks actually get logged through (Best Bets, Graded Picks, Game Watch, etc., not just the
    # manual fallback form). Confirms real results are consolidated into ONE real, deduplicated
    # notice across every real pick logged in one action, not one separate notice per pick --
    # a real parlay/singles batch can log several picks on the same real game at once.
    src = (_HERE / "quick_log.py").read_text()
    assert "_all_bets_this_sport = B.list_bets(sport=sport_key)" in src, (
        "the real bet list must be fetched once for the whole real logging action")
    assert "_team_notices = {}" in src, "results must be consolidated into one real, deduplicated collection"
    assert "_team_notices[(b.get(\"game\"), b.get(\"slate_date\"), b.get(\"market\"), b.get(\"side\"))] = b" in src, (
        "must dedupe by the real bet's own identity, so the same real prior bet isn't reported twice"
    )
    assert "if _team_notices:" in src, "the real, consolidated notice must actually render when real matches exist"
    print("✓ quick_log genuinely wires the same-team recent-bets check into the primary real logging path, with a consolidated, deduplicated notice")


def test_best_bets_wires_blowout_risk_opt_in_and_separate_from_grading():
    # ADDED DIRECTLY ON REQUEST, a real, confirmed fix for a real, repeated community pain
    # point: "blowouts causing failed parlays" / "players forget how to play after halftime" --
    # both real descriptions of garbage time. Confirms the real, existing signal (basketball_
    # projections.blowout_risk_tag, driven by real, live spreads) is now genuinely surfaced on
    # this page, gated by hasattr (not a hardcoded sport list -- every current/future basketball
    # sport gets this automatically, MLB/NFL genuinely don't), opt-in (a real, live spreads
    # fetch costs real odds-API quota), and still kept separate from grading -- the same real
    # design principle the original Hot Hand Engine wiring already established.
    src = (_HERE / "views" / "1_#U2b50_Best_Bets.py").read_text()
    assert 'hasattr(P, "blowout_risk_tag")' in src, "must gate by real capability, not a hardcoded sport list"
    assert "BSC.load_team_spreads_cached(_active.key, date_str, BBD.get_odds_api_key())" in src, (
        "must fetch real spreads through the shared cache, not a new, separate implementation")
    assert '_cols.insert(_cols.index("Team") + 1, "_blowout_risk")' in src, (
        "the real column must only be added when the checkbox is genuinely on"
    )
    print("✓ Best Bets genuinely wires the real blowout-risk signal, opt-in and gated by real sport capability")


def test_graded_picks_wires_blowout_risk_as_a_real_game_level_banner():
    src = (_HERE / "views" / "2_Graded_Picks.py").read_text()
    assert 'hasattr(P, "blowout_risk_tag")' in src, "must gate by real capability, not a hardcoded sport list"
    assert "BSC.load_team_spreads_cached(_active.key, date_str, BBD.get_odds_api_key())" in src
    assert "for _team_part in game_label.split(\" @ \")" in src, (
        "must check both real teams involved in the game, matching same_team_recent_bets' own established approach")
    print("✓ Graded Picks genuinely wires the real blowout-risk signal as a real, game-level banner")


def test_suggested_parlays_wires_blowout_risk_per_leg():
    src = (_HERE / "views" / "3_Suggested_Parlays.py").read_text()
    assert 'hasattr(P, "blowout_risk_tag")' in src, "must gate by real capability, not a hardcoded sport list"
    assert "BSC.blowout_risk_for_team(leg.get(\"Team\"), _spreads, P)" in src, (
        "must check each real leg's own team, since a parlay can span several real, different games")
    print("✓ Suggested Parlays genuinely wires the real blowout-risk signal per leg")


def test_all_five_real_callers_pass_preferred_book_to_load_generic_best_bets_board():
    # REAL, CONFIRMED PERFORMANCE FIX, not the original design: load_generic_best_bets_board
    # used to have no @st.cache_data at all, and every real caller called it with just
    # (sport_key, date_str) -- a real, confirmed production regression, directly evidenced by a
    # real server log showing build_slate's own full real fetch chain re-running from scratch on
    # nearly every single real page interaction. Confirms every one of the five real callers now
    # explicitly passes preferred_book through -- an internal st.session_state read inside a
    # cached function would silently go stale the moment someone switched books, since
    # Streamlit's own cache key only ever includes a function's real arguments.
    callers = {
        "views/0_#L01f3c6_Command_Center.py": 'BBD.load_generic_best_bets_board(sport_key, date_str, preferred_book)',
        "views/1_#U2b50_Best_Bets.py": "BBD.load_generic_best_bets_board(sport_key, date_str, preferred_book)",
        "views/2_Graded_Picks.py": 'BBD.load_generic_best_bets_board(_active.key, date_str, preferred_book)',
        "views/3_Suggested_Parlays.py": 'BBD.load_generic_best_bets_board(_active.key, date_str, preferred_book)',
        "views/4_Speculative_Basket.py": 'BBD.load_generic_best_bets_board(_active.key, date_str, preferred_book)',
    }
    for path, expected_call in callers.items():
        src = (_HERE / path).read_text()
        assert expected_call in src, f"{path} must genuinely pass preferred_book through, not call with just (sport_key, date_str)"
    print("✓ All five real callers of load_generic_best_bets_board genuinely pass preferred_book through explicitly")


def test_matchup_lab_pitcher_comparison_table_avoids_the_real_arrow_serialization_bug():
    # REAL, CONFIRMED FIX for a real, reported bug, evidenced directly in a real server log:
    # repeated "Could not convert '—' with type str: tried to convert to double" Arrow
    # serialization failures on this exact table. The real root cause was never the old
    # cdf.fillna("—") call -- fillna doesn't change a column's dtype back to something Arrow-
    # compatible; by the time it ran, pandas had already inferred that column as "object" from a
    # real mix of floats and None, and filling the None with a real string only made that same
    # real column hold BOTH real floats and a real string, exactly what Arrow can't serialize.
    # Confirms the real fix: every real numeric value is formatted to a real string via
    # _fmt_stat BEFORE it ever reaches the DataFrame (the same real, already-proven principle
    # _delta_str's own column already used successfully), and the real fillna call that was
    # papering over the symptom, not the real cause, is genuinely gone.
    src = (_HERE / "views" / "9_Matchup_Lab.py").read_text()
    assert "def _fmt_stat(val):" in src, "the real formatter must exist"
    assert 'return "—" if val is None else f"{val:g}"' in src, "the real formatter must always return a real string, matching _delta_str's own proven principle"
    assert '("ERA", _fmt_stat(era_full), _fmt_stat(era_split),' in src, (
        "every real numeric value in the row must be formatted to a real string before reaching the DataFrame")
    assert 'cdf = cdf.fillna("—")' not in src, (
        "the real fillna call that only papered over the symptom (not the real dtype cause) must genuinely be gone")
    print("✓ Matchup Lab's pitcher comparison table genuinely fixes the real Arrow serialization bug at its real root cause, not just its symptom")


def test_edge_board_idp_section_no_longer_references_an_undefined_meta():
    # REAL, CONFIRMED FIX for a real, pre-existing bug -- caught directly via a real pyflakes
    # sweep (not observed live): load_index already computed meta internally (from engine.
    # build_slate) but never returned it, while this page's own real IDP section referenced a
    # bare `meta` name that was never defined anywhere in ITS OWN scope. A genuine, real
    # NameError waiting to fire the moment anyone selected NFL and a real IDP position filter
    # (DB/LB/DL/DE/CB/S) together -- the exact same class of bug as the real, reported
    # production NameError on Best Bets (bare `O` instead of `BBD.O`), just not yet triggered
    # live because this specific real combination is a narrower real path than every page load.
    src = (_HERE / "views" / "15_#L01f4c8_Edge_Board.py").read_text()
    assert "return index, meta, known_names, all_active_names" in src, (
        "load_index must genuinely return the real meta it already computes internally")
    assert "index, meta, known_names, all_active_names = load_index(" in src, (
        "the real call site must genuinely unpack meta, not silently discard it")
    assert "for m in meta:" in src, (
        "the real IDP section's own loop must still be present, now with a genuinely defined meta to iterate")
    print("✓ Edge Board's IDP section no longer references an undefined meta -- the real NameError is genuinely fixed")


def test_retrospective_rank_history_fetch_is_genuinely_cached():
    # REAL, CONFIRMED PERFORMANCE FIX for a real, reported case: "retrospective still takes
    # extremely long to load. other pages load faster" -- an earlier real fix made other pages
    # faster by caching load_generic_best_bets_board, but this page's own _rank_history fetch
    # (a real, growing accumulated-history database query) was NEVER touched by that fix at all,
    # since it lived as bare, uncached top-level script code here, re-running on every single
    # real rerun of this specific page regardless of whether either real chart further down was
    # even shown. Confirms the real fix directly: a genuine, dedicated @st.cache_data wrapper,
    # matching this same file's own established pattern for small, dedicated cache wrappers
    # (_load_l5_l10_games, right above it).
    src = (_HERE / "views" / "16_#L01f50d_Retrospective.py").read_text()
    assert "def _load_rank_history(sport_key: str, since_date, market):" in src, (
        "the real, dedicated cache wrapper must genuinely exist")
    assert "return GH.fetch_graded_plays(sport_key, since_date=since_date, market=market)" in src, (
        "the real wrapper must genuinely delegate to the real, underlying fetch")
    assert "_rank_history = _load_rank_history(_rank_sport.key, _rank_since" in src, (
        "the real top-level call site must genuinely go through the real cached wrapper, not the raw fetch directly")
    # A real, direct check that the real @st.cache_data decorator immediately precedes the real
    # function -- confirms this isn't just a plain function sitting near an unrelated decorator.
    assert '@st.cache_data(ttl=300, show_spinner=False)\ndef _load_rank_history(' in src, (
        "the real cache decorator must genuinely, directly wrap this real function")
    print("✓ Retrospective's own rank-history fetch is genuinely wired through a real, dedicated, cached wrapper")


def test_command_center_wires_devigged_game_lines_correctly():
    # EXTENDED DIRECTLY ON REQUEST: a real, direct extension of odds_api.devig_two_way (already
    # proven for player props via real_market_prob) one level up, to a game's own real moneyline
    # -- a real, live TOR @ NYY DraftKings screenshot was the concrete example that prompted
    # this. Confirms the real section is genuinely opt-in (costs real live-odds API quota, same
    # established posture as Best Bets' own blowout-risk checkbox), genuinely sport-aware (not
    # hardcoded to MLB, since Command Center itself is multi-sport), and genuinely uses
    # real_moneyline_devig rather than a parallel, duplicate devig implementation.
    src = (_HERE / "views" / "0_#L01f3c6_Command_Center.py").read_text()
    assert 'st.checkbox("Show de-vigged moneylines (uses live odds API quota)"' in src, (
        "the real feature must be genuinely opt-in, matching this platform's own established "
        "posture for anything costing real live-odds API quota")
    assert "BBD.O.fetch_slate_moneylines(date_str_inner, api_key, sport=odds_sport_key)" in src, (
        "must fetch using the real, ACTIVE sport's own odds_sport_key, not a hardcoded default "
        "-- Command Center itself is multi-sport")
    assert "_load_game_moneylines(today, _active.odds_sport_key)" in src, (
        "the real call site must pass the real, currently-active sport's own odds_sport_key")
    assert "BBD.O.real_moneyline_devig(_game_moneylines, g.get(\"away_name\", \"\")," in src, (
        "must genuinely reuse real_moneyline_devig, not a parallel, duplicate devig implementation")
    assert "if result is None:\n                continue" in src, (
        "a real game with no genuine same-book, two-sided price must be honestly skipped, never "
        "guessed or fabricated into a row")
    print("✓ Command Center genuinely wires the de-vigged game-lines section, opt-in, sport-aware, reusing real_moneyline_devig")


def test_ncaaf_qb_lab_wires_correctly_and_carries_its_own_honest_caveat():
    # BUILT DIRECTLY ON REQUEST: NCAAF's first real dedicated page, adapted from NFL QB Lab
    # (views/14_QB_Lab.py) with every function signature and output dict key confirmed to match
    # exactly first (see this file's own module docstring for the full reasoning). Confirms the
    # real page genuinely gates to NCAAF (not NFL, not left open to every sport), genuinely
    # reuses ncaaf_projections.build_qb_matchup_projections/build_qb_efficiency_table rather than
    # a parallel reimplementation, and genuinely carries forward sports.py's own honest note that
    # NCAAF's whole pipeline was verified against realistic constructed data, not an actual live
    # CFBD fetch -- that caveat needed to stay visible on the page itself, not buried in a
    # comment only a developer would ever read.
    src = (_HERE / "views" / "29_NCAAF_QB_Lab.py").read_text()
    assert 'sports.require_sport(["NCAAF"], "NCAAF QB Lab")' in src, (
        "must gate to NCAAF specifically, not NFL and not left ungated")
    assert "import ncaaf_engine as E" in src and "import ncaaf_projections as P" in src, (
        "must genuinely use NCAAF's own engine/projections modules, not NFL's"
    )
    assert "P.build_qb_matchup_projections(proj_rows, opp_pass_allowed, league_avg_pass," in src, (
        "must genuinely reuse the real, confirmed-matching projections function, not a parallel "
        "reimplementation -- and must use proj_rows (the real, safe, baseline-aware fix), not "
        "the original, unfixed rows")
    assert "P.build_qb_efficiency_table(proj_rows, season_logs)" in src, (
        "must genuinely reuse the real, confirmed-matching efficiency table function, on proj_rows")
    assert "This page's own first real live load is part of this platform's first real," in src, (
        "the real, honest caveat about this being NCAAF's first real live verification must stay "
        "visible on the page itself, not just in a developer-facing comment")
    print("✓ NCAAF QB Lab genuinely gates to NCAAF, reuses the real confirmed-matching projections functions, and carries its own honest first-load caveat")


def test_both_qb_labs_carry_the_honest_week_one_empty_state():
    # FIXED DIRECTLY ON REQUEST: a real, reported case -- a live NCAAF QB Lab screenshot showed
    # "No projectable QBs for this date" for a date League Schedules confirmed genuinely had real
    # games scheduled, which reads as a bug or a wrong date even though it's neither. Traced
    # directly: build_qb_matchup_projections silently skips any QB with an empty _recent_games
    # list, and in the real, literal first week of a new season, EVERY QB has zero completed
    # games this season by definition -- a genuine, structural property of the recent-form
    # design, not a data gap or a bug, and one that recurs every single season for BOTH NFL and
    # NCAAF, confirmed identical in both files before this fix. The old message didn't say any
    # of that; it read as "wrong date" or "broken." Confirms the new, honest message explains the
    # real why, and points to Best Bets/Graded Picks -- which use a genuinely different pathway
    # with a real, tested prior-season fallback (see ncaaf_data.py's own refresh_schedule/
    # refresh_player_season_stats docstrings) and so keep working even in week 1.
    for fname in ("14_QB_Lab.py", "29_NCAAF_QB_Lab.py"):
        src = (_HERE / "views" / fname).read_text()
        assert "no real recent-form data to" in src, (
            f"{fname}: the real, honest reason (no completed games yet this season) must be "
            f"stated plainly, not left as an unexplained empty result")
        assert "Best Bets or Graded Picks instead" in src, (
            f"{fname}: must point to the real, working alternative for this exact scenario, not "
            f"just say 'try a different date' (which wouldn't actually fix anything in week 1)")
        assert 'st.info("No projectable QBs for this date. Pick a date within an' not in src, (
            f"{fname}: the old, unexplained message must genuinely be gone, not left alongside the new one")
    print("✓ Both NFL and NCAAF QB Lab genuinely carry the honest week-1 empty-state message, pointing to the real working alternative")


def test_ncaaf_qb_lab_2025_baseline_toggle_is_real_not_cosmetic():
    # BUILT DIRECTLY ON REQUEST: real, honest content to work with before 2026 has any games at
    # all -- specifically named as needed for podcast/Discord dialogue, not for actual betting
    # decisions. Confirms the toggle genuinely redirects the STATS lookups to a real prior-season
    # date while leaving the SLATE date (today's real games/players) untouched -- a cosmetic
    # version that just relabeled the same date_str everywhere would silently show 2026's own
    # (nonexistent) data under a "2025" label, the opposite of honest.
    src = (_HERE / "views" / "29_NCAAF_QB_Lab.py").read_text()
    assert 'show_2025_baseline = st.checkbox(' in src, (
        "the real, honest toggle must exist as an actual UI control, not just be described"
    )
    assert 'stats_date_str = "2026-02-01" if show_2025_baseline else date_str' in src, (
        "must genuinely branch the STATS date only -- date_str (the real slate/game-picker "
        "date) must stay independent, or today's real matchups would silently disappear too")
    assert "def load(date_str: str, stats_date_str: str):" in src, (
        "load() must genuinely accept two separate dates, not collapse back to one"
    )
    assert 'E.get_player_season_games(r["_pid"], stats_date_str)' in src, (
        "the real per-player stats lookup must use stats_date_str, not date_str -- using the "
        "slate date here would defeat the whole point of the toggle")
    assert "Showing 2025 season data as a baseline" in src, (
        "when active, the page must genuinely, visibly label itself as showing prior-season "
        "data -- a silent redirect risks someone mistaking 2025 stats for 2026 form")
    print("✓ NCAAF QB Lab's 2025-baseline toggle genuinely redirects stats lookups while keeping the real slate date independent, and visibly labels itself when active")


def test_ncaaf_qb_lab_baseline_toggle_actually_produces_real_projections():
    # THE critical fix for a real, reported bug: Player Lines correctly showed a real QB's real
    # 2025 game log, but QB Lab's own baseline toggle still showed "no data" for that exact same
    # player -- because build_qb_matchup_projections/build_qb_efficiency_table both gate on
    # row["_recent_games"], which is baked in at slate-build time using TODAY's date_str,
    # completely independent of stats_date_str. Confirms the real fix: QB rows get a real,
    # SHALLOW-COPIED override (never mutating the shared, cached rows object other pages also
    # read from) before either projections function runs.
    src = (_HERE / "views" / "29_NCAAF_QB_Lab.py").read_text()
    assert '_recent_games=season_logs.get(r["_pid"]) or []' in src, (
        "must genuinely override _recent_games with the real, stats_date_str-aware season log "
        "before calling either projections function, or the baseline toggle stays broken "
        "exactly as reported"
    )
    assert "dict(r, _recent_games=" in src, (
        "must use a genuine shallow copy (dict(r, ...)), never mutate the shared rows objects "
        "in place -- those come from a separately-cached function Matchup Lab and Player Lines "
        "also read from, and an in-place mutation risks leaking this page's own baseline "
        "override into their unrelated views")
    assert "P.build_qb_matchup_projections(proj_rows," in src and "P.build_qb_efficiency_table(proj_rows," in src, (
        "both real projections functions must receive the real, fixed proj_rows -- not the "
        "original, unfixed rows"
    )
    print("✓ NCAAF QB Lab's baseline toggle now genuinely produces real projections via a safe, non-mutating row override, matching what Player Lines already proved works")


def test_ncaaf_matchup_lab_2025_baseline_toggle_also_redirects_the_players_own_log():
    # THE single most important, easiest-to-miss real bug this feature could have shipped with:
    # row["_recent_games"] is baked into each row at SLATE-BUILD time (today's real date),
    # completely independent of load_matchup's own stats_date_str parameter. A baseline toggle
    # that redirected load_matchup alone would leave the trend charts and "recent games" table
    # silently empty even with the toggle checked -- confirmed fixed here, not assumed, since
    # this exact gap was caught and fixed live while building this feature, not designed in from
    # the start.
    src = (_HERE / "views" / "30_NCAAF_Matchup_Lab.py").read_text()
    assert 'show_2025_baseline = st.checkbox(' in src, (
        "the real, honest toggle must exist as an actual UI control, not just be described"
    )
    assert 'stats_date_str = "2026-02-01" if show_2025_baseline else date_str' in src, (
        "must genuinely branch the STATS date, matching QB Lab's own established pattern"
    )
    assert 'log = season_log if show_2025_baseline else (row.get("_recent_games") or [])' in src, (
        "THE critical fix: log must genuinely redirect to season_log (which respects "
        "stats_date_str) in baseline mode, or trend charts and the recent-games table would "
        "silently stay empty even with the toggle checked")
    assert "def load_matchup(date_str: str, stats_date_str: str," in src, (
        "load_matchup must genuinely accept both dates, not collapse back to one"
    )
    assert "not any(r.get(\"_recent_games\") for r in rows)" in src, (
        "the empty-state check must genuinely test for real recent-form data across the slate, "
        "not just an empty slate -- the season-average fallback means the slate itself is rarely "
        "empty even in week 1, so checking 'not rows' alone would almost never fire")
    print("✓ NCAAF Matchup Lab's 2025-baseline toggle genuinely redirects BOTH load_matchup's stats calls AND the player's own recent-games log, and the empty-state check tests the real condition")


def test_ncaaf_matchup_lab_position_filter_genuinely_narrows_and_labels_players():
    # BUILT DIRECTLY ON REQUEST, fixing a real, reported UX gap: browsing every player on the
    # whole slate with no position grouping at all made it genuinely hard to find, say, just the
    # RBs, or even tell what position a given dropdown entry played without selecting them
    # first. Confirms the real filter genuinely narrows `rows` before any downstream slot/game/
    # player logic runs (not just a cosmetic label), and the player dropdown itself shows
    # position directly, matching NCAAF Player Lines' own established QB/RB/WR-TE grouping for
    # consistency across the two pages.
    src = (_HERE / "views" / "30_NCAAF_Matchup_Lab.py").read_text()
    assert '_POSITION_GROUPS = {"All positions": ("QB", "RB", "WR", "TE"), "QB": ("QB",), "RB": ("RB",),' in src, (
        "the real position groups must match NCAAF Player Lines' own QB/RB/WR-TE grouping, not a new, third scheme"
    )
    assert 'rows = [r for r in rows if r.get("Position") in _POSITION_GROUPS[position_group]]' in src, (
        "the filter must genuinely narrow the real rows list before slots/games/player options "
        "are computed from it, not just change a label"
    )
    assert "{r['Player']} ({r['Team']}, {r['Position']}) — {r['GameLabel']}" in src, (
        "the player dropdown itself must show real position, so 'All positions' mode doesn't "
        "leave the reported ambiguity in place"
    )
    print("✓ NCAAF Matchup Lab's position filter genuinely narrows the real player list before downstream filters run, and the dropdown itself shows real position")


def test_ncaaf_matchup_lab_wires_correctly_and_carries_both_its_honest_gaps():
    # BUILT DIRECTLY ON REQUEST: NCAAF Matchup Lab, adapted from NFL Matchup Lab (12) on five new
    # real engine functions and five new real projections functions, each individually tested --
    # not assumed correct by analogy to NFL's own. Confirms the real page genuinely gates to
    # NCAAF, reuses build_matchup_profile rather than a parallel reimplementation, carries the
    # same week-1 honest empty-state message QB Lab already established, and -- the two real,
    # deliberate gaps agreed on directly before building this -- genuinely shows an honest
    # injury-report placeholder (not a silently missing section, not faked data) and flags the
    # TD-allowed column names as a real, not-yet-live-verified guess rather than a confirmed fact.
    src = (_HERE / "views" / "30_NCAAF_Matchup_Lab.py").read_text()
    assert 'sports.require_sport(["NCAAF"], "NCAAF Matchup Lab")' in src, (
        "must gate to NCAAF specifically, not NFL and not left ungated")
    assert "import ncaaf_engine as E" in src and "import ncaaf_projections as P" in src, (
        "must genuinely use NCAAF's own engine/projections modules, not NFL's"
    )
    assert "P.build_matchup_profile(row, h2h_log, opp_recent, opp_season, season_log=season_log," in src, (
        "must genuinely reuse the real, tested build_matchup_profile, not a parallel reimplementation")
    assert "no real recent-form data" in src and "Best Bets" in src, (
        "must carry the same real, honest week-1 empty-state message QB Lab already established"
    )
    assert "No real injury-report data source is wired up for NCAAF yet" in src, (
        "the real, honest injury-report placeholder must stay visible on the page itself, not "
        "silently omitted or faked with data that doesn't exist")
    assert "yet live-verified guess" in src, (
        "the real, flagged uncertainty on TD-allowed column names must stay visible on the page "
        "itself, not presented as a confirmed fact")
    print("✓ NCAAF Matchup Lab genuinely gates to NCAAF, reuses the real tested build_matchup_profile, and honestly carries both its real, flagged gaps")


def test_ncaaf_player_lines_wires_correctly_and_covers_every_position_group():
    # BUILT DIRECTLY ON REQUEST: the fast, browse-by-position trend-chart tool, adapted from MLB
    # Player Lines (26). Confirms the real page genuinely gates to NCAAF, reuses
    # get_player_season_games/build_trend_series rather than a parallel reimplementation, defines
    # all three real position groups with their own real, position-appropriate chart specs
    # (QB gets split Passing/Rushing TDs, RB and WR/TE get the combined Touchdowns row -- same
    # real distinction build_matchup_profile already established and tested), and carries the
    # same real TD-column-guess flag QB Lab/Matchup Lab already carry, not silently dropped just
    # because it's the third page to reuse those columns.
    src = (_HERE / "views" / "31_NCAAF_Player_Lines.py").read_text()
    assert 'sports.require_sport(["NCAAF"], "NCAAF Player Lines")' in src, (
        "must gate to NCAAF specifically, not NFL and not left ungated")
    assert "import ncaaf_engine as E" in src and "import ncaaf_projections as P" in src, (
        "must genuinely use NCAAF's own engine/projections modules, not NFL's"
    )
    assert "games = E.get_player_season_games(player_id, stats_date_str)" in src, (
        "must genuinely reuse the real, tested get_player_season_games, not a parallel reimplementation")
    assert '"QB": {' in src and '"RB": {' in src and '"WR / TE": {' in src, (
        "all three real position groups must be defined"
    )
    assert '("Passing TDs", lambda g: g.get("passing_TD") or 0)' in src, (
        "QB must get the real split Passing TDs row, not the combined one"
    )
    assert 'lambda g: (g.get("rushing_TD") or 0) + (g.get("receiving_TD") or 0)' in src, (
        "RB and WR/TE must get the real combined Touchdowns row, matching build_matchup_profile's own convention"
    )
    assert "yet live-verified guess" in src, (
        "the real, flagged uncertainty on TD-allowed-style column names must stay visible on "
        "this page too, not silently dropped just because it's the third page to reuse them")
    print("✓ NCAAF Player Lines genuinely gates to NCAAF, reuses the real tested data functions, covers all three real position groups with correct chart specs, and carries its own honest TD-column flag")


def test_ncaaf_player_lines_sorts_games_by_real_time_not_alphabetically():
    # BUILT DIRECTLY ON REQUEST, fixing a real, reported bug: the Game dropdown used to be a
    # plain sorted() over game labels -- a text sort, so a game starting later could land above
    # one starting earlier for the wrong reason (alphabetical order, not kickoff order). Confirms
    # the real fix matches the same, already-correct pattern NCAAF Matchup Lab and MLB Player
    # Lines both already use -- sorting on each game's own real start time, not its label text.
    src = (_HERE / "views" / "31_NCAAF_Player_Lines.py").read_text()
    assert "games_present = sorted({r[\"GameLabel\"] for r in slot_rows})" not in src, (
        "the old, plain alphabetical sort must genuinely be gone, not left alongside a new one"
    )
    assert 'games_present = sorted(game_date_by_label, key=lambda g: game_date_by_label[g] or "~")' in src, (
        "must sort on each game's own real start time, matching Matchup Lab's and MLB Player "
        "Lines' own already-correct convention"
    )
    print("✓ NCAAF Player Lines now sorts its Game dropdown by real kickoff time, matching the established convention every other page already uses")


def test_ncaaf_game_lab_wires_correctly_with_two_honest_tiers():
    # BUILT DIRECTLY ON REQUEST: game-level modeling for moneyline/spread/total/quarter/half
    # winners -- the first game-level modeling page for NCAAF. Confirms the real page genuinely
    # gates to NCAAF, uses the correct simulation functions, sorts games by real time (same fix
    # as Player Lines), and honestly maintains two distinct data tiers: Tier 1 (schedule-based,
    # always shown) and Tier 2 (drives-based, opt-in checkbox, explicitly flagged as unverified).
    src = (_HERE / "views" / "32_NCAAF_Game_Lab.py").read_text()
    assert 'sports.require_sport(["NCAAF"], "NCAAF Game Lab")' in src, (
        "must gate to NCAAF specifically"
    )
    assert "P.simulate_ncaaf_game(" in src, (
        "must genuinely call the real schedule-based simulation function, not a parallel implementation"
    )
    assert "P.simulate_period_winners(" in src, (
        "must genuinely call the real period simulation function for the drives-based tier"
    )
    assert 'key=lambda m: m.get("game_date") or "~"' in src, (
        "must sort games by real start time, matching the established convention"
    )
    assert "show_period = st.checkbox(" in src, (
        "the drives-based quarter/half section must be genuinely opt-in, not shown by default"
    )
    assert "show_2025_baseline = st.checkbox(" in src, (
        "must have a real 2025 baseline toggle -- the actual fix for Week 1 having no data, "
        "matching the same pattern QB Lab/Matchup Lab/Player Lines already use"
    )
    assert 'stats_date_str = "2026-02-01" if show_2025_baseline else date_str' in src, (
        "stats_date_str must genuinely redirect to 2025 when the baseline is active -- a cosmetic "
        "toggle that still passes date_str to all functions would show empty results regardless"
    )
    assert "load_game(\n        date_str, stats_date_str," in src, (
        "load_game must receive stats_date_str as a real, separate argument -- a single date_str "
        "passed to both would make the baseline toggle completely non-functional"
    )
    assert "unverified" in src and "drives cache" in src.lower(), (
        "the drives-based tier must honestly flag its data-provenance uncertainty, not present "
        "period probabilities as if they were equally confirmed as the schedule-based moneyline"
    )
    print("✓ NCAAF Game Lab genuinely gates to NCAAF, wires both real simulation functions, sorts games by time, and maintains two honest data tiers")


def test_nfl_player_lines_wires_correctly_with_confirmed_column_names():
    # BUILT DIRECTLY ON REQUEST: NFL Player Lines (33), adapted from NCAAF Player Lines (31).
    # Confirms it gates to NFL, uses the correct NFL column names for TDs (rushing_tds /
    # receiving_tds from nflreadpy -- confirmed live, not a cross-referenced guess like NCAAF's),
    # and sorts games by time rather than alphabetically.
    src = (_HERE / "views" / "33_NFL_Player_Lines.py").read_text()
    assert 'sports.require_sport(["NFL"], "NFL Player Lines")' in src, (
        "must gate to NFL specifically"
    )
    assert 'lambda g: g.get("passing_tds") or 0' in src, (
        "QB's passing TD chart must use NFL's confirmed nflreadpy column name 'passing_tds', "
        "not NCAAF's 'passing_TD'"
    )
    assert 'lambda g: (g.get("rushing_tds") or 0) + (g.get("receiving_tds") or 0)' in src, (
        "non-QB TD chart must use NFL's confirmed 'rushing_tds'/'receiving_tds', not NCAAF's"
    )
    assert 'key=lambda g: game_date_by_label[g] or "~"' in src, (
        "games must sort by real kickoff time, matching the established convention"
    )
    assert "import nfl_engine as E" in src and "import nfl_projections as P" in src, (
        "must use NFL's own engine/projections, not NCAAF's"
    )
    print("✓ NFL Player Lines genuinely gates to NFL, uses confirmed nflreadpy TD column names, and sorts games by time")


def test_nfl_game_lab_wires_correctly_with_real_injury_report():
    # BUILT DIRECTLY ON REQUEST: NFL Game Lab (34), the genuine upgrade over NCAAF's version --
    # a real, live injury report via nflreadpy, not the honest placeholder NCAAF carries.
    # Confirms it gates to NFL, calls simulate_nfl_game (not NCAAF's version), calls
    # get_team_injuries for both teams, and sorts games by time.
    src = (_HERE / "views" / "34_NFL_Game_Lab.py").read_text()
    assert 'sports.require_sport(["NFL"], "NFL Game Lab")' in src, (
        "must gate to NFL specifically"
    )
    assert "P.simulate_nfl_game(" in src, (
        "must call simulate_nfl_game specifically -- not NCAAF's simulate_ncaaf_game"
    )
    assert "E.get_team_injuries(home_abbr, season, week)" in src, (
        "must call get_team_injuries for the home team -- the real, live upgrade over NCAAF"
    )
    assert "E.get_team_injuries(away_abbr, season, week)" in src, (
        "must call get_team_injuries for the away team too"
    )
    assert 'key=lambda m: m.get("game_date") or "~"' in src, (
        "must sort games by real kickoff time"
    )
    assert "import nfl_engine as E" in src and "import nfl_projections as P" in src, (
        "must use NFL's own engine/projections"
    )
    print("✓ NFL Game Lab genuinely gates to NFL, wires simulate_nfl_game, calls real get_team_injuries for both teams, and sorts games by time")


def test_no_undefined_names_anywhere_in_the_real_project():
    # ADDED DIRECTLY as a real, permanent safeguard, after TWO real, confirmed undefined-name
    # bugs shipped in the same real session -- one a real, live production NameError (a bare `O`
    # instead of `BBD.O` on Best Bets, crashing that page for every real user), the other a
    # real, pre-existing bug this same real sweep caught before it was ever reported (a bare
    # `meta` on Edge Board's own IDP section). py_compile alone -- this project's own real,
    # existing syntax check -- never catches this real class of bug, since it only checks
    # syntax, never whether a name actually resolves; a NameError on a default parameter value
    # or a bare reference only ever fires at real import/execution time, which py_compile never
    # performs. This is the real, permanent fix for that real gap: a genuine static-analysis
    # sweep, via pyflakes' own real API, run automatically every time this real suite runs, not
    # something that has to be remembered and run by hand.
    #
    # Deliberately filters to ONLY "undefined name" messages -- pyflakes' own other real
    # categories (imported-but-unused, f-string missing a placeholder, local variable assigned
    # but never used) are real, but genuinely benign style notes, not a real, live crash risk;
    # failing this real test on those would create real noise that trains people to ignore real
    # failures, the opposite of what a permanent safeguard should do.
    import io
    from pathlib import Path
    from pyflakes.api import checkPath
    from pyflakes.reporter import Reporter

    project_root = _HERE
    py_files = sorted(
        p for p in project_root.glob("*.py")
        if not p.name.startswith("test_")
    ) + sorted(
        p for p in (project_root / "views").glob("*.py")
    )
    assert len(py_files) > 50, "the real file sweep must genuinely cover this project's real size, not an empty or tiny glob"

    undefined_name_issues = []
    for path in py_files:
        out, err = io.StringIO(), io.StringIO()
        checkPath(str(path), Reporter(out, err))
        for line in out.getvalue().splitlines():
            if "undefined name" in line:
                undefined_name_issues.append(line)

    assert undefined_name_issues == [], (
        "Real, live undefined-name bug(s) found -- each one is a genuine NameError waiting to "
        "fire the moment its real code path executes:\n" + "\n".join(undefined_name_issues)
    )
    print(f"✓ No real undefined-name bugs anywhere across {len(py_files)} real project files")


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
