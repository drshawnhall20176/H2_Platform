"""
NFL Matchup Lab — one player, one opponent, real signals: recent form, head-to-head history this
season, and whether the opponent's defense has been trending looser or tighter lately.

BUILT AS ITS OWN PAGE, NOT ADDED TO THE EXISTING WNBA/NBA/NCAAMB MATCHUP LAB — a real decision,
not an oversight. Two genuine differences in NFL's data shape made reusing that exact page the
wrong call: nfl_engine.get_team_injuries takes (team_abbr, season, week) — richer and more
precise than basketball's (team_abbr) alone, since NFL's real injury data is genuinely week-
specific — and weakening that to fit the shared page's 1-arg convention would throw away real
value. And NFL's game-log records use nflreadpy's own raw columns (week, opponent_team,
passing_yards, ...) rather than basketball's engine-added opp/date convenience fields. Same
conventions and spirit as the WNBA/NBA/NCAAMB page throughout (time slot + game filters, trend
charts against the line, recent-form/season-form/head-to-head table, opponent defensive trend
table) — adapted, not reinvented, for what NFL's real data actually looks like.
"""

import os

import streamlit as st
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import pytz

import sports
import odds_api as O
import nfl_engine as E
import nfl_projections as P

_active = sports.active()
game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER   # shared with Best Bets

st.title("🔬 Matchup Lab")
st.caption("One player, one opponent, three real signals: recent form, head-to-head history this "
          "season, and whether the opponent's defense has been trending looser or tighter "
          "lately — the honest NFL counterpart to WNBA/NBA/NCAAMB's own Matchup Lab, built on "
          "NFL's real data shape (weekly slates, week-specific injury reports) rather than a "
          "forced port of the basketball version.")

if not sports.require_sport(["NFL"], "Matchup Lab"):
    st.stop()

eastern = pytz.timezone("US/Eastern")


def get_api_key():
    try:
        return st.secrets["ODDS_API_KEY"]
    except Exception:
        return os.environ.get("ODDS_API_KEY")


@st.cache_data(ttl=300, show_spinner=False)
def load_slate(date_str: str):
    rows, meta = E.build_slate(date_str)
    team_abbrs = E.team_abbrs_from_meta(meta)   # zero extra cost — meta already has this
    return rows, len(meta), team_abbrs


@st.cache_data(ttl=300, show_spinner=False)
def load_injuries(date_str: str, team_abbr, opp_abbr):
    season = E._infer_season(date_str)
    schedule = E.get_schedule(season) if season is not None else []
    week = E._resolve_week(schedule, date_str) if schedule else None
    if season is None or week is None:
        return [], []
    return E.get_team_injuries(team_abbr, season, week), E.get_team_injuries(opp_abbr, season, week)


@st.cache_data(ttl=300, show_spinner=False)
def load_matchup(date_str: str, player_id: str, opp_abbr: str, team_abbr: str):
    h2h_log = E.get_player_history_vs_opponent(player_id, opp_abbr, date_str)
    season_log = E.get_player_season_games(player_id, date_str)
    opp_recent = E.get_team_allowed_stats(opp_abbr, date_str, n=5)
    opp_season = E.get_team_allowed_stats(opp_abbr, date_str, n=None)
    team_rest = E.get_team_rest_info(team_abbr, date_str)
    opp_rest = E.get_team_rest_info(opp_abbr, date_str)
    return h2h_log, season_log, opp_recent, opp_season, team_rest, opp_rest


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
    rows, n_games, team_abbrs = load_slate(date_str)

if not rows:
    st.info("No projectable players for this date. Pick a date within an NFL week with a real slate.")
    st.stop()

rows_sorted = sorted(rows, key=lambda r: (r["GameLabel"], r["Player"]))

# Time slot + Game filters — same convention Best Bets/basketball Matchup Lab already established
# (shared via sports.py), doubly useful here: an NFL week's games span Thu-Mon across multiple
# calendar dates, all resolving to the SAME slate, so narrowing by actual game matters more than
# it would for a single-date sport.
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
game_labels = {g: (f"{P.format_et(game_date_by_label[g])} — {g}" if P.format_et(game_date_by_label[g]) else g)
              for g in games_present}

