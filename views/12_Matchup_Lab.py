"""
Matchup Lab — WNBA player-vs-opponent deep-dive.

The honest WNBA counterpart to MLB's Matchup Lab: MLB's version is pitch-type granular
(Statcast tracks every pitch), which has no free WNBA equivalent. This is built on three real,
computable signals instead — recent form (what the model already prices off), head-to-head
history vs this exact opponent this season, and the opponent's recent-vs-season defensive trend
(built on the same box-score infrastructure Hot Hand Engine uses, extended with a season-wide
scan for the head-to-head piece).
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

_active = sports.active()

st.title("🔬 Matchup Lab")
st.caption("One player, one opponent, three real signals: recent form, head-to-head history "
           "this season, and whether the opponent's defense has been trending looser or "
           "tighter lately — the honest WNBA counterpart to Dinger Engine's pitch-type "
           "Matchup Lab (no free WNBA equivalent to Statcast exists, so this leans on box-score "
           "signals instead, the same foundation Hot Hand Engine is built on).")

if not sports.require_sport("WNBA", "Matchup Lab"):
    st.stop()

E, P = _active.engine, _active.projections
eastern = pytz.timezone("US/Eastern")


def get_api_key():
    try:
        return st.secrets["ODDS_API_KEY"]
    except Exception:
        return os.environ.get("ODDS_API_KEY")


@st.cache_data(ttl=300, show_spinner=False)
def load_slate(date_str: str):
    rows, meta = E.build_slate(date_str)
    return rows, len(meta)


@st.cache_data(ttl=300, show_spinner=False)
def load_matchup(date_str: str, player_id: int, team_id: int, opp_id: int):
    h2h_log = E.get_player_history_vs_opponent(player_id, team_id, opp_id, date_str)
    season_log = E.get_player_season_games(player_id, team_id, date_str)              # full season, any opponent
    opp_recent = E.get_team_recent_allowed_stats(opp_id, date_str)                    # last 10
    opp_season = E.get_team_recent_allowed_stats(opp_id, date_str, n=82, days_back=200)  # season-wide
    team_rest = E.get_team_rest_info(team_id, date_str)
    opp_rest = E.get_team_rest_info(opp_id, date_str)
    return h2h_log, season_log, opp_recent, opp_season, team_rest, opp_rest


@st.cache_data(ttl=300, show_spinner=False)
def load_offers(sport_key: str, date_str: str, markets_tuple: tuple, _api_key: str):
    # One fetch covers the WHOLE slate (every game, every player) — cached by (date, markets, key)
    # so switching between players on this page never re-fetches; only a genuinely new date/key
    # combination costs quota. Same button-gated, cached pattern as Edge Board's live-odds fetch.
    sport = sports.get(sport_key)
    offers, info = O.fetch_slate_props(date_str, _api_key, list(markets_tuple),
                                       sport=sport.odds_sport_key)
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

with st.spinner("Loading tonight's slate..."):
    rows, n_games = load_slate(date_str)

if not rows:
    st.info(f"No projectable players for this date. Pick a date with scheduled {_active.label} games.")
    st.stop()

rows_sorted = sorted(rows, key=lambda r: (r["GameLabel"], r["Player"]))
options = {f"{r['Player']} ({r['Team']}) — {r['GameLabel']}": r for r in rows_sorted}
choice = st.selectbox("Player", list(options.keys()))
row = options[choice]

pid, team_id, opp_id = row["_pid"], row["_team_id"], row["_opp_id"]
if team_id is None or opp_id is None:
    st.error("This player's team/opponent couldn't be resolved — try refreshing the slate.")
    st.stop()

with st.spinner(f"Pulling {row['Opp']}'s matchup history and defensive trend..."):
    h2h_log, season_log, opp_recent, opp_season, team_rest, opp_rest = load_matchup(
        date_str, pid, team_id, opp_id)

profile = P.build_matchup_profile(row, h2h_log, opp_recent, opp_season, season_log=season_log)

st.markdown(f"### {row['Player']} vs {row['Opp']}")
st.caption(f"{row['GameLabel']}  ·  averaging {row['AvgMin']:.0f} min/game over their last "
           f"{len(row.get('_game_log') or [])} games")


def _rest_line(label: str, rest: dict) -> str:
    days = rest.get("rest_days")
    if days is None:
        return f"{label}: rest unknown (no recent game on file)"
    if rest.get("is_back_to_back"):
        return f"⚠️ {label}: back-to-back (played yesterday)"
    return f"{label}: {days} day{'s' if days != 1 else ''} rest"


rc1, rc2 = st.columns(2)
with rc1:
    st.caption(_rest_line(row["Team"], team_rest))
with rc2:
    st.caption(_rest_line(row["Opp"], opp_rest))

st.info(
    f"**How {row['Player']} does against {row['Opp']} specifically, vs. how she's played "
    "overall:** the table below compares her head-to-head average against this exact opponent "
    "to her SEASON average (not just her last-10 recent form) — that isolates what THIS TEAM "
    "does to her specifically from her just being generally hot or cold lately. A wide swing "
    "between her H2H games (⚠️ flagged) is a real but less trustworthy signal than a small, "
    "consistent one. 🎯 A flagged market means her performance in THAT specific stat is "
    "distinctly lower against this team than her other stats are — the closest honest read on "
    "\"how do they play her\" that box-score data supports (not a scheme detail — just which "
    "specific stat category dips more than the others).", icon="🎯")

# --- trend charts: is she trending toward or away from the number? ----------
st.markdown(f"**{row['Player']} — recent-form trend vs. the line**")

api_key = get_api_key()
if not api_key:
    st.caption("🔑 No `ODDS_API_KEY` found — charts below show the model's own default line "
               "instead of tonight's actual sportsbook number. Add the key to `.streamlit/"
               "secrets.toml` or the `ODDS_API_KEY` environment variable, then reload, to see "
               "the real line.")
elif st.button("📡 Fetch live lines", help="One fetch covers every player/market on tonight's "
               "slate — switching players afterward reuses it at no extra API cost."):
    st.session_state["matchup_lab_fetch_odds"] = True

offers, offers_info = [], {}
if api_key and st.session_state.get("matchup_lab_fetch_odds"):
    try:
        with st.spinner("Fetching live lines..."):
            offers, offers_info = load_offers(_active.key, date_str, tuple(_active.markets), api_key)
    except O.OddsAPIError as e:
        st.error(f"Odds API error: {e}")

if offers_info:
    st.caption(f"Quota remaining: {offers_info.get('remaining', '—')} · "
               f"games priced: {offers_info.get('events_fetched', '—')}/{offers_info.get('events_total', '—')}")

live_lines = O.market_lines_for_player(offers, row["Player"], projections_module=P) if offers else {}

log = row.get("_game_log") or []
trend_log = P.build_trend_series(log)   # oldest -> newest, for left-to-right reading
tc1, tc2 = st.columns(2)
tc3, tc4 = st.columns(2)
for (mkey, col, disp), slot in zip(P.market_list(), (tc1, tc2, tc3, tc4)):
    stat_key = P.stat_key_for(col)
    with slot:
        if not trend_log:
            st.caption(f"{disp}: no recent games on file yet.")
            continue
        line_val = live_lines.get(mkey)
        is_live = line_val is not None
        if line_val is None:
            line_val = P.default_line(mkey)
        xs = [g.get("date", "—")[5:10] for g in trend_log]   # MM-DD, short enough for a small chart
        ys = [g.get(stat_key, 0.0) for g in trend_log]
        hover = [f"{disp}: {y:g}<br>vs {g.get('opp', '—')}" for y, g in zip(ys, trend_log)]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name=disp,
                                 line=dict(color="#3b82f6"), marker=dict(size=8),
                                 text=hover, hoverinfo="text"))
        if line_val is not None:
            fig.add_hline(y=line_val, line_dash="dash", line_color="#f97316",
                         annotation_text=f"{'Line' if is_live else 'Model default'}: {line_val:g}",
                         annotation_position="top left")
        fig.update_xaxes(type="category")   # MM-DD strings are LABELS, not dates — stops Plotly
                                            # from auto-parsing them as full dates (which produced
                                            # nonsense years like "Sep 1, 2007" on a single point)
        fig.update_layout(template="plotly_white", height=220,
                          margin=dict(l=10, r=10, t=30, b=10), title=disp,
                          showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
st.caption("Dashed line is tonight's actual sportsbook number once fetched above; otherwise it's "
           "the model's own default line, clearly labeled as such, never presented as a live "
           "quote it isn't.")

# --- table 1: player signals (recent form / season form / this matchup) -----
pdf = pd.DataFrame(profile)[["Market", "Recent Avg", "Season Avg", "H2H Avg", "H2H Games",
                             "H2H Spread", "High Variance", "Suppressed"]]


def _notes(r):
    bits = []
    if r["Suppressed"]:
        bits.append("🎯 Suppressed vs her other markets")
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
               "may just equal her recent form.")

# --- table 2: opponent's whole-team defensive trend --------------------------
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
    "own norm. 🟢 Green / looser lately = they've been allowing MORE than usual — good news for "
    f"{row['Player']}'s counting stats. 🔴 Red / tighter lately = allowing less. Each market has "
    "its own independent trend.")

with st.expander("Full column reference"):
    st.markdown("""
