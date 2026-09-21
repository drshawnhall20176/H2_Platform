"""
slip_suggest.py — the "what should I actually bet?" half of Slip Lab. Pure logic (numpy + the
sibling slip modules): no Streamlit, no network, fully unit-tested.

TWO THINGS, both built on the same leg pool the page shows:

  1. leg_scorecard — for every leg, how likely it is to hit AND how much to trust that number.
     "Hit chance" is the model's probability. "Confidence floor" is the 25th percentile of the
     model's uncertainty (the same Beta "worlds" the pressure test uses, sized by how many games
     stand behind the leg): in three of four plausible worlds the true hit rate is at least this.
     A leg the model likes on 5 games scores a lower floor than the same number on 30 games — which
     is the honest answer to "which leg is most likely to win?". Note what a simulation can and
     cannot do here: it cannot make a leg likelier than the model says (a leg's simulated hit rate
     equals its model probability by construction). What it adds is reliability (the floor, and the
     share of plausible worlds in which the price is +EV) and how legs interact.

  2. suggest_tickets — ready-to-load singles and parlay/pick'em tickets built from the legs the
     MODEL prices (never from market-only legs: with no model view a leg's EV is just minus the
     book's vig, so a "suggestion" from those would be noise). Three strategies, each a different
     answer to "best":
        Safest      — highest chance of a paying ticket, among tickets that are +EV as modelled
        Best value  — biggest EV that still holds when each leg is taken at its confidence floor
        Balanced    — most EV per unit of risk (EV divided by the return's standard deviation)
     Candidates are ranked with fast independent-leg maths, then the finalists are run through the
     full correlated simulation (slip_sim) so what is shown includes same-game correlation and a
     3-point overconfidence haircut.
"""

from __future__ import annotations

import itertools
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

import odds_api as O
import slip_lab as SL
import slip_sim as SIM

FLOOR_Q = 25            # confidence floor = this percentile of the model-uncertainty band
NO_GAME_CAP = 99        # max_per_game value meaning "no limit" (the page uses it when one game is selected)
STRATEGIES = {
    "Safest": "Highest chance the ticket pays, among tickets that are +EV as modelled.",
    "Best value": "Biggest EV that still holds when every leg is taken at its confidence floor.",
    "Balanced": "Most EV per unit of risk (EV divided by the spread of the return).",
}
MODEL_SOURCES = ("model", "yours", None)     # leg["p_source"] values that count as a model view


def is_model_priced(leg: Dict) -> bool:
    """True when the leg's probability is the MODEL's (or the user's own), not just the book's
    no-vig number echoed back. Board legs and hand-typed legs are; menu legs are only once a model
    probability was matched to them or the user typed their own."""
    if leg.get("source") == "menu":
        return leg.get("p_source") in ("model", "yours")
    return leg.get("p_source") in MODEL_SOURCES


# --------------------------------------------------------------------------- scorecard
def _evidence_label(n_eff: float) -> str:
    return "thin" if n_eff < 8 else "ok" if n_eff < 20 else "solid"


def leg_scorecard(legs: Sequence[Dict], *, evidence_mult: float = 1.0, n_worlds: int = 4000,
                  seed: int = 7, floor_q: int = FLOOR_Q) -> List[Dict]:
    """One row per leg, ranked strongest first (by confidence floor, then hit chance).

    Row: id, label, p, floor, ceiling, n_eff, evidence ("thin"/"ok"/"solid"), price, ev_pct,
    ev_floor_pct (EV if the leg only hits at its floor), p_ev_pos (share of uncertainty worlds in
    which the price is +EV — None without a price), edge, rank. Deterministic for a given seed."""
    legs = list(legs)
    if not legs:
        return []
    p = np.array([float(l["p"]) for l in legs])
    nu = np.array([max(3.0, float(l.get("n_eff") or 10.0) * evidence_mult) for l in legs])
    rng = np.random.default_rng(seed)
    worlds = SIM.sample_worlds(p, nu, n_worlds, rng)                 # (W x k) true probabilities
    floors = np.percentile(worlds, floor_q, axis=0)
    ceilings = np.percentile(worlds, 100 - floor_q, axis=0)
    rows = []
    for i, l in enumerate(legs):
        dec = SL.leg_decimal(l)
        row = {
            "id": l["id"], "label": SL.leg_label(l), "game": l.get("game"), "p": float(p[i]),
            "floor": float(floors[i]), "ceiling": float(ceilings[i]), "n_eff": float(nu[i]),
            "evidence": _evidence_label(float(nu[i])), "price": l.get("price"),
            "edge": l.get("edge"), "p_mkt": l.get("p_mkt"),
            "ev_pct": None, "ev_floor_pct": None, "p_ev_pos": None,
        }
        if dec is not None:
            row["ev_pct"] = (p[i] * dec - 1.0) * 100.0
            row["ev_floor_pct"] = (floors[i] * dec - 1.0) * 100.0
            row["p_ev_pos"] = float((worlds[:, i] * dec > 1.0).mean())
        rows.append(row)
    order = sorted(range(len(rows)), key=lambda i: (-rows[i]["floor"], -rows[i]["p"], rows[i]["label"]))
    for rank, i in enumerate(order, 1):
        rows[i]["rank"] = rank
    return [rows[i] for i in order]


