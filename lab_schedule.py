"""
Lab schedules (Nov 18) -- the schedule rows League Schedules shows for the lab sports (Tennis, International Hoops,
Soccer). Those sports are not in sports.REGISTRY and have no engine.get_schedule, so the page used to skip them. Their
games already live in the model store (one row per game the labs' builders captured), so the schedule is read from
there: nothing new is fetched, nothing is written. Owner rule (Nov 13): soccer and international hoops list only the
leagues with a game today or tomorrow.
"""
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Sequence

import pytz

ET = pytz.timezone("US/Eastern")


def leagues_for(sport_key: str) -> List[str]:
    """The league keys a lab's schedule reads, limited to leagues with a game today or tomorrow when known."""
    if sport_key == "TENNIS":
        return ["TENNIS"]
    if sport_key == "INTL":
        import intl_picks as IP
        on = IP.slate_leagues()
        return list(on) if on is not None else list(IP.INTL_LEAGUES)
    if sport_key == "SOCCER":
        import soccer_data as D
        import soccer_picks as SP
        on = SP.slate_leagues()
        return list(on) if on is not None else list(D.LEAGUES)
    return []


def league_title(league: str) -> str:
    if league == "TENNIS":
        return "Tennis"
    try:
        import soccer_data as D
        if league in D.LEAGUES:
            return D.LEAGUES[league]["title"]
    except Exception:                                           # noqa: BLE001
        pass
    try:
        import intl_hoops as I
        return (I.LEAGUES.get(league) or {}).get("title") or league
    except Exception:                                           # noqa: BLE001
        return league


def kickoff_et(p: Dict) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(p.get("kickoff")).replace("Z", "+00:00")).astimezone(ET)
    except (TypeError, ValueError):
        return None


def _status(p: Dict) -> str:
    fh, fa = p.get("final_home"), p.get("final_away")
    if fh is not None and fa is not None:
        return f"Final {fa:g}–{fh:g}" if isinstance(fh, (int, float)) and isinstance(fa, (int, float)) else "Final"
    if p.get("result"):
        return "Final"
    return "Scheduled"


def rows(sport_key: str, picks_by_league: Dict[str, Sequence[Dict]], day: date) -> List[Dict]:
    """One row per game on `day` (US/Eastern), earliest first. Duplicate captures of the same game collapse to one."""
    out, seen = [], set()
    for league, picks in picks_by_league.items():
        for p in picks or []:
            ko = kickoff_et(p)
            if not ko or ko.date() != day:
                continue
            ident = (league, str(p.get("home")), str(p.get("away")), ko.strftime("%Y-%m-%d %H"))
            if ident in seen:
                continue
            seen.add(ident)
            if sport_key == "TENNIS":
                event = " · ".join(x for x in (p.get("tour"), p.get("tournament")) if x) or "Tennis"
                match = f"{p.get('home')} vs {p.get('away')}"
            else:
                event = league_title(league)
                match = f"{p.get('away')} @ {p.get('home')}"
            out.append({"_ko": ko, "Time (ET)": ko.strftime("%-I:%M %p"), "League" if sport_key != "TENNIS" else "Event": event,
                        "Match": match, "Status": _status(p)})
    out.sort(key=lambda r: r["_ko"])
    return out


def load(sport_key: str, loader: Optional[Callable] = None) -> Dict[str, List[Dict]]:
    if loader is None:
        import model_store as MS
        loader = MS.load_game_picks
    out = {}
    for lg in leagues_for(sport_key):
        try:
            out[lg] = loader(lg) or []
        except Exception:                                       # noqa: BLE001
            out[lg] = []
    return out
