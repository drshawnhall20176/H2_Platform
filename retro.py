"""
retro.py — grade the model's pre-game board against what actually happened.
 
This is a MODEL REVIEW, not an outlier-explainer. It scores the probabilities the model
assigned BEFORE the games against real results — it never hunts for new variables to
explain a specific surprise after the fact (that's overfitting, the thing that quietly
destroys a model). The headline view answers the honest version of "could we have caught
that surprise homer?": of the players who actually homered, where did the model rank them?
 
IMPORTANT CAVEAT (surfaced in the UI): rebuilding a past slate today uses CURRENT-season
rates, not point-in-time rates as of that date, so recent dates have little look-ahead but
older dates have more. For rigorous, point-in-time proof, the Bet Log (which captured the
model's probability at bet time) is the source of truth. This page is for exploration.
"""
 
from __future__ import annotations
 
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta


def trading_dates_ending_yesterday(n_days: int, as_of: Optional[str] = None) -> List[str]:
    """The last n_days real calendar dates, as "YYYY-MM-DD" strings, ending at YESTERDAY
    relative to as_of (defaults to today) -- added directly on request, for a "trend across
    recent nights" dashboard view.

    Ends at yesterday, not today, on purpose: today's slate is still in progress or hasn't been
    played yet at any point someone would realistically be checking this, so including it would
    mean rebuilding a night with an incomplete or entirely absent real result to grade against.

    Returns OLDEST FIRST (chronological order), matching how a trend is naturally read left to
    right. n_days <= 0 returns an empty list, not an error -- a real, honest "nothing to show"
    rather than a crash on a stray zero from a UI number input."""
    if n_days <= 0:
        return []
    anchor = datetime.strptime(as_of, "%Y-%m-%d") if as_of else datetime.now()
    yesterday = anchor - timedelta(days=1)
    return [(yesterday - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n_days - 1, -1, -1)]

 
MARKET_STAT = {
    "Batter HR": "hr", "Batter Total Bases": "tb", "Batter Total Hits": "hits",
    "Batter Strikeouts": "so", "Pitcher Strikeouts": "p_k", "Pitcher Outs": "p_outs",
    "Pitcher Walks": "p_bb",
    # WNBA/NBA/NCAAMB — all three basketball sports share the same display market names (the
    # Core-4 convention), so one entry per name covers all of them; no separate NBA/NCAAMB rows
    # needed. Keys match wnba_engine.get_player_results()'s (and NBA's/NCAAMB's) result dict exactly.
    "Points": "pts", "Rebounds": "reb", "Assists": "ast", "Threes Made": "fg3m",
    # NFL — display names are entirely different from basketball's, so these DO need their own
    # entries (unlike the three basketball sports above). Keys match nfl_engine.get_player_
    # results()'s result dict exactly — confirmed the pairing explicitly, not just assumed, since
    # this dict is the one place a mismatch would silently grade zero plays rather than crash.
    "Pass Yards": "passing_yards", "Rush Yards": "rushing_yards",
    "Receptions": "receptions", "Receiving Yards": "receiving_yards",
}
 
 
def grade_play(market: str, side: str, line: float, actuals: Optional[Dict]) -> Optional[bool]:
    """Did the play hit? None if the player has no stat for that market (didn't appear)."""
    key = MARKET_STAT.get(market)
    if not actuals or key not in actuals:
        return None
    val = actuals[key]
    over_hit = val > line
    return over_hit if side == "Over" else (val < line)   # .5 lines -> no push
 
 
def _calibration(graded: List[Dict], n_bins: int = 5) -> List[Dict]:
    settled = [g for g in graded if g["Hit"] is not None]
    if not settled:
        return []
    width, out = 1.0 / n_bins, []
    for i in range(n_bins):
        lo, hi = i * width, (i + 1) * width
        grp = [g for g in settled if (lo <= g["ModelProb"] < hi) or (i == n_bins - 1 and g["ModelProb"] == 1.0)]
        if not grp:
            continue
        out.append({"lo": round(lo, 2), "hi": round(hi, 2),
                    "predicted": round(sum(g["ModelProb"] for g in grp) / len(grp), 3),
                    "actual": round(sum(1 for g in grp if g["Hit"]) / len(grp), 3),
                    "n": len(grp)})
    return out
 
 
