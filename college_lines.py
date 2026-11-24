"""
college_lines.py — the game-line plays at the top of Best Bets for college sports (Nov 24).

Owner: "if you take a look through NCAAMB we have an interesting issue because most times Best Bets is empty. I think
the problem is that sportsbooks are not posting player props." Measured Nov 24 (research/ncaamb_props_supply.py): on
Nov 16-24 the sportsbooks priced college basketball props on 0-5 games a day out of 22-85 (FanDuel only); everything
else was PrizePicks / Underdog pick'em lines, which have tested as coin flips (51-52%), so the props board filters
them out and the page reads empty. College basketball is a game-line sport for us, so Best Bets now leads with the
day's game-line plays — 💰 Money picks (tested) and the ✅ close-gap games (tracked forward) — and says how many games
the books priced props on.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

COLLEGE = ("NCAAMB", "NCAAF")


def prop_supply(plays: Sequence[Dict], n_games: int) -> str:
    """'Sportsbooks priced props on 2 of 44 games today (FanDuel); the rest are pick'em-app lines.'"""
    import odds_api as O
    priced = [p for p in plays or [] if p.get("PriceSource") == "book" and not p.get("Pickem")]
    games = {p.get("Game") for p in priced if p.get("Game")}
    books = sorted({O.book_label(p.get("RealPriceBook")) for p in priced if p.get("RealPriceBook")})
    return (f"Sportsbooks priced player props on **{len(games)} of {n_games}** games today"
            + (f" ({', '.join(books)})" if books else "")
            + ". The rest are pick'em-app lines (PrizePicks, Underdog), which have tested as coin flips — so the "
              "edge in this sport is on the game lines below.")


def plays(league: str, day: str, rows: Sequence[Dict], recs: Optional[List[Dict]] = None) -> List[Dict]:
    """Today's actionable game lines, by start time: 💰 Money picks, then the ✅ close-gap games (NCAAMB)."""
    import components as C
    import game_previews as GP
    by_game = {r.get("game"): r for r in rows}
    out: List[Dict] = []
    for r in rows:
        if r.get("money") and r.get("money_pick"):
            out.append({"Time": r.get("time") or "", "Game": r.get("game"), "Play": r["money_pick"],
                        "Price": r.get("money_price"), "Why": "💰 Money pick — the tested rule",
                        "Blowout risk": GP.blowout(league, r.get("_full") or {}) if r.get("_full") else "—",
                        "Last meetings": GP._last(league, r.get("_full") or {})})
    if league == "NCAAMB":
        try:
            import candidate_rules as CR
            if recs is None:
                import model_store as MS
                recs = MS.load_game_picks(league)
            start = datetime.fromisoformat(day + "T05:00:00+00:00")   # every game of the day, started or not
            for c in CR.picks(recs, day, now=start):
                r = by_game.get(c["game"]) or {}
                out.append({"Time": c.get("time") or r.get("time") or "", "Game": c["game"], "Play": c["pick"],
                            "Price": c.get("price"),
                            "Why": f"✅ Model & market within {c['edge']:.1f} pts — tracked rule, not yet tested",
                            "Blowout risk": GP.blowout(league, r.get("_full") or {}) if r.get("_full") else "—",
                            "Last meetings": GP._last(league, r.get("_full") or {}) if r.get("_full") else "—"})
        except Exception:                                       # noqa: BLE001
            pass
    return C.by_kickoff(out, lambda x: x.get("Time"))


def render(league: str, date_str: str, board_plays: Sequence[Dict]) -> None:
    """The section at the top of Best Bets for a college sport."""
    import pandas as pd
    import pytz
    import streamlit as st
    import components as C
    import game_lines_table as GLT
    if league not in COLLEGE:
        return
    today = datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
    try:
        rows = [dict(r) for r in GLT._rows(league, date_str, date_str < today)]
    except Exception:                                           # noqa: BLE001
        rows = []
    C.section_header("📏", "Game-line plays — where the college edge is")
    st.caption(prop_supply(board_plays, len(rows)))
    pl = plays(league, date_str, rows)
    if pl:
        st.dataframe(pd.DataFrame(pl), hide_index=True, width="stretch",
                     column_config={"Price": st.column_config.NumberColumn(format="%+d")})
        cand = ""
        if league == "NCAAMB":
            try:
                import candidate_rules as CR
                cand = CR.status_line(league, date_str)
            except Exception:                                   # noqa: BLE001
                cand = ""
        st.caption("💰 = the game-line rule that has returned money in testing (1 unit each). ✅ = the close-gap "
                   "rule being tracked forward — information until it earns its tag." + ("  \n" + cand if cand else ""))
    else:
        st.caption("No 💰 or ✅ game lines for this date yet — the full board below has every game.")
    with st.expander(f"🧾 Full game board ({len(rows)} games) — tick any line to log it", expanded=False):
        GLT.render(rows, f"bb_glt_{league}", date_str, past=date_str < today)
    st.divider()
