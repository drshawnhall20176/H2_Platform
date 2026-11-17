"""
model_view.py -- one source of truth for player numbers across the site (Nov 15).

Owner: "if the model cannot agree or point in the same direction, then I have a broken system ... see if anything
else in this system is 'an old tool' running in this new system and if so fix it."

Several pages grew up before the props model did and still compute their own player numbers -- the Hot Hand Engines
(recent average x a raw matchup factor), the Matchup Labs, QB Labs, Anytime TD Engines, Player Lines. Measured on
Nov 15's NFL slate, the Hot Hand number and the model's projection picked the same side of the book's line only 75% of
the time, and the splits fell exactly where the model's tested adjustments matter (a hot streak regressed toward the
player's group, injuries and roles, weather, game script, daily calibration).

This module puts THE MODEL'S read beside any page's own numbers: the book's line, the model's projection, its call
(side of the line), its chance and the site-wide Use symbol, all from the day's saved board reads (the same reads
Today's best, Best Bets and My Coach use). A page's own number stays only as the explanation ("form x matchup"),
never as a second answer. `agrees` flags where the page's own number would have said the other side.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable, Dict, Iterable, List, Optional, Tuple

# page market label -> the board's market name
ALIASES = {
    "rush yards": "Rush Yards", "rushing yards": "Rush Yards", "rush yds": "Rush Yards",
    "receptions": "Receptions", "rec": "Receptions",
    "receiving yards": "Receiving Yards", "rec yards": "Receiving Yards", "rec yds": "Receiving Yards",
    "pass yards": "Pass Yards", "passing yards": "Pass Yards", "pass yds": "Pass Yards",
    "pass tds": "Passing TDs", "passing tds": "Passing TDs", "pass td": "Passing TDs",
    "interceptions": "Interceptions", "ints": "Interceptions",
    "pass attempts": "Pass Attempts", "pass completions": "Pass Completions", "completions": "Pass Completions",
    "rush attempts": "Rush Attempts", "carries": "Rush Attempts",
    "rush + rec yards": "Rush + Rec Yards", "rush+rec yards": "Rush + Rec Yards",
    "anytime td": "Anytime TD", "td": "Anytime TD",
    "points": "Points", "pts": "Points", "rebounds": "Rebounds", "reb": "Rebounds", "assists": "Assists",
    "ast": "Assists", "threes": "Threes Made", "threes made": "Threes Made", "3pm": "Threes Made", "fg3m": "Threes Made",
    "pra": "PRA", "pts+reb+ast": "PRA", "pa": "PA", "pts+ast": "PA", "pr": "PR", "pts+reb": "PR", "ra": "RA",
    "reb+ast": "RA", "pts+blk": "PB", "steals": "Steals", "blocks": "Blocks",
    "shots on goal": "Shots on Goal", "sog": "Shots on Goal", "goals": "Goals", "saves": "Saves",
}
_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?")


def norm_name(name) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    s = _SUFFIX.sub("", s.replace(".", " ").replace("'", "").replace("-", " "))
    return " ".join(s.split())


def market_of(label) -> Optional[str]:
    return ALIASES.get(str(label or "").strip().lower(), str(label or "").strip() or None)


def latest_reads(sport: str, day: str, snaps: Optional[Iterable[Dict]] = None) -> Dict[Tuple[str, str], Dict]:
    """{(normalized player, market): the newest saved board read} for one sport and day."""
    if snaps is None:
        try:
            import model_store as MS
            snaps = MS.load_snapshots(sport, [day])
        except Exception:                                       # noqa: BLE001
            snaps = []
    out: Dict[Tuple[str, str], Dict] = {}
    for s in snaps or []:
        if s.get("line") is None or s.get("projection") is None:
            continue
        k = (norm_name(s.get("player")), s.get("market"))
        if k not in out or str(s.get("ts") or "") > str(out[k].get("ts") or ""):
            out[k] = s
    return out


TOSS_UP = 0.52     # under this the model has no side: a coin flip is shown as one, not dressed up as a call


def call(read: Optional[Dict]) -> Dict:
    """The model's call on one read, as table fields: the side it thinks MORE LIKELY and that chance. (A saved read's
    side is the side with the better price-adjusted value, which on a Pass can be the less likely one -- e.g. Over
    at 43% because the Under costs -170. Research pages show the likelier side so the projection and the call
    never point opposite ways.) Under 52% either way it says "Toss-up"."""
    if not read:
        return {"Line": None, "Model proj": None, "Model call": "no line posted", "Chance": None, "Use": "",
                "_side": None}
    line, side, proj = float(read["line"]), read.get("side"), float(read["projection"])
    if side == "Yes":
        side = "Over"
    if side not in ("Over", "Under"):
        side = "Over" if proj > line else "Under"
    ch = read.get("chance")
    use = read.get("use_tag") or ""
    if ch is not None and float(ch) < 0.5:
        side, ch, use = ("Under" if side == "Over" else "Over"), 1 - float(ch), "⚪ No edge"
    if ch is not None and float(ch) < TOSS_UP:
        return {"Line": line, "Model proj": proj, "Model call": f"Toss-up at {line:g}", "Chance": float(ch),
                "Use": "⚪ No edge", "_side": None}
    return {"Line": line, "Model proj": proj, "Model call": f"{side} {line:g}", "Chance": ch, "Use": use,
            "_side": side}


def attach(rows: List[Dict], reads: Dict[Tuple[str, str], Dict], player_key: str = "Player",
           market_key: str = "Market", own_key: Optional[str] = None, market: Optional[str] = None) -> List[Dict]:
    """Each row gets the model's call (Line, Model proj, Model call, Chance, Use). With `own_key` (the page's own
    number for the same stat), "Agrees" says whether that number sits on the model's side of the line."""
    out = []
    for r in rows:
        mk = market or market_of(r.get(market_key))
        c = call(reads.get((norm_name(r.get(player_key)), mk)))
        row = dict(r, **{k: v for k, v in c.items() if not k.startswith("_")})
        if own_key is not None:
            own = r.get(own_key)
            if c["_side"] is None or own is None:
                row["Agrees"] = ""
            else:
                own_side = "Over" if float(own) > c["Line"] else "Under"
                row["Agrees"] = "✅" if own_side == c["_side"] else "⚠️ model says " + c["_side"]
        out.append(row)
    return out


