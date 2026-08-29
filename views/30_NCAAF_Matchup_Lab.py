"""
NCAAF Matchup Lab — one player, one opponent, real signals: recent form, head-to-head history
this season, and whether the opponent's defense has been trending looser or tighter lately.

Adapted directly from NFL Matchup Lab (views/12_NFL_Matchup_Lab.py), NOT a fresh build. Every
engine/projections function this page needs was either already confirmed to exist for NCAAF
(get_player_season_games, get_team_allowed_stats), or built directly for this page in the same
session (get_player_history_vs_opponent, get_team_rest_info, get_team_tds_allowed/passing/
rushing, build_matchup_profile, stat_key_for, build_trend_series, is_td_eligible_position) --
every one of those new functions ported NFL's own real signal, adapted for NCAAF's genuinely
different data shape, and covered by its own real tests, not assumed correct. See each
function's own docstring in ncaaf_engine.py/ncaaf_projections.py for the specific, confirmed
difference from its NFL counterpart.

TWO REAL, HONEST GAPS THIS PAGE CARRIES FORWARD RATHER THAN PAPERS OVER:

  1. NO INJURY REPORT SECTION WITH REAL DATA. Unlike the NFL (a real, league-mandated weekly
     report), NCAA football has no NCAA-wide injury reporting mandate at all -- as of the 2026
     season, all four Power conferences now require SOME form of game-week availability
     reporting, but formats aren't standardized, Group of Five/FCS programs vary widely, and
     CFBD doesn't appear to aggregate any of it. Building a real get_team_injuries here would be
     a separate, substantial data-sourcing project, not something derivable from CFBD's existing
     endpoints. This page shows an honest placeholder explaining the real gap, not a silently
     empty or missing section.

  2. TD-ALLOWED COLUMN NAMES ARE A PLAUSIBLE, NOT YET LIVE-VERIFIED GUESS. See
     ncaaf_engine._TD_STAT_COLS' own docstring for the full reasoning -- CFBD's API isn't
     reachable from this build environment, so passing_TD/rushing_TD/receiving_TD are an
     extrapolation of CFBD's own confirmed "{category}_{statType}" naming convention, not a
     confirmed fact. This page's own first real live load is part of verifying that guess, the
     same "first real run is the actual verification step" posture NCAAF QB Lab already carries.

NO team_abbrs_from_meta EQUIVALENT NEEDED, a real, confirmed simplification versus NFL: NFL's
own team_id IS its abbreviation string ("KC"), which is why that function exists at all. NCAAF's
own team_id/_opp_id/_team_id are CFBD's numeric school IDs, but get_team_allowed_stats/
get_player_history_vs_opponent/get_team_rest_info all already match against real school NAME
strings ("Alabama") -- exactly what row["Team"]/row["Opp"] already are. Using those directly,
throughout, is correct and simpler than porting a function that solves a problem this sport
doesn't have.
"""

import os

import streamlit as st
import components as C
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import pytz

import sports
import odds_api as O
import ncaaf_engine as E
import ncaaf_shared_cache as NSC
import ncaaf_projections as P

_active = sports.active()
game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER   # shared with Best Bets

C.base_css()
C.page_header("🔬", "NCAAF Matchup Lab",
             "One player, one opponent, three real signals: recent form, head-to-head history "
             "this season, and whether the opponent's defense has been trending looser or "
             "tighter lately — adapted directly from NFL's own Matchup Lab, on real, individually "
             "tested engine functions, not a forced port of NFL's data shape.")

if not sports.require_sport(["NCAAF"], "NCAAF Matchup Lab"):
    st.stop()

eastern = pytz.timezone("US/Eastern")


def get_api_key():
    try:
        return st.secrets["ODDS_API_KEY"]
    except Exception:
        return os.environ.get("ODDS_API_KEY")


@st.cache_data(ttl=300, show_spinner=False)
def load_slate(date_str: str):
    rows, meta = NSC.load_ncaaf_slate_cached(date_str)
    return rows, len(meta)


