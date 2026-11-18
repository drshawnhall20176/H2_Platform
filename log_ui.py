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
    """st.dataframe with a tick box on every row; returns the ticked rows' positions in `df`. The public build (no Bet
    Log) gets the plain table."""
    import components as C
    if not C.is_owner():
        st.dataframe(df, **kw)
        return []
    ev = st.dataframe(df, on_select="rerun", selection_mode="multi-row", key=key, **kw)
    try:
        return sorted(int(i) for i in (ev.selection.rows or []))
    except Exception:                                           # noqa: BLE001 -- older Streamlit / tests
        return []


def tick_grid(df: pd.DataFrame, tick_cols: Sequence[str], key: str, **kw) -> List[tuple]:
    """Nov 18: a table with tick boxes in chosen columns (placed by the caller, next to what they bet on) instead of one
    box per row. Returns [(row position, ticked column)] in table order. The public build gets the table without
    the boxes."""
    import components as C
    cols = [c for c in tick_cols if c in df.columns]
    if not C.is_owner():
        st.dataframe(df.drop(columns=cols), **kw)
        return []
    cfg = {c: st.column_config.CheckboxColumn(c, default=False, width="small") for c in cols}
    ed = st.data_editor(df, key=key, disabled=[c for c in df.columns if c not in cols], column_config=cfg, **kw)
    out = []
    try:
        for i, row in enumerate(ed.to_dict("records")):
            out += [(i, c) for c in cols if bool(row.get(c))]
    except Exception:                                           # noqa: BLE001 -- tests
        pass
    return out


def relined(it: Dict, line) -> Dict:
    """Nov 18: an item at a different line (a DraftKings alt spread, say): label, line and the model's chance follow."""
    if line is None or line != line or it.get("bet_market") not in ("Spread", "Total") or not it.get("_rec"):
        return it
    line = float(line)
    if it.get("bet_line") is not None and abs(float(it["bet_line"]) - line) < 1e-9:
        return it
    p, side = it["_rec"], it.get("bet_side")
    if it["bet_market"] == "Spread":
        label = f"{p['home'] if side == 'home' else p['away']} {line:+g}"
    else:
        label = f"{str(side).title()} {line:g} ({p['away']} @ {p['home']})"
    try:
        import intl_picks as IP
        ch = IP.fair_chance(p, it["bet_market"], side, line)
    except Exception:                                           # noqa: BLE001
        ch = None
    return dict(it, pick=label, bet_line=line, chance=ch, best_chance=None if ch is None else round(ch, 4),
                best_tested=bool(it.get("best_tested")) and ch is not None)


@st.cache_data(ttl=1800, show_spinner=False)
def _tag_records(sport: str) -> Dict:
    try:
        import pick_records as PR
        return PR.tag_records(sport)
    except Exception:                                           # noqa: BLE001
        return {}


def picked(items: Sequence[Dict], rows: Sequence[int]) -> List[Dict]:
    return [dict(items[i]) for i in rows if 0 <= i < len(items)]


def panel(items: Sequence[Dict], key: str, date_str: str, tag: str = "platform-test", past: bool = False) -> None:
    """The log box for ticked picks. Nothing is written until the button is pressed."""
    import components as C
    if not C.is_owner():                                        # Nov 14: the public build never writes to the Bet Log
        return
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
    if any(it.get("grade") for it in items):                     # Nov 14: game lines show their grade here
        ed.insert(1, "Grade", [it.get("grade") or "" for it in items])
    lined = any(it.get("_rec") and it.get("bet_market") in ("Spread", "Total") for it in items)
    if lined:                                                   # Nov 18: alt lines (DK alt spreads) are typed here
        ed.insert(1, "Line", [float(it["bet_line"]) if it.get("_rec") and it.get("bet_market") in ("Spread", "Total")
                              and it.get("bet_line") is not None else None for it in items])
    ed = st.data_editor(ed, hide_index=True, width="stretch", key=f"{key}_prices", disabled=["Pick", "Grade"],
                        column_config={"Price": st.column_config.NumberColumn(
                            "Price you got", help="American odds from your slip; edit if it moved", format="%+d"),
                            "Line": st.column_config.NumberColumn(
                                "Line", step=0.5, format="%g", help="Spread from the team's side (−4.5, +3.5) or the "
                                "total. Change it to the line on your slip, e.g. an alternate spread; the model's "
                                "chance follows.")})
    recs = ed.to_dict("records")
    prices = [r["Price"] for r in recs]
    its = [dict(it, price=(None if p is None or p != p else p)) for it, p in zip(items, prices)]
    if lined:
        its = [relined(it, r.get("Line")) for it, r in zip(its, recs)]
        moved = [it for it, old in zip(its, items) if it.get("pick") != old.get("pick")]
        if moved:
            st.caption("At your line: " + "; ".join(
                f"{it['pick']}" + ("" if it.get("chance") is None else f" — model {it['chance']:.0%}") for it in moved))
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
    # Nov 9: the coach grades the ticket before it's logged (or placed) -- legs, parlay size, same-game stacks, the
    # chance it hits vs what it pays, and the owner's daily limits (My Coach → My limits)
    blocked = False
    try:
        import betlog as B
        import coach as CO
        chk = CO.ticket_check(its, mode, stake, pstake, podds if mode != "Singles" else None, B.list_bets(), date_str,
                              tag_records_for=_tag_records)
        box = {"A": st.success, "B": st.success, "C": st.warning, "D": st.warning, "F": st.error}[chk["grade"]]
        import components as C
        box(C.money_md(f"**Coach grade: {chk['grade']}** — {chk['headline']}"))
        icon = {"red": "🔴", "amber": "🟠", "ok": "✅"}
        for lv, msg in chk["flags"]:
            st.markdown(C.money_md(f"{icon[lv]} {msg}"))
        t = chk["today"]
        st.caption(C.money_md(f"Today so far: ${t['staked']:.0f} staked across {t['bets']} bet(s), "
                              f"{t['parlays']} parlay(s), settled {CO.usd(t['pl'])}."))
        if any(lv == "red" for lv, _ in chk["flags"]):
            blocked = not st.checkbox("I've read the red flags — I already placed it / log it anyway",
                                      key=f"{key}_override")
    except Exception as exc:                                    # noqa: BLE001 -- the coach never blocks logging by failing
        st.caption(f"(Coach check unavailable: {type(exc).__name__})")
    if st.button("📝 Log to Bet Log", type="primary", key=f"{key}_go", disabled=blocked):
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
