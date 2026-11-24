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

TICKS = ["✓ Pick", "✓ Money", "✓ Winner"]
BLOW, AGREE = "Blowout risk", "Model & market agree?"
# Nov 24 (owner: "Line pick would be the first selectable item, not money pick"): the Line pick block first, with the
# spread move beside it (the tested tiebreaker), then the Money pick, then the Winner
ORDER = ["Time", "Sport", "Game", "Bet?", "Final", "Pick result", "Money result", "Winner result",
         "✓ Pick", "Pick", "Use", "Spread move", "Chance", "Price", "Value", BLOW, AGREE,
         "✓ Money", "Money pick", "Money score",
         "✓ Winner", "Likely winner", "Record (30d)", "Backtest cover", "Last meetings", "Spread", "Total", "Model",
         "Weather", "League"]
# Nov 23 (owner: members couldn't "identify and correlate the items"): what the members see. The board keeps its short
# internal names; display() renames for the screen and back() maps a ticked column back.
DISPLAY = {
    "✓ Money": "✓ Money pick", "Money pick": "Money pick (best value)", "Money score": "Money score (return per $1)",
    "✓ Pick": "✓ Line pick", "Pick": "Line pick (model favors)", "Use": "Line pick: use",
    "Chance": "Line pick: chance", "Price": "Line pick: price", "Value": "Line pick: value",
    "✓ Winner": "✓ Winner pick", "Likely winner": "Winner pick (chance, price)",
    "Record (30d)": "Line picks like it: last 30 days", "Backtest cover": "Line picks like it: backtest",
    "Spread": "Market spread", "Total": "Market total", "Model": "Model",
    "Money result": "Money pick result", "Pick result": "Line pick result", "Winner result": "Winner pick result",
}
SHOW = {"💰 Money picks": "💰 Only games with a Money pick", "🔒 Locks only": "🔒 Only games with a Lock",
        "All games": "All games", "All playable": "All games"}
LEGEND = "\n".join("- " + x for x in [
    "Each game can carry **three different bets**, each with its own tick box right before it:",
    "&nbsp;&nbsp;**Line pick** — the side of the **spread or total** the model favors against the market. On a 🧪 "
    "Tracking game it is the tracked rule's side — the box to tick.",
    "&nbsp;&nbsp;**💰 Money pick** — the bet whose **price** pays best for its chance (the Money score = expected return "
    "per $1). 💰 marks one that meets the tested rule.",
    "&nbsp;&nbsp;**Winner pick** — the team the model has **winning outright**, with its chance and moneyline.",
    "They can point at **different sides of the same game** (the Money pick often takes the other side of a big model "
    "lean, because those leans have lost in testing). **Pick one per game.**",
    "**Line pick: use** — 🔒 Most probable · 🎟️ Parlay + Single · 🎯 Single only · ⚪ No edge (information, not a bet).",
    "**Line picks like it** — how the model's favored side has done on leans of this kind and size: last 30 days, and in the "
    "long-run backtest. 52.4% breaks even at −110.",
    "**Model** = our projection; **Market** = the sportsbooks' line. **Market spread / Market total** — the books' lines; **Model** — the model's own score.",
    "**Game** is listed **Away @ Home**.",
    "**Blowout risk** — the chance the game is decided by 15+ points (basketball), 14+ (football) or 3+ goals "
    "(hockey), from the market's spread: 🟥 60%+ · 🟨 35–60% · 🟩 under 35%.",
    "**Model & market agree?** — ✅ same winner and close (2 points; hockey: win chances within 4) · 🟨 same winner, "
    "further apart · ⚠️ the model has the other team. It has meant something only in college basketball so far.",
    "**Bet?** — 🃏 Bet = the row carries a tag from a rule that has made money in testing (and which pick it is) · "
    "🧪 Tracking = the college basketball ✅ close-gap rule, being tested forward · Info only = no tested edge: "
    "what the model thinks, not a bet.",
    "**Last meetings** — how the two teams' games against each other went over the last year. Context only: past "
    "meetings tested as adding nothing to the chances (Nov 24).",
    "Stakes: a flat 1u per 💰 pick until the edge is proven, scaled so a day's 💰 picks total 5u at most.",
])


def display(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns=DISPLAY)


def config(cfg: Dict) -> Dict:
    return {DISPLAY.get(k, k): v for k, v in cfg.items()}


def back(ticks) -> List[tuple]:
    rev = {v: k for k, v in DISPLAY.items()}
    return [(i, rev.get(c, c)) for i, c in ticks]


TICK_HELP = {"✓ Money pick": "Log the Money pick (the next column)", "✓ Line pick": "Log the Line pick (the next "
             "column)", "✓ Winner pick": "Log the Winner pick's moneyline (the next column)"}
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


