"""
lab_desk.py — the Command Center for sports without a props model: UFC, Tennis, International Hoops, Soccer (Nov 21).

Owner, Nov 21: "UFC, Tennis and International Hoops ... the command Center shows nothing, it appears I need to click
the link under recommendations for anything to show." The Command Center is built around the props boards (tonight's
games, playable plays, top leans, CLV) -- for a sport with no props model it showed empty tiles (UFC) or a "not wired
up" notice (the labs). Each of these sports already has its day's slate: the labs' game picks (todays_best.winner_rows
/ soccer_rows -- the Money · Pick · Winner board the Game Labs use) and UFC's whole card in one odds request
(ufc_engine.get_card). This desk shows that slate, the sport's Bet Log record, and the way to the full page.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List

import pandas as pd
import streamlit as st

PAGES = {"UFC": ("views/23_#L01f94a_UFC_Fight_Card.py", "🥊 Open the UFC Fight Card — every bout, method and rounds"),
         "TENNIS": ("views/43_Tennis_Lab.py", "🎾 Open the Tennis Lab"),
         "INTL": ("views/44_Intl_Hoops.py", "🌍 Open International Hoops"),
         "SOCCER": ("views/55_Soccer_Lab.py", "⚽ Open the Soccer Lab")}


def is_lab(sport) -> bool:
    return not sport.has_projections and sport.key != "MLB"


@st.cache_data(ttl=300, show_spinner="Reading today's games…", max_entries=16)
def _game_rows(key: str, day: str) -> List[Dict]:
    import intl_hoops as H
    import todays_best as TB
    if key == "SOCCER":
        return TB.soccer_rows(day)
    if key == "TENNIS":
        return TB.winner_rows(day, leagues=["TENNIS"])
    return TB.winner_rows(day, leagues=[k for k in H.LEAGUES if k not in TB.WINNER_LEAGUES])


@st.cache_data(ttl=600, show_spinner="Loading the fight card…", max_entries=8)
def _ufc_card(day: str) -> List[Dict]:
    import ufc_engine as E
    try:
        key = st.secrets.get("ODDS_API_KEY") or os.environ.get("ODDS_API_KEY")
    except Exception:                                           # noqa: BLE001
        key = os.environ.get("ODDS_API_KEY")
    if not key:
        return []
    card = E.get_card(key, day)                                 # one odds request for the whole card
    return E.main_card_only(card) or card


def _record(key: str) -> Dict:
    import betlog as B
    try:
        return B.summary([b for b in B.list_bets() if (b.get("sport") or "") == key])
    except Exception:                                           # noqa: BLE001
        return {"settled": 0}


def render(sport, day: str) -> None:
    import components as C
    page, label = PAGES.get(sport.key, (None, None))
    st.caption(f"{sport.icon} {sport.label} has no player-props model, so this desk shows the day's slate instead: "
               "the games, the model's read where it has one, and the market's chances. The full tools are one click "
               "away.")
    if page:
        try:
            st.page_link(page, label=label)
        except Exception:                                       # noqa: BLE001 -- page hidden in this build
            pass
    rec = _record(sport.key)
    if sport.key == "UFC":
        try:
            card = _ufc_card(day)
        except Exception as exc:                                # noqa: BLE001
            card = []
            st.caption(f"The fight card couldn't load right now ({type(exc).__name__}).")
        favs = [b for b in card if b.get("p_a") is not None]
        top = max(favs, key=lambda b: max(b["p_a"], 1 - b["p_a"])) if favs else None
        C.kpi_row([
            {"icon": "🥊", "value": str(len(card)), "label": "Bouts today (main cards)"},
            {"icon": "⭐", "value": "—" if top is None else (top["a"] if top["p_a"] >= 0.5 else top["b"]),
             "label": "Biggest favorite"},
            {"icon": "🧾", "value": f"{rec.get('wins', 0)}–{rec.get('losses', 0)}" if rec.get("settled") else "—",
             "label": "Bet Log record, UFC"},
            {"icon": "📈", "value": f"{rec['beat_close_rate']:.0f}%" if rec.get("beat_close_rate") is not None else "—",
             "label": "Beat-close rate"},
        ])
        if not card:
            st.info("No major-promotion bouts listed for today. The Fight Card page lists the next card dates.")
            return
        C.section_header("🥊", "Today's card")
        rows = []
        for b in C.by_kickoff(card, lambda b: b.get("commence")):
            fav_a = b["p_a"] is not None and b["p_a"] >= 0.5
            rows.append({"Time (ET)": pd.to_datetime(b["commence"]).tz_convert("America/New_York").strftime("%-I:%M %p"),
                         "Bout": f"{b['a']} vs {b['b']}",
                         "Favorite": "—" if b["p_a"] is None else (b["a"] if fav_a else b["b"]),
                         "Market chance": None if b["p_a"] is None else (b["p_a"] if fav_a else 1 - b["p_a"]),
                         "Best price, 1st named": "—" if b["best_a"] is None else f"{float(b['best_a']):+.0f}",
                         "Best price, 2nd named": "—" if b["best_b"] is None else f"{float(b['best_b']):+.0f}",
                         "Books": b.get("books")})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"Market chance": st.column_config.NumberColumn(format="percent")})
        st.caption("No UFC model: the chances are the books' own, with the margin removed (the median across books). "
                   "Methods, rounds and logging are on the Fight Card page.")
        return
    try:
        games = [dict(r) for r in _game_rows(sport.key, day)]
    except Exception as exc:                                    # noqa: BLE001
        games = []
        st.caption(f"Today's games couldn't load right now ({type(exc).__name__}).")
    picks = [r for r in games if r.get("best") and r.get("best_tested")]
    C.kpi_row([
        {"icon": "🏟️", "value": str(len(games)), "label": "Games today"},
        {"icon": "🎯", "value": str(len(picks)), "label": "Tested picks"},
        {"icon": "💰", "value": str(sum(1 for r in games if r.get("money"))), "label": "💰 Money picks"},
        {"icon": "🧾", "value": f"{rec.get('wins', 0)}–{rec.get('losses', 0)}" if rec.get("settled") else "—",
         "label": f"Bet Log record, {sport.label.split(' — ')[0]}"},
        {"icon": "📈", "value": f"{rec['beat_close_rate']:.0f}%" if rec.get("beat_close_rate") is not None else "—",
         "label": "Beat-close rate"},
    ])
    if not games:
        st.info("No games with a model read for today yet. They fill in as the morning capture runs.")
        return
    import game_lines_table as GLT
    GLT.render(games, f"cc_lab_{sport.key}", day, past=False, show_sport=False,
               title="Today's games: 💰 Money pick · Line pick · Winner pick")
