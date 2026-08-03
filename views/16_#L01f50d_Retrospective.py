"""
Retrospective — how did the model's board hold up against what actually happened?
 
A MODEL REVIEW, not an outlier hunt. It grades the pre-game probabilities against real
results and shows where the model ranked the players who actually produced. It never mines
for new variables to explain a specific surprise after the fact.
"""
 
import streamlit as st
import components as C
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
 
import retro as R
import sports
import best_bets_data as BBD
import odds_api as O
import grading_history as GH

_active = sports.active()
E, P = _active.engine, _active.projections

C.base_css()
C.page_header("🔍", "Retrospective",
             f"How the model's pre-game board lined up with what actually happened — "
             f"{_active.icon} {_active.label}")

if not sports.require_live_engine("Retrospective"):
    st.stop()

_MARKET_ICONS = {
    "Batter HR": "🏠", "Pitcher Strikeouts": "⚡", "Batter Total Bases": "📊",
    "Batter Total Hits": "✅", "Batter Strikeouts": "🌀", "Pitcher Outs": "🎯", "Pitcher Walks": "🚶",
    "Batter Runs": "🏃", "Batter RBIs": "💪", "Batter Stolen Bases": "💨", "Pitcher Earned Runs": "🛡️",
    "Points": "🏀", "Rebounds": "🔁", "Assists": "🤝", "Threes Made": "3️⃣",
}
_active_markets = list(_active.market_map.keys())


@st.cache_data(ttl=600, show_spinner=False)
def load_retro_mlb(date_str: str, fip_constant: float):
    # build_mlb_board (best_bets_data.py) is the SAME shared pipeline Best Bets and Graded Picks
    # use — a real consolidation, not just deduplication for its own sake: Retrospective used to
    # have its OWN separate, third copy of this pipeline, which meant it graded the model against
    # UNBLENDED probabilities while the actual board shown to a person used the bullpen-blended
    # ones. That's a real accuracy gap now closed, not just fewer lines of code — this now grades
    # the SAME numbers a person actually sees.
    rows, meta, plays, _books = BBD.build_mlb_board(date_str, fip_constant)
    results = E.get_player_results(date_str)
    graded, summary = R.grade_slate(plays, results)
    reports = {m: R.market_report(plays, results, m) for m in _active_markets}
    rows_by_pid = {r.get("_pid"): r for r in rows}
    # pitcher_rows themselves aren't returned by build_mlb_board (only used internally to build
    # plays) — rebuilding them here is cheap, pure computation (no network calls; every pitcher's
    # own stats are already sitting in rows' own "_opp_stat" fields), not a real duplication of
    # the expensive part of the pipeline (build_slate, statcast, weather, the bullpen blend).
    # real_lines IS fetched again here -- a real, confirmed second instance of the same
    # disconnected-pipeline gap, found during a later audit: this call was missing real_lines
    # even though the main `plays` above already correctly used them, meaning the "why did this
    # K prediction miss" explanation built from pitcher_rows could reference a genuinely
    # different (wrong) line than what was actually graded. Calls the SAME cached
    # fetch_mlb_real_lines function build_mlb_board's own internal call already used -- cached at
    # the same 300s window, so this is a real cache hit, not a second real API cost.
    api_key = BBD.get_odds_api_key()
    real_lines, _offers, _books2 = BBD.fetch_mlb_real_lines(date_str, api_key)
    pitcher_rows = P.build_pitcher_projection_rows(rows, meta, seed=11, real_lines=real_lines)
    for pr in pitcher_rows:                     # so pitcher-K misses can be explained too
        rows_by_pid.setdefault(pr.get("_pid"), pr)
    return graded, summary, reports, rows_by_pid, len(meta), len(results)


@st.cache_data(ttl=600, show_spinner=False)
def load_retro_generic(sport_key: str, date_str: str):
    sport = sports.get(sport_key)
    if not sport.has_projections:
        st.info("🥊 Retrospective doesn't apply to UFC — head to **UFC Fight Card**.")
        st.stop()
    rows, meta = sport.engine.build_slate(date_str)

    # Real sportsbook lines, same fetch best_bets_data.load_generic_best_bets_board already does
    # for Best Bets/Command Center/etc. -- a real, confirmed gap this closes: MLB's own
    # load_retro_mlb (just above) already grades against real lines via build_mlb_board, but this
    # generic path (every other sport) was calling build_best_bets with no real_lines at all,
    # always falling back to this platform's own placeholder DEFAULT_LINES regardless of whether
    # a real book price existed. Retrospective's whole purpose is judging the model's own board
    # honestly -- grading it against a line nobody could actually get undermines that.
    real_lines = None
    api_key = BBD.get_odds_api_key()
    if api_key and sport.markets:
        try:
            preferred_book = st.session_state.get(
                f"_preferred_book_{sport_key.lower()}", O.DEFAULT_BOOK)
            offers, _ = O.fetch_slate_props(date_str, api_key, list(sport.markets),
                                            sport=sport.odds_sport_key)
            real_lines = O.market_lines_for_slate(offers, preferred_book=preferred_book)
        except Exception:
            real_lines = None   # fall back to DEFAULT_LINES, not a page crash

    plays = sport.projections.build_best_bets(rows, real_lines=real_lines)
    results = sport.engine.get_player_results(date_str)
    graded, summary = R.grade_slate(plays, results)
    reports = {m: R.market_report(plays, results, m) for m in _active_markets}
    rows_by_pid = {r.get("_pid"): r for r in rows}
    return graded, summary, reports, rows_by_pid, len(meta), len(results)
 
 
if _active.key == "MLB":
    c1, c2 = st.columns([2, 1])
    with c1:
        target = st.date_input("Slate to review", datetime.now() - timedelta(days=1))
    with c2:
        fip_constant = st.number_input("FIP constant", value=E.FIP_CONSTANT_DEFAULT, step=0.01)
    date_str = target.strftime("%Y-%m-%d")

    st.warning("**Approximate, for exploration.** Rebuilding a past slate uses *current*-season "
               "rates, so recent dates have little look-ahead but older dates have more. For "
               "rigorous, point-in-time proof, the **Bet Log** (which saved the model's probability "
               "at bet time) is the real scorecard. Read this as a model review, not a P&L.", icon="⚠️")

    with st.spinner("Rebuilding the board and pulling results..."):
        graded, summary, reports, rows_by_pid, n_games, n_results = load_retro_mlb(date_str, fip_constant)

    # Persisted here, in genuinely uncached top-level page code — NEVER inside load_retro_mlb
    # itself, which is @st.cache_data-wrapped. A write inside a cached function only fires on the
    # actual cache MISS; a second visit (or a second person) within the 600s TTL would silently
    # skip writing at all. Same real, confirmed reason best_bets_data.ensure_mlb_offers_session_
    # state's own docstring already documents for the identical class of bug. record_graded_slate
    # itself is idempotent per (slate_date, sport) — revisiting this same date repeatedly (which
    # this page's own st.date_input makes easy) replaces, not multiplies, the stored rows.
    #
    # REAL CAVEAT, STATED PLAINLY, NOT SWEPT UNDER THE RUG: this page's own warning above already
    # says it — rebuilding a past MLB slate uses CURRENT-season rates, not the rates that existed
    # on that real date, so a row persisted here reflects "what today's model would say about that
    # game," not a genuine point-in-time prediction. Real, useful signal for calibration on
    # recently-played dates (little look-ahead yet); a real bias for old ones. Not filtered out
    # here on purpose — this module's own docstring already puts the sample-size-and-soundness
    # judgment call on every caller, not on the storage layer; a future retuning decision needs to
    # weigh this the same way it weighs sample size, using since_date to prefer recent history.
    GH.record_graded_slate(date_str, "MLB", graded)
else:
    target = st.date_input("Slate to review", datetime.now() - timedelta(days=1))
    date_str = target.strftime("%Y-%m-%d")

    st.info("Rebuilt using only games completed **strictly before** this date — genuinely "
            "point-in-time, not a look-ahead approximation. (MLB's version above rebuilds from "
            "current-season rates; WNBA's recency-window model naturally avoids that.)", icon="✅")

    with st.spinner("Rebuilding the board and pulling results..."):
        graded, summary, reports, rows_by_pid, n_games, n_results = load_retro_generic(_active.key, date_str)

    # Persisted here, in genuinely uncached top-level page code -- same reasoning as the MLB
    # branch above. WNBA's own recency-window model naturally avoids the look-ahead caveat MLB's
    # version carries (this page's own info banner above already says so) -- so a row persisted
    # here is a genuinely point-in-time prediction, the cleanest signal this module can store.
    GH.record_graded_slate(date_str, _active.key, graded)
 
if not summary["graded"]:
    st.info("No completed games with results for this date yet. Pick a date whose games are final.")
    st.stop()
 
st.caption(f"{n_games} games · {summary['graded']} plays graded · {n_results} players with results")
 
# --- headline: could we have caught it? (all cast markets) -----------------
C.section_header("🎯", "Could we have caught it?")
st.caption("For each market we cast, of the players whose result *cleared the line*, where did "
           "the model rank them **before** the game — and for the ones it ranked low, an honest "
           "reason. High rank = the model surfaced it; deep in the list = the data says it was "
           "largely random.")


_explain_miss = R.explain_miss if _active.key == "MLB" else P.explain_miss


def _render_market_review(rep, market, rows_by_pid):
    m1, m2, m3 = st.columns(3)
    m1.metric("Caught", len(rep["caught"]),
              help=f"Cleared the line AND ranked in the model's top {rep['cutoff']} "
                   f"of {rep['total_ranked']}")
    m2.metric("Ranked low", len(rep["missed"]), help="Cleared the line but the model ranked it deep")
    m3.metric("Off the board", rep["unprojected"], help="Cleared a typical line but not in a projected lineup")
 
    if rep["caught"]:
        cdf = pd.DataFrame(rep["caught"])
        cdf["Rank"] = cdf.apply(lambda r: f"#{r['Rank']} of {r['OfTotal']}", axis=1)
        cols = [c for c in ["Player", "Value", "Line", "ModelProb", "Conviction", "Rank"]
                if c in cdf.columns]
        st.markdown("**Caught — ranked high and delivered**")
        st.dataframe(
            cdf[cols].rename(columns={"ModelProb": "Model %", "Value": market}).style.format(
                {"Model %": "{:.0%}", "Conviction": "{:.2f}×", "Line": "{:g}", market: "{:.1f}"}, na_rep="—"),
            hide_index=True, width="stretch")
 
    if rep["missed"]:
        st.markdown("**Ranked low — could we have caught it?**")
        mrows = []
        for m in rep["missed"]:
            row = rows_by_pid.get(m.get("PlayerId"))
            mrows.append({
                "Player": m["Player"], market: m.get("Value"), "Model %": m["ModelProb"],
                "Conviction": m.get("Conviction") if m.get("Conviction") is not None else float("nan"),
                "Rank": f"#{m['Rank']} of {m['OfTotal']}",
                "Reason": _explain_miss(row, market),
            })
        mdf = pd.DataFrame(mrows)
        st.dataframe(
            mdf.style.format({"Model %": "{:.0%}", "Conviction": "{:.2f}×", market: "{:.1f}"}, na_rep="—"),
            hide_index=True, width="stretch")
 
    if rep["unprojected"]:
        st.caption(f"➕ {rep['unprojected']} more from players not in a projected lineup "
                   "(late changes, call-ups, subs) — the model never saw them.")
    if not (rep["caught"] or rep["missed"]):
        st.caption("Nothing cleared the line to review for this market on this date.")
 
 
_RETRO_ITEMS = [(f"{_MARKET_ICONS.get(m, '🔹')} {m}", m) for m in _active_markets]
market = C.wrapped_tab_picker(_RETRO_ITEMS, key="retro_market")
_render_market_review(reports[market], market, rows_by_pid)
if market == "Batter Total Hits":
    st.caption("⚠️ Reminder: 1+ hits lands well over half the time, so a 'miss' here is closer "
               "to a coin flip than a called shot — most are simply variance, not something the "
               "model should have caught.")

if _active.key == "MLB":
    st.caption("**\"Catchable\" does not mean the model was wrong** — it means a real, market-specific "
               "signal (barrels or a homer-prone matchup for power; a hittable/whiff-prone opposing "
               "pitcher for hits and strikeouts; platoon edge; park/weather) was present that the ranking "
               "under-weighted, worth reviewing. **\"Genuine long shot / over\"** means no such edge: the "
               "model was right to rank it low, and chasing these is the overfitting we avoid. Most misses "
               "are simply variance — that's baseball, not a flaw.")
else:
    st.caption("**\"Catchable\" does not mean the model was wrong** — it means the player was already "
               "trending up over their last few games before this one, a real signal the recency "
               "weighting hadn't fully caught up to yet. **\"Genuine outlier\"** means no such trend: "
               "the result sits above their established form with no warning sign, and chasing these "
               "after the fact is the overfitting the model avoids. Most misses are simply variance.")
 
# --- model accuracy --------------------------------------------------------
st.divider()
C.section_header("📊", "How the model's leans did")
m1, m2, m3 = st.columns(3)
m1.metric("Plays graded", summary["graded"])
m2.metric("Hit rate", f"{summary['hit_rate']:.0%}" if summary["hit_rate"] is not None else "—")
m3.metric("Hits", summary["hits"])
 
if summary["tiers"]:
    st.markdown("**Hit rate by conviction tier** — if the model ranks well, stronger leans hit more often")
    st.dataframe(pd.DataFrame(summary["tiers"]).rename(
        columns={"tier": "Conviction", "n": "Plays", "hit_rate": "Hit rate"})
        .style.format({"Hit rate": "{:.0%}"}), hide_index=True, width="stretch")
    st.caption("No equivalent of this specific conviction-tier breakdown exists anywhere else on "
              "this platform — Model Dashboard's own letter-grade tables are organized by grade "
              "and market instead, not conviction tier.")

# Letter-grade accuracy moved to a pointer directly on request, after a platform audit found real
# overlap: Model Dashboard's own "hit rate by letter grade, within each market/side" section
# already includes this exact same A-through-D range (confirmed directly against its own code --
# it deliberately does NOT re-filter to C-or-better the way its neighboring pie chart does), just
# broken out PER MARKET/SIDE rather than pooled across the whole slate the way this page's own
# version used to be -- a strict superset of what this page showed, not a different cut of the
# data. Removed here rather than kept as a second, coarser copy of the same real numbers.
st.page_link("views/17_Model_Dashboard.py",
             label="🎯 Want hit rate by letter grade? See Model Dashboard — broken out per market/side, "
                  "not just pooled across the whole slate →", icon="🏆")

cal = summary["calibration"]
if cal:
    fig, ax = plt.subplots(figsize=(3.6, 3.0), dpi=110)
    ax.plot([0, 1], [0, 1], "--", color="gray", label="perfect", linewidth=1)
    ax.scatter([c["predicted"] for c in cal], [c["actual"] for c in cal],
               s=[max(20, c["n"] * 3) for c in cal], color="#7c3aed", alpha=0.75, zorder=3)
    ax.set_xlabel("Model predicted", fontsize=8)
    ax.set_ylabel("Actual hit rate", fontsize=8)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_title("Calibration (this slate)", fontsize=9)
    ax.tick_params(labelsize=7)
    ax.legend(loc="upper left", fontsize=7); ax.grid(alpha=0.2)
    fig.tight_layout()
    chart_col, _ = st.columns([2, 3])          # cap width to ~40% of the page
    with chart_col:
        try:
            st.pyplot(fig, width="content")   # fixed small size, don't stretch
        except TypeError:
            st.pyplot(fig)                              # older Streamlit: column still caps it
    plt.close(fig)
    st.caption("One slate is a tiny sample — points won't sit perfectly on the line. The Bet Log's "
               "calibration, accumulated over many bets, is the trustworthy version.")
 
# --- full graded board -----------------------------------------------------
st.divider()
C.section_header("📋", "Full graded board")
only = st.radio("Show", ["All graded", "Hits only", "Misses only"], horizontal=True)
 
_graded_all = [g for g in graded if g["Hit"] is not None]
 
 
def _render_graded(subset):
    g = pd.DataFrame(subset)
    if not g.empty:
        if only == "Hits only":
            g = g[g["Hit"]]
        elif only == "Misses only":
            g = g[~g["Hit"]]
    if g.empty:
        st.caption("No graded plays match this filter.")
        return
    g = g.sort_values("Conviction", ascending=False)
    g["Result"] = g["Hit"].map({True: "✓", False: "✗"})
    g["Why it missed"] = g.apply(
        lambda r: "" if r["Hit"] else R.explain_pick_miss(r["ModelProb"], r["Market"], r.get("Side", "")),
        axis=1)
    show = g[["Conviction", "Player", "Market", "Side", "Line", "ModelProb", "Actual",
              "Result", "Why it missed", "Why"]]
    styler = (show.rename(columns={"ModelProb": "Model %", "Why": "Why the model liked it"})
              .style.format({"Model %": "{:.0%}", "Conviction": "{:.2f}×", "Line": "{:g}",
                            "Actual": "{:.1f}"}, na_rep="—"))
    # Natural width + wide text columns -> horizontal scroll for the two long reason columns.
    try:
        st.dataframe(
            styler, width="content", hide_index=True, height=480,
            column_config={
                "Why it missed": st.column_config.TextColumn("Why it missed", width="large"),
                "Why the model liked it": st.column_config.TextColumn("Why the model liked it", width="large"),
                "Player": st.column_config.TextColumn("Player", width="medium"),
            })
    except (TypeError, AttributeError):
        st.dataframe(styler, width="content", hide_index=True, height=480)
 
 
_GRADED_TABS = [("All markets", None)] + [(f"{_MARKET_ICONS.get(m, '🔹')} {m}", m) for m in _active_markets]
mkt = C.wrapped_tab_picker(_GRADED_TABS, key="retro_graded_market")
subset = _graded_all if mkt is None else [g for g in _graded_all if g["Market"] == mkt]
_render_graded(subset)
 
if only == "Misses only":
    st.caption("**Why so many high-conviction plays 'missed':** conviction is a *ratio* (model prob ÷ "
               "the typical rate for that market), so a high multiple is **not** a high probability — "
               "always read the Model % column. For HR especially, a 2.5–3.4× lean is still only a "
               "~28–37% chance, so the model itself expects **roughly 2 in 3 to miss**; a night where "
               "most do is normal variance for a high-variance market, not a broken model. The Bet Log's "
               "calibration over many slates — not one cold night — is the real test of whether the "
               "probabilities are honest.")
