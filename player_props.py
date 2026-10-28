"""
player_props.py -- Position Matchups' Player props view for basketball: every rotation player, the prop market you
pick (PRA by default), a matchup-adjusted projection, and an over/under read against a line you type in.

PURE LOGIC, NO NETWORK (position_data.py loads; the page renders). Built to fix what the Oct 27 NBA slate exposed:

  1. Every rotation player gets his own row. The Depth table shows one starter per Guard / Forward / Center group and
     tucks everyone else into "Next up" -- Paul George, Mitchell Robinson and Michael Porter Jr. were all there, off
     the right edge, with no read of their own.
  2. The matchup is applied to the PLAYER, not graded on the group. A defense's number for a position group becomes a
     factor (allowed / league average for that market), and a player's projection is his own recent average times it.
  3. Small samples are shrunk. Three games of a defense barely moves the factor; it's blended with the end of last
     season (when loaded) and pulled toward neutral until the season sample is big enough to trust.
  4. A line you type gets a read: projection vs the line, how often he's cleared it lately, a rough probability, and
     Over / Under / no lean.
  5. Pace is flagged. Two fast, high-scoring teams inflate every counting-stat prop; that's called out per game.

HONEST LIMITS: the probability is a normal approximation around the projection using the player's own game-to-game
spread -- a guide, not a priced model; minutes, blowouts and overtime aren't modelled (pace is a flag, not an input).
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# Display name -> the box-score stats it sums. PRA first: it's the default market.
MARKETS: Dict[str, Tuple[str, ...]] = {
    "PRA": ("pts", "reb", "ast"),
    "Points": ("pts",),
    "Rebounds": ("reb",),
    "Assists": ("ast",),
    "Blocks": ("blk",),
    "Steals": ("stl",),
    "PA": ("pts", "ast"),
    "PR": ("pts", "reb"),
    "PB": ("pts", "blk"),
    "RA": ("reb", "ast"),
}
DEFAULT_MARKET = "PRA"
MARKET_HELP = {"PRA": "Points + Rebounds + Assists", "PA": "Points + Assists", "PR": "Points + Rebounds",
               "PB": "Points + Blocks", "RA": "Rebounds + Assists"}

FORM_N = 5                 # a player's "lately" window, games
HIT_N = 10                 # the window his hit rate against a line is counted over
FILL_BELOW = 3             # fewer than this many games this season -> fill his form from the end of last season
SHRINK_K = 10.0            # games of a defense that count as half-trusted (n / (n + K))
FACTOR_RANGE = (0.80, 1.20)
MIN_MINUTES = 10.0         # rotation cut-off (average minutes)
MAX_PLAYERS = 10
LEAN_EDGE = 0.05           # projection must clear the line by 5% (and the probability agree) to call a lean
PACE_FLAG_PCT = 4.0
MIN_DEFENSES = 8           # a league average from fewer defenses than this isn't one (college: two teams only)        # a game total this far from the league average gets flagged

_OUT = {"out", "injured reserve", "ir", "suspended", "inactive"}


def _num(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(v) or math.isinf(v) else v


def market_value(stats: Dict, market: str) -> float:
    return sum(_num((stats or {}).get(k)) for k in MARKETS[market])


# --------------------------------------------------------------------------- rotation (fix 1)
def rotation(usage: Dict[str, List[Dict]], injuries: Optional[Dict[str, str]] = None,
             min_minutes: float = MIN_MINUTES, limit: int = MAX_PLAYERS) -> List[Dict]:
    """position_matchups.usage_depth output ({G/F/C: [{"pid","name","avg_min",...}]}) -> one flat list of every
    rotation player, most minutes first: [{"pid","name","slot","avg_min","status"}]."""
    injuries = injuries or {}
    seen, out = set(), []
    for slot, players in (usage or {}).items():
        for u in players:
            if u.get("pid") in seen or _num(u.get("avg_min")) < min_minutes:
                continue
            seen.add(u.get("pid"))
            out.append({"pid": u.get("pid"), "name": u.get("name"), "slot": slot, "avg_min": _num(u.get("avg_min")),
                        "status": injuries.get(u.get("name"))})
    out.sort(key=lambda r: -r["avg_min"])
    return out[:limit]


def is_out(status) -> bool:
    return str(status or "").strip().lower() in _OUT


# --------------------------------------------------------------------------- defense factor (fixes 2 + 3)
def defense_allowed(allowed: Dict, market: str, min_games: int = 3) -> Dict[str, Dict[str, Dict]]:
    """position_matchups.allowed_by_slot output -> {defense: {slot: {"avg", "games"}}} of the MARKET allowed per game
    to each position group, plus a "_league" entry {slot: average across defenses with >= min_games}."""
    out: Dict[str, Dict[str, Dict]] = {}
    for defense, games in (allowed or {}).items():
        per: Dict[str, Dict] = {}
        slots = {s for g in games for s in (g.get("slots") or {})}
        for slot in slots:
            vals = [market_value((g.get("slots") or {}).get(slot) or {}, market) for g in games]
            per[slot] = {"avg": sum(vals) / len(vals), "games": len(vals)}
        out[defense] = per
    league: Dict[str, float] = {}
    for slot in {s for per in out.values() for s in per}:
        vals = [per[slot]["avg"] for per in out.values() if slot in per and per[slot]["games"] >= min_games]
        if vals:
            league[slot] = sum(vals) / len(vals)
    out["_league"] = {s: {"avg": v, "games": None, "defenses": len([1 for per in out.values()
                                                                   if s in per and per[s]["games"] >= min_games])}
                      for s, v in league.items()}
    return out


def raw_factor(table: Dict[str, Dict[str, Dict]], defense, slot: str) -> Optional[Tuple[float, int]]:
    """(allowed / league average, games) for one defense at one position group, or None if unknown."""
    d = (table.get(defense) or {}).get(slot)
    lg = (table.get("_league") or {}).get(slot)
    if not d or not lg or not lg["avg"] or lg.get("defenses", 0) < MIN_DEFENSES:
        return None
    return d["avg"] / lg["avg"], d["games"]


def shrink(factor: float, games: int, toward: float = 1.0, k: float = SHRINK_K) -> float:
    w = games / (games + k) if games > 0 else 0.0
    return toward + (factor - toward) * w


def blended_factor(current: Optional[Tuple[float, int]], prior: Optional[Tuple[float, int]],
                   mode: str = "blend") -> Dict:
    """The factor a player's projection is multiplied by, and how it was built.

    mode "blend" (default): last season's factor (itself shrunk by its own sample) is the starting point, and this
    season's pulls away from it as games pile up -- n / (n + 10). "season": this season only, shrunk toward neutral.
    "prior": last season only. Always clipped to FACTOR_RANGE. Returns {"factor", "season_weight", "basis"}."""
    lo, hi = FACTOR_RANGE
    if mode == "prior":
        f = shrink(*prior) if prior else 1.0
        return {"factor": min(hi, max(lo, f)), "season_weight": 0.0, "basis": "last season" if prior else "neutral"}
    target = shrink(*prior) if (prior and mode == "blend") else 1.0
    if current is None:
        return {"factor": min(hi, max(lo, target)), "season_weight": 0.0,
                "basis": "last season" if target != 1.0 else "neutral"}
    f, n = current
    w = n / (n + SHRINK_K)
    return {"factor": min(hi, max(lo, target + (f - target) * w)), "season_weight": w,
            "basis": f"{n} games this season" + (" + last season" if mode == "blend" and prior else "")}


# --------------------------------------------------------------------------- player form + the line read (fix 4)
def player_values(pgames: Iterable[Dict], pid, market: str, n: int) -> List[float]:
    mine = [p for p in pgames or [] if p.get("pid") == pid and _num((p.get("stats") or {}).get("min")) > 0]
    mine.sort(key=lambda p: (p.get("order") is None, p.get("order")), reverse=True)
    return [market_value(p.get("stats") or {}, market) for p in mine[:n]]


def form(cur_pgames, prior_pgames, pid, market: str) -> Dict:
    """His recent values for the market, newest first: this season's games, topped up from the end of last season
    when he has fewer than FILL_BELOW this season (flagged). {"values", "season_games", "filled"}."""
    cur = player_values(cur_pgames, pid, market, HIT_N)
    filled = False
    vals = list(cur)
    if len(cur) < FILL_BELOW:
        extra = player_values(prior_pgames, pid, market, HIT_N)
        if extra:
            vals = cur + extra[: HIT_N - len(cur)]
            filled = True
    return {"values": vals, "season_games": len(cur), "filled": filled}


def prob_over(projection: float, values: Sequence[float], line: float) -> Optional[float]:
    """P(stat > line), normal approximation around the projection with the player's own spread (floored, so a
    three-game sample can't claim certainty). A rough guide, not a priced model."""
    if line is None or projection is None:
        return None
    vals = list(values)
    if len(vals) >= 2:
        m = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))
    else:
        sd = 0.0
    sd = max(sd, 0.25 * max(projection, 1.0), 1.0)
    z = (threshold(line) - projection) / sd
    return max(0.01, min(0.99, 0.5 * (1 - math.erf(z / math.sqrt(2)))))


