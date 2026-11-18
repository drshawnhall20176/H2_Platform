"""
hoops_games_page.py — the game-lines view shared by International Hoops (EuroLeague / NBL) and the college
basketball Game Lab (Nov 3): upcoming games with the model's margin, total and win chance against the books, the
tracking picks where the backtested rules allow one, and the graded record. Data: intl_picks (model_store.game_picks).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import streamlit as st

import components as C
import log_ui as LU

import intl_hoops as I
import intl_picks as IP
import model_store as MS
import props_engine as PE
import sports

EVIDENCE = {
    "EUROLEAGUE": "Backtest vs real lines: spreads with the model 4+ points off went 119-98 (54.8%) over 2022-26, 6+ "
                  "points 59-39 (60%); totals and moneylines showed no edge.",
    "NBL": "Backtest vs real lines: no spread or total edge; the moneyline at a 5%+ edge was slightly positive (+2.5% "
           "over 204) and is tracked.",
}


def _pick(p):
    out = []
    if p.get("pick") and p.get("home_spread") is not None:
        pt = p["home_spread"] if p["pick"] == "home" else -p["home_spread"]
        out.append(f"{p['home'] if p['pick'] == 'home' else p['away']} {pt:+g}")
    if p.get("total_pick") and p.get("line_total") is not None:
        out.append(f"{p['total_pick'].title()} {p['line_total']:g}")
    if p.get("ml_pick"):
        out.append(f"{p['home'] if p['ml_pick'] == 'home' else p['away']} ML")
    return " · ".join(out) or "—"


def _likes(p):
    if p.get("home_spread") is None or p.get("edge") is None:
        return "—"
    if p["edge"] >= 0:
        return f"{p['home']} {p['home_spread']:+g}"
    return f"{p['away']} {-p['home_spread']:+g}"


def _tag(league, p):
    return IP.hoops_use(league, p) if hasattr(IP, "hoops_use") else {"use": p.get("use") or "—", "lock": p.get("lock")}


def _commercial() -> bool:
    """Nov 16: the customer view (a commercial deployment, or the owner previewing it) -- nav_layout.py."""
    try:
        import nav_layout as NL
        return NL.is_commercial(st.secrets.get("AUDIENCE", "owner"), st.session_state.get(NL.PREVIEW_KEY))
    except Exception:                                           # noqa: BLE001 -- no secrets: a local / owner run
        return False


@st.cache_data(ttl=1800, show_spinner=False)
def _season_results(league: str, day: str):
    """This season's finished games from the results archive (what the ratings are fitted on)."""
    season = I.season_of(league, day)
    return [g for g in MS.load_results(league, since=f"{int(season) - 1}-07-01")
            if str(g.get("date") or "") >= (f"{season}-07-01" if league != "WNBA" else f"{season}-01-01")]


def _scoring_side(col, label, ctx, noun):
    with col:
        st.markdown(f"**{label}**")
        if not ctx:
            st.caption("No completed games on file yet")
            return
        s, a = ctx["scored"], ctx["allowed"]
        ds, da = s["recent_avg"] - s["season_avg"], a["recent_avg"] - a["season_avg"]
        # Nov 17: no "+0.0 vs season" arrow when recent IS the season (early on, fewer games than the recent window)
        st.metric("Recent avg scored", f"{s['recent_avg']:.1f}",
                  delta=None if abs(ds) < 0.05 else f"{ds:+.1f} vs season", delta_color="normal")
        st.metric("Recent avg allowed", f"{a['recent_avg']:.1f}",
                  delta=None if abs(da) < 0.05 else f"{da:+.1f} vs season", delta_color="inverse")
        st.caption(f"{ctx['games']} game{'s' if ctx['games'] != 1 else ''} this season")


