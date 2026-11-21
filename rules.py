"""
rules.py — the rules in force, each with a version and the slate it started on (Nov 21).

Owner, Nov 21: get the build and the proven edge to A+. Item 5 of that plan: rules frozen before they're tested. A
record is only evidence if the rule behind it didn't move while it was being kept -- tuning a rule until the past looks
good is the most common way a betting model fools its owner. So:

  * every rule that decides what the platform flags (💰 props, 💰 game lines, 🔒, the earned chance, the strongest
    list) is registered here with a version, a start date and its parameters;
  * the parameters are fingerprinted from the live code (fingerprint()); test_rules.py fails the build if they change
    without a new version here -- a rule can't drift silently;
  * the shown-picks ledger stamps each pick with the version in force (pick_ledger.add), and the record pages show each
    version's record from its own start date, so a change starts a fresh record instead of rewriting the old one.
"""
from __future__ import annotations

import hashlib
import json
from typing import Dict, List, Optional

# rule -> versions, oldest first. "params" is what fingerprint() must match for the CURRENT (last) version.
RULES: Dict[str, List[Dict]] = {
    "money_props": [
        {"v": 1, "from": "2026-11-19", "what": "NBA props the model priced 6-15% better than the sportsbook"},
        {"v": 2, "from": "2026-11-20", "what": "edge 3-20% at a sportsbook price, chance 40%+, price no more than 3% "
                                              "off the books' fair; live test in every props sport Nov 20-23",
         "fp": "809a075fca"},
    ],
    "money_games": [
        {"v": 1, "from": "2026-11-20", "what": "college basketball moneyline / spread, Money Score +4% to +12%, "
                                              "chance 40%+", "fp": "66491557ed"},
    ],
    "lock": [
        {"v": 1, "from": "2026-11-18", "what": "most probable with a sportsbook line"},
        {"v": 2, "from": "2026-11-20", "what": "most probable, a sportsbook line, and the price must pay (edge 0+)",
         "fp": "1269f85281"},
    ],
    "earned": [
        {"v": 1, "from": "2026-11-21", "what": "books' chance + the earned share of the model's disagreement (ridge "
                                              "logistic per sport x market, last 45 days, refit nightly); pick'em "
                                              "lines: the model's chance pulled toward 50% by its record",
         "fp": "21e4bbbefb"},
    ],
    "strong": [
        {"v": 1, "from": "2026-11-20", "what": "the 15 likeliest saved props by the model's chance"},
        {"v": 2, "from": "2026-11-21", "what": "up to 15 props and game-line 💰 picks by earned edge (earned chance "
                                              "less what the price needs), positive only, 5 per sport at most",
         "fp": "323240ef9c"},
    ],
    "shutoff": [
        {"v": 1, "from": "2026-11-21", "what": "a sport x market loses its 💰 / 🔒 / strongest-list place after 150+ "
                                              "graded picks losing even at the top of their 90% range, or the market "
                                              "moving against them 55%+ of 100+ moves (last 60 days, re-scored daily)",
         "fp": "ccf3c43786"},
    ],
}

NAMES = {"money_props": "💰 Money picks (props)", "money_games": "💰 Money picks (game lines)",
         "lock": "🔒 Most probable", "earned": "Earned chance", "strong": "Strongest picks list",
         "shutoff": "Automatic shut-off"}


def params() -> Dict[str, Dict]:
    """The live parameters of each rule, read from the code that applies it."""
    import money_score as MSC
    import pick_ledger as PL
    import props_engine as PE
    import props_money as PM
    import shutoff as SO
    return {
        "money_props": {"band": list(PE.MONEY_BAND), "min_chance": PE.MONEY_MIN_CHANCE, "min_mev": PE.MONEY_MIN_MEV,
                        "skip": {k: list(v) for k, v in sorted(PE.MONEY_SKIP.items())}},
        "money_games": {"band": list(MSC.BAND), "min_chance": MSC.MIN_CHANCE, "leagues": list(MSC.MONEY_LEAGUES),
                        "markets": list(MSC.MONEY_MARKETS)},
        "lock": {"min_ev": PE.LOCK_MIN_EV, "pickem_books": sorted(PE.PICKEM_BOOKS)},
        "earned": {"min_fit": PM.MIN_FIT, "window": PM.WINDOW_DAYS, "pickem_need": PM.PICKEM_NEED},
        "strong": {"n": PL.STRONG_N, "per_sport": PL.PER_SPORT},
        "shutoff": {"window": SO.WINDOW, "min_n": SO.MIN_N, "min_clv_n": SO.MIN_CLV_N, "min_beat": SO.MIN_BEAT,
                    "watch_n": SO.WATCH_N, "watch_roi": SO.WATCH_ROI},
    }


def fingerprint(rule: str, p: Optional[Dict] = None) -> str:
    p = params()[rule] if p is None else p
    return hashlib.sha1(json.dumps(p, sort_keys=True, default=str).encode()).hexdigest()[:10]


def current(rule: str) -> Dict:
    return RULES[rule][-1]


def version(rule: str, day: str) -> Optional[int]:
    """The version of `rule` in force on slate `day`, or None before its first version."""
    v = None
    for r in RULES.get(rule, []):
        if day >= r["from"]:
            v = r["v"]
    return v


def started(rule: str, v: int) -> Optional[str]:
    return next((r["from"] for r in RULES.get(rule, []) if r["v"] == v), None)


def table() -> List[Dict]:
    """Rows for the record pages: every rule's current version, since when, and what it is."""
    return [{"Rule": NAMES.get(k, k), "Version": f"v{current(k)['v']}", "Since": current(k)["from"],
             "What it is": current(k)["what"]} for k in RULES]


def drift() -> List[str]:
    """Rules whose live parameters no longer match their registered fingerprint (test_rules.py fails on any)."""
    out = []
    for k in RULES:
        fp = current(k).get("fp")
        if fp and fingerprint(k) != fp:
            out.append(f"{k}: parameters changed (fingerprint {fingerprint(k)}, registered {fp}) -- add version "
                       f"{current(k)['v'] + 1} to rules.RULES with today's date")
    return out
