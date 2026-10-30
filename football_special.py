"""
football_special.py — kicking and defensive player props (NFL). PURE LOGIC, NO NETWORK.

    projection = the player's own per-game rate (recency weighted; last season fills in under 4 games this season;
                 shrunk a little toward his position's league rate)
               x MATCHUP  (kickers: what this defense lets kickers score; defenders: what this OFFENSE gives up --
                           tackles made against it, sacks it allows -- per game vs the league, shrunk for small samples)
               x GAME     (kickers: implied team total; defenders: game script from the spread -- a favorite's pass rush
                           sees more dropbacks, an underdog's defense makes more tackles)

Rows come out in football_props' shape (price_row), so every page, the ticket builder and the Use tags read them
unchanged.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import football_props as FP
import player_props as PPR
import props_engine as PE

PRIOR_FULL = 4
OWN_SHRINK_GAMES = {"kicker": 3.0, "defense": 2.0}     # game-equivalents of the position's league rate
MATCHUP_SHRINK = {"kicker": 8.0, "defense": 6.0}
MATCHUP_CLIP = {"kicker": (0.80, 1.20), "defense": (0.75, 1.30)}
ENV_WEIGHT = {"FG Made": 0.6, "Kicking Points": 0.9, "PATs Made": 1.1}
SCRIPT = {"Sacks": -0.010, "Tackles + Assists": 0.004, "Solo Tackles": 0.004}   # x this team's spread
ROSTER_RECENT = 3              # played in one of the team's last 3 games
MAX_DEFENDERS = 14
MIN_TKL, MIN_SACKS = 1.5, 0.15


def _num(x) -> float:
    return PE.num(x)


def team_roster(special_pgames: Sequence[Dict], team, injuries: Optional[Dict[str, str]] = None) -> List[Dict]:
    """The team's kicker and regular defenders, from recent games: [{"pid","name","slot" (K/DL/LB/DB),"status"}]."""
    injuries = injuries or {}
    mine = [p for p in special_pgames or [] if p.get("team") == team]
    orders = sorted({p.get("order") for p in mine if p.get("order") is not None}, reverse=True)[:ROSTER_RECENT]
    recent = [p for p in mine if p.get("order") in orders]
    out: List[Dict] = []
    ks = sorted([p for p in recent if p.get("pos") == "K"], key=lambda p: p.get("order"), reverse=True)
    if ks:
        k = ks[0]
        out.append({"pid": k["pid"], "name": k["name"], "slot": "K", "status": injuries.get(k["name"])})
    agg: Dict = {}
    for p in [p for p in mine if p.get("pos") != "K"]:
        a = agg.setdefault(p["pid"], {"p": p, "n": 0, "tkl": 0.0, "sacks": 0.0, "recent": False})
        a["n"] += 1
        a["tkl"] += _num(p["stats"].get("tkl"))
        a["sacks"] += _num(p["stats"].get("sacks"))
        if p.get("order") in orders:
            a["recent"] = True
            if p.get("order") >= a["p"].get("order", -999):
                a["p"] = p
    regs = [a for a in agg.values() if a["recent"] and (a["tkl"] / a["n"] >= MIN_TKL or a["sacks"] / a["n"] >= MIN_SACKS)]
    regs.sort(key=lambda a: -(a["tkl"] / a["n"] + 4 * a["sacks"] / a["n"]))
    for a in regs[:MAX_DEFENDERS]:
        p = a["p"]
        out.append({"pid": p["pid"], "name": p["name"], "slot": p["pos"], "status": injuries.get(p["name"])})
    return out


def league_rate(pgames: Sequence[Dict], market: str, pos: str) -> Optional[float]:
    vals = [FP.market_value(p.get("stats") or {}, market) for p in pgames or [] if p.get("pos") == pos]
    return sum(vals) / len(vals) if vals else None


