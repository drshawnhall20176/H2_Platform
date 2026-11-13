"""
props_section.py — a player-props section for the college game pages (Nov 12).

Owner: keep the game lines and add player props for the college sports. The props are the ones the Best Bets board
already prices and saves (todays_best.save_props: the sportsbooks plus Underdog / Pick6 for college basketball), so this
spends no Odds API credits and can't run the app out of memory. Each prop gets My Coach's verdict at its price, and
ticked rows log through log_ui like every other page. The boards refresh hourly and before the afternoon picks note
(morning_brief.refresh_boards); the section says when its prices were taken.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

import components as C


def _age(at: Optional[str]) -> str:
    if not at:
        return ""
    try:
        t = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        import pytz
        return t.astimezone(pytz.timezone("US/Eastern")).strftime("%-I:%M %p")
    except ValueError:
        return ""


def judged(rows: List[Dict], sport: str, bets=None, tag_records_for=None) -> List[Dict]:
    """Each saved prop with My Coach's verdict at its price; props without a price are kept, marked unchecked."""
    import coach as CO
    priced = [r for r in rows if r.get("price") is not None and r.get("chance") is not None]
    out = []
    if priced:
        if bets is None:
            import betlog as B
            bets = B.list_bets()
        if tag_records_for is None:
            import pick_records as PR
            tag_records_for = PR.tag_records
        out = CO.finder(priced, list(bets), tag_records_for(sport))
    out += [dict(r, verdict="⚪ No sportsbook price", edge=None) for r in rows if r not in priced]
    return out


def render(sport: str, day: str, title: str = "🎯 Player props") -> None:
    import log_ui as LU
    import todays_best as TB
    st.markdown(f"##### {title}")
    saved = TB.load_props(sport, day) or {}
    rows = list(saved.get("rows") or [])
    if not rows:
        st.info("No player props saved for today yet. They're priced when the books post them (the board refreshes "
                "hourly and again before the afternoon picks note); college props are thinner than the pros — many "
                "games have none.")
        return
    js = C.by_kickoff(judged(rows, sport), lambda j: j.get("time"))
    games = sorted({j.get("game") for j in js if j.get("game")})
    c1, c2 = st.columns([2, 1])
    g = c1.selectbox("Game", ["All games"] + games, key=f"ps_game_{sport}")
    good_only = c2.toggle("Only 🟢 Good bets", value=False, key=f"ps_good_{sport}")
    show = [j for j in js if (g == "All games" or j.get("game") == g) and (not good_only or j.get("verdict") == "🟢 Good bet")]
    if not show:
        st.caption("Nothing matches these filters.")
        return
    import coach as CO
    df = pd.DataFrame([{"Time": j.get("time") or "", "Game": j.get("game") or "", "Pick": j.get("pick"),
                        "Price": j.get("price"), "Book": j.get("book") or "", "Model": j.get("chance"),
                        "Use": j.get("use") or "", "Coach": j.get("verdict"),
                        "Edge": "" if j.get("edge") is None else CO.pts(j["edge"])} for j in show])
    sel = LU.selectable(df, f"ps_sel_{sport}", hide_index=True, width="stretch", column_config={
        "Price": st.column_config.NumberColumn(format="%+d"),
        "Model": st.column_config.NumberColumn(format="percent")})
    st.caption(C.money_md(
        f"The model's playable props for today ({len(rows)} saved, prices as of {_age(saved.get('at')) or 'today'}). "
        "Coach = My Coach's verdict at that price — 🟢 Good bet, 🟡 Maybe, 🔴 Skip. Tick rows to log them."))
    LU.panel(LU.picked(show, sel), f"ps_log_{sport}", day, tag=f"{sport.lower()}-props")