def _one_game(league, upcoming, day):
    """Nov 16: the football Game Labs' two sections for one game -- team scoring context and the simulated
    moneyline / spread / total (game_sim.py) -- so every Game Lab has them. Simulated around the ratings model's own
    projection: one model, one answer."""
    import game_sim as GS
    st.divider()
    C.section_header("🔬", "One game, up close", "Pick a game for its scoring context and a 20,000-game simulation.")
    ordered = C.by_kickoff(upcoming)
    labels = {f"{_tip(p)} — {p['away']} @ {p['home']}": p for p in ordered}
    p = labels[st.selectbox("Game to simulate", list(labels), key=f"hg_sim_game_{league}")]
    home, away, noun = p["home"], p["away"], GS.unit(league)

    C.section_header("📊", "Team scoring context")
    try:
        results = _season_results(league, str(day))
    except Exception:                                           # noqa: BLE001
        results = []
    c1, c2 = st.columns(2)
    loose = league != "NCAAMB"                                  # the same team matching the ratings model uses
    hc, ac = GS.scoring_context(results, home, loose), GS.scoring_context(results, away, loose)
    _scoring_side(c1, f"{away} (Away)", ac, noun)
    _scoring_side(c2, f"{home} (Home)", hc, noun)
    st.caption(f"Recent = last {GS.RECENT_N} games. A positive change on scoring is good (trending up); a negative "
               f"change on allowed is good (trending tighter). Raw {noun} per game, not adjusted for opponents: the "
               "projection below does that.")

    C.section_header("🎯", "Moneyline / spread / total — simulated")
    # Nov 17: the same one-line answer as the table above, so this close-up never reads as a separate pick
    try:
        import game_previews as GP
        t = _tag(league, p) or {}
        playable = t.get("use") in (PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE)
        st.markdown(f"**{t.get('use') or ''}** {GP.says(p, playable)}")
    except Exception:                                           # noqa: BLE001
        pass
    sim = GS.simulate(league, p.get("model_margin"), p.get("model_total"), key=p.get("game_id"))
    if not sim:
        st.info("No projection for this game yet, so there is nothing to simulate.", icon="🕐")
        return
    mp = p.get("model_p")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(f"{away} ML", "—" if mp is None else f"{1 - mp:.1%}")
    m2.metric(f"{home} ML", "—" if mp is None else f"{mp:.1%}")
    fav, by = (home, sim["proj_spread"]) if sim["proj_spread"] > 0 else (away, -sim["proj_spread"])
    m3.metric("Projected spread", f"{fav} -{by:.1f}",
              delta=None if p.get("home_spread") is None else f"book: {home} {p['home_spread']:+g}", delta_color="off", delta_arrow="off")
    m4.metric("Projected total", f"{sim['proj_total']:.1f}",
              delta=None if p.get("line_total") is None else f"book: {p['line_total']:g}", delta_color="off", delta_arrow="off")
    st.caption(f"Proj: {away} **{sim['proj_away_score']:.1f}** — {home} **{sim['proj_home_score']:.1f}** · "
               f"{sim['n_sims']:,} simulated games")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric(f"{away} likely range", GS.range_text(*sim["away_range"], league), help=f"8 of 10 simulated games: {noun}")
    r2.metric(f"{home} likely range", GS.range_text(*sim["home_range"], league), help=f"8 of 10 simulated games: {noun}")
    r3.metric("Total likely range", GS.range_text(*sim["total_range"], league), help="8 of 10 simulated games")
    if sim["overtime"] is not None:
        r4.metric("Goes to overtime", f"{sim['overtime']:.0%}")
    else:
        r4.metric(f"Decided by {GS.CLOSE[sim['family']]} or fewer", f"{sim['close']:.0%}")
    b1, b2 = st.columns(2)
    if sim["overtime"] is not None:
        b1.metric("One-goal game (overtime included)", f"{sim['close']:.0%}")
    b2.metric(f"Decided by {GS.BLOWOUT[sim['family']]}+ {noun}", f"{sim['blowout']:.0%}")
    with st.expander("How this works — and what it doesn't account for"):
        st.markdown(
            f"**Method:** the projected score, spread and total are the ratings model's (opponent-adjusted offense "
            f"and defense plus home advantage, the same numbers as the table above). {sim['n_sims']:,} games are then "
            "simulated around that projection: " + (
                "each team's goals are a count around its projected goals, and a tie after regulation goes to "
                "overtime, decided 50/50." if sim["family"] == "hockey" else
                "the two scores are drawn together so that margins and totals spread as widely as they do in real "
                "games in this league.") +
            "\n\n**The win chance** is the model's own, the same one the table uses. The simulation adds the ranges: "
            "how wide the likely finishes are around the projection.\n\n"
            "**What it does not account for:** injuries, rest, lineup news, or the book's price. It is not a pick: "
            "no game-line rule in this league has beaten the books in long-run testing unless the table above tags one.")


def _rules_text(rules) -> str:
    what = []
    if rules.get("spread") is not None:
        what.append(f"a spread pick needs the model {rules['spread']:g}+ points off the line")
    if rules.get("total") is not None:
        what.append(f"a total pick needs the model {rules['total']:g}+ points off")
    if rules.get("ml") is not None:
        what.append(f"a moneyline pick needs a {rules['ml']:.0%}+ edge")
    return (("; ".join(what)).capitalize() if what else "No tested rule for this league: the model is a second opinion") + "."


def _book_spread(p):
    hs = p.get("home_spread")
    return "—" if hs is None else f"{p['home']} {float(hs):+g}"


def _book_ml(p):
    f = lambda x: "—" if x is None or x != x else f"{float(x):+.0f}"
    return "—" if p.get("best_home") is None and p.get("best_away") is None else \
        f"{p['home']} {f(p.get('best_home'))} / {f(p.get('best_away'))}"


def with_book_ticks(df: pd.DataFrame, games, after: str) -> pd.DataFrame:
    """Nov 18: the book's spread, total and moneyline, each followed by its tick boxes, placed after `after`."""
    extra = pd.DataFrame([{
        "Book spread": _book_spread(p), "✓ Home spread": False, "✓ Away spread": False,
        "Book total": "—" if p.get("line_total") is None else f"{float(p['line_total']):g}", "✓ Over": False,
        "✓ Under": False, "Book ML": _book_ml(p), "✓ Home ML": False, "✓ Away ML": False} for p in games],
        index=df.index)
    at = list(df.columns).index(after) + 1 if after in df.columns else len(df.columns)
    return pd.concat([df.iloc[:, :at], extra, df.iloc[:, at:]], axis=1)


