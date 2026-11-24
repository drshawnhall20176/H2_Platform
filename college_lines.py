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


GL_MARKETS = ("📏 Spread", "📏 Total", "📏 Moneyline")      # Best Bets' Markets filter: the game lines


def _icon(use) -> str:
    """'🎯 Single only' -> '🎯'; '⚪ No edge' / '' -> ''."""
    u = str(use or "").strip()
    return "" if not u or u.startswith("⚪") else u.split()[0]


def _agree(league: str, r: Dict) -> str:
    try:
        import game_previews as GP
        return GP.agreement(r.get("_full") or {}, league) if r.get("_full") else "—"
    except Exception:                                           # noqa: BLE001
        return "—"


def _close_gap(league: str, day: str, recs: Optional[List[Dict]]) -> Dict[str, Dict]:
    """{game: candidate pick} for the NCAAMB close-gap rule (every game of the day, started or not)."""
    if league != "NCAAMB":
        return {}
    try:
        import candidate_rules as CR
        if recs is None:
            import model_store as MS
            recs = MS.load_game_picks(league)
        start = datetime.fromisoformat(day + "T05:00:00+00:00")
        return {c["game"]: c for c in CR.picks(recs, day, now=start)}
    except Exception:                                           # noqa: BLE001
        return {}


# Nov 24 (owner: "the Pick ... is what the model is suggesting based on a model and market reconciliation correct?
# This is different than Pick in the Game Lab"): three kinds of pick share the table, so each row says which it is.
MONEY = "Money pick (model + market)"     # Money Score: the books' no-vig chance plus the model's EARNED disagreement
LINE = "Line pick (model vs market)"      # the side of the spread / total the model's own number favors
CLOSE = "Close-gap pick"                  # NCAAMB: model and market within 2 points, the model's side (tracked)
WINNER = "Winner (model's favorite)"      # the team the model alone has winning; its chance is the model's


def board_rows(league: str, day: str, rows: Sequence[Dict], recs: Optional[List[Dict]] = None) -> List[Dict]:
    """Every game's bets as rows — the Line pick, the Money pick and the Winner (one row per distinct bet) — with the
    icons the boards use on the LEFT: 💰 Money pick (tested) · 🔒 / 🎟️ / 🎯 the line pick's Use tag · ✅ the model
    and the market agree (NCAAMB: the tracked close-gap pick). Sorted by start time."""
    import game_previews as GP
    cand = _close_gap(league, day, recs)
    out: List[Dict] = []
    for r in rows:
        full = r.get("_full") or {}
        agree = _agree(league, r)
        blow = GP.blowout(league, full) if full else "—"
        last = GP._last(league, full) if full else "—"
        cg = cand.get(r.get("game"))
        seen = set()

        def add(market, pick, price, chance, icons, kind):
            key = str(pick).replace(" ML", "").replace(" moneyline", "").strip()
            if not pick or key in seen:
                return
            seen.add(key)
            ic = list(dict.fromkeys(i for i in icons if i))
            out.append({"Time": r.get("time") or "", "Game": r.get("game"), "Use": " ".join(ic), "Pick type": kind,
                        "Market": market, "Pick": pick, "Price": price, "Chance": chance,
                        "Blowout risk": blow, GP.AGREE: agree, "Last meetings": last,
                        "_kick": (r.get("_rec") or {}).get("kickoff")})

        money_same = r.get("money_pick") and r.get("best") and r.get("money_pick") == r.get("best")
        if r.get("money") and r.get("money_pick") and not money_same:
            add(r.get("money_market") or "", r["money_pick"], r.get("money_price"), r.get("money_chance"), ["💰"],
                MONEY)
        if r.get("best"):
            m = r.get("bet_market") or "Spread"
            add(m, r["best"], r.get("best_price"), r.get("best_chance"),
                [("💰" if r.get("money") and money_same else ""), ("🔒" if r.get("lock") else ""), _icon(r.get("use")),
                 ("✅" if m in ("Spread", "Moneyline") and agree.startswith("✅") else "")],
                MONEY if r.get("money") and money_same else LINE)
        if cg and cg["pick"] not in seen:
            add("Spread", cg["pick"], cg.get("price"), None, ["✅"], CLOSE)
        if r.get("winner"):
            add("Moneyline", f"{r['winner']} ML", r.get("price"), r.get("chance"),
                ["✅" if agree.startswith("✅") else ""], WINNER)
    import components as C
    return C.by_kickoff(out, lambda x: x.get("_kick") or x.get("Time"))


