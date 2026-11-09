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
  trust    given the script happens, how much of the effect repeated on games it wasn't fit on (held-out slope
           over the four scripts, other season and alternate games averaged, 0..1; 0 if either test reversed): the
           shift actually applied is effect x trust. (A separate test -- does the pre-game line alone predict who beats
           his average? -- is weaker: NBA and WNBA ~0; NCAAMB, NCAAF, NHL yes. That's why a script is a call you
           make, and the page treats a tag under it as conditional.)

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
DEEP_MIN = 3.0                                                  # deep reserves: 3 minutes to the bench line
UNIT = {"hoops": "pts", "football": "pts", "hockey": "goals"}

HOOPS_STAT = {"Points": "points", "PRA": "points", "PA": "points", "PR": "points", "PB": "points",
              "Rebounds": "rebounds", "RA": "rebounds", "Assists": "assists", "Threes Made": "threes"}
FOOTBALL_STAT = {"Pass Yards": "pass_yds", "Pass Attempts": "pass_att", "Pass Completions": "pass_att",
                 "Rush Yards": "rush_yds", "Rush Attempts": "rush_yds", "Receiving Yards": "rec_yds",
                 "Rush + Rec Yards": "rec_yds", "Receptions": "receptions", "Targets": "receptions",
                 "Tackles + Assists": "tackles", "Solo Tackles": "tackles",
                 # Nov 9: every NFL / college market now has a group (script_data measures each nightly)
                 "Passing TDs": "pass_td", "Interceptions": "pass_int", "Anytime TD": "anytime_td", "Sacks": "sacks",
                 "FG Made": "fg_made", "Kicking Points": "kick_pts", "PATs Made": "pat_made"}
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
    if avg_min >= DEEP_MIN:
        return "deep"                                           # Nov 7: measured by the nightly job (script_learn)
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


def parse_event(ev: Dict, sport: str, odds: Optional[Dict] = None) -> Optional[Dict]:
    """One scoreboard event -> {teams: [{names, home, display, score}], fav (index), strength, final} or None without
    a usable line. `odds` overrides the event's own (a finished game's line from its summary's pickcenter)."""
    comp = (ev.get("competitions") or [{}])[0]
    teams = []
    for c in comp.get("competitors") or []:
        t = c.get("team") or {}
        names = {norm(t.get(k)) for k in ("displayName", "shortDisplayName", "location", "abbreviation", "name")}
        if t.get("id") is not None:
            names.add(norm(str(t["id"])))                       # kickoff snapshots store ESPN team ids
        names.add(norm(f"{t.get('location', '')} {t.get('name', '')}"))
        teams.append({"names": {n for n in names if n}, "home": c.get("homeAway") == "home", "id": t.get("id"),
                      "display": t.get("displayName") or t.get("location") or "", "score": _num(c.get("score"))})
    if len(teams) != 2:
        return None
    hi = 0 if teams[0]["home"] else 1
    ai = 1 - hi
    final = bool(((comp.get("status") or ev.get("status") or {}).get("type") or {}).get("completed"))
    odds = odds if odds is not None else ((comp.get("odds") or [None])[0] or {})
    ho, ao = odds.get("homeTeamOdds") or {}, odds.get("awayTeamOdds") or {}
    if strength_kind(sport) == "ml":
        ml = odds.get("moneyline") or {}
        hml = ho.get("moneyLine") or ((ml.get("home") or {}).get("close") or (ml.get("home") or {}).get("open") or {}).get("odds")
        aml = ao.get("moneyLine") or ((ml.get("away") or {}).get("close") or (ml.get("away") or {}).get("open") or {}).get("odds")
        ph, pa = _ml_p(hml), _ml_p(aml)
        if not (ph and pa):
            return None
        ph, pa = ph / (ph + pa), pa / (ph + pa)
        return {"teams": teams, "fav": hi if ph >= pa else ai, "strength": max(ph, pa), "final": final}
    sp = _num(odds.get("spread"))
    if sp is None or sp == 0:
        return None
    fav = hi if sp < 0 else ai
    if ho.get("favorite") is True:
        fav = hi
    elif ao.get("favorite") is True:
        fav = ai
    return {"teams": teams, "fav": fav, "strength": abs(sp), "final": final}


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
            if g is None and ev.get("id"):                      # finished games drop their odds: the summary keeps them
                try:
                    summ = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/{ESPN[sport]}/summary",
                                        params={"event": ev["id"]}, headers={"User-Agent": "Mozilla/5.0"}, timeout=15).json()
                    for pc in summ.get("pickcenter") or []:
                        g = parse_event(ev, sport, odds=pc)
                        if g:
                            break
                except Exception:                               # noqa: BLE001
                    g = None
            if g:
                out.append(g)
    return out


