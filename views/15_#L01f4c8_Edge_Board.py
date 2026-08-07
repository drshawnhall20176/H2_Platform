"""
Edge Board — the predictive + edge layer.
 
Two views from a single Monte Carlo pass:
  1. Model board: probabilities and fair prices for every prop (no odds needed).
  2. Live edges: when you fetch odds, the model is re-evaluated AT THE BOOK'S LINE,
     the price is de-vigged, and plays are ranked by EV%.
 
The API key is read from st.secrets / env — never hardcoded. Player props are quota-
expensive, so the live fetch is behind a button and cached.
"""
 
import os
from typing import Optional
from datetime import datetime
 
import pandas as pd
import pytz
import streamlit as st
import components as C
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
 
import sports
import odds_api as O
import betlog as B
import bet_sizing as BS
import statcast_data as SC
import weather as WX
import mlb_shared_cache as MSC

_active = sports.active()

if not _active.has_projections:
    C.base_css()
    C.page_header("📈", "Edge Board", "Model probabilities, fair prices, and live edges")
    st.info("🥊 Edge Board doesn't apply to UFC — it's built on player stat projections. "
            "Head to **UFC Fight Card** in the sidebar for tonight's bouts and odds.")
    st.stop()
E, P = _active.engine, _active.projections   # sport-routed: MLB -> mlb_engine/projections,
                                              # WNBA -> wnba_engine/wnba_projections, etc.
C.base_css()
C.page_header("📈", "Edge Board",
             f"Where the edge shows its work. Model probabilities, fair prices, and live edges for every prop on the slate "
             f"— {_active.icon} {_active.label}")

if not sports.require_live_engine("Edge Board"):
    st.stop()
 
eastern = pytz.timezone("US/Eastern")
 
# Odds-API-market-key -> display label, built from the active sport's OWN market_map (Stage 1),
# not a hardcoded per-sport dict. Adding a sport's markets to sports.py is now sufficient; this
# page needs no further edits.
MARKET_LABEL = {v: k for k, v in _active.market_map.items()}
 
 
def get_api_key():
    try:
        return st.secrets["ODDS_API_KEY"]
    except Exception:
        return os.environ.get("ODDS_API_KEY")
 
 
# load_statcast (a local @st.cache_data wrapper around SC.load()) consolidated into
# statcast_data.load_cached — this exact wrapper used to be independently redefined in 6 places
# platform-wide, each its own separate, unshared cache entry despite doing identical real work.
# See that function's own docstring for the full real, confirmed finding.
 
 
# load_weather (a local @st.cache_data wrapper doing a SEQUENTIAL per-game loop) consolidated
# into weather.load_slate_weather — this exact wrapper used to be independently redefined in 3
# places platform-wide, and unlike every other per-game/per-player fetch in this codebase, it
# fetched one game's weather at a time with zero concurrency. See that function's own docstring
# for the full real, confirmed finding.
 
 
@st.cache_data(ttl=300, show_spinner=False)
def load_index(sport_key: str, date_str: str, sims: int, seed: int):
    """Sport-routed: dispatches to that sport's own engine/projections modules. MLB additionally
    layers in Statcast + weather enrichment (its own model inputs, unique to baseball); other
    sports don't have those and build their projection index straight from the engine's rows.

    Returns (index, known_names, all_active_names) -- known_names ADDED DIRECTLY ON REQUEST, a
    real, confirmed fix for a real, reported case (see projections.known_roster_names' own
    docstring for the full reasoning); all_active_names a SECOND real, confirmed fix layered on
    the first (see mlb_engine.get_all_active_player_names' own docstring). Both use hasattr/a
    real sport_key check, not a hard assumption: MLB has these real helpers today, other sports
    don't yet, and this must not break for any of them -- an empty set here is an honest "no
    real distinction available yet" for a sport that hasn't wired this in, not a crash or a
    silently wrong guess."""
    sport = sports.get(sport_key)
    engine, proj = sport.engine, sport.projections
    rows, meta = engine.build_slate(date_str)
    extra = {}
    if sport_key == "MLB":
        sc, k = SC.load_cached()
        wx = WX.load_slate_weather(tuple((m.get("venue_id"), m.get("game_date"), m.get("venue")) for m in meta))
        for r in rows:
            w = wx.get(r.get("_venue_id"))
            r["_weather_hr"] = w["hr_factor"] if w else 1.0   # temp + wind on HR, matches Dinger Engine
        extra = {"statcast": sc, "statcast_k": k}
    # Statcast + weather attached (MLB only) -> HR probabilities here are consistent with Dinger Engine.
    index = proj.build_projection_index(rows, meta, sims=sims, seed=seed, **extra)
    known_names = proj.known_roster_names(rows, meta) if hasattr(proj, "known_roster_names") else set()
    all_active_names = (MSC.get_all_active_player_names_cached(int(date_str[:4]))
                        if sport_key == "MLB" else set())
    return index, known_names, all_active_names


@st.cache_data(ttl=300, show_spinner=False)
def load_edges(sport_key: str, date_str: str, markets_tuple: tuple, _index: dict, _api_key: str,
               _known_names: Optional[set] = None, _all_active_names: Optional[set] = None):
    sport = sports.get(sport_key)
    offers, info = O.fetch_slate_props(date_str, _api_key, list(markets_tuple),
                                       sport=sport.odds_sport_key)
    edges, stats = O.compute_edges(_index, offers, projections_module=sport.projections,
                                   known_names=_known_names, all_active_names=_all_active_names)
    return edges, {**info, **stats}
 
 
