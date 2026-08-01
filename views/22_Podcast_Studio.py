"""
Podcast Studio — a full ~hour show rundown for Dr. Hall & Deezy, regenerated daily.

Opens with Yesterday in Review (real results + fill-in chaos prompts), then slate overview,
top selections as banter beats, sleepers & fades, a rotating teaching segment, the honest game
plan, and a sign-off. Copy-pasteable as a complete show doc.
"""

import os

import streamlit as st
import components as C
from datetime import datetime, timedelta

import sports
import odds_api as O
import retro as R
import podcast as PC
import selections as SEL

_active = sports.active()

# UFC is outcome-based -- Podcast Studio's script generation is built on
# player stat projections that don't exist for UFC.
if not _active.has_projections:
    C.base_css()
    C.page_header("🎙️", "H2 Podcast Studio", "Episode scripts, rebuilt every day from the slate")
    st.info("🥊 Podcast Studio doesn't apply to UFC — the episode scripts are built on "
            "player stat projections. Head to **UFC Fight Card** for tonight's bouts.")
    st.stop()
E, P = _active.engine, _active.projections

if not sports.require_live_engine("Podcast Studio"):
    st.stop()


def get_key():
    try:
        return st.secrets["ODDS_API_KEY"]
    except Exception:
        return os.environ.get("ODDS_API_KEY")


C.base_css()
st.markdown("""
<style>
.beat-line {margin:3px 0;font-size:14px;color:#e6e6e6;}
.beat-line b {color:#a78bfa;}
.beat-note {margin:3px 0;font-size:13px;color:#9aa4b2;font-style:italic;}
.beat-fill {margin:4px 0;font-size:14px;background:#3a3410;border-left:3px solid #eab308;
            padding:4px 10px;border-radius:5px;color:#fde68a;}
.sec-time {color:#9aa4b2;font-size:13px;font-weight:normal;}
</style>
""", unsafe_allow_html=True)

C.page_header("🎙️", f"H2 Podcast Studio  ·  {_active.icon} {_active.label}",
             "A full ~hour show rundown for Dr. Hall & Deezy — rebuilt every day from the slate")


def _board_mlb(date_str):
    # Real, confirmed fix for a structural gap: this used to be its own separate, duplicate
    # reimplementation of build_mlb_board's own logic (statcast/weather/hitter-pitcher
    # enrichment/best_bets) -- but WITHOUT ever fetching real sportsbook lines or prices. Every
    # play shown here was always measured against this platform's own DEFAULT_LINES/BEST_BET_REF
    # placeholders, even after Best Bets/Graded Picks/Command Center/Model Dashboard/Retrospective
    # were all already fixed to use real data. build_mlb_board's own docstring explicitly
    # documents this exact class of bug already causing one real, confirmed production issue
    # (a Command Center/Best Bets conviction mismatch) BEFORE it was made "PUBLIC, NOT INTERNAL"
    # specifically so every page could share it -- this page just never actually did.
    import best_bets_data as BBD
    import statcast_data as SC

    @st.cache_data(ttl=3600, show_spinner=False)
    def load_statcast():
        return SC.load()

    fip_constant = E.FIP_CONSTANT_DEFAULT
    api_key = get_key()
    rows, meta, plays, _books = BBD.build_mlb_board(date_str, fip_constant, odds_api_key=api_key)
    # Statcast loaded separately here (its own cached call, same ttl as build_mlb_board's own
    # internal copy) specifically for the "ev_mode" feature's own build_projection_index call
    # below, which build_mlb_board doesn't expose internally. Not a new parallel pipeline --
    # rows/meta/plays all still come from the one real, shared source; this is the one piece
    # build_mlb_board's own return doesn't carry.
    sc, k = load_statcast()
    return plays, len(meta), rows, meta, sc, k


def _board_generic(sport_key, date_str):
    sport = sports.get(sport_key)
    if not sport.has_projections:
        rows, meta = [], []
    else:
        rows, meta = sport.engine.build_slate(date_str)
    return sport.projections.build_best_bets(rows), len(meta), rows, meta, None, None


def _board(sport_key, date_str):
    return _board_mlb(date_str) if sport_key == "MLB" else _board_generic(sport_key, date_str)


