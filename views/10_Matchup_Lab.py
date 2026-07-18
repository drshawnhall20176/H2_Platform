"""
Matchup Lab — pitch-level arsenal vs. hitter vulnerability.

Season rate stats say whether a hitter is good; this says *how to get him out*. Pick a probable
starter and an opposing hitter, and the Lab pairs the pitcher's arsenal (what he throws, how much
he misses bats with each pitch) against the hitter's performance by pitch family — then flags the
specific pitches to attack with.

Reads the nightly-cached tables from matchup_data (data/pitcher_arsenals.csv,
data/hitter_pitch_splits.csv). It never pulls pitch-level Statcast live — that job belongs to
refresh_matchups.py / the nightly Action.
"""

import pandas as pd
import streamlit as st
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import plotly.graph_objects as go

import sports
import mlb_engine as E
import matchup_data as MD
from datetime import datetime

game_dt, slot_of, SLOT_ORDER = sports.game_dt, sports.slot_of, sports.SLOT_ORDER   # shared with Best Bets

st.title("🔬 Matchup Lab")
st.caption("Pitch-level arsenal vs. hitter vulnerability — the specific pitches to attack with. "
           "Season stats tell you *if* a hitter is good; this tells you *how* to get him out.")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_matchup_cache():
    return MD.load()


@st.cache_data(ttl=300, show_spinner="Loading probable starters…")
def load_pitchers(date_str: str):
    return E.build_pitching_slate(date_str)


@st.cache_data(ttl=300, show_spinner="Loading hitters…")
def load_hitters(date_str: str):
    rows, _meta = E.build_slate(date_str)
    return rows


arsenals, hitter_splits = load_matchup_cache()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_hitter_type_cache():
    return MD.load_hitter_types()

# --- empty-state: cache not built yet -------------------------------------------------------
if not arsenals or not hitter_splits:
    st.info("**Pitch-level data isn't cached yet.** The Matchup Lab reads two tables built by a "
            "nightly job. Run `python refresh_matchups.py` (or wait for the scheduled Action) to "
            "pull the season's pitch-level Statcast and populate:\n\n"
            "- `data/pitcher_arsenals.csv`\n- `data/hitter_pitch_splits.csv`\n\n"
            "This page will light up once those exist.")
    st.stop()

c1, c2 = st.columns([3, 1])
with c1:
    date_str = st.date_input("Slate date", datetime.now()).strftime("%Y-%m-%d")
with c2:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

pitchers = load_pitchers(date_str)
if not pitchers:
    st.warning("No probable starters found for this date yet — check back closer to game time.")
    st.stop()

# Time slot + Game filters — same shared helpers Best Bets and the WNBA/NBA/NCAAMB/NFL Matchup
# Lab pages already use, narrowing a busy night's pitcher list before picking one. Two pitchers
# share a game (home/away starter), so filtering is by the shared "Game" label, not per-pitcher.
for r in pitchers:
    r["_slot"] = slot_of(game_dt(r.get("_game_date")))
slots_present = sorted({r["_slot"] for r in pitchers}, key=lambda s: SLOT_ORDER.get(s, 9))

c_slot, c_game = st.columns(2)
with c_slot:
    slot_pick = st.selectbox("Time slot", ["All slate"] + slots_present)
slot_pitchers = pitchers if slot_pick == "All slate" else [r for r in pitchers if r["_slot"] == slot_pick]

if not slot_pitchers:
    st.info(f"No probable starters in the {slot_pick} slot — try a different time slot or \"All slate\".")
    st.stop()

game_date_by_label: dict = {}
for r in slot_pitchers:
    game_date_by_label.setdefault(r["Game"], r.get("_game_date"))
games_present = sorted(game_date_by_label, key=lambda g: game_date_by_label[g] or "~")


def _game_label_fmt(g: str) -> str:
    dt = game_dt(game_date_by_label.get(g))   # already Eastern-localized by game_dt itself
    if dt is None:
        return g
    return f"{dt.strftime('%-I:%M %p ET')} — {g}"


with c_game:
    game_pick = st.selectbox("Game", ["All games in this slot"] + games_present,
                             format_func=lambda g: _game_label_fmt(g) if g != "All games in this slot" else g)