def agreement(rows: List[Dict]) -> Tuple[int, int]:
    """(agree, compared) over attached rows."""
    got = [r.get("Agrees") for r in rows if r.get("Agrees")]
    return sum(1 for a in got if a == "✅"), len(got)


def cached_reads(sport: str, day: str) -> Dict[Tuple[str, str], Dict]:
    """latest_reads behind Streamlit's cache (5 minutes) when running in a page."""
    try:
        import streamlit as st
    except Exception:                                           # noqa: BLE001
        return latest_reads(sport, day)
    return _cached(sport, day)


try:
    import streamlit as _st

    @_st.cache_data(ttl=300, show_spinner=False)
    def _cached(sport: str, day: str):
        return latest_reads(sport, day)
except Exception:                                               # noqa: BLE001
    def _cached(sport: str, day: str):                          # type: ignore
        return latest_reads(sport, day)


EXPLAIN = ("**Model** columns are the platform's one model — the same read Today's best, Best Bets and My Coach use "
           "(recent form pulled toward the player's position group, injuries and roles, weather, game script, and "
           "daily calibration against results). This page's own numbers are kept as the explanation of WHY the "
           "projection moved; where they'd point the other way from the model, ⚠️ says so — go with the model.")


def player_calls(reads: Dict[Tuple[str, str], Dict], player) -> List[Dict]:
    """Every market the model has a read on for one player, as table rows (highest chance first)."""
    who = norm_name(player)
    out = [dict({"Market": mk}, **{k: v for k, v in call(r).items() if not k.startswith("_")})
           for (p, mk), r in reads.items() if p == who]
    return sorted(out, key=lambda r: -(r.get("Chance") or 0))


def td_yes(read: Optional[Dict]) -> Optional[float]:
    """The model's chance a player scores (Anytime TD reads store the chance of the side they picked)."""
    if not read or read.get("chance") is None:
        return None
    return float(read["chance"]) if read.get("side") in ("Over", "Yes") else 1 - float(read["chance"])


def attach_td(rows: List[Dict], reads: Dict[Tuple[str, str], Dict], player_key: str = "Player",
              own_key: Optional[str] = None) -> List[Dict]:
    """Anytime TD rows get the model's scoring chance, the book's (no-vig) chance, the model's call and Use. With
    `own_key` (the page's own scoring rate), "Agrees" says whether that rate sits on the model's side of the book."""
    out = []
    for r in rows:
        read = reads.get((norm_name(r.get(player_key)), "Anytime TD"))
        yes = td_yes(read)
        book = None if not read or read.get("p_market") is None else float(read["p_market"])
        side = None if not read else ("Yes" if read.get("side") in ("Over", "Yes") else "No")
        row = dict(r, **{"Model TD %": yes, "Book TD %": book,
                         "Model call": f"{side} (scores)" if side == "Yes" else ("No (doesn't score)" if side
                                                                               else "no line posted"),
                         "Use": (read or {}).get("use_tag") or ""})
        if own_key is not None:
            own = r.get(own_key)
            if side is None or own is None or book is None:
                row["Agrees"] = ""
            else:
                own_side = "Yes" if float(own) > book else "No"
                row["Agrees"] = "✅" if own_side == side else "⚠️ model says " + side
        out.append(row)
    return out


def show_player_calls(st, reads: Dict[Tuple[str, str], Dict], player, sport_label: str = "") -> None:
    """The model's call on every market for one player, at the top of a player page."""
    rows = player_calls(reads, player)
    st.markdown(f"**🧠 The model's read on {player}**")
    if not rows:
        st.caption("No board read for this player today (no line posted yet, or not on the slate). The charts "
                   "below are history only — not a call.")
        return
    import pandas as pd
    st.dataframe(pd.DataFrame(rows)[["Market", "Line", "Model proj", "Model call", "Chance", "Use"]]
                 .style.format({"Line": "{:g}", "Model proj": "{:.1f}", "Chance": "{:.0%}"}, na_rep="—"),
                 hide_index=True, width="stretch")
    st.caption("This is the platform's one model — the same read Today's best, Best Bets and My Coach use. "
               "Everything below on this page is the history behind it, not a second answer.")
