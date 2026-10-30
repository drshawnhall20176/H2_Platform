"""
props_backtest.py — the Scorecard: does the Player props model actually predict better than a player's plain
average? PURE LOGIC, NO NETWORK -- it replays the games already loaded for the page.

WALK-FORWARD, NO PEEKING: every player-game in the sample is "predicted" using only the games BEFORE it -- the
player's earlier games for his rate and volume, the defenses' earlier games for the matchup factor, the team's
schedule for rest -- then compared with what he actually did.

WHAT IT'S COMPARED AGAINST:
  * the NAIVE read: his plain average of his last 5 games (what most people eyeball);
  * a PROXY LINE: his average over the earlier games in the sample, rounded to the nearest .5 below. Historical
    book lines aren't stored, and books open most player lines close to the season average, so this tests "does
    the model know which side of his normal number he'll land" -- not "does it beat the book's closing line";
    that's what closing-line value in the Bet Log is for.

WHAT IT REPORTS: projection error (model vs naive), how often the model's leans hit, calibration buckets
(when it says 60%, does it hit 60%?), the Brier score, and the fitted calibration slope -- the number the Player
props tab can apply to shrink over-confident probabilities.

ONE HONEST CAVEAT: a teammate who didn't play in a past game is treated as a known absence (the injury report
usually says so before tip-off), which flatters the "next man up" logic slightly.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence

import player_props as PPR
import position_matchups as PM
import props_engine as PE

MIN_HISTORY = 4
MAX_CASES = 3000


def proxy_line(history: Sequence[float]) -> Optional[float]:
    if not history:
        return None
    return math.floor(sum(history) / len(history)) + 0.5


def _date(x) -> str:
    return str(x or "")[:10]


def _days_between(a: str, b: str) -> Optional[int]:
    from datetime import datetime
    try:
        return (datetime.strptime(b[:10], "%Y-%m-%d") - datetime.strptime(a[:10], "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return None


def summarize(cases: Sequence[Dict]) -> Dict:
    """cases: [{"actual","naive","model","line","p_model","p_naive","lean"}] -> the scorecard numbers."""
    n = len(cases)
    if not n:
        return {"n": 0}
    mae_m = sum(abs(c["model"] - c["actual"]) for c in cases) / n
    mae_n = sum(abs(c["naive"] - c["actual"]) for c in cases) / n
    preds = [(c["p_model"], c["actual"] > PE.threshold(c["line"])) for c in cases if c.get("p_model") is not None]
    naive_preds = [(c["p_naive"], c["actual"] > PE.threshold(c["line"])) for c in cases if c.get("p_naive") is not None]
    leans = [c for c in cases if c["lean"] in ("Over", "Under")]
    lean_hits = sum(1 for c in leans if (c["actual"] > PE.threshold(c["line"])) == (c["lean"] == "Over"))
    direction = [c for c in cases if abs(c["model"] - PE.threshold(c["line"])) > 1e-9]
    dir_hits = sum(1 for c in direction if (c["model"] > PE.threshold(c["line"])) == (c["actual"] > PE.threshold(c["line"])))
    return {
        "n": n, "mae_model": mae_m, "mae_naive": mae_n,
        "mae_gain_pct": (mae_n - mae_m) / mae_n * 100 if mae_n else None,
        "brier_model": PE.brier(preds), "brier_naive": PE.brier(naive_preds), "brier_coin": 0.25,
        "lean_n": len(leans), "lean_hits": lean_hits,
        "lean_rate": lean_hits / len(leans) if leans else None,
        "side_rate": dir_hits / len(direction) if direction else None,
        "buckets": PE.calibration_buckets(preds),
        "slope": PE.fitted_slope(preds),
    }


# --------------------------------------------------------------------------- basketball
def backtest_basketball(pgames: Sequence[Dict], sport: str, market: str, max_cases: int = MAX_CASES,
                        min_history: int = MIN_HISTORY) -> Dict:
    dist = PPR.DIST.get(market, "normal")
    pg = [p for p in pgames or [] if p.get("order") is not None]
    by_player: Dict = {}
    for p in pg:
        if PE.num((p.get("stats") or {}).get("min")) > 0:
            by_player.setdefault(p["pid"], []).append(p)
    for lst in by_player.values():
        lst.sort(key=lambda p: _date(p["order"]), reverse=True)
    team_dates: Dict = {}
    for p in pg:
        team_dates.setdefault(p["team"], set()).add(_date(p["order"]))
    team_games: Dict = {}
    for p in pg:
        team_games.setdefault(p["team"], {}).setdefault(p["game"], _date(p["order"]))
    lineup: Dict = {}
    for p in pg:
        if PE.num((p.get("stats") or {}).get("min")) > 0:
            lineup.setdefault((p["game"], p["team"]), set()).add(p["pid"])
    tables: Dict[str, Dict] = {}

    def table_for(d: str) -> Dict:
        if d not in tables:
            tables[d] = PPR.defense_allowed(PM.allowed_by_slot([q for q in pg if _date(q["order"]) < d], sport), market)
        return tables[d]

    def prev_date(team, d):
        earlier = [x for x in team_dates.get(team, ()) if x < d]
        return max(earlier) if earlier else None

    cases: List[Dict] = []
    targets = sorted(pg, key=lambda p: _date(p["order"]), reverse=True)
    for p in targets:
        if len(cases) >= max_cases:
            break
        if PE.num((p.get("stats") or {}).get("min")) <= 0:
            continue
        slot = PM.position_group(p.get("pos"))
        if slot is None:
            continue
        d = _date(p["order"])
        hist = [q for q in by_player.get(p["pid"], []) if _date(q["order"]) < d][:PPR.HIT_N]
        if len(hist) < min_history:
            continue
        vals = [PPR.market_value(q.get("stats") or {}, market) for q in hist]
        mins = [PE.num((q.get("stats") or {}).get("min")) for q in hist]
        actual = PPR.market_value(p.get("stats") or {}, market)
        naive = sum(vals[:5]) / len(vals[:5])
        rate, proj_min = PE.rate_and_opportunity(vals, mins)
        if rate is None:
            continue
        # next man up: regulars of this team (2 of its last 3 games, 20+ min) who sat this one
        recent_team = sorted([g for g, gd in team_games.get(p["team"], {}).items() if gd < d],
                             key=lambda g: team_games[p["team"]][g], reverse=True)[:PE.FRESH_OUT_GAMES]
        here = lineup.get((p["game"], p["team"]), set())
        mates, seen = [], set()
        for g in recent_team:
            for pid in lineup.get((g, p["team"]), set()):
                if pid in seen:
                    continue
                seen.add(pid)
                mh = [q for q in by_player.get(pid, []) if _date(q["order"]) < d][:PPR.HIT_N]
                r_, o_ = PE.rate_and_opportunity([PPR.market_value(q.get("stats") or {}, market) for q in mh],
                                                 [PE.num((q.get("stats") or {}).get("min")) for q in mh])
                if r_ is None:
                    continue
                absent = pid not in here
                played = sum(1 for gg in recent_team if pid in lineup.get((gg, p["team"]), set()))
                if absent and (played < 2 or (o_ or 0) < 20):
                    continue                                   # not a regular: his absence moves nothing
                mates.append({"pid": pid, "name": str(pid), "slot": PM.position_group(mh[0].get("pos")),
                              "opp": o_ or 0.0, "rate": r_, "out": absent, "fresh": absent})
        if not any(m["pid"] == p["pid"] for m in mates):
            mates.append({"pid": p["pid"], "name": "self", "slot": slot, "opp": proj_min, "rate": rate, "out": False})
        sh = PE.redistribute(mates, cap=42.0).get(p["pid"], {"opp_add": 0.0, "rate_mult": 1.0})
        pd_, od_ = prev_date(p["team"], d), prev_date(p["opp"], d)
        rest = PE.rest_effect(_days_between(pd_, d) if pd_ else None, _days_between(od_, d) if od_ else None,
                              proj_min, "basketball")
        rf = PPR.raw_factor(table_for(d), p["opp"], slot)
        fac = PPR.blended_factor(rf, None, "season")["factor"]
        model = rate * sh["rate_mult"] * rest["rate_mult"] * (proj_min + sh["opp_add"]) * rest["opp_mult"] * fac
        line = proxy_line(vals)
        p_model = PE.prob_over(model, vals, line, dist)
        p_naive = PE.prob_over(naive, vals, line, dist)
        read = PE.read_line(model, vals, line, dist)
        cases.append({"actual": actual, "naive": naive, "model": model, "line": line, "p_model": p_model,
                      "p_naive": p_naive, "lean": read["lean"], "date": d, "pid": p["pid"]})
    out = summarize(cases)
    out["dates"] = (min(c["date"] for c in cases), max(c["date"] for c in cases)) if cases else None
    return out


# --------------------------------------------------------------------------- hockey
def backtest_hockey(pgames: Sequence[Dict], market: str, max_cases: int = MAX_CASES,
                    min_history: int = MIN_HISTORY) -> Dict:
    import hockey_props as HP
    m = HP.MARKETS[market]
    pg = [p for p in pgames or [] if p.get("order") is not None]
    role = m["role"]
    cases: List[Dict] = []
    for p in sorted(pg, key=lambda x: _date(x["order"]), reverse=True):
        if len(cases) >= max_cases:
            break
        st = p.get("stats") or {}
        if p.get("role") != role or PE.num(st.get("toi")) <= 0 or (role == "goalie" and not st.get("gs")):
            continue
        d = _date(p["order"])
        before = [q for q in pg if _date(q["order"]) < d]
        hist = [q for q in HP._games(before, p["pid"], role=role)]
        if len(hist) < min_history:
            continue
        vals = [PE.num((q.get("stats") or {}).get(m["stat"])) for q in hist]
        opps = [PE.num((q.get("stats") or {}).get("sa" if role == "goalie" else "toi")) for q in hist]
        rate, opp = PE.rate_and_opportunity(vals, opps)
        if rate is None:
            continue
        of = HP.opponent_factor(before, p["opp"], m["opp_side"], m["opp_stat"])
        fac = of["factor"] if of else 1.0
        model = rate * (opp or 0.0) * fac
        naive = sum(vals[:5]) / len(vals[:5])
        line = proxy_line(vals)
        actual = PE.num(st.get(m["stat"]))
        cases.append({"actual": actual, "naive": naive, "model": model, "line": line,
                      "p_model": PE.prob_over(model, vals, line, m["dist"]),
                      "p_naive": PE.prob_over(naive, vals, line, m["dist"]),
                      "lean": PE.read_line(model, vals, line, m["dist"])["lean"], "date": d, "pid": p["pid"]})
    out = summarize(cases)
    out["dates"] = (min(c["date"] for c in cases), max(c["date"] for c in cases)) if cases else None
    return out


# --------------------------------------------------------------------------- football
def backtest_football(pgames: Sequence[Dict], sport: str, market: str, max_cases: int = MAX_CASES,
                      min_history: int = 3) -> Dict:
    import football_props as FP
    m = FP.MARKETS[market]
    if FP.is_special(market):                       # kickers / defenders replay from their own lines (not here)
        out = summarize([])
        out["dates"] = None
        return out
    pg = [p for p in pgames or [] if p.get("order") is not None]
    tgt_ok = FP.has_targets(pg)
    grp_ok = {"Receptions": {"WR", "TE", "RB"}, "Receiving Yards": {"WR", "TE", "RB"}, "Rush Yards": {"RB", "QB"},
              "Rush + Rec Yards": {"RB", "WR", "TE"}, "Pass Yards": {"QB"}, "Passing TDs": {"QB"}, "Rush Attempts": {"RB"},
              "Pass Attempts": {"QB"}, "Pass Completions": {"QB"}, "Targets": {"WR", "TE", "RB"},
              "Interceptions": {"QB"}, "Anytime TD": {"RB", "WR", "TE"}}[market]
    by_player: Dict = {}
    for q in pg:
        by_player.setdefault(q["pid"], []).append(q)
    for lst in by_player.values():
        lst.sort(key=lambda q: q["order"], reverse=True)
    slot_of: Dict = {}
    by_team_game: Dict = {}
    for q in pg:
        by_team_game.setdefault((q["game"], q["team"]), []).append(q)
    for key, lst in by_team_game.items():
        for s_, occ in PM.assign_football_slots(lst).items():
            for q in occ:
                slot_of[(key, q["pid"])] = s_
    tables: Dict = {}
    rates_by_week: Dict = {}
    cases: List[Dict] = []
    for p in sorted(pg, key=lambda x: x["order"], reverse=True):
        if len(cases) >= max_cases:
            break
        pos = "RB" if str(p.get("pos") or "").upper() in ("RB", "FB", "HB") else str(p.get("pos") or "").upper()
        if pos not in grp_ok:
            continue
        wk = p["order"]
        hist = [q for q in by_player.get(p["pid"], []) if q["order"] < wk][:FP.FORM_N]
        if len(hist) < min_history:
            continue
        vals = [FP.market_value(q.get("stats") or {}, market) for q in hist]
        opps = [FP.opportunity(q.get("stats") or {}, m["opp"], tgt_ok) for q in hist]
        if sum(opps) <= 0 or sum(1 for o in opps if o > 0) < min_history:
            continue
        rate, opp = PE.rate_and_opportunity(vals, opps)
        if wk not in rates_by_week:
            before = [q for q in pg if q["order"] < wk]
            rates_by_week[wk] = FP.league_rates(before, market, tgt_ok)
            tables[wk] = FP.defense_table(PM.allowed_by_slot(before, sport), market)
        prior = rates_by_week[wk].get(pos, rate or 0.0)
        k = FP.EFF_SHRINK.get(m["opp"], 40.0)
        n_opp = sum(opps)
        rate = (rate * n_opp + prior * k) / (n_opp + k)
        # the slot he held in this game (usage), for the defense factor
        slot = slot_of.get(((p["game"], p["team"]), p["pid"]))
        fac = PPR.blended_factor(PPR.raw_factor(tables[wk], p["opp"], slot), None, "season")["factor"] if slot else 1.0
        model = rate * opp * fac
        naive = sum(vals[:5]) / len(vals[:5])
        line = 0.5 if market == "Anytime TD" else proxy_line(vals)
        floor = (0.45, 8.0) if m["dist"] == "normal" else (0.25, 1.0)
        actual = FP.market_value(p.get("stats") or {}, market)
        cases.append({"actual": actual, "naive": naive, "model": model, "line": line,
                      "p_model": PE.prob_over(model, vals, line, m["dist"], *floor),
                      "p_naive": PE.prob_over(naive, vals, line, m["dist"], *floor),
                      "lean": PE.read_line(model, vals, line, m["dist"], sd_floor_frac=floor[0],
                                           sd_floor_abs=floor[1])["lean"],
                      "date": str(wk), "pid": p["pid"]})
    out = summarize(cases)
    out["dates"] = (f"week {min(c['date'] for c in cases)}", f"week {max(c['date'] for c in cases)}") if cases else None
    return out


def verdict(card: Dict) -> List[str]:
    """Plain-English reads of a scorecard, for the page."""
    if not card or not card.get("n"):
        return ["Not enough games in the sample to grade the model yet."]
    out = []
    g = card.get("mae_gain_pct")
    if g is not None:
        out.append(f"Projections were {'closer' if g > 0 else 'further'} to the real result than the plain last-5 "
                   f"average by {abs(g):.1f}% ({card['mae_model']:.2f} vs {card['mae_naive']:.2f} off per game).")
    if card.get("lean_rate") is not None and card["lean_n"]:
        be = 0.524
        out.append(f"Leans hit {card['lean_hits']}/{card['lean_n']} ({card['lean_rate']:.0%}) against the proxy line — "
                   + ("above" if card["lean_rate"] > be else "below") + " the 52.4% you need at -110.")
    s = card.get("slope")
    if s is not None:
        if s < 0.85:
            out.append(f"Probabilities run over-confident (slope {s:.2f}): switch on **Apply Scorecard calibration** "
                       "on the Player props tab to shrink them.")
        elif s > 1.15:
            out.append(f"Probabilities run under-confident (slope {s:.2f}) — the model's leans are stronger than it says.")
        else:
            out.append(f"Probabilities are well calibrated (slope {s:.2f}).")
    if card["n"] < 200:
        out.append(f"Only {card['n']} graded player-games — treat every number here as a rough early read.")
    return out


BACKTESTS: Dict[str, Callable] = {"basketball": backtest_basketball, "hockey": backtest_hockey,
                                  "football": backtest_football}