def actual_script(g: Dict, sport: str) -> Optional[str]:
    """How a finished game went, as a script (relative to the pre-game favorite)."""
    if not g or not g.get("final"):
        return None
    f, o = g["teams"][g["fav"]].get("score"), g["teams"][1 - g["fav"]].get("score")
    if f is None or o is None:
        return None
    m, d = f - o, DATA[sport]
    if abs(m) <= d["close"]:
        return "close"
    if m >= d["blow"]:
        return "fav_blowout"
    if m <= -d["blow"]:
        return "dog_blowout"
    return "middle"


def team_matches(team: Optional[str], names: set) -> bool:
    t = norm(team)
    if not t:
        return False
    if t in names:
        return True
    if t.isdigit():                                             # an ESPN id matches exactly or not at all
        return False
    return any(n and len(n) > 3 and (t.startswith(n + " ") or n.startswith(t + " ")) for n in names)


def game_for(teams: Sequence[str], lines: Sequence[Dict]) -> Optional[Dict]:
    """The parsed ESPN game these board teams play, or None."""
    teams = [t for t in teams if t]
    for g in lines:
        hit = sum(any(team_matches(t, tm["names"]) for t in teams) for tm in g["teams"])
        if hit == 2 or (hit == 1 and len(teams) == 1):
            return g
    return None


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


# ---------------------------------------------------------------- one prop, normalized (live board or kickoff snapshot)
def from_play(p: Dict) -> Dict:
    """A Best Bets board play -> the row the page works with. Only the play's own side has a price."""
    side = p.get("Side")
    p_over = p["ModelProb"] if side == "Over" else 1 - p["ModelProb"]
    log = p.get("_game_log") or []
    mins = [float(g.get("min") or 0) for g in log[-10:] if g.get("min") is not None]
    return {"player": p.get("Player"), "pid": p.get("PlayerId"), "team": p.get("Team"), "opp": p.get("Opp"),
            "game": p.get("Game"), "market": p.get("Market"), "line": p.get("Line"), "side": side, "p_over": p_over,
            "projection": p.get("Projection"), "over_price": p.get("RealPrice") if side == "Over" else None,
            "under_price": p.get("RealPrice") if side == "Under" else None, "use": p.get("Use") or "",
            "lean": p.get("Lean"), "gap": p.get("Gap"), "flags": list(p.get("Warnings") or []),
            "kickoff": p.get("GameDate"), "mins": (sum(mins) / len(mins)) if mins else None}


def from_snapshot(s: Dict) -> Optional[Dict]:
    """A kickoff snapshot (model_store.prop_snapshots) -> the same row, with both sides' prices."""
    if s.get("chance") is None or s.get("line") is None:
        return None
    ch = float(s["chance"])
    try:
        flags = json.loads(s.get("flags") or "[]")
    except (TypeError, ValueError):
        flags = []
    return {"player": s.get("player"), "pid": s.get("player_id"), "team": s.get("team"), "opp": s.get("opp"),
            "game": s.get("game"), "market": s.get("market"), "line": float(s["line"]), "side": s.get("side"),
            "p_over": ch if s.get("side") == "Over" else 1 - ch,
            "projection": None if s.get("projection") is None else float(s["projection"]),
            "over_price": s.get("over_price") if s.get("over_price") is not None else (s.get("price") if s.get("side") == "Over" else None),
            "under_price": s.get("under_price") if s.get("under_price") is not None else (s.get("price") if s.get("side") == "Under" else None),
            "use": s.get("use_tag") or "", "lean": s.get("lean"), "gap": s.get("gap"), "flags": flags,
            "kickoff": s.get("kickoff"), "mins": None}


