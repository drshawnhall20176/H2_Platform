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

import mlb_engine as E
import matchup_data as MD
from datetime import datetime

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

date_str = st.date_input("Slate date", datetime.now()).strftime("%Y-%m-%d")

pitchers = load_pitchers(date_str)
if not pitchers:
    st.warning("No probable starters found for this date yet — check back closer to game time.")
    st.stop()

# Pitcher picker (only those we have arsenal data for are useful, but show all with a flag).
p_by_label = {}
for r in pitchers:
    pid = r.get("_pid")
    has = pid in arsenals
    label = f"{r['Pitcher']} ({r['Team']}){'' if has else '  — no pitch data'}"
    p_by_label[label] = r
p_label = st.selectbox("Pitcher (type to search)", sorted(p_by_label.keys()))
pitcher = p_by_label[p_label]
pitcher_pid = pitcher.get("_pid")

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
               f"{best['h_slg'] or 0:.3f} against it. Matchup score is a scouting sort, not a "
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
          .format({"Usage": "{:.0%}", "Velo": "{:.1f}", "P Whiff%": "{:.0%}", "P PutAway%": "{:.0%}",
                   "H Whiff% (fam)": "{:.0%}", "H SLG (fam)": "{:.3f}", "H xwOBA (fam)": "{:.3f}",
                   "Score": "{:.3f}"}, na_rep="—")
          # green = good FOR THE PITCHER: high pitcher-whiff, high hitter-whiff, high score
          .theme_gradient(cmap="Greens", subset=["P Whiff%", "P PutAway%", "H Whiff% (fam)", "Score"])
          # red = damage the hitter does: high SLG/xwOBA against is bad for the pitcher
          .theme_gradient(cmap="Reds", subset=["H SLG (fam)", "H xwOBA (fam)"]))
st.dataframe(styler, use_container_width=True, hide_index=True)
st.caption("Green favors the pitcher (whiffs, put-aways, matchup score). Red is damage the hitter "
           "does to that pitch family (SLG / xwOBA against). Hitter columns are by pitch **family** "
           "(Fastball / Breaking / Offspeed) for a stable sample; the pitch is mapped to its family.")

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
        st.dataframe(ars.style.format({"Usage": "{:.0%}", "Velo": "{:.1f}", "Whiff%": "{:.0%}",
                                       "PutAway%": "{:.0%}"}, na_rep="—")
                     .theme_gradient(cmap="Greens", subset=["Whiff%", "PutAway%"]),
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
        st.dataframe(hrows.style.format({"Whiff%": "{:.0%}", "SLG": "{:.3f}", "xwOBA": "{:.3f}"},
                                        na_rep="—")
                     .theme_gradient(cmap="Reds", subset=["SLG", "xwOBA"])
                     .theme_gradient(cmap="Greens", subset=["Whiff%"]),
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
    st.dataframe(htype.style.format({"Whiff%": "{:.0%}", "SLG": "{:.3f}", "xwOBA": "{:.3f}"},
                                    na_rep="—")
                 .theme_gradient(cmap="Greens", subset=["Whiff%"])
                 .theme_gradient(cmap="Reds", subset=["SLG", "xwOBA"]),
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
