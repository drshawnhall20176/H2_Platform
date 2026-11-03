"""
Tennis Lab — ATP / WTA match model (Nov 3). TRACKING ONLY until the record proves it. Owner only.

Every upcoming match the books price (The Odds API: the main ATP and WTA events), saved every 3 hours by the
capture-intl workflow with the model's read: surface Elo win chance vs the market's no-vig chance, total games and the
game handicap vs the posted lines, and a tracking pick where the model clears its bar. Graded from ESPN results.
Model: tennis_model.py; capture / grading / record: intl_picks.py.
"""
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import components as C
import intl_picks as IP
import model_store as MS

C.base_css()
C.page_header("🎾", "Tennis Lab",
              "ATP and WTA: surface Elo win chances against the books, total games and game handicaps. Tracking only "
              "until the record proves it.")
st.warning("Tracking only. These picks are being recorded to test the model against real lines; they are not "
           "recommendations to bet yet.")

picks = MS.load_game_picks("TENNIS")
now = datetime.now(timezone.utc).isoformat()
upcoming = [p for p in picks if str(p.get("kickoff")) > now and p.get("result") is None]
done = [p for p in picks if p.get("result")]


def _pct(x):
    return "—" if x is None else f"{x:.0%}"


def _odds(x):
    return "—" if x is None else f"{float(x):+.0f}"


def _pick(p):
    out = []
    if p.get("pick"):
        side = p["home"] if p["pick"] == "home" else p["away"]
        out.append(f"🎯 {side} ML")
    if p.get("spread_pick") and p.get("home_spread") is not None:
        pt = p["home_spread"] if p["spread_pick"] == "home" else -p["home_spread"]
        out.append(f"{p['home'] if p['spread_pick'] == 'home' else p['away']} {pt:+g} games")
    if p.get("total_pick") and p.get("line_total") is not None:
        out.append(f"{p['total_pick'].title()} {p['line_total']:g} games")
    return " · ".join(out) or "—"


tours = st.radio("Tour", ["All", "ATP", "WTA"], horizontal=True, key="tl_tour")
rows = [p for p in upcoming if tours == "All" or p.get("tour") == tours.lower()]
st.markdown(f"##### Upcoming ({len(rows)})")
if not rows:
    st.info("No upcoming matches captured yet. The capture runs every 3 hours while an ATP or WTA event the books "
            "price is on (Challengers and ITF aren't offered by the odds feed).")
else:
    st.dataframe(pd.DataFrame([{
        "Start (ET)": pd.to_datetime(p["kickoff"]).tz_convert("America/New_York").strftime("%a %I:%M %p"),
        "Event": f"{p.get('tour', '').upper()} {p.get('tournament', '')} · {p.get('surface', '')}",
        "Match": f"{p['home']} vs {p['away']}",
        "Model": _pct(p.get("model_p")), "Market": _pct(p.get("line")),
        "Edge": "—" if p.get("edge") is None else f"{p['edge']:+.0%}",
        "Best price": f"{_odds(p.get('best_home'))} / {_odds(p.get('best_away'))}",
        "Games: model / line": f"{p.get('model_total') or '—'} / {p.get('line_total') or '—'}",
        "Rated matches": f"{p.get('n_home', 0)} / {p.get('n_away', 0)}",
        "Tracking pick": _pick(p)} for p in sorted(rows, key=lambda x: x["kickoff"])]),
        hide_index=True, width="stretch")
    st.caption(f"Model = the first-named player's chance from surface Elo; Market = the books' no-vig chance. A "
               f"match-winner pick needs a {IP.TENNIS_ML_EDGE:.0%}+ edge and {IP.TENNIS_MIN_MATCHES}+ rated matches "
               f"for both players; game picks need the model {50 + IP.TENNIS_GAMES_EDGE * 100:.0f}%+ on a side.")

st.markdown("##### Tracking record")
rec = IP.record(done)
if not rec:
    st.caption("Nothing graded yet.")
else:
    names = {"ml": "Match winner", "spread": "Game handicap", "total": "Total games"}
    st.dataframe(pd.DataFrame([{"Market": names.get(k, k), "Record": f"{r['w']}-{r['l']}" + (f"-{r['p']}" if r["p"] else ""),
                                "Profit (units)": f"{r['units']:+.1f}", "Per $1": "—" if r["roi"] is None else f"{r['roi']:+.1%}"}
                               for k, r in rec.items()]), hide_index=True, width="stretch")
st.caption("Player props (aces, double faults) aren't in the odds feed, so they aren't modeled.")