def threshold(line: float) -> float:
    """A whole-number line is an alt "N+" ladder line (DraftKings' 40+ means 40 or more), so it's cleared at N --
    the continuity point is N - 0.5. A half line (39.5) is cleared above it."""
    line = float(line)
    return line - 0.5 if line == int(line) else line


def clears(value: float, line: float) -> bool:
    return value > threshold(line)


def lean(projection: Optional[float], line: Optional[float], p_over: Optional[float]) -> str:
    if projection is None or line is None or p_over is None or line <= 0:
        return "—"
    edge = (projection - threshold(line)) / threshold(line) if threshold(line) > 0 else 0.0
    if edge >= LEAN_EDGE and p_over >= 0.55:
        return "Over"
    if edge <= -LEAN_EDGE and p_over <= 0.45:
        return "Under"
    return "No lean"


def american(p: Optional[float]) -> Optional[int]:
    if p is None or p <= 0 or p >= 1:
        return None
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


def player_rows(rotation_list: Sequence[Dict], defense, market: str, cur_table: Dict, prior_table: Optional[Dict],
                cur_pgames, prior_pgames, lines: Optional[Dict] = None, mode: str = "blend",
                current_is_prior: bool = False) -> List[Dict]:
    """One row per rotation player for `market` against `defense`. `lines` is {pid: line} typed by the user.
    `current_is_prior` means the season table is really last season's (opening weeks) -- then it's used as the prior
    and there's no separate this-season factor."""
    lines = lines or {}
    rows = []
    for r in rotation_list:
        slot = r["slot"]
        cur = None if current_is_prior else raw_factor(cur_table, defense, slot)
        pri = raw_factor(prior_table, defense, slot) if prior_table else (raw_factor(cur_table, defense, slot)
                                                                          if current_is_prior else None)
        fac = blended_factor(cur, pri, mode)
        f = form(cur_pgames, prior_pgames, r["pid"], market)
        recent = f["values"][:FORM_N]
        avg = sum(recent) / len(recent) if recent else None
        out = is_out(r.get("status"))
        proj = None if (avg is None or out) else avg * fac["factor"]
        line = lines.get(r["pid"])
        try:
            line = float(line) if line not in (None, "") and not (isinstance(line, float) and math.isnan(line)) else None
        except (TypeError, ValueError):
            line = None
        p = prob_over(proj, f["values"], line) if (proj is not None and line is not None) else None
        hits = [v for v in f["values"] if line is not None and clears(v, line)]
        rows.append({
            "pid": r["pid"], "player": r["name"], "slot": slot, "status": r.get("status"), "out": out,
            "avg_min": r["avg_min"], "recent_avg": avg, "games": len(recent), "season_games": f["season_games"],
            "filled": f["filled"], "factor": fac["factor"], "season_weight": fac["season_weight"],
            "basis": fac["basis"], "projection": proj, "line": line,
            "hit": (len(hits), len(f["values"])) if line is not None and f["values"] else None,
            "p_over": p, "lean": lean(proj, line, p),
        })
    return rows


