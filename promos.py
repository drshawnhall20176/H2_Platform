"""
promos.py -- the sportsbooks' recurring promotions and which ones are on today (Nov 17).

Owner: "a page dedicated to the various sportsbooks' special promotions like King of the Court. These promotions should
pop up automatically when offered." The books publish promotions only inside their apps (no feed, and their pages
can't be read automatically under their terms), so "automatically" works off each promotion's SCHEDULE: a recurring
promo (King of the Court = every NBA Tuesday) is listed here once with its days, sports and season window, and shows
itself on every matching day. One-offs and new recurring promos are added by the owner on the Promotions page (saved in
app_settings under CUSTOM_KEY) and behave the same way.

Every entry says where its rules were last checked. Rules change; the card always says to confirm in the book's app.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Sequence

CUSTOM_KEY = "promos:custom"
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
EVERY_DAY = tuple(range(7))

# Researched Nov 17, 2026 for the books in the platform's book list. Only promotions confirmed to recur are seeded;
# one-game specials (e.g. FanDuel's Sept 2026 "Early Win" on a single NFL game) are the kind the owner adds by hand.
SEED: List[Dict] = [
    {"id": "dk_kotc", "book": "DraftKings", "name": "👑 King of the Court", "sports": ["NBA"], "days": [1],
     "window": ["2026-10-20", "2027-04-15"], "banner": True, "tool": "kotc",
     "rules": "Every NBA Tuesday in the regular season: bet on the player you think posts the night's most points + "
              "rebounds + assists (the PRA leader market). If your player is the night's PRA leader, you share the "
              "bonus-bet prize pool on top of your winnings. Opt in, minimum odds and stake rules are in the app.",
     "checked": "Nov 17, 2026 — DraftKings' Week 4 King of the Court ran Tue Nov 11, 2026 (Oddschecker).",
     "source": "https://www.oddschecker.com/us/insight/basketball/nba/20261111-who-was-the-draftkings-king-of-the-court-for-week-4"},
    {"id": "b365_early_payout", "book": "Bet365", "name": "⏱️ Early Payout (moneyline)",
     "sports": ["NFL", "NBA", "NHL", "SOCCER"], "days": list(EVERY_DAY), "window": ["2026-09-01", "2027-06-30"],
     "banner": False, "tool": None,
     "rules": "Pre-game moneyline bets are paid as winners as soon as your team leads by NFL 17 points, NBA 20, NHL 3 "
              "goals, soccer 2 goals (any league) — at any point, even if they lose. Automatic, no opt-in. Spreads, "
              "puck lines and totals settle normally; in a parlay only the leg that hits the lead is marked won. "
              "Soccer and MLB windows end Dec 31, 2026; NBA and NHL run to Jun 30, 2027; NFL through the Super Bowl.",
     "checked": "Nov 17, 2026 — rules page updated October 2026 (Pikkit).",
     "source": "https://pikkit.com/blog/bet365-early-payout"},
    {"id": "dk_early_win", "book": "DraftKings", "name": "⏱️ Early Win (select days)", "sports": ["NBA", "NFL"],
     "days": [], "window": None, "banner": False, "tool": None,
     "rules": "Runs on select game days only, with one token per day: a pre-game moneyline pays early if your team leads "
              "by 10+ (NBA) or the posted margin (NFL) at any point. Betting both sides disqualifies the bet. "
              "Not on a fixed schedule — add the day here when it shows up in the app.",
     "checked": "Nov 17, 2026 — described as periodic / select days (TheGameDay, updated Oct 16, 2026).",
     "source": "https://thegameday.com/news/draftkings-nfl-early-win-promo/"},
]


def _in_window(p: Dict, d: date) -> bool:
    w = p.get("window")
    if not w:
        return True
    lo, hi = (date.fromisoformat(x) if x else None for x in w)
    return (lo is None or d >= lo) and (hi is None or d <= hi)


def all_promos(custom: Optional[Sequence[Dict]] = None) -> List[Dict]:
    return [dict(p, custom=False) for p in SEED] + [dict(p, custom=True) for p in (custom or [])]


def custom_promos() -> List[Dict]:
    try:
        import model_store as MS
        v = MS.get_setting(CUSTOM_KEY, [])
        return v if isinstance(v, list) else []
    except Exception:                                           # noqa: BLE001
        return []


def save_custom(promos: Sequence[Dict]) -> bool:
    import model_store as MS
    return MS.save_setting(CUSTOM_KEY, list(promos))


def on_today(d: date, playing: Optional[Sequence[str]] = None, custom: Optional[Sequence[Dict]] = None,
             banners_only: bool = False) -> List[Dict]:
    """Promotions running on `d`: the weekday matches (or a one-off date matches) and it's inside its season window.
    With `playing` (sport keys with games today), a promo shows only if one of its sports is playing."""
    out = []
    for p in all_promos(custom if custom is not None else custom_promos()):
        if banners_only and not p.get("banner"):
            continue
        dates = p.get("dates") or []
        if d.isoformat() not in dates and d.weekday() not in (p.get("days") or []):
            continue
        if not _in_window(p, d):
            continue
        if playing is not None and p.get("sports") and not set(p["sports"]) & set(playing):
            continue
        out.append(p)
    return out


def schedule_text(p: Dict) -> str:
    days = p.get("days") or []
    if p.get("dates"):
        return ", ".join(p["dates"])
    if not days:
        return "select days (added when offered)"
    if sorted(days) == list(EVERY_DAY):
        return "every day in season"
    return ", ".join(WEEKDAYS[i] for i in sorted(days))