final_pitchers = (slot_pitchers if game_pick == "All games in this slot"
                 else [r for r in slot_pitchers if r["Game"] == game_pick])

if not final_pitchers:
    st.info("No probable starters match the current filters — try a different time slot or game.")
    st.stop()

# Pitcher picker (only those we have arsenal data for are useful, but show all with a flag).
p_by_label = {}
for r in final_pitchers:
    pid = r.get("_pid")
    has = pid in arsenals
    label = f"{r['Pitcher']} ({r['Team']}){'' if has else '  — no pitch data'}"
    p_by_label[label] = r
p_label = st.selectbox("Pitcher (type to search)", sorted(p_by_label.keys()))
pitcher = p_by_label[p_label]
pitcher_pid = pitcher.get("_pid")

# --- Bullpen instead of the starter -----------------------------------------
# The whole point: a lineup can struggle against a real ace and still erupt once his team's
# bullpen takes over — a genuinely different matchup once the starter leaves. The underlying
# arsenal/hitter-vulnerability data already covers every pitcher who threw a pitch that season,
# not just probable starters (confirmed during scoping — matchup_data.py's refresh pulls Savant's
# whole-league pitch log), so this needed a picker extension, not new modeling.
st.caption("💡 A lineup that struggles against tonight's starter can look very different once "
          "his bullpen takes over — check a specific reliever below instead.")
use_bullpen = st.checkbox(f"🔄 Look at {pitcher['Team']}'s bullpen instead of {pitcher['Pitcher']}")


@st.cache_data(ttl=1800, show_spinner=False)
def load_pitching_staff(team_id, exclude_pid):
    if not team_id:
        return []
    return E.get_team_pitching_staff(team_id, exclude_pid=exclude_pid)


if use_bullpen:
    staff = load_pitching_staff(pitcher.get("_team_id"), pitcher_pid)
    if not staff:
        st.warning(f"No active pitching staff found for {pitcher['Team']} — showing "
                  f"{pitcher['Pitcher']} instead.")
    else:
        staff_by_label = {}
        for s in staff:
            has = s["id"] in arsenals
            staff_by_label[f"{s['name']}{'' if has else '  — no pitch data'}"] = s
        reliever_label = st.selectbox("Reliever (type to search)", sorted(staff_by_label.keys()))
        reliever = staff_by_label[reliever_label]
        with st.spinner(f"Loading {reliever['name']}'s season stats..."):
            rm = E.get_pitcher_metrics(reliever["id"], E.FIP_CONSTANT_DEFAULT)
        # Same field shape build_pitching_slate's rows use, so every downstream reference below
        # (pitcher["Pitcher"]/["Team"]/.get("_team_id") etc.) works unchanged for a reliever too —
        # this is a swap of WHICH pitcher feeds the rest of the page, not a second code path.
        pitcher = {
            "Pitcher": rm.name, "_pid": rm.id, "Team": pitcher["Team"],
            "Opponent": pitcher["Opponent"], "Game": pitcher["Game"], "Hand": rm.hand,
            "_game_date": pitcher.get("_game_date"), "_team_id": pitcher.get("_team_id"),
            "_opp_id": pitcher.get("_opp_id"),
            "ERA": round(rm.era, 2), "FIP": rm.fip, "Delta": round(rm.era - rm.fip, 2),
            "K/9": round(rm.k9, 1), "WHIP": round(rm.whip, 2), "HR/9": round(rm.hr9, 2), "OBA": rm.oba,
        }
        pitcher_pid = pitcher["_pid"]
        if not rm.has_stats:
            st.caption(f"⚪ No season pitching line found for {rm.name} yet — arsenal data below "
                      "may still be useful, but ERA/FIP won't be.")

# Hitters: default to the pitcher's opponent, fall back to the whole slate.
hitters = load_hitters(date_str)
opp = pitcher.get("Opponent")
opp_hitters = [h for h in hitters if h.get("Team") == opp] or hitters
h_by_label = {}
for h in opp_hitters:
    hid = h.get("_pid")
    has = hid in hitter_splits
    label = f"{h.get('Hitter', '?')} ({h.get('Team', '')}){'' if has else '  — no pitch data'}"
    h_by_label[label] = h
