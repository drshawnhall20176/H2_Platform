"""
hoops_games_page.py — the game-lines view shared by International Hoops (EuroLeague / NBL) and the college
basketball Game Lab (Nov 3): upcoming games with the model's margin, total and win chance against the books, the
tracking picks where the backtested rules allow one, and the graded record. Data: intl_picks (model_store.game_picks).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import intl_hoops as I
import intl_picks as IP
import model_store as MS
import props_engine as PE

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


def _use(p):
    u = p.get("use") or "—"
    return f"{PE.MOST_PROBABLE} · {u}" if p.get("lock") else u


def _tip(p):
    try:
        return pd.to_datetime(p["kickoff"]).tz_convert("America/New_York").strftime("%a %I:%M %p")
    except Exception:                                           # noqa: BLE001
        return "—"


def render(league: str, search: bool = False) -> None:
    rules = IP.HOOPS_RULES.get(league, {})
    ev = getattr(IP, "HOOPS_EVIDENCE", {}).get(league) or EVIDENCE.get(league)
    st.warning("Tracking only — not recommendations yet." + (f" {ev}" if ev else ""))
    picks = MS.load_game_picks(league)
    now = datetime.now(timezone.utc).isoformat()
    upcoming = [p for p in picks if str(p.get("kickoff")) > now and p.get("result") is None]
    done = [p for p in picks if p.get("result")]
    title = I.LEAGUES[league]["title"]
    if search and upcoming:
        q = st.text_input("Find a team", key=f"hg_q_{league}").strip()
        if q:
            upcoming = [p for p in upcoming if q.lower() in f"{p['home']} {p['away']}".lower()]
        if st.toggle("Only games with a tracking pick", key=f"hg_only_{league}"):
            upcoming = [p for p in upcoming if _pick(p) != "—"]
    st.markdown(f"##### Upcoming ({len(upcoming)})")
    if not upcoming:
        st.info(f"No upcoming {title} games captured yet. The capture runs every 3 hours.")
    else:
        st.dataframe(pd.DataFrame([{
            "Tip (ET)": _tip(p),
            "Game": f"{p['away']} @ {p['home']}",
            "Line": f"{p['home']} {p['home_spread']:+g}",
            "Model likes": _likes(p),
            "Gap (pts)": f"{abs(p['edge']):.1f}",
            "Est. cover": "—" if p.get("cover_est") is None else f"{p['cover_est']:.0%}",
            "Use": _use(p),
            "Total: model / line": f"{p.get('model_total')} / {p.get('line_total') or '—'}",
            "Win chance: model / market": f"{p['model_p']:.0%} / " + ("—" if p.get("fair_home") is None else f"{p['fair_home']:.0%}"),
            "Tracking pick": _pick(p)} for p in sorted(upcoming, key=lambda x: (-(abs(x.get("edge") or 0)), x["kickoff"]))]),
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
                   "how often that size of gap covered in the backtest; Use follows the props pages (🔒 / 🎟️ Parlay + "
                   "Single at 60%+, 🎯 Single at 55-60%, ⛔ Pass below). "
                   + ("; ".join(what) if what else "no picks for this league — the model is shown for reference") + ".")
    if upcoming:
        log_panel(league, upcoming)
    st.markdown("##### Tracking record")
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


def log_panel(league: str, games) -> None:
    """Log a bet on any listed game straight to the Bet Log (it settles itself once the game is graded here)."""
    import betlog as B
    with st.expander("📒 Log a bet"):
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