@st.cache_data(ttl=300, show_spinner=False)
def load_matchup(date_str: str, stats_date_str: str, player_id, opp_name: str, team_name: str):
    # TWO DIFFERENT DATES, same real reasoning as NCAAF QB Lab's own load() -- see that page's
    # own docstring for the full explanation. date_str stays on today's real slate (unused inside
    # this function directly, but kept in the signature/cache key so switching slate dates
    # doesn't reuse a stale cached matchup from a different real date); every real stats-lookup
    # call below uses stats_date_str, which the 2025-baseline toggle below can redirect to a
    # real, already-completed prior season.
    h2h_log = E.get_player_history_vs_opponent(player_id, opp_name, stats_date_str)
    season_log = E.get_player_season_games(player_id, stats_date_str)
    opp_recent = E.get_team_allowed_stats(opp_name, stats_date_str, n=5)
    opp_season = E.get_team_allowed_stats(opp_name, stats_date_str, n=None)
    opp_recent_tds = E.get_team_tds_allowed(opp_name, stats_date_str, n=5)
    opp_season_tds = E.get_team_tds_allowed(opp_name, stats_date_str, n=None)
    opp_recent_pass_tds = E.get_team_passing_tds_allowed(opp_name, stats_date_str, n=5)
    opp_season_pass_tds = E.get_team_passing_tds_allowed(opp_name, stats_date_str, n=None)
    opp_recent_rush_tds = E.get_team_rushing_tds_allowed(opp_name, stats_date_str, n=5)
    opp_season_rush_tds = E.get_team_rushing_tds_allowed(opp_name, stats_date_str, n=None)
    team_rest = E.get_team_rest_info(team_name, stats_date_str)
    opp_rest = E.get_team_rest_info(opp_name, stats_date_str)
    return (h2h_log, season_log, opp_recent, opp_season, opp_recent_tds, opp_season_tds,
           opp_recent_pass_tds, opp_season_pass_tds, opp_recent_rush_tds, opp_season_rush_tds,
           team_rest, opp_rest)


@st.cache_data(ttl=300, show_spinner=False)
def load_offers(date_str: str, markets_tuple: tuple, _api_key: str):
    offers, info = O.fetch_slate_props(date_str, _api_key, list(markets_tuple),
                                       sport=_active.odds_sport_key)
    return offers, info


# --- controls ----------------------------------------------------------------
c1, c2 = st.columns([2, 1])
with c1:
    target_date = st.date_input("Slate date", datetime.now(eastern))
with c2:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
date_str = target_date.strftime("%Y-%m-%d")

with st.spinner("Loading this week's slate..."):
    rows, n_games = load_slate(date_str)

if not rows:
    st.info("No games scheduled for this date — try a different date.", icon="🕐")
    st.stop()

# 2025-baseline toggle -- ADDED DIRECTLY ON REQUEST, same real reasoning and same "2026-02-01"
# date as NCAAF QB Lab's own toggle (see that page's own comment for why that specific date is
# safe). A REAL, EASY MISTAKE THIS SECTION AVOIDS: row["_recent_games"] is baked into each row at
# SLATE-BUILD time, using TODAY's real date, regardless of stats_date_str below -- redirecting
# load_matchup's own stats-lookup calls alone would leave the trend charts and "recent games"
# table silently empty even in baseline mode, since those read from the row directly, not from
# load_matchup's return values. Fixed below by using season_log (which DOES respect
# stats_date_str) as the real recent-games log whenever baseline mode is active.
show_2025_baseline = st.checkbox(
    "📊 Show 2025 season baseline instead (2026 hasn't started yet)",
    help="Uses last season's real, complete stats as a starting-point baseline for the same "
        "real players — clearly a stand-in for 2026 form, not a claim about it. A transfer, "
        "true freshman, or backup who barely played in 2025 will honestly show no baseline at "
        "all, not a guessed one.")
stats_date_str = "2026-02-01" if show_2025_baseline else date_str

if show_2025_baseline:
    st.info("📊 **Showing 2025 season data as a baseline.** Today's real matchups above are "
           "current — the numbers below are last season's, since 2026 has no games yet. Real "
           "roster and scheme changes since 2025 aren't reflected here.", icon="📊")
