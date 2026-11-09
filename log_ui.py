"""
log_ui.py — tick rows in a table, log them to the Bet Log as singles, a parlay, or both (Nov 8).

Used by Today's best (Home), the Analyst Desk and My Coach. A table drawn with `selectable()` gets a tick box on every
row; `panel()` takes the ticked picks and shows the price you got (editable), singles / parlay / both, stakes, parlay
odds (pre-filled from the legs' prices), real money or tracking, a strategy tag, and the Log button. The writing is
todays_best.log_selection -- the same code the old dropdown used.

An item is a dict with at least "sport", "pick" (what the row says) and "price"; props add "player", "market",
"side", "line", "game", "chance", "book", "pid"; game lines carry the Game Lab record ("_rec", "bet_market",
"bet_side", "bet_line", "best_tested", "best_chance").
"""
from __future__ import annotations

from typing import Dict, List, Sequence

import pandas as pd
import streamlit as st


def selectable(df: pd.DataFrame, key: str, **kw) -> List[int]:
    """st.dataframe with a tick box on every row; returns the ticked rows' positions in `df`."""
    ev = st.dataframe(df, on_select="rerun", selection_mode="multi-row", key=key, **kw)
    try:
        return sorted(int(i) for i in (ev.selection.rows or []))
    except Exception:                                           # noqa: BLE001 -- older Streamlit / tests
        return []


def picked(items: Sequence[Dict], rows: Sequence[int]) -> List[Dict]:
    return [dict(items[i]) for i in rows if 0 <= i < len(items)]


def panel(items: Sequence[Dict], key: str, date_str: str, tag: str = "platform-test", past: bool = False) -> None:
    """The log box for ticked picks. Nothing is written until the button is pressed."""
    if not items:
        st.caption("☑️ Tick rows in the table to log them to the Bet Log — as singles, a parlay, or both.")
        return
    if past:
        st.caption("Pick today's date to log picks.")
        return
    import todays_best as TB
    st.markdown(f"**📝 Log {len(items)} ticked pick{'s' if len(items) != 1 else ''}**")
    ed = pd.DataFrame([{"Pick": f"{it.get('sport', '')} · {it.get('pick', '')}",
                        "Price": None if it.get("price") is None else float(it["price"])} for it in items])
    ed = st.data_editor(ed, hide_index=True, width="stretch", key=f"{key}_prices", disabled=["Pick"],
                        column_config={"Price": st.column_config.NumberColumn(
                            "Price you got", help="American odds from your slip; edit if it moved", format="%+d")})
    prices = [r["Price"] for r in ed.to_dict("records")]
    its = [dict(it, price=(None if p is None or p != p else p)) for it, p in zip(items, prices)]
    c1, c2, c3 = st.columns(3)
    modes = ["Singles", "Parlay", "Both"] if len(its) >= 2 else ["Singles"]
    mode = c1.radio("Log as", modes, horizontal=True, key=f"{key}_mode")
    stake = c2.number_input("Stake per single ($)", min_value=0.0, value=4.0, step=1.0, key=f"{key}_stake",
                            disabled=mode == "Parlay")
    real = c3.checkbox("Real money", value=True, key=f"{key}_real", help="Untick to log it as tracking only")
    p1, p2, p3 = st.columns(3)
    have = [x["price"] for x in its if x.get("price") is not None]
    calc = TB.parlay_odds(have) if len(have) == len(its) and len(its) >= 2 else None
    pstake = p1.number_input("Parlay stake ($)", min_value=0.0, value=10.0, step=1.0, key=f"{key}_pstake",
                             disabled=mode == "Singles")
    podds = p2.number_input("Parlay odds (from your slip)", value=int(calc) if calc else None, step=5,
                            key=f"{key}_podds", placeholder="type your slip's odds",
                            disabled=mode == "Singles",
                            help="Pre-filled with the legs' prices multiplied; same-game parlays usually pay less — "
                                 "type what your slip says")
    tg = p3.text_input("Strategy tag", value=tag, key=f"{key}_tag")
    broken = [x.get("pick") for x in its if not x.get("_rec") and (not x.get("player") or not x.get("side")
                                                                    or x.get("line") is None)]
    if broken:
        st.warning("These are missing the player, side or line and won't be logged — reload the page and tick them "
                   "again: " + "; ".join(str(b) for b in broken))
    missing = [x.get("pick") for x in its if x.get("price") is None]
    if missing:
        st.caption("Add a price for: " + "; ".join(str(m) for m in missing) + " — picks without one aren't logged.")
    if st.button("📝 Log to Bet Log", type="primary", key=f"{key}_go"):
        if mode != "Singles" and not podds:
            st.error("Type the parlay odds from your slip first.")
            return
        try:
            done = TB.log_selection(its, mode, stake, pstake, int(podds or 0), real, tg.strip(), date_str)
            msg = []
            if done["singles"]:
                msg.append(f"{len(done['singles'])} single(s) logged")
            if done["ticket"]:
                msg.append(f"parlay logged (#{done['ticket']})")
            if done["skipped"]:
                msg.append(f"{done['skipped']} already in today's log, skipped")
            if msg:
                st.success("; ".join(msg) + ". See the Bet Log.")
            else:
                st.warning("Nothing logged — check the prices.")
        except Exception as exc:                                # noqa: BLE001
            st.error(f"Couldn't log: {type(exc).__name__}: {exc}")