def grade_slate(plays: List[Dict], results: Dict[int, Dict]) -> Tuple[List[Dict], Dict]:
    """Attach Hit/Actual to every play and summarize. Returns (graded_plays, summary)."""
    graded = []
    for p in plays:
        actuals = results.get(p.get("PlayerId")) if p.get("PlayerId") is not None else None
        hit = grade_play(p["Market"], p["Side"], p["Line"], actuals)
        graded.append({**p, "Hit": hit,
                       "Actual": (actuals or {}).get(MARKET_STAT.get(p["Market"]))})
 
    matched = [g for g in graded if g["Hit"] is not None]
    # discrimination: hit rate by conviction tier (should trend up if the model ranks well)
    tiers = []
    for lo, hi, label in [(1.75, 99, "≥1.75×"), (1.4, 1.75, "1.4–1.75×"),
                          (1.2, 1.4, "1.2–1.4×"), (0, 1.2, "<1.2×")]:
        grp = [g for g in matched if lo <= g["Conviction"] < hi]
        if grp:
            tiers.append({"tier": label, "n": len(grp),
                          "hit_rate": round(sum(1 for g in grp if g["Hit"]) / len(grp), 3)})
 
    summary = {
        "total": len(plays), "graded": len(matched),
        "hits": sum(1 for g in matched if g["Hit"]),
        "hit_rate": round(sum(1 for g in matched if g["Hit"]) / len(matched), 3) if matched else None,
        "tiers": tiers,
        "calibration": _calibration(matched),
    }
    return graded, summary
 
 