# ---------------------------------------------------------------- the Use tag under a script (Nov 7)
def _z(p: float) -> float:
    from statistics import NormalDist
    return NormalDist().inv_cdf(min(0.995, max(0.005, p)))


def script_projection(projection: Optional[float], line: float, p_model: float, p_script: float) -> Optional[float]:
    """The projection moved as far as the chance moved: the model's spread of outcomes is read off its own
    projection vs line vs chance (normal approximation), then the projection shifts by the change in z."""
    import props_engine as PE
    if projection is None:
        return None
    thr = PE.threshold(line)
    z0 = _z(p_model)
    sd = abs(projection - thr) / abs(z0) if abs(z0) > 0.15 and projection != thr else 0.35 * max(abs(projection), 1.0)
    sd = min(max(sd, 0.15 * max(abs(projection), 1.0)), 0.8 * max(abs(projection), 1.0))
    return projection + (_z(p_script) - z0) * sd


def script_use(row: Dict, p_over: float, sport: str) -> Dict:
    """The platform's own Use rules (props_engine.use_tag) re-run on the script's numbers: the side the script
    favors, its chance, the edge at that side's price, the projection moved with the chance. The 'blowout risk'
    warning is dropped -- the script IS the blowout call; news / returning-player warnings still apply.
    -> {"side", "chance", "ev", "use", "why"}"""
    import props_engine as PE
    side = "Over" if p_over >= 0.5 else "Under"
    p = p_over if side == "Over" else 1 - p_over
    price = row.get("over_price") if side == "Over" else row.get("under_price")
    dec = PE.decimal(price) if price is not None else None
    ev = (p * dec - 1) if dec else None
    proj = script_projection(row.get("projection"), float(row["line"]), row["p_over"], p_over)
    flags = [f for f in row.get("flags") or [] if not any(k in str(f).lower() for k in PE.BLOWOUT_WORDS)]
    r = {"projection": proj, "line": float(row["line"]), "side": side, "p_final": p_over, "ev": ev,
         "lean": row.get("lean") if row.get("lean") == "Check news" else (side if ev is not None and ev >= PE.MIN_EV else None),
         "gap": row.get("gap"), "flags": flags, "returning": any("missed" in str(f) for f in flags)}
    PE.single_bar([r], sport)
    try:
        tag, why = PE.use_tag(r, side, float(row["line"]), p, ev)
    except Exception as exc:                                    # noqa: BLE001
        tag, why = "—", type(exc).__name__
    if price is None and tag == PE.USE_PASS:
        why = f"no price posted for the {side} — " + why
    return {"side": side, "chance": p, "ev": ev, "use": tag, "why": why, "price": price}


def game_teams(rows: Sequence[Dict], game: str) -> List[str]:
    """Everything that can identify this game's two teams: the rows' team / opponent (names or ESPN ids) and the
    two halves of the game label ("Away @ Home")."""
    out = {t for r in rows for t in (r.get("team"), r.get("opp")) if t}
    if " @ " in (game or ""):
        out |= {t.strip() for t in game.split(" @ ")}
    return sorted(out)


def fav_names(g: Optional[Dict]) -> set:
    return set(g["teams"][g["fav"]]["names"]) if g else set()


# ---------------------------------------------------------------- the nightly fit (script_learn.py) -- the feedback loop
_LEARNED: Dict[str, Tuple[float, Optional[Dict]]] = {}
LEARNED_TTL_S = 1800


