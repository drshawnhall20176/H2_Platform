"""
nav_layout.py — the commercial (customer) sidebar (Nov 16).

The owner app's sidebar grew one page per tool: seven sections, up to 27 pages in one of them. That suits the owner's
workbench, not a paying customer, who needs to see at once where today's picks, the games, the players and the proof
are. This module is the customer layout: four sections, pages matched by TITLE (so a renumbered views/ file can't move
or expose one by accident), and everything not listed here hidden.

Who sees it:
  * a deployment whose AUDIENCE secret is "commercial" (it is a non-owner build: every owner-only gate applies), and
  * the owner app while "Customer layout" is on in its sidebar (the default since Nov 25) -- the layout only; pages
    still show the owner's own log boxes there, and the toggle goes back to the classic workbench.
The public Discord build (AUDIENCE = "public") switched to it on Nov 25 (PUBLIC_LIVE); the owner app opens in it.

Soccer, International Hoops and Tennis sit in their own "Beta" section: tracking only, record not proven.
"""
from __future__ import annotations

from typing import Dict, List, Optional

COMMERCIAL = "commercial"
PREVIEW_KEY = "preview_commercial"
OWNER_HOME = "🏠 START HERE"

TODAY = "🏠 TODAY"
RESEARCH = "🔎 RESEARCH"
RECORD = "📊 TRACK RECORD"
BETA = "🧪 BETA · TRACKING ONLY"
SECTION_ORDER = (TODAY, RESEARCH, RECORD, BETA)

# section -> (page title in the app, the name the customer sees), in the order they are listed.
# Nov 16 (second pass): Today replaces Home, the player tools are one Players page (players_hub.py), plain names.
LAYOUT: Dict[str, tuple] = {
    TODAY: (("Today", "Today"), ("Best Bets", "All picks"), ("Pick'em Board", "Pick'em"), ("Live Games", "Live"),
            ("Long Shots", "Long shots"),
            ("UFC Fight Card", "Fight card"), ("Highlights", "My filters")),
    RESEARCH: (("Game Lab", "Games"), ("Players", "Players"), ("Soft Spots", "Soft spots"), ("Alt Lines", "Alt-line hit rates"), ("League Schedules", "Schedule"),
               ("Analyst Desk", "Daily write-up"), ("Game Watch", "Game watch"), ("Bullpen Watch", "Bullpens")),
    RECORD: (("Model Record", "Track record"), ("Analyst Record", "Analyst record")),
    BETA: (("Tennis Lab", "Tennis"), ("International Hoops", "International hoops"), ("Soccer Lab", "Soccer")),
}
COMMERCIAL_ONLY = ("Today", "Players")          # customer pages: not in the owner or public Discord sidebars
_SECTION_OF = {title: sec for sec, pairs in LAYOUT.items() for title, _ in pairs}
_LABEL = {title: label for pairs in LAYOUT.values() for title, label in pairs}
_RANK = {label: i for pairs in LAYOUT.values() for i, (_, label) in enumerate(pairs)}


# Nov 25 (owner: "let's build 1-7 then we can publish the live sites on owners and discord"): the customer layout is
# live. The Discord build ("public") gets it outright; the owner app opens in it (the sidebar toggle, on by default,
# goes back to the classic workbench).
PUBLIC_LIVE = True


def is_commercial(audience, preview=False) -> bool:
    """The customer layout: a "commercial" deployment, the Discord build once it went live, or the owner with the
    layout switched on (the default since Nov 25)."""
    a = str(audience or "owner").lower()
    return a == COMMERCIAL or (a == "public" and PUBLIC_LIVE) or (a == "owner" and bool(preview))


def commercial_section(title: str) -> Optional[str]:
    """The customer section a page belongs to; None = not part of the commercial product (hidden)."""
    return _SECTION_OF.get(str(title))


def label(title: str) -> str:
    """The name a customer sees for a page ("Game Lab" -> "Games")."""
    return _LABEL.get(str(title), str(title))


def arrange(sections: Dict[str, List]) -> Dict[str, List]:
    """Sections in customer order with pages in LAYOUT order. The owner's Home (its own section) is dropped: Today is
    the customer's front page. An empty section is dropped. Pages are anything with a `.title` (the customer name)."""
    merged: Dict[str, List] = {}
    for sec, pages in (sections or {}).items():
        if sec == OWNER_HOME:
            continue
        merged.setdefault(sec, []).extend(pages)
    out: Dict[str, List] = {}
    for sec in SECTION_ORDER + tuple(s for s in merged if s not in SECTION_ORDER):
        pages = merged.get(sec) or []
        if pages:
            out[sec] = sorted(pages, key=lambda p: _RANK.get(str(getattr(p, "title", "")), 99))   # stable
    return out