# --- controls ---------------------------------------------------------------
c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    target_date = st.date_input("Slate date", datetime.now(eastern))
with c2:
    min_prob = st.slider("Min model prob (model board)", 0.50, 0.95, 0.60, 0.01)
with c3:
    st.write("")
    if st.button("🔄 Refresh slate"):
        st.cache_data.clear()
        st.rerun()
 
date_str = target_date.strftime("%Y-%m-%d")

with st.spinner("Projecting the slate..."):
    index, known_names, all_active_names = load_index(_active.key, date_str, P.DEFAULT_SIMS, seed=7)

if not index:
    st.info(f"No projectable props for this date. Pick a date with scheduled {_active.label} games.")
    st.stop()
 
board = pd.DataFrame(P.default_board_from_index(index))
 
# ============================================================================
# LIVE EDGES
# ============================================================================
C.section_header("💵", "Live edges")
api_key = get_api_key()
 
if not api_key:
    st.warning(
        "No API key found. Create `.streamlit/secrets.toml` with "
        "`ODDS_API_KEY = \"your_key\"` (and add it to .gitignore), or set the "
        "`ODDS_API_KEY` environment variable. Then reload.",
        icon="🔑",
    )
else:
    ec1, ec2 = st.columns([3, 1])
    with ec1:
        # A REAL, CONFIRMED FIX, not the original design: _active.markets (every market
        # registered in sports.py's own market map, for MLB 16 total) used to be both the real
        # options list AND the real default selection here -- but MLB's own build_projection_
        # index only ever builds a real index entry for 7 of those 16 (a hardcoded tuple list
        # that was never kept in sync as new markets like Batter RBIs and Batter Stolen Bases
        # got added to the market map over time). Any of the other 9 was GUARANTEED to show up
        # as "unmatched" for every single player the book offered it for, regardless of name
        # spelling -- confirmed directly from a real, reported Edge Board run showing six
        # different players all failing on the exact same market (batter_rbis), the real
        # signature of an unsupported market, not a name-matching problem. Reuses P._MARKET_
        # DISPLAY (MLB's own real, already-accurate list of what it can price) as the source of
        # truth when it exists; every other sport's own build_projection_index is already
        # market-spec-driven (covers every registered market with no such gap), so this falls
        # back to the original, still-correct _active.markets for them.
        priceable_markets = list(getattr(P, "_MARKET_DISPLAY", {}).keys()) or _active.markets
        chosen = st.multiselect(
            "Markets to price (each market × each game = 1 quota unit)",
            priceable_markets, default=priceable_markets,
            format_func=lambda k: MARKET_LABEL.get(k, k),
        )
    with ec2:
        min_ev = st.slider("Min EV%", -10.0, 30.0, 0.0, 0.5)
 
    n_games = len({v["ctx"]["game"] for v in index.values()})
    est_cost = len(chosen) * max(n_games, 1)
    st.caption(f"Estimated quota cost of a fetch: ~{est_cost} units "
               f"({len(chosen)} markets × ~{n_games} games). Cached for 5 min after fetching.")
 
    st.markdown("**Credibility filters** — keep the board honest, not just impressive")
    gc1, gc2, gc3 = st.columns(3)
    with gc1:
        max_odds = st.slider("Max odds — skip long shots", 150, 1000, 400, 25,
                             help="Long-shot prices (roughly +450 and up — think 2+ HR props) are "
                                  "where the model's tail probabilities are least reliable, so huge "
                                  "'EV' there is almost always model error, not a real edge. Capping "
                                  "the price keeps the board on bets the model can actually be trusted on.")
    with gc2:
        max_ev = st.slider("Max EV% — skip 'too good to be true'", 10, 100, 25, 5,
                           help="A genuine edge is usually a few percent. A +50% or +90% EV is almost "
                                "always the model being overconfident — especially on rare events or "
                                "high-probability pitcher props — not free money the whole market missed. "
                                "Hiding implausible EV protects you from trusting model error.")
    with gc3:
        top_n = st.slider("Show top N edges", 5, 50, 20, 5,
                          help="Surface the most credible plays, not every prop with a positive number. "
                               "You'd never bet 200 props — don't let the board imply you should.")
    heavy_fav_floor = st.slider(
        "Heavy-favorite floor — skip prices more juiced than this", -600, -100, -300, 25,
        help="The other half of the odds band. A price like -476 means risking ~$4.76 to win $1 — "
             "you need a huge, reliable edge to justify it, and one miss erases several wins. "
             "Together with the long-shot cap above, this keeps the board on prices in a sane "
             f"window (roughly {-300} to +{400} by default).")
 
    st.markdown("**Stake sizing (fractional Kelly)** — set your bankroll here; it drives every "
                "stake and cap, so bump it up as you (paper-)win and watch the guardrails scale with it")
    kc1, kc2, kc3 = st.columns(3)
    with kc1:
        bankroll = st.number_input("Bankroll ($)", min_value=1.0, value=150.0, step=5.0,
                                   help="Today's roll. Change it any day — every stake, the per-bet cap, "
                                        "and the per-game cap all recompute instantly off this number.")
    with kc2:
        frac_label = st.select_slider("Kelly fraction", options=["Quarter", "Half", "Full"],
                                      value="Quarter",
                                      help="Quarter-Kelly is the safe default — model probabilities "
                                           "are noisy, and full Kelly overbets when an edge is off.")
        kelly_frac = {"Quarter": 0.25, "Half": 0.5, "Full": 1.0}[frac_label]
    with kc3:
        cap_pct = st.slider("Max bet (% of bankroll)", 1, 25, 5,
                            help="Hard ceiling per bet — protects against a mis-estimated edge "
                                 "recommending a huge stake.") / 100.0
 
    kd1, kd2 = st.columns(2)
    with kd1:
        shade_pts = st.slider("Model shading (points)", 0, 10, 5,
                              help="Subtract this many percentage points from every model probability "
                                   "BEFORE sizing. Models run hot on small samples and soft matchups; a "
                                   "flat haircut is honest insurance. A thin edge can size to $0 after "
                                   "shading — that's the discipline working, not a bug.")
    with kd2:
        per_game_pct = st.slider("Max per game (% of bankroll)", 2, 40, 10,
                                 help="Props in the same game are correlated — if the starter is sharp, "
                                      "a whole cluster misses together. Kelly assumes bets are independent, "
                                      "so it overbets one game. This caps total exposure per game and scales "
                                      "that game's bets down proportionally.") / 100.0
 
    if st.button("📡 Fetch live odds & compute edges", type="primary", disabled=not chosen):
        st.session_state["do_fetch"] = True
 
    if st.session_state.get("do_fetch"):
        try:
            with st.spinner("Fetching odds and computing edges..."):
                edges, info = load_edges(_active.key, date_str, tuple(sorted(chosen)), index, api_key,
                                         known_names, all_active_names)
        except O.OddsAPIError as e:
            st.error(f"Odds API error: {e}")
            edges, info = [], {}
 
        if info:
            q1, q2, q3, q4 = st.columns(4)
            q1.metric("Quota remaining", info.get("remaining", "—"))
            q2.metric("Games priced", info.get("events_fetched", "—"))
            q3.metric("Props matched", info.get("matched", "—"))
            q4.metric("Unmatched (name/line)", info.get("unmatched", "—"),
                     help="Counts every real failed offer, including when multiple books each "
                         "post the same unmatched player/market -- so this can legitimately run "
                         "higher than the player/market panel(s) below, which show each real "
                         "unique mismatch once, not once per book.")

            no_offer = info.get("no_offer_events") or []
            if no_offer:
                st.caption(f"⚪ {len(no_offer)} of {info.get('events_fetched', '—')} priced game(s) "
                          f"returned no live props for the selected markets — most likely already "
                          f"underway (books pull pre-game props once a game starts), so there's no "
                          f"live pre-game edge left to compute. These won't appear in \"Filter by "
                          f"game\" below even though they were queried: {', '.join(no_offer)}")

            todays_events = info.get("todays_events") or []
            with st.expander(f"🔍 Raw events returned by the odds provider today ({len(todays_events)})"):
                if todays_events:
                    st.dataframe(pd.DataFrame(todays_events), hide_index=True, width="stretch")
                else:
                    st.caption("No events at all came back for today's date.")
                st.caption("If a game you expect isn't in this list, it's not a matching or "
                          "parsing issue on our side — the provider's own event feed didn't "
                          "include it. Doubleheaders are the most likely case: some providers "
                          "only expose one event per team pairing per day, not one per leg.")

            unmatched_names = info.get("unmatched_names") or []
            if unmatched_names:
                # A REAL, CONFIRMED FIX, not the original design: every real unmatched offer
                # used to land in ONE undifferentiated list, whether it was a genuine, fixable
                # name-spelling mismatch or a real player genuinely on tonight's roster with too
                # little real data for the model to honestly price -- confirmed directly from a
                # real, reported case where established veterans just off a long injury (Sean
                # Murphy), just traded (Kevin Gausman), and real rookies (Abimelec Ortiz) all
                # sat in the same bucket as a real name-normalization bug. A SECOND real,
                # confirmed follow-up found real, active, correctly-spelled players (Kevin
                # Gausman again, Alí Sánchez, Edgar Quero, Zach Thornton) STILL sitting in the
                # real mismatch bucket, simply because none of them was part of TONIGHT's
                # specific slate -- a real, different reason than a spelling bug. Split here
                # into three real, honest sections using the real "reason" tag compute_edges now
                # attaches -- "unknown" (a sport without known_names wired in yet) is shown in
                # the same single-list form as before, never silently dropped or miscategorized.
                mismatches = [u for u in unmatched_names if u.get("reason") == "name_mismatch"]
                no_data = [u for u in unmatched_names if u.get("reason") == "on_roster_no_data"]
                not_tonight = [u for u in unmatched_names if u.get("reason") == "not_playing_tonight"]
                unclassified = [u for u in unmatched_names if u.get("reason") not in
                               ("name_mismatch", "on_roster_no_data", "not_playing_tonight")]

                if mismatches:
                    with st.expander(f"❓ {len(mismatches)} real player(s)/market(s) the book "
                                     f"posted but we couldn't match to our own slate at all"):
                        st.dataframe(pd.DataFrame(mismatches)[["player", "market"]].rename(
                            columns={"player": "Player (as the book spelled it)", "market": "Market"}),
                            hide_index=True, width="stretch")
                        st.caption("A real mismatch usually means the book's own spelling of "
                                  "this name differs from what our roster data has (an accent, "
                                  "a suffix, a nickname) — normalize_name already strips "
                                  "accents/punctuation/Jr.-Sr.-II-III-IV-V and a real trailing "
                                  "birth-year disambiguator, so a name still showing up here "
                                  "needs its own real fix, not a guess. This name genuinely "
                                  "doesn't appear anywhere on tonight's real roster data, and "
                                  "isn't a real, currently active MLB player under any real "
                                  "spelling either.")

                if no_data:
                    with st.expander(f"⏳ {len(no_data)} real player(s)/market(s) on tonight's "
                                     f"roster with too little real data to price yet"):
                        st.dataframe(pd.DataFrame(no_data)[["player", "market"]].rename(
                            columns={"player": "Player", "market": "Market"}),
                            hide_index=True, width="stretch")
                        st.caption("Not a name problem — each of these real players genuinely "
                                  "showed up on tonight's real roster/lineup data. The model is "
                                  "honestly declining to price them because it doesn't have "
                                  "enough real, current data to build a real projection from yet "
                                  "— a real trade with no debut for the new team yet, a real "
                                  "return from a long injury absence, a real rookie's first "
                                  "handful of games, or a real role change (e.g. a reliever's "
                                  "first career start). This isn't a bug to fix; it's the model "
                                  "correctly refusing to guess.")

                if not_tonight:
                    with st.expander(f"🌙 {len(not_tonight)} real player(s)/market(s) the book "
                                     f"posted for a player not part of tonight's specific slate"):
                        st.dataframe(pd.DataFrame(not_tonight)[["player", "market"]].rename(
                            columns={"player": "Player", "market": "Market"}),
                            hide_index=True, width="stretch")
                        st.caption("Not a name problem, and not a data problem either — each of "
                                  "these is a real, currently active MLB player under this exact "
                                  "spelling, confirmed against MLB's own full, real league-wide "
                                  "roster. They're just not part of TONIGHT's specific games — a "
                                  "different team's game, a bench day, or a real trade where the "
                                  "new team hasn't played them yet. Nothing to fix here either.")

                if unclassified:
                    with st.expander(f"❓ {len(unclassified)} real player(s)/market(s) the book "
                                     f"posted but we couldn't match to our own slate"):
                        st.dataframe(pd.DataFrame(unclassified)[["player", "market"]].rename(
                            columns={"player": "Player (as the book spelled it)", "market": "Market"}),
                            hide_index=True, width="stretch")
                        st.caption("A real mismatch usually means the book's own spelling of this "
                                  "name differs from what our roster data has (an accent, a suffix, "
                                  "a nickname) — normalize_name already strips accents/punctuation/Jr."
                                  "-Sr.-II-III-IV-V and a real trailing birth-year disambiguator, so "
                                  "a name still showing up here needs its own real fix, not a guess. "
                                  "Could also mean this player genuinely isn't on tonight's projected "
                                  "slate at all, or has too little real data to price yet (not a "
                                  "name problem) — this sport doesn't yet distinguish the reasons "
                                  "the way MLB does.")
 
        if edges:
            edf = pd.DataFrame(edges)
            # Credibility filters: clear the EV floor, keep prices inside the odds band
            # [heavy_fav_floor, max_odds], drop implausible EV, keep top N.
            edf = edf[(edf["EV%"] >= min_ev) & (edf["EV%"] <= max_ev)
                      & (edf["Price"] <= max_odds) & (edf["Price"] >= heavy_fav_floor)].copy()
            edf = edf.sort_values("EV%", ascending=False).head(top_n).copy()
            n_longshots = sum(1 for e in edges if e["EV%"] >= min_ev and e["Price"] > max_odds)
            n_heavyfav = sum(1 for e in edges if e["EV%"] >= min_ev and e["Price"] < heavy_fav_floor)
            n_toohigh = sum(1 for e in edges if e["EV%"] > max_ev
                            and heavy_fav_floor <= e["Price"] <= max_odds)
 
            if edf.empty:
                st.info(f"No credible edges at these filters. Hidden: {n_longshots} long shots "
                        f"(beyond +{max_odds}), {n_heavyfav} heavy favorites (more juiced than "
                        f"{heavy_fav_floor}), and {n_toohigh} implausibly-high-EV plays (over {max_ev}% "
                        f"— likely model error). Loosen the filters to see more, but they're hidden for "
                        f"a reason: that's where the model is least trustworthy.")
            else:
                edf["Market"] = edf["Market"].map(lambda k: MARKET_LABEL.get(k, k))
                # Disciplined sizing: shade the model prob, size fractional-Kelly, cap per bet,
                # then cap per game. Recomputes instantly when you move any sizing control (no re-fetch).
                edf = BS.apply_stake_discipline(edf, bankroll, shade_pts=shade_pts,
                                                kelly_frac=kelly_frac, cap_pct=cap_pct,
                                                per_game_pct=per_game_pct)
                edf["Tier"] = edf["Stake $"].map(lambda s: BS.stake_tier(s, bankroll))
 
                # Filter by game — narrow the whole section to one or more games (empty = all).
                if "Game" in edf.columns:
                    if "GameTime" in edf.columns:
                        _go = (edf[["Game", "GameTime"]].dropna(subset=["Game"])
                               .assign(_k=lambda d: d["GameTime"].fillna("~"))
                               .sort_values("_k").drop_duplicates("Game"))
                        _labeler = {g: (f"{P.format_et(t)} — {g}" if P.format_et(t) else g)
                                    for g, t in zip(_go["Game"], _go["GameTime"])}
                        _opts = list(_go["Game"])
                    else:
                        _opts = sorted(edf["Game"].dropna().unique())
                        _labeler = {g: g for g in _opts}
                    _picked = st.multiselect(
                        "Filter by game — leave empty for the whole slate", options=_opts,
                        format_func=lambda g: _labeler.get(g, g), default=[],
                        help="Focus the board on one or more games. Everything below — the metrics, "
                             "the table, the export, and logging — narrows to your selection.")
                    if _picked:
                        edf = edf[edf["Game"].isin(_picked)].copy()
 
                if edf.empty:
                    st.info("No plays for the selected game(s). Clear the filter to see the full slate.")
                    st.stop()
 
                total_stake = edf["Stake $"].sum()
                bets = int((edf["Stake $"] > 0).sum())
                s1, s2, s3 = st.columns(3)
                s1.metric("Recommended bets", bets)
                s2.metric("Total exposure", f"${total_stake:,.2f}")
                s3.metric("of bankroll", f"{(total_stake / bankroll * 100) if bankroll else 0:.0f}%")
                if n_longshots or n_heavyfav or n_toohigh:
                    st.caption(f"🛡️ Hidden as likely model error / bad price: {n_longshots} long shots "
                               f"(beyond +{max_odds}), {n_heavyfav} heavy favorites (past {heavy_fav_floor}), "
                               f"and {n_toohigh} implausibly-high-EV plays (over {max_ev}%). The board shows "
                               f"only what the model can be trusted on.")
 
                # Per-game exposure — the correlation guardrail, made visible.
                gt = BS.game_totals(edf)
                if not gt.empty:
                    cap_dollars = per_game_pct * bankroll
                    hottest = gt.iloc[0]
                    note = (f"🎯 Per-game cap ${cap_dollars:,.2f} ({int(per_game_pct*100)}% of roll). "
                            f"Most-loaded game: {hottest['Game']} at ${hottest['Staked $']:,.2f}.")
                    if len(gt) == 1:
                        note += " Everything tonight is one game — that's a single correlated swing, not many bets."
                    st.caption(note)
 
                show = edf.rename(columns={"ModelProb": "Model %", "ImpliedBest": "Impl %",
                                           "NoVigMkt": "NoVig %", "EdgeVsMkt": "Edge", "Price": "Odds"})
                cols = ["Player", "Team", "Market", "Side", "Line", "Proj", "Model %", "Shaded %",
                        "Book", "Odds", "EV%", "Stake $", "Stake %", "Tier", "Game"]
                show = show[[c for c in cols if c in show.columns]]
 
                def _tier_style(col):
                    # Text color set explicitly on every tier, matching styling.py's own "black
                    # on light backgrounds" convention (#C8E6C9/#FFF3E0/#ECEFF1 are all light
                    # enough — luminance > 150 — that the app theme's default text color applies
                    # otherwise, which is near-white in dark mode: pale background + white text
                    # is nearly invisible, exactly the dark-mode bug reported live on this page).
                    out = []
                    for v in col:
                        if v == "Bet":
                            out.append("background-color: #C8E6C9; color: #111111")   # green: put money on it
                        elif v == "Dust":
                            out.append("background-color: #FFF3E0; color: #111111")   # amber: real but negligible
                        elif v == "No bet":
                            out.append("background-color: #ECEFF1; color: #111111")   # muted: shaded out
                        else:
                            out.append("")
                    return out
 
                styler = (
                    show.style
                    .format({"Model %": "{:.1%}", "Shaded %": "{:.1%}", "Proj": "{:.2f}",
                             "Line": "{:.1f}", "EV%": "{:+.1f}", "Stake $": "${:.2f}", "Stake %": "{:.1%}"})
                    .theme_gradient(cmap="RdYlGn", subset=["EV%"])
                    .theme_gradient(cmap="Blues", subset=["Stake $"])
                    .apply(_tier_style, subset=["Tier"])
                )
                st.dataframe(styler, width="stretch", hide_index=True, height=520)
                st.caption("Ranked by EV% at the best price. **Shaded %** is the model prob after your "
                           "haircut; **Stake $** is fractional-Kelly on that shaded prob, capped per bet "
                           "AND per game. **Tier** reads the stake for you: **No bet** = edge shaded out to "
                           "$0; **Dust** = positive but a negligible slice of bankroll (<0.5%), real but not "
                           "worth the click; **Bet** = enough edge survived to size real money. Tiers are a "
                           "% of bankroll, so they scale as you change your roll. EV% = model_prob × decimal "
                           "payout − 1.")
 
                # --- Export: a static, shareable snapshot (no weblink, no live model) --------
                gen_at = datetime.now(eastern).strftime("%Y-%m-%d %H:%M %Z")
                card = show[show["Stake $"] > 0].copy() if "Stake $" in show.columns else show.copy()
                xlsx_bytes = BS.build_card_xlsx(
                    card, bankroll=bankroll, date_str=date_str, generated_at=gen_at,
                    total_stake=float(card["Stake $"].sum()) if "Stake $" in card.columns else 0.0,
                    n_bets=int(len(card)),
                )
                if xlsx_bytes:
                    st.download_button(
                        "📤 Export tonight's card (Excel)", data=xlsx_bytes,
                        file_name=f"H2_card_{date_str}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        help="A formatted, static snapshot of the sized card — final stakes only. "
                             "Share the file itself; it doesn't expose your model or a link.")
                else:
                    csv_bytes = card.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "📤 Export tonight's card (CSV)", data=csv_bytes,
                        file_name=f"H2_card_{date_str}.csv", mime="text/csv",
                        help="Static snapshot of the sized card (Excel export unavailable in this "
                             "environment, so CSV).")
 
                # --- Log straight to the proof layer (pre-filled, including Kelly stake) ----
                st.markdown("**📒 Log a bet to your proof layer**")
                logable = edf[edf["Stake $"] > 0] if "Stake $" in edf.columns else edf
                if logable.empty:
                    st.caption("No +EV bets to log at the current filter.")
                else:
                    def _label(i):
                        r = logable.loc[i]
                        return (f"{r['Player']} · {r['Market']} {r['Side']} {float(r['Line']):g} "
                                f"@ {int(r['Price']):+d}  (EV {r['EV%']:+.1f}%, ${r['Stake $']:.2f})")
 
                    picks = st.multiselect("Pick the bets you placed — they log with the odds, model "
                                           "probability, and Kelly stake already filled in",
                                           list(logable.index), format_func=_label)
                    if st.button("Log selected bets", type="primary", disabled=not picks):
                        logged_sigs = st.session_state.setdefault("logged_sigs", set())
                        n = skipped = 0
                        for i in picks:
                            r = logable.loc[i]
                            sig = (date_str, r["Player"], r["Market"], r["Side"],
                                   float(r["Line"]), int(r["Price"]))
                            if sig in logged_sigs:
                                skipped += 1
                                continue
                            B.add_bet(slate_date=date_str, game=r.get("Game"), player=r["Player"],
                                      market=r["Market"], side=r["Side"], line=float(r["Line"]),
                                      entry_odds=int(r["Price"]), model_prob=float(r["ModelProb"]),
                                      stake=float(r.get("Stake $", 0) or 0), book=r.get("Book"),
                                      sport=_active.key)
                            logged_sigs.add(sig)
                            n += 1
                        msg = f"Logged {n} bet(s) to the Bet Log — settle them there after the games."
                        if skipped:
                            msg += f" Skipped {skipped} already logged this session."
                        st.success(msg)
        else:
            st.info("No edges to show (no props matched, or all below the EV filter).")
 
