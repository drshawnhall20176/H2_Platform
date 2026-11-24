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


@st.cache_data(ttl=120, show_spinner=False)
def _load(sport: str, day: str):
    """Nov 14: the saved board and My Coach's verdicts, cached for 2 minutes -- a Saturday college board is hundreds of
    props, and judging them (with the bet history and the 30-day records) on every click made the Game Lab crawl."""
    import todays_best as TB
    saved = TB.load_props(sport, day) or {}
    rows = list(saved.get("rows") or [])
    return saved, rows, (judged(rows, sport) if rows else [])


def _prop_tagged(use) -> bool:
    """Nov 24 (owner's Bet? column): a prop carrying a tested tag (💰 / 🔒 / 🎟️ / 🎯)."""
    u = str(use or "")
    return any(i in u for i in ("💰", "🔒", "🎟️", "🎯"))


def render(sport: str, day: str, title: str = "🎯 Player props") -> None:
    import log_ui as LU
    st.markdown(f"##### {title}")
    try:                                                        # Nov 23: a prop rule being tracked forward, if any
        import candidate_rules as CR
        _cand = CR.prop_status_line(sport)
        if _cand:
            st.caption(_cand)
    except Exception:                                           # noqa: BLE001
        pass
    saved, rows, _judged = _load(sport, day)
    if not rows:
        # Nov 23 (owner, Monday Madness): "none saved" read like a broken page. Say what this list holds and why
        # it's empty: only props with an edge are listed, and pick'em-app lines alone don't carry one.
        st.info("**No player props with an edge yet today.** This list shows only props the model rates playable "
                "(🔒 / 🎟️ / 🎯 / 💰). Early in the day most college props are pick'em-app lines (Underdog, Pick6), "
                "and those haven't earned an edge in testing — they said 57–59% and hit 44–52% — so they're scored "
                "as coin flips. Sportsbook props usually post late morning; the board refreshes every hour and "
                "anything with an edge appears here. Every prop, edge or not, is on the Best Bets page.")
        return
    js = C.by_kickoff(_judged, lambda j: j.get("time"))
    games = sorted({j.get("game") for j in js if j.get("game")})
    c1, c2 = st.columns([2, 1])
    g = c1.selectbox("Game", ["All games"] + games, key=f"ps_game_{sport}")
    good_only = c2.toggle("Only 🟢 Good bets", value=False, key=f"ps_good_{sport}")
    show = [j for j in js if (g == "All games" or j.get("game") == g) and (not good_only or j.get("verdict") == "🟢 Good bet")]
    if not show:
        st.caption("Nothing matches these filters.")
        return
    import coach as CO
    import game_previews as GP
    _pk = GP.bet_filter(f"ps_bet_{sport}")                     # Nov 24 (owner): 🃏 / 🧪 / Info only filter buttons
    show = [j for j in show if GP.prop_bet(sport, j.get("use"), j) in _pk]
    if not show:
        st.caption("No props of the Bet? kinds picked.")
        return
    try:                                                        # Nov 24: the game-lab columns on props too
        _blow = GP.game_blowouts(sport, [j.get("game") for j in show])
    except Exception:                                           # noqa: BLE001
        _blow = {}
    df = pd.DataFrame([{"League": sport, "Time": j.get("time") or "", "Game": j.get("game") or "",
                        GP.BET: GP.prop_bet(sport, j.get("use"), j), "Pick": j.get("pick"),
                        "Use": j.get("use") or "", "Model": j.get("chance"), "Price": j.get("price"),
                        "Blowout risk": _blow.get(j.get("game"), "—"),
                        GP.AGREE: GP.prop_agreement(j.get("chance"), j.get("price")),
                        "Coach": j.get("verdict"),
                        "Edge": "" if j.get("edge") is None else CO.pts(j["edge"]),
                        "Book": j.get("book") or ""} for j in show])
    sel = LU.selectable(df, f"ps_sel_{sport}", hide_index=True, width="stretch", column_config={
        "Price": st.column_config.NumberColumn(format="%+d"),
        "Model": st.column_config.NumberColumn(format="percent")})
    st.caption(C.money_md(
        f"The model's playable props for today ({len(rows)} saved, prices as of {_age(saved.get('at')) or 'today'}). "
        "Coach = My Coach's verdict at that price — 🟢 Good bet, 🟡 Maybe, 🔴 Skip. Blowout risk = the game's chance of "
        "a lopsided finish (starters may sit late). Model & market agree? = does the price lean the same way as the "
        "model (✅ yes · ⚠️ the price says the other side · ➖ about even). Tick rows to log them."))
    LU.panel(LU.picked(show, sel), f"ps_log_{sport}", day, tag=f"{sport.lower()}-props")
