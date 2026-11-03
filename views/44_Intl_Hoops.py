"""
International Hoops — EuroLeague and Australia's NBL game model (Nov 3). TRACKING ONLY until the record proves it.
Owner only.

Every upcoming game the books price, saved every 3 hours by the capture-intl workflow: the ratings model's margin and
total against the consensus spread and total, its win chance against the moneyline, and tracking picks where it
clears its bar. Graded from the leagues' results. Model: intl_hoops.py; capture / grading / record: intl_picks.py.
"""
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import components as C
import intl_hoops as I
import intl_picks as IP
import model_store as MS

C.base_css()
C.page_header("🌍", "International Hoops",
              "EuroLeague and NBL: opponent-adjusted ratings against the spread, total and moneyline. Tracking only "
              "until the record proves it.")
st.warning("Tracking only — not recommendations yet. Backtest vs real lines: EuroLeague spreads with the model 4+ "
           "points off went 119-98 (54.8%) over 2022-26, 6+ points 59-39 (60%); totals and moneylines showed no edge. "
           "NBL showed no spread or total edge; its moneyline at a 5%+ edge was slightly positive (+2.5% over 204) and is "
           "tracked.")

league = st.radio("League", list(I.LEAGUES), format_func=lambda k: I.LEAGUES[k]["title"], horizontal=True,
                  key="ih_league")
picks = MS.load_game_picks(league)
now = datetime.now(timezone.utc).isoformat()
upcoming = [p for p in picks if str(p.get("kickoff")) > now and p.get("result") is None]
done = [p for p in picks if p.get("result")]


def _pick(p):
    out = []
    if p.get("pick") and p.get("home_spread") is not None:
        pt = p["home_spread"] if p["pick"] == "home" else -p["home_spread"]
        out.append(f"{p['home'] if p['pick'] == 'home' else p['away']} {pt:+g}")
    if p.get("total_pick"):
        out.append(f"{p['total_pick'].title()} {p['line_total']:g}")
    if p.get("ml_pick"):
        out.append(f"{p['home'] if p['ml_pick'] == 'home' else p['away']} ML")
    return " · ".join(out) or "—"


st.markdown(f"##### Upcoming ({len(upcoming)})")
if not upcoming:
    st.info(f"No upcoming {I.LEAGUES[league]['title']} games captured yet. The capture runs every 3 hours; ratings start "
            f"once the season has {I.LEAGUES[league]['min_games']} completed games.")
else:
    st.dataframe(pd.DataFrame([{
        "Tip (ET)": pd.to_datetime(p["kickoff"]).tz_convert("America/New_York").strftime("%a %I:%M %p"),
        "Game": f"{p['away']} @ {p['home']}",
        "Model margin": f"{p['home']} {p['model_margin']:+.1f}",
        "Line": f"{p['home']} {p['home_spread']:+g}",
        "Edge (pts)": f"{p['edge']:+.1f}",
        "Total: model / line": f"{p.get('model_total')} / {p.get('line_total') or '—'}",
        "Win chance: model / market": f"{p['model_p']:.0%} / " + ("—" if p.get("fair_home") is None else f"{p['fair_home']:.0%}"),
        "Tracking pick": _pick(p)} for p in sorted(upcoming, key=lambda x: x["kickoff"])]),
        hide_index=True, width="stretch")
    rules = IP.HOOPS_RULES.get(league, {})
    what = []
    if rules.get("spread") is not None:
        what.append(f"a spread pick needs the model {rules['spread']:g}+ points off the line")
    if rules.get("ml") is not None:
        what.append(f"a moneyline pick needs a {rules['ml']:.0%}+ edge")
    st.caption("Edge = the model's home margin minus the margin the spread implies; "
               + ("; ".join(what) if what else "no picks for this league") + ".")

st.markdown("##### Tracking record")
rec = IP.record(done)
if not rec:
    st.caption("Nothing graded yet.")
else:
    names = {"ml": "Moneyline", "spread": "Spread (vs the close)", "total": "Total"}
    st.dataframe(pd.DataFrame([{"Market": names.get(k, k), "Record": f"{r['w']}-{r['l']}" + (f"-{r['p']}" if r["p"] else ""),
                                "Profit (units)": f"{r['units']:+.1f}", "Per $1": "—" if r["roi"] is None else f"{r['roi']:+.1%}"}
                               for k, r in rec.items()]), hide_index=True, width="stretch")