def score_lookup(legs: Sequence[Dict], **kw) -> Dict[str, Dict]:
    return {r["id"]: r for r in leg_scorecard(legs, **kw)}


def grade(row: Dict) -> str:
    """One plain word for a scorecard row. Priced legs are graded on value, unpriced (pick'em) on
    the hit chance alone."""
    if row.get("ev_pct") is not None:
        if row["ev_floor_pct"] > 0:
            return "Value"
        if row["ev_pct"] > 0:
            return "Lean"
        return "Priced in"
    p = row["p"]
    return "Strong" if p >= 0.65 else "Lean" if p >= 0.55 else "Coin flip"


# --------------------------------------------------------------------------- fast ticket maths
def _dist(ps: Sequence[float]) -> List[float]:
    d = [1.0]
    for p in ps:
        nxt = [0.0] * (len(d) + 1)
        for h, v in enumerate(d):
            nxt[h] += v * (1.0 - p)
            nxt[h + 1] += v * p
        d = nxt
    return d


def _mult_vector(k: int, decimal: Optional[float], table: Optional[Dict[int, float]]) -> List[float]:
    """Return multiple for each hit count 0..k."""
    if table is not None:
        return [float(table.get(h, 0.0)) for h in range(k + 1)]
    return [0.0] * k + [float(decimal or 0.0)]


def _stats(ps: Sequence[float], mult: Sequence[float]) -> Tuple[float, float, float]:
    """(mean return multiple, standard deviation, P(return > 1)) for independent legs."""
    dist = _dist(ps)
    mean = sum(d * m for d, m in zip(dist, mult))
    second = sum(d * m * m for d, m in zip(dist, mult))
    sd = max(second - mean * mean, 0.0) ** 0.5
    p_pay = sum(d for d, m in zip(dist, mult) if m > 1.0 + 1e-9)
    return mean, sd, p_pay


def _combo_ok(combo: Sequence[Dict], max_per_game: int) -> bool:
    players = [l.get("player") for l in combo]
    if len(set(players)) != len(players):
        return False                                   # one leg per player
    if max_per_game < len(combo):
        per: Dict[str, int] = {}
        for l in combo:
            g = l.get("game") or ""
            if g:
                per[g] = per.get(g, 0) + 1
                if per[g] > max_per_game:
                    return False
    return True


def _pick_modes(book: str) -> List[str]:
    b = O.canonical_book(book)
    return ["power", "flex"] if b == "prizepicks" else ["pick6"] if b == "pick6" else ["parlay"]


