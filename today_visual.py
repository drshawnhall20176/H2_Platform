"""
today_visual.py — the clickable Today page (Nov 25, commercial preview only).

Owner, Nov 24: "One thing that I like on the H2 site is the today page ... we are missing some good functionality like
the ability to click a card and have it jump to a game or prop." The customer Today page (views/57_Today.py) gets a
Cards view, in H2's own look (h2_brand.py):

  * one bordered row per sport playing today: its strongest picks as cards (player picks from pick types with a
    winning 30-day record; game lines for the game-line sports, each saying 🃏 Bet / 🧪 Tracking / Info only), each
    with an "Open" button -> the player card (player_card.py) or the game card (game_card.py) in a pop-up;
  * under it, a strip of that sport's games, by start time, each opening its game card.

It is shown only in the commercial layout (a commercial deployment, or the owner previewing it); the tables stay one
click away (the page's Cards | Table switch). It reads only what the boards already saved.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Sequence

import h2_brand as HB

STRIP_MAX = 8
CARDS_PER_SPORT = 4


# --------------------------------------------------------------------------- data (no Streamlit)
def _norm(s) -> str:
    return re.sub(r"[^a-z0-9 ]", "", str(s or "").lower()).strip()


def _nick(team) -> str:
    w = _norm(team).split()
    return w[-1] if w else ""


def same_game(prop_game, home, away) -> bool:
    """A prop row's game string against a board game's teams: exact, or both teams' last names in it."""
    g = _norm(prop_game)
    if not g:
        return False
    if g == _norm(f"{away} @ {home}"):
        return True
    h, a = _nick(home), _nick(away)
    return bool(h and a) and h in g.split() and a in g.split()


def props_in_game(rows: Sequence[Dict], w: Dict) -> List[Dict]:
    rec = w.get("_rec") or {}
    home, away = rec.get("home"), rec.get("away")
    sp = w.get("sport")
    return [r for r in rows or [] if r.get("kind") == "Prop" and r.get("sport") == sp
            and same_game(r.get("game"), home, away)]


def kickoff_key(w: Dict) -> str:
    return str((w.get("_rec") or {}).get("kickoff") or (w.get("_full") or {}).get("kickoff") or "9999")


def games_for(winners: Sequence[Dict], sport: str) -> List[Dict]:
    """A sport's games, earliest first; games already started go last."""
    import game_lines_table as GLT
    ws = [w for w in winners or [] if w.get("sport") == sport]

    def started(w):
        try:
            return GLT.started(w)
        except Exception:                                       # noqa: BLE001
            return False
    return sorted(ws, key=lambda w: (started(w), kickoff_key(w)))


def prop_row_for(rows: Sequence[Dict], card: Dict) -> Optional[Dict]:
    return next((r for r in rows or [] if r.get("kind") == "Prop" and r.get("sport") == card.get("sport")
                 and r.get("pick") == card.get("pick")), None)


def sport_cards(sport: str, rows: Sequence[Dict], winners: Sequence[Dict], day: str,
                records_for: Optional[Callable] = None, line_rows: Optional[Callable] = None) -> List[Dict]:
    """Up to four cards for one sport: game-line sports show their game lines (Bet? first); the others their player
    picks from winning pick types, topped up with playable game lines."""
    import college_lines as CLT
    import customer_today as CT
    if sport in CLT.LINE_SPORTS_TODAY:
        lr = (line_rows or (lambda s: CLT.today_rows(s, day, winners)))(sport)
        return [dict(c, kind="Line") for c in CLT.today_cards(lr, n=CARDS_PER_SPORT)]
    out = []
    if sport in CT.PROPS_SPORTS:
        for c in CT.top_cards([r for r in rows or [] if r.get("sport") == sport], records_for=records_for,
                              n=CARDS_PER_SPORT):
            out.append(dict(c, kind="Prop"))
    if len(out) < CARDS_PER_SPORT:
        for ln in CT.line_picks([w for w in winners or [] if w.get("sport") == sport]):
            out.append({"sport": sport, "pick": ln["Pick"], "chance": ln.get("Chance"), "price": ln.get("Best price"),
                        "game": ln.get("Game") or "", "time": ln.get("Time") or "", "record": ln.get("Record (30 days)"),
                        "basis": ln.get("Basis"), "kind": "Line", "lock": False, "money": False})
            if len(out) >= CARDS_PER_SPORT:
                break
    return out


# --------------------------------------------------------------------------- drawing
import streamlit as _st


# The two pop-ups, at module level so a click inside one (a player picker in the game card) reruns just the pop-up.
@_st.dialog("Player card", width="large")
def _player_dialog(row: Dict, sport: str):
    import game_previews as GP
    import player_card as PC
    c = PC.from_row(row)
    PC.render(c, sport, bet=GP.prop_bet(sport, str(c.get("Use") or ""), c))


@_st.dialog("Game card", width="large")
def _game_dialog(w: Dict, props: List[Dict]):
    import game_card as GC
    GC.render(GC.build(w), props, key=f"gcd_{_norm(w.get('game')).replace(' ', '_')}")


def _chance(x) -> str:
    try:
        return f"{float(x):.0%}"
    except (TypeError, ValueError):
        return "—"


