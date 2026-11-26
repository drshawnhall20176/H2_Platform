"""
office.py -- the Owner Office (Nov 18).

Owner: "I would like to have these sections a completely separate page and not applied to each sport's sidebar. This
new section should be password protected just like the bet log. I want to be the only one with access to this and not
my other partners unless I give them the password."

The self-grading, proof, ops and investor pages (Bet Log, Track Record, Postgame Review, My Coach, Reports, Model
Performance ...) are no longer in any sport's sidebar. They are routed only inside the Office: a separate menu that
exists only after the Office password is entered (secret OWNER_OFFICE_PASSWORD -- its own secret, so a partner who
knows the trading password still can't get in). Until then those pages have no route at all; a direct URL finds
nothing. With the secret missing the Office stays shut (fails closed).
"""
from __future__ import annotations

from typing import Optional

# page number -> the Office section it sits in
PAGES = {
    "64": "📒 MONEY", "18": "📒 MONEY", "19": "📒 MONEY", "42": "📒 MONEY", "48": "📒 MONEY", "51": "📒 MONEY",
    "16": "🔍 GRADING & PROOF", "17": "🔍 GRADING & PROOF", "40": "🔍 GRADING & PROOF", "41": "🔍 GRADING & PROOF",
    "56": "🔍 GRADING & PROOF", "65": "🔍 GRADING & PROOF",
    "20": "📣 OPS & CONTENT", "21": "📣 OPS & CONTENT", "22": "📣 OPS & CONTENT",
    "49": "💼 INVESTOR RELATIONS",
}
SECTION_ORDER = ("🔐 OWNER OFFICE", "📒 MONEY", "🔍 GRADING & PROOF", "📣 OPS & CONTENT", "💼 INVESTOR RELATIONS")
SECRET = "OWNER_OFFICE_PASSWORD"
UNLOCKED, MODE = "office_unlocked", "office_mode"


def is_office_page(key: str) -> bool:
    return key in PAGES


def check(entered: Optional[str], expected) -> bool:
    """Fails closed: no secret configured = no way in."""
    if not expected or not entered:
        return False
    return str(entered) == str(expected)


def unlocked(state) -> bool:
    return bool(state.get(UNLOCKED))


def active(state) -> bool:
    return bool(state.get(UNLOCKED)) and bool(state.get(MODE))


def leave(state, lock: bool = False) -> None:
    """Out of the Office and back to Today (owner, Nov 18: "when I exit the Owner Office have the page return to the
    Today page"); `lock` also forgets the password for this session."""
    state[MODE] = False
    if lock:
        state[UNLOCKED] = False
    state["_goto_page"] = "today"