# ============================================================================
# MODEL BOARD (no odds needed)
# ============================================================================
st.divider()
C.section_header("🧮", "Model board (no odds)")
st.caption("Model probabilities and fair prices at default lines — your pre-odds scouting view. "
           "Without a market this can't compute edge, but it can flag where an edge could realistically "
           "be *found and bet* once you fetch odds.")
 
view = board[board["ModelProb"] >= min_prob].sort_values("ModelProb", ascending=False).copy()
 
# Game-time filter: turn each game's ISO start into an ET clock string, and let the user
# narrow the scouting view to specific games (sorted by game time) — handy on a spread-out
# slate where you want just the next game up.
if "GameTime" in view.columns:
    view["Time (ET)"] = view["GameTime"].map(P.format_et)
    # order games by actual start time (fall back to the ISO string, which sorts chronologically)
    game_order = (view[["Game", "GameTime"]].dropna(subset=["Game"])
                  .assign(_k=lambda d: d["GameTime"].fillna("~"))
                  .sort_values("_k").drop_duplicates("Game"))
    game_opts = list(game_order["Game"])
    label_for = {g: (f"{P.format_et(t)} — {g}" if P.format_et(t) else g)
                 for g, t in zip(game_order["Game"], game_order["GameTime"])}
    picked = st.multiselect(
        "Filter by game — leave empty for all", options=game_opts,
        format_func=lambda g: label_for.get(g, g), default=[],
        help="Pick one or more games to focus the board. Options are ordered by start time, so the "
             "earliest games are at the top. Empty = show every game.")
    if picked:
        view = view[view["Game"].isin(picked)]