def plays(league: str, day: str, rows: Sequence[Dict], recs: Optional[List[Dict]] = None) -> List[Dict]:
    """The top section: only the rows carrying 💰, ✅ or a Use tag (🔒 / 🎟️ / 🎯), by start time."""
    keep = [r for r in board_rows(league, day, rows, recs)
            if any(i in r["Use"] for i in ("💰", "✅", "🔒", "🎟️", "🎯"))]
    # one ✅ per game: the spread pick, not also the moneyline
    out, games_ok = [], set()
    for r in keep:
        if r["Use"] == "✅" and r["Market"] == "Moneyline" and r["Game"] in games_ok:
            continue
        if "✅" in r["Use"]:
            games_ok.add(r["Game"])
        out.append(r)
    return out


def same_game(a: str, b: str) -> bool:
    """'Boston Celtics @ New York Knicks' vs 'BOS @ NYK' / 'Celtics @ Knicks': both teams' last words appear."""
    import re
    if not a or not b:
        return False
    a2, b2 = a.lower(), b.lower()
    if a2 == b2:
        return True
    teams = [t.strip() for t in re.split(r" @ | vs ", a2) if t.strip()]
    return len(teams) == 2 and all((t.split() or [""])[-1] in b2 for t in teams)


def gl_board(league: str, day: str, markets: Sequence[str], slot: str, game: str, slot_of=None) -> List[Dict]:
    """Best Bets' full board: the game-line rows for the selected 📏 markets, time slot and game."""
    import game_lines_table as GLT
    import pytz
    import sports
    want = {m.replace("📏 ", "") for m in markets if m in GL_MARKETS}
    if not want:
        return []
    today = datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
    rows = [dict(r) for r in GLT._rows(league, day, day < today)]
    out = [r for r in board_rows(league, day, rows) if r["Market"] in want]
    if slot and slot != "All slate":
        so = slot_of or sports.slot_of
        out = [r for r in out if so(sports.game_dt(r.get("_kick"))) == slot]
    if game and not game.startswith("All games"):
        out = [r for r in out if same_game(r["Game"], game)]
    return out


ICON_KEY = ("**Pick type:** Money pick = the model's chance reconciled with the market (the books' chance plus only "
            "the part of the model's disagreement its record has earned) at a price that pays · Line pick = the side "
            "of the spread or total the model's own number favors against the market (the Game Lab's Pick) · Winner = "
            "the team the model alone has winning, at the model's own chance · Close-gap pick = the model's side when "
            "model and market are within 2 points. **Chance** follows the pick type.  \n**Use:** 💰 Money pick — the game-line rule that has returned money in testing (1 unit each) · 🔒 / 🎟️ / 🎯 "
            "a tested Use tag on the line pick · ✅ the model and the market agree (college basketball: the close-gap "
            "rule being tracked forward — information until it earns its tag).")


def show_table(rows: Sequence[Dict]) -> None:
    import pandas as pd
    import streamlit as st
    df = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows])
    st.dataframe(df, hide_index=True, width="stretch",
                 column_config={"Price": st.column_config.NumberColumn(format="%+d"),
                                "Chance": st.column_config.NumberColumn(format="percent")})


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
        show_table(pl)
        cand = ""
        if league == "NCAAMB":
            try:
                import candidate_rules as CR
                cand = CR.status_line(league, date_str)
            except Exception:                                   # noqa: BLE001
                cand = ""
        st.caption(ICON_KEY + ("  \n" + cand if cand else ""))
    else:
        st.caption("No 💰 or ✅ game lines for this date yet — the full board below has every game.")
    with st.expander(f"🧾 Full game board ({len(rows)} games) — tick any line to log it", expanded=False):
        GLT.render(rows, f"bb_glt_{league}", date_str, past=date_str < today)
    st.divider()
