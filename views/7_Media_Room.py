"""
Media Room — curated "selections we found interesting," built for a podcast/Discord segment.
 
Not picks, not locks, not advice. Each selection shows the side/line, the plain-English CASE
(the model's reasoning), and an honest value read. Two modes:
  • Conviction (free)      — ranks by how far the model diverges from a typical line; shows fair price.
  • Live value (uses odds) — ranks by real EV% against live prices, identical math to the Edge Board.
Plays whose opposing starter is undetermined (TBD) are excluded — the matchup can't be priced.
"""
 
import os
 
import streamlit as st
from datetime import datetime
 
import mlb_engine as E
import projections as P
import statcast_data as SC
import weather as WX
import odds_api as O
import selections as SEL
import retro as R
 
 
st.markdown("""
<style>
.sel-card {background:#f8fafc;border:1px solid #e2e8f0;border-left:5px solid #7c3aed;
           border-radius:10px;padding:14px 18px;margin-bottom:12px;}
.sel-card h4 {margin:0 0 6px;font-size:17px;color:#0f172a;}
.sel-card .case {color:#334155;font-size:14px;margin:2px 0;}
.sel-card .rc {color:#64748b;font-size:13px;font-style:italic;margin-top:6px;}
.sel-badge {display:inline-block;background:#7c3aed;color:#fff;font-size:12px;
            padding:2px 9px;border-radius:999px;margin-left:6px;vertical-align:middle;}
.sel-val {display:inline-block;background:#dcfce7;color:#166534;font-size:12px;
          padding:2px 9px;border-radius:999px;margin-left:6px;vertical-align:middle;}
</style>
""", unsafe_allow_html=True)
 
st.title("📣 H2 Sports Media — Selections")
st.caption("Curated plays we found interesting, with the reasoning — ready for the show and the Discord")
 
SIDE_PHRASE = {
    ("Batter HR", "Over"): "to homer", ("Batter Total Bases", "Over"): "Over 1.5 total bases",
    ("Batter Total Bases", "Under"): "Under 1.5 total bases", ("Batter Total Hits", "Over"): "to record a hit",
    ("Batter Total Hits", "Under"): "to be held hitless", ("Batter Strikeouts", "Over"): "to strike out",
    ("Batter Strikeouts", "Under"): "to avoid the K", ("Pitcher Strikeouts", "Over"): "Over on strikeouts",
    ("Pitcher Strikeouts", "Under"): "Under on strikeouts", ("Pitcher Outs", "Over"): "Over on outs",
    ("Pitcher Outs", "Under"): "Under on outs", ("Pitcher Walks", "Over"): "Over on walks",
    ("Pitcher Walks", "Under"): "Under on walks",
}
 
 
def line_label(p):
    return f"{p['Side']} {p['Line']:g}"
 
 
def headline(p):
    verb = SIDE_PHRASE.get((p["Market"], p["Side"]), f"{p['Side']} {p['Line']:g}")
    vs = f" vs {p['Opp']}" if p.get("Opp") else ""
    return f"{p['Player']} ({p['Team']}) {verb}{vs}"
 
 
def value_text(p):
    if p.get("EV") is not None:
        live = f"{p['LivePrice']:+d}" if p.get("LivePrice") is not None else "—"
        return f"Live value: {p['EV']:+.1f}% at {live} ({p['Book']})." if p.get("Book") else \
               f"Live value: {p['EV']:+.1f}% at {live}."
    fair = f"{p['Fair']:+d}" if p.get("Fair") is not None else "—"
    return f"Fair price ~{fair} (prices not checked — flip on Live value to verify)."
 
 
def reality_check(p):
    prob = f"{p['ModelProb']*100:.0f}%"
    return (f"Reality check: model ~{prob} to cash — a lean we found interesting, not a lock. "
            + value_text(p) + " Only worth backing if you beat the number.")
 
 
def get_key():
    try:
        return st.secrets["ODDS_API_KEY"]
    except Exception:
        return os.environ.get("ODDS_API_KEY")
 
 
@st.cache_data(ttl=3600, show_spinner=False)
def load_statcast():
    return SC.load()
 
 
@st.cache_data(ttl=1800, show_spinner=False)
def load_weather(keys):
    out = {}
    for vid, gdate, vname in keys:
        if vid is not None and vid not in out:
            try:
                out[vid] = WX.get_game_weather(vid, gdate, vname)
            except Exception:
                out[vid] = None
    return out
 
 
@st.cache_data(ttl=300, show_spinner=False)
def load_selections(date_str, n, cap, ev_mode):
    rows, meta = E.build_slate(date_str)
    sc, k = load_statcast()
    wx = load_weather(tuple((m.get("venue_id"), m.get("game_date"), m.get("venue")) for m in meta))
    for r in rows:
        w = wx.get(r.get("_venue_id"))
        r["_weather_hr"] = w["hr_factor"] if w else 1.0
    P.enrich_hitter_rows(rows, seed=7, statcast=sc, statcast_k=k)
    pr = P.build_pitcher_projection_rows(rows, meta, seed=11)
    plays = SEL.filter_known_pitcher(P.build_best_bets(rows, pr))   # drop TBD-pitcher plays
 
    ev_used = False
    if ev_mode:
        key = get_key()
        if key:
            index = P.build_projection_index(rows, meta, statcast=sc, statcast_k=k)
            markets = sorted(set(SEL.MARKET_TO_ODDS_KEY.values()))
            offers, _ = O.fetch_slate_props(date_str, key, markets)
            edges, _ = O.compute_edges(index, offers)
            SEL.attach_live_ev(plays, edges)
            plays = [p for p in plays if p.get("EV") is not None]
            ev_used = True
 
    rank = "EV" if ev_used else "Conviction"
    return P.curate_selections(plays, n=n, per_market_cap=cap, rank_key=rank), len(meta), ev_used
 
 