else:
    view["Time (ET)"] = ""
 
# Value lens: a near-lock (fair heavier than -300 — the same heavy-fav line the Edge Board uses)
# has no room to profit, even against a perfectly fair market. A longshot (fair longer than +300)
# is a tail the model prices least reliably. The middle is where a findable, bettable edge lives.
# Also preview the model prob after the standard 5-point honesty haircut.
_SHADE_PREVIEW = 0.05
 
 
def _room(fair_am):
    try:
        a = float(fair_am)
    except (TypeError, ValueError):
        return "—"
    if a <= -300:
        return "🔒 near-lock"
    if a >= 300:
        return "🎯 longshot"
    return "✅ value zone"
 
 
view["Shaded %"] = (view["ModelProb"] - _SHADE_PREVIEW).clip(lower=0)
view["Room"] = view["FairAm"].map(_room)
 
zone_only = st.checkbox(
    "Show only the value zone (hide near-locks & longshots)", value=False,
    help="Near-locks — a 90% strikeout at a fair price of -976, say — can't offer value: even a fair "
         "market pays almost nothing, and shading plus the heavy-fav floor would reject them on the "
         "Edge Board. The value zone (fair roughly -300 to +300) is where a model edge can both exist "
         "and be worth betting. That's where your attention and quota should go.")