def _previews(league, upcoming, lean_recs, no_rule, day, cust, rules=None):
    """Nov 16: upcoming games as previews with each lean's recent form -- the standard on every build (it started as
    the customer view; the owner made it the standard the same day). The owner and Discord builds keep the Use
    column, and the owner ticks rows to log exactly as before."""
    import game_previews as GP
    if no_rule:
        st.info(GP.NOTE)
    by_gap = st.toggle("Biggest disagreements first", value=False, key=f"hg_bygap_{league}",
                       help="Off: earliest games first. On: the games where the model is furthest from the book.")
    ordered = C.by_kickoff(upcoming)
    rows = GP.preview_rows(
        league, ordered, lean_recs, _tip, lambda p: _tag(league, p),
        use=None if cust else (lambda p: _use(p, league)),
        extras=None if cust else (lambda p: {
            "Long backtest": "—" if p.get("cover_est") is None else f"{p['cover_est']:.0%}",
            "Win chance: model / market": ("—" if p.get("model_p") is None else f"{p['model_p']:.0%}") + " / "
                                          + ("—" if p.get("fair_home") is None else f"{p['fair_home']:.0%}"),
            "Tracking pick": _pick(p), "Why": _why(league, p, lean_recs)}))
    top = GP.spotlight(rows)
    if top:
        st.markdown("**Worth a look first**")
        for r in top:
            why = "a tested pick" if r.get("_playable") else f"the spread is moving its way {r.get('Spread move', '')}"
            st.markdown(f"- **{r['_lean']}** ({r['Game']}, {r['Tip (ET)']}): {why}; the model is "
                        f"{r['Gap (pts)']:.1f} points from the book.")
    if by_gap:
        rows = sorted(rows, key=lambda r: -(r["Gap (pts)"] or 0))
    df = pd.DataFrame(GP.public(rows))
    if cust:
        st.dataframe(df, hide_index=True, width="stretch")
    else:
        shown = [ordered[r["_i"]] for r in rows]                # the games in the order the table lists them
        df = with_book_ticks(df, shown, after="Gap (pts)")
        st.caption("☑️ Tick any side to log it — the model's side or the other one, spread, total or moneyline. "
                   "Change the line or price in the log box to match your slip (alternate spreads too).")
        ticks = LU.tick_grid(df, list(TICK_COLS), key=f"hg_ticks_{league}", hide_index=True, width="stretch")
        items = ticked_items(shown, ticks)
        LU.panel(items, key=f"hg_panel_{league}", date_str=str(day), tag=f"{league.lower()}-games",
                 past=day < _today_et())
    st.caption(f"Form: {GP.HOT} = leans of that size won 55%+ of 20 or more graded games in the last 30 days; "
               f"{GP.EVEN} = about break-even; {GP.COLD} = losing; {GP.NEW} = fewer than 20 games. A −110 spread needs "
               "52.4% to break even. **The model says** = who the model has winning and by how much, the same for "
               "the book, and the side of the spread that difference points to; \"No bet\" = no tested rule, so the "
               "lean is information, not a pick. Gap = how far the model is from the book."
               + ("" if cust else " Long backtest = how often the model's side covered in the long-run test. "
                  + USE_LEGEND + " " + _rules_text(rules or {})))
    if not cust:
        log_panel(league, upcoming)                             # Nov 12: right under the games, not below the finals


def _why(league, p, recs):
    """Nov 16: a row the model passes on says what THIS game's gap is and how gaps that size have done (it used to be
    the same backtest sentence on every row); a real pick keeps its own reason."""
    t = _tag(league, p)
    if t.get("use") != PE.USE_PASS or p.get("edge") is None:
        return t.get("why", "")
    import pick_records as PR
    return PR.spread_why(league, p, recs, p.get("cover_est"))


def _use(p, league=""):
    return IP.tag_label(_tag(league, p)) if hasattr(IP, "tag_label") else (p.get("use") or "—")


USE_LEGEND = ("Use reads like the props pages: 🔒 Most probable = 60%+ with a tested edge behind it; 🎟️ Parlay + Single "
              "= 60%+; 🎯 Single only = 55-60%, or a tracked rule; ⚪ No edge = no tested edge for this league or gap size.")


def _show_filter(key, rows, league):
    show = st.radio("Show", ["All", PE.MOST_PROBABLE, "Playable (🎟️ / 🎯)", PE.USE_PASS], horizontal=True, key=key)
    if show == "All":
        return rows
    out = []
    for p in rows:
        t = _tag(league, p)
        if (show == PE.MOST_PROBABLE and t.get("lock")) or (show == PE.USE_PASS and t.get("use") == PE.USE_PASS) or \
                (show.startswith("Playable") and t.get("use") in (PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE)):
            out.append(p)
    return out


def _et(p):
    try:
        return pd.to_datetime(p["kickoff"]).tz_convert("America/New_York").to_pydatetime()
    except Exception:                                           # noqa: BLE001
        return None


def _today_et():
    return pd.Timestamp.now(tz="America/New_York").date()


def _ats(p):
    """Did the model's side cover the close? ✅ / ❌ / push / pending."""
    if p.get("final_home") is None or p.get("edge") is None:
        return "pending"
    line = p.get("close_line") if p.get("close_line") is not None else p.get("line")
    d = (p["final_home"] - p["final_away"]) - line
    if d == 0:
        return "push"
    return "✅" if (d > 0) == (p["edge"] > 0) else "❌"


def _tip(p):
    try:
        return pd.to_datetime(p["kickoff"]).tz_convert("America/New_York").strftime("%a %I:%M %p")
    except Exception:                                           # noqa: BLE001
        return "—"


@st.cache_data(ttl=30, show_spinner=False)
def _live_games(league: str, day):
    import live_games as LG
    try:
        return LG.games(league, day)
    except Exception:                                           # noqa: BLE001
        return []