elif not any(r.get("_recent_games") for r in rows):
    st.info(
        "No player has a completed game yet **this season**, so there's no real recent-form data "
        "to project from — this is expected for the first week of a new season, not a data "
        "problem with this specific date. This page's own signals stay empty until real Week 1 "
        "games are actually in the books. **Check the \"Show 2025 season baseline\" box above** "
        "for real, honest content to work with in the meantime — or use Best Bets or Graded "
        "Picks instead for actual prop decisions right now, since those already fall back to "
        "last season's full stats as a real, tested baseline.",
        icon="🕐")
    st.stop()

# POSITION GROUP FILTER, added directly on request: browsing "every player on the whole slate"
# with no position grouping at all made it genuinely hard to find, say, just the RBs, or even
# tell what position a given name in the dropdown played without selecting them first. Same
# real position groups NCAAF Player Lines already established (page 31) -- QB / RB / WR+TE --
# for consistency across the two pages, not a new, third grouping scheme.
_POSITION_GROUPS = {"All positions": ("QB", "RB", "WR", "TE"), "QB": ("QB",), "RB": ("RB",),
                   "WR / TE": ("WR", "TE")}
position_group = st.radio("Position", list(_POSITION_GROUPS.keys()), horizontal=True)
rows = [r for r in rows if r.get("Position") in _POSITION_GROUPS[position_group]]
if not rows:
    st.info(f"No {position_group} players on today's real slate — try a different position or date.")
    st.stop()

rows_sorted = sorted(rows, key=lambda r: (r["GameLabel"], r["Player"]))

for r in rows_sorted:
    r["_slot"] = slot_of(game_dt(r.get("_game_date")))
slots_present = sorted({r["_slot"] for r in rows_sorted}, key=lambda s: SLOT_ORDER.get(s, 9))

c_slot, c_game = st.columns(2)
with c_slot:
    slot_pick = st.selectbox("Time slot", ["All slate"] + slots_present)
slot_rows = rows_sorted if slot_pick == "All slate" else [r for r in rows_sorted if r["_slot"] == slot_pick]

if not slot_rows:
    st.info(f"No players in the {slot_pick} slot — try a different time slot or \"All slate\".")
    st.stop()

game_date_by_label = {}
for r in slot_rows:
    game_date_by_label.setdefault(r["GameLabel"], r.get("_game_date"))
games_present = sorted(game_date_by_label, key=lambda g: game_date_by_label[g] or "~")
game_labels = {g: g for g in games_present}   # NCAAF's own rows have no format_et equivalent yet — plain label

with c_game:
    game_pick = st.selectbox("Game", ["All games in this slot"] + games_present,
                             format_func=lambda g: game_labels.get(g, g))
final_rows = slot_rows if game_pick == "All games in this slot" else [r for r in slot_rows if r["GameLabel"] == game_pick]

if not final_rows:
    st.info("No players match the current filters — try a different time slot or game.")
    st.stop()

options = {f"{r['Player']} ({r['Team']}, {r['Position']}) — {r['GameLabel']}": r for r in final_rows}
choice = st.selectbox("Player", list(options.keys()))
row = options[choice]

pid, opp_name, team_name = row["_pid"], row["Opp"], row["Team"]
if not row.get("_markets"):
    st.info(f"{row['Player']} doesn't have a market projected this week — try a different player.")
    st.stop()

with st.spinner(f"Pulling {row['Opp']}'s matchup history and defensive trend..."):
    (h2h_log, season_log, opp_recent, opp_season, opp_recent_tds, opp_season_tds,
    opp_recent_pass_tds, opp_season_pass_tds, opp_recent_rush_tds, opp_season_rush_tds,
    team_rest, opp_rest) = load_matchup(date_str, stats_date_str, pid, opp_name, team_name)

profile = P.build_matchup_profile(row, h2h_log, opp_recent, opp_season, season_log=season_log,
                                  opp_recent_tds_allowed=opp_recent_tds, opp_season_tds_allowed=opp_season_tds,
                                  opp_recent_passing_tds_allowed=opp_recent_pass_tds,
                                  opp_season_passing_tds_allowed=opp_season_pass_tds,
                                  opp_recent_rushing_tds_allowed=opp_recent_rush_tds,
                                  opp_season_rushing_tds_allowed=opp_season_rush_tds)

