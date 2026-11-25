"""
nhl_card.py — the NHL game card's own extras (Nov 25, PropSeason scrub item 2).

PropSeason's NHL game page leads with the starting goalies, who's hurt, the back-to-back and each team's scoring
share. Ours, from ESPN's scoreboard and tonight's saved NHL board:
  * starting goalie per side, with ESPN's own status (Confirmed / Expected) -- never a guess: no listing says so;
  * each team's record overall and home / road;
  * a back-to-back flag (the team also played yesterday, per ESPN's scoreboard);
  * scoring share: each player's slice of his team's projected points among tonight's Points props on our board.
Who's out comes from game_card._injuries (the same ESPN injury report every card uses).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional

import h2_brand as HB

URL = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates={d}"


def _get(d: str) -> Dict:
    try:
        import requests
        return requests.get(URL.format(d=d.replace("-", "")), timeout=8).json() or {}
    except Exception:                                           # noqa: BLE001
        return {}


def parse(js: Dict) -> List[Dict]:
    """One entry per game: {"home": side, "away": side}; side = {"abbr","name","goalie","goalie_status","record",
    "split"} where split is the home record for the home side and the road record for the away side."""
    out = []
    for e in (js or {}).get("events") or []:
        comp = (e.get("competitions") or [{}])[0]
        game = {}
        for t in comp.get("competitors") or []:
            ha = t.get("homeAway")
            if ha not in ("home", "away"):
                continue
            tm = t.get("team") or {}
            recs = {str(r.get("name") or r.get("type") or "").lower(): r.get("summary") for r in t.get("records") or []}
            g = next((p for p in t.get("probables") or [] if "goalie" in str(p.get("name") or "").lower()), None)
            game[ha] = {"abbr": tm.get("abbreviation") or "", "name": tm.get("displayName") or "",
                        "goalie": ((g or {}).get("athlete") or {}).get("displayName") or "",
                        "goalie_status": str((((g or {}).get("status") or {}).get("type")) or "").lower(),
                        "record": recs.get("overall") or recs.get("total") or "",
                        "split": recs.get("home" if ha == "home" else "road") or ""}
        if "home" in game and "away" in game:
            out.append(game)
    return out


def teams_played(js: Dict) -> set:
    """Every team abbreviation and full name on a day's scoreboard (yesterday's, for the back-to-back flag)."""
    got = set()
    for g in parse(js):
        for side in g.values():
            got |= {side["abbr"], side["name"]}
    return got - {""}


def _hit(a, b) -> bool:
    import injury_check as IC
    a, b = IC._norm(a), IC._norm(b)
    return bool(a and b) and (a == b or a.endswith(" " + b) or b.endswith(" " + a))


def find(games: Iterable[Dict], away: str, home: str) -> Optional[Dict]:
    for g in games or []:
        if (_hit(g["home"]["name"], home) or _hit(g["home"]["abbr"], home)) and \
                (_hit(g["away"]["name"], away) or _hit(g["away"]["abbr"], away)):
            return g
    return None


def point_share(rows: Iterable[Dict], team: str, abbr: str = "", n: int = 4) -> List[Dict]:
    """[{"name","proj","share"}]: each player's share of the team's projected points among tonight's Points props."""
    mine = {}
    for r in rows or []:
        if str(r.get("market") or "").lower() != "points" or not (_hit(r.get("team"), team)
                                                                     or (abbr and _hit(r.get("team"), abbr))):
            continue
        try:
            pj = float(r.get("projection"))
        except (TypeError, ValueError):
            continue
        name = r.get("player") or r.get("Player")
        if name and pj > 0:
            mine[name] = max(pj, mine.get(name, 0.0))
    tot = sum(mine.values())
    if tot <= 0:
        return []
    return [{"name": k, "proj": v, "share": v / tot} for k, v in sorted(mine.items(), key=lambda kv: -kv[1])][:n]


def side_html(side: Dict, where: str, b2b: bool, share: List[Dict]) -> str:
    st = side.get("goalie_status") or ""
    gtxt = (f'<b>{side["goalie"]}</b> <span style="color:{HB.INK_SOFT};">'
            f'({"✓ confirmed" if st == "confirmed" else st or "listed"})</span>') if side.get("goalie") else \
        f'<span style="color:{HB.INK_SOFT};">Not announced yet</span>'
    rec = side.get("record") or "—"
    split = f' · {where} {side["split"]}' if side.get("split") else ""
    flag = (f'<div style="color:{HB.GOLD};font-size:12.5px;font-weight:700;margin-top:3px;">'
            f'⏱️ 2nd night of a back-to-back</div>') if b2b else ""
    sh = "".join(f'<div style="display:flex;gap:6px;align-items:center;font-size:12.5px;color:{HB.INK};">'
                 f'<div style="width:120px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{p["name"]}</div>'
                 f'<div style="flex:1;background:{HB.EDGE};border-radius:4px;height:8px;"><div style="width:'
                 f'{max(4, int(100 * p["share"]))}%;background:{HB.BLUE};height:8px;border-radius:4px;"></div></div>'
                 f'<div style="width:40px;text-align:right;">{p["share"]:.0%}</div></div>' for p in share)
    if sh:
        sh = (f'<div style="color:{HB.INK_SOFT};font-size:11.5px;margin:7px 0 2px;letter-spacing:.04em;">'
              f'SHARE OF PROJECTED POINTS</div>' + sh)
    return (f'<div style="flex:1;min-width:240px;"><div style="color:{HB.INK_SOFT};font-size:12px;letter-spacing:.05em;">'
            f'{str(side.get("name") or "").upper()}</div>'
            f'<div style="font-size:13px;color:{HB.INK};margin-top:3px;">🥅 {gtxt}</div>'
            f'<div style="font-size:12.5px;color:{HB.INK_SOFT};margin-top:2px;">Record {rec}{split}</div>{flag}{sh}</div>')


CAPTION = ("Goalies: ESPN's starter listing — ✓ confirmed by the team, otherwise expected; a late change happens, so "
           "check before puck drop. Back-to-back: the team also played yesterday. Share: each player's slice of his "
           "team's projected points among tonight's Points props on the H2 board. Context only — the projection "
           "already counts the matchup.")


def render(away: str, home: str, day: str, rows: Optional[List[Dict]] = None, get=None) -> bool:
    """The NHL extras under the game card. False when ESPN has no listing for this game."""
    import streamlit as st
    get = get or _get
    g = find(parse(get(day)), away, home)
    if not g:
        return False
    try:
        y = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
        played = teams_played(get(y))
    except ValueError:
        played = set()
    st.markdown("**Goalies, form & who scores**")
    st.markdown('<div style="display:flex;gap:18px;flex-wrap:wrap;">'
                + side_html(g["away"], "road", bool({g["away"]["abbr"], g["away"]["name"]} & played),
                            point_share(rows, g["away"]["name"], g["away"]["abbr"]))
                + side_html(g["home"], "home", bool({g["home"]["abbr"], g["home"]["name"]} & played),
                            point_share(rows, g["home"]["name"], g["home"]["abbr"]))
                + '</div>', unsafe_allow_html=True)
    st.caption(CAPTION)
    return True