def live_section(league: str) -> None:
    """Nov 13 (owner: lots of games in progress I can't see): the league's games in progress right now, straight
    from the live feed, with the model's live win chance when it priced the game before tip."""
    import live_games as LG
    gs = [g for g in _live_games(league, _today_et()) if g.get("state") == "in"]
    if not gs:
        return
    picks = MS.load_game_picks(league)
    rows = []
    for g in gs:
        pre = LG.pregame_for(g, picks)
        rd = None
        try:
            rd = LG.read_game(g, pre)
        except Exception:                                       # noqa: BLE001
            rd = None
        win = None if not rd else rd["read"]["win_home"]
        rows.append({"Game": f"{g['away']} @ {g['home']}", "Score": f"{int(g['away_score'])}–{int(g['home_score'])}",
                     "Clock": g.get("detail") or "", "Model: home wins": win,
                     "Projected final": "—" if not rd else
                     f"{(rd['read']['total'] - rd['read']['margin']) / 2:.0f}–"
                     f"{(rd['read']['total'] + rd['read']['margin']) / 2:.0f}"})
    st.markdown(f"##### 🔴 In progress ({len(gs)})")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Model: home wins": st.column_config.NumberColumn(format="percent")})
    st.caption("Straight from the league's live feed (refreshes every 30 seconds on reload). The live win chance needs "
               "the model's pre-game read; leagues still building a record show the score only. Full live reads, live "
               "lines and auto-refresh are on 🔴 Live Games.")


def render(league: str, search: bool = False) -> None:
    live_section(league)
    if not I.LEAGUES.get(league, {}).get("odds_key"):
        return render_fair(league)
    rules = IP.HOOPS_RULES.get(league, {})
    ev = getattr(IP, "HOOPS_EVIDENCE", {}).get(league) or EVIDENCE.get(league)
    if not _commercial():
        st.warning("Tracking only — not recommendations yet." + (f" {ev}" if ev else ""))
    elif any(rules.get(k) is not None for k in ("spread", "total", "ml")):
        st.warning("Tracking only: this league's record is not proven yet.")
    picks = MS.load_game_picks(league)
    now = datetime.now(timezone.utc).isoformat()
    done = [p for p in picks if p.get("result")]
    title = I.LEAGUES[league]["title"]
    c1, c2, c3 = st.columns([1, 1, 2])
    day = c1.date_input("Slate date", _today_et(), key=f"hg_date_{league}")
    # Nov 16: a weekly league (the NFL) lists the week from the picked date by default -- a single day is empty most days
    week = league in getattr(sports, "WEEKLY_SLATE_SPORTS", ()) and st.radio(
        "Games shown", ["This week", "Selected date"], horizontal=True, key=f"hg_scope_{league}") == "This week"
    last = day + timedelta(days=6) if week else day
    on_day = [p for p in picks if _et(p) is not None and day <= _et(p).date() <= last]
    slots = sorted({sports.slot_of(_et(p)) for p in on_day}, key=lambda x: sports.SLOT_ORDER.get(x, 9))
    slot = c2.selectbox("Time slot", ["All slate"] + slots, key=f"hg_slot_{league}")
    if slot != "All slate":
        on_day = [p for p in on_day if sports.slot_of(_et(p)) == slot]
    _teams = C.team_names(on_day)                               # every team in this slate / slot, before the Game filter
    on_day = C.game_select(on_day, key=f"hg_game_{league}", container=c3)       # Nov 7: Game filter, tip order
    if _teams:                                                  # Nov 16: a dropdown on every league (was a text box, some leagues)
        on_day = C.team_select(on_day, key=f"hg_team_{league}", options=_teams)
    upcoming = [p for p in on_day if str(p.get("kickoff")) > now and p.get("result") is None]
    finished = [p for p in on_day if p not in upcoming]
    if search and on_day:
        if not _commercial() and st.toggle("Only games with a tracking pick", key=f"hg_only_{league}"):
            upcoming = [p for p in upcoming if _pick(p) != "—"]
            finished = [p for p in finished if _pick(p) != "—"]
    # Nov 16: how the model's spread leans have actually done by size of gap (last 30 days) -- the evidence behind
    # each row's Why, and the reason a page of passes isn't 22 copies of one sentence
    import pick_records as PR
    try:
        lean_recs = PR.lean_records(league, recs=picks)
    except Exception:                                           # noqa: BLE001
        lean_recs = {}
    cust = _commercial()
    no_rule = not any(rules.get(k) is not None for k in ("spread", "total", "ml"))
    with st.expander("How the model's spread leans have done by size of gap (last 30 days)"):
        st.table(pd.DataFrame([{**r, "Hit rate": "—" if r["Hit rate"] is None else f"{r['Hit rate']:.0%}"}
                               for r in PR.band_table(league, lean_recs)]).set_index("Gap size"))
        st.caption("A −110 spread needs 52.4% to break even. Fewer than 20 graded games is too few to judge.")
    if upcoming and not cust:
        upcoming = _show_filter(f"hg_use_{league}", upcoming, league)
    st.markdown(f"##### Upcoming ({len(upcoming)})")
    if upcoming:
        _previews(league, upcoming, lean_recs, no_rule, day, cust, rules)
        try:
            _one_game(league, upcoming, day)
        except Exception as exc:                                # noqa: BLE001 -- never takes the slate down with it
            st.caption(f"The one-game simulation is unavailable right now ({type(exc).__name__}).")
    else:
        st.info(f"No upcoming {title} games for {day:%a %b %d}" + (f" ({slot})" if slot != "All slate" else "")
                + ". The capture runs every 3 hours; games appear once the books post lines.")
    if finished:
        st.markdown(f"##### Started or final ({len(finished)})")
        st.dataframe(pd.DataFrame([{
            "Tip (ET)": _tip(p), "Game": f"{p['away']} @ {p['home']}",
            "Line (close)": f"{p['home']} {(-(p.get('close_line') if p.get('close_line') is not None else p.get('line') or 0)):+g}",
            "Use": _use(p, league), "Model likes": _likes(p),
            "Final": "—" if p.get("final_home") is None else f"{p['away']} {p['final_away']:g} – {p['home']} {p['final_home']:g}",
            "Model's side": _ats(p), "Tracking pick": _pick(p)} for p in C.by_kickoff(finished)]),
            hide_index=True, width="stretch")
    st.markdown("##### Tracking record")
    st.caption(honesty_line(done, league))                      # Nov 12: the check that caught tennis, every league
    tagged = [] if cust else [p for p in done if p.get("use")]     # Nov 16: the by-Use table is the owner's view
    if tagged:
        rows = []
        for label, keep in ((PE.MOST_PROBABLE, lambda p: p.get("lock")), (PE.USE_SINGLE, lambda p: p.get("use") == PE.USE_SINGLE),
                            (PE.USE_PASS, lambda p: p.get("use") == PE.USE_PASS)):
            res = []
            for p in tagged:
                if not keep(p) or p.get("final_home") is None or p.get("home_spread") is None:
                    continue
                line = p.get("close_line") if p.get("close_line") is not None else p.get("line")
                d = (p["final_home"] - p["final_away"]) - line
                if d != 0 and p.get("edge"):
                    res.append((d > 0) == (p["edge"] > 0))
            if res:
                rows.append({"Use": label, "Record (model's side ATS)": f"{sum(res)}-{len(res) - sum(res)}",
                             "Hit": f"{sum(res) / len(res):.0%}"})
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    rec = IP.record(done)
    if not rec:
        st.caption("Nothing graded yet.")
    else:
        names = {"ml": "Moneyline", "spread": "Spread (vs the close)", "total": "Total"}
        st.dataframe(pd.DataFrame([{"Market": names.get(k, k), "Record": f"{r['w']}-{r['l']}" + (f"-{r['p']}" if r["p"] else ""),
                                    "Profit (units)": f"{r['units']:+.1f}", "Per $1": "—" if r["roi"] is None else f"{r['roi']:+.1%}"}
                                   for k, r in rec.items()]), hide_index=True, width="stretch")