st.markdown(f"### {row['Player']} vs {row['Opp']}")
st.caption(f"{row['GameLabel']}  ·  {row['Position']}  ·  averaging over their last "
          f"{len(row.get('_recent_games') or [])} game(s) on file")


def _rest_line(label: str, rest: dict) -> str:
    days = rest.get("rest_days")
    if days is None:
        return f"{label}: rest unknown (no completed game on file yet this season)"
    return f"{label}: {days} day{'s' if days != 1 else ''} rest"


rc1, rc2 = st.columns(2)
with rc1:
    st.caption(_rest_line(row["Team"], team_rest))
with rc2:
    st.caption(_rest_line(row["Opp"], opp_rest))

with st.expander("🏥 Injury report — both teams"):
    st.info(
        "**No real injury-report data source is wired up for NCAAF yet — this section is an "
        "honest placeholder, not a silently empty result.** Unlike the NFL's league-mandated "
        "weekly report, college football has no NCAA-wide injury reporting requirement. As of "
        "the 2026 season all four Power conferences require some form of game-week availability "
        "reporting, but formats aren't standardized across conferences, and Group of Five/FCS "
        "programs vary further still — CFBD, this platform's own data source, doesn't appear to "
        "aggregate any of it. Wiring in a real feed here would be a separate, substantial data "
        "project, not something this page can honestly derive from what it already has.",
        icon="🏥")

st.info(
    f"**How {row['Player']} does against {row['Opp']} specifically, vs. how they've played "
    "overall:** the table below compares their head-to-head average against this exact opponent "
    "to their SEASON average (not just recent form) — that isolates what THIS TEAM does to them "
    "specifically from just being generally hot or cold lately. Expect H2H to be empty far more "
    "often than not — most FBS opponents meet exactly once a season (conference or rivalry games "
    "sometimes twice), so an empty H2H table is the common case here, not a gap.",
    icon="🎯")

# --- trend charts: is he trending toward or away from the number? ----------
st.markdown(f"**{row['Player']} — recent-form trend vs. the line**")

api_key = get_api_key()
if not api_key:
    st.caption("🔑 No `ODDS_API_KEY` found — charts below show the model's own default line "
              "instead of this week's actual sportsbook number. Add the key to `.streamlit/"
              "secrets.toml` or the `ODDS_API_KEY` environment variable, then reload, to see "
              "the real line.")
elif st.button("📡 Fetch live lines", help="One fetch covers every player/market on this week's "
              "slate — switching players afterward reuses it at no extra API cost."):
    st.session_state["ncaaf_matchup_lab_fetch_odds"] = True

offers, offers_info = [], {}
if api_key and st.session_state.get("ncaaf_matchup_lab_fetch_odds"):
    try:
        with st.spinner("Fetching live lines..."):
            offers, offers_info = load_offers(date_str, tuple(_active.markets), api_key)
    except O.OddsAPIError as e:
        st.error(f"Odds API error: {e}")

if offers_info:
    st.caption(f"Quota remaining: {offers_info.get('remaining', '—')} · "
              f"games priced: {offers_info.get('events_fetched', '—')}/{offers_info.get('events_total', '—')}")

live_lines = O.market_lines_for_player(offers, row["Player"], projections_module=P) if offers else {}

log = season_log if show_2025_baseline else (row.get("_recent_games") or [])
trend_log = P.build_trend_series(log)   # oldest -> newest, for left-to-right reading
market_slots = P.market_list()          # only 1-2 entries for a real row, position-gated already
active_markets = [(mkey, col, disp) for mkey, col, disp in market_slots if mkey in row["_markets"]]
is_qb = row.get("Position") == "QB"
show_td_chart = (not is_qb) and P.is_td_eligible_position(row.get("Position"))
extra_bar_charts = (
    [("Rush Yards", lambda g: g.get("rushing_YDS") or 0),
    ("Passing TDs", lambda g: g.get("passing_TD") or 0),
    ("Rushing TDs", lambda g: g.get("rushing_TD") or 0)] if is_qb
    else [("Touchdowns", lambda g: (g.get("rushing_TD") or 0) + (g.get("receiving_TD") or 0))]
    if show_td_chart else []
)
n_charts = len(active_markets) + len(extra_bar_charts)
chart_cols = st.columns(n_charts) if n_charts else []
col_iter = iter(chart_cols)