h_label = st.selectbox(f"Hitter (opposing {opp or 'lineup'} — type to search)",
                       sorted(h_by_label.keys()))
hitter = h_by_label[h_label]
hitter_hid = hitter.get("_pid")


@st.cache_data(ttl=1800, show_spinner=False)
def load_injuries(team_id):
    if not team_id:
        return []
    return E.get_team_injuries(team_id)


team_injuries = load_injuries(pitcher.get("_team_id"))
opp_injuries = load_injuries(pitcher.get("_opp_id"))
if team_injuries or opp_injuries:
    with st.expander("🏥 Injury report — both teams"):
        for label, injuries in ((pitcher["Team"], team_injuries), (opp or "Opponent", opp_injuries)):
            if not injuries:
                continue
            st.markdown(f"**{label}**")
            idf = pd.DataFrame(injuries)[["player", "position", "status", "return_date", "comment"]]
            idf = idf.rename(columns={"player": "Player", "position": "Pos", "status": "Status",
                                      "return_date": "Est. Return", "comment": "Comment"})
            st.dataframe(idf, hide_index=True, use_container_width=True)
        st.caption("Sourced from MLB Stats API's own roster status field — any player not on "
                  "Active status (10/15/60-day IL, restricted, bereavement, paternity, etc.), "
                  "using MLB's own description for that status. \"Est. Return\" and \"Comment\" "
                  "are always blank — the roster endpoint reports a status, not a detailed "
                  "injury description (body part, expected return), so this stays honestly "
                  "empty rather than guessed. Informational only, not folded into any signal "
                  "on this page.")

st.divider()

# --- the matchup: arsenal joined to the hitter's family vulnerability ------------------------
rows = MD.build_matchup(pitcher_pid, hitter_hid, arsenals, hitter_splits)
if not rows:
    st.warning(f"No cached pitch data for **{pitcher['Pitcher']}** — pick another starter, or the "
               "nightly refresh hasn't captured enough of his pitches yet.")
    st.stop()

have_hitter = any(r["score"] is not None for r in rows)

# Headline insight — the single takeaway.
if have_hitter:
    best = rows[0]
    st.markdown(f"### 🎯 Attack **{hitter['Hitter']}** with the **{best['pitch_name']}**")
    st.caption(f"{pitcher['Pitcher']} throws it {best['usage']*100:.0f}% of the time and misses "
               f"bats {best['p_whiff']*100:.0f}% per swing. {hitter['Hitter']} whiffs "
               f"{(best['h_whiff'] or 0)*100:.0f}% vs {best['family'].lower()} and slugs "
               f"{best['h_slg'] or 0:.2f} against it. Matchup score is a scouting sort, not a "
               "probability.")
else:
    st.info(f"We have {pitcher['Pitcher']}'s arsenal, but no cached pitch-family data for "
            f"{hitter['Hitter']} yet — showing the arsenal alone.")

# --- table 1: the matchup grid (the money view) ---------------------------------------------
st.subheader("Matchup grid — arsenal × this hitter")
grid = pd.DataFrame([{
    "Pitch": r["pitch_name"],
    "Usage": r["usage"],
    "Velo": r["velo"],
    "P Whiff%": r["p_whiff"],
    "P PutAway%": r["p_putaway"],
    "H Whiff% (fam)": r["h_whiff"],
    "H SLG (fam)": r["h_slg"],
    "H xwOBA (fam)": r["h_xwoba"],
    "Score": r["score"],
} for r in rows])

# Coerce numeric (None-safe) so the gradient never chokes — the lesson from the Dinger fix.
for c in ["Usage", "Velo", "P Whiff%", "P PutAway%", "H Whiff% (fam)", "H SLG (fam)",
          "H xwOBA (fam)", "Score"]:
    grid[c] = pd.to_numeric(grid[c], errors="coerce")

styler = (grid.style
          .format({"Usage": "{:.0%}", "Velo": "{:.2f}", "P Whiff%": "{:.0%}", "P PutAway%": "{:.0%}",
                   "H Whiff% (fam)": "{:.0%}", "H SLG (fam)": "{:.2f}", "H xwOBA (fam)": "{:.2f}",
                   "Score": "{:.2f}"}, na_rep="—")
          # Green = high value on that stat, everywhere on the platform (same convention as the
          # Dinger Engine). P Whiff%/P PutAway%/Score stay pitcher-framed (green = good for the
          # pitcher); SLG/xwOBA are a hitter-quality stat, so they share Dinger's direction too.
          .theme_gradient(cmap="RdYlGn", subset=["P Whiff%", "P PutAway%", "H Whiff% (fam)", "Score"])
          .theme_gradient(cmap="RdYlGn", subset=["H SLG (fam)", "H xwOBA (fam)"]))
