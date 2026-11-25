"""
players_cards.py — the Players page as cards (Nov 25): tonight's players for the chosen sport, by game, each opening
the one player card (today_visual._player_dialog). Owner: one place for a player, not several tools with their own
numbers; the tools stay under Table.
"""
from __future__ import annotations

from typing import Dict, List

import h2_brand as HB


def by_game(rows: List[Dict]) -> List[tuple]:
    """[(game, time, {team: [rows]})] in start order, one row per player (his bet, else his main stat)."""
    import components as C
    import today_visual as TV
    games: Dict[str, List[Dict]] = {}
    for r in rows or []:
        if r.get("game") and TV.player_of(r):
            games.setdefault(r["game"], []).append(r)
    out = []
    for g, rs in games.items():
        t = next((r.get("time") for r in rs if r.get("time")), "")
        out.append((g, t, TV.team_groups(rs)))
    return sorted(out, key=lambda x: (C._kick_dt(x[1]) is None, str(C._kick_dt(x[1]) or ""), x[0]))


def render(sport: str) -> None:
    import streamlit as st
    import components as C
    import today_visual as TV
    rows = TV.all_props(sport)
    if not rows:
        st.info("No player lines on tonight's board for this sport yet — they're added as the books post them.")
        return
    names = sorted({TV.player_of(r) for r in rows if TV.player_of(r)})
    fk = f"pl_find_{sport}"

    def _picked():                                              # open once, then clear the box (no reopening loop)
        st.session_state["_pl_open"] = st.session_state.get(fk)
        st.session_state[fk] = ""
    st.selectbox("🔎 Find a player", [""] + names, key=fk, on_change=_picked,
                 format_func=lambda n: "Type a name…" if not n else n)
    pick = st.session_state.pop("_pl_open", None)
    if pick:
        row = next(r for r in sorted(rows, key=TV._rank) if TV.player_of(r) == pick)
        TV._player_dialog(row, sport, rows)

    @st.fragment
    def cards():                                                # a tap reruns only this list
        for gi, (game, when, teams) in enumerate(by_game(rows)):
            with st.container(border=True):
                st.markdown(f'<div style="color:{HB.INK};font-weight:800;font-size:15px;">{game}</div>'
                            f'<div style="color:{HB.INK_SOFT};font-size:12px;">{when}</div>', unsafe_allow_html=True)
                cols = st.columns(max(1, min(2, len(teams))))
                for (team, lst), col in zip(teams.items(), cols * 2):
                    with col:
                        st.markdown(f"<div style='color:{HB.INK_SOFT};font-size:11.5px;letter-spacing:.05em;'>"
                                    f"{str(team).upper()}</div>", unsafe_allow_html=True)
                        for i, r in enumerate(lst):
                            ch = TV._chance(r.get("earned") if r.get("earned") is not None else r.get("chance"))
                            label = (f"{TV._bet_mark(r)}{TV.ls_mark(sport, TV.player_of(r))}"
                                     f"{TV.player_of(r)} — {TV.market_label(r)} · {ch}"
                                     f"{'' if r.get('earned') is not None else ' model'}")
                            if st.button(label, key=f"pl_{sport}_{gi}_{TV._norm(team)}_{i}", width="stretch",
                                         type="primary" if TV._bet_mark(r).startswith("🃏") else "secondary"):
                                TV._player_dialog(r, sport, rows)
        st.caption("💎 a value long shot tonight · 🃏 a bet (highlighted) · 🧪 tracking · no mark = the model's read only. Each player shows his bet if "
                   "he has one, else his main stat; his card has every prop he has tonight.")
    cards()
