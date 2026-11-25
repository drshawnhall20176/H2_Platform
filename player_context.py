"""
player_context.py — the Players tab's context, inside the player card (Nov 25).

Owner: "could we merge the data we see in the Players sidebar tab into the player card so we do not have two data
points showing different things?" The Players views (Hot players, Head to head, By position) each grew their own
numbers; the Hot players "Matchup Score" is a second projection that agreed with the model only ~75% of the time.
The card keeps ONE answer (the model's projection and chance) and takes from those views only what is context, never
a second projection:

  * Head to head -- his games against tonight's opponent this season, each against tonight's line;
  * Their defense lately -- what tonight's opponent has allowed in this stat over its last 5 and 10 games (team totals,
    every position), with its season average on request;
  * Rest -- days since each team's last game, back-to-backs flagged.
(By position is the card's matchup chip already -- the same number Position Matchups shows.)

Basketball (NBA, NCAAMB, WNBA) for now: the engines' own head-to-head, allowed-stats and rest functions, the same
ones Matchup Lab calls. Needs the row's team and opponent ids, saved on the board since Nov 25.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import h2_brand as HB

SPORTS = ("NBA", "NCAAMB", "WNBA")
BASE_STAT = {"Points": "pts", "Rebounds": "reb", "Assists": "ast", "Threes Made": "fg3m", "Threes": "fg3m"}


def stat_key(market: str) -> Optional[str]:
    import basketball_markets as BM
    m = str(market or "")
    return BASE_STAT.get(m) or BM.EXTRA_DISPLAY_TO_STAT.get(m)


def game_value(line: Dict, key: str) -> Optional[float]:
    """His number in one box-score line for the stat (combos summed)."""
    import basketball_markets as BM
    try:
        if key in BM.COMBOS:
            return float(sum(float(line.get(k) or 0) for k in BM.COMBOS[key]))
        v = line.get(key)
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def h2h_rows(log: List[Dict], key: str, line: Optional[float], side: str) -> List[Dict]:
    out = []
    for g in log or []:
        v = game_value(g, key)
        if v is None:
            continue
        hit = None
        if line is not None:
            hit = (v > line) if side != "Under" else (v < line)
        out.append({"date": str(g.get("date") or "")[:10], "value": v, "min": g.get("min"), "hit": hit})
    return out


def rest_text(team: str, r: Optional[Dict]) -> str:
    if not r or r.get("rest_days") is None:
        return f"{team}: rest unknown"
    d = int(r["rest_days"])
    return f"{team}: " + ("back-to-back (played yesterday)" if r.get("is_back_to_back") else
                          f"{d} day{'s' if d != 1 else ''} since their last game")


def _ids(p: Dict):
    try:
        return int(p.get("PlayerId")), int(p.get("_team_id")), int(p.get("_opp_id"))
    except (TypeError, ValueError):
        return None


def load(sport: str, day: str, pid: int, team_id: int, opp_id: int, season: bool = False):
    """(head-to-head log, {window: allowed}, (team rest, opp rest)) -- cached 30 minutes."""
    import streamlit as st

    @st.cache_data(ttl=1800, show_spinner="Reading his matchup history…", max_entries=64)
    def _h2h(sp, d, p_, t_, o_):
        import sports
        E = sports.get(sp).engine
        return E.get_player_history_vs_opponent(p_, t_, o_, d)

    @st.cache_data(ttl=1800, show_spinner=False, max_entries=64)
    def _allowed(sp, d, o_, n, days_back):
        import sports
        E = sports.get(sp).engine
        return E.get_team_recent_allowed_stats(o_, d, n=n, days_back=days_back)

    @st.cache_data(ttl=1800, show_spinner=False, max_entries=64)
    def _rest(sp, d, t_):
        import sports
        return sports.get(sp).engine.get_team_rest_info(t_, d)

    allowed = {"Last 5": _allowed(sport, day, opp_id, 5, 45), "Last 10": _allowed(sport, day, opp_id, 10, 45)}
    if season:
        allowed["Season"] = _allowed(sport, day, opp_id, 82, 200)
    return _h2h(sport, day, pid, team_id, opp_id), allowed, (_rest(sport, day, team_id), _rest(sport, day, opp_id))


def render(p: Dict, sport: str, day: Optional[str] = None) -> None:
    """The three sections under the card's read. Quietly skipped when the row has no ids or the stat isn't one the
    box scores carry."""
    import streamlit as st
    if sport not in SPORTS:
        return
    ids = _ids(p)
    key = stat_key(p.get("Market"))
    if not ids or not key:
        return
    if day is None:
        from datetime import datetime
        import pytz
        day = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
    pid, team_id, opp_id = ids
    opp = p.get("Opp") or p.get("Versus") or "tonight's opponent"
    team = p.get("Team") or "His team"
    mk = p.get("Market") or key
    line, side = p.get("Line"), p.get("Side") or "Over"
    season = st.toggle("Compare their defense with their season", value=False,
                       key=f"pctx_season_{pid}_{key}", help="Reads every game they've played -- slower the first time.")
    try:
        log, allowed, (rest_t, rest_o) = load(sport, day, pid, team_id, opp_id, season)
    except Exception as exc:                                    # noqa: BLE001 -- the card never breaks on context
        st.caption(f"The matchup history couldn't be read just now ({type(exc).__name__}).")
        return
    st.markdown(f"**Against {opp} this season**")
    rows = h2h_rows(log, key, line, side)
    if rows:
        hits = [r["hit"] for r in rows if r["hit"] is not None]
        chips = " ".join(
            f'<span style="display:inline-block;margin:2px 4px 2px 0;padding:3px 9px;border-radius:10px;'
            f'background:{HB.EDGE};color:{HB.INK};font-size:12.5px;">{r["date"][5:].replace("-", "/")} · '
            f'<b style="color:{(HB.BLUE if r["hit"] else HB.GRAY) if r["hit"] is not None else HB.INK};">'
            f'{r["value"]:g}</b></span>' for r in rows)
        st.markdown(chips, unsafe_allow_html=True)
        st.caption(f"His {mk.lower()} in each meeting (blue = cleared tonight's {side} {line:g})."
                   if line is not None else f"His {mk.lower()} in each meeting.")
        if hits:
            st.caption(f"{sum(hits)} of {len(hits)} cleared it — a small sample; the projection already weighs it.")
    else:
        st.caption(f"He hasn't played {opp} yet this season.")
    st.markdown(f"**{opp}'s defense lately — {mk.lower()} allowed per game**")
    cells = []
    for label, a in allowed.items():
        v = (a or {}).get(key)
        if v:
            cells.append(f'<div style="flex:1;min-width:90px;background:{HB.NAVY};border:1px solid {HB.EDGE};'
                         f'border-radius:10px;padding:8px 10px;"><div style="color:{HB.INK_SOFT};font-size:11.5px;">'
                         f'{label.upper()}</div><div style="color:{HB.INK};font-size:20px;font-weight:800;">'
                         f'{float(v):.1f}</div></div>')
    if cells:
        st.markdown('<div style="display:flex;gap:8px;flex-wrap:wrap;">' + "".join(cells) + '</div>',
                    unsafe_allow_html=True)
        st.caption("Team totals they've allowed (every position). A rising number = a looser defense lately. Context: "
                   "the projection already uses their defense against his position (the matchup chip).")
    else:
        st.caption("Their recent defensive numbers aren't available for this stat.")
    st.markdown("**Rest**")
    st.caption(rest_text(team, rest_t) + " · " + rest_text(opp, rest_o))
