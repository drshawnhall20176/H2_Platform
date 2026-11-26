"""
nfl_zones.py -- where a receiver's targets go (left / middle / right) and what tonight's defense gives up there (Nov 26).

Owner, Nov 26 ("build all 7", PropSeason pass 3, Zones tab). From nflverse play-by-play (the same source the Position
Matchups game log reads): every pass attempt's `pass_location`, receiver, defense, yards and completion.
  * him: his share of targets to each side, yards a target and catch rate there;
  * the defense: yards a target it allows to each side, against the league average and ranked of 32
    (1 = gives up the most);
  * a side is called soft / tough only when the defense's gap to the league is bigger than chance (1.64 standard
    errors, ~90% one-sided) -- otherwise "about average".
A side is where the ball was thrown, not where he lines up. Context, not a pick: the projection already counts the
defense. NBA shot zones and NHL shot areas need data feeds we don't have yet (see the owner note, Nov 26).
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Optional

SIDES = ("left", "middle", "right")
YPT_SD = 9.5             # yards per target, one target's standard deviation (NFL, roughly)
Z = 1.64
MIN_TARGETS = 12         # his targets before his split means anything


def _norm(s) -> str:
    return " ".join(re.sub(r"[^a-z ]", " ", str(s or "").lower()).split())


def short_name(full: str) -> str:
    """'Amon-Ra St. Brown' -> 'a st brown' (nflverse writes 'A.St. Brown'); suffixes dropped."""
    toks = [t for t in str(full or "").split() if _norm(t) not in ("jr", "sr", "ii", "iii", "iv", "")]
    if len(toks) < 2:
        return _norm(full)
    return f"{_norm(toks[0])[:1]} {_norm(' '.join(toks[1:]).replace('-', ' '))}"


def pbp_short(name: str) -> str:
    """'A.St. Brown' -> 'a st brown'; 'T.McBride' -> 't mcbride'."""
    return _norm(str(name).replace(".", " ").replace("-", " "))


def rows_from_pbp(df) -> List[Dict]:
    """A play-by-play frame (pandas or polars) -> [{week, off, def, rec, side, yds, comp}] pass targets only."""
    try:
        recs = df.to_dicts()                                    # polars
    except AttributeError:
        recs = df.to_dict("records")                            # pandas
    out = []
    for r in recs:
        side = r.get("pass_location")
        if side not in SIDES or not r.get("receiver_player_name") or (r.get("sack") or 0) == 1:
            continue
        try:
            yds = float(r.get("yards_gained") or 0.0)
        except (TypeError, ValueError):
            yds = 0.0
        out.append({"week": r.get("week"), "off": r.get("posteam"), "def": r.get("defteam"),
                    "rec": pbp_short(r["receiver_player_name"]), "side": side, "yds": yds,
                    "comp": 1 if (r.get("complete_pass") or 0) == 1 else 0})
    return out


def player(rows: List[Dict], name: str, team: Optional[str] = None) -> Optional[Dict]:
    key = short_name(name)
    mine = [r for r in rows if r["rec"] == key and (team is None or r["off"] == team)]
    if len(mine) < MIN_TARGETS:
        return None
    out = {"targets": len(mine), "sides": {}}
    for s in SIDES:
        x = [r for r in mine if r["side"] == s]
        out["sides"][s] = {"share": len(x) / len(mine), "n": len(x),
                           "ypt": (sum(r["yds"] for r in x) / len(x)) if x else None,
                           "catch": (sum(r["comp"] for r in x) / len(x)) if x else None}
    return out


def defense(rows: List[Dict], team: str) -> Dict[str, Dict]:
    """{side: {ypt, n, league, rank, of, tier}} -- tier 'soft' / 'tough' / 'average'."""
    by: Dict[str, Dict[str, List[float]]] = {}
    for r in rows:
        by.setdefault(r["side"], {}).setdefault(r["def"], []).append(r["yds"])
    out = {}
    for s in SIDES:
        teams = {t: sum(v) / len(v) for t, v in (by.get(s) or {}).items() if len(v) >= 20}
        if team not in teams:
            continue
        all_y = [y for v in (by.get(s) or {}).values() for y in v]
        lg = sum(all_y) / len(all_y)
        n = len(by[s][team])
        se = YPT_SD / math.sqrt(n)
        gap = teams[team] - lg
        rank = 1 + sum(1 for v in teams.values() if v > teams[team])
        tier = "soft" if gap > Z * se else "tough" if gap < -Z * se else "average"
        out[s] = {"ypt": teams[team], "n": n, "league": lg, "rank": rank, "of": len(teams), "tier": tier}
    return out


def ordinal(n: int) -> str:
    return f"{n}{'tsnrhtdd'[(n // 10 % 10 != 1) * (n % 10 < 4) * n % 10::4]}"


def sentences(me: Dict, de: Dict[str, Dict], opp: str) -> List[str]:
    """Plain lines: where he gets the ball, and how the defense holds up there."""
    if not me or not de:
        return []
    top = max(SIDES, key=lambda s: me["sides"][s]["share"])
    out = [f"He's targeted to the **{top}** most: {me['sides'][top]['share']:.0%} of his {me['targets']} targets."]
    soft = [s for s in SIDES if (de.get(s) or {}).get("tier") == "soft"]
    for s in soft:
        d = de[s]
        out.append(f"{opp}'s soft side is the **{s}**: {d['ypt']:.1f} yards a target (NFL {d['league']:.1f}), "
                   f"{ordinal(d['rank'])} most of {d['of']}. {me['sides'][s]['share']:.0%} of his targets go there.")
    if not soft:
        out.append(f"{opp} is about average or better to every side.")
    return out


def table(me: Dict, de: Dict[str, Dict]) -> List[Dict]:
    rows = []
    for s in SIDES:
        m, d = me["sides"][s], de.get(s) or {}
        rows.append({"Side": s.title(), "His targets": f"{m['share']:.0%}",
                     "His yds / target": "—" if m["ypt"] is None else f"{m['ypt']:.1f}",
                     "His catch rate": "—" if m["catch"] is None else f"{m['catch']:.0%}",
                     "Defense allows": "—" if not d else f"{d['ypt']:.1f} yds / target",
                     "NFL average": "—" if not d else f"{d['league']:.1f}",
                     "Rank (1 = most)": "—" if not d else f"{d['rank']} of {d['of']}",
                     "Read": {"soft": "🟢 Soft", "tough": "🔴 Tough", "average": "⚪ About average"}.get(d.get("tier"), "—")})
    return rows


RECEIVING = ("receiving yards", "receptions", "rec yds", "longest reception")


def team_abbr(x: str) -> Optional[str]:
    x = str(x or "").strip()
    try:
        import position_lines as PL
    except Exception:                                           # noqa: BLE001
        return x or None
    if x.upper() in PL.NFL_TEAMS:
        return x.upper()
    for k, v in PL.NFL_TEAMS.items():
        if _norm(v) == _norm(x) or _norm(v).endswith(" " + _norm(x)):
            return k
    return None


def _load(season: int):
    import nflreadpy as nfl
    df = nfl.load_pbp([season])
    keep = [c for c in ("week", "posteam", "defteam", "receiver_player_name", "pass_location", "yards_gained",
                        "complete_pass", "sack") if c in df.columns]
    return rows_from_pbp(df.select(keep))


def render(p: Dict, sport: str) -> None:
    if sport != "NFL" or str(p.get("Market") or "").strip().lower() not in RECEIVING:
        return
    import streamlit as st
    from datetime import datetime
    import pytz

    @st.cache_data(ttl=21600, show_spinner="Reading where the ball goes…", max_entries=2)
    def load(season):
        return _load(season)
    now = datetime.now(pytz.timezone("US/Eastern"))
    season = now.year if now.month >= 3 else now.year - 1
    rows = load(season)
    team, opp = team_abbr(p.get("Team")), team_abbr(p.get("Opp"))
    if not rows or not opp:
        return
    me = player(rows, p.get("Player") or "", team)
    de = defense(rows, opp)
    if not me or not de:
        return
    st.markdown(f"**Zones — where his targets go vs {opp}**")
    for line in sentences(me, de, opp):
        st.markdown(line)
    import pandas as pd
    st.dataframe(pd.DataFrame(table(me, de)), hide_index=True, width="stretch")
    st.caption("This season's play-by-play (nflverse). A side is where the ball was thrown, not where he lines up. "
               "Soft / tough only when the defense's gap to the league average is bigger than chance. Context, not a "
               "pick — the projection already counts the defense.")
