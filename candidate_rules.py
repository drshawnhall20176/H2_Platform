"""
candidate_rules.py -- game-line rules tracked FORWARD before they earn a Use tag (Nov 23).

Owner, Nov 23: "if the Use column shows no edge for everything is it useful? ... we won't have status other than no
edge through the entire season" -> "yes" to tracking the morning's finding forward. Looking back over Nov 5-22 (768
college basketball games, the corrected model), the model's side of the spread won 60% (101-66) when the model and
the market were within 2 points, and only ~50% at gaps of 5+. A pattern found by looking back can be luck, so it
earns nothing until games played AFTER it was named agree:

  * record() -- each capture (capture-intl, analyst-lock) writes every not-yet-started qualifying game to the
    pick_ledger kind "cand" (first sighting wins, so the read is pre-game);
  * pick_ledger.grade_day grades it nightly with the other ledgers;
  * status_line() -- the forward record, shown where the Use column would be; PROMOTE says what earns the 🎯.
Nothing here is shown as a bet or counted in any record members see.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

KIND = "cand"
RULES = {"close_gap": {"sport": "NCAAMB", "max_gap": 2.0, "from": "2026-11-23",
                       "what": "the model's side of the spread when the model and the market are within 2 points",
                       "lookback": "60% (101–66) on Nov 5–22's games, found by looking back"}}
PROMOTE_N, PROMOTE_RATE = 200, 0.55          # graded forward games, and the hit rate they must hold


def picks(recs, day: str, now: Optional[datetime] = None, rule: str = "close_gap") -> List[Dict]:
    """Qualifying games of `day` (New York date) that haven't started: the model's side of the spread."""
    import intl_picks as IP
    import sports
    cfg = RULES[rule]
    now = now or datetime.now(timezone.utc)
    out = []
    for p in recs or []:
        k = sports.game_dt(p.get("kickoff"))
        if k is None or k.strftime("%Y-%m-%d") != day:
            continue
        try:
            kt = datetime.fromisoformat(str(p["kickoff"]).replace("Z", "+00:00"))
            if kt.tzinfo is None:
                kt = kt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if kt <= now or p.get("home_spread") is None or p.get("model_margin") is None:
            continue
        d = float(p["model_margin"]) + float(p["home_spread"])
        if d == 0 or abs(d) >= cfg["max_gap"]:
            continue
        side = "home" if d > 0 else "away"
        line = float(p["home_spread"]) if side == "home" else -float(p["home_spread"])
        try:
            price = IP.spread_price_for(p, side)
        except Exception:                                       # noqa: BLE001
            price = None
        out.append({"sport": cfg["sport"], "kind": "Game", "league": cfg["sport"], "game_id": p.get("game_id"),
                    "kickoff": p.get("kickoff"), "game": f"{p.get('away')} @ {p.get('home')}",
                    "time": k.strftime("%-I:%M %p"), "pick": f"{p.get(side)} {line:+g}", "money_market": "Spread",
                    "money_side": side, "money_line": line, "price": price if price is not None else -110,
                    "edge": round(abs(d), 2), "use": f"🧪 tracking ({rule})"})
    return out


def record(day: Optional[str] = None, now: Optional[datetime] = None, load=None) -> int:
    import model_store as MS
    import pick_ledger as PL
    day = day or PL._today_et()
    n = 0
    for rule, cfg in RULES.items():
        if day < cfg["from"]:
            continue
        recs = (load or MS.load_game_picks)(cfg["sport"])
        n += PL.add(KIND, cfg["sport"], day, picks(recs, day, now, rule), now)
    return n


def forward(end: str, rule: str = "close_gap", get=None) -> Optional[Dict]:
    import pick_ledger as PL
    cfg = RULES[rule]
    return PL.since_record(KIND, cfg["sport"], cfg["from"], end, get)


def status_line(league: str, end: str, get=None) -> str:
    """The candidate rule's forward record for a league's table ('' when it has none)."""
    for rule, cfg in RULES.items():
        if cfg["sport"] != league:
            continue
        r = None
        try:
            r = forward(end, rule, get)
        except Exception:                                       # noqa: BLE001
            pass
        rec = (f"forward record since {cfg['from'][5:].replace('-', '/')}: **{r['hits']}–{r['misses']}** "
               f"({r['hit_rate']:.0%}, {r['units']:+.1f}u)" if r else "its forward record starts today")
        return (f"🧪 **Tracking a candidate rule:** {cfg['what']} ({cfg['lookback']}). Not a bet yet — {rec}. It "
                f"earns a 🎯 tag after {PROMOTE_N} graded games at {PROMOTE_RATE:.0%}+. Those games show ✅ in "
                "**Model & market agree?**")
    return ""


# --------------------------------------------------------------------------- player props (Nov 23)
# Owner, Nov 23: "what I would like for the NBA, NHL, NFL and NCAAF [is] where agree or some other indicator is a bet
# signal." 100 prop indicators were tested on Oct 15-Nov 8 and checked on Nov 9-22 at the real prices; none cleared
# chance, but two football Under indicators made money in both halves and fit a known market lean (bettors overbet
# Overs). They are tracked FORWARD from Nov 24 on the props board's pre-game snapshots -- a fixed definition, no
# retuning -- and earn a 🎯 only if they hold up. Nothing found in the NBA or NHL; none in game lines (too few games).
PROP_RULES = {
    "nfl_under_vs_fav": {"sport": "NFL", "from": "2026-11-24", "dir": "opp",
                         "what": "NFL player-prop Unders when the model goes against the market's favorite",
                         "lookback": "+7.5% on 504 props, Oct 15–Nov 22, positive in both halves"},
    "ncaaf_under_same": {"sport": "NCAAF", "from": "2026-11-24", "dir": "same",
                         "what": "college football player-prop Unders when the model and the market favor the same side",
                         "lookback": "+6.1% on 599 props, Oct 15–Nov 22"},
}
PROP_PROMOTE_N, PROP_PROMOTE_Z = 300, 2.0       # graded forward props; units per sqrt(n) -- too strong to be luck
PROP_KEY = "CAND_PROPS"


def prop_qualifies(rule: str, r: Dict) -> bool:
    """A graded (or snapshot) prop read the rule would bet: a sportsbook line with both prices, the model on the Under
    (its Over chance below the market's), and the model and market favoring the same / opposite side as the rule says."""
    import props_engine as PE
    cfg = PROP_RULES[rule]
    if (r.get("book") or "") in PE.PICKEM_BOOKS or r.get("over_price") is None or r.get("under_price") is None:
        return False
    if r.get("p_model") is None or r.get("p_market") is None or r.get("line") is None:
        return False
    pm, pmod = float(r["p_market"]), float(r["p_model"])
    if not pmod < pm:
        return False
    same = (pm > 0.5) == (pmod > 0.5)
    return same if cfg["dir"] == "same" else not same


def prop_forward(rule: str, through: str, grade=None) -> Dict:
    """{"n", "hits", "units", "through"} for the rule's graded props from its start date through `through`."""
    import props_engine as PE
    cfg = PROP_RULES[rule]
    if grade is None:
        import daily_review as DR
        import model_store as MS
        dates = [d for d in MS.snapshot_dates(cfg["sport"]) if cfg["from"] <= d <= through]
        grade = lambda: DR.grade_dates(cfg["sport"], dates)                             # noqa: E731
    n = hits = 0
    units = 0.0
    for day, rs in (grade() or {}).items():
        if not cfg["from"] <= day <= through:
            continue
        for r in rs:
            if r.get("actual") is None or not prop_qualifies(rule, r):
                continue
            thr = PE.threshold(float(r["line"]))
            if r["actual"] == thr:
                continue
            won = r["actual"] < thr
            d = PE.decimal(r["under_price"])
            n += 1
            hits += won
            units += (d - 1) if won else -1.0
    return {"n": n, "hits": hits, "units": round(units, 2), "through": through}


def refresh_props(today: Optional[str] = None, get=None, save=None, grade_for=None) -> Dict:
    """Once a day (from the hourly morning review): each prop rule's forward record through yesterday."""
    import model_store as MS
    from datetime import date, timedelta
    get, save = get or MS.get_setting, save or MS.save_setting
    import pick_ledger as PL
    today = today or PL._today_et()
    through = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    cur = get(PROP_KEY) or {}
    if all((cur.get(k) or {}).get("through") == through for k in PROP_RULES):
        return cur
    out = dict(cur)
    for rule in PROP_RULES:
        try:
            out[rule] = prop_forward(rule, through, (grade_for or {}).get(rule))
        except Exception as exc:                                # noqa: BLE001 -- one rule never stops the other
            print(f"{rule}: {type(exc).__name__}: {exc}")
    save(PROP_KEY, out)
    return out


def prop_status_line(sport: str, get=None) -> str:
    import model_store as MS
    rec = (get or MS.get_setting)(PROP_KEY) or {}
    lines = []
    for rule, cfg in PROP_RULES.items():
        if cfg["sport"] != sport:
            continue
        r = rec.get(rule) or {}
        n = int(r.get("n") or 0)
        so_far = (f"forward record since {cfg['from'][5:].replace('-', '/')}: **{r['hits']}–{n - r['hits']}**, "
                  f"{r['units']:+.1f}u on {n} props" if n else "its forward record starts with the next slate")
        lines.append(f"🧪 **Tracking a candidate rule:** {cfg['what']} ({cfg['lookback']}). Not a bet yet — {so_far}. "
                     f"It earns a 🎯 tag after {PROP_PROMOTE_N} graded props if the return stays positive and too strong "
                     "to be luck.")
    return "  \n".join(lines)


if __name__ == "__main__":
    if sys.argv[1:2] == ["record"]:
        print(f"candidate rules: {record()} new game(s) recorded")
    elif sys.argv[1:2] == ["props"]:
        print(f"candidate prop rules: {refresh_props()}")
