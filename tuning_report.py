"""
tuning_report.py — the weekly tuning report (Nov 2). Run by the tuning-report workflow (Tuesday mornings, after
Monday Night Football) and on demand. Read-only except for saving the report itself; nothing changes the model until
the owner approves a proposal (approve-tuning workflow, or Postgame Review).

For each sport, over the last --days days of saved pre-game reads, graded against the box scores:
  1. calibration      -- when the model said 60%, did it hit 60%? by chance bucket and by market + side
  2. edge at the price -- profit per $1 at the price that was posted (what betting every read would have made)
  3. closing line      -- for logged bets, did the price we got beat the closing price? (the fastest honest signal)
  4. blend fit         -- how much the model should count against the books' no-vig line, per market: the share
                          (0 = trust the books entirely) that would have predicted these results best (log loss)
Proposals are listed only where the sample is big enough (MIN_N graded reads) and the gain is real.

    build(sport, graded_rows, bets) -> {"sport", "markdown", "proposals": [...], "n"}
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence

import pytz

MIN_N = 150                     # graded reads in a market before its blend weight can be proposed
MIN_SLATES = 5                  # ... spread over at least this many slates (one slate's results move together)
MIN_GAIN = 0.002                # log-loss improvement a new weight must show over the current one
MIN_MOVE = 0.10                 # ... and it must move the weight at least this much
W_GRID = [round(i * 0.05, 2) for i in range(0, 13)]          # 0.00 .. 0.60 (blend_weights.W_RANGE)
BUCKETS = ((0.0, 0.45), (0.45, 0.50), (0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 1.01))
SPORTS = ("NFL", "NCAAF", "NBA", "NHL", "NCAAMB", "WNBA")
EPS = 1e-4


def _dec(a) -> Optional[float]:
    import props_engine as PE
    return PE.decimal(a)


def _clip(p: float) -> float:
    return min(1 - EPS, max(EPS, p))


def _ll(p: float, y: int) -> float:
    p = _clip(p)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def prepare(graded: Sequence[Dict], default_w: float) -> List[Dict]:
    """Graded snapshots -> one row per read with y, the side's chance, its price, and (when the books priced it) the
    model's and the market's own chance for that side. The model's chance comes from the stored p_model; for reads
    saved before it was stored it is backed out of the blend (chance = w*model + (1-w)*market)."""
    import props_engine as PE
    out, seen = [], set()
    for r in graded:
        if r.get("result") not in ("hit", "miss") or r.get("chance") is None:
            continue
        k = (r.get("slate_date"), r.get("player"), r.get("market"), r.get("side"), r.get("line"))
        if k in seen:
            continue
        seen.add(k)
        side = r.get("side") or "Over"
        over = side == "Over"
        q_mkt = q_mod = None
        if r.get("p_market") is not None:
            q_mkt = r["p_market"] if over else 1 - r["p_market"]
        elif r.get("price") is not None and PE.implied(r["price"]) is not None:
            q_mkt = min(0.99, PE.implied(r["price"]) / (1 + PE.ASSUMED_VIG))
        if r.get("p_model") is not None:
            q_mod = r["p_model"] if over else 1 - r["p_model"]
        elif q_mkt is not None:
            w0 = min(default_w, PE.GAP_MODEL_WEIGHT) if r.get("gap") == "big" else default_w
            if w0 > 0:
                q_mod = _clip((r["chance"] - (1 - w0) * q_mkt) / w0)
        out.append({"lock": PE.most_probable(r.get("chance"), r.get("cushion"), r.get("gap")),
                    "y": 1 if r["result"] == "hit" else 0, "chance": float(r["chance"]), "price": r.get("price"),
                    "q_mkt": q_mkt, "q_mod": q_mod, "market": r.get("market") or "?", "side": side,
                    "date": r.get("slate_date"), "gap": r.get("gap")})
    return out


def profit(rows: Sequence[Dict]) -> Optional[float]:
    """Profit per $1 betting every priced read at its posted price."""
    priced = [r for r in rows if _dec(r.get("price")) is not None]
    if not priced:
        return None
    return sum((_dec(r["price"]) - 1) if r["y"] else -1 for r in priced) / len(priced)


def fit_weight(rows: Sequence[Dict]) -> Optional[Dict]:
    """The model's share (0..0.6) that predicts these results best; None without market prices."""
    usable = [r for r in rows if r["q_mkt"] is not None and r["q_mod"] is not None]
    if not usable:
        return None
    scores = {w: sum(_ll(w * r["q_mod"] + (1 - w) * r["q_mkt"], r["y"]) for r in usable) / len(usable) for w in W_GRID}
    best = min(scores, key=scores.get)
    return {"n": len(usable), "best": best, "scores": scores}