def _side_options(p):
    """[(label, market, side, line, price, model_prob)] for every bet this game offers."""
    out = []
    hs = p.get("home_spread")
    if hs is not None:
        sp = p.get("spread_price") or -110
        out.append((f"{p['home']} {hs:+g} (spread)", "Spread", "home", hs, sp, None))
        out.append((f"{p['away']} {-hs:+g} (spread)", "Spread", "away", -hs, sp, None))
    if p.get("line_total") is not None:
        out.append((f"Over {p['line_total']:g}", "Total", "over", p["line_total"], p.get("over_price") or -110, None))
        out.append((f"Under {p['line_total']:g}", "Total", "under", p["line_total"], p.get("under_price") or -110, None))
    if p.get("best_home") is not None:
        out.append((f"{p['home']} moneyline", "Moneyline", "home", None, p["best_home"], p.get("model_p")))
    if p.get("best_away") is not None:
        mp = p.get("model_p")
        out.append((f"{p['away']} moneyline", "Moneyline", "away", None, p["best_away"], None if mp is None else 1 - mp))
    return out


def _default_choice(p, opts):
    """The tracking pick, if there is one, so one tap logs what the model flagged."""
    for i, (_, mk, side, *_rest) in enumerate(opts):
        if (mk == "Spread" and p.get("pick") == side) or (mk == "Total" and p.get("total_pick") == side) or \
                (mk == "Moneyline" and p.get("ml_pick") == side):
            return i
    return 0


TICK_KINDS = {"Spread": "Spread", "Moneyline": "Moneyline", "Total": "Total"}


def _half(x: float) -> float:
    """A fair line rounded to the nearest half point, the way books post them."""
    return float(round(x * 2) / 2)