def market_report(plays: List[Dict], results: Dict[int, Dict], market: str, top_n: int = 15,
                  default_line: Optional[float] = None) -> Dict:
    """Of players whose actual result CLEARED the model's line for `market`, where did the model
    rank them pre-game? Generic version of homer_report/pitcher_k_report/batter_tb_report/
    batter_hits_report below — those four differ only in which market/stat key/default line they
    use, so this single function covers any market present in MARKET_STAT (MLB or WNBA) rather
    than needing a fifth near-duplicate for every future sport's markets. grade_play/grade_slate
    were already market-agnostic; this brings the report layer to the same standard.

    default_line: threshold used ONLY for the 'unprojected' bucket (a player who cleared a
    plausible line but wasn't in a projected slate at all, so there's no play-specific line to
    check against). Defaults to the median Line among this market's plays when not given — a
    reasonable per-slate stand-in that doesn't require a market-specific constant."""
    stat_key = MARKET_STAT.get(market)
    if stat_key is None:
        return {"caught": [], "missed": [], "unprojected": 0, "cutoff": 0, "total_ranked": 0}

    mkt_plays = sorted([p for p in plays if p["Market"] == market], key=lambda x: -x["ModelProb"])
    total = len(mkt_plays)
    cutoff = max(top_n, int(total * 0.10))
    rank_by_pid = {p.get("PlayerId"): (i + 1, p["ModelProb"], p["Player"], p["Line"], p.get("Conviction"))
                   for i, p in enumerate(mkt_plays)}

    if default_line is None:
        lines = sorted(p["Line"] for p in mkt_plays)
        default_line = lines[len(lines) // 2] if lines else 0.5

    caught, missed, unprojected = [], [], 0
    for pid, actuals in results.items():
        val = actuals.get(stat_key, 0) or 0
        if pid in rank_by_pid:
            rank, prob, name, line, conv = rank_by_pid[pid]
            if val <= line:            # the over didn't clear -> not a catch/miss candidate
                continue
            entry = {"Player": name, "PlayerId": pid, "Value": val, "Line": line, "ModelProb": prob,
                     "Conviction": conv, "Rank": rank, "OfTotal": total, "HitLine": True}
            (caught if rank <= cutoff else missed).append(entry)
        elif val > default_line:
            unprojected += 1

    caught.sort(key=lambda x: x["Rank"])
    missed.sort(key=lambda x: x["Rank"])
    return {"caught": caught, "missed": missed, "unprojected": unprojected,
            "cutoff": cutoff, "total_ranked": total}


def homer_report(plays: List[Dict], results: Dict[int, Dict], top_n: int = 15) -> Dict:
    """Of the players who actually homered, where did the model rank them in HR probability?
 
    The honest 'could we have caught it' view: a homer-hitter in the model's top plays was
    catchable pre-game; one ranked deep in the list was, by the data, genuinely random."""
    hr_plays = sorted([p for p in plays if p["Market"] == "Batter HR"],
                      key=lambda x: -x["ModelProb"])
    total = len(hr_plays)
    cutoff = max(top_n, int(total * 0.10))
    rank_by_pid = {p.get("PlayerId"): (i + 1, p["ModelProb"], p["Player"], p.get("Conviction"))
                   for i, p in enumerate(hr_plays)}
 
    caught, missed, unprojected = [], [], 0
    for pid, actuals in results.items():
        if (actuals.get("hr", 0) or 0) < 1:
            continue
        if pid in rank_by_pid:
            rank, prob, name, conv = rank_by_pid[pid]
            entry = {"Player": name, "PlayerId": pid, "HR": actuals["hr"], "ModelProb": prob,
                     "Conviction": conv, "Rank": rank, "OfTotal": total}
            (caught if rank <= cutoff else missed).append(entry)
        else:
            unprojected += 1   # not in a lineup we projected (sub, call-up, etc.)
 
    caught.sort(key=lambda x: x["Rank"])
    missed.sort(key=lambda x: x["Rank"])
    return {"caught": caught, "missed": missed, "unprojected": unprojected,
            "cutoff": cutoff, "total_ranked": total}
 
 
def _plat(row) -> Optional[str]:
    if row.get("Advantage") == "Advantage":
        return f"had the platoon edge ({row.get('Hand')} vs {row.get('Opp Hand')}HP)"
    return None
 
 
def _opp_hr9(row):
    try:
        h = float(row.get("Opp HR/9"))
        return h if h == h else None      # filter NaN (no-stats pitcher)
    except (TypeError, ValueError):
        return None
 
 
def explain_miss(row: Optional[Dict], market: str = "Batter HR") -> str:
    """Explain an outcome the model ranked LOW: what — if anything — could it have leaned on?
 
    Market-aware, because what makes an outcome 'catchable' differs by prop: homers key on
    barrels + power + a homer-prone matchup; total bases on slugging; hits on contact +
    hittable pitching; pitcher strikeouts on the opposing lineup's whiff rate. Deliberately
    honest: it separates a *catchable* miss (a real signal the ranking under-weighted, worth
    reviewing) from plain *variance* (no edge — the model was right to rank it low, and chasing
    these is the overfitting we avoid). `row` is the enriched board row (hitter or pitcher)
    looked up by player id; None means the player wasn't in a projected lineup at all."""
    if not row:
        return ("Not in a projected lineup (late change, call-up, or pinch-hit) — the model "
                "never saw this player.")
 
    # ---- Pitcher strikeouts: driven by the opposing lineup's whiff rate + projection -------
    if market == "Pitcher Strikeouts":
        signals: List[str] = []
        opp_k = row.get("_opp_k")
        proj_k = row.get("Proj K")
        if isinstance(opp_k, (int, float)) and opp_k >= 0.23:
            signals.append(f"opposing lineup whiff-prone ({opp_k * 100:.0f}% K rate)")
        if isinstance(proj_k, (int, float)) and proj_k >= 5.5:
            signals.append(f"model already projected a healthy {proj_k:.1f} K")
        if signals:
            return "Catchable — model had signal it under-weighted: " + "; ".join(signals) + "."
        pk = float(proj_k) if isinstance(proj_k, (int, float)) else 0.0
        return (f"Genuine over — projected only {pk:.1f} K against a contact lineup; the strikeouts "
                "landed above a low expectation. Not a systematic miss.")
 
    # ---- Offensive markets: shared skeleton, market-specific signal + power floor -----------
    signals = []
    wx = row.get("_weather_hr") or 1.0
    hr9 = _opp_hr9(row)
    plat = _plat(row)
 
    if market == "Batter Total Bases":
        if (row.get("Due") or 0) > 0.01:
            signals.append("Statcast barrels imply extra-base power the HR count hides")
        if hr9 is not None and hr9 >= 1.30:
            signals.append(f"faced a homer-prone starter (Opp HR/9 {hr9:.2f})")
        if wx >= 1.05:
            signals.append(f"park/weather favored power (+{(wx - 1) * 100:.0f}%)")
        if plat:
            signals.append(plat)
        slg = float(row.get("SLG") or 0.0)
        low, low_msg = (slg < 0.400), f"modest slugging (SLG {slg:.3f})"
        tail = "extra-base variance"
 
    elif market == "Batter Total Hits":
        if plat:
            signals.append(plat)
        if hr9 is not None and hr9 >= 1.30:
            signals.append(f"faced a hittable starter (Opp HR/9 {hr9:.2f})")
        avg = float(row.get("AVG") or 0.0)
        low = avg < 0.250
        low_msg = f"contact bat (AVG {avg:.3f}) — with a hit landing well over half the time anyway"
        tail = "hit variance (1+ hits is closer to a coin flip than a called shot)"
 
    else:  # Batter HR
        if (row.get("Due") or 0) > 0.01:
            bp = row.get("Barrel%")
            extra = f" (barrel {bp * 100:.0f}%)" if isinstance(bp, (int, float)) and bp else ""
            signals.append(f"Statcast barrels ran ahead of the HR count{extra} — the buy-the-dip "
                           "power signal was there")
        if hr9 is not None and hr9 >= 1.30:
            signals.append(f"faced a homer-prone starter (Opp HR/9 {hr9:.2f})")
        if wx >= 1.05:
            signals.append(f"park/weather favored power (+{(wx - 1) * 100:.0f}%)")
        if plat:
            signals.append(plat)
        iso = float(row.get("ISO") or 0.0)
        hr = int(float(row.get("HR") or 0.0))
        low = iso < 0.15 or hr <= 6
        low_msg = f"modest season power (ISO {iso:.3f}, {hr} HR)"
        tail = "home-run variance"
 
    if signals:
        return "Catchable — model had signal it under-weighted: " + "; ".join(signals) + "."
    if low:
        return (f"Genuine long shot — {low_msg} and no matchup edge. Correctly ranked low; "
                "variance, not a systematic miss.")
    return f"Landed just outside the top tier — no specific signal the model missed; normal {tail}."
 
 
def explain_pick_miss(model_prob: Optional[float], market: str = "", side: str = "") -> str:
    """Why did a graded PICK (the model's lean) NOT hit? Different question from explain_miss:
    that one asks why a result the model ranked low still happened; THIS asks why a play the
    model liked didn't come in.
 
    The honest, dominant answer is usually the base rate — the model's own probability favored a
    miss. This reframes a cold slate of 'misses' as the expected outcome for a high-variance
    market, not a model error. HR is the extreme case: a 2.5-3x conviction is still only ~30%
    model probability, so most such plays are *supposed* to miss on any given night."""
    try:
        p = float(model_prob)
    except (TypeError, ValueError):
        return ""
    if p != p:                       # NaN
        return ""
    pct, miss_pct = p * 100, (1 - p) * 100
    if p < 0.40:
        msg = (f"Long shot by design — model gave only {pct:.0f}%, so a miss was the "
               f"~{miss_pct:.0f}% base case.")
        if market == "Batter HR":
            msg += (" HR is the highest-variance market; even top plays sit near 30%, so most "
                    "miss on any given night — a cold HR slate is normal, not a model failure.")
        return msg
    if p < 0.55:
        return (f"Coin-flip lean — model was only mildly on the {(side or 'over').lower()} "
                f"({pct:.0f}%); a miss is well within range.")
    return (f"Real lean that lost — model favored it at {pct:.0f}%, so this was a genuine adverse "
            "result (variance), not a low-probability play.")
 
 
def pitcher_k_report(plays: List[Dict], results: Dict[int, Dict], top_n: int = 15,
                     default_line: float = 5.5) -> Dict:
    """Of pitchers whose strikeouts CLEARED their line, where did the model rank them?"""
    k_plays = sorted([p for p in plays if p["Market"] == "Pitcher Strikeouts"],
                     key=lambda x: -x["ModelProb"])
    total = len(k_plays)
    cutoff = max(top_n, int(total * 0.10))
    rank_by_pid = {p.get("PlayerId"): (i + 1, p["ModelProb"], p["Player"], p["Line"], p.get("Conviction"))
                   for i, p in enumerate(k_plays)}
 
    caught, missed, unprojected = [], [], 0
    for pid, actuals in results.items():
        k_val = actuals.get("p_k", 0) or 0
        if pid in rank_by_pid:
            rank, prob, name, line, conv = rank_by_pid[pid]
            if k_val < line:            # the over didn't hit -> not a catch/miss candidate
                continue
            entry = {"Player": name, "PlayerId": pid, "K": k_val, "Line": line, "ModelProb": prob,
                     "Conviction": conv, "Rank": rank, "OfTotal": total, "HitLine": True}
            (caught if rank <= cutoff else missed).append(entry)
        elif k_val >= default_line:     # cleared a typical line but wasn't in a projected slate
            unprojected += 1
 
    caught.sort(key=lambda x: x["Rank"])
    missed.sort(key=lambda x: x["Rank"])
    return {"caught": caught, "missed": missed, "unprojected": unprojected,
            "cutoff": cutoff, "total_ranked": total}
 
 
def batter_tb_report(plays: List[Dict], results: Dict[int, Dict], top_n: int = 15,
                     default_line: float = 1.5) -> Dict:
    """Of batters whose total bases CLEARED their line, where did the model rank them?"""
    tb_plays = sorted([p for p in plays if p["Market"] == "Batter Total Bases"],
                      key=lambda x: -x["ModelProb"])
    total = len(tb_plays)
    cutoff = max(top_n, int(total * 0.10))
    rank_by_pid = {p.get("PlayerId"): (i + 1, p["ModelProb"], p["Player"], p["Line"], p.get("Conviction"))
                   for i, p in enumerate(tb_plays)}
 
    caught, missed, unprojected = [], [], 0
    for pid, actuals in results.items():
        tb_val = actuals.get("tb", 0) or 0
        if pid in rank_by_pid:
            rank, prob, name, line, conv = rank_by_pid[pid]
            if tb_val < line:
                continue
            entry = {"Player": name, "PlayerId": pid, "TB": tb_val, "Line": line, "ModelProb": prob,
                     "Conviction": conv, "Rank": rank, "OfTotal": total, "HitLine": True}
            (caught if rank <= cutoff else missed).append(entry)
        elif tb_val >= default_line:
            unprojected += 1
 
    caught.sort(key=lambda x: x["Rank"])
    missed.sort(key=lambda x: x["Rank"])
    return {"caught": caught, "missed": missed, "unprojected": unprojected,
            "cutoff": cutoff, "total_ranked": total}
 
 
def batter_hits_report(plays: List[Dict], results: Dict[int, Dict], top_n: int = 15,
                       default_line: float = 0.5) -> Dict:
    """Of batters whose hits CLEARED their line, where did the model rank them?"""
    hit_plays = sorted([p for p in plays if p["Market"] == "Batter Total Hits"],
                       key=lambda x: -x["ModelProb"])
    total = len(hit_plays)
    cutoff = max(top_n, int(total * 0.10))
    rank_by_pid = {p.get("PlayerId"): (i + 1, p["ModelProb"], p["Player"], p["Line"], p.get("Conviction"))
                   for i, p in enumerate(hit_plays)}
 
    caught, missed, unprojected = [], [], 0
    for pid, actuals in results.items():
        h_val = actuals.get("hits", 0) or 0
        if pid in rank_by_pid:
            rank, prob, name, line, conv = rank_by_pid[pid]
            if h_val < line:
                continue
            entry = {"Player": name, "PlayerId": pid, "Hits": h_val, "Line": line, "ModelProb": prob,
                     "Conviction": conv, "Rank": rank, "OfTotal": total, "HitLine": True}
            (caught if rank <= cutoff else missed).append(entry)
        elif h_val >= default_line:
            unprojected += 1
 
    caught.sort(key=lambda x: x["Rank"])
    missed.sort(key=lambda x: x["Rank"])
    return {"caught": caught, "missed": missed, "unprojected": unprojected,
            "cutoff": cutoff, "total_ranked": total}