def extras(r: Dict) -> Dict:
    """Nov 24 (owner: every table like the NCAAMB Game Lab's): the game's blowout risk and whether the model and the
    market agree -- the same two columns the Game Lab tables carry, from the board row's full game record."""
    import game_previews as GP
    p = r.get("_full") or {}
    lg = r.get("league") or r.get("sport") or ""
    try:
        return {BLOW: GP.blowout(lg, p) if p else "—", AGREE: GP.agreement(p, lg) if p else "—",
                GP.LAST: GP._last(lg, p) if p else "—"}
    except Exception:                                           # noqa: BLE001
        return {BLOW: "—", AGREE: "—", "Last meetings": "—"}


def bet(r: Dict) -> str:
    """Nov 24 (owner): which of the row's picks, if any, is a bet. The 💰 flag already respects a paused rule."""
    import game_previews as GP
    import todays_best as TB
    lg = r.get("league") or r.get("sport") or ""
    parts = []
    if r.get("money"):
        parts.append("💰 Money pick")
    if r.get("lock") or r.get("use") in TB.PLAYABLE:
        parts.append("Line pick")
    if parts:
        return f"{GP.BET_YES}: " + " + ".join(parts)
    try:
        ag = GP.agreement(r.get("_full") or {}, lg) if r.get("_full") else ""
    except Exception:                                           # noqa: BLE001
        ag = ""
    return GP.game_bet(lg, False, False, ag)


def frame(rows: Sequence[Dict], past: bool, show_sport: bool = False) -> pd.DataFrame:
    """The board as a table, columns in ORDER; empty columns dropped."""
    import pick_records as PR
    import todays_best as TB
    df = pd.DataFrame([{
        "Time": r.get("time") or "", "Sport": r.get("sport"), "Game": r.get("game"), "Bet?": bet(r),
        "Final": r.get("final") or "—", **extras(r),
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
    show = st.radio("Which games to show", ["💰 Money picks", "🔒 Locks only", "All games"], index=2, horizontal=True,
                    key=f"{key}_show", format_func=lambda o: SHOW.get(o, o))
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
        C.hit_miss_pair([("Money pick result (score +4%+)", proxy, "money", "money_chance"),
                         ("Line pick result", proxy, "pick", "pick_chance"),
                         ("Winner pick result", proxy, "winner", "winner_chance")],
                        key=f"{key}_hm", title="How the Money picks, Line picks and Winner picks did")
        _, rows = C.show_filter(proxy, "money", key=f"{key}_hmshow", apply_to=rows,
                                by={"Money pick result": "money", "Line pick result": "pick",
                                    "Winner pick result": "winner"})
    if not rows:
        st.caption({"💰 Money picks": "No 💰 game lines for this date — choose All games to see every game.",
                    "🔒 Locks only": "No 🔒 game lines for this date — choose All games to see every game."}
                   .get(show, "Nothing to show."))
        return
    df = frame(rows, past, show_sport)
    import game_previews as _GP
    df, _note = _GP.collapse_use(df)                           # Nov 23: a Use column that's ⚪ on every row goes
    if _note:
        st.caption(_note)
    with st.expander("📖 How to read this board — the three picks and every column", expanded=False):
        st.markdown(LEGEND)
    if C.is_owner() and not past:
        st.caption("☑️ Tick **Money pick**, **Line pick** or **Winner pick** on any row to log that bet — each box sits "
                   "right before the bet it logs.")
    ticks = back(LU.tick_grid(display(df), [DISPLAY[t] for t in TICKS], key=f"{key}_ticks", hide_index=True,
                              width="stretch", tick_help=TICK_HELP,
                              column_config=config({"Chance": st.column_config.NumberColumn(format="percent"),
                                                    "Value": st.column_config.NumberColumn(format="percent"),
                                                    "Backtest cover": st.column_config.NumberColumn(format="percent"),
                                                    "Money score": st.column_config.NumberColumn(format="percent",
                                                                                                 help=MONEY_HELP)})))
    LU.panel(line_items(rows, ticks), f"{key}_log", date_str, past=past)


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
    C.section_header("🧾", "Game board: 💰 Money pick · Line pick · Winner pick")
    if day is None:
        day = st.date_input("Board date", today, key=f"{key}_date", format="MM/DD/YYYY")
    try:
        rows = [dict(r) for r in _rows(league, day.strftime("%Y-%m-%d"), day < today)]
    except Exception as exc:                                    # noqa: BLE001 -- the rest of the lab still renders
        st.caption(f"The board is unavailable right now ({type(exc).__name__}).")
        return
    render(rows, key, day.strftime("%Y-%m-%d"), past=day < today)