def display(rows: Sequence[Dict]) -> List[Dict]:
    """Rows -> table strings. 'Line' stays numeric (it's the editable column)."""
    out = []
    for r in rows:
        status = f" 🚫 {r['status']}" if r["out"] else (f" ⚠️ {r['status']}" if r.get("status") else "")
        fac = r["factor"] - 1
        out.append({
            "Player": f"{r['player']}{status}",
            "Pos": r["slot"],
            "Min": f"{r['avg_min']:.0f}",
            "Last 5": "—" if r["recent_avg"] is None else
                      f"{r['recent_avg']:.1f} ({r['games']} g{', incl. last season' if r['filled'] else ''})",
            "Matchup": f"{fac:+.0%}",
            "Projection": "—" if r["projection"] is None else f"{r['projection']:.1f}",
            "Line": r["line"],
            "Hit rate": "—" if not r["hit"] else f"{r['hit'][0]}/{r['hit'][1]}",
            "P(over)": "—" if r["p_over"] is None else f"{r['p_over']:.0%}",
            "Lean": {"Over": "🟢 Over", "Under": "🔴 Under", "No lean": "⚪ No lean"}.get(r["lean"], "—"),
        })
    return out


def plays_for_log(rows: Sequence[Dict], market: str, game_label: str) -> List[Dict]:
    """Rows with a line -> quick_log play dicts. Side follows the lean (Under only when the read is Under); the
    probability is for that side; Fair is its no-vig price -- edit to the price you actually got in Bet Log."""
    plays = []
    for r in rows:
        if r["line"] is None or r["p_over"] is None:
            continue
        side = "Under" if r["lean"] == "Under" else "Over"
        p = r["p_over"] if side == "Over" else 1 - r["p_over"]
        plays.append({"Player": r["player"], "PlayerId": r["pid"], "Game": game_label, "Market": market,
                      "Side": side, "Line": r["line"], "ModelProb": round(p, 4), "Fair": american(p)})
    return plays