def pick_card_html(c: Dict) -> str:
    tag = c.get("bet") or (c.get("record") and f"✅ {c['record']}") or ""
    top = HB.bet_chip(c["bet"]) if c.get("bet") else (
        f'<span style="color:{HB.INK_SOFT};font-size:12px;">{tag}</span>' if tag else "")
    icons = ("💰 " if c.get("money") else "") + ("🔒 " if c.get("lock") else "")
    price = c.get("price") if c.get("price") not in (None, "", "—") else ""
    return (f'<div style="min-height:132px;">{top}'
            f'<div style="color:{HB.INK};font-weight:800;font-size:15.5px;margin-top:7px;line-height:1.25;">'
            f'{icons}{c.get("pick") or ""}</div>'
            f'<div style="color:{HB.BLUE};font-size:24px;font-weight:800;margin-top:4px;">{_chance(c.get("chance"))}'
            f'<span style="color:{HB.GOLD};font-size:13px;font-weight:700;"> {price}</span></div>'
            f'<div style="color:{HB.INK_SOFT};font-size:12px;margin-top:2px;">{c.get("game") or ""}'
            f'{" · " + c["time"] if c.get("time") else ""}</div></div>')


def game_tile_html(w: Dict) -> str:
    import game_lines_table as GLT
    try:
        bet = GLT.bet(w)
    except Exception:                                           # noqa: BLE001
        bet = ""
    try:
        gone = GLT.started(w)
    except Exception:                                           # noqa: BLE001
        gone = False
    lines = " · ".join(x for x in (w.get("spread_txt") or "", f"O/U {w['total_txt']}" if w.get("total_txt") else "")
                       if x) or "No line yet"
    return (f'<div style="min-height:108px;{"opacity:.55;" if gone else ""}">'
            f'<div style="color:{HB.INK_SOFT};font-size:11.5px;letter-spacing:.05em;">'
            f'{w.get("time") or ""}{" · started" if gone else ""}</div>'
            f'<div style="color:{HB.INK};font-weight:800;font-size:14px;margin-top:3px;line-height:1.25;">'
            f'{w.get("game") or ""}</div>'
            f'<div style="color:{HB.GOLD};font-size:12.5px;margin-top:4px;">{lines}</div>'
            f'<div style="color:{HB.BLUE_SOFT};font-size:12px;">Model: {w.get("model_txt") or "—"}</div>'
            f'<div style="margin-top:6px;">{HB.bet_chip(bet) if bet else ""}</div></div>')


def render(live: Sequence, rows: Sequence[Dict], winners: Sequence[Dict], day: str,
           records_for: Optional[Callable] = None, line_rows: Optional[Callable] = None) -> None:
    """The Cards view: one row per sport (busiest first), its pick cards, then its game strip."""
    import streamlit as st
    import game_card as GC
    player_dlg, game_dlg = _player_dialog, _game_dialog
    sections = []
    for s in live:
        try:
            cards = sport_cards(s.key, rows, winners, day, records_for, line_rows)
        except Exception:                                       # noqa: BLE001 -- one sport never blanks the page
            cards = []
        games = games_for(winners, s.key)
        if cards or games:
            sections.append((s, cards, games))
    if not sections:
        st.info("No games or picks on today's boards yet. Boards fill in through the day as the books post lines.")
        return
    sections.sort(key=lambda x: (-len(x[1]), -len(x[2])))
    for s, cards, games in sections:
        with st.container(border=True):
            st.markdown(f"#### {s.icon} {s.key}  \n<span style='opacity:.7'>{len(games)} game"
                        f"{'s' if len(games) != 1 else ''} today</span>", unsafe_allow_html=True)
            if cards:
                for i, (col, c) in enumerate(zip(st.columns(CARDS_PER_SPORT), cards)):
                    with col.container(border=True):
                        st.markdown(pick_card_html(c), unsafe_allow_html=True)
                        if st.button("Open →", key=f"tv_card_{s.key}_{i}", width="stretch",
                                     help="Open this pick's player card" if c.get("kind") == "Prop"
                                     else "Open this game's card"):
                            if c.get("kind") == "Prop":
                                row = prop_row_for(rows, c)
                                if row is not None:
                                    player_dlg(row, s.key)
                                else:
                                    st.toast("That player's card isn't on the saved board yet.")
                            else:
                                w = GC.for_game(winners, c.get("game"))
                                if w is not None:
                                    game_dlg(w, props_in_game(rows, w))
                                else:
                                    st.toast("That game's card isn't on the saved board yet.")
            else:
                st.caption("No pick clears the bar here yet. Open a game below for the model's read.")
            if games:
                st.markdown(f"<div style='color:{HB.INK_SOFT};font-size:12.5px;margin:6px 0 2px;letter-spacing:.05em;'>"
                            "GAMES · EARLIEST FIRST</div>", unsafe_allow_html=True)
                shown = games[:STRIP_MAX]
                for start in range(0, len(shown), 4):
                    cols = st.columns(4)
                    for j, w in enumerate(shown[start:start + 4]):
                        with cols[j].container(border=True):
                            st.markdown(game_tile_html(w), unsafe_allow_html=True)
                            if st.button("Game card →", key=f"tv_game_{s.key}_{start + j}", width="stretch"):
                                game_dlg(w, props_in_game(rows, w))
                if len(games) > STRIP_MAX:
                    st.caption(f"{len(games) - STRIP_MAX} more {s.key} games under **Games** in the sidebar, or "
                               "switch to **Table** above.")