if zone_only:
    view = view[view["Room"] == "✅ value zone"]
 
disp = view.rename(columns={"ModelProb": "Model %", "Projection": "Proj",
                            "FairDec": "Fair (dec)", "FairAm": "Fair (am)"})
cols = ["Time (ET)", "Player", "Team", "Market", "Side", "Line", "Proj", "Model %", "Shaded %",
        "Fair (dec)", "Fair (am)", "Room", "Opp", "Game"]
disp = disp[[c for c in cols if c in disp.columns]]
 
 
def _zone_style(col):
    styles = []
    for v in col:
        if v == "✅ value zone":
            styles.append("background-color: #C8E6C9")          # green: value lives here
        elif v == "🔒 near-lock":
            styles.append("background-color: #ECEFF1; color: #888")  # muted: no room
        elif v == "🎯 longshot":
            styles.append("background-color: #FFF3E0")          # amber: unreliable tail
        else:
            styles.append("")
    return styles
 
 
styler2 = (
    disp.style
    .format({"Model %": "{:.1%}", "Shaded %": "{:.1%}", "Proj": "{:.2f}",
             "Line": "{:.1f}", "Fair (dec)": "{:.2f}"})
    .apply(_zone_style, subset=["Room"])
)
st.dataframe(styler2, width="stretch", hide_index=True, height=420)
st.caption("**Room** redirects the eye from raw certainty to actual opportunity: the darkest-probability "
           "rows are usually near-locks (no room), so the green here marks the **value zone** instead — "
           "where a model edge can exist *and* be bet. **Shaded %** previews a 5-point haircut. This is "
           "scouting only; confirm real edge against live prices on the Edge Board above.")
 
