"""
data_checks.py — catch bad data before it reaches a record (Nov 21).

Owner, Nov 21: "I think your 14-1 record is overstated" -- eleven bets settled from box scores of games still being
played, and nothing noticed until he did. A+ plan item 8: every morning, after the night is graded, check the data the
records are built on and say what's wrong:

  * settlement   -- settled prop bets of the last few slates regraded on FINAL box scores; any disagreement is listed
                    (the settle job only reads final games now; a conflict means something new broke);
  * closes       -- bets whose "closing line" moved the chance 20+ points: another line's price, left out of CLV;
  * prices       -- impossible American odds (between -100 and +100, or past +/-10000) on bets or shown picks;
  * ledger       -- yesterday's shown-picks ledgers: picks still ungraded after grading, earned chances out of range,
                    a sportsbook pick without a price;
  * rules        -- any rule whose live parameters differ from its registered version (rules.drift()).

Read-only: it changes no bet and no record. The result is saved (KEY) for the morning health check (health_check.py)
and printed. `python data_checks.py [YYYY-MM-DD]` (default: today, New York).
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Sequence

KEY = "health:checks:{day}"
SETTLE_DAYS = 3
SETTLE_SPORTS = ("NBA", "NCAAMB", "WNBA", "NHL")


def _issue(check: str, level: str, detail: str, ids: Sequence = ()) -> Dict:
    return {"check": check, "level": level, "detail": detail, "ids": list(ids)[:30]}


def bad_odds(o) -> bool:
    try:
        v = float(o)
    except (TypeError, ValueError):
        return False
    return -100 < v < 100 or abs(v) > 10000


def check_settlement(bets: Sequence[Dict], today: str, results: Optional[Callable] = None) -> List[Dict]:
    import betlog as B
    import settle_results as SR
    if results is None:
        import sports

        def results(sp, d):
            return sports.get(sp).engine.get_player_results(d)
    t = date.fromisoformat(today)
    days = {(t - timedelta(days=k)).isoformat() for k in range(1, SETTLE_DAYS + 1)}
    by: Dict = {}
    for b in bets:
        if (str(b.get("slate_date") or "") in days and b.get("sport") in SETTLE_SPORTS and b.get("market")
                and b.get("player") and B._result(b) in ("win", "loss")):
            by.setdefault((b["sport"], str(b["slate_date"])), []).append(b)
    wrong = []
    for (sp, d), bs in sorted(by.items()):
        try:
            res = results(sp, d) or {}
        except Exception:                                       # noqa: BLE001
            continue
        if not res:
            continue
        known = SR._ids_by_name(bs, res)
        for b in bs:
            bb = b if b.get("player_id") is not None else dict(b, player_id=known.get(SR._norm(b.get("player"))))
            g = SR.settle_bet(bb, res) if bb.get("player_id") is not None else None
            if g and g != B._result(b):
                wrong.append(f"#{b['id']} {b.get('player')} {b.get('market')} {b.get('side')} {b.get('line')}: "
                             f"logged {B._result(b)}, final box score says {g}")
    if wrong:
        return [_issue("settlement", "error", f"{len(wrong)} settled bet(s) disagree with the final box score: "
                       + "; ".join(wrong[:5]) + (" …" if len(wrong) > 5 else ""), [w.split()[0] for w in wrong])]
    return []


def check_closes(bets: Sequence[Dict], today: str, days: int = 7) -> List[Dict]:
    import betlog as B
    since = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    bad = [b for b in bets if str(b.get("slate_date") or "") >= since and not B._missing(b.get("entry_odds"))
           and not B._missing(b.get("close_odds")) and B.clv_pct(b["entry_odds"], b["close_odds"]) is None]
    if bad:
        return [_issue("closes", "warn", f"{len(bad)} bet(s) in the last {days} days carry a closing price 20+ points "
                       "from the entry — another line's price, left out of CLV",
                       [f"#{b['id']}" for b in bad])]
    return []


def check_prices(bets: Sequence[Dict], ledger_rows: Sequence[Dict], today: str, days: int = 7) -> List[Dict]:
    since = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    bb = [b for b in bets if str(b.get("slate_date") or "") >= since
          and (bad_odds(b.get("entry_odds")) or bad_odds(b.get("close_odds")))]
    lb = [r for r in ledger_rows if bad_odds(r.get("price"))]
    out = []
    if bb:
        out.append(_issue("prices", "error", f"{len(bb)} bet(s) with impossible odds (between -100 and +100, or past "
                          "±10000)", [f"#{b['id']}" for b in bb]))
    if lb:
        out.append(_issue("prices", "error", f"{len(lb)} shown pick(s) with impossible odds: "
                          + "; ".join(f"{r.get('pick')} {r.get('price')}" for r in lb[:5])))
    return out


def check_ledgers(day: str, load: Optional[Callable] = None) -> List[Dict]:
    """Yesterday's ledgers (`day`): graded, earned chances in range, sportsbook picks priced."""
    import pick_ledger as PL
    load = load or PL.load
    out = []
    for kind, sps in (("strong", ["ALL"]), ("money", ["NBA", "NHL", "NFL", "NCAAF", "NCAAMB"]),
                      ("games", ["NCAAMB", "NBA", "NHL", "NFL", "NCAAF"])):
        for sp in sps:
            led = load(kind, sp, day)
            rows = list(led["rows"].values())
            if not rows:
                continue
            tag = f"{kind}{'' if sp == 'ALL' else ' · ' + sp}"
            if not led.get("graded_at"):
                out.append(_issue("ledger", "error", f"{tag}: {len(rows)} shown pick(s) from {day} were never graded"))
                continue
            ung = [r for r in rows if r.get("result") not in ("win", "loss", "push", "void")]
            if ung:
                out.append(_issue("ledger", "warn", f"{tag}: {len(ung)} of {len(rows)} shown pick(s) from {day} have no "
                                  "result (no final box score / score found): "
                                  + "; ".join(str(r.get("pick")) for r in ung[:4])))
            odd = [r for r in rows if r.get("earned") is not None and not 0.02 <= float(r["earned"]) <= 0.98]
            if odd:
                out.append(_issue("ledger", "warn", f"{tag}: {len(odd)} earned chance(s) out of range"))
            unp = [r for r in rows if r.get("price") is None and not r.get("pickem_only")]
            if unp:
                out.append(_issue("ledger", "warn", f"{tag}: {len(unp)} sportsbook pick(s) without a price"))
    return out


