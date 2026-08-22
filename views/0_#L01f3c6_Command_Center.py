"""
Command Center — the executive overview.
 
One screen that tells the story: a rigorous, layered model that prices every prop, sizes
with discipline, and — the differentiator — holds itself accountable with CLV and calibration.
 
HONESTY IS THE DESIGN. Proof panels render the FRAMEWORK with honest empty states until real
bets are logged. Nothing here is a fabricated track record. Where a number would be a forward
claim, it reads "tracking since inception" until the Bet Log fills it in for real.
"""
 
import streamlit as st
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import components as C  # shared KPI tiles / section headers -- see that module's own docstring
import pandas as pd
from datetime import datetime, timedelta
import plotly.graph_objects as go
 
import retro as R
import betlog as B
import sports
import best_bets_data as BBD
import grading
import quick_log
 
_active = sports.active()
 
C.hero_banner("🏆", "H2 Sports — Command Center",
             f"Trade sports, don't bet sports. A layered model that prices every prop, sizes with "
             f"discipline, and proves itself with closing-line value and calibration. — "
             f"{_active.icon} {_active.label}")

if not sports.require_live_engine("Command Center"):
    st.stop()

C.base_css()

# Icon per market, for the tab strips below — falls back to a generic icon for anything not
# listed (future sports don't need an entry here to render correctly, just less decoratively).
_MARKET_ICONS = {
    "Batter HR": "🏠", "Pitcher Strikeouts": "⚡", "Batter Total Bases": "📊",
    "Batter Total Hits": "✅", "Batter Strikeouts": "🌀", "Pitcher Outs": "🎯", "Pitcher Walks": "🚶",
    "Batter Runs": "🏃", "Batter RBIs": "💪", "Batter Stolen Bases": "💨", "Pitcher Earned Runs": "🛡️",
    "Points": "🏀", "Rebounds": "🔁", "Assists": "🤝", "Threes Made": "3️⃣",
}


# ---------- loaders ----------
def _board_mlb(date_str):
    plays, meta, _books = BBD.load_mlb_best_bets_board(date_str, BBD.E.FIP_CONSTANT_DEFAULT)
    return plays, meta


def _board_generic(sport_key, date_str):
    if not sports.get(sport_key).has_projections:
        return [], []   # UFC is outcome-based -- no generic plays pipeline
    # Same real session-state read _board_mlb's own preferred_book already uses (line above) --
    # Command Center has no book-selector widget of its own; it reads whichever real book was
    # last chosen on a page that does (Best Bets, Graded Picks, etc.).
    preferred_book = st.session_state.get(f"_preferred_book_{sport_key.lower()}", BBD.O.DEFAULT_BOOK)
    plays, meta, _books = BBD.load_generic_best_bets_board(sport_key, date_str, preferred_book)
    return plays, meta


def _board(sport_key, date_str):
    return _board_mlb(date_str) if sport_key == "MLB" else _board_generic(sport_key, date_str)


@st.cache_data(ttl=300, show_spinner=False)
def today_board(sport_key, date_str):
    plays, meta = _board(sport_key, date_str)
    return plays, len(meta)


@st.cache_data(ttl=900, show_spinner=False)
def yesterday_catches(sport_key, date_str, markets):
    plays, _ = _board(sport_key, date_str)
    results = sports.get(sport_key).engine.get_player_results(date_str)
    reports = {m: R.market_report(plays, results, m) for m in markets}
    rows_by_pid = {}
    if sport_key == "MLB":
        # explain_miss needs the enriched board row itself (season K/BB/SB rates, opposing
        # allowed rates, Statcast barrels, etc.), not just the play -- same real data already
        # powering the "Why" column elsewhere, reused here rather than recomputed. Mirrors
        # Retrospective's own established rows_by_pid pattern exactly (load_retro_mlb).
        try:
            rows, _meta, _plays, _books = BBD.build_mlb_board(date_str, BBD.E.FIP_CONSTANT_DEFAULT)
            rows_by_pid = {r.get("_pid"): r for r in rows}
        except Exception:
            rows_by_pid = {}
    return ({m: r["caught"] for m, r in reports.items()},
            {m: r["missed"] for m, r in reports.items()},
            rows_by_pid, len(results))


today = datetime.now().strftime("%Y-%m-%d")
yest = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

with st.spinner("Loading tonight's board..."):
    try:
        plays, n_games = today_board(_active.key, today)
    except Exception:
        plays, n_games = [], 0

if _active.key == "MLB":
    # Guarantees THIS session's own quick_log real-price side-channel is populated, regardless
    # of whether today_board above was a cache hit for this session specifically -- see
    # ensure_mlb_offers_session_state's own docstring for the real, confirmed cross-session bug
    # this fixes. Called here, in genuinely uncached top-level page code.
    BBD.ensure_mlb_offers_session_state(
        today, BBD.get_odds_api_key(), st.session_state.get("_preferred_book_mlb", BBD.O.DEFAULT_BOOK))

bets = B.list_bets(sport=_active.key)
s = B.summary(bets)
 
# ---------- KPI row ----------
top = plays[0] if plays else None
_beat_close = s["beat_close_rate"]
_avg_clv = s["avg_clv"]
C.kpi_row([
    {"icon": "⚾", "value": str(n_games), "label": "Tonight's games"},
    {"icon": "🎲", "value": str(len(plays)), "label": "Model plays"},
    {"icon": "⭐", "value": f"{top['Conviction']:.1f}×" if top else "—", "label": "Top lean",
     "help": f"{top['Player']} {top['Market']} {top['Side']}" if top else None},
    {"icon": "📈", "value": f"{_beat_close:.0f}%" if _beat_close is not None else "—",
     "label": "Beat-close rate", "help": "Share of bets that beat the closing line. The core proof metric.",
     "trend": ("good" if _beat_close is not None and _beat_close >= 50
               else "bad" if _beat_close is not None else None)},
    {"icon": "💰", "value": f"{_avg_clv:+.2f}%" if _avg_clv is not None else "—", "label": "Avg CLV",
     "trend": ("good" if _avg_clv is not None and _avg_clv >= 0
               else "bad" if _avg_clv is not None else None)},
])

# Owner-only data-health pointer — the Data Health page itself is gated the same way, so this
# stays hidden for a public/Discord audience rather than linking to a page they can't open.
if st.secrets.get("AUDIENCE", "owner") == "owner":
    import data_freshness as DF
    _dh_results = DF.check_all_sources()
    _dh_overall = DF.overall_status(_dh_results)
    _DH_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
    st.page_link("views/20_Data_Health.py",
                label=f"{_DH_ICON[_dh_overall]} Data health — see what's behind these numbers →",
                icon="🩺")
 
# ---------- the model pipeline (the pitch) ----------
st.markdown("##### How every play is built")
if _active.key == "MLB":
    C.pipeline_chips(["Matchup (odds-ratio)", "Handedness splits", "Statcast expected power",
                     "Weather & wind", "Live EV vs market", "Kelly sizing",
                     "Logged · CLV · calibration"])
else:
    C.pipeline_chips(["Last 10 games", "Bootstrap resample", "Rotation-minutes filter",
                     "Live EV vs market", "Kelly sizing", "Logged · CLV · calibration"])
    st.caption("v1 model — opponent defense and pace aren't incorporated yet.")
 
st.divider()

# ---------- today's game lines, de-vigged (EXTENDED DIRECTLY ON REQUEST) ----------
# A real, direct extension of odds_api.devig_two_way -- that function already powers Best Bets'
# own "vs XX% typical" display for player props (via real_market_prob) whenever a real book
# posted both sides, but nothing did the same real math one level up, for a game's own real
# moneyline. real_moneyline_devig (odds_api.py) closes that gap using the SAME proven formula,
# never a reimplementation -- see that function's own docstring for the full reasoning,
# including why it refuses to mix two different books' own real prices together.
#
# OPT-IN, matching this platform's own established pattern for any feature needing a genuinely
# NEW live-odds fetch (see Best Bets' own "Show blowout risk (uses live odds API quota)"
# checkbox) -- this costs real API quota fetching a "h2h" market per game, so it never fires
# silently just because Command Center loaded.
C.section_header("⚖️", "Today's game lines — de-vigged")
st.caption("Real, no-vig probability from today's actual moneyline, with the sportsbook's own "
          "margin removed — the exact same math Best Bets already applies to player props "
          "(via the 📊 icon on \"vs XX% typical\"), one level up to the game itself.")
_show_game_devig = st.checkbox("Show de-vigged moneylines (uses live odds API quota)",
                               key="_show_game_devig")
if _show_game_devig:
    @st.cache_data(ttl=600, show_spinner=False)
    def _load_game_moneylines(date_str_inner: str, odds_sport_key: str):
        """Real, captured moneyline prices for every team playing today, for whichever sport is
        currently active -- same real caching contract (600s ttl, None on no API key configured
        vs {} on a genuine "fetched, nothing found") as Game Watch's own load_real_moneylines,
        just sport-aware via odds_sport_key rather than hardcoded to O.SPORT, since Command
        Center itself is multi-sport."""
        api_key = BBD.get_odds_api_key()
        if not api_key:
            return None
        try:
            moneylines, _info = BBD.O.fetch_slate_moneylines(date_str_inner, api_key, sport=odds_sport_key)
            return moneylines
        except Exception:
            return None

    _game_moneylines = _load_game_moneylines(today, _active.odds_sport_key)
    if _game_moneylines is None:
        st.info("No live odds API key configured — de-vigged lines aren't available right now.")
    else:
        _plays_gd, _meta_gd = _board(_active.key, today)
        _preferred_book_gd = st.session_state.get(f"_preferred_book_{_active.key.lower()}", BBD.O.DEFAULT_BOOK)
        _devig_rows = []
        for g in _meta_gd:
            result = BBD.O.real_moneyline_devig(_game_moneylines, g.get("away_name", ""),
                                                g.get("home_name", ""),
                                                preferred_book=_preferred_book_gd)
            if result is None:
                continue
            no_vig_away, book = result
            _devig_rows.append({
                "Game": g.get("label", f"{g.get('away_name','?')} @ {g.get('home_name','?')}"),
                g.get("away_name", "Away"): f"{no_vig_away:.1%}",
                g.get("home_name", "Home"): f"{1 - no_vig_away:.1%}",
                "Book": book,
            })
        if _devig_rows:
            st.dataframe(pd.DataFrame(_devig_rows), hide_index=True, width="stretch")
            st.caption("Only games where a single real book posted both real prices are shown — "
                      "never a guessed or cross-book-mixed number.")
        else:
            st.info("No real, same-book, two-sided moneyline found for today's games yet — "
                   "check back closer to first pitch.")

st.divider()
left, right = st.columns([3, 2])
 
# ---------- tonight's top plays ----------
with left:
    with st.container(border=True):
        C.section_header("⭐", "Tonight's top leans")
        # Owner-only Graded Picks pointer — Graded Picks itself is gated the same way (moved to
        # owner-only directly on request, to guarantee no broken public links as the subscriber
        # split hardens), so this stays hidden for a public/Discord audience rather than linking to
        # a page they can't open, the same pattern already used just below for Data Health.
        # ALSO now gated on has_projections -- Graded Picks hides itself entirely for any sport
        # without a projections model (UFC), same real StreamlitPageNotFoundError risk just
        # confirmed and fixed on Bet Log's own link to Track Record (see that page's own comment).
        if st.secrets.get("AUDIENCE", "owner") == "owner" and _active.has_projections:
            st.page_link("views/2_Graded_Picks.py", label="See the full slate, graded game by game →",
                        icon="🏅")
        if plays:
            # A REAL, CONFIRMED FIX, not the original design -- this used to sort by raw Conviction
            # directly, which can genuinely INVERT against the letter-grade system every other page
            # (Graded Picks, Suggested Parlays, Speculative Basket) already uses: a raw 2.5x on HR
            # (ceiling ~9.09, a "B") can outrank a raw 1.8x on a near-50%-reference market (ceiling
            # ~2.0, a genuine "A") purely because HR's own raw numbers run bigger, even though the
            # SECOND play is the stronger one by every other page's own grading logic. Grading every
            # play here too, and sorting/filtering by the SAME ceiling-normalized rank_value grading.
            # conviction_to_grade already exposes for exactly this reason, means "Tonight's top
            # leans" now agrees with what Graded Picks itself would show for the same slate --
            # intra-page consistency, not a second, silently different ranking of "the same" model.
            # A REAL, CONFIRMED FIX, not the original design -- Top Leans used to sort by rank_value
            # (the ceiling-normalized Conviction metric), which is the wrong number for what a "top
            # lean" actually means to a real person. Confirmed directly with a real, reported
            # example: a genuine longshot Triples play (11% real chance of happening, an 89% chance
            # it doesn't) can carry a raw Conviction of 4.44x purely because Triples' reference rate
            # is so low (~2.5%) that even a modest real probability looks huge relative to it --
            # rank_value would still rate this a real, valid grade, but "leans" colloquially means
            # "I lean toward this happening," which is a probability question, not an edge-relative-
            # to-typical one. This is the SAME real distinction already built into Suggested Parlays'
            # Safer/Steady tiers -- Top Leans just never got the same treatment. Graded Picks itself
            # stays rank_value-sorted on purpose (its entire identity IS the letter-grade system),
            # but this widget's own name and purpose are different. See grading.build_top_leans' own
            # docstring for the full reasoning -- pulled out of this view for the same reason every
            # other piece of real logic on this platform lives in grading.py, not trusted by eye in
            # the browser.
            _TOP_TABS = [("All", None)] + [(f"{_MARKET_ICONS.get(m, '🔹')} {m}", m)
                                           for m in _active.market_map.keys()]
            _mkt = C.wrapped_tab_picker(_TOP_TABS, key="top_leans_market")
            if _mkt is None:
                subset = grading.build_top_leans(plays, per_market=2)
                st.caption("Best two leans from each market — so this isn't just one market's tab again.")
            else:
                subset = [p for p in grading.build_top_leans(plays, per_market=8)
                         if p["Market"] == _mkt][:8]
            if subset:
                for p in subset:
                    p["Grade"] = p["_grade"]["letter"]
                    p["_display_line"] = (f"📊 {p['Line']:g}" if p.get("LineSource") == "book"
                                          and p.get("Line") is not None
                                          else f"{p['Line']:g}" if p.get("Line") is not None else "—")
                    # The actual fix for a real, reported optics problem: Grade and Model %
                    # look like they should move together (higher probability -> better
                    # grade), but they're deliberately different axes -- Grade/Conviction
                    # measure edge relative to what's TYPICAL for that specific line, not raw
                    # likelihood. Without seeing that baseline, a C at 80% sitting above an A
                    # at 79% looks like a bug even though it's correct math. The baseline is
                    # derived directly from data already on the play (ModelProb/Conviction),
                    # not a new computation -- the same number the grade was already using,
                    # just no longer hidden behind a caption someone has to trust.
                    conv = p.get("Conviction")
                    mp = p.get("ModelProb")
                    if conv and mp is not None and conv > 0:
                        baseline = mp / conv
                        marker = "📊 " if p.get("ConvictionSource") == "book" else ""
                        p["_baseline"] = f"{marker}{baseline:.0%}"
                    else:
                        p["_baseline"] = "—"
                tdf = pd.DataFrame(subset)[["Grade", "ModelProb", "Player", "Team", "TeamTrend",
                                            "Market", "Side", "_display_line", "Conviction",
                                            "_baseline", "Why"]]
                st.dataframe(
                    tdf.rename(columns={"ModelProb": "Model %", "Why": "Reasoning",
                                        "_display_line": "Line", "_baseline": "Baseline",
                                        "TeamTrend": "Team Trend"})
                    .style.format({"Model %": "{:.0%}", "Conviction": "{:.2f}×"})
                    .theme_gradient(cmap="Greens", subset=["Model %"]),
                    column_config={"Reasoning": st.column_config.TextColumn(width="large")},
                    hide_index=True, width="stretch", height=330)
                st.caption("**Baseline** is the real reference rate Conviction (and therefore "
                          "Grade) is actually measured against for that exact line — "
                          "Model % ÷ Conviction. It's why Grade and Model % don't move "
                          "together: an 80% Model % against an 80%+ baseline is barely any "
                          "edge at all (a real, correctly low grade), while a 65% Model % "
                          "against a 20% baseline is a massive one. 📊 means the baseline "
                          "itself is a real, live no-vig market rate, not this platform's own "
                          "typical-rate estimate for the market.")
            else:
                st.caption("No leans in this market on tonight's board.")
            st.caption("Ranked by real probability of hitting (Model %), among plays that clear at "
                      "least a C grade — not by Conviction alone, which measures edge relative to a "
                      "market-typical rate and can run high on a genuine longshot in a rare-event "
                      "market. D-grade picks are excluded here on purpose (same as Graded Picks' own "
                      "summary): a near-certain \"Under\" on a rare-event market like Stolen Bases or "
                      "Triples can show a 95%+ Model % while still earning the platform's own lowest "
                      "grade, because that market's own typical rate is already close to 100% — a "
                      "high Model % there isn't a real edge, just a market where almost nothing "
                      "happens for almost everyone. A grade shown here (C or better) means real, "
                      "validated edge, not just a high raw probability.")
            # Quick-log widget, added directly on request: during a real, narrow pick-making window,
            # having to separately re-enter a pick into Bet Log is real friction that gets skipped in
            # favor of just making the pick. Uses the same curated "best 2 per market" set shown in
            # the All tab -- the most representative summary of tonight's top leans, not a separate
            # widget per market tab (which would mean 15+ redundant copies). Owner-only (quick_log
            # itself enforces this, so this stays hidden for a public/Discord audience even though
            # Command Center itself is a public page).
            # _real_offers: the SAME real sportsbook offers already fetched to price this board (see
            # best_bets_data.py's own offers side-channel) -- reused so a logged pick gets a real
            # captured price when one exists, instead of quick_log always falling back to Fair odds.
            _real_offers = st.session_state.get(f"_real_offers_{_active.key}_{today}") or []
            quick_log.render_quick_log(grading.build_top_leans(plays, per_market=2), today,
                                       _active.key, key_prefix="top_leans", offers=_real_offers)
        else:
            st.info("No games on the board right now. Top leans appear here on an active slate.")
 
# ---------- proof panel (the hero) ----------
with right:
    with st.container(border=True):
        C.section_header("🧾", "The proof")
        clv_bets = [b for b in bets if b.get("close_odds") is not None and b.get("entry_odds") is not None]
        if clv_bets:
            clv_bets = sorted(clv_bets, key=lambda b: b.get("ts_placed", ""))
            running, tot = [], 0.0
            for i, b in enumerate(clv_bets, 1):
                tot += B.clv_pct(b["entry_odds"], b["close_odds"]) or 0
                running.append(tot / i)
            fig = go.Figure(go.Scatter(y=running, mode="lines+markers", line=dict(color="#22c55e")))
            fig.add_hline(y=0, line_dash="dash", line_color="#64748b")
            fig.update_layout(height=240, margin=dict(l=10, r=10, t=24, b=10),
                              title="Average CLV over time (%)", template="plotly_white")
            st.plotly_chart(fig, width="stretch")
            st.caption(f"Positive and climbing = beating the market. {len(clv_bets)} bets with closing lines.")
        else:
            st.info("**Tracking since inception.** CLV and calibration populate here as bets are logged "
                    "and settled — this is the honest, forward-tested track record, not a backtest. "
                    "Log plays from the Edge Board to begin.", icon="🧭")
 
        cal = B.calibration(bets, n_bins=5) if bets else []
        if cal:
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines",
                                      line=dict(dash="dash", color="#94a3b8"), showlegend=False))
            fig2.add_trace(go.Scatter(x=[c["predicted"] for c in cal], y=[c["actual"] for c in cal],
                                      mode="markers", marker=dict(size=12, color="#7c3aed"), showlegend=False))
            fig2.update_layout(height=240, margin=dict(l=10, r=10, t=24, b=10),
                               title="Calibration: predicted vs actual", template="plotly_white",
                               xaxis_range=[0, 1], yaxis_range=[0, 1])
            st.plotly_chart(fig2, width="stretch")
 
# ---------- model-caught highlight (yesterday) ----------
st.divider()
C.section_header("🎯", "The model's own top picks — confirmed")
if _active.key == "MLB":
    st.caption("Players whose result cleared the line AND sat in the model's top plays before "
               "the game — real, direct proof the model's own pre-game confidence lined up "
               "with what actually happened, not a claim these were surprising or hard to spot. "
               "Surfaced by matchup, platoon, Statcast, and weather, not name recognition — a "
               "correct #1-ranked pick counts the same here whether it's a household name or "
               "not. (Exploratory; see Retrospective.)")
else:
    st.caption("Players whose result cleared the line AND sat in the model's top plays before "
               "the game — real, direct proof the model's own pre-game confidence lined up "
               "with what actually happened. Surfaced by recent form, not name recognition. "
               "(Exploratory; see Retrospective.)")
try:
    catches, misses, rows_by_pid, _ = yesterday_catches(_active.key, yest, tuple(_active.market_map.keys()))
except Exception:
    catches, misses, rows_by_pid = {}, {}, {}

_caught_markets = list(_active.market_map.keys())
_TOP_PICKS_ITEMS = [(f"{_MARKET_ICONS.get(m, '🔹')} {m}", m) for m in _caught_markets]
_mkt = C.wrapped_tab_picker(_TOP_PICKS_ITEMS, key="top_picks_market")
caught = catches.get(_mkt, [])
if caught:
    cdf = pd.DataFrame(caught[:6])
    cdf["Pre-game rank"] = cdf.apply(lambda r: f"#{r['Rank']} of {r['OfTotal']}", axis=1)
    cols = [c for c in ["Player", "Value", "Line", "ModelProb", "Pre-game rank"] if c in cdf.columns]
    cdf = cdf[cols].rename(columns={"ModelProb": "Model %", "Value": _mkt})
    fmt = {"Model %": "{:.0%}", "Line": "{:g}", _mkt: "{:.1f}"}
    st.dataframe(cdf.style.format({k: v for k, v in fmt.items() if k in cdf.columns}, na_rep="—"),
                hide_index=True, width="stretch")
    # REAL, CONFIRMED EXPLANATION for something a user flagged as looking "off" -- every player
    # in this table showing the identical Line value (the sport's own _MARKET_SPEC default, e.g.
    # WNBA Points = 12.5) is expected here, not a wiring bug. odds_api.fetch_slate_props pulls
    # its event list from the Odds API's own /events endpoint, which only lists current/upcoming
    # games (see that function's own docstring: "the game has already started and books pulled
    # pre-game player props"). By the time this table looks back at YESTERDAY's already-finished
    # games, there's no live event left to fetch a real captured line from -- every play falls
    # back to the model's own placeholder line honestly, the same fallback used any time a real
    # line genuinely isn't available. Real historical lines were never actually gone (Bet Log's
    # own closing-line capture stores them for anything logged), just not wired into THIS
    # specific backward-looking table.
    st.caption("Line reflects the model's own evaluation threshold. Real captured book lines "
              "aren't fetchable for games that already finished by the time this table looks "
              "back at them — the live odds feed only covers current/upcoming games.")
else:
    st.caption("Nothing cleared the line in the model's top plays for this market last night, "
               "or results aren't final yet.")

# ---------- genuinely surprising hits (the actual "opposite side," requested previously) ----------
# market_report already computes this exact bucket (players whose result cleared the line but
# whose PRE-GAME rank sat OUTSIDE the model's own top tier) -- it was just being discarded. This
# is the honest complement to "top picks confirmed" above: that section shows the model's own
# high-confidence calls landing (expected, if the model is well-calibrated); this one shows
# outcomes the model DIDN'T have strong pre-game confidence in, that happened anyway. Neither
# section claims the other's data -- "top picks confirmed" no longer says "non-obvious," and this
# section is the one actually built to carry that meaning.
st.divider()
C.section_header("🔦", "Surprising hits — the model didn't see these coming")
st.caption("Players whose result ALSO cleared the line last night, but who sat OUTSIDE the "
          "model's own top-ranked plays pre-game — genuinely low pre-game confidence, not a "
          "confirmed top pick. A real, honest signal worth a second look either way: either the "
          "model is missing something about this player/matchup worth investigating, or it's a "
          "genuinely unpredictable event landing as variance does. The Reason column (MLB only "
          "for now) tells you which: \"Catchable\" means a real signal existed and the model "
          "under-weighted it — worth investigating. \"Genuine variance\" means the model was "
          "right to rank it low; this is randomness, not a modeling gap — chasing these is "
          "exactly the overfitting this platform avoids. Sorted worst-ranked (most surprising) "
          "first. (Exploratory.)")
_SURPRISE_ITEMS = [(f"{_MARKET_ICONS.get(m, '🔹')} {m}", m) for m in _caught_markets]
_mkt = C.wrapped_tab_picker(_SURPRISE_ITEMS, key="surprising_hits_market")
surprises = sorted(misses.get(_mkt, []), key=lambda x: -x["Rank"])
if surprises:
    sdf = pd.DataFrame(surprises[:6])
    sdf["Pre-game rank"] = sdf.apply(lambda r: f"#{r['Rank']} of {r['OfTotal']}", axis=1)
    if _active.key == "MLB":
        sdf["Reason"] = sdf["PlayerId"].apply(
            lambda pid: R.explain_miss(rows_by_pid.get(pid), _mkt))
    cols = [c for c in ["Player", "Value", "Line", "ModelProb", "Pre-game rank", "Reason"]
           if c in sdf.columns]
    sdf = sdf[cols].rename(columns={"ModelProb": "Model %", "Value": _mkt})
    fmt = {"Model %": "{:.0%}", "Line": "{:g}", _mkt: "{:.1f}"}
    st.dataframe(sdf.style.format({k: v for k, v in fmt.items() if k in sdf.columns}, na_rep="—"),
                column_config={"Reason": st.column_config.TextColumn(width="large")},
                hide_index=True, width="stretch")
else:
    st.caption("No real surprises for this market last night — every real hit sat in the "
              "model's own top-ranked plays, or results aren't final yet.")

st.divider()
st.caption("⚖️ For analysis and entertainment. Not financial advice and not a guarantee — outcomes "
           "are uncertain and variance is real. Proof metrics reflect logged activity only; empty "
           "panels mean no track record yet, by design. Bet responsibly.")