@st.cache_data(ttl=300, show_spinner=False)
def load_today(sport_key, date_str, ev_mode):
    sport = sports.get(sport_key)
    plays, n_games, rows, meta, sc, k = _board(sport_key, date_str)
    plays = SEL.filter_known_pitcher(plays)             # never headline a TBD-pitcher matchup
    ev_used = False
    if ev_mode:
        key = get_key()
        if key:
            if sport_key == "MLB":
                index = sport.projections.build_projection_index(rows, meta, statcast=sc, statcast_k=k)
                markets = sorted(set(SEL.MARKET_TO_ODDS_KEY.values()))
                mmap = None
            else:
                index = sport.projections.build_projection_index(rows, meta)
                markets = sport.markets
                mmap = sport.market_map
            offers, _ = O.fetch_slate_props(date_str, key, markets, sport=sport.odds_sport_key)
            edges, _ = O.compute_edges(index, offers, projections_module=sport.projections)
            SEL.attach_live_ev(plays, edges, market_map=mmap)
            plays = [p for p in plays if p.get("EV") is not None]
            ev_used = True
    rank = "EV" if ev_used else "Conviction"
    headliners = sport.projections.curate_selections(plays, n=5, per_market_cap=2, rank_key=rank)
    hl = {id(p) for p in headliners}
    sleepers = sport.projections.curate_selections(
        [p for p in plays if id(p) not in hl], n=3, per_market_cap=1, rank_key=rank)
    return headliners, sleepers, n_games, ev_used


@st.cache_data(ttl=900, show_spinner=False)
def load_yesterday(sport_key, date_str):
    try:
        sport = sports.get(sport_key)
        plays, *_ = _board(sport_key, date_str)
        results = sport.engine.get_player_results(date_str)
        _, summary = R.grade_slate(plays, results)
        # marquee single-event market for the "and they cashed" flex line — HR for MLB, Points
        # for WNBA (first entry in that sport's market_map, see sports.py's registry).
        marquee = next(iter(sport.market_map), None)
        caught = R.market_report(plays, results, marquee)["caught"] if marquee else []
        return summary, caught
    except Exception:
        return None, None


target = st.date_input("Show date (tonight's slate)", datetime.now())
ev_mode = st.toggle("Feature live-value plays (uses odds quota)", value=False,
                    help="On: ranks the show's selections by real EV% against live prices (same math "
                         "as the Edge Board). Off: ranks by model conviction. Either way, TBD-pitcher "
                         "plays are excluded.")
date_str = target.strftime("%Y-%m-%d")
yest = (target - timedelta(days=1)).strftime("%Y-%m-%d")

with st.spinner("Writing tonight's rundown..."):
    headliners, sleepers, n_games, ev_used = load_today(_active.key, date_str, ev_mode)
    retro, caught = load_yesterday(_active.key, yest)

if not headliners:
    st.info("No games on this date to build a show around. Pick a date with a scheduled slate.")
    st.stop()

sections = PC.assemble_script(date_str, headliners, sleepers, retro, caught, sport=_active.key)

st.caption(f"{n_games} games tonight · {len(headliners)} headline selections · "
           f"{len(sleepers)} sleepers · teaching + yesterday's review included")
st.info("This is a talking-points rundown — riff, don't read. Yellow blocks are **FILL IN** prompts "
        "for the stuff only you two know (last night's chaos, tonight's storyline). The model never "
        "makes up game news it can't verify.", icon="🎬")

# --- render sections on screen ---------------------------------------------
for sec in sections:
    st.markdown(f"### {sec['title']} <span class='sec-time'>· {sec['time']}</span>", unsafe_allow_html=True)
    for b in sec["beats"]:
        if b["type"] == "fill":
            st.markdown(f"<div class='beat-fill'>✍️ {b['text']}</div>", unsafe_allow_html=True)
        elif b["type"] == "note":
            st.markdown(f"<div class='beat-note'>» {b['text']}</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='beat-line'><b>{b['who']}:</b> {b['text']}</div>", unsafe_allow_html=True)
    st.markdown("")

# --- full copy-paste show doc ----------------------------------------------
st.divider()
C.section_header("📋", "Full show doc — copy for the studio")
st.caption("One click the copy icon to grab the entire rundown for your notes or teleprompter.")
st.code(PC.script_to_text(date_str, sections), language=None)