with c_game:
    game_pick = st.selectbox("Game", ["All games in this slot"] + games_present,
                             format_func=lambda g: game_labels.get(g, g))
final_rows = slot_rows if game_pick == "All games in this slot" else [r for r in slot_rows if r["GameLabel"] == game_pick]

if not final_rows:
    st.info("No players match the current filters — try a different time slot or game.")
    st.stop()

options = {f"{r['Player']} ({r['Team']}) — {r['GameLabel']}": r for r in final_rows}
choice = st.selectbox("Player", list(options.keys()))
row = options[choice]

pid, opp_abbr, team_abbr = row["_pid"], row["_opp_id"], row["_team_id"]
if not row.get("_markets"):
    st.info(f"{row['Player']} doesn't have a market projected this week — try a different player.")
    st.stop()

with st.spinner(f"Pulling {row['Opp']}'s matchup history and defensive trend..."):
    h2h_log, season_log, opp_recent, opp_season, team_rest, opp_rest = load_matchup(
        date_str, pid, opp_abbr, team_abbr)

profile = P.build_matchup_profile(row, h2h_log, opp_recent, opp_season, season_log=season_log)

st.markdown(f"### {row['Player']} vs {row['Opp']}")
st.caption(f"{row['GameLabel']}  ·  {row['Position']}  ·  averaging over their last "
          f"{len(row.get('_recent_games') or [])} game(s) on file")


def _rest_line(label: str, rest: dict) -> str:
    days = rest.get("rest_days")
    if days is None:
        return f"{label}: rest unknown (no recent game on file)"
    if rest.get("is_short_week"):
        return f"⚠️ {label}: short week ({days} days rest, likely a Thursday game)"
    return f"{label}: {days} day{'s' if days != 1 else ''} rest"


rc1, rc2 = st.columns(2)
with rc1:
    st.caption(_rest_line(row["Team"], team_rest))
with rc2:
    st.caption(_rest_line(row["Opp"], opp_rest))

team_injuries, opp_injuries = load_injuries(date_str, team_abbr, opp_abbr)
if team_injuries or opp_injuries:
    with st.expander("🏥 Injury report — both teams"):
        for label, injuries in ((row["Team"], team_injuries), (row["Opp"], opp_injuries)):
            if not injuries:
                continue
            st.markdown(f"**{label}**")
            idf = pd.DataFrame(injuries)[["player", "position", "status", "return_date", "comment"]]
            idf = idf.rename(columns={"player": "Player", "position": "Pos", "status": "Status",
                                      "return_date": "Est. Return", "comment": "Comment"})
            st.dataframe(idf, hide_index=True, use_container_width=True)
        st.caption("Sourced from nflverse's real weekly injury reports — informational only, not "
                  "folded into any signal on this page. \"Questionable\" isn't a hard out; "
                  "\"Est. Return\" is always blank — NFL's real injury data doesn't include an "
                  "estimated return date the way some other sources do, so this stays honestly "
                  "empty rather than guessed.")

st.info(
    f"**How {row['Player']} does against {row['Opp']} specifically, vs. how they've played "
    "overall:** the table below compares their head-to-head average against this exact opponent "
    "to their SEASON average (not just recent form) — that isolates what THIS TEAM does to them "
    "specifically from just being generally hot or cold lately. Expect H2H to be empty far more "
    "often than in any other sport on this platform — most NFL opponents meet exactly once a "
    "season (division rivals twice), so an empty H2H table is the common case here, not a gap.",
    icon="🎯")

# --- trend charts: is he trending toward or away from the number? ----------
st.markdown(f"**{row['Player']} — recent-form trend vs. the line**")

api_key = get_api_key()
if not api_key:
    st.caption("🔑 No `ODDS_API_KEY` found — charts below show the model's own default line "
              "instead of tonight's actual sportsbook number. Add the key to `.streamlit/"
              "secrets.toml` or the `ODDS_API_KEY` environment variable, then reload, to see "
              "the real line.")
elif st.button("📡 Fetch live lines", help="One fetch covers every player/market on this week's "
              "slate — switching players afterward reuses it at no extra API cost."):
    st.session_state["nfl_matchup_lab_fetch_odds"] = True

