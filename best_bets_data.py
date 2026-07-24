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

from typing import Any, Dict, Optional

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
    """Render the shared sportsbook selector. Returns the selected Odds API book key.

    available_books: if supplied directly (e.g. from a prior load), use it. Otherwise,
    if date_str is supplied, fetches tonight's real book coverage via fetch_available_books
    (a separate, lightweight cached function independent of the heavy pipeline cache).
    Falls back to the full US_BOOKS list if neither is available."""
    if not get_odds_api_key():
        return O.DEFAULT_BOOK

    if available_books is None and date_str:
        available_books = fetch_available_books(date_str, get_odds_api_key())

    books_to_show = available_books if available_books else list(O.US_BOOKS.keys())
    if O.DEFAULT_BOOK not in books_to_show:
        books_to_show = [O.DEFAULT_BOOK] + books_to_show

    book_labels = [O.US_BOOKS.get(k, k) for k in books_to_show]
    default_idx = books_to_show.index(O.DEFAULT_BOOK) if O.DEFAULT_BOOK in books_to_show else 0

    with st.sidebar:
        st.markdown("---")
        selected_label = st.selectbox(
            "📖 Sportsbook",
            book_labels,
            index=default_idx,
            key=f"{key_prefix}_book_selector",
            help="Lines and odds will use this book's specific line where it has coverage. "
                "Only books that posted lines on tonight's slate are shown. "
                "Falls back to the lowest available line across all books when your selected "
                "book doesn't have a line for a specific player."
        )
    return books_to_show[book_labels.index(selected_label)]


@st.cache_data(ttl=300, show_spinner=False)
def fetch_available_books(date_str: str, odds_api_key: Optional[str]) -> List[str]:
    """Fetch the list of books that actually have coverage tonight -- kept SEPARATE from
    build_mlb_board intentionally. available_books is UI state for the book selector; baking
    it into build_mlb_board's own cached result means the selector sees a stale list whenever
    the heavy pipeline cache is hit, even after the API response changes. A separate, lightweight
    cache means the selector always reflects tonight's real book coverage independently of
    whether the full pipeline result is stale. Same TTL as build_mlb_board."""
    if not odds_api_key:
        return list(O.US_BOOKS.keys())
    try:
        offers, _ = O.fetch_slate_props(date_str, odds_api_key,
                                        list(O.SUPPORTED_MARKETS), sport=O.SPORT)
        live = O.books_in_offers(offers)
        return live if live else list(O.US_BOOKS.keys())
    except Exception:
        return list(O.US_BOOKS.keys())


@st.cache_data(ttl=300, show_spinner=False)
def build_mlb_board(date_str: str, fip_constant: float, odds_api_key: Optional[str] = None,
                    preferred_book: str = O.DEFAULT_BOOK):
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
            if live_books:   # only narrow the list when we actually got real data back
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
                             preferred_book: str = O.DEFAULT_BOOK):
    """Build the full MLB best-bets board: slate -> real sportsbook lines -> statcast/weather
    enrichment -> hitter/pitcher projections -> ranked plays -> bullpen-blend re-pricing.

    Returns (plays, meta, available_books) — available_books is the list of book keys that
    actually had coverage in tonight's odds data, used to populate the sportsbook selector."""
    _, meta, plays, available_books = build_mlb_board(date_str, fip_constant,
                                                      get_odds_api_key(), preferred_book)
    return plays, meta, available_books


def load_mlb_graded_picks_board(date_str: str, fip_constant: float,
                                preferred_book: str = O.DEFAULT_BOOK):
    """Same underlying board as load_mlb_best_bets_board, but also returns raw hitter rows
    for Graded Picks' one-sided banner.

    Returns (plays, meta, rows, available_books)."""
    rows, meta, plays, available_books = build_mlb_board(date_str, fip_constant,
                                                         get_odds_api_key(), preferred_book)
    return plays, meta, rows, available_books


def load_generic_best_bets_board(sport_key: str, date_str: str):
    """Any sport whose engine/projections don't need MLB's statcast/weather/bullpen-blend
    enrichment path — currently WNBA, and any future sport built the same way.

    A REAL, DELIBERATE CONSOLIDATION, not new scope creep: before this existed, Best Bets and
    Command Center each had their OWN separate copy of this exact two-line pattern
    (build_slate -> build_best_bets) — the same kind of duplication that caused the real,
    reported conviction-mismatch bug for MLB specifically, just not yet triggered here because
    nothing sport-specific has been layered onto only one copy. Consolidating this now, before a
    third page (Graded Picks) needed its own copy too, rather than after a real bug forces it —
    unlike the MLB fix, which came after a real, reported production issue.

    Takes sport_key as an explicit argument and calls sports.get(sport_key) fresh on each call —
    deliberately NOT resolved via sports.active() at import time, same reasoning as this file's
    own MLB functions: a module-level resolution would freeze to whichever sport was active on
    this module's first import, silently wrong for every later call to a different sport.

    Returns (plays, meta)."""
    sport = sports.get(sport_key)
    rows, meta = sport.engine.build_slate(date_str)
    plays = sport.projections.build_best_bets(rows)
    return plays, meta