def _render_bar_chart(title: str, stat_fn, slot) -> None:
    with slot:
        if not trend_log:
            st.caption(f"{title}: no recent games on file yet.")
            return
        xs = [f"Wk {g.get('week', '—')}" for g in trend_log]
        ys = [stat_fn(g) for g in trend_log]
        hover = [f"{title}: {y:g}<br>vs {g.get('opponent_team', '—')}" for y, g in zip(ys, trend_log)]
        fig = go.Figure(go.Bar(x=xs, y=ys, marker=dict(color="#3b82f6"), text=hover, hoverinfo="text"))
        fig.update_xaxes(type="category")
        if "TD" in title:
            fig.update_yaxes(dtick=1)
        fig.update_layout(template="plotly_white", height=220,
                          margin=dict(l=10, r=10, t=30, b=10), title=title, showlegend=False)
        st.plotly_chart(fig, width="stretch")


for (mkey, col, disp), slot in zip(active_markets, col_iter):
    stat_key = P.stat_key_for(col)
    with slot:
        if not trend_log:
            st.caption(f"{disp}: no recent games on file yet.")
            continue
        line_val = live_lines.get(mkey)
        is_live = line_val is not None
        if line_val is None:
            line_val = P.default_line(mkey)
        xs = [f"Wk {g.get('week', '—')}" for g in trend_log]
        ys = [g.get(stat_key, 0.0) for g in trend_log]
        hover = [f"{disp}: {y:g}<br>vs {g.get('opponent_team', '—')}" for y, g in zip(ys, trend_log)]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name=disp,
                                 line=dict(color="#3b82f6"), marker=dict(size=8),
                                 text=hover, hoverinfo="text"))
        if line_val is not None:
            fig.add_hline(y=line_val, line_dash="dash", line_color="#f97316",
                         annotation_text=f"{'Line' if is_live else 'Model default'}: {line_val:g}",
                         annotation_position="top left")
        fig.update_xaxes(type="category")
        fig.update_layout(template="plotly_white", height=220,
                          margin=dict(l=10, r=10, t=30, b=10), title=disp,
                          showlegend=False)
        st.plotly_chart(fig, width="stretch")

for (title, stat_fn), slot in zip(extra_bar_charts, col_iter):
    _render_bar_chart(title, stat_fn, slot)

st.caption("Dashed line is this week's actual sportsbook number once fetched above; otherwise "
          "it's the model's own default line, clearly labeled as such, never presented as a "
          "live quote it isn't.")

# --- table 1: player signals (recent form / season form / this matchup) -----
if profile:
    pdf = pd.DataFrame(profile)[["Market", "Recent Avg", "Season Avg", "H2H Avg", "H2H Games",
                                 "H2H Spread", "High Variance", "Suppressed"]]

    def _notes(r):
        bits = []
        if r["Suppressed"]:
            bits.append("🎯 Suppressed vs his other markets")
        if r["High Variance"]:
            bits.append(f"⚠️ Wide swing ({r['H2H Spread']})")
        return " · ".join(bits) if bits else "—"

    pdf["Notes"] = pdf.apply(_notes, axis=1)
    pdf = pdf[["Market", "Recent Avg", "Season Avg", "H2H Avg", "H2H Games", "Notes"]]
    st.markdown(f"**{row['Player']} — recent form, season form, and this matchup**")
    st.dataframe(
        pdf.style.format({"Recent Avg": "{:.1f}", "Season Avg": "{:.1f}", "H2H Avg": "{:.1f}"}, na_rep="—"),
        hide_index=True, width="stretch",
    )

if not h2h_log:
    st.caption(f"ℹ️ {row['Team']} and {row['Opp']} haven't played each other yet this season — "
              "H2H columns are honestly blank rather than a guess. Recent form and defense "
              "trend are still real signals on their own.")
if not season_log:
    st.caption("ℹ️ No season-long log available yet for Season Avg — early in the season this "
              "may just equal recent form.")

