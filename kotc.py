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
  King chance  share of 20,000 simulated nights where he posts the slate's top PRA; injured-out players dropped

Nov 18 (the Sensabaugh / Grimes night: two players the model had at ~15 PRA tied for the crown at 56 while Luka sat at
76%). The simulation now (research/kotc_backtest.py + kotc_sweep.py, every NBA night with saved reads):
  * runs the WHOLE field, not the top 40 -- the crown came from outside the top 5 on 9 of 18 nights
  * draws each player's night from how players at his projection level actually finished against the model's
    projection (RATIO_Q: 1,700+ graded player-nights) instead of a normal curve: a 15-PRA bench scorer goes 2-3x his
    projection about 1 night in 20, a 45-PRA star rarely beats 1.5x. Spread scaled by RATIO_SHRINK (fitted: 0.8)
  Result on those nights: the old way gave the top 5 an average 91% and they won 9 of 18; the new way says ~68% and
  they won 10 of 18. Log score on the actual winner 3.38 -> 3.03; the old way gave the eventual winner 0% on 3 nights.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

PRA_MARKETS = ("Points", "Rebounds", "Assists")
STARTER_BLOWOUT_MIN_LOSS = 2.8      # script study: starters -2.99 (winning blowout) / -2.59 (losing one)
SIMS = 20000
# actual PRA / model PRA projection, 5% quantiles (0, 5, ..., 100%), by projection band -- research/kotc_sweep.py, Nov 18
RATIO_BANDS = (15.0, 25.0, 35.0)          # < 15, 15-25, 25-35, 35+
RATIO_Q = (
    (0.0, 0.312, 0.407, 0.536, 0.618, 0.696, 0.75, 0.836, 0.918, 0.985, 1.03, 1.13, 1.197, 1.283, 1.339, 1.432, 1.539,
     1.669, 1.919, 2.172, 3.965),
    (0.047, 0.393, 0.528, 0.596, 0.653, 0.717, 0.772, 0.828, 0.864, 0.915, 0.965, 1.026, 1.087, 1.148, 1.213, 1.271,
     1.369, 1.473, 1.58, 1.765, 3.385),
    (0.2, 0.4, 0.56, 0.627, 0.713, 0.794, 0.828, 0.876, 0.911, 0.948, 0.999, 1.026, 1.063, 1.111, 1.146, 1.202, 1.262,
     1.334, 1.393, 1.5, 2.275),
    (0.08, 0.596, 0.648, 0.694, 0.735, 0.776, 0.812, 0.828, 0.859, 0.909, 0.945, 0.962, 0.979, 0.994, 1.028, 1.076,
     1.115, 1.153, 1.198, 1.339, 1.799),
)
RATIO_SHRINK = 0.8
FIELD_TOP = 5                             # "the field" = everyone outside the top 5 by King chance


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


def model_pra(reads: Dict) -> Dict[str, float]:
    """Nov 17 (one model): {normalized player: the model's PRA projection} from the day's saved board reads -- its PRA
    read when posted, else the sum of its Points, Rebounds and Assists reads (all three needed)."""
    import model_view as MV
    out, parts = {}, {}
    for (p, mk), r in (reads or {}).items():
        if r.get("projection") is None:
            continue
        if mk == "PRA":
            out[p] = float(r["projection"])
        elif mk in PRA_MARKETS:
            parts.setdefault(p, {})[mk] = float(r["projection"])
    for p, d in parts.items():
        if p not in out and len(d) == 3:
            out[p] = sum(d.values())
    return out


def build(board: Sequence[Dict], player_info: Dict, blow: Dict[str, Dict], out_players: Optional[set] = None,
          sims: int = SIMS, seed: int = 7, model_proj: Optional[Dict[str, float]] = None) -> List[Dict]:
    """board: Hot Hand rows (Player, Team, Opp, Market, Recent Avg, Matchup Score, Game); player_info:
    {(player, team): {"min": avg minutes, "pra": [recent PRA games]}}. model_proj: {normalized player: the model's
    PRA projection} -- used for Proj PRA whenever the model has one (Nov 17: one model across the site); the Hot
    Hand's form x matchup sum only fills in for players the model has no read on."""
    import model_view as MV
    model_proj = model_proj or {}
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
        mp = model_proj.get(MV.norm_name(a["Player"]))
        if mp is not None:
            a["proj"] = mp
            adj = a["proj"] * (1 - risk / mins) if mins else a["proj"]
        rows.append({"Player": a["Player"], "Team": a["Team"], "Opp": a["Opp"], "Game": a["Game"],
                     "Form PRA": round(a["form"], 1), "Proj PRA": round(a["proj"], 1),
                     "Source": "model" if mp is not None else "form × matchup",
                     "Minutes": None if mins is None else round(mins, 1),
                     "Blowout chance": chance, "Min at risk": round(risk, 1) if risk else 0.0,
                     "Adj PRA": round(adj, 1), "Ceiling (90th)": None if not pra_log else round(_pct(pra_log, 0.9), 1),
                     "Best recent": None if not pra_log else max(pra_log),
                     "Spread": g.get("line"), "Blowout pick": g.get("who_big")})
    rows.sort(key=lambda r: -r["Adj PRA"])
    if rows:
        import numpy as np
        rng = np.random.default_rng(seed)
        adj = np.array([max(r["Adj PRA"], 0.0) for r in rows])
        band = np.searchsorted(np.array(RATIO_BANDS), adj, side="right")
        qs = np.array(RATIO_Q)
        grid = np.linspace(0.0, 1.0, qs.shape[1])
        wins = np.zeros(len(rows))
        chunk = 4000
        for start in range(0, sims, chunk):
            n = min(chunk, sims - start)
            u = rng.random((n, len(rows)))
            ratio = np.empty_like(u)
            for b in range(len(RATIO_Q)):
                cols = band == b
                if cols.any():
                    ratio[:, cols] = np.interp(u[:, cols], grid, qs[b])
            nights = adj * (1.0 + RATIO_SHRINK * (ratio - 1.0))
            wins += np.bincount(nights.argmax(axis=1), minlength=len(rows))
        for r, w in zip(rows, wins):
            r["King chance"] = float(w) / sims
    rows.sort(key=lambda r: (-r["King chance"], -r["Adj PRA"]))
    return rows


def field_chance(rows: Sequence[Dict], top: int = FIELD_TOP) -> Optional[float]:
    """Chance the crown goes to someone outside the top `top` by King chance (rows as build() returns them)."""
    if not rows:
        return None
    return max(0.0, 1.0 - sum(r.get("King chance") or 0.0 for r in rows[:top]))