def side_item(p, market: str, side: str, line=None, price=None):
    """Nov 18: any side of any market on a game as a log_ui item -- not only the model's side. The owner sometimes takes
    the other team, or a DraftKings alt spread at a better price. `line` is from that side's point of view (Spread) or
    the total; left out, it is the book's line, or the model's fair line rounded to the half point when the league has
    no odds feed. The price defaults to the book's (None = type it in the log box)."""
    import math
    team = lambda s: p["home"] if s == "home" else p["away"]
    if market == "Spread":
        if line is None:
            if p.get("home_spread") is not None:
                line = float(p["home_spread"]) if side == "home" else -float(p["home_spread"])
                price = price if price is not None else (p.get("spread_price") or -110)
            elif p.get("model_margin") is not None:
                line = _half(-p["model_margin"] if side == "home" else p["model_margin"])
            else:
                return None
        label = f"{team(side)} {line:+g}"
    elif market == "Total":
        if line is None:
            if p.get("line_total") is not None:
                line = float(p["line_total"])
                price = price if price is not None else ((p.get("over_price") if side == "over" else
                                                         p.get("under_price")) or -110)
            elif p.get("model_total") is not None:
                line = _half(p["model_total"])
            else:
                return None
        label = f"{side.title()} {line:g} ({p['away']} @ {p['home']})"
    elif market == "Moneyline":
        if p.get("model_p") is None and p.get("best_home") is None:
            return None
        line = None
        if price is None:
            price = p.get("best_home") if side == "home" else p.get("best_away")
        label = f"{team(side)} moneyline"
    else:
        return None
    try:
        ch = IP.fair_chance(p, market, side, line)
    except Exception:                                           # noqa: BLE001
        ch = None
    if price is not None and (isinstance(price, float) and math.isnan(price)):
        price = None
    # Nov 17: carry the page's Use tag. A ⚪ No edge game's chance is the model's own, untested number -- the Coach graded
    # two such spreads "A" (Hofstra +11.5, Rutgers +16.5) while the page said Pass and both lines were moving away.
    try:
        use = (_tag(p.get("sport"), p) or {}).get("use")
    except Exception:                                           # noqa: BLE001
        use = None
    passed = bool(use) and ("No edge" in str(use) or "Pass" in str(use))
    return {"sport": p.get("sport"), "pick": label, "price": price, "game": f"{p['away']} @ {p['home']}",
            "chance": ch, "_rec": p, "bet_market": market, "bet_side": side, "bet_line": line, "use": use,
            "best_tested": ch is not None and not passed, "best_chance": None if ch is None else round(ch, 4)}


def tick_item(p, kind: str):
    """A ticked game as a log_ui item: the model's side of the chosen market at the book's price (editable)."""
    if kind == "Spread" and p.get("home_spread") is not None and p.get("edge") is not None:
        return side_item(p, "Spread", "home" if p["edge"] >= 0 else "away")
    if kind == "Moneyline" and p.get("model_p") is not None:
        return side_item(p, "Moneyline", "home" if p["model_p"] >= 0.5 else "away")
    if kind == "Total" and p.get("line_total") is not None and p.get("model_total") is not None:
        return side_item(p, "Total", "over" if p["model_total"] > p["line_total"] else "under")
    return None


# Nov 18: a tick box for every side of every market, each placed next to the column it bets on
TICK_COLS = {"✓ Home spread": ("Spread", "home"), "✓ Away spread": ("Spread", "away"), "✓ Over": ("Total", "over"),
             "✓ Under": ("Total", "under"), "✓ Home ML": ("Moneyline", "home"), "✓ Away ML": ("Moneyline", "away")}


def ticked_items(games, ticks):
    """[(row, tick column)] from LU.tick_grid -> log_ui items, in table order."""
    out = []
    for i, col in ticks:
        if 0 <= i < len(games) and col in TICK_COLS:
            it = side_item(games[i], *TICK_COLS[col])
            if it:
                out.append(it)
    return out


def honesty_line(done, league: str = "") -> str:
    """How often the model's favorite won against the chance it gave (Nov 12: the check that showed the tennis model
    overconfident), and whether the automatic correction is on for this league."""
    import tennis_calibration as TC
    rs = TC.rows(done)
    if not rs:
        return "Honesty check: no graded games yet."
    won = sum((r["y"] == 1) == (r["p"] >= 0.5) for r in rs) / len(rs)
    said = sum(max(r["p"], 1 - r["p"]) for r in rs) / len(rs)
    k = TC.current_k(sport=league) if league else 1.0
    fix = (f" Automatic correction on (×{k:.2f})." if abs(k - 1) > 1e-9 else
           f" The automatic correction checks every morning; it needs {TC.MIN_N}+ graded games over {TC.MIN_DAYS}+ days "
           "and must hold up on days it didn't see.")
    return (f"Honesty check: over {len(rs)} graded games the model's favorite won **{won:.0%}** (it said {said:.0%})."
            + fix)


def value_at_price(p, market: str, side: str, line, odds) -> str:
    """The model's chance for the bet being logged and its expected value at the typed price."""
    try:
        ch = IP.fair_chance(p, market, side, line)
    except Exception:                                           # noqa: BLE001
        ch = None
    if ch is None or abs(odds) < 100:
        return ""
    dec = 1 + (odds / 100 if odds > 0 else 100 / -odds)
    ev = ch * dec - 1
    return (f"Model chance **{ch:.0%}** · at {odds:+d}: **{ev:+.1%}** expected value"
            + (" — the price beats the model's fair line" if ev > 0 else " — the price is worse than the model's fair line"))