**Player signals**
- **Recent Avg** — the player's own bootstrap-model average over her last 10 games, no opponent
  adjustment (the same number Best Bets/Edge Board price off).
- **Season Avg** — her full-season average (any opponent). H2H Avg is compared against THIS, not
  Recent Avg — that separates "this team's specific effect on her" from "she's just been hot or
  cold lately," which a 10-game recency window alone can't distinguish.
- **H2H Avg / H2H Games** — her actual average in every game her team has played against this
  specific opponent *this season*. Teams typically meet 2-4 times a season, so a small sample
  here is expected, not a bug — read it as a data point, not a verdict.
- **Notes** — 🎯 flags the one market (if any) where her H2H performance is distinctly lower than
  her other markets against this same opponent. ⚠️ flags a wide swing between her H2H meetings
  (shown as the min–max spread) — a real signal, but a less trustworthy one than a consistent
  small sample.

**Opponent signals**
- **Opp Team Total (recent / season)** — tonight's opponent's WHOLE TEAM combined total at each
  stat, over their last 10 games vs. their full season (same recent number Hot Hand Engine uses).
- **Defense Trend** — Team Total (recent) ÷ Team Total (season). See the note above that table
  for what the color and tags mean.
    """)

# --- supporting detail: recent game log + H2H game log ----------------------
gc1, gc2 = st.columns(2)
with gc1:
    st.markdown("**Recent games (any opponent)**")
    log = row.get("_game_log") or []
    if log:
        rec_df = pd.DataFrame([{"Date": g.get("date", "—")[:10], "Opp": g.get("opp", "—"),
                                "PTS": g.get("pts", 0), "REB": g.get("reb", 0),
                                "AST": g.get("ast", 0), "3PM": g.get("fg3m", 0),
                                "MIN": g.get("min", 0)} for g in log])
        st.dataframe(rec_df, hide_index=True, use_container_width=True, height=250)
    else:
        st.caption("No recent games on file.")

with gc2:
    st.markdown(f"**Games vs {row['Opp']} this season**")
    if h2h_log:
        h2h_df = pd.DataFrame([{"Date": g.get("date", "—")[:10], "PTS": g.get("pts", 0),
                                "REB": g.get("reb", 0), "AST": g.get("ast", 0),
                                "3PM": g.get("fg3m", 0), "MIN": g.get("min", 0)} for g in h2h_log])
        st.dataframe(h2h_df, hide_index=True, use_container_width=True, height=250)
    else:
        st.caption("No meetings yet this season.")

st.caption("v1 signals — no positional matchup data (who's likely to guard this player), no pace "
           "adjustment. Recent Avg here is deliberately NOT adjusted by the Defense Trend column "
           "(unlike Hot Hand Engine's Matchup Score) — this page is meant to show you the raw "
           "signals side by side so you can weigh them yourself, not hand you one blended number.")