# --------------------------------------------------------------------------- the suggester
def suggest_tickets(pool: Sequence[Dict], book: str, *, sizes: Sequence[int] = (2, 3, 4),
                    max_per_game: int = 2, min_leg_p: float = 0.45, n_singles: int = 5,
                    bankroll: float = 1000.0, evidence_mult: float = 1.0, n_candidates: int = 16,
                    require_positive: bool = True, simulate: bool = True, n_sims: int = 6000,
                    n_worlds: int = 80, seed: int = 7) -> Dict:
    """Suggested tickets from the legs in `pool` for `book`.

    Returns {"singles": {"likely": [...], "value": [...]}, "tickets": [...], "notes": [...],
    "eligible": n, "excluded_market_only": n}.  A single: {leg, score, stake}. A ticket: {"mode",
    "k", "strategies": [...], "legs", "decimal"/"table", "p_all_indep", "ev_indep", "ev_floor",
    "p_all", "ev", "ev_haircut", "p_ev_positive", "stake"} — the last five from the correlated
    simulation when `simulate`."""
    book = O.canonical_book(book)
    pickem = O.is_pickem_book(book)
    notes: List[str] = []
    all_legs = list(pool)
    model_legs = [l for l in all_legs if is_model_priced(l)]
    excluded = len(all_legs) - len(model_legs)
    if excluded:
        notes.append(f"{excluded} market-only leg(s) were left out: with no model view their EV is just "
                     "minus the book's margin, so they can't be recommended.")
    posted = [l for l in model_legs if l.get("at_book")]
    if len(posted) < len(model_legs):
        notes.append(f"{len(model_legs) - len(posted)} leg(s) skipped because {O.book_label(book)} doesn't post them.")
    if not pickem:
        posted = [l for l in posted if l.get("price") is not None]
    score = score_lookup(posted, evidence_mult=evidence_mult, seed=seed)

    out: Dict = {"singles": {"likely": [], "value": []}, "tickets": [], "notes": notes,
                 "eligible": len(posted), "excluded_market_only": excluded, "scores": score}
    if not posted:
        notes.append("No model-priced legs are available at this book with the current filters.")
        return out

    # ---- singles (sportsbooks only: a pick'em entry is never a single) ----------------------
    if not pickem:
        by_id = {l["id"]: l for l in posted}

        def single(row: Dict) -> Dict:
            leg = by_id[row["id"]]
            dec = SL.leg_decimal(leg)
            stake = O.kelly_stake(row["floor"], leg["price"], bankroll, fraction=0.25, cap_pct=0.02)
            return {"leg": leg, "score": row, "grade": grade(row), "stake": stake, "decimal": dec}

        likely = sorted(score.values(), key=lambda r: (-r["floor"], -r["p"]))[:n_singles]
        value = sorted([r for r in score.values() if (r["ev_pct"] or 0) > 0],
                       key=lambda r: (-r["ev_floor_pct"], -r["p"]))[:n_singles]
        out["singles"]["likely"] = [single(r) for r in likely]
        out["singles"]["value"] = [single(r) for r in value]
        if not value:
            notes.append("No single is +EV at this book right now, so \"best value\" singles is empty — "
                         "that is the model telling you the prices are fair or worse.")

    # ---- parlays / pick'em entries ---------------------------------------------------------
    cands = [l for l in posted if l["p"] >= min_leg_p]
    if len(cands) < 2:
        notes.append("Fewer than two legs clear the minimum hit chance, so no multi-leg tickets were built. "
                     "Lower the minimum or widen the filters.")
        return out
    top_floor = sorted(cands, key=lambda l: -score[l["id"]]["floor"])
    top_value = sorted([l for l in cands if score[l["id"]]["ev_floor_pct"] is not None],
                       key=lambda l: -score[l["id"]]["ev_floor_pct"])
    picked: List[Dict] = []
    seen_ids = set()

    def _take(l: Optional[Dict]) -> None:
        if l is not None and l["id"] not in seen_ids and len(picked) < n_candidates:
            seen_ids.add(l["id"])
            picked.append(l)

    # alternate the safest legs with the best-value legs so both kinds of ticket have material
    for a, b in itertools.zip_longest(top_floor, top_value):
        _take(a)
        _take(b)
    picked = picked[:n_candidates]

    finalists: Dict[Tuple, Dict] = {}
    for mode in _pick_modes(book):
        for k in sorted(set(int(s) for s in sizes)):
            if k < 2 or k > len(picked):
                continue
            table = SL.default_table(mode, k) if mode != "parlay" else None
            if mode != "parlay" and not table:
                continue
            best: Dict[str, Tuple[float, Tuple]] = {}
            for combo in itertools.combinations(picked, k):
                if not _combo_ok(combo, max_per_game):
                    continue
                decimal = None
                if mode == "parlay":
                    decs = [SL.leg_decimal(l) for l in combo]
                    if any(d is None for d in decs):
                        continue
                    decimal = SIM.parlay_decimal(decs)
                mult = _mult_vector(k, decimal, table)
                ps = [l["p"] for l in combo]
                fl = [score[l["id"]]["floor"] for l in combo]
                mean, sd, _ = _stats(ps, mult)
                mean_f, _, p_pay_f = _stats(fl, mult)
                if require_positive and mean <= 1.0:
                    continue
                keyed = {"Safest": p_pay_f, "Best value": mean_f - 1.0,
                         "Balanced": (mean - 1.0) / sd if sd > 1e-9 else 0.0}
                for strat, val in keyed.items():
                    if strat not in best or val > best[strat][0]:
                        best[strat] = (val, combo)
            if not best:
                notes.append(f"No +EV {k}-leg {'entry' if pickem else 'parlay'} could be built from these legs"
                             + (f" ({mode})." if mode != "parlay" else "."))
            for strat, (_, combo) in best.items():
                key = (mode, k, tuple(sorted(l["id"] for l in combo)))
                rec = finalists.setdefault(key, {"mode": mode, "k": k, "legs": list(combo), "table": table,
                                                 "strategies": []})
                rec["strategies"].append(strat)

    tickets = []
    for rec in finalists.values():
        tickets.append(_finish_ticket(rec, score, bankroll=bankroll, evidence_mult=evidence_mult,
                                      simulate=simulate, n_sims=n_sims, n_worlds=n_worlds, seed=seed))
    order = {s: i for i, s in enumerate(STRATEGIES)}
    tickets.sort(key=lambda t: (min(order[s] for s in t["strategies"]), t["k"], t["mode"]))
    out["tickets"] = tickets
    return out


