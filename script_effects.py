"""
script_effects.py — game scripts for every sport with player props: how likely each kind of game is, and what each
does to a player's line (Nov 7; NBA-only version earlier the same day).

Measured in research/script_study.py from ESPN box scores and pre-game lines (DraftKings via ESPN), market by market,
against each player's own average over his previous games:

  shares   how games finish -- favorite blows it open / close / underdog blows it open -- by pre-game strength
           (the spread; NHL: the favorite's no-vig moneyline chance, since the puck line is always 1.5)
  effects  how much more (or less) often a player beats his own average, by group (basketball: role x stat;
           football and hockey: the stat) and how his team's game went, relative to the group's overall rate,
           shrunk toward zero for small samples
  trust    how much of the effect carried over to games it wasn't fit on (held-out slope, 0..1): the shift
           actually applied is effect x trust. A sport or market whose effects didn't hold up gets no shift.

The shifts are centered so that, averaged over how likely each script is, a player's chance is the model's own: a
script view re-splits the model's read, it never invents an edge. A ticket's chance under scripts = sum over scripts
of P(script) x the product of its legs' chances in that script, which counts legs that win or lose together.

CAVEAT (stated on the page): effects are measured against players' own averages, not prop lines; the books know the
spread too, so some of it may already be priced in.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

SCRIPTS = ("fav_blowout", "middle", "close", "dog_blowout")
_STATE = {"close": "close", "middle": "mid"}

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "script_effects_data.json")) as _fh:
    DATA: Dict[str, Dict] = json.load(_fh)
SPORTS = tuple(DATA)

FAMILY = {"NBA": "hoops", "WNBA": "hoops", "NCAAMB": "hoops", "NFL": "football", "NCAAF": "football", "NHL": "hockey"}
ROLE_MIN = {"NBA": (26.0, 12.0), "WNBA": (24.0, 10.0), "NCAAMB": (24.0, 10.0)}       # (starter, bench) average minutes
UNIT = {"hoops": "pts", "football": "pts", "hockey": "goals"}

HOOPS_STAT = {"Points": "points", "PRA": "points", "PA": "points", "PR": "points", "PB": "points",
              "Rebounds": "rebounds", "RA": "rebounds", "Assists": "assists", "Threes Made": "threes"}
FOOTBALL_STAT = {"Pass Yards": "pass_yds", "Pass Attempts": "pass_att", "Pass Completions": "pass_att",
                 "Rush Yards": "rush_yds", "Rush Attempts": "rush_yds", "Receiving Yards": "rec_yds",
                 "Rush + Rec Yards": "rec_yds", "Receptions": "receptions", "Targets": "receptions",
                 "Tackles + Assists": "tackles", "Solo Tackles": "tackles"}
HOCKEY_STAT = {"Shots on Goal": "shots", "Points": "points", "Goals": "points", "Assists": "points",
               "Blocked Shots": "blocks", "Saves": "saves"}


def strength_kind(sport: str) -> str:
    return "ml" if FAMILY.get(sport) == "hockey" else "spread"


def labels(sport: str) -> Dict[str, str]:
    d = DATA[sport]
    u = UNIT[FAMILY[sport]]
    one = "1 goal" if FAMILY[sport] == "hockey" else f"{d['close']}"
    return {"fav_blowout": f"Favorite blows it open ({d['blow']}+)",
            "middle": f"Middle ({d['close'] + 1}–{d['blow'] - 1})" if d["blow"] - d["close"] > 2 else f"Middle ({d['close'] + 1} {u})",
            "close": f"Close game (within {one})" if FAMILY[sport] == "hockey" else f"Close game (within {d['close']})",
            "dog_blowout": f"Underdog blows it open ({d['blow']}+)"}


def short(sport: str, script: str) -> str:
    return labels(sport)[script].split(" (")[0]


def shares(strength: Optional[float], sport: str = "NBA") -> Dict[str, float]:
    """{script: probability} from the pre-game strength: the spread (either sign) or, for hockey, the favorite's
    chance. None -> the most even bucket."""
    rows = DATA[sport]["shares"]
    if strength is None:
        fav, close, dog = rows[0][2:5]
    else:
        s = abs(float(strength)) if strength_kind(sport) == "spread" else max(float(strength), 1 - float(strength))
        fav, close, dog = rows[-1][2:5]
        for lo, hi, f, c, dg, *_ in rows:
            if lo <= s < hi:
                fav, close, dog = f, c, dg
                break
    return {"fav_blowout": fav, "middle": max(0.0, 1 - fav - close - dog), "close": close, "dog_blowout": dog}


def role(avg_min: Optional[float], sport: str = "NBA") -> Optional[str]:
    if avg_min is None or sport not in ROLE_MIN:
        return None
    st_min, bench_min = ROLE_MIN[sport]
    if avg_min >= st_min:
        return "starter"
    if avg_min >= bench_min:
        return "bench"
    return None


def group(sport: str, market: str, avg_min: Optional[float] = None) -> Optional[str]:
    """The measured group a prop belongs to, or None (no shift: not measured, or a deep reserve)."""
    fam = FAMILY.get(sport)
    if fam == "hoops":
        r, stat = role(avg_min, sport), HOOPS_STAT.get(market)
        return f"{r}:{stat}" if r and stat else None
    if fam == "football":
        return FOOTBALL_STAT.get(market)
    if fam == "hockey":
        return HOCKEY_STAT.get(market)
    return None


def role_label(grp: Optional[str]) -> str:
    if not grp:
        return "—"
    return grp.split(":")[0] if ":" in grp else grp.replace("_", " ")


def trust(sport: str, grp: Optional[str]) -> float:
    if not grp:
        return 0.0
    return float((DATA[sport].get("trust") or {}).get(grp, 0.0))


def _state(script: str, is_fav: bool) -> str:
    if script in _STATE:
        return _STATE[script]
    won = (script == "fav_blowout") == is_fav
    return "blow_win" if won else "blow_lose"


def over_by_script(p_over: float, grp: Optional[str], is_fav: bool, sh: Dict[str, float], sport: str = "NBA") -> Dict[str, float]:
    """{script: P(Over)} for one prop. Shifts (effect x trust) are centered on the script mix so the weighted
    average is p_over."""
    w = trust(sport, grp)
    eff = (DATA[sport]["effects"].get(grp) if grp else None) or {}
    if w <= 0 or not eff:
        return {s: p_over for s in SCRIPTS}
    raw = {s: w * float(eff.get(_state(s, is_fav), 0.0)) for s in SCRIPTS}
    centre = sum(sh[s] * raw[s] for s in SCRIPTS)
    return {s: min(0.97, max(0.03, p_over + raw[s] - centre)) for s in SCRIPTS}


def side_chance(by_script: Dict[str, float], side: str) -> Dict[str, float]:
    return {s: (p if side == "Over" else 1 - p) for s, p in by_script.items()}


def ticket(legs: Sequence[Dict[str, float]], sh: Dict[str, float]) -> Tuple[float, float, Dict[str, float]]:
    """(chance counting scripts, chance multiplying the legs' plain chances, {script: chance in that script}).
    Each leg is {script: chance of the side taken}."""
    per = {}
    for s in SCRIPTS:
        p = 1.0
        for lg in legs:
            p *= lg[s]
        per[s] = p
    scripted = sum(sh[s] * per[s] for s in SCRIPTS)
    plain = 1.0
    for lg in legs:
        plain *= sum(sh[s] * lg[s] for s in SCRIPTS)
    return scripted, plain, per


def fair_american(p: float) -> Optional[int]:
    if p <= 0 or p >= 1:
        return None
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


def evidence(sport: str) -> Dict:
    """What the page says about how well this sport's script effects held up."""
    d = DATA[sport]
    return {"games": d.get("games"), "lined": d.get("lined"), "slope": d.get("slope"), "trusted": sorted(
        g for g, t in (d.get("trust") or {}).items() if t > 0), "untrusted": sorted(
        g for g, t in (d.get("trust") or {}).items() if t <= 0)}


# ---------------------------------------------------------------- today's pre-game lines (ESPN, same source as the study)
ESPN = {"NBA": "basketball/nba", "WNBA": "basketball/wnba", "NCAAMB": "basketball/mens-college-basketball",
        "NFL": "football/nfl", "NCAAF": "football/college-football", "NHL": "hockey/nhl"}
GROUPS = {"NCAAMB": "50", "NCAAF": "80"}


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ml_p(ml) -> Optional[float]:
    ml = _num(ml)
    if ml is None or -100 < ml < 100:
        return None
    return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)