# --- table 2: opponent's whole-team defensive trend --------------------------
if profile:
    st.markdown(f"**{row['Opp']} — whole-team defensive trend (not player- or position-specific)**")
    odf = pd.DataFrame(profile)[["Market", "Opp Recent Allowed", "Opp Season Allowed", "Defense Trend",
                                 "Trend Tag"]]
    odf = odf.rename(columns={"Opp Recent Allowed": "Opp Team Total (recent)",
                              "Opp Season Allowed": "Opp Team Total (season)"})
    st.dataframe(
        odf.style.format({"Opp Team Total (recent)": "{:.1f}", "Opp Team Total (season)": "{:.1f}",
                          "Defense Trend": "{:.2f}×"}, na_rep="—")
        .theme_gradient(cmap="RdYlGn", subset=["Defense Trend"]),
        hide_index=True, width="stretch",
    )
    st.caption(
        f"\"Opp Team Total\" = {row['Opp']}'s **entire team combined**, not a per-player or "
        "per-position figure. 🟢 Green / looser lately = they've been allowing MORE than usual — "
        f"good news for {row['Player']}'s counting stats. 🔴 Red / tighter lately = allowing less. "
        "Each market has its own independent trend.")

with st.expander("Full column reference"):
    st.markdown("""
**Player signals**
- **Recent Avg** — the player's own bootstrap-model average over their last games on file, no
  opponent adjustment (the same number Best Bets/Edge Board price off).
- **Season Avg** — their full-season average (any opponent). H2H Avg is compared against THIS,
  not Recent Avg — that separates "this team's specific effect on them" from "they're just been
  hot or cold lately," which a short recency window alone can't distinguish.
- **H2H Avg / H2H Games** — their actual average in every game their team has played against this
  specific opponent *this season*. Most FBS opponents meet once a season, so a small — usually
  zero — sample here is expected, not a bug.
- **Notes** — 🎯 flags the one market (if any) where H2H performance is distinctly lower than
  their other markets against this same opponent. ⚠️ flags a wide swing between H2H meetings
  (shown as the min–max spread) — a real signal, but a less trustworthy one than a consistent
  small sample.

**Opponent signals**
- **Opp Team Total (recent / season)** — this week's opponent's WHOLE TEAM combined total at
  each stat, over their last 5 games vs. their full season so far.
- **Defense Trend** — Team Total (recent) ÷ Team Total (season). See the note above that table
  for what the color and tags mean.
    """)

# --- supporting detail: recent game log + H2H game log ----------------------
gc1, gc2 = st.columns(2)
with gc1:
    st.markdown("**Recent games (any opponent)**")
    if log:
        rec_df = pd.DataFrame([{"Week": g.get("week", "—"), "Opp": g.get("opponent_team", "—"),
                                "Pass Yds": g.get("passing_YDS", 0), "Rush Yds": g.get("rushing_YDS", 0),
                                "Rec": g.get("receiving_REC", 0), "Rec Yds": g.get("receiving_YDS", 0)}
                               for g in log])
        st.dataframe(rec_df, hide_index=True, width="stretch", height=250)
    else:
        st.caption("No recent games on file.")

with gc2:
    st.markdown(f"**Games vs {row['Opp']} this season**")
    if h2h_log:
        h2h_df = pd.DataFrame([{"Week": g.get("week", "—"),
                                "Pass Yds": g.get("passing_YDS", 0), "Rush Yds": g.get("rushing_YDS", 0),
                                "Rec": g.get("receiving_REC", 0), "Rec Yds": g.get("receiving_YDS", 0)}
                               for g in h2h_log])
        st.dataframe(h2h_df, hide_index=True, width="stretch", height=250)
    else:
        st.caption("No meetings yet this season.")

st.caption("v1 signals — no positional matchup data (which defender/scheme is likely to see this "
          "player), no pace adjustment. Recent Avg here is deliberately NOT adjusted by the "
          "Defense Trend column — this page shows the raw signals side by side so you can weigh "
          "them yourself, not one blended number. TD-allowed column names are a plausible, not "
          "yet live-verified guess — see this page's own module docstring.")