def log_panel(league: str, games) -> None:
    """Log a bet on any listed game straight to the Bet Log (it settles itself once the game is graded here)."""
    import betlog as B
    if not C.is_owner():                                        # Nov 14: the public build has no Bet Log
        return
    with st.expander("📒 Log one bet with your own line (any side, spread, total or moneyline)"):
        flagged = [p for p in games if _pick(p) != "—"]
        pool = sorted(flagged or games, key=lambda x: x["kickoff"]) if st.toggle(
            "Only games with a tracking pick", value=bool(flagged), key=f"hg_log_only_{league}") else \
            sorted(games, key=lambda x: x["kickoff"])
        if not pool:
            st.caption("No games to log.")
            return
        labels = {f"{p['away']} @ {p['home']} · {_tip(p)}": p for p in pool}
        p = labels[st.selectbox("Game", list(labels), key=f"hg_log_game_{league}")]
        opts = _side_options(p)
        if not opts:
            st.caption("No lines for this game yet.")
            return
        i = st.selectbox("Bet", range(len(opts)), index=_default_choice(p, opts), format_func=lambda k: opts[k][0],
                         key=f"hg_log_bet_{league}_{p['game_id']}")
        label, mk, side, line, price, mprob = opts[i]
        c1, c2, c3 = st.columns(3)
        line_in = c1.number_input("Line", value=float(line), step=0.5, key=f"hg_log_line_{league}_{p['game_id']}_{i}") \
            if line is not None else None
        odds = c2.number_input("Your price (American)", value=int(round(float(price))), step=5,
                               key=f"hg_log_odds_{league}_{p['game_id']}_{i}")
        stake = c3.number_input("Stake ($)", min_value=0.0, value=1.0, step=1.0, key=f"hg_log_stake_{league}")
        st.markdown(value_at_price(p, mk, side, line_in, odds))   # Nov 12: like Tennis Lab's price check
        real = st.toggle("Real money (off = tracking only)", value=True, key=f"hg_log_real_{league}")
        st.caption("Adjust the line and price to what your book shows before logging. It settles automatically once "
                   "the game is graded.")
        if st.button("Log it", key=f"hg_log_go_{league}", type="primary"):
            if abs(odds) < 100:
                st.error("Enter a price of +100 or more, or -100 or less.")
                return
            f = IP.bet_fields(p, mk, side, line_in, odds, stake, real, mprob)
            try:
                bid = B.add_bet(**f)
                what = f"{f['side']} {mk.lower()}" + ("" if line_in is None else
                                                       f" {line_in:g}" if mk == "Total" else f" {line_in:+g}")
                st.success(f"Logged #{bid}: {what} at {odds:+d}, ${stake:,.2f} {'real' if real else 'tracking'}.")
            except Exception as exc:                            # noqa: BLE001
                st.error(f"Couldn't log it: {exc}")


def _fair_american(p: Optional[float]) -> str:
    if p is None or p <= 0 or p >= 1:
        return "—"
    return f"{-100 * p / (1 - p):+.0f}" if p >= 0.5 else f"{100 * (1 - p) / p:+.0f}"


def _fav(p):
    return (p["home"], p["model_p"]) if p["model_p"] >= 0.5 else (p["away"], 1 - p["model_p"])


