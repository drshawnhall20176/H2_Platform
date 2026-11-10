"""
kotc.py — DraftKings "King of the Court" view for the Hot Hand Engine (Nov 10).

King of the Court pays the player with the night's most points + rebounds + assists. So the question isn't "who's hot"
but "who is most likely to post the TOP PRA on the slate" -- which needs a ceiling and a chance, not just an average.

For each rotation player on tonight's NBA slate:
  Proj PRA     matchup-adjusted form (the Hot Hand board's Matchup Score for Points + Rebounds + Assists)
  Minutes      his recent average
  Blowout      his game's chance of a 20+ point blowout, from the platform's game-script model (free, no odds credits)
  Min at risk  starters lose about 3 minutes in a blowout (measured, script study, ~10k player-games); his game's
               blowout chance above tonight's average game, times that loss
  Adj PRA      Proj PRA scaled by the minutes he's expected to keep
  Ceiling      his 90th-percentile PRA over his recent games (how high he goes on a good night)
  King chance  share of 20,000 simulated nights where he posts the slate's top PRA (each player normal around his
               Adj PRA with his own game-to-game spread; injured-out players dropped)
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

PRA_MARKETS = ("Points", "Rebounds", "Assists")
STARTER_BLOWOUT_MIN_LOSS = 2.8      # script study: starters -2.99 (winning blowout) / -2.59 (losing one)
SIMS = 20000


def _pct(xs: Sequence[float], q: float) -> Optional[float]:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def blowout_by_team(blow_rows: Sequence[Dict]) -> Dict[str, Dict]:
    """{team name: {"chance", "fav", "line", "time", "game"}} from todays_best.blowout_rows (NBA)."""
    out = {}
    for r in blow_rows or []:
        chance = float(r.get("fav_big") or 0) + float(r.get("dog_big") or 0)
        for side in str(r.get("game") or "").split(" @ "):
            out[side.strip()] = {"chance": chance, "fav": r.get("team") if r.get("who") == "favorite" else None,
                                 "line": r.get("line"), "time": r.get("time"), "game": r.get("game"),
                                 "who_big": r.get("team")}
    return out


def build(board: Sequence[Dict], player_info: Dict, blow: Dict[str, Dict], out_players: Optional[set] = None,
          sims: int = SIMS, seed: int = 7) -> List[Dict]:
    """board: Hot Hand rows (Player, Team, Opp, Market, Recent Avg, Matchup Score, Game); player_info:
    {(player, team): {"min": avg minutes, "pra": [recent PRA games]}}."""
    out_players = out_players or set()
    agg: Dict[tuple, Dict] = {}
    for b in board:
        if b.get("Market") not in PRA_MARKETS:
            continue
        k = (b["Player"], b["Team"])
        a = agg.setdefault(k, {"Player": b["Player"], "Team": b["Team"], "Opp": b.get("Opp"), "Game": b.get("Game"),
                               "form": 0.0, "proj": 0.0, "n": 0})
        a["form"] += float(b.get("Recent Avg") or 0)
        a["proj"] += float(b.get("Matchup Score") or b.get("Recent Avg") or 0)
        a["n"] += 1
    chances = [v["chance"] for v in blow.values()]
    avg_chance = sum(chances) / len(chances) if chances else 0.0
    rows = []
    for k, a in agg.items():
        if a["n"] < 3 or k[0] in out_players:
            continue
        info = player_info.get(k) or {}
        mins = info.get("min")
        pra_log = [x for x in (info.get("pra") or []) if x is not None]
        g = blow.get(a["Team"]) or {}
        chance = g.get("chance")
        starter = (mins or 0) >= 28
        risk = 0.0
        if chance is not None and starter:
            risk = max(0.0, (chance - avg_chance)) * STARTER_BLOWOUT_MIN_LOSS
        adj = a["proj"] * (1 - risk / mins) if mins else a["proj"]
        sd = None
        if len(pra_log) >= 4:
            m = sum(pra_log) / len(pra_log)
            sd = math.sqrt(sum((x - m) ** 2 for x in pra_log) / (len(pra_log) - 1))
        rows.append({"Player": a["Player"], "Team": a["Team"], "Opp": a["Opp"], "Game": a["Game"],
                     "Form PRA": round(a["form"], 1), "Proj PRA": round(a["proj"], 1),
                     "Minutes": None if mins is None else round(mins, 1),
                     "Blowout chance": chance, "Min at risk": round(risk, 1) if risk else 0.0,
                     "Adj PRA": round(adj, 1), "Ceiling (90th)": None if not pra_log else round(_pct(pra_log, 0.9), 1),
                     "Best recent": None if not pra_log else max(pra_log), "_sd": max(4.0, sd or 0.18 * adj),
                     "Spread": g.get("line"), "Blowout pick": g.get("who_big")})
    rows.sort(key=lambda r: -r["Adj PRA"])
    top = rows[:40]                                            # the crown never comes from deeper than this
    if top:
        import random
        rnd = random.Random(seed)
        wins = [0] * len(top)
        for _ in range(sims):
            best, bi = -1e9, 0
            for i, r in enumerate(top):
                v = rnd.gauss(r["Adj PRA"], r["_sd"])
                if v > best:
                    best, bi = v, i
            wins[bi] += 1
        for r, w in zip(top, wins):
            r["King chance"] = w / sims
    for r in rows:
        r.setdefault("King chance", 0.0)
    rows.sort(key=lambda r: (-r["King chance"], -r["Adj PRA"]))
    return rows