c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    target = st.date_input("Slate date", datetime.now())
with c2:
    n = st.slider("How many selections", 5, 8, 6)
with c3:
    cap = st.slider("Max per market", 1, 3, 2)
ev_mode = st.toggle("Rank by live value (uses odds quota)", value=False,
                    help="On: pulls live prices and ranks by real EV% (same math as the Edge Board). "
                         "Off: ranks by model conviction and shows fair price — no odds spent.")
date_str = target.strftime("%Y-%m-%d")
 
with st.spinner("Curating selections..."):
    sel, n_games, ev_used = load_selections(date_str, n, cap, ev_mode)
 
if not sel:
    msg = ("No live-value plays cleared the filters today." if ev_mode
           else "No selections for this date. Pick a date with scheduled games.")
    st.info(msg)
    st.stop()
 
mode_label = "ranked by **live EV%**" if ev_used else "ranked by **model conviction** (prices not checked)"
st.caption(f"{n_games} games scanned · {len(sel)} selections · {mode_label} · TBD-pitcher plays excluded")
if ev_mode and not ev_used:
    st.warning("Live value is on but no Odds API key was found — showing conviction instead. Add "
               "ODDS_API_KEY in secrets to enable live EV.", icon="⚠️")
 
# --- result lights: grade past-date selections by the pick's SIDE and LINE -----------------
# Only for finalized (past) dates — today's games have no results, so no lights are shown.
# Graded via retro.grade_play so a 🟢/🔴 matches how the Retrospective and Bet Log score:
# an Under is 🟢 only if the player stayed UNDER the line, not if he "did something".
_is_past = target < datetime.now().date()
_results = {}
if _is_past:
    try:
        _results = E.get_player_results(date_str)
    except Exception:
        _results = {}
_graded_on = _is_past and bool(_results)
 
 
def result_mark(p):
    """🟢 hit / 🔴 miss / 🟡 no result (didn't appear), or '' when the date isn't finalized."""
    if not _graded_on:
        return ""
    hit = R.grade_play(p["Market"], p["Side"], p.get("Line"), _results.get(p.get("PlayerId")))
    return "🟢" if hit is True else "🔴" if hit is False else "🟡"
 
 
if _graded_on:
    _marks = [result_mark(p) for p in sel]
    _h, _m, _p = _marks.count("🟢"), _marks.count("🔴"), _marks.count("🟡")
    _tally = f"🟢 {_h}  ·  🔴 {_m}" + (f"  ·  🟡 {_p}" if _p else "")
    st.markdown(f"### 🚦 Selection scorecard — {_tally}")
    if _h + _m:
        st.caption(f"The model went **{_h}-for-{_h + _m}** on {date_str}'s selections "
                   f"(graded by the pick's side and line). 🟡 = player didn't appear / no result.")
elif _is_past:
    st.caption("🚦 Results for this date aren't available to grade yet.")
 
# --- on-screen cards -------------------------------------------------------
for i, p in enumerate(sel, 1):
    val = (f"<span class='sel-val'>{p['EV']:+.1f}% EV</span>" if p.get("EV") is not None else "")
    mark = result_mark(p)
    mark_html = f"{mark} " if mark else ""
    st.markdown(
        f"""<div class="sel-card">
        <h4>{mark_html}{i}. {headline(p)} <span class="sel-badge">{p['Market']} · {line_label(p)}</span>{val}</h4>
        <div class="case"><b>The case:</b> {p['Why']}.</div>
        <div class="rc">{reality_check(p)}</div>
        </div>""", unsafe_allow_html=True)
 
# --- copy-all block --------------------------------------------------------
st.subheader("📋 Copy for the show / Discord")
st.caption("One click the copy icon (top-right of the block) to grab the whole segment.")
lines = [f"🎙️ H2 Sports Media — Selections we found interesting · {date_str}",
         f"({'live value' if ev_used else 'model conviction — prices not checked'})", ""]
if _graded_on and (_h + _m):
    lines.append(f"🚦 Scorecard: {_h}-for-{_h + _m}  ({_tally})")
    lines.append("")
for i, p in enumerate(sel, 1):
    mark = result_mark(p)
    prefix = f"{mark} " if mark else ""
    lines.append(f"{prefix}{i}) {headline(p)}  [{p['Market']} · {line_label(p)}]")
    lines.append(f"   The case: {p['Why']}.")
    lines.append(f"   {reality_check(p)}")
    lines.append("")
lines.append("⚖️ For entertainment. Selections we found interesting with our reasoning — not locks "
             "and not betting advice. Variance is real; always check the price and bet responsibly.")
st.code("\n".join(lines), language=None)