st.dataframe(styler, use_container_width=True, hide_index=True)
st.caption("Green favors the pitcher on Whiff%/PutAway%/Score. SLG/xwOBA color the same direction "
           "as every other page on the platform (high = green), so a hitter's power reads the same "
           "here as on the Dinger Engine. Hitter columns are by pitch **family** (Fastball / "
           "Breaking / Offspeed) for a stable sample; the pitch is mapped to its family.")

# --- pitch mix, visualized -------------------------------------------------------------------
# NOT a WNBA/NBA-style trend chart on purpose: that chart works because there's a real per-game
# time axis (10 dated recent games) to plot against. This data has no equivalent — arsenals/
# hitter_splits are season-aggregate snapshots PER PITCH, not a dated sequence, so there's no
# "recent form over time" to trend. What genuinely maps here is the same instinct (see it, don't
# just read a table) applied to what this data actually is: a COMPOSITION (pitch mix) and a
# MATCHUP (whiff rates compared), so a bar chart, not a line chart.
st.markdown("**Pitch mix, colored by matchup score**")
mix_rows = sorted(rows, key=lambda r: r["usage"] or 0, reverse=True)
mix_fig = go.Figure(go.Bar(
    x=[r["usage"] or 0 for r in mix_rows], y=[r["pitch_name"] for r in mix_rows],
    orientation="h",
    marker=dict(color=[r["score"] if r["score"] is not None else 0 for r in mix_rows],
               colorscale=[[0, "#c84242"], [0.5, "#f0d660"], [1, "#2e964e"]],
               cmin=0, cmax=1, showscale=have_hitter,
               colorbar=dict(title="Score", thickness=12) if have_hitter else None),
    text=[f"{(r['usage'] or 0)*100:.0f}%" for r in mix_rows], textposition="outside",
    hovertext=[f"{r['pitch_name']}: {(r['usage'] or 0)*100:.0f}% usage"
              + (f", score {r['score']:.2f}" if r["score"] is not None else "") for r in mix_rows],
    hoverinfo="text",
))
mix_fig.update_layout(template="plotly_white", height=max(220, 60 * len(mix_rows)),
                      margin=dict(l=10, r=10, t=10, b=10), xaxis_title="Usage%",
                      xaxis_tickformat=".0%", yaxis=dict(autorange="reversed"), showlegend=False)
st.plotly_chart(mix_fig, use_container_width=True)