with st.expander("How edge is computed (read me)"):
    st.markdown(
        """
1. **Model %** comes from a per-PA Monte Carlo (batters) or innings/Poisson model
   (pitchers), evaluated **at the book's actual line** — not a default — so it's
   comparable to the price.
2. **De-vig:** a book's Over and Under both carry juice. We convert each to an implied
   probability and normalize so they sum to 100% → the **NoVig %** (fair market prob).
3. **EV%** uses the *best* available price across books: `model_prob × decimal − 1`.
   Positive EV% means the price beats your fair value — that's the bet a trader takes.
4. **Edge vs market** = Model % − NoVig %. If this is large, you're disagreeing with the
   market — sometimes that's an edge, often it means the model is missing something
   (injury, weather, role change). Trust it only once calibration backs it up.
5. **Stake $** = fractional Kelly: `f* = (p·d − 1)/(d − 1)`, scaled by your chosen fraction
   and capped. Kelly is the bet size that maximizes long-run growth — but only if your
   probability is exact. Since it isn't, **quarter-Kelly with a hard cap** is the disciplined
   default: it captures most of the growth with far less risk of ruin when an edge is
   mis-estimated. Negative-EV bets get $0.
 
Line shopping matters: always bet the **best** price (the Book column), since EV swings
fast with the number. And remember: from a small bankroll, correct sizing means *small*
bets and slow, bumpy growth — that's the math, not a flaw.
"""
    )