def matchup(pgames: Sequence[Dict], market: str, group: str, other) -> float:
    """Kickers: per game, what kickers scored against defense `other`; defenders: what defenders made against
    offense `other` -- vs the league per team-game, shrunk and clipped."""
    pos_ok = (lambda p: p.get("pos") == "K") if group == "kicker" else (lambda p: p.get("pos") != "K")
    per: Dict = {}
    for p in pgames or []:
        if not pos_ok(p):
            continue
        k = (p.get("opp"), p.get("game"))
        per[k] = per.get(k, 0.0) + FP.market_value(p.get("stats") or {}, market)
    if not per:
        return 1.0
    league = sum(per.values()) / len(per)
    mine = [v for (o, _g), v in per.items() if o == other]
    if not mine or league <= 0:
        return 1.0
    n = len(mine)
    w = n / (n + MATCHUP_SHRINK[group])
    raw = (sum(mine) / n) / league
    lo, hi = MATCHUP_CLIP[group]
    return max(lo, min(hi, w * raw + (1 - w)))


def player_rows(roster: Sequence[Dict], team, other, market: str, special: Dict, lines: Optional[Dict] = None,
                context: Optional[Dict] = None, sport: str = "NFL") -> List[Dict]:
    """Rows for a kicking or defensive market. `other` is the opponent (the defense a kicker faces; the offense a
    defender faces); `special` = {"pgames": this season's kicker/defender lines, "prior": last season's}."""
    m = FP.MARKETS[market]
    group = m["group"]
    ctx = context or {}
    lines, prices = lines or {}, ctx.get("prices") or {}
    pg, prior = list(special.get("pgames") or []), list(special.get("prior") or [])
    fac = matchup(pg, market, group, other)
    env = None
    if group == "kicker" and ctx.get("implied"):
        env = PE.env_factor(ctx["implied"], FP.LEAGUE_TEAM_POINTS.get(sport, 22.5))
    spread = PE.maybe(ctx.get("spread"))
    rows = []
    for r in roster:
        slot = r.get("slot")
        if slot not in m["slots"]:
            continue
        key = r.get("pid") if r.get("pid") is not None else r.get("name")
        out = PPR.is_out(r.get("status")) or str(r.get("status") or "").lower() == "out"
        g = FP._games(pg, r.get("pid"), r.get("name"), team if r.get("pid") is None else None)
        vals = [FP.market_value(x.get("stats") or {}, market) for x in g]
        read_vals = list(vals)
        flags: List[str] = []
        n_eq = float(len(vals))
        own = PE.wmean(vals) if vals else None
        if len(vals) < PRIOR_FULL and prior:
            pgx = FP._games(prior, r.get("pid"), r.get("name"), None)
            if len(pgx) >= 2:
                k = PRIOR_FULL - len(vals)
                p_vals = [FP.market_value(x.get("stats") or {}, market) for x in pgx]
                p_mean = PE.wmean(p_vals)
                own = p_mean if own is None else (len(vals) * own + k * p_mean) / (len(vals) + k)
                n_eq += k
                read_vals = vals + p_vals[:k]
                flags.append(f"＋ last season blended in ({len(vals)} game{'s' if len(vals) != 1 else ''} this season)")
        proj = None
        env_mult = 1.0
        if not out and own is not None:
            lg = league_rate(pg, market, slot)
            s = OWN_SHRINK_GAMES[group]
            base = own if lg is None else (own * n_eq + lg * s) / (n_eq + s)
            if env is not None:
                env_mult = 1.0 + ENV_WEIGHT.get(market, 0.8) * (env - 1.0)
            if spread is not None and market in SCRIPT:
                env_mult *= 1.0 + SCRIPT[market] * spread
            proj = base * fac * env_mult * FP._tuning(sport, market, slot)
            if abs(fac - 1.0) >= 0.08:
                flags.append(("Soft" if fac > 1 else "Tough") + f" matchup: {fac - 1:+.0%} vs normal")
        elif not out:
            flags.append("no games in the sample")
        rows.append(FP.price_row(r, key, slot, proj, None, market, vals, read_vals, ctx, lines, prices, fac, env_mult,
                                 flags, out=out, group=group))
    return rows
