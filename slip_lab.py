"""
slip_lab.py — the pure logic behind the Slip Lab page: turn a board of model plays plus real
sportsbook offers into a pool of bettable LEGS for one chosen book, price a slip built from them,
and hand it to slip_sim for pressure-testing. No Streamlit and no network in here, so all of it is
unit-tested.

THREE KINDS OF BOOK, because the same "leg" means different things at each:
  - a SPORTSBOOK (DraftKings, FanDuel, Hard Rock Bet, ...): each side of a prop has an American
    price. A single pays at that price; a parlay pays the product of its legs' decimal prices.
  - a PICK'EM app (PrizePicks, DK Pick6): a fixed line and NO per-leg price. The entry pays a
    multiplier that depends only on how many picks are in it (and, for Flex, how many hit).
  - a MANUAL book (Bet365): The Odds API has no US player-prop feed for it, so the line and price
    are typed in by hand.

A leg's model probability comes straight from the same play the Best Bets board already computed
(the sport's own projection module, shrunk for small samples) — Slip Lab never re-models anything,
so a number here always matches the number on Best Bets for the same play and line. The other side
of a prop is 1 minus it (exact at a half-point line; the model does not price pushes on whole-number
lines).
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

import odds_api as O
import slip_sim as SIM

PICKEM_MODE_LABELS = {
    "power": "Power Play — every pick must hit",
    "flex": "Flex Play — pays for most picks hitting",
    "pick6": "Pick6 — base payout, every pick must hit",
}


def _is_over(side: Optional[str]) -> bool:
    s = str(side or "").strip().lower()
    return s.startswith("o") or s in ("yes", "y", "more", "higher")


def _side_word(over: bool) -> str:
    return "Over" if over else "Under"


def leg_id(player, market, side, line) -> str:
    """Stable identity for a leg. A Yes-only market (anytime HR/TD) has no line: its id ends in '-'."""
    if line is None:
        return f"{player}|{market}|{side}|-"
    return f"{player}|{market}|{side}|{line:g}" if isinstance(line, (int, float)) else f"{player}|{market}|{side}|{line}"


def leg_label(leg: Dict) -> str:
    line = leg.get("line")
    line_s = "" if line is None else (f" {line:g}" if isinstance(line, (int, float)) else f" {line}")
    return f"{leg.get('player')} · {leg.get('market')} {leg.get('side')}{line_s}"


# --------------------------------------------------------------------------- pool from the board
def _novig_over(off: Dict, book: Optional[str]) -> Optional[float]:
    """No-vig P(Over) at one point: the chosen book's own two-sided price when it posted both
    sides, otherwise the average across every sportsbook that did. None if no book posted both."""
    over, under = off.get("over") or {}, off.get("under") or {}
    if book in over and book in under:
        v = O.devig_two_way(over[book], under[book])
        if v is not None:
            return v
    vals = [O.devig_two_way(over[b], under[b]) for b in set(over) & set(under)]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _best_price(prices: Dict[str, float]) -> Tuple[Optional[str], Optional[float]]:
    if not prices:
        return None, None
    b, pr = max(prices.items(), key=lambda kv: O.american_to_decimal(kv[1]))
    return b, pr


def build_leg_pool(plays: List[Dict], offers: List[Dict], book: str, market_map: Dict[str, str],
                   normalize_name: Callable[[str], str],
                   single_line_markets: Optional[set] = None) -> List[Dict]:
    """One leg per (play, side) for the chosen `book`.

    Each leg: id, player, player_id, team, game, opp, market, side, line, p (model probability),
    n_eff (games behind it), price (American, at THIS book, None if not posted), best_price /
    best_book (best across sportsbooks at this exact point), p_mkt (no-vig market probability),
    edge (p - p_mkt), ev_pct (at this book's price), at_book (this book actually posts this
    leg), conviction, why, game_date, line_source, play (the original play dict, for logging).
    """
    book = O.canonical_book(book)
    pickem_book = O.is_pickem_book(book)
    singles = single_line_markets or set()
    index: Dict[Tuple[str, str], List[Dict]] = {}
    for off in offers or []:
        index.setdefault((normalize_name(off.get("player", "")), off.get("market")), []).append(off)

    legs: List[Dict] = []
    for pl in plays or []:
        player = pl.get("Player")
        line = pl.get("Line")
        mkey = market_map.get(pl.get("Market"))
        yes_only = mkey in singles                  # anytime HR/TD: no line, matched on player+market
        if not player or pl.get("ModelProb") is None or (line is None and not yes_only):
            continue
        off = None
        cands = index.get((normalize_name(player), mkey), [])
        if yes_only:
            off = cands[0] if cands else None
        else:
            for cand in cands:
                try:
                    if abs(float(cand.get("point")) - float(line)) < 1e-9:
                        off = cand
                        break
                except (TypeError, ValueError):
                    continue
        p_fav = float(pl["ModelProb"])
        fav_over = _is_over(pl.get("Side"))
        p_over = p_fav if fav_over else 1.0 - p_fav
        # A genuine Over/Under market gets both legs; a Yes-only market (anytime TD) only the one.
        two_sided = str(pl.get("Side", "")).strip().lower() in ("over", "under")
        novig_over = _novig_over(off, book) if off else None
        n_games = len(pl.get("_game_log") or []) or None

        for over in (True, False):
            side = _side_word(over)
            if over != fav_over and not two_sided:
                continue
            if not two_sided and str(pl.get("Side", "")).strip().lower() == "yes":
                side = "Yes"
            p = p_over if over else 1.0 - p_over
            prices = ((off or {}).get("over") if over else (off or {}).get("under")) or {}
            price = prices.get(book) if not pickem_book else None
            best_book, best_price = _best_price(prices)
            p_mkt = None if novig_over is None else (novig_over if over else 1.0 - novig_over)
            pk = ((off or {}).get("pickem") or {}).get(book) if pickem_book else None
            at_book = (pk is not None) if pickem_book else (price is not None)
            ev_pct = None
            if price is not None:
                ev_pct = round((p * O.american_to_decimal(price) - 1.0) * 100.0, 2)
            legs.append({
                "id": leg_id(player, pl.get("Market"), side, None if line is None else float(line)),
                "player": player, "player_id": pl.get("PlayerId"), "team": pl.get("Team"),
                "game": pl.get("Game"), "opp": pl.get("Opp") or pl.get("Versus"),
                "market": pl.get("Market"), "side": side, "line": None if line is None else float(line),
                "p": round(p, 4), "n_eff": n_games or 10,
                "price": price, "best_price": best_price, "best_book": best_book,
                "p_mkt": None if p_mkt is None else round(p_mkt, 4),
                "edge": None if p_mkt is None else round(p - p_mkt, 4),
                "ev_pct": ev_pct, "at_book": at_book, "book": book,
                "conviction": pl.get("Conviction") if over == fav_over else None,
                "why": pl.get("Why"), "game_date": pl.get("GameDate") or pl.get("GameTime"),
                "line_source": pl.get("LineSource"), "source": "board", "play": pl,
            })
    return legs


# --------------------------------------------------------------------------- manual legs
def empirical_over_prob(values: Sequence[float], line: float, reference: float = 0.5) -> Optional[float]:
    """P(stat > line) from a player's recent games (a push counts half), shrunk toward `reference`
    by the same small-sample rule the model uses everywhere (basketball_projections.shrink_prob).
    None when there are no games."""
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    raw = sum(1.0 if v > line else 0.5 if v == line else 0.0 for v in vals) / len(vals)
    import basketball_projections as BB_P
    return float(BB_P.shrink_prob(raw, len(vals), reference=reference))


def manual_leg(*, player: str, market: str, side: str, line: float, p: float,
               price: Optional[float] = None, game: Optional[str] = None, team: Optional[str] = None,
               n_eff: float = 10.0, book: Optional[str] = None, player_id=None,
               p_mkt: Optional[float] = None, why: str = "entered by hand") -> Dict:
    """A leg typed in by hand (Bet365, or any line the board doesn't have). `p` is the model
    probability of THIS side; price is the American price if there is one."""
    over = _is_over(side)
    sd = _side_word(over)
    ev_pct = None if price is None else round((p * O.american_to_decimal(price) - 1.0) * 100.0, 2)
    return {
        "id": leg_id(player, market, sd, float(line)), "player": player, "player_id": player_id,
        "team": team, "game": game or "", "opp": None, "market": market, "side": sd,
        "line": float(line), "p": round(float(p), 4), "n_eff": float(n_eff), "price": price,
        "best_price": price, "best_book": O.canonical_book(book) or None, "p_mkt": p_mkt,
        "edge": None if p_mkt is None else round(p - p_mkt, 4), "ev_pct": ev_pct,
        "at_book": True, "book": O.canonical_book(book), "conviction": None, "why": why,
        "game_date": None, "line_source": "manual", "source": "manual", "play": None,
    }


# --------------------------------------------------------------------------- pricing a slip
def leg_decimal(leg: Dict) -> Optional[float]:
    return None if leg.get("price") is None else O.american_to_decimal(leg["price"])


def poisson_binomial(probs: Sequence[float]) -> List[float]:
    """Exact P(exactly j of the legs hit), j = 0..k, for INDEPENDENT legs."""
    dist = np.array([1.0])
    for p in probs:
        dist = np.convolve(dist, [1.0 - float(p), float(p)])
    return dist.tolist()


def default_table(mode: str, k: int) -> Optional[Dict[int, float]]:
    tbl = SIM.PAYOUT_TABLES.get(mode, {}).get(k)
    return dict(tbl) if tbl else None


def slip_payout(mode: str, legs: List[Dict], *, decimal_override: Optional[float] = None,
                table: Optional[Dict[int, float]] = None, stakes: Optional[Sequence[float]] = None
                ) -> Optional[Dict]:
    """The payout dict slip_sim understands, or None if the slip can't be priced.

      "singles"           each leg a straight bet at its own price (needs `stakes`)
      "parlay"            all-or-nothing at the product of the legs' decimal prices, or
                          `decimal_override` (the price the sportsbook's own slip actually shows —
                          use it: books apply their own same-game-parlay adjustments)
      "power"/"flex"/"pick6"   PrizePicks / Pick6 multiplier table for len(legs) picks (`table`
                          overrides the built-in one)
    """
    k = len(legs)
    if k == 0:
        return None
    if mode == "singles":
        decs = [leg_decimal(l) for l in legs]
        if any(d is None for d in decs):
            return None
        stk = list(stakes) if stakes is not None else [1.0] * k
        return {"mode": "singles", "decimals": decs, "stakes": stk}
    if mode == "parlay":
        if k < 2:
            return None
        if decimal_override:
            return {"mode": "parlay", "decimal": float(decimal_override)}
        decs = [leg_decimal(l) for l in legs]
        if any(d is None for d in decs):
            return None
        return {"mode": "parlay", "decimal": SIM.parlay_decimal(decs)}
    if mode in SIM.PAYOUT_TABLES:
        tbl = table or default_table(mode, k)
        if not tbl:
            return None
        return {"mode": "table", "table": {int(a): float(b) for a, b in tbl.items()}}
    raise ValueError(f"unknown slip mode {mode!r}")


def headline(legs: List[Dict], payout: Dict) -> Dict:
    """Instant, simulation-free numbers for a slip (legs treated as independent): joint
    probability, fair vs offered price, EV per $1, and the hit-count distribution."""
    k = len(legs)
    ps = [l["p"] for l in legs]
    dist = poisson_binomial(ps)
    out = {"k": k, "p_all_independent": dist[k], "hit_dist": dist}
    if payout["mode"] == "singles":
        evs = [l["p"] * d - 1.0 for l, d in zip(legs, payout["decimals"])]
        stk = payout["stakes"]
        tot = sum(stk) or 1.0
        out["ev_per_dollar"] = sum(e * s for e, s in zip(evs, stk)) / tot
        out["leg_ev"] = evs
        return out
    if payout["mode"] == "parlay":
        d = payout["decimal"]
        out["offered_decimal"] = d
        out["fair_decimal"] = (1.0 / dist[k]) if dist[k] > 0 else None
        out["ev_per_dollar"] = dist[k] * d - 1.0
        out["breakeven_leg_prob"] = SIM.breakeven_leg_prob(d, k)
        return out
    tbl = payout["table"]
    out["ev_per_dollar"] = sum(dist[h] * m for h, m in tbl.items() if 0 <= h <= k) - 1.0
    top = tbl.get(k)
    out["offered_decimal"] = top
    out["fair_decimal"] = (1.0 / dist[k]) if dist[k] > 0 else None
    out["breakeven_leg_prob"] = SIM.breakeven_leg_prob(top, k) if len(tbl) == 1 else None
    return out


def payout_for_subset_factory(mode: str, *, decimal_override: Optional[float], tables: Optional[Dict],
                              stakes: Optional[Sequence[float]] = None):
    """A payout_for_subset(legs) for slip_sim.leg_drop_table: the smaller slip's payout when a leg
    is removed. A typed-in parlay price can't be re-derived for a subset, so the leg-drop view
    uses the product of the remaining legs' own prices instead (and says so)."""
    def f(sub: List[Dict]) -> Dict:
        if mode == "singles":
            return slip_payout("singles", sub)
        if mode == "parlay":
            p = slip_payout("parlay", sub)
            if p is None:
                raise ValueError("cannot price")
            return p
        p = slip_payout(mode, sub, table=(tables or {}).get(len(sub)))
        if p is None:
            raise KeyError(len(sub))
        return p
    return f


# --------------------------------------------------------------------------- Bet Log hand-off defaults
def quick_log_prefill(prefix: str, mode: str, stake: float, stakes: Optional[Sequence[float]], n_legs: int,
                      max_stake: float = 500.0) -> Dict:
    """Session-state values that make the shared quick-log widget open on THE SLIP THAT WAS TESTED
    — every leg ticked, parlay-vs-singles logging matching the slip's mode, and the stake filled in
    (quick_log's stake pickers move in 0.5 steps, so the value is rounded to the nearest half dollar
    and capped at `max_stake`). Singles use the average stake, since the widget has one per-pick box."""
    def near(x: float) -> float:
        return float(min(max_stake, max(0.0, round(float(x) * 2) / 2)))

    out: Dict = {f"{prefix}_ql_picks": list(range(n_legs))}
    if mode == "singles":
        stk = [float(x) for x in (stakes or []) if x is not None]
        per = near(sum(stk) / len(stk)) if stk else 0.0
        out.update({f"{prefix}_ql_mode_parlay": False, f"{prefix}_ql_mode_singles": True,
                    f"{prefix}_ql_s_stake_pick": per, f"{prefix}_ql_s_stake_{per}": per})
    else:
        amt = near(stake)
        out.update({f"{prefix}_ql_mode_parlay": True, f"{prefix}_ql_mode_singles": False,
                    f"{prefix}_ql_p_stake_pick": amt, f"{prefix}_ql_p_stake_{amt}": amt})
    return out


# --------------------------------------------------------------------------- can two legs share a slip?
TEAM_KINDS = ("moneyline", "spread", "total", "team_total")


def conflicts(existing: Sequence[Dict], cand: Dict) -> Optional[str]:
    """Why `cand` cannot go on a slip that already holds `existing` (None = it can).

    Two bets on the two sides of the SAME proposition can't both win, so a slip holding both is
    nonsense: the other side of the same prop (same subject, market and line), or the opposing
    team's moneyline / spread in the same market of the same game. A middle (Over 44.5 with
    Under 47.5) is a real, deliberate bet and is allowed."""
    for x in existing:
        if x["id"] == cand["id"]:
            return "that leg is already on the slip"
        if (x["player"], x["market"], x["line"]) == (cand["player"], cand["market"], cand["line"]):
            return "the slip already has the other side of that prop"
        margin = ("moneyline", "spread")
        if (x.get("kind") in margin and cand.get("kind") in margin and x.get("game") == cand.get("game")
                and x.get("market_key") == cand.get("market_key") and x.get("kind") == cand.get("kind")
                and x.get("team") != cand.get("team")):
            return "it opposes a team leg already on the slip (the other side of that game's result)"
    return None


# --------------------------------------------------------------------------- hand-off to Bet Log
def legs_to_plays(legs: List[Dict]) -> List[Dict]:
    """Play-shaped dicts (what quick_log.render_quick_log / bet_log_fields_from_play expect) so a
    slip that has been pressure-tested can be logged with the SAME machinery every other page
    uses. A leg with a real price at the chosen book carries it as RealPrice/PriceSource="book"
    (so the Bet Log records a real entry price for CLV); a leg without one falls back to the
    model's own fair price, exactly as quick_log always has."""
    from projections import prob_to_american
    out = []
    for l in legs:
        p = float(l["p"])
        play = dict(l.get("play") or {})
        team_level = l.get("kind") in TEAM_KINDS
        side = l["side"]
        if team_level and l.get("kind") in ("moneyline", "spread"):
            side = l["player"]                       # the team backed, exactly as Game Watch logs a moneyline
        elif l.get("kind") == "team_total":
            side = f"{l['player']} {l['side']}"
        play.update({
            "Player": None if team_level else l["player"], "PlayerId": None if team_level else l.get("player_id"),
            "Team": l.get("team"), "Game": l.get("game"), "Opp": l.get("opp"), "Market": l["market"],
            "Side": side, "Line": l["line"], "ModelProb": p, "Fair": prob_to_american(p),
            "Why": l.get("why") or play.get("Why"),
        })
        if l.get("price") is not None:
            play.update({"RealPrice": l["price"], "PriceSource": "book", "RealPriceBook": l.get("book")})
        else:
            play.update({"RealPrice": None, "PriceSource": "model_fair"})
        out.append(play)
    return out


# --------------------------------------------------------------------------- pressure test
def decimal_to_american(d: Optional[float]) -> Optional[int]:
    if d is None or d <= 1:
        return None
    return int(round((d - 1) * 100)) if d >= 2 else int(round(-100 / (d - 1)))


def total_stake(mode: str, stake: float, stakes: Optional[Sequence[float]]) -> float:
    return float(sum(stakes)) if mode == "singles" and stakes is not None else float(stake)


def run_pressure_test(legs: List[Dict], mode: str, payout: Dict, *, stake: float, bankroll: float,
                      stakes: Optional[Sequence[float]] = None, tables: Optional[Dict] = None,
                      decimal_override: Optional[float] = None, rho_player: float = 0.30,
                      rho_game: float = 0.08, evidence_mult: float = 1.0, n_sims: int = 20000,
                      n_slips: int = 100, seed: int = 7) -> Dict:
    """Everything the Slip Lab results panel shows, in one call: the baseline simulation, the
    stress scenarios, the leg-drop table, the repeat-play projection and the plain-language
    verdict. Returns light-weight (JSON-able) data only — the big random arrays stay inside."""
    sim_legs = [dict(l, n_eff=max(3.0, float(l.get("n_eff") or 10.0) * evidence_mult),
                     label=leg_label(l)) for l in legs]
    kw = dict(rho_player=rho_player, rho_game=rho_game, n_sims=n_sims, seed=seed)
    base = SIM.evaluate(sim_legs, payout, n_worlds=200, **kw)
    scenarios = SIM.stress_scenarios(sim_legs, payout, n_worlds=200, **kw)
    drops: List[Dict] = []
    if len(sim_legs) >= 2 and mode != "singles":
        drops = SIM.leg_drop_table(
            sim_legs, payout_for_subset_factory(mode, decimal_override=None, tables=tables),
            rho_player=rho_player, rho_game=rho_game, n_sims=max(5000, n_sims // 2), n_worlds=80, seed=seed)
    elif mode == "singles":
        for l, s_leg in zip(sim_legs, payout["decimals"]):
            drops.append({"leg": l["label"], "ev_without": None, "p_profit_without": None,
                          "delta_ev": l["p"] * s_leg - 1.0})
    tot = total_stake(mode, stake, stakes)
    repeat = SIM.repeat_play(base["R"], stake_fraction=(tot / bankroll) if bankroll > 0 else 0.0,
                             n_slips=n_slips, seed=seed)
    ps = [l["p"] for l in sim_legs]
    result = {
        "mode": mode, "k": len(sim_legs), "stake": tot,
        "ev": base["ev"], "p_profit": base["p_profit"], "p_total_loss": base["p_total_loss"],
        "p_all": base["p_all"], "p_all_independent": base["p_all_independent"],
        "ev_p05": base["ev_p05"], "ev_p50": base["ev_p50"], "ev_p95": base["ev_p95"],
        "p_ev_positive": base["p_ev_positive"], "hit_dist": base["hit_dist"],
        "hit_dist_independent": poisson_binomial(ps), "leg_hit_rate": base["leg_hit_rate"],
        "scenarios": scenarios, "leg_drop": drops, "repeat": repeat,
        "avg_n_eff": float(np.mean([l["n_eff"] for l in sim_legs])),
        "settings": {"rho_player": rho_player, "rho_game": rho_game, "evidence_mult": evidence_mult,
                     "n_sims": n_sims},
    }
    if payout["mode"] == "parlay":
        d = payout["decimal"]
        result["breakeven_leg_prob"] = SIM.breakeven_leg_prob(d, len(sim_legs))
        result["kelly_fraction"] = O.kelly_fraction(base["p_all"], decimal_to_american(d) or 0)
    elif payout["mode"] == "table" and len(payout["table"]) == 1:
        d = list(payout["table"].values())[0]
        result["breakeven_leg_prob"] = SIM.breakeven_leg_prob(d, len(sim_legs))
        result["kelly_fraction"] = O.kelly_fraction(base["p_all"], decimal_to_american(d) or 0)
    result["n_market_prob"] = sum(1 for l in legs if l.get("source") == "menu"
                                  and l.get("p_source") in ("market", "implied"))
    result["geo_mean_leg_prob"] = float(np.exp(np.mean(np.log(np.clip(ps, 1e-6, 1)))))
    result["verdict"] = verdict(result)
    return result


def verdict(r: Dict) -> List[Tuple[str, str]]:
    """Plain-language read of a pressure-test result: [(level, text)], level in
    "good" / "warn" / "bad" / "info". The rules are deliberately simple and stated in the text so
    the reader can see WHY it says what it says; they are guidance, not a betting recommendation."""
    out: List[Tuple[str, str]] = []
    rows = {s["scenario"]: s for s in r["scenarios"]}
    ev = r["ev"]
    h3 = rows.get("Model 3 pts too bullish", {}).get("ev")
    h5 = rows.get("Model 5 pts too bullish", {}).get("ev")
    nm_all = (r.get("n_market_prob") or 0) >= r["k"]
    if nm_all:
        out.append(("info", f"Priced entirely off the book's own probabilities: {ev*100:+.1f}% EV per $1 — the book's "
                            "margin, as expected when nobody has a view. Enter your own probability on a leg to test "
                            "an actual opinion."))
    elif ev <= 0:
        out.append(("bad", f"The model itself has this slip losing money: {ev*100:+.1f}% EV per $1 at these "
                           "prices, before any stress."))
    elif h5 is not None and h5 > 0 and r["p_ev_positive"] >= 0.70:
        out.append(("good", f"Holds up: still {h5*100:+.1f}% EV if the model is 5 points too bullish on "
                            f"every leg, and +EV in {r['p_ev_positive']*100:.0f}% of the uncertainty worlds."))
    elif h3 is not None and h3 > 0:
        out.append(("warn", f"Moderately robust: survives a 3-point overconfidence haircut "
                            f"({h3*100:+.1f}% EV) but not a 5-point one"
                            + (f" ({h5*100:+.1f}%)." if h5 is not None else ".")))
    else:
        out.append(("warn", f"Fragile: +{ev*100:.1f}% EV as modelled, but the edge is gone if the model is "
                            "just 3 points too bullish."))
    book = rows.get("If the book's no-vig price is right")
    if book is not None:
        if book["ev"] < 0:
            out.append(("info", f"If the book's own no-vig probabilities are right, this slip is "
                                f"{book['ev']*100:+.1f}% EV — the edge exists only if the model beats the market."))
        else:
            out.append(("good", f"Even if the book's own no-vig probabilities are right the slip is "
                                f"{book['ev']*100:+.1f}% EV — the edge isn't just model-vs-market disagreement."))
    if r["k"] >= 2 and r["p_all_independent"] > 0:
        ratio = r["p_all"] / r["p_all_independent"]
        if abs(ratio - 1) >= 0.10:
            out.append(("info", f"Correlation matters here: the legs hit together {r['p_all']*100:.1f}% of "
                                f"the time vs {r['p_all_independent']*100:.1f}% if independent "
                                f"({(ratio-1)*100:+.0f}%). Check your book's parlay price reflects it."))
    drops = [d for d in r["leg_drop"] if d.get("delta_ev") is not None]
    if len(drops) >= 2 and r["mode"] != "singles":
        worst = min(drops, key=lambda d: d["delta_ev"])
        if worst["delta_ev"] < 0:
            out.append(("warn", f"Weakest leg: {worst['leg']} — the slip is {abs(worst['delta_ev'])*100:.1f} "
                                "EV-points better without it."))
    nm = r.get("n_market_prob") or 0
    if nm:
        out.append(("info", f"{nm} of {r['k']} leg{'s' if r['k'] != 1 else ''} use the book's own probability "
                            "(no model view of them), so there is no edge built into "
                            f"{'those legs' if nm < r['k'] else 'this slip'}: their EV is minus the book's margin by "
                            "construction. What the test tells you there is how the legs interact and how wide the "
                            "outcomes are — not whether the bet is +EV. Type your own probability into the slip "
                            "table to test a view."))
    if r["avg_n_eff"] < 8:
        out.append(("warn", f"Thin evidence: about {r['avg_n_eff']:.0f} games behind each leg on average, so the "
                            "uncertainty band is wide — early-season slips deserve extra skepticism."))
    rp = r["repeat"]
    if rp["p_ahead"] is not None:
        out.append(("info", f"Run {rp['n_slips']} times at this stake, you'd finish ahead in "
                            f"{rp['p_ahead']*100:.0f}% of simulated runs; median result "
                            f"{(rp['final_p50']-1)*100:+.0f}% of bankroll, worst 5% {(rp['final_p05']-1)*100:+.0f}%."))
    return out