# --------------------------------------------------------------------------- pace (fix 5)
def team_scoring(pgames: Iterable[Dict]) -> Dict:
    """{team: {"for": avg points scored, "against": avg allowed, "games"}} from player lines."""
    pts: Dict[Tuple, float] = {}
    pair: Dict[Tuple, object] = {}
    for p in pgames or []:
        key = (p.get("game"), p.get("team"))
        pts[key] = pts.get(key, 0.0) + _num((p.get("stats") or {}).get("pts"))
        pair[key] = p.get("opp")
    agg: Dict = {}
    for (g, t), v in pts.items():
        a = agg.setdefault(t, {"for": [], "against": []})
        a["for"].append(v)
        opp_pts = pts.get((g, pair[(g, t)]))
        if opp_pts is not None:
            a["against"].append(opp_pts)
    return {t: {"for": sum(a["for"]) / len(a["for"]), "games": len(a["for"]),
                "against": (sum(a["against"]) / len(a["against"])) if a["against"] else None}
            for t, a in agg.items() if a["for"]}


def pace_flag(pgames: Iterable[Dict], home, away) -> Optional[Dict]:
    """Projected game total from both teams' scoring for/against vs the sample's average game total."""
    ts = team_scoring(pgames)
    h, a = ts.get(home), ts.get(away)
    if not h or not a or h["against"] is None or a["against"] is None:
        return None
    proj = (h["for"] + a["against"]) / 2 + (a["for"] + h["against"]) / 2
    totals = [t["for"] + t["against"] for t in ts.values() if t["against"] is not None]
    league = sum(totals) / len(totals) if totals else None
    if not league:
        return None
    pct = (proj - league) / league * 100
    label = ("⚡ Fast, high-scoring matchup" if pct >= PACE_FLAG_PCT else
             "🐢 Slow, low-scoring matchup" if pct <= -PACE_FLAG_PCT else "Normal pace")
    return {"projected_total": proj, "league_total": league, "pct": pct, "label": label}