if have_hitter:
    st.markdown("**Whiff rate: this pitch (pitcher) vs this family (hitter)**")
    wf_rows = sorted(rows, key=lambda r: (r["score"] if r["score"] is not None else -1), reverse=True)
    wf_fig = go.Figure()
    wf_fig.add_trace(go.Bar(x=[r["p_whiff"] or 0 for r in wf_rows], y=[r["pitch_name"] for r in wf_rows],
                            orientation="h", name=f"{pitcher['Pitcher']} whiff% (this pitch)",
                            marker=dict(color="#2563eb")))
    wf_fig.add_trace(go.Bar(x=[r["h_whiff"] or 0 for r in wf_rows], y=[r["pitch_name"] for r in wf_rows],
                            orientation="h", name=f"{hitter['Hitter']} whiff% (this family)",
                            marker=dict(color="#f97316")))
    wf_fig.update_layout(template="plotly_white", height=max(220, 60 * len(wf_rows)),
                         margin=dict(l=10, r=10, t=10, b=10), xaxis_title="Whiff%",
                         xaxis_tickformat=".0%", yaxis=dict(autorange="reversed"),
                         barmode="group", legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(wf_fig, use_container_width=True)
    st.caption("Both bars long = the strongest case to attack with that pitch (misses bats for "
               "the pitcher AND against this hitter). Blue long / orange short = a pitch that "
               "misses bats generally but not particularly against this hitter — usage and "
               "Score above already account for this, this just makes it visible at a glance.")
else:
    st.caption("Blue bars only — no cached hitter-side whiff data to pair against yet, showing "
               "arsenal mix alone.")

# --- table 2 + 3 side by side: raw arsenal and raw hitter splits -----------------------------
c1, c2 = st.columns(2)
with c1:
    st.subheader(f"{pitcher['Pitcher']} — full arsenal")
    ars = pd.DataFrame([{
        "Pitch": p["pitch_name"], "Family": p["family"], "Usage": p["usage"],
        "Velo": p["velo"], "Whiff%": p["whiff"], "PutAway%": p["putaway"],
    } for p in arsenals.get(pitcher_pid, [])])
    if len(ars):
        for c in ["Usage", "Velo", "Whiff%", "PutAway%"]:
            ars[c] = pd.to_numeric(ars[c], errors="coerce")
        st.dataframe(ars.style.format({"Usage": "{:.0%}", "Velo": "{:.2f}", "Whiff%": "{:.0%}",
                                       "PutAway%": "{:.0%}"}, na_rep="—")
                     .theme_gradient(cmap="RdYlGn", subset=["Whiff%", "PutAway%"]),
                     use_container_width=True, hide_index=True)

with c2:
    st.subheader(f"{hitter['Hitter']} — by pitch family")
    hs = hitter_splits.get(hitter_hid, {})
    if hs:
        hrows = pd.DataFrame([{
            "Family": fam, "Pitches": v["pitches"], "Whiff%": v["whiff"],
            "SLG": v["slg"], "xwOBA": v["xwoba"],
        } for fam, v in hs.items()])
        for c in ["Whiff%", "SLG", "xwOBA"]:
            hrows[c] = pd.to_numeric(hrows[c], errors="coerce")
        st.dataframe(hrows.style.format({"Whiff%": "{:.0%}", "SLG": "{:.2f}", "xwOBA": "{:.2f}"},
                                        na_rep="—")
                     .theme_gradient(cmap="RdYlGn", subset=["SLG", "xwOBA"])
                     .theme_gradient(cmap="RdYlGn", subset=["Whiff%"]),
                     use_container_width=True, hide_index=True)
    else:
        st.caption("No cached pitch-family splits for this hitter yet.")

# --- hitter by SPECIFIC pitch type (full arsenal view) --------------------------------------
st.subheader(f"{hitter['Hitter']} — by pitch type (full arsenal)")
st.caption("Granular view: performance against each individual pitch, not just the family. More "
           "detailed but noisier — the **Pitches** column shows the sample, and pitches with too "
           "few seen are hidden. Read a small sample with caution.")
hitter_types = load_hitter_type_cache()
ht = hitter_types.get(hitter_hid, [])
if ht:
    htype = pd.DataFrame([{
        "Pitch": r["pitch_name"], "Family": r["family"], "Pitches": r["pitches"],
        "Whiff%": r["whiff"], "SLG": r["slg"], "xwOBA": r["xwoba"],
    } for r in ht])
    for c in ["Whiff%", "SLG", "xwOBA"]:
        htype[c] = pd.to_numeric(htype[c], errors="coerce")
    st.dataframe(htype.style.format({"Whiff%": "{:.0%}", "SLG": "{:.2f}", "xwOBA": "{:.2f}"},
                                    na_rep="—")
                 .theme_gradient(cmap="RdYlGn", subset=["Whiff%"])
                 .theme_gradient(cmap="RdYlGn", subset=["SLG", "xwOBA"]),
                 use_container_width=True, hide_index=True)
    st.caption("Green = the hitter whiffs on it (good for the pitcher). Red = damage the hitter "
               "does (SLG / xwOBA against). Sorted by pitches seen.")
else:
    st.caption("No by-pitch-type data cached for this hitter yet — the nightly refresh needs enough "
               "of each pitch to clear the sample floor. The family view above is the stable read.")

st.divider()
st.caption("⚖️ A scouting tool, not a projection. Pitch-level rates are descriptive of the past and "
           "come from Statcast; small samples (especially per hitter) move around. The matchup score "
           "is a transparent sort to surface pitches worth attacking — not a probability or a bet signal.")
