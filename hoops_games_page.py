"""
hoops_games_page.py — the game-lines view shared by International Hoops (EuroLeague / NBL) and the college
basketball Game Lab (Nov 3): upcoming games with the model's margin, total and win chance against the books, the
tracking picks where the backtested rules allow one, and the graded record. Data: intl_picks (model_store.game_picks).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import streamlit as st

import components as C

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


def _use(p, league=""):
    return IP.tag_label(_tag(league, p)) if hasattr(IP, "tag_label") else (p.get("use") or "—")


USE_LEGEND = ("Use reads like the props pages: 🔒 Most probable = 60%+ with a tested edge behind it; 🎟️ Parlay + Single "
              "= 60%+; 🎯 Single only = 55-60%, or a tracked rule; ⛔ Pass = no tested edge for this league or gap size.")


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


def render(league: str, search: bool = False) -> None:
    if not I.LEAGUES.get(league, {}).get("odds_key"):
        return render_fair(league)
    rules = IP.HOOPS_RULES.get(league, {})
    ev = getattr(IP, "HOOPS_EVIDENCE", {}).get(league) or EVIDENCE.get(league)
    st.warning("Tracking only — not recommendations yet." + (f" {ev}" if ev else ""))
    picks = MS.load_game_picks(league)
    now = datetime.now(timezone.utc).isoformat()
    done = [p for p in picks if p.get("result")]
    title = I.LEAGUES[league]["title"]
    c1, c2, c3 = st.columns([1, 1, 2])
    day = c1.date_input("Slate date", _today_et(), key=f"hg_date_{league}")
    on_day = [p for p in picks if _et(p) is not None and _et(p).date() == day]
    slots = sorted({sports.slot_of(_et(p)) for p in on_day}, key=lambda x: sports.SLOT_ORDER.get(x, 9))
    slot = c2.selectbox("Time slot", ["All slate"] + slots, key=f"hg_slot_{league}")
    if slot != "All slate":
        on_day = [p for p in on_day if sports.slot_of(_et(p)) == slot]
    on_day = C.game_select(on_day, key=f"hg_game_{league}", container=c3)       # Nov 7: Game filter, tip order
    upcoming = [p for p in on_day if str(p.get("kickoff")) > now and p.get("result") is None]
    finished = [p for p in on_day if p not in upcoming]
    if search and on_day:
        q = st.text_input("Find a team", key=f"hg_q_{league}").strip()
        if q:
            upcoming = [p for p in upcoming if q.lower() in f"{p['home']} {p['away']}".lower()]
            finished = [p for p in finished if q.lower() in f"{p['home']} {p['away']}".lower()]
        if st.toggle("Only games with a tracking pick", key=f"hg_only_{league}"):
            upcoming = [p for p in upcoming if _pick(p) != "—"]
            finished = [p for p in finished if _pick(p) != "—"]
    if upcoming:
        upcoming = _show_filter(f"hg_use_{league}", upcoming, league)
    st.markdown(f"##### Upcoming ({len(upcoming)})")
    if not upcoming:
        st.info(f"No upcoming {title} games for {day:%a %b %d}" + (f" ({slot})" if slot != "All slate" else "")
                + ". The capture runs every 3 hours; games appear once the books post lines.")
    else:
        st.dataframe(pd.DataFrame([{
            "Tip (ET)": _tip(p),
            "Game": f"{p['away']} @ {p['home']}",
            "Use": _use(p, league),
            "Model likes": _likes(p),
            "Why": _tag(league, p).get("why", ""),
            "Line": f"{p['home']} {p['home_spread']:+g}",
            "Gap (pts)": f"{abs(p['edge']):.1f}",
            "Est. cover": "—" if p.get("cover_est") is None else f"{p['cover_est']:.0%}",
            "Total: model / line": f"{p.get('model_total')} / {p.get('line_total') or '—'}",
            "Win chance: model / market": f"{p['model_p']:.0%} / " + ("—" if p.get("fair_home") is None else f"{p['fair_home']:.0%}"),
            "Tracking pick": _pick(p)} for p in C.by_kickoff(upcoming)]),          # Nov 7: earliest tip first
            hide_index=True, width="stretch")
        what = []
        if rules.get("spread") is not None:
            what.append(f"a spread pick needs the model {rules['spread']:g}+ points off the line")
        if rules.get("total") is not None:
            what.append(f"a total pick needs the model {rules['total']:g}+ points off")
        if rules.get("ml") is not None:
            what.append(f"a moneyline pick needs a {rules['ml']:.0%}+ edge")
        st.caption("Model likes = the side the model would take against the spread, at the book's number; Gap = how many "
                   "points the model's margin is from the spread (the size, not the sign, is what matters); Est. cover = "
                   "how often that size of gap covered in the backtest. " + USE_LEGEND + " "
                   + ("; ".join(what) if what else "no picks for this league — the model is shown for reference") + ".")
        log_panel(league, upcoming)                             # Nov 12: right under the games, not below the finals
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
    tagged = [p for p in done if p.get("use")]
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
    with st.expander("📒 Log a bet on any game above", expanded=True):
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
    on_day = C.game_select(on_day, key=f"hg_game_{league}")                     # Nov 7: Game filter, tip order
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
        st.dataframe(pd.DataFrame([{
            "Tip (ET)": _tip(p), "Game": f"{p['away']} @ {p['home']}",
            "Model's pick": _fav(p)[0] + f" {_fav(p)[1]:.0%}",
            "Use": IP.tag_label(IP.chance_use(_fav(p)[1], None, trusted=False)),
            "Fair spread": f"{p['home']} {-p['model_margin']:+.1f}", "Fair total": f"{p['model_total']:.1f}",
            "Win chance": f"{p['home']} {p['model_p']:.0%}",
            "Fair ML": f"{_fair_american(p['model_p'])} / {_fair_american(1 - p['model_p'])}"} for p in upcoming]),
            hide_index=True, width="stretch")
        st.caption("Model's pick = the team the model favors to win and its chance. Use reads like the props pages (🎯 "
                   "Single only at 55%+, ⛔ Pass below); \"(-150 or better)\" = the moneyline price needed for +3% value. No 🔒 "
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
                real = st.toggle("Real money", value=True, key=f"hf_real_{league}")
                if st.button("📒 Log it", key=f"hf_log_{league}", type="primary"):
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