def _finish_ticket(rec: Dict, score: Dict[str, Dict], *, bankroll: float, evidence_mult: float,
                   simulate: bool, n_sims: int, n_worlds: int, seed: int) -> Dict:
    legs, mode, k, table = rec["legs"], rec["mode"], rec["k"], rec["table"]
    if mode == "parlay":
        payout = {"mode": "parlay", "decimal": SIM.parlay_decimal([SL.leg_decimal(l) for l in legs])}
        decimal = payout["decimal"]
    else:
        payout = {"mode": "table", "table": {int(a): float(b) for a, b in table.items()}}
        decimal = max(table.values())
    mult = _mult_vector(k, payout.get("decimal"), payout.get("table"))
    ps = [l["p"] for l in legs]
    mean, _sd, p_pay = _stats(ps, mult)
    mean_f, _, p_pay_f = _stats([score[l["id"]]["floor"] for l in legs], mult)
    t = {"mode": mode, "k": k, "strategies": list(rec["strategies"]), "legs": legs, "payout": payout,
         "decimal": decimal, "table": table, "p_all_indep": float(np.prod(ps)),
         "p_pay_indep": p_pay, "ev_indep": mean - 1.0, "ev_floor": mean_f - 1.0,
         "p_all": None, "ev": None, "ev_haircut": None, "p_ev_positive": None, "stake": None}
    if simulate:
        sim_legs = [dict(l, n_eff=max(3.0, float(l.get("n_eff") or 10.0) * evidence_mult),
                         label=SL.leg_label(l)) for l in legs]
        base = SIM.evaluate(sim_legs, payout, n_sims=n_sims, n_worlds=n_worlds, seed=seed)
        hc = SIM.evaluate(sim_legs, payout, n_sims=n_sims, n_worlds=n_worlds, seed=seed, haircut=0.03,
                          _Z=base["Z"], _worlds=base["worlds"])
        t.update({"p_all": base["p_all"], "ev": base["ev"], "ev_haircut": hc["ev"],
                  "p_ev_positive": base["p_ev_positive"], "p_profit": base["p_profit"]})
        # Stake: quarter-Kelly on the haircut probability, only for an all-or-nothing payout.
        if len(payout.get("table", {1: 1})) == 1 or mode == "parlay":
            d = payout.get("decimal") or list(payout["table"].values())[0]
            am = SL.decimal_to_american(d)
            if am:
                t["stake"] = O.kelly_stake(hc["p_all"], am, bankroll, fraction=0.25, cap_pct=0.02)
    return t


def ticket_title(t: Dict) -> str:
    kind = {"parlay": "parlay", "power": "Power Play", "flex": "Flex Play", "pick6": "Pick6"}[t["mode"]]
    return f"{t['k']}-leg {kind}"