def norm(s: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower().replace("&", "and")).strip()


def parse_event(ev: Dict, sport: str) -> Optional[Dict]:
    """One scoreboard event -> {teams: [{names, home}], fav (index), strength} or None without a usable line."""
    comp = (ev.get("competitions") or [{}])[0]
    teams = []
    for c in comp.get("competitors") or []:
        t = c.get("team") or {}
        names = {norm(t.get(k)) for k in ("displayName", "shortDisplayName", "location", "abbreviation", "name")}
        names.add(norm(f"{t.get('location', '')} {t.get('name', '')}"))
        teams.append({"names": {n for n in names if n}, "home": c.get("homeAway") == "home",
                      "display": t.get("displayName") or t.get("location") or ""})
    if len(teams) != 2:
        return None
    hi = 0 if teams[0]["home"] else 1
    ai = 1 - hi
    odds = (comp.get("odds") or [None])[0] or {}
    ho, ao = odds.get("homeTeamOdds") or {}, odds.get("awayTeamOdds") or {}
    if strength_kind(sport) == "ml":
        ml = odds.get("moneyline") or {}
        hml = ho.get("moneyLine") or ((ml.get("home") or {}).get("close") or (ml.get("home") or {}).get("open") or {}).get("odds")
        aml = ao.get("moneyLine") or ((ml.get("away") or {}).get("close") or (ml.get("away") or {}).get("open") or {}).get("odds")
        ph, pa = _ml_p(hml), _ml_p(aml)
        if not (ph and pa):
            return None
        ph, pa = ph / (ph + pa), pa / (ph + pa)
        return {"teams": teams, "fav": hi if ph >= pa else ai, "strength": max(ph, pa)}
    sp = _num(odds.get("spread"))
    if sp is None or sp == 0:
        return None
    fav = hi if sp < 0 else ai
    if ho.get("favorite") is True:
        fav = hi
    elif ao.get("favorite") is True:
        fav = ai
    return {"teams": teams, "fav": fav, "strength": abs(sp)}