# ============================================================================
# FANTASY FOOTBALL RANKINGS  (NFL only)
# ============================================================================
if _active.key == "NFL":
    st.divider()
    C.section_header("🏈", "Fantasy Football Rankings")
    st.caption("Projected fantasy points from the same model driving the Edge Board — "
               "ranked by position for start/sit decisions. "
               "**No TD projections** (too sparse/random) and **no injury monitoring**. "
               "Use as a projection baseline alongside your own TD/injury reads.")

    sf1, sf2, sf3 = st.columns(3)
    with sf1:
        scoring = st.radio("Scoring format", ["PPR", "Half PPR", "Standard"],
                          key="ff_scoring")
    with sf2:
        pos_filter = st.multiselect(
            "Positions",
            ["QB", "RB", "WR", "TE", "K", "DEF", "DB", "LB", "DL", "DE", "CB", "S"],
            default=["QB", "RB", "WR", "TE"],
            key="ff_positions",
            help="Standard fantasy: QB/RB/WR/TE. IDP leagues: add DB/LB/DL/DE/CB/S. DEF = team defense."
        )
    with sf3:
        top_n_ff = st.number_input("Top N per position", min_value=5,
                                   max_value=30, value=10, key="ff_top_n")

    rec_bonus = {"PPR": 1.0, "Half PPR": 0.5, "Standard": 0.0}[scoring]

    # Load defensive ranks for all teams -- one pass over the weekly stats table,
    # fast because load_season_weekly_stats is already cached from the Edge Board load above.
    @st.cache_data(ttl=3600, show_spinner=False)
    def load_def_ranks(date_str_inner: str) -> dict:
        try:
            return E.get_defense_ranks(date_str_inner)
        except Exception:
            return {}

    def_ranks = load_def_ranks(date_str) if _active.key == "NFL" else {}

    # Aggregate market projections per player into fantasy points
    player_proj = {}
    for (nm, mkey), entry in index.items():
        ctx = entry["ctx"]
        player = ctx["player"]
        mean = entry["mean"]
        if player not in player_proj:
            # Position is now stored in ctx directly -- no need to scan rows
            pos = ctx.get("position", "")
            player_proj[player] = {
                "Player": player, "Team": ctx["team"], "Game": ctx["game"],
                "Opp": ctx.get("opp", ""), "Position": pos,
                "pass_yds": 0.0, "rush_yds": 0.0, "rec": 0.0, "rec_yds": 0.0,
            }
        if mkey == "player_pass_yds":
            player_proj[player]["pass_yds"] = mean
        elif mkey == "player_rush_yds":
            player_proj[player]["rush_yds"] = mean
        elif mkey == "player_receptions":
            player_proj[player]["rec"] = mean
        elif mkey == "player_reception_yds":
            player_proj[player]["rec_yds"] = mean

    ff_rows = []
    for p, d in player_proj.items():
        pos = d["Position"]
        if pos not in pos_filter:
            continue
        fpts = (d["pass_yds"] * 0.04 + d["rush_yds"] * 0.1
                + d["rec"] * rec_bonus + d["rec_yds"] * 0.1)
        if pos == "QB":
            proj_str = f"{d['pass_yds']:.0f} pass yds"
            if d["rush_yds"] > 5:
                proj_str += f" + {d['rush_yds']:.0f} rush"
        elif pos == "RB":
            proj_str = f"{d['rush_yds']:.0f} rush yds"
            if d["rec"] > 0.5:
                proj_str += f" + {d['rec']:.1f} rec / {d['rec_yds']:.0f} rec yds"
        else:
            proj_str = f"{d['rec']:.1f} rec / {d['rec_yds']:.0f} yds"
        opp = d["Opp"]
        opp_ranks = def_ranks.get(opp, {})
        # Pick the rank most relevant to this position
        if pos == "QB":
            def_rank = opp_ranks.get("pass_yds")
        elif pos in ("RB",):
            def_rank = opp_ranks.get("rush_yds")
        else:
            def_rank = opp_ranks.get("rec_yds")

        def_rank_str = (f"#{def_rank}" if def_rank else "—")
        # Color-code: rank 1-10 = easy (green), 11-22 = mid, 23-32 = tough (red)
        if def_rank and def_rank <= 10:
            def_rank_str = f"🟢 #{def_rank}"
        elif def_rank and def_rank >= 23:
            def_rank_str = f"🔴 #{def_rank}"

        ff_rows.append({
            "Player": p, "Pos": pos, "Team": d["Team"], "Opp": d["Opp"],
            "Proj Pts": round(fpts, 1), "Projected stat": proj_str,
            "Opp DEF": def_rank_str, "Game": d["Game"],
        })

    # Real IDP rows — the actual missing piece behind a long-open item: this dropdown already
    # offered DB/LB/DL/DE/CB/S, but nothing here ever computed a real number for any of them.
    # Only fetched when an IDP position is actually selected, so the common QB/RB/WR/TE case
    # doesn't pay for a fetch/computation it doesn't need.
    idp_positions_selected = [p for p in pos_filter if p in E.IDP_POSITION_MAP.values()]
    if _active.key == "NFL" and idp_positions_selected:
        season = E._infer_season(date_str)
        weekly = E.load_season_weekly_stats(season) if season is not None else None
        idp_candidates = (E.get_idp_candidates(weekly, date_str, season)
                          if weekly is not None and not weekly.empty else [])
        # Real game/opponent context for each IDP candidate's own team, from the same meta
        # the rest of this page already built for the offensive side.
        game_by_team = {}
        for m in meta:
            game_by_team[m.get("home_name")] = (m.get("label"), m.get("away_name"))
            game_by_team[m.get("away_name")] = (m.get("label"), m.get("home_name"))
        for c in idp_candidates:
            if c["position"] not in idp_positions_selected:
                continue
            game_label, opp = game_by_team.get(c["team"], (None, None))
            if game_label is None:
                continue   # this player's team isn't on tonight's slate at all
            pts = E.idp_fantasy_points(c)
            proj_str = (f"{c['def_tackles_solo']:.1f} solo tkl"
                       + (f" + {c['def_sacks']:.2f} sk" if c["def_sacks"] >= 0.1 else "")
                       + (f" + {c['def_interceptions']:.2f} int" if c["def_interceptions"] >= 0.1 else ""))
            ff_rows.append({
                "Player": c["player"], "Pos": c["position"], "Team": c["team"], "Opp": opp,
                "Proj Pts": round(pts, 1), "Projected stat": proj_str,
                "Opp DEF": "—", "Game": game_label,
            })
        if idp_positions_selected:
            st.caption("**IDP scoring** (DB/LB/DL/DE/CB/S): solo tackle 1pt, assist 0.5pt, "
                      "sack 2pt, INT 3pt, forced fumble 2pt, pass defended 1pt, defensive TD "
                      "6pt, safety 2pt — one common scoring convention, not a universal "
                      "standard. Check your own league's exact settings before trusting these "
                      "points directly; the underlying per-game stat averages are the more "
                      "portable real number regardless of scoring format.")

    if not ff_rows:
        st.info("No fantasy projections for this slate — try a date with scheduled NFL games.")
    else:
        ff_df = pd.DataFrame(ff_rows).sort_values("Proj Pts", ascending=False)
        for pos in [p for p in ["QB", "RB", "WR", "TE", "K", "DEF", "DB", "LB", "DL", "DE", "CB", "S"] if p in pos_filter]:
            pos_df = ff_df[ff_df["Pos"] == pos].head(top_n_ff).reset_index(drop=True)
            if pos_df.empty:
                continue
            pos_df.index += 1
            st.markdown(f"**{pos}**")
            st.dataframe(
                pos_df[["Player", "Team", "Opp", "Proj Pts", "Projected stat", "Opp DEF", "Game"]],
                width="stretch",
                column_config={
                    "Proj Pts": st.column_config.NumberColumn(
                        "Proj Pts", format="%.1f",
                        help=f"Projected {scoring} fantasy points. No TDs included — "
                             "add manually (QB ~1.5, RB ~0.5, WR/TE ~0.3 per game)."),
                    "Projected stat": st.column_config.TextColumn("Projected stat line"),
                    "Opp DEF": st.column_config.TextColumn(
                        "Opp DEF rank",
                        help="Opposing defense ranked 1-32 by yards allowed at this position. "
                             "🟢 #1-10 = permissive (easy matchup), "
                             "🔴 #23-32 = stingy (tough matchup). "
                             "QB uses pass yds allowed, RB uses rush yds, WR/TE uses rec yds."),
                }
            )
        rec_note = ("+1.0/rec" if scoring == "PPR"
                    else "+0.5/rec" if scoring == "Half PPR" else "no rec bonus")
        st.caption(
            f"**{scoring}** — Pass yds×0.04, Rush/Rec yds×0.1, {rec_note}. "
            "No TD projections (too rare per game to model reliably). "
            "Rule of thumb to add: QB +1.5 TD pts, RB1 +0.5, WR1/TE1 +0.3. "
            "Always check the official injury report before locking lineups."
        )
