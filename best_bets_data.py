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

import streamlit as st

import mlb_engine as E
import projections as P
import sports


@st.cache_data(ttl=300, show_spinner=False)
def _build_mlb_board(date_str: str, fip_constant: float):
    """Internal, shared board-building step — slate -> statcast/weather enrichment -> hitter/
    pitcher projections -> ranked plays -> bullpen-blend re-pricing. Returns (rows, meta, plays).

    Cached here (not just at each public function's own level) so load_mlb_best_bets_board and
    load_mlb_graded_picks_board, when called with the same (date_str, fip_constant) in the same
    session, share ONE result instead of each re-running build_slate and everything downstream of
    it — real network cost avoided, not just a style preference. rows is exposed here (not by the
    original load_mlb_best_bets_board) because Graded Picks needs it directly for compute_one_
    sided_banner, which reads real per-hitter fields (Opp HR/9) that don't survive into the
    flattened plays list."""
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

    rows, meta = E.build_slate(date_str, fip_constant)
    sc, k = load_statcast()
    wx = load_weather(tuple((m.get("venue_id"), m.get("game_date"), m.get("venue")) for m in meta))
    for r in rows:
        w = wx.get(r.get("_venue_id"))
        r["_weather_hr"] = w["hr_factor"] if w else 1.0
        if w:                              # keep the pieces so the inspector can decompose weather
            r["_wx_temp"] = w.get("temp_f")
            r["_wx_outwind"] = w.get("out_wind_mph", 0.0)
            r["_wx_desc"] = w.get("wind_desc")
            r["_wx_roof"] = w.get("roof", "open")
    P.enrich_hitter_rows(rows, seed=7, statcast=sc, statcast_k=k)
    pitcher_rows = P.build_pitcher_projection_rows(rows, meta, seed=11)
    plays = P.build_best_bets(rows, pitcher_rows)

    # Re-price the top hitter-market plays using their real vs-starter/vs-bullpen exposure — see
    # apply_bullpen_blend_to_top_plays' own docstring for the full reasoning and the real,
    # confirmed finding this was built from. Scoped to top_n=30 for real cost reasons.
    rows_by_pid = {r.get("_pid"): r for r in rows}
    P.apply_bullpen_blend_to_top_plays(
        plays, rows_by_pid,
        get_bullpen_stat_fn=lambda tid, ex: load_bullpen_aggregate_for_blend(tid, ex, fip_constant),
        statcast=sc, statcast_k=k, seed=7, top_n=30)

    return rows, meta, plays


def load_mlb_best_bets_board(date_str: str, fip_constant: float):
    """Build the full MLB best-bets board: slate -> statcast/weather enrichment -> hitter/pitcher
    projections -> ranked plays -> bullpen-blend re-pricing of the top hitter-market candidates.

    Returns (plays, meta) — the RAW ranked plays (no Slot/Time enrichment; Best Bets adds that
    itself for its own table, Command Center doesn't need it at all) and the full per-game
    metadata list, matching what both callers' own pre-existing interfaces already expected."""
    _, meta, plays = _build_mlb_board(date_str, fip_constant)
    return plays, meta


def load_mlb_graded_picks_board(date_str: str, fip_constant: float):
    """Same underlying board as load_mlb_best_bets_board (shares its cached result when called
    with the same arguments in the same session — no duplicate slate fetch), but ALSO returns the
    raw hitter rows, needed for the Graded Picks page's own per-game "one-sided" banner
    (mlb_engine.compute_one_sided_banner), which reads real per-hitter fields that don't survive
    into the flattened plays list.

    Returns (plays, meta, rows)."""
    rows, meta, plays = _build_mlb_board(date_str, fip_constant)
    return plays, meta, rows


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