def render_fair(league: str) -> None:
    """A league the odds feed doesn't carry (EuroCup): the model's fair spread, total and moneyline for every scheduled
    game, a box to check the sportsbook's price against it, and logging. No picks -- there is no line history to test
    against, so the record kept here is how close the model's margins come and how often its favorite wins."""
    import betlog as B
    title = I.LEAGUES[league]["title"]
    st.info(f"{title} isn't in the odds feed, so there are no book lines here. Each game shows the model's FAIR prices; "
            "type the sportsbook's price below to see whether it beats them. Information only — the model has no tested "
            "edge in this league yet; the accuracy record below builds as games finish.")
    picks = MS.load_game_picks(league)
    now = datetime.now(timezone.utc).isoformat()
    c1, c2 = st.columns(2)
    day = c1.date_input("Slate date", _today_et(), key=f"hg_date_{league}")
    on_day = [p for p in picks if _et(p) is not None and _et(p).date() == day]
    slots = sorted({sports.slot_of(_et(p)) for p in on_day}, key=lambda x: sports.SLOT_ORDER.get(x, 9))
    slot = c2.selectbox("Time slot", ["All slate"] + slots, key=f"hg_slot_{league}")
    if slot != "All slate":
        on_day = [p for p in on_day if sports.slot_of(_et(p)) == slot]
    _teams = C.team_names(on_day)
    on_day = C.game_select(on_day, key=f"hg_game_{league}")                     # Nov 7: Game filter, tip order
    if _teams:
        on_day = C.team_select(on_day, key=f"hg_team_{league}", options=_teams)  # Nov 16: Find a team, every Game Lab
    upcoming = C.by_kickoff([p for p in on_day if str(p.get("kickoff")) > now and p.get("result") is None])
    finished = C.by_kickoff([p for p in on_day if p not in upcoming])
    if league in getattr(I, "GENIUS_COMPS", {}):
        try:
            stored = len(MS.load_results(league))
        except Exception:                                       # noqa: BLE001
            stored = 0
        need = I.LEAGUES[league].get("min_decay_games", 30)
        if stored < need:
            st.warning(f"📥 Building {title}: {stored} of {need} games recorded. This league's stats feed shows only the "
                       "current round, so results are being recorded from Nov 5 on; fair lines appear once there are "
                       "enough games to rate the teams.")
    st.markdown(f"##### Upcoming ({len(upcoming)})")
    if not upcoming:
        st.caption(f"No upcoming {title} games for {day:%a %b %d}" + (f" ({slot})" if slot != "All slate" else "") + ".")
    else:
        ticks = LU.tick_grid(pd.DataFrame([{
            "Tip (ET)": _tip(p), "Game": f"{p['away']} @ {p['home']}",
            "Model's pick": _fav(p)[0] + f" {_fav(p)[1]:.0%}",
            "Use": IP.tag_label(IP.chance_use(_fav(p)[1], None, trusted=False)),
            "Fair spread": f"{p['home']} {-p['model_margin']:+.1f}", "✓ Home spread": False, "✓ Away spread": False,
            "Fair total": f"{p['model_total']:.1f}", "✓ Over": False, "✓ Under": False,
            "Win chance": f"{p['home']} {p['model_p']:.0%}", "✓ Home ML": False, "✓ Away ML": False,
            "Fair ML": f"{_fair_american(p['model_p'])} / {_fair_american(1 - p['model_p'])}"} for p in upcoming]),
            list(TICK_COLS), key=f"hf_ticks_{league}", hide_index=True, width="stretch")
        st.caption("☑️ Tick any side to log it — the model's pick or the other team, either side of the fair spread, "
                   "Over or Under. Spreads and totals start at the fair line rounded to the half point: change the Line "
                   "and type the Price in the log box to match your slip (alternate spreads too).")
        items = ticked_items(upcoming, ticks)
        LU.panel(items, key=f"hf_panel_{league}", date_str=str(day), tag=f"{league.lower()}-games",
                 past=day < _today_et())
        st.caption("Model's pick = the team the model favors to win and its chance. Use reads like the props pages (🎯 "
                   "Single only at 55%+, ⚪ No edge below); \"(-150 or better)\" = the moneyline price needed for +3% value. No 🔒 "
                   "here: the model has no tested edge in this league yet.")
        with st.expander("💲 Check a sportsbook price · 📒 log it"):
            labels = {f"{p['away']} @ {p['home']} · {_tip(p)}": p for p in upcoming}
            p = labels[st.selectbox("Game", list(labels), key=f"hf_game_{league}")]
            opts = [(f"{p['home']} spread", "Spread", "home"), (f"{p['away']} spread", "Spread", "away"),
                    ("Over", "Total", "over"), ("Under", "Total", "under"),
                    (f"{p['home']} moneyline", "Moneyline", "home"), (f"{p['away']} moneyline", "Moneyline", "away")]
            i = st.selectbox("Bet", range(len(opts)), format_func=lambda k: opts[k][0], key=f"hf_bet_{league}")
            label, mk, side = opts[i]
            k1, k2, k3 = st.columns(3)
            default_line = (-p["model_margin"] if side == "home" else p["model_margin"]) if mk == "Spread" else p["model_total"]
            line = None if mk == "Moneyline" else k1.number_input("Book's line", value=float(round(default_line * 2) / 2),
                                                                  step=0.5, key=f"hf_line_{league}_{i}")
            odds = k2.number_input("Book's price", value=-110, step=5, key=f"hf_odds_{league}")
            stake = k3.number_input("Stake ($)", min_value=0.0, value=1.0, step=1.0, key=f"hf_stake_{league}")
            ch = IP.fair_chance(p, mk, side, line)
            if ch is not None and abs(odds) >= 100:
                dec = 1 + (odds / 100 if odds > 0 else 100 / -odds)
                ev_ = ch * dec - 1
                st.markdown(f"Model chance **{ch:.0%}** · fair **{_fair_american(ch)}** · at {odds:+d}: **{ev_:+.1%}** → **"
                            + IP.tag_label(dict(IP.chance_use(ch, odds, trusted=False), priced=True)) + "**")
                real = st.toggle("Real money", value=True, key=f"hf_real_{league}") if C.is_owner() else False
                if C.is_owner() and st.button("📒 Log it", key=f"hf_log_{league}", type="primary"):
                    f = IP.bet_fields(p, mk, side, line, odds, stake, real, round(ch, 4))
                    try:
                        st.success(f"Logged #{B.add_bet(**f)}: {label}" + ("" if line is None else f" {line:+g}" if mk == "Spread"
                                                                             else f" {line:g}")
                                   + f" at {odds:+d}. It settles once the result is in.")
                    except Exception as exc:                    # noqa: BLE001
                        st.error(f"Couldn't log it: {exc}")
    if finished:
        st.markdown(f"##### Started or final ({len(finished)})")
        st.dataframe(pd.DataFrame([{
            "Tip (ET)": _tip(p), "Game": f"{p['away']} @ {p['home']}", "Fair spread": f"{p['home']} {-p['model_margin']:+.1f}",
            "Final": "—" if p.get("final_home") is None else f"{p['away']} {p['final_away']:g} – {p['home']} {p['final_home']:g}",
            "Model's favorite": "pending" if p.get("final_home") is None else
            ("✅" if (p["final_home"] > p["final_away"]) == (p["model_p"] >= 0.5) else "❌")} for p in finished]),
            hide_index=True, width="stretch")
    done = [p for p in picks if p.get("final_home") is not None and p.get("model_margin") is not None]
    st.markdown("##### Accuracy so far")
    if not done:
        st.caption("Nothing graded yet.")
    else:
        mae = sum(abs((p["final_home"] - p["final_away"]) - p["model_margin"]) for p in done) / len(done)
        fav = sum(1 for p in done if (p["final_home"] > p["final_away"]) == (p["model_p"] >= 0.5)) / len(done)
        said = sum(max(p["model_p"], 1 - p["model_p"]) for p in done) / len(done)
        st.markdown(f"{len(done)} games · the model's favorite won **{fav:.0%}** (it said {said:.0%}) · its margin missed by "
                    f"**{mae:.1f}** points on average.")