def learned(sport: str) -> Optional[Dict]:
    """The latest nightly fit for this sport (settings script_learn:<sport>), or None before the first run."""
    import time
    hit = _LEARNED.get(sport)
    if hit and time.time() - hit[0] < LEARNED_TTL_S:
        return hit[1]
    try:
        import model_store as MS
        fit = MS.get_setting(f"script_learn:{sport}", None)
    except Exception:                                           # noqa: BLE001
        fit = None
    _LEARNED[sport] = (time.time(), fit)
    return fit


def refresh(sport: str) -> Optional[Dict]:
    """Overlay the nightly fit on the shipped numbers: scenario table, effects, trust. Returns the fit."""
    fit = learned(sport)
    if fit and fit.get("effects") and fit.get("shares"):
        d = DATA.setdefault(sport, {})
        for k in ("shares", "effects", "base", "n", "trust", "conditional", "games", "lined", "close", "blow", "minutes"):
            if fit.get(k) is not None:
                d[k] = fit[k]
        d["fit_at"] = fit.get("fit_at")
        d["scenario"] = fit.get("scenario")
        d["track"] = fit.get("track")
    return fit


def scenario_probs(sport: str, strength: Optional[float]) -> Tuple[Dict[str, float], str]:
    """(scenario chances, source) from the line: the nightly line curve when it beat the table on held-out games,
    else the table. (The matchup model needs team histories: it arrives through the logged calls, scenario_call.)"""
    sc = (DATA.get(sport) or {}).get("scenario") or {}
    if strength is not None and sc.get("source") == "line" and sc.get("model"):
        import math
        import scenario_model as M
        s = float(strength)
        if strength_kind(sport) == "ml":
            p = min(0.95, max(0.5, max(s, 1 - s)))
            x = math.log(p / (1 - p))
        else:
            x = abs(s)
        return M.predict(sc["model"], {"strength": x}), "line"
    return shares(strength, sport), "table"


def calls(sport: str) -> Dict:
    try:
        import model_store as MS
        return MS.get_setting(f"scenario_calls:{sport}", None) or {}
    except Exception:                                           # noqa: BLE001
        return {}


def scenario_call(sport: str, teams: Sequence[str], day: str, all_calls: Optional[Dict] = None) -> Optional[Dict]:
    """The pre-game call logged for this game (pending or graded), matched on ESPN ids or names and the date."""
    cs = all_calls if all_calls is not None else calls(sport)
    want = {norm(t) for t in teams if t}
    for k in list(cs.get("pending") or []) + list(cs.get("graded") or []):
        if k.get("d") not in (day, None) and not str(k.get("kick") or "").startswith(day):
            if k.get("d") != day:
                continue
        names = {norm(k.get("fav")), norm(k.get("dog")), norm(str(k.get("fav_id"))), norm(str(k.get("dog_id")))}
        hit = sum(1 for t in want if t in names or any(team_matches(t, {n}) for n in names if n))
        if hit >= 2 or (hit == 1 and len(want) == 1):
            return k
    return None



def minutes_by_script(sport: str, avg_min: Optional[float], is_fav: bool, sh: Dict[str, float]) -> Dict[str, float]:
    """{script: projected minutes} for one player: his average plus his role's measured minutes change in that kind
    of game (script_data.minutes_effects), centered so the mix over how likely each script is equals his average.
    Empty when minutes aren't measured for the sport or he has no role."""
    rl = role(avg_min, sport)
    eff = ((DATA.get(sport) or {}).get("minutes") or {}).get(rl or "")
    if avg_min is None or not eff:
        return {}
    raw = {s: float(eff.get(_state(s, is_fav), 0.0)) for s in SCRIPTS}
    centre = sum(sh[s] * raw[s] for s in SCRIPTS)
    return {s: max(0.0, avg_min + raw[s] - centre) for s in SCRIPTS}
