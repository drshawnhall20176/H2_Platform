"""
card_links.py — tables whose rows open the player card or the game card (Nov 25).

Owner: "what other redundancy can be resolved by direct linking such as players and player card ... let's do them
all." Any table of picks or games becomes a way into the one card for that player or game: tap a row, the card opens
(the same pop-ups Today and the Games pages use). The selection opens the card once, not on every rerun.
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence


def table(data, key: str, items: Sequence, open_fn: Callable, caption: Optional[str] = None, **kwargs) -> None:
    """st.dataframe(data) whose row `i` opens `open_fn(items[i])`. `data` may be a DataFrame or a Styler."""
    import streamlit as st
    flag = f"{key}__open"

    def _picked():
        ev = st.session_state.get(key)
        try:
            rows = list(ev.selection.rows) if ev is not None else []
        except AttributeError:
            rows = list(((ev or {}).get("selection") or {}).get("rows") or [])
        if rows:
            st.session_state[flag] = rows[0]
    st.dataframe(data, key=key, on_select=_picked, selection_mode="single-row", **kwargs)
    st.caption(caption or "Tap a row to open its card.")
    i = st.session_state.pop(flag, None)
    if i is not None and 0 <= i < len(items):
        try:
            open_fn(items[i])
        except Exception:                                       # noqa: BLE001 -- a card that can't open never breaks the page
            st.toast("That card couldn't open just now.")


def open_player(sport: str):
    """An opener for a pick row (board play or saved row): his player card with every prop he has tonight."""
    def _open(row):
        import today_visual as TV
        TV._player_dialog(row, sport, TV.all_props(sport))
    return _open


def open_player_named(sport: str):
    """An opener for a row that only names the player (a long shot, an alt rung): his board row -- the same market if
    he has one -- so the card opens on that prop; a minimal row otherwise."""
    def _open(row):
        import today_visual as TV
        name = row.get("Player") or row.get("player")
        mk = row.get("Market") or row.get("market")
        mine = [r for r in TV.all_props(sport) if TV._norm(TV.player_of(r)) == TV._norm(name)]
        pick = next((r for r in mine if (r.get("market") or r.get("Market")) == mk), None) or (mine[0] if mine else None)
        if pick is None:
            pick = {"player": name, "market": mk, "game": row.get("Game") or row.get("game"),
                    "values": row.get("values") or [], "projection": row.get("Projection") or row.get("projection")}
        TV._player_dialog(pick, sport, TV.all_props(sport))
    return _open


def open_game(sport_of: Callable = None):
    """An opener for a game row: its game card, found among today's game boards by its label."""
    def _open(row):
        import game_card as GC
        import today_visual as TV
        w = game_row(row, sport_of(row) if sport_of else row.get("sport"))
        if w is None:
            import streamlit as st
            st.toast("This game has no model read yet, so there's no game card.")
            return
        TV._game_dialog(w, TV.players_in_game(TV.all_props(w.get("sport") or ""), w))
    return _open


def game_row(row, sport: Optional[str]):
    """The saved board row for a game (`row["game"]` / `row["Game"]`, "Away @ Home") on its date, if any."""
    import game_card as GC
    import todays_best as TB
    label = row.get("game") or row.get("Game") or ""
    day = row.get("date") or row.get("slate_date")
    if not day:
        from datetime import datetime
        import pytz
        day = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
    try:
        winners = TB.winner_rows(str(day)[:10], leagues=[sport] if sport else None)
    except Exception:                                           # noqa: BLE001
        winners = []
    hit = GC.for_game(winners, label)
    if hit is not None:
        return hit
    import today_visual as TV
    for w in winners:                                           # "NYJ @ MIA", "Jets @ Dolphins" ...
        full = w.get("_full") or {}
        if full.get("home") and full.get("away") and TV.same_game(label, full["home"], full["away"]):
            return w
    return None
