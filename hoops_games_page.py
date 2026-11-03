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
            "Model margin": f"{p['home']} {p['model_margin']:+.1f}",
            "Line": f"{p['home']} {p['home_spread']:+g}",
            "Edge (pts)": f"{p['edge']:+.1f}",
            "Total: model / line": f"{p.get('model_total')} / {p.get('line_total') or '—'}",
            "Win chance: model / market": f"{p['model_p']:.0%} / " + ("—" if p.get("fair_home") is None else f"{p['fair_home']:.0%}"),
            "Tracking pick": _pick(p)} for p in sorted(upcoming, key=lambda x: x["kickoff"])]),
            hide_index=True, width="stretch")
        what = []
        if rules.get("spread") is not None:
            what.append(f"a spread pick needs the model {rules['spread']:g}+ points off the line")
        if rules.get("total") is not None:
            what.append(f"a total pick needs the model {rules['total']:g}+ points off")
        if rules.get("ml") is not None:
            what.append(f"a moneyline pick needs a {rules['ml']:.0%}+ edge")
        st.caption("Edge = the model's home margin minus the margin the spread implies; "
                   + ("; ".join(what) if what else "no picks for this league — the model is shown for reference") + ".")
    st.markdown("##### Tracking record")
    rec = IP.record(done)
    if not rec:
        st.caption("Nothing graded yet.")
    else:
        names = {"ml": "Moneyline", "spread": "Spread (vs the close)", "total": "Total"}
        st.dataframe(pd.DataFrame([{"Market": names.get(k, k), "Record": f"{r['w']}-{r['l']}" + (f"-{r['p']}" if r["p"] else ""),
                                    "Profit (units)": f"{r['units']:+.1f}", "Per $1": "—" if r["roi"] is None else f"{r['roi']:+.1%}"}
                                   for k, r in rec.items()]), hide_index=True, width="stretch")
