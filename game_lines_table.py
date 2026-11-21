"""
game_lines_table.py — the "Winner · Pick · Money" game-lines board, shared by the sport desk (Home) and every Game Lab
(Nov 20).

Owner: "study and enhance the game lab based on how we are trending the site. Also ... game lab is one of those pieces
of the site that has no logging capability." The Game Labs predated the week's work: no Money Score, no 💰 or stake, no
Winner / Pick / Money split, no hit-and-miss pies, and (NFL, college football) no tick-to-log at all -- the hoops labs'
tick boxes sat at the far right of a wide preview table. This is the sport desk's game-lines board as one component:

  * the three measures per game -- Winner (who wins), Pick (the model's side of the line), Money (what the price pays:
    money_score.py) -- with 💰 and a stake (props_engine.stake_units, inside the day's 10u budget);
  * important columns left, detail right (owner, Nov 20: "investor friendly");
  * a tick box beside each of the three bets (log_ui.tick_grid) and the log box (log_ui.panel);
  * on past days, Final and the three results, with a pie each (components.hit_miss_pair) and a hits / misses filter.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import pandas as pd
import streamlit as st

TICKS = ["✓ Money", "✓ Pick", "✓ Winner"]
ORDER = ["Time", "Sport", "Game", "Final", "Money result", "Pick result", "Winner result",
         "✓ Money", "Money pick", "Money score", "✓ Pick", "Pick", "Use", "Chance", "Price", "Value",
         "✓ Winner", "Likely winner", "Record (30d)", "Backtest cover", "Spread", "Total", "Model",
         "Spread move", "Weather", "League"]
MONEY_HELP = ("What the price pays: expected return per $1 at the best price, from a chance that trusts the model only "
              "as far as its record against the books has earned (refit every morning). 💰 = college basketball, +4% "
              "to +12% with a 40%+ chance (what made money in testing).")


def money_pick_text(r: Dict) -> str:
    import props_engine as PE
    if not r.get("money_pick"):
        return "—"
    txt = ("💰 " if r.get("money") else "") + r["money_pick"]
    if r.get("money_price") is not None:
        txt += f" {float(r['money_price']):+.0f}"
    if r.get("money"):
        u = PE.stake_units(r.get("money_chance"), r.get("money_price"))
        if u:
            txt += f" · {u:g}u"
    return txt


def line_items(rows: Sequence[Dict], ticks) -> List[Dict]:
    """[(row, tick column)] from log_ui.tick_grid -> log items: the Pick, the Likely winner's moneyline, or the Money
    pick (any side, at its own line and price)."""
    import hoops_games_page as HG
    import pick_records as PR
    out = []
    for i, col in ticks:
        if not 0 <= i < len(rows):
            continue
        r = rows[i]
        full = r.get("_full") or {}
        if col == "✓ Pick" and r.get("bet_market") and r.get("best"):
            out.append(dict(r, price=r.get("bet_price"), pick=r["best"],
                            grade=("tracking only" if r.get("status") else PR.grade(r))))
        elif col == "✓ Winner" and full:
            it = HG.side_item(full, "Moneyline", "home" if r.get("winner") == full.get("home") else "away",
                              price=r.get("price"))
            if it:
                out.append(it)
        elif col == "✓ Money" and full and r.get("money_market"):
            it = HG.side_item(full, r["money_market"], r.get("money_side"), line=r.get("money_line"),
                              price=r.get("money_price"))
            if it:
                out.append(dict(it, pick=r.get("money_pick") or it["pick"],
                                note="💰 Money pick" if r.get("money") else "Money Score pick"))
    return out


def frame(rows: Sequence[Dict], past: bool, show_sport: bool = False) -> pd.DataFrame:
    """The board as a table, columns in ORDER; empty columns dropped."""
    import pick_records as PR
    import todays_best as TB
    df = pd.DataFrame([{
        "Time": r.get("time") or "", "Sport": r.get("sport"), "Game": r.get("game"),
        "Final": r.get("final") or "—",
        "Money result": TB.RESULT_ICON.get(r.get("money_result"), "—"),
        "Pick result": TB.RESULT_ICON.get(r.get("best_result"), "—"),
        "Winner result": TB.RESULT_ICON.get(r.get("winner_result"), "—"),
        "✓ Money": False, "Money pick": money_pick_text(r), "Money score": r.get("money_score"),
        "✓ Pick": False, "Pick": r.get("best") or "—", "Use": PR.lean_use(r),
        "Chance": r.get("best_chance") if r.get("best_tested") else None,
        "Price": (f"{float(r['best_price']):+.0f}" if r.get("best_tested") and r.get("best_price") is not None else ""),
        "Value": r.get("best_value") if r.get("best_tested") else None,
        "✓ Winner": False,
        "Likely winner": (f"{r['winner']} ({r['chance']:.0%})" + (f" {float(r['price']):+.0f}"
                                                                    if r.get("price") is not None else ""))
        if r.get("winner") else "—",
        "Record (30d)": r.get("lean_record") or "—",
        "Backtest cover": r.get("backtest") if not r.get("best_tested") else None,
        "Spread": r.get("spread_txt") or "", "Total": r.get("total_txt") or "",
        "Model": r.get("model_txt") or r.get("lean_detail") or "", "League": r.get("league")} for r in rows])
    if df.empty:
        return df
    drop = [] if past else ["Final", "Money result", "Pick result", "Winner result"]
    if not show_sport:
        drop.append("Sport")
    for c in ("Chance", "Price", "Value", "Backtest cover", "Money score", "Spread", "Total", "Model"):
        if c in df and not df[c].replace("", None).notna().any():
            drop.append(c)
    df = df.drop(columns=[c for c in drop if c in df.columns])
    return df[[c for c in ORDER if c in df.columns] + [c for c in df.columns if c not in ORDER]]


def render(rows: Sequence[Dict], key: str, date_str: str, past: bool, show_sport: bool = False,
           title: Optional[str] = None) -> None:
    """The whole board: the Show choice, pies + a hits / misses filter on past days, the tick table and the log box."""
    import components as C
    import log_ui as LU
    import pick_records as PR
    rows = list(rows or [])
    if title:
        st.markdown(f"##### {title}")
    if not rows:
        st.caption("No games with a model read for this date.")
        return
    try:
        PR.annotate_leans(rows, lambda lg: PR.lean_records(lg))
    except Exception:                                           # noqa: BLE001
        pass
    if not past:                                                # Nov 21: the game-line 💰 as shown (pick_ledger.py)
        try:
            import pick_ledger as PL
            PL.record_games(date_str, rows)
        except Exception:                                       # noqa: BLE001
            pass
    show = st.radio("Show", ["💰 Money picks", "🔒 Locks only", "All games"], index=2, horizontal=True,
                    key=f"{key}_show", label_visibility="collapsed")
    if show.startswith("💰"):
        rows = [r for r in rows if r.get("money")]
    elif show.startswith("🔒"):
        rows = [r for r in rows if r.get("lock")]
    rows = sorted(rows, key=lambda r: (C._kick_dt(r.get("time")) is None, str(C._kick_dt(r.get("time")) or ""),
                                       not r.get("money")))
    if past and rows:
        import money_score as MSC
        proxy = [{"pick": r.get("best_result"),
                  "pick_chance": r.get("best_chance") if r.get("best_tested") else r.get("backtest"),
                  "winner": r.get("winner_result"), "winner_chance": r.get("chance"),
                  "money": r.get("money_result") if (r.get("money_score") or -1) >= MSC.BAND[0] else None,
                  "money_chance": r.get("money_chance")} for r in rows]
        C.hit_miss_pair([("Money result (score +4%+)", proxy, "money", "money_chance"),
                         ("Pick result", proxy, "pick", "pick_chance"),
                         ("Winner result", proxy, "winner", "winner_chance")],
                        key=f"{key}_hm", title="How the money picks, the picks and the likely winners did")
        _, rows = C.show_filter(proxy, "money", key=f"{key}_hmshow", apply_to=rows,
                                by={"Money result": "money", "Pick result": "pick", "Winner result": "winner"})
    if not rows:
        st.caption({"💰 Money picks": "No 💰 game lines for this date — choose All games to see every game.",
                    "🔒 Locks only": "No 🔒 game lines for this date — choose All games to see every game."}
                   .get(show, "Nothing to show."))
        return
    df = frame(rows, past, show_sport)
    if C.is_owner() and not past:
        st.caption("☑️ Tick **Money**, **Pick** or **Winner** on any row to log that bet — each box sits beside what "
                   "it bets on.")
    ticks = LU.tick_grid(df, TICKS, key=f"{key}_ticks", hide_index=True, width="stretch",
                         column_config={"Chance": st.column_config.NumberColumn(format="percent"),
                                        "Value": st.column_config.NumberColumn(format="percent"),
                                        "Backtest cover": st.column_config.NumberColumn(format="percent"),
                                        "Money score": st.column_config.NumberColumn(format="percent",
                                                                                     help=MONEY_HELP)})
    LU.panel(line_items(rows, ticks), f"{key}_log", date_str, past=past)
    st.caption("**Money** = what the price pays (the Money Score); **Pick** = the model's side of the line; **Winner** = "
               "who the model has winning. They can point at different sides of the same game — in college basketball "
               "the Money pick often takes the other side of a big model lean, because those leans have lost. Pick one "
               "per game. Stakes are a quarter of the Kelly stake, scaled so the day's 💰 picks total 10u at most.")


@st.cache_data(ttl=300, show_spinner=False, max_entries=16)
def _rows(league: str, day: str, past: bool) -> List[Dict]:
    import todays_best as TB
    return TB.winner_rows(day, leagues=[league], past=past)


def lab_section(league: str, key: Optional[str] = None, day=None) -> None:
    """The board at the top of a Game Lab: its own date (default today, New York), the league's games that day."""
    from datetime import datetime
    import pytz
    import components as C
    key = key or f"glt_{league}"
    today = datetime.now(pytz.timezone("US/Eastern")).date()
    C.section_header("🧾", "The board: Money · Pick · Winner")
    if day is None:
        day = st.date_input("Board date", today, key=f"{key}_date", format="MM/DD/YYYY")
    try:
        rows = [dict(r) for r in _rows(league, day.strftime("%Y-%m-%d"), day < today)]
    except Exception as exc:                                    # noqa: BLE001 -- the rest of the lab still renders
        st.caption(f"The board is unavailable right now ({type(exc).__name__}).")
        return
    render(rows, key, day.strftime("%Y-%m-%d"), past=day < today)
