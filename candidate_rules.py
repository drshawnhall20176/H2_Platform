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


if __name__ == "__main__":
    if sys.argv[1:2] == ["record"]:
        print(f"candidate rules: {record()} new game(s) recorded")
