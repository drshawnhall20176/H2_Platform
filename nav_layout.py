"""
nav_layout.py — the commercial (customer) sidebar (Nov 16).

The owner app's sidebar grew one page per tool: seven sections, up to 27 pages in one of them. That suits the owner's
workbench, not a paying customer, who needs to see at once where today's picks, the games, the players and the proof
are. This module is the customer layout: five sections, pages matched by TITLE (so a renumbered views/ file can't move
or expose one by accident), and everything not listed here hidden.

Who sees it:
  * a deployment whose AUDIENCE secret is "commercial" (it is a non-owner build: every owner-only gate applies), and
  * the owner app when "Preview the commercial layout" is switched on in its sidebar -- the layout only; pages still
    show the owner's own log boxes there.
The public Discord build (AUDIENCE = "public") is unchanged until the owner switches it.

Soccer, International Hoops and Tennis sit in their own "Beta" section: tracking only, record not proven.
"""
from __future__ import annotations

from typing import Dict, List, Optional

COMMERCIAL = "commercial"
PREVIEW_KEY = "preview_commercial"
OWNER_HOME = "🏠 START HERE"

TODAY = "🏠 TODAY"
GAMES = "🏟️ GAMES"
PLAYERS = "👤 PLAYERS"
RECORD = "📊 TRACK RECORD"
BETA = "🧪 BETA · TRACKING ONLY"
SECTION_ORDER = (TODAY, GAMES, PLAYERS, RECORD, BETA)

# section -> page titles, in the order they are listed
LAYOUT: Dict[str, tuple] = {
    TODAY: ("Home", "Best Bets", "Live Games", "Long Shots", "Analyst Desk", "UFC Fight Card", "Highlights"),
    GAMES: ("Game Lab", "League Schedules", "Game Watch", "Bullpen Watch"),
    PLAYERS: ("Position Matchups", "Matchup Lab", "Hot Hand Engine", "QB Lab", "Anytime TD Engine", "Pitching Lab",
              "Dinger Engine"),
    RECORD: ("Model Record", "Analyst Record"),
    BETA: ("Tennis Lab", "International Hoops", "Soccer Lab"),
}
_SECTION_OF = {title: sec for sec, titles in LAYOUT.items() for title in titles}
_RANK = {title: i for titles in LAYOUT.values() for i, title in enumerate(titles)}


def is_commercial(audience, preview=False) -> bool:
    """The customer layout: a "commercial" deployment, or the owner previewing it."""
    a = str(audience or "owner").lower()
    return a == COMMERCIAL or (a == "owner" and bool(preview))


def commercial_section(title: str) -> Optional[str]:
    """The customer section a page belongs to; None = not part of the commercial product (hidden)."""
    return _SECTION_OF.get(str(title))


def arrange(sections: Dict[str, List]) -> Dict[str, List]:
    """Sections in customer order with pages in LAYOUT order. The owner layout's home section folds into TODAY, and
    an empty section is dropped. Pages are anything with a `.title`."""
    merged: Dict[str, List] = {}
    for sec, pages in (sections or {}).items():
        merged.setdefault(TODAY if sec == OWNER_HOME else sec, []).extend(pages)
    out: Dict[str, List] = {}
    for sec in SECTION_ORDER + tuple(s for s in merged if s not in SECTION_ORDER):
        pages = merged.get(sec) or []
        if pages:
            out[sec] = sorted(pages, key=lambda p: _RANK.get(str(getattr(p, "title", "")), 99))   # stable
    return out
