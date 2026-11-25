"""
screener.py — stack filters over every playable pick on tonight's boards (Nov 25, PropSeason scrub item 4).

PropSeason's props board has a "stack filters" screener (matchup grade, our %, L10 / L5 hit rates, streak). Ours runs
over the same slim rows Today's search reads (todays_best.KEY_ALL: every playable pick, not just the top ones) and
shows each pick's Bet? verdict beside it, so a filter can never turn an untested or below-break-even pick into a bet.
Sorted by start time (the owner's standing rule), then our chance.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def hit_rate(values: Sequence, line, side: str, n: int = 10) -> Optional[float]:
    """Share of his last n games that cleared tonight's line on the pick's side."""
    import player_card as PC
    ln = _f(line)
    vals = [v for v in list(values or [])[:n] if _f(v) is not None]
    if ln is None or not vals:
        return None
    return sum(1 for v in vals if PC.cleared(float(v), ln, side or "Over")) / len(vals)


def enrich(r: Dict) -> Dict:
    """The fields the filters read: hit10, hit5, streak, matchup tone."""
    import player_card as PC
    import today_visual as TV
    vals, line, side = r.get("values") or [], r.get("line"), r.get("side") or "Over"
    mc = PC.matchup_chip(r.get("factor"), r.get("slot"))
    return dict(r, _hit10=hit_rate(vals, line, side, 10), _hit5=hit_rate(vals, line, side, 5),
                _streak=TV.streak(vals, line, side), _match=(mc or {}).get("tone"), _match_text=(mc or {}).get("text"))


def apply(rows: Iterable[Dict], min_chance: float = 0.0, min_hit10: float = 0.0, min_streak: int = 0,
          soft_only: bool = False, sides: Optional[Sequence[str]] = None, markets: Optional[Sequence[str]] = None,
          bets_only: bool = False, bet_of=None) -> List[Dict]:
    """Every filter must pass (a missing number fails a filter that's switched on)."""
    out = []
    for r in rows or []:
        e = r if "_hit10" in r else enrich(r)
        ch = _f(e.get("chance"))
        if min_chance and (ch is None or ch < min_chance):
            continue
        if min_hit10 and (e["_hit10"] is None or e["_hit10"] < min_hit10):
            continue
        if min_streak and e["_streak"] < min_streak:
            continue
        if soft_only and e["_match"] != "soft":
            continue
        if sides and (e.get("side") or "Over") not in sides:
            continue
        if markets and e.get("market") not in markets:
            continue
        if bets_only and bet_of is not None and not str(bet_of(e)).startswith("🃏"):
            continue
        out.append(e)
    return out


def _pct(x) -> str:
    return "—" if x is None else f"{x:.0%}"


def table(rows: Iterable[Dict], bet_of, parse_time=None) -> List[Dict]:
    """Display rows, earliest start first, then the highest chance."""
    def key(r):
        t = None
        if parse_time is not None:
            try:
                t = parse_time(r.get("time"))
            except Exception:                                   # noqa: BLE001
                t = None
        return (t is None, str(t or r.get("time") or ""), -(_f(r.get("chance")) or 0))
    out = []
    for r in sorted(rows, key=key):
        price = r.get("price")
        out.append({"Time": r.get("time") or "", "Sport": r.get("sport") or "", "Pick": r.get("pick") or "",
                    "Bet?": bet_of(r), "Our chance": _f(r.get("chance")),
                    "Price": "" if _f(price) is None else f"{_f(price):+.0f}",
                    "Last 10": _pct(r.get("_hit10")), "Last 5": _pct(r.get("_hit5")),
                    "Streak": r.get("_streak") or 0, "Matchup": r.get("_match_text") or "—",
                    "Game": r.get("game") or ""})
    return out


def bet_for(r: Dict) -> str:
    import game_previews as GP
    use = ("💰 " if r.get("money") else "") + ("🔒 " if r.get("lock") else "") + str(r.get("use") or "")
    return GP.prop_bet(r.get("sport") or "", use, r)


def render(rows: Sequence[Dict], key: str = "scr", parse_time=None) -> None:
    """The filter bar and the matching picks."""
    import pandas as pd
    import streamlit as st
    rows = [enrich(r) for r in rows or [] if r.get("player") or r.get("Player")]
    if not rows:
        st.caption("No playable picks saved for this day yet — the screener fills in as the boards are built.")
        return
    c1, c2, c3, c4 = st.columns(4)
    mc = c1.slider("Our chance ≥", 0, 90, 0, 5, key=f"{key}_ch", format="%d%%")
    mh = c2.slider("Last 10 hit rate ≥", 0, 100, 0, 10, key=f"{key}_h10", format="%d%%")
    ms = c3.slider("Streak ≥ (games in a row)", 0, 10, 0, 1, key=f"{key}_st")
    soft = c4.toggle("Soft matchup only", key=f"{key}_soft",
                     help="Tonight's defense allows his position 3%+ more than average (the matchup chip).")
    d1, d2, d3 = st.columns([1, 2, 1])
    sides = d1.pills("Side", ["Over", "Under"], selection_mode="multi", key=f"{key}_side")
    markets = d2.multiselect("Markets", sorted({r.get("market") for r in rows if r.get("market")}), key=f"{key}_mk",
                             placeholder="All markets")
    bets = d3.toggle("🃏 Bets only", key=f"{key}_bet", help="Only picks whose Bet? verdict is 🃏 Bet.")
    got = apply(rows, mc / 100, mh / 100, ms, soft, sides or None, markets or None, bets, bet_for)
    st.caption(f"{len(got)} of {len(rows)} playable picks match. Hit rates and streaks are against tonight's line; "
               "Bet? is the model's verdict and doesn't change with the filters.")
    if got:
        st.dataframe(pd.DataFrame(table(got, bet_for, parse_time)), hide_index=True, width="stretch",
                     column_config={"Our chance": st.column_config.NumberColumn(format="percent")})
