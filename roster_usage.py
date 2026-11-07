"""
roster_usage.py — every rostered player in one game, with recent minutes and usage % (Nov 7, Game Script).

The props board lists only players with a posted line who clear the rotation bar (12+ minutes in the NBA), so the deep
bench -- exactly who gets the garbage-time minutes in a blowout -- never showed. This reads both teams' full rosters
from the basketball engines (NBA, WNBA, NCAAMB), each player's last games before the date, and estimates usage:

    USG% = 100 x (FGA + 0.44 FTA + TOV) per game x (team minutes / 5) / (minutes per game x team's (FGA + 0.44 FTA + TOV))

-- the standard formula on per-game averages (team numbers from the team's own recent games; team minutes taken as
regulation, 5 x 48 in the NBA, 5 x 40 in college and the WNBA). Shown only when the box scores carried the attempts.
"""
from __future__ import annotations

from typing import Dict, List, Optional

TEAM_MIN = {"NBA": 240.0, "WNBA": 200.0, "NCAAMB": 200.0}
LAST_N = 10


def _avg(log: List[Dict], key: str) -> Optional[float]:
    vals = [float(g[key]) for g in log if g.get(key) is not None]
    return sum(vals) / len(vals) if vals else None


def usage(log: List[Dict], team: Dict[str, float], team_min: float) -> Optional[float]:
    mins, fga, fta, tov = (_avg(log, k) for k in ("min", "fga", "fta", "tov"))
    t_plays = (team.get("fga") or 0) + 0.44 * (team.get("fta") or 0) + (team.get("tov") or 0)
    if not mins or fga is None or fta is None or not t_plays or not team.get("fga"):
        return None
    p_plays = fga + 0.44 * fta + (tov or 0)
    return 100.0 * p_plays * (team_min / 5.0) / (mins * t_plays)


def team_rows(sport: str, team_id, team_name: str, date_str: str, engine=None) -> List[Dict]:
    """[{player, pid, team, games, min, usg, pts, reb, ast, src}] for one team's whole roster, minutes first."""
    import sports
    eng = engine or sports.get(sport).engine
    try:
        tid = int(team_id)
    except (TypeError, ValueError):
        tid = team_id
    try:
        team = eng.get_team_recent_scored_stats(tid, date_str) or {}
    except Exception:                                           # noqa: BLE001
        team = {}
    out = []
    for pl in eng.get_team_roster(tid) or []:
        try:
            log = eng.get_player_recent_games(pl["id"], LAST_N, team_id=tid, before_date=date_str) or []
        except Exception:                                       # noqa: BLE001
            log = []
        played = [g for g in log if (g.get("min") or 0) > 0]
        out.append({"player": pl.get("name"), "pid": pl.get("id"), "team": team_name, "games": len(played),
                    "min": _avg(played, "min"), "usg": usage(played, team, TEAM_MIN.get(sport, 240.0)),
                    "pts": _avg(played, "pts"), "reb": _avg(played, "reb"), "ast": _avg(played, "ast"),
                    "src": "last season" if played and all(g.get("src") == "prior" for g in played) else ""})
    out.sort(key=lambda r: -(r["min"] or 0))
    return out


def game_rows(sport: str, teams: List[Dict], date_str: str, engine=None) -> List[Dict]:
    """Both teams' rosters. teams = [{"id", "name"}] (ESPN ids, as the scoreboard gives them)."""
    rows = []
    for t in teams:
        if t.get("id") is not None:
            rows += team_rows(sport, t["id"], t.get("name") or "", date_str, engine)
    return rows