# Nov 22 (owner: "this seems to be a lingering problem that is costing me money and credibility"): the college model
# rated home teams 7.2 points too high in close games for days before anyone noticed. Every game model is now checked
# each morning: league -> (a "close game" is within this many points on the spread, the bias that raises a warning).
BIAS_LEAGUES = {"NCAAMB": (10.0, 3.0), "NBA": (10.0, 3.0), "NFL": (7.0, 3.0), "NCAAF": (7.0, 3.5), "NHL": (1.5, 0.5)}
BIAS_DAYS = 14
CONFIRM_DAYS = 28         # a home-bias warning must show over this longer window too, or it's reported as a streak
TOTAL_LIMIT = {"NCAAMB": 4.0, "NBA": 4.0, "NFL": 3.5, "NCAAF": 4.0, "NHL": 0.5}
SLOPE_OFF = 0.2           # actual margins 20%+ bigger or smaller than the model's, at 2.5+ standard errors
SHOWN_DAYS = 14
SHOWN_MIN_N = 40
SHOWN_GAP = 0.07
BIAS_MIN_N = 30
LEAN_MIN_N = 12
LEAN_SHARE = 0.8


def check_bias(today: str, load: Optional[Callable] = None, now: Optional[datetime] = None) -> List[Dict]:
    """Each game model's home-side bias: over the last BIAS_DAYS days' graded close games, (model margin - actual
    margin) averaging more than the league's limit AND clearly not noise (2.5+ standard errors); or today's slate
    leaning one way on LEAN_SHARE+ of its games (28 of 35 home leans on Nov 22 was the first sign)."""
    if load is None:
        import model_store as MS
        load = MS.load_game_picks
    now = now or datetime.now(timezone.utc)
    since = (date.fromisoformat(today) - timedelta(days=BIAS_DAYS)).isoformat()
    out = []
    for lg, (close, limit) in BIAS_LEAGUES.items():
        try:
            recs = load(lg)
        except Exception:                                       # noqa: BLE001
            continue
        errs = []
        for r in recs or []:
            if str(r.get("kickoff") or "")[:10] < since or r.get("final_home") is None or r.get("model_margin") is None:
                continue
            ref = r.get("home_spread")
            size = abs(float(ref)) if ref is not None else abs(float(r["model_margin"]))
            if size <= close:
                errs.append(float(r["model_margin"]) - (float(r["final_home"]) - float(r["final_away"])))
        # Nov 22 (owner: "enact methods to keep it from reintroducing itself"): totals running high or low, and margins
        # too extreme or too timid (the slope of actual margins on the model's: 1 = right size)
        tots, pairs = [], []
        for r in recs or []:
            if str(r.get("kickoff") or "")[:10] < since or r.get("final_home") is None or r.get("model_margin") is None:
                continue
            act_m = float(r["final_home"]) - float(r["final_away"])
            pairs.append((float(r["model_margin"]), act_m))
            if r.get("model_total") is not None:
                tots.append(float(r["model_total"]) - (float(r["final_home"]) + float(r["final_away"])))
        tlim = TOTAL_LIMIT.get(lg)
        if tlim and len(tots) >= BIAS_MIN_N:
            tm = sum(tots) / len(tots)
            tsd = (sum((t - tm) ** 2 for t in tots) / (len(tots) - 1)) ** 0.5
            if abs(tm) > tlim and tsd and abs(tm) / (tsd / len(tots) ** 0.5) >= 2.5:
                out.append(_issue("model bias", "warn", f"{lg} game model's totals run {abs(tm):.1f} "
                                  f"{'high' if tm > 0 else 'low'} (last {BIAS_DAYS} days, {len(tots)} games)"))
        if len(pairs) >= 60:
            mx = sum(a for a, _ in pairs) / len(pairs)
            my = sum(b for _, b in pairs) / len(pairs)
            sxx = sum((a - mx) ** 2 for a, _ in pairs)
            slope = sum((a - mx) * (b - my) for a, b in pairs) / sxx if sxx else None
            se = None
            if slope is not None:
                res = [b - my - slope * (a - mx) for a, b in pairs]
                se = (sum(e * e for e in res) / (len(pairs) - 2) / sxx) ** 0.5
            if slope is not None and se and abs(slope - 1) >= SLOPE_OFF and abs(slope - 1) / se >= 2.5:
                # Nov 25 (owner asked what 1.46x meant for his close-gap bets): say whether the market shares it. The
                # NCAAMB study that day: market 0.99x, and the close-gap picks were 119-78 over 28 days -- the warning
                # was about blowout games the market already prices, not about the picks.
                mk = [(-float(r["home_spread"]), float(r["final_home"]) - float(r["final_away"])) for r in recs or []
                      if str(r.get("kickoff") or "")[:10] >= since and r.get("final_home") is not None
                      and r.get("home_spread") is not None and r.get("model_margin") is not None]
                msl = None
                if len(mk) >= 60:
                    ax = sum(a for a, _ in mk) / len(mk); ay = sum(b for _, b in mk) / len(mk)
                    axx = sum((a - ax) ** 2 for a, _ in mk)
                    msl = sum((a - ax) * (b - ay) for a, b in mk) / axx if axx else None
                ctx = ("" if msl is None else
                       f"; the market's spreads run {msl:.2f}x" + (" — right-sized, so lean on the market for margin "
                       "size; picks built on the market's number (close-gap) aren't affected" if abs(msl - 1) < SLOPE_OFF
                       else " — the market misses it too"))
                out.append(_issue("model bias", "warn", f"{lg} game model's margins are too "
                                  f"{'extreme' if slope < 1 else 'timid'}: actual margins run {slope:.2f}x "
                                  f"the model's (last {BIAS_DAYS} days, {len(pairs)} games; 1.00 = the right size){ctx}"))
        if len(errs) >= BIAS_MIN_N:
            m = sum(errs) / len(errs)
            sd = (sum((e - m) ** 2 for e in errs) / (len(errs) - 1)) ** 0.5
            se = sd / len(errs) ** 0.5 if sd else None
            if abs(m) > limit and se and abs(m) / se >= 2.5:
                side = "home" if m > 0 else "road"
                # Nov 23: a 14-day run of home losses (NHL, Nov 9-22: home teams -0.35 goals a game) is a streak, not a
                # model problem, unless the longer window agrees. Walk-forward refits matched the saved projections.
                lo = (date.fromisoformat(today) - timedelta(days=CONFIRM_DAYS)).isoformat()
                long_ = []
                for r in recs or []:
                    if str(r.get("kickoff") or "")[:10] < lo or r.get("final_home") is None or r.get("model_margin") is None:
                        continue
                    ref = r.get("home_spread")
                    if (abs(float(ref)) if ref is not None else abs(float(r["model_margin"]))) <= close:
                        long_.append(float(r["model_margin"]) - (float(r["final_home"]) - float(r["final_away"])))
                lm = sum(long_) / len(long_) if long_ else 0.0
                lsd = (sum((e - lm) ** 2 for e in long_) / (len(long_) - 1)) ** 0.5 if len(long_) > 1 else 0.0
                lse = lsd / len(long_) ** 0.5 if lsd else None
                confirmed = lse and lm * m > 0 and abs(lm) > limit and abs(lm) / lse >= 2.0
                if not confirmed:
                    out.append(_issue("model bias", "info",
                                      f"{lg}: {side} teams have run {abs(m):.1f} below the model in close games over the "
                                      f"last {BIAS_DAYS} days ({len(errs)} games), but the last {CONFIRM_DAYS} days "
                                      f"({len(long_)} games, {lm:+.1f}) don't confirm a model problem -- likely a streak; "
                                      "watching"))
                    m = 0.0
            if abs(m) > limit and se and abs(m) / se >= 2.5:
                out.append(_issue("model bias", "warn",
                                  f"{lg} game model rates {side} teams {abs(m):.1f} too high in close games "
                                  f"(last {BIAS_DAYS} days, {len(errs)} games, ±{se:.1f}) -- check its home court and "
                                  "neutral sites before trusting its leans"))
        upcoming = []
        for r in recs or []:
            try:
                k = datetime.fromisoformat(str(r.get("kickoff")).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if k.tzinfo is None:
                k = k.replace(tzinfo=timezone.utc)
            if not now < k <= now + timedelta(hours=36):
                continue
            if lg == "NHL":
                # Nov 25: hockey's spread is the ±1.5 puck line, so a 0.3-goal home edge "leans road" against it on
                # almost every game -- the Nov 25 "11 of 13 road" warning. Judge the lean on the win chance instead.
                if r.get("model_p") is not None and r.get("fair_home") is not None:
                    e = float(r["model_p"]) - float(r["fair_home"])
                    if abs(e) >= 0.005:
                        upcoming.append(e > 0)
                continue
            if r.get("home_spread") is not None and r.get("model_margin") is not None:
                e = float(r["model_margin"]) + float(r["home_spread"])
                if e:
                    upcoming.append(e > 0)
        if len(upcoming) >= LEAN_MIN_N:
            share = sum(upcoming) / len(upcoming)
            if share >= LEAN_SHARE or share <= 1 - LEAN_SHARE:
                side = "home" if share >= LEAN_SHARE else "road"
                n_side = sum(upcoming) if side == "home" else len(upcoming) - sum(upcoming)
                out.append(_issue("model bias", "warn",
                                  f"{lg} game model leans {side} on {n_side} of {len(upcoming)} upcoming games -- a "
                                  "one-sided slate is the first sign of a home-court problem"))
    return out


def check_shown(today: str, load: Optional[Callable] = None) -> List[Dict]:
    """Nov 22: the picks members actually saw (strongest list, 💰, Hot Tickets) -- did they hit as often as the chance
    shown said? By sport and sportsbook vs pick'em, last SHOWN_DAYS days; a shortfall of SHOWN_GAP+ at 2+ standard
    errors warns (pick'em lines said 57% and hit 44-52% for days before the Nov 22 audit)."""
    import pick_ledger as PL
    load = load or PL.load
    groups: Dict[tuple, List[tuple]] = {}
    seen = set()
    d0 = date.fromisoformat(today) - timedelta(days=SHOWN_DAYS)
    d = d0
    while d < date.fromisoformat(today):
        day = d.isoformat()
        targets = [("strong", "ALL"), ("hot", "ALL")] + [("money", s) for s in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB")]
        for kind, sp in targets:
            try:
                rows = (load(kind, sp, day) or {}).get("rows") or {}
            except Exception:                                   # noqa: BLE001
                continue
            for k, r in rows.items():
                if (day, k) in seen or r.get("result") not in ("win", "loss"):
                    continue
                ch = r.get("earned") if r.get("earned") is not None else r.get("chance")
                if ch is None:
                    continue
                seen.add((day, k))
                kind_ = "pick'em" if (r.get("pickem_only") or r.get("price") is None) else "sportsbook"
                groups.setdefault((r.get("sport") or sp, kind_), []).append((float(ch), r["result"] == "win"))
        d += timedelta(days=1)
    out = []
    for (sp, kind_), xs in sorted(groups.items()):
        if len(xs) < SHOWN_MIN_N:
            continue
        said = sum(c for c, _ in xs) / len(xs)
        hit = sum(h for _, h in xs) / len(xs)
        se = (hit * (1 - hit) / len(xs)) ** 0.5 or 0.01
        if said - hit >= SHOWN_GAP and (said - hit) / se >= 2:
            out.append(_issue("model bias", "warn", f"{sp} {kind_} picks shown said {said:.0%} and hit {hit:.0%} "
                              f"(last {SHOWN_DAYS} days, {len(xs)} picks) -- the shown chance is running high"))
    return out


def check_rules() -> List[Dict]:
    import rules as RU
    return [_issue("rules", "error", d) for d in RU.drift()]


def run(today: Optional[str] = None, bets=None, results=None, ledger_load=None, save=True) -> Dict:
    import props_engine as PE
    today = today or PE._et_today()
    yest = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    if bets is None:
        import betlog as B
        bets = B.list_bets()
    issues: List[Dict] = []
    for name, fn in (("settlement", lambda: check_settlement(bets, today, results)),
                     ("closes", lambda: check_closes(bets, today)),
                     ("ledger", lambda: check_ledgers(yest, ledger_load)),
                     ("rules", check_rules),
                     ("model bias", lambda: check_bias(today)),
                     ("shown picks", lambda: check_shown(today, ledger_load))):
        try:
            issues += fn()
        except Exception as exc:                                # noqa: BLE001 -- one check failing never hides the rest
            issues.append(_issue(name, "warn", f"the check itself failed ({type(exc).__name__}: {str(exc)[:120]})"))
    try:
        import pick_ledger as PL
        lrows = [r for kind, sp in [("strong", "ALL")] + [("money", s) for s in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB")]
                 for r in (ledger_load or PL.load)(kind, sp, yest)["rows"].values()]
        issues += check_prices(bets, lrows, today)
    except Exception as exc:                                    # noqa: BLE001
        issues.append(_issue("prices", "warn", f"the check itself failed ({type(exc).__name__})"))
    rec = {"day": today, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "issues": issues,
           "errors": sum(i["level"] == "error" for i in issues), "warnings": sum(i["level"] == "warn" for i in issues)}
    if save:
        try:
            import model_store as MS
            MS.save_setting(KEY.format(day=today), rec)
        except Exception:                                       # noqa: BLE001
            pass
    return rec


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    rec = run(argv[0] if argv else None)
    print(f"Data checks {rec['day']}: {rec['errors']} error(s), {rec['warnings']} warning(s)")
    for i in rec["issues"]:
        print(f"  [{i['level']}] {i['check']}: {i['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