offers, offers_info = [], {}
if api_key and st.session_state.get("nfl_matchup_lab_fetch_odds"):
    try:
        with st.spinner("Fetching live lines..."):
            offers, offers_info = load_offers(date_str, tuple(_active.markets), api_key)
    except O.OddsAPIError as e:
        st.error(f"Odds API error: {e}")

if offers_info:
    st.caption(f"Quota remaining: {offers_info.get('remaining', '—')} · "
              f"games priced: {offers_info.get('events_fetched', '—')}/{offers_info.get('events_total', '—')}")

live_lines = O.market_lines_for_player(offers, row["Player"], projections_module=P) if offers else {}

log = row.get("_recent_games") or []
trend_log = P.build_trend_series(log)   # oldest -> newest, for left-to-right reading
market_slots = P.market_list()          # only 1-3 entries for a real row, position-gated already
active_markets = [(mkey, col, disp) for mkey, col, disp in market_slots if mkey in row["_markets"]]
chart_cols = st.columns(len(active_markets)) if active_markets else []
for (mkey, col, disp), slot in zip(active_markets, chart_cols):
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
        fig.update_xaxes(type="category")   # "Wk N" strings are LABELS, not dates — same guard
                                            # against Plotly's date auto-parsing every other
                                            # sport's trend chart already needed.
        fig.update_layout(template="plotly_white", height=220,
                          margin=dict(l=10, r=10, t=30, b=10), title=disp,
                          showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
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
        hide_index=True, use_container_width=True,
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
        hide_index=True, use_container_width=True,
    )
    st.caption(
        f"\"Opp Team Total\" = {row['Opp']}'s **entire team combined**, not a per-player or "
        "per-position figure — there's no per-position or per-defender data here, just whether "
        "this team's overall defense at each stat has been trending looser or tighter than their "
        "own norm. 🟢 Green / looser lately = they've been allowing MORE than usual — good news "
        f"for {row['Player']}'s counting stats. 🔴 Red / tighter lately = allowing less. Each "
        "market has its own independent trend.")

with st.expander("Full column reference"):
    st.markdown("""
**Player signals**
- **Recent Avg** — the player's own bootstrap-model average over their last games on file, no
  opponent adjustment (the same number Best Bets/Edge Board price off).
- **Season Avg** — their full-season average (any opponent). H2H Avg is compared against THIS,
  not Recent Avg — that separates "this team's specific effect on them" from "they're just been
  hot or cold lately," which a short recency window alone can't distinguish.
- **H2H Avg / H2H Games** — their actual average in every game their team has played against this
  specific opponent *this season*. Most NFL opponents meet once a season (division rivals
  twice), so a small — usually zero — sample here is expected, not a bug.
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
                                "Pass Yds": g.get("passing_yards", 0), "Rush Yds": g.get("rushing_yards", 0),
                                "Rec": g.get("receptions", 0), "Rec Yds": g.get("receiving_yards", 0)}
                               for g in log])
        st.dataframe(rec_df, hide_index=True, use_container_width=True, height=250)
    else:
        st.caption("No recent games on file.")

with gc2:
    st.markdown(f"**Games vs {row['Opp']} this season**")
    if h2h_log:
        h2h_df = pd.DataFrame([{"Week": g.get("week", "—"),
                                "Pass Yds": g.get("passing_yards", 0), "Rush Yds": g.get("rushing_yards", 0),
                                "Rec": g.get("receptions", 0), "Rec Yds": g.get("receiving_yards", 0)}
                               for g in h2h_log])
        st.dataframe(h2h_df, hide_index=True, use_container_width=True, height=250)
    else:
        st.caption("No meetings yet this season.")

st.caption("v1 signals — no positional matchup data (which defender/scheme is likely to see this "
          "player), no pace adjustment (NFL has no direct \"possessions\" equivalent basketball's "
          "per-100 normalization needs). Recent Avg here is deliberately NOT adjusted by the "
          "Defense Trend column — this page shows the raw signals side by side so you can weigh "
          "them yourself, not one blended number.")
