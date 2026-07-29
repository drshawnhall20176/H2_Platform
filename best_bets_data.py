"""
best_bets_data.py — the ONE shared loader for MLB's "best bets" board (statcast, weather,
hitter/pitcher projections, ranked plays, and the bullpen-blend re-pricing pass).

WHY THIS FILE EXISTS: Best Bets and Command Center's "Tonight's top leans" are supposed to show
the SAME plays with the SAME conviction numbers — they're two views onto one board, not two
independent models. Before this file existed, each page had its OWN, separately-written copy of
this loading logic. When the bullpen-blend re-pricing pass (apply_bullpen_blend_to_top_plays) was
added to fix a real, confirmed conviction-overstatement bug, it was added to Best Bets' own copy —
and Command Center's separate copy silently kept using the old, unblended numbers, with no error,
no warning, just two pages quietly showing different convictions for the same play. That's exactly
the kind of drift that happens when the same logic lives in two places; the fix is to make it live
in exactly one.

Both views should call load_mlb_best_bets_board(date_str, fip_constant) and nothing else for this
purpose — if a THIRD page ever needs this board, it calls this too, not a new copy.

Imports mlb_engine/projections DIRECTLY, not via sports.active() — a real, deliberate choice, not
an oversight: this function is explicitly MLB-only, and going through the generic sport-dispatch
registry would mean E/P get set ONCE at module import time (Python only runs a module's top-level
code on its FIRST import, not on every subsequent one) — if this module happened to be first
imported while a different sport was active, E/P would stay frozen to that sport's modules for
the rest of the process, silently wrong for every later MLB call. The original per-view inline
code didn't have this risk (the whole view file re-runs fresh on every page load in Streamlit);
consolidating into a shared module would have quietly introduced it if not for this fix.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

import mlb_engine as E
import projections as P
import odds_api as O
import sports


def get_odds_api_key() -> Optional[str]:
    """Read the Odds API key from st.secrets or the environment -- the SAME pattern Edge Board
    already uses, centralized here so every page that shares build_mlb_board doesn't each
    duplicate the key-lookup logic. Returns None when not configured (graceful fallback to
    DEFAULT_LINES, not a page crash -- the intent is that a deploy without an API key still
    works correctly, just without real lines)."""
    import os
    try:
        return st.secrets["ODDS_API_KEY"]
    except Exception:
        return os.environ.get("ODDS_API_KEY")


def render_book_selector(key_prefix: str = "book",
                         available_books: Optional[List[str]] = None,
                         date_str: Optional[str] = None) -> str:
    """Render the sportsbook selector inline on the main page (not the sidebar).
    Sidebar placement caused the dropdown to be clipped by the viewport bottom edge.
    Returns the selected Odds API book key."""
    if not get_odds_api_key():
        return O.DEFAULT_BOOK

    if available_books is None and date_str:
        available_books = get_available_books_for_date(date_str)

    books_to_show = available_books if available_books else list(O.US_BOOKS.keys())
    if O.DEFAULT_BOOK not in books_to_show:
        books_to_show = [O.DEFAULT_BOOK] + books_to_show

    book_labels = [O.US_BOOKS.get(k, k) for k in books_to_show]
    default_idx = books_to_show.index(O.DEFAULT_BOOK) if O.DEFAULT_BOOK in books_to_show else 0

    selected_label = st.selectbox(
        "📖 Sportsbook",
        book_labels,
        index=default_idx,
        key=f"{key_prefix}_book_selector",
        help=f"Lines and model probabilities will use this book's specific line where available. "
            f"{len(books_to_show)} book(s) active on tonight's slate. "
            "Falls back to the lowest available line across all books when your selected "
            "book doesn't have coverage for a specific player."
    )
    return books_to_show[book_labels.index(selected_label)]


def render_split_selector(key_prefix: str = "split") -> tuple:
    """Render the venue (Home/Away/All) and time-of-day (Day/Night/All) split selectors
    inline on the main page. Returns (venue_split, time_split) as Odds-API-style strings:
    venue_split: 'home', 'away', or None (All). time_split: 'day', 'night', or None (All).

    Placed inline (not sidebar) so users clearly understand the split toggles affect the
    CURRENT PAGE's conviction scores, grades, and rankings -- not a global preference.
    Default is All/All (full-season, existing behavior), so the page works identically for
    users who never touch the toggles.

    IMPORTANT -- these drive a real recomputation of every probability on the board when
    set. A clear per-play indicator (via _split_label in the Why column) ensures no one
    looks at a changed conviction score without knowing the split drove it."""
    vc1, vc2 = st.columns(2)
    with vc1:
        venue_opt = st.radio(
            "🏟️ Venue split",
            ["All", "Home", "Away"],
            horizontal=True,
            key=f"{key_prefix}_venue",
            help="Recomputes model probabilities using only each pitcher's and hitter's "
                 "home (or away) game log. Falls back to full-season when fewer than 5 "
                 "qualifying starts/games exist — shown in 'Why the model likes it'.")
    with vc2:
        time_opt = st.radio(
            "🕐 Time split",
            ["All", "Day", "Night"],
            horizontal=True,
            key=f"{key_prefix}_time",
            help="Recomputes using only day games (before 5pm ET) or night games. "
                 "Day games are a minority of the schedule so samples are often thin — "
                 "the model will show 'full-season used (thin split)' when fewer than 5 "
                 "qualifying games exist.")
    venue_split = None if venue_opt == "All" else venue_opt.lower()
    time_split = None if time_opt == "All" else time_opt.lower()

    if venue_split or time_split:
        parts = [p for p in [venue_opt if venue_split else None,
                              time_opt if time_split else None] if p]
        st.caption(f"⚠️ **Split mode active: {' + '.join(parts)} games only.** "
                  "The board shows only players who are actually in this situation tonight "
                  f"(e.g. Away = only away teams; Night = only night games). "
                  "Conviction scores reflect each player's own historical performance in "
                  "this split, not their full-season baseline. "
                  "Plays showing 'full-season used' in the Why column had fewer than 5 "
                  "qualifying games in this split.")
    return venue_split, time_split


def get_available_books_for_date(date_str: str) -> List[str]:
    """Returns the list of books stored in session state for tonight, or the full US_BOOKS
    list as a safe fallback when nothing has been stored yet."""
    return st.session_state.get(f"_available_books_{date_str}", list(O.US_BOOKS.keys()))


@st.cache_data(ttl=300, show_spinner=False)
def build_mlb_board(date_str: str, fip_constant: float, odds_api_key: Optional[str] = None,
                    preferred_book: str = O.DEFAULT_BOOK,
                    venue_split: Optional[str] = None,
                    time_split: Optional[str] = None):
    """The ONE shared MLB board-building pipeline — slate -> real sportsbook lines -> statcast/
    weather enrichment -> hitter/pitcher projections -> ranked plays -> bullpen-blend re-pricing.
    Returns (rows, meta, plays).

    odds_api_key: the real The Odds API key (from st.secrets/env, same as Edge Board already
    uses). When None (not configured), every market falls back to this platform's own
    DEFAULT_LINES placeholder -- the exact original behavior -- so a deploy without an API key
    still works correctly, just without real lines. When supplied, a single real batch fetch
    pulls real sportsbook lines for all 17 real MLB markets at once, and every probability
    computed by enrich_hitter_rows/build_pitcher_projection_rows is computed against the real
    line for that specific player, not a one-size-fits-all placeholder.

    REAL COST, STATED DIRECTLY: player props cost 1 quota unit per market per event. This fetch
    requests all 17 real markets for every game on the slate -- a full 15-game slate is 15 × 17
    = 255 quota units per build_mlb_board call. Cached at the same 5-minute ttl as the rest of
    this pipeline (so a full slate refresh costs 255 quota, not 255 per page navigation within
    that window), and fetched once here for every page that shares this pipeline (Best Bets,
    Graded Picks, Suggested Parlays, Speculative Basket, Command Center) rather than once per
    page -- confirmed that this consolidation is what best_bets_data.py was built for in the
    first place.

    PUBLIC, NOT INTERNAL — a real, deliberate widening of scope, not the original design:
    Retrospective had its own separate, third copy of this exact pipeline (load_retro_mlb),
    found during a later cross-sport audit — structurally the same duplication-drift risk that
    caused the real Command Center/Best Bets conviction mismatch earlier, just not yet triggered
    into a visible bug. Consolidating this here means Retrospective now grades against the SAME
    bullpen-blended probabilities actually shown on Best Bets and Graded Picks, not a duplicate,
    unblended computation — a real accuracy improvement for Retrospective, not just deduplication
    for its own sake.

    Cached here (not just at each public function's own level) so every caller — Best Bets,
    Graded Picks, and now Retrospective — when called with the same (date_str, fip_constant) in
    the same session, share ONE result instead of each re-running build_slate and everything
    downstream of it — real network cost avoided, not just a style preference. rows is exposed
    (not just plays) because both Graded Picks (compute_one_sided_banner, which reads real
    per-hitter fields like "Opp HR/9" that don't survive into the flattened plays list) and
    Retrospective (pitcher-K miss explanations, which need the pitcher rows themselves) need more
    than just the ranked plays."""
    import statcast_data as SC
    import weather as WX

    @st.cache_data(ttl=3600, show_spinner=False)
    def load_statcast():
        return SC.load()

    @st.cache_data(ttl=1800, show_spinner=False)
    def load_weather(meta_keys: tuple):
        out = {}
        for vid, gdate, vname in meta_keys:
            if vid is not None and vid not in out:
                try:
                    out[vid] = WX.get_game_weather(vid, gdate, vname)
                except Exception:
                    out[vid] = None
        return out

    @st.cache_data(ttl=1800, show_spinner=False)
    def load_bullpen_aggregate_for_blend(team_id, exclude_pid, fip_constant_inner):
        if not team_id:
            return None
        return E.get_bullpen_aggregate_stat(team_id, exclude_pid=exclude_pid,
                                            fip_constant=fip_constant_inner)

    @st.cache_data(ttl=1800, show_spinner=False)
    def load_starter_rest(pitcher_id, team_id, date_str_inner):
        if not pitcher_id or not team_id:
            return None
        return E.get_starter_rest_info(pitcher_id, team_id, date_str_inner).get("days_rest")

    @st.cache_data(ttl=1800, show_spinner=False)
    def load_bullpen_fatigue_for_blend(team_id, exclude_pid, date_str_inner):
        if not team_id:
            return None
        fatigue_rows = E.get_team_bullpen_fatigue(team_id, date_str_inner)
        return P.bullpen_fatigued_fraction(fatigue_rows, exclude_pid=exclude_pid)

    @st.cache_data(ttl=1800, show_spinner=False)
    def load_team_hitter_workload(team_id, date_str_inner):
        if not team_id:
            return {}
        workload_rows = E.get_team_hitter_workload(team_id, date_str_inner)
        return {r["player_id"]: r.get("consecutive_games_started") for r in workload_rows}

    rows, meta = E.build_slate(date_str, fip_constant)
    sc, k = load_statcast()
    wx = load_weather(tuple((m.get("venue_id"), m.get("game_date"), m.get("venue")) for m in meta))

    # Split stat overrides -- when venue_split or time_split is set, replace each pitcher's
    # full-season stat (and each hitter's _stat) with their filtered game log, so the model
    # computes probabilities against what this player actually does in THIS type of game.
    # Falls back to full-season silently when the split sample is below MIN_SPLIT_STARTS (5).
    # The _split_label attached here flows through to the Why column so every play shows
    # which data source was used -- never a silent substitution.
    season = int(date_str[:4])
    if venue_split or time_split:
        # Compute label base first so it's available in the loops below
        split_parts = [p for p in [venue_split, time_split] if p]
        split_label_base = "/".join(split_parts) if split_parts else None

        # Pitcher splits: replace pm.stat in meta for each starter
        for m in meta:
            for pm_attr in ("home_pm", "away_pm"):
                pm = m.get(pm_attr)
                if pm is None or pm.id is None or not pm.stat:
                    continue
                pitcher_team_id = m.get("home_id") if pm_attr == "home_pm" else m.get("away_id")
                split_stat, n = E.get_pitcher_split_stat(
                    pm.id, season, date_str,
                    venue=venue_split, time_of_day=time_split,
                    team_id=pitcher_team_id)
                if split_stat is not None:
                    import dataclasses
                    m[pm_attr] = dataclasses.replace(pm, stat=split_stat)
                    m[f"_{pm_attr}_split_n"] = n
                    m[f"_{pm_attr}_split_label"] = f"{split_label_base} split ({n} starts)"
                else:
                    m[f"_{pm_attr}_split_label"] = None

        # Hitter splits: replace _stat on each row
        for r in rows:
            pid = r.get("_pid")
            if not pid:
                continue
            split_stat, n = E.get_hitter_split_stat(
                pid, season, date_str,
                venue=venue_split, time_of_day=time_split)
            if split_stat is not None:
                r["_stat"] = split_stat
                r["_split_n"] = n
                r["_split_label"] = f"{split_label_base} split ({n} games)"
            else:
                r["_split_label"] = None
    else:
        split_label_base = None
        for r in rows:
            r["_split_label"] = None

    # Real sportsbook lines -- one batch fetch for all 17 real markets across every game on the
    # slate, feeding every probability the pipeline computes downstream. None (and a silent
    # graceful fallback to DEFAULT_LINES) if: no API key configured, the fetch fails for any
    # reason (network, quota exceeded, etc), or the response body is non-dict (the same real
    # failure mode that tripped the live pitch-count feature -- fetch_json's own None-body guard
    # handles this already, but a belt-and-suspenders try/except here means a real, unexpected
    # odds-fetch failure can never block the rest of the pipeline from running).
    real_lines = None
    available_books: List[str] = list(O.US_BOOKS.keys())   # full list as default
    if odds_api_key:
        try:
            offers, _info = O.fetch_slate_props(date_str, odds_api_key,
                                                list(O.SUPPORTED_MARKETS), sport=O.SPORT)
            real_lines = O.market_lines_for_slate(offers, preferred_book=preferred_book)
            live_books = O.books_in_offers(offers)
            if live_books:
                available_books = live_books
        except Exception:
            real_lines = None   # fall back to DEFAULT_LINES, not a page crash

    # Starter rest, added directly on request -- one cached fetch per real starter (home/away
    # per game), not per hitter row. Attached to meta (home_days_rest/away_days_rest) for
    # build_pitcher_projection_rows' own use, and mirrored into a pitcher_id -> days_rest lookup
    # so every hitter row can carry its OPPOSING starter's rest via the same _opp_pid it already
    # has -- the same per-row metadata convention as _opp_stat.
    rest_by_pitcher_id: Dict[int, Optional[int]] = {}
    for m in meta:
        home_pid = m["home_pm"].id
        away_pid = m["away_pm"].id
        m["home_days_rest"] = load_starter_rest(home_pid, m.get("home_id"), date_str)
        m["away_days_rest"] = load_starter_rest(away_pid, m.get("away_id"), date_str)
        if home_pid is not None:
            rest_by_pitcher_id[home_pid] = m["home_days_rest"]
        if away_pid is not None:
            rest_by_pitcher_id[away_pid] = m["away_days_rest"]
    # Hitter workload, added directly on request: fetched once per DISTINCT team (not per
    # hitter row) since every hitter on the same team shares the same team-level fetch, same
    # cost-efficiency posture as the pitcher-side rest/fatigue fetches above.
    workload_by_team: Dict[Any, Dict[int, Optional[int]]] = {}
    for r in rows:
        w = wx.get(r.get("_venue_id"))
        r["_weather_hr"] = w["hr_factor"] if w else 1.0
        if w:                              # keep the pieces so the inspector can decompose weather
            r["_wx_temp"] = w.get("temp_f")
            r["_wx_outwind"] = w.get("out_wind_mph", 0.0)
            r["_wx_desc"] = w.get("wind_desc")
            r["_wx_roof"] = w.get("roof", "open")
        r["_opp_days_rest"] = rest_by_pitcher_id.get(r.get("_opp_pid"))
        team_id = r.get("_team_id")
        if team_id not in workload_by_team:
            workload_by_team[team_id] = load_team_hitter_workload(team_id, date_str)
        r["_consecutive_games_started"] = workload_by_team[team_id].get(r.get("_pid"))
    P.enrich_hitter_rows(rows, seed=7, statcast=sc, statcast_k=k, real_lines=real_lines)
    pitcher_rows = P.build_pitcher_projection_rows(rows, meta, seed=11, real_lines=real_lines)
    plays = P.build_best_bets(rows, pitcher_rows)

    # Re-price the top hitter-market plays using their real vs-starter/vs-bullpen exposure — see
    # apply_bullpen_blend_to_top_plays' own docstring for the full reasoning and the real,
    # confirmed finding this was built from. Scoped to top_n=30 for real cost reasons.
    rows_by_pid = {r.get("_pid"): r for r in rows}
    P.apply_bullpen_blend_to_top_plays(
        plays, rows_by_pid,
        get_bullpen_stat_fn=lambda tid, ex: load_bullpen_aggregate_for_blend(tid, ex, fip_constant),
        get_bullpen_fatigue_fn=lambda tid, ex: load_bullpen_fatigue_for_blend(tid, ex, date_str),
        statcast=sc, statcast_k=k, seed=7, top_n=30, real_lines=real_lines)

    return rows, meta, plays, available_books


def load_mlb_best_bets_board(date_str: str, fip_constant: float,
                             preferred_book: str = O.DEFAULT_BOOK,
                             venue_split: Optional[str] = None,
                             time_split: Optional[str] = None):
    """Build the full MLB best-bets board with optional split filtering.
    Returns (plays, meta, available_books)."""
    _, meta, plays, available_books = build_mlb_board(
        date_str, fip_constant, get_odds_api_key(), preferred_book,
        venue_split, time_split)
    return plays, meta, available_books


def load_mlb_graded_picks_board(date_str: str, fip_constant: float,
                                preferred_book: str = O.DEFAULT_BOOK,
                                venue_split: Optional[str] = None,
                                time_split: Optional[str] = None):
    """Same as load_mlb_best_bets_board but also returns raw hitter rows.
    Returns (plays, meta, rows, available_books)."""
    rows, meta, plays, available_books = build_mlb_board(
        date_str, fip_constant, get_odds_api_key(), preferred_book,
        venue_split, time_split)
    return plays, meta, rows, available_books


def filter_by_split_situation(plays: List[Dict],
                               venue_split: Optional[str],
                               time_split: Optional[str]) -> List[Dict]:
    """When a venue or time split is active, filter plays to only those where the player
    is actually in that situation TONIGHT -- not just where their historical split stats
    were used. A player whose away/night stats were used to compute the probability should
    only appear on the board when they're actually the away team in a night game tonight.

    This is the display filter that complements the model-side split stat substitution:
    - Model side: recomputes probabilities using filtered game logs (already done)
    - Display side: shows only plays where the player is in that situation tonight (this)

    Without this, 'Away + Night' shows home-team players whose away/night historical stats
    happened to be strong -- but they're not actually in that situation tonight.

    venue_split: 'home', 'away', or None. time_split: 'day', 'night', or None.
    When both None, returns plays unchanged."""
    if not venue_split and not time_split:
        return plays

    filtered = []
    for p in plays:
        is_home = p.get("_is_home")
        is_day = p.get("_is_day_game")

        # Venue filter: skip if we know the player's situation and it doesn't match
        if venue_split == "home" and is_home is False:
            continue
        if venue_split == "away" and is_home is True:
            continue
        # If _is_home is None (unknown), include the play -- never silently drop unknowns

        # Time filter: skip if we know and it doesn't match
        if time_split == "day" and is_day is False:
            continue
        if time_split == "night" and is_day is True:
            continue

        filtered.append(p)
    return filtered


def load_generic_best_bets_board(sport_key: str, date_str: str) -> tuple:
    """Any sport whose engine/projections don't need MLB's statcast/weather/bullpen-blend
    enrichment path — currently NFL, WNBA, and any future sport built the same way.

    A REAL, DELIBERATE CONSOLIDATION, not new scope creep: before this existed, Best Bets and
    Command Center each had their OWN separate copy of this exact two-line pattern
    (build_slate -> build_best_bets) — the same kind of duplication that caused the real,
    reported conviction-mismatch bug for MLB specifically, just not yet triggered here because
    nothing sport-specific has been layered onto only one copy. Consolidating this now, before a
    third page (Graded Picks) needed its own copy too, rather than after a real bug forces it —
    unlike the MLB fix, which came after a real, reported production issue.

    Real sportsbook lines fetched generically for every sport with a projections module, not
    just NFL -- this used to be NFL-only ("WNBA and other non-NFL sports still use the
    placeholder default... until their own market keys are confirmed and tested the same way"),
    a deliberate deferral at the time. That confirmation has since happened: sport.markets and
    sport.odds_sport_key are correctly populated for every live sport (WNBA/NBA/NCAAMB/NFL/
    NCAAF), so the fetch is generic now -- same one batch call per sport, real_lines passed to
    build_best_bets, no per-sport special-casing needed. A real user report is what surfaced the
    gap directly: NCAAF's Best Bets board showed every single play using the exact same
    hardcoded placeholder line (219.5/49.5/54.5/4.5, matching _MARKET_SPEC's own defaults
    exactly), because the fetch was never even attempted for anything but NFL -- not a fetch
    failure, a fetch that never ran.

    Returns (plays, meta)."""
    sport = sports.get(sport_key)
    diag_key = f"_real_lines_diag_{sport_key}_{date_str}"

    # Sports like UFC are outcome-based and have no projections module -- they use
    # dedicated pages instead of the generic Best Bets pipeline. Return empty gracefully.
    if not sport.has_projections:
        return [], [], list(O.US_BOOKS.keys())

    rows, meta = sport.engine.build_slate(date_str)

    real_lines = None
    available_books: List[str] = list(O.US_BOOKS.keys())
    api_key = get_odds_api_key()
    diag = {"attempted": bool(api_key and sport.markets), "api_key_present": bool(api_key),
           "offers": 0, "matched_lines": 0, "error": None}
    if api_key and sport.markets:
        try:
            # Per-sport key, not a hardcoded "_preferred_book_nfl" -- that string was a real,
            # latent bug of its own: harmless only because this whole block used to be gated to
            # NFL alone, so nothing else ever reached it to expose the mismatch.
            preferred_book = st.session_state.get(
                f"_preferred_book_{sport_key.lower()}", O.DEFAULT_BOOK)
            offers, _ = O.fetch_slate_props(
                date_str, api_key, list(sport.markets),
                sport=sport.odds_sport_key)
            real_lines = O.market_lines_for_slate(offers, preferred_book=preferred_book)
            diag["offers"] = len(offers)
            diag["matched_lines"] = len(real_lines)
            live = O.books_in_offers(offers)
            if live:
                available_books = live
        except Exception as e:  # noqa: BLE001
            real_lines = None
            diag["error"] = str(e)[:200]
    try:
        st.session_state[diag_key] = diag
    except Exception:
        pass   # no Streamlit runtime (e.g. a test or script context) -- diagnostic is optional

    plays = sport.projections.build_best_bets(rows, real_lines=real_lines)
    return plays, meta, available_books