def holdout(rows: Sequence[Dict], now: float) -> Dict:
    """Nov 11: does the fitted weight beat the current one on days it never saw? Walk forward over the later half
    of the slates: fit on the days before each one, score both weights on that day. Same rule as the automatic
    calibration (calibration.auto_side): it must win on 2 of every 3 held-out days and overall."""
    usable = [r for r in rows if r["q_mkt"] is not None and r["q_mod"] is not None and r.get("date")]
    dates = sorted({r["date"] for r in usable})
    cur = min(W_GRID, key=lambda w: abs(w - now))
    splits = passed = 0
    gain = 0.0
    for i in range(max(1, len(dates) // 2), len(dates)):
        train = [r for r in usable if r["date"] < dates[i]]
        test = [r for r in usable if r["date"] == dates[i]]
        f = fit_weight(train)
        if not f or not test:
            continue

        def score(w):
            return sum(_ll(w * r["q_mod"] + (1 - w) * r["q_mkt"], r["y"]) for r in test) / len(test)
        splits += 1
        g = score(cur) - score(f["best"])
        gain += g * len(test)
        passed += g >= 0
    return {"splits": splits, "passed": passed, "gain": gain,
            "ok": splits >= 2 and passed >= (2 / 3) * splits and gain > 0}


def clv(bets: Sequence[Dict], sport: str) -> Optional[Dict]:
    import betlog as B
    vals = []
    for b in bets:
        if (b.get("sport") or "MLB") != sport or B.is_parlay_header(b):
            continue
        c = B.clv_pct(b.get("entry_odds"), b.get("close_odds"))
        if c is not None:
            vals.append(c)
    if not vals:
        return None
    return {"n": len(vals), "avg": sum(vals) / len(vals), "beat": sum(1 for v in vals if v > 0) / len(vals)}


def _pct(x, sign=False) -> str:
    if x is None:
        return "—"
    return f"{x:+.1%}" if sign else f"{x:.0%}"


def build(sport: str, graded: Sequence[Dict], bets: Sequence[Dict], days: int = 28) -> Dict:
    import blend_weights as BW
    import props_engine as PE
    rows = prepare(graded, PE.MODEL_WEIGHT)
    md = [f"## {sport} weekly tuning report — last {days} days", ""]
    if not rows:
        md.append("No graded reads in this window yet.")
        return {"sport": sport, "markdown": "\n".join(md), "proposals": [], "n": 0}
    n, hits = len(rows), sum(r["y"] for r in rows)
    avg = sum(r["chance"] for r in rows) / n
    md += [f"**{n} graded reads** over {len({r['date'] for r in rows})} slate(s). The model said **{avg:.0%}** on "
           f"average; they hit **{hits / n:.0%}**. Betting every priced read at the posted price: "
           f"**{_pct(profit(rows), True)} per $1**.", ""]

    c = clv(bets, sport)
    md.append("**Closing line (logged bets):** " + ("no bets with a closing price yet." if not c else
              f"{c['n']} bets · average {c['avg']:+.1f}% vs the close · beat the close {c['beat']:.0%} of the time "
              f"({'a good sign' if c['avg'] > 0 else 'the market moved against us — the picks are not ahead of it yet'})."))
    md.append("")

    locks = [r for r in rows if r.get("lock")]
    md += [f"### {PE.MOST_PROBABLE} picks (Best Bets' lock)", ""]
    if not locks:
        md += ["No lock picks graded in this window.", ""]
    else:
        lh = sum(r["y"] for r in locks)
        md += [f"**{lh}-{len(locks) - lh}** ({lh / len(locks):.0%}) · the model said "
               f"{sum(r['chance'] for r in locks) / len(locks):.0%} · profit {_pct(profit(locks), True)} per $1 at the "
               "posted price.", "", "| Market | Side | Record | Hit | Shown | Profit per $1 |", "|---|---|---|---|---|---|"]
        lby = defaultdict(list)
        for r in locks:
            lby[(r["market"], r["side"])].append(r)
        for (mk, sd), g in sorted(lby.items(), key=lambda kv: -len(kv[1])):
            if len(g) < 5:
                continue
            h = sum(r["y"] for r in g)
            md.append(f"| {mk} | {sd} | {h}-{len(g) - h} | {h / len(g):.0%} | "
                      f"{sum(r['chance'] for r in g) / len(g):.0%} | {_pct(profit(g), True)} |")
        md.append("")
    md += ["### 1. Calibration — does the chance shown match how often it hits?", "",
           "| Chance shown | Reads | Avg shown | Hit | Off by |", "|---|---|---|---|---|"]
    for lo, hi in BUCKETS:
        g = [r for r in rows if lo <= r["chance"] < hi]
        if len(g) < 10:
            continue
        sh, ht = sum(r["chance"] for r in g) / len(g), sum(r["y"] for r in g) / len(g)
        md.append(f"| {lo:.0%}–{min(hi, 1):.0%} | {len(g)} | {sh:.0%} | {ht:.0%} | {ht - sh:+.0%} |")
    md.append("")

    md += ["### 2. By market and side", "",
           "| Market | Side | Reads | Shown | Hit | Off by | Profit per $1 | Model weight now | Best fit |",
           "|---|---|---|---|---|---|---|---|---|"]
    proposals = []
    by = defaultdict(list)
    for r in rows:
        by[(r["market"], r["side"])].append(r)
    by_market = defaultdict(list)
    for r in rows:
        by_market[r["market"]].append(r)
    for (mk, sd), g in sorted(by.items(), key=lambda kv: -len(kv[1])):
        if len(g) < 30:
            continue
        sh, ht = sum(r["chance"] for r in g) / len(g), sum(r["y"] for r in g) / len(g)
        now = BW.weight(sport, mk, PE.MODEL_WEIGHT)
        f = fit_weight(g)
        md.append(f"| {mk} | {sd} | {len(g)} | {sh:.0%} | {ht:.0%} | {ht - sh:+.0%} | {_pct(profit(g), True)} | "
                  f"{now:.2f} | {'—' if not f else format(f['best'], '.2f')} |")
    md.append("")

    md += ["### 3. Blend fit — how much should the model count against the books?", "",
           "0 = go with the books' line entirely; the current default is "
           f"{PE.MODEL_WEIGHT:.2f}. Fitted per market (both sides together) on reads the books priced.", "",
           "| Market | Reads | Now | Best | Log loss now → best | Proposal |", "|---|---|---|---|---|---|"]
    for mk, g in sorted(by_market.items(), key=lambda kv: -len(kv[1])):
        f = fit_weight(g)
        if not f or f["n"] < 30:
            continue
        now = BW.weight(sport, mk, PE.MODEL_WEIGHT)
        cur = min(W_GRID, key=lambda w: abs(w - now))
        gain = f["scores"][cur] - f["scores"][f["best"]]
        slates = len({r["date"] for r in g if r["q_mkt"] is not None})
        better = gain >= MIN_GAIN and abs(f["best"] - now) >= MIN_MOVE - 1e-9
        ok = better and f["n"] >= MIN_N and slates >= MIN_SLATES
        why = ("**propose " + format(f["best"], ".2f") + "**") if ok else (
            "keep" if not better else f"wait (need {MIN_N} reads)" if f["n"] < MIN_N else
            f"wait ({slates} of {MIN_SLATES} slates)")
        md.append(f"| {mk} | {f['n']} | {now:.2f} | {f['best']:.2f} | {f['scores'][cur]:.4f} → "
                  f"{f['scores'][f['best']]:.4f} | {why} |")
        if ok:
            h = holdout(g, now)
            proposals.append({"sport": sport, "market": mk, "w": f["best"], "now": now, "n": f["n"],
                              "gain": round(gain, 4), "profit": profit(g), "holdout": h, "auto_ok": h["ok"],
                              "applied": False,
                              "why": (f"held up on {h['passed']} of {h['splits']} held-out days" if h["ok"] else
                                      f"didn't hold up on held-out days ({h['passed']} of {h['splits']})")})
    md.append("")

    losers = [(mk, sd, g) for (mk, sd), g in by.items() if len(g) >= 100 and (profit(g) or 0) <= -0.10]
    if losers:
        md += ["### 4. Losing pockets (100+ reads, losing 10%+ at the price)", ""]
        md += [f"- {mk} {sd}: {len(g)} reads, {_pct(profit(g), True)} per $1" for mk, sd, g in
               sorted(losers, key=lambda t: profit(t[2]) or 0)]
        md.append("")
    md += ["### Proposals", ""]
    if proposals:
        md += [f"- {p['market']}: model weight {p['now']:.2f} → **{p['w']:.2f}** ({p['n']} reads, log loss "
               f"−{p['gain']:.4f})" for p in proposals]
        md += ["", "Each one applies itself when it also wins on days the fit never saw (held-out days); the rest "
               "wait for next week. Nothing for you to approve."]
    else:
        md.append("None this week — no market has enough reads with a clear improvement.")
    lock_rec = None
    if locks:
        lock_rec = {"hits": sum(r["y"] for r in locks), "graded": len(locks), "profit": profit(locks)}
    return {"sport": sport, "markdown": "\n".join(md), "proposals": proposals, "n": n, "locks": lock_rec}


def _dates(sport: str, days: int, today: date) -> List[str]:
    import model_store as MS
    lo = (today - timedelta(days=days)).isoformat()
    return [d for d in MS.snapshot_dates(sport) if lo <= d < today.isoformat()]


def main(argv=None) -> int:
    import betlog as B
    import daily_review as D
    import model_store as MS
    ap = argparse.ArgumentParser()
    ap.add_argument("--sports", default=",".join(SPORTS))
    ap.add_argument("--days", type=int, default=28)
    a = ap.parse_args(argv)
    today = datetime.now(pytz.timezone("US/Eastern")).date()
    bets = B.list_bets()
    for sport in [s.strip() for s in a.sports.split(",") if s.strip()]:
        dates = _dates(sport, a.days, today)
        graded = [r for recs in D.grade_dates(sport, dates).values() for r in recs] if dates else []
        rep = build(sport, graded, bets, a.days)
        # Nov 11: the owner wants the model to tune itself -- a proposal that holds up out of sample applies itself
        for p in rep.get("proposals") or []:
            if p.get("auto_ok") and os.environ.get("TUNING_AUTO_APPLY", "1") == "1":
                p["applied"] = bool(MS.approve_blend(p["sport"], p["market"], p["w"],
                                                     {"week": today.isoformat(), "n": p["n"], "gain": p["gain"],
                                                      "auto": True, "holdout": p["holdout"]}))
            rep["markdown"] += (f"\n- 🤖 {p['market']}: {p['now']:.2f} → {p['w']:.2f} "
                                f"{'applied automatically' if p['applied'] else 'not applied'} — {p['why']}.")
        print(rep["markdown"] + "\n")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
                f.write(rep["markdown"] + "\n\n")
        MS.save_daily_review(f"{sport}-tuning", today.isoformat(), rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