def fetch_lines(sport: str, days: Sequence[str]) -> List[Dict]:
    """Pre-game lines for the given YYYYMMDD days from ESPN's scoreboard (DraftKings, as in the study)."""
    import requests
    out = []
    for d in days:
        params = {"dates": d, "limit": "400"}
        if sport in GROUPS:
            params["groups"] = GROUPS[sport]
        try:
            sb = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/{ESPN[sport]}/scoreboard", params=params,
                              headers={"User-Agent": "Mozilla/5.0"}, timeout=15).json()
        except Exception:                                       # noqa: BLE001
            continue
        for ev in sb.get("events") or []:
            g = parse_event(ev, sport)
            if g:
                out.append(g)
    return out


def team_matches(team: Optional[str], names: set) -> bool:
    t = norm(team)
    if not t:
        return False
    if t in names:
        return True
    return any(n and len(n) > 3 and (t.startswith(n + " ") or n.startswith(t + " ")) for n in names)


def line_for(teams: Sequence[str], lines: Sequence[Dict]) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """(strength, favorite team name as the board writes it, underdog name) for the game these board teams play."""
    teams = [t for t in teams if t]
    for g in lines:
        hit = {}
        for t in teams:
            for i, tm in enumerate(g["teams"]):
                if team_matches(t, tm["names"]):
                    hit[i] = t
        if len(hit) == 2 or (len(hit) == 1 and len(teams) == 1):
            fi = g["fav"]
            fav = hit.get(fi) or g["teams"][fi]["display"]
            dog = hit.get(1 - fi) or g["teams"][1 - fi]["display"]
            return g["strength"], fav, dog
    return None, None, None
