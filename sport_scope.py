"""
sport_scope.py -- one sport choice for the whole site: the sidebar's Sport picker and a page's own sport filter are the
same control (Nov 27).

Owner, Nov 27: "there could be some confusion between what the sidebar shows as a selected sport, in this case NFL
Football, and what the main page shows, in this case all sports. I believe these should be synched and either
filtering mechanism should control the page display."

The state, in session:
  "sport"      -- the one sport every single-sport page shows (as before);
  "cc_all"     -- True when "All sports" is the choice (the flag Command Center already used);
  "sport_many" -- the sports picked when a page's filter holds several (shown in the sidebar as "Several sports").
Pages that span sports (MULTI_PAGES: Today, Test list, Rule scoreboard, Analyst record, My coach, Command Center) offer
"🌐 All sports" in the sidebar picker too; a page's own filter reads its starting value from here (seed_*) and writes
back on change (from_*), so whichever control is used, the other shows the same thing. On a single-sport page the
sidebar shows that page's sport (All sports can't apply there). Never raises.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

ALL = "__all__"
MANY = "__many__"
FLAG = "cc_all"
MANY_KEY = "sport_many"
MULTI_PAGES = ("today", "test_list", "rule_scoreboard", "analyst_record", "my_coach", "command_center", "",
               "pickem_board")                                   # Nov 27: the Pick'em board spans sports


def _ss():
    import streamlit as st
    return st.session_state


def is_multi(url_path: Optional[str]) -> bool:
    """Does this page span sports? ("" = the default page, Today in the customer layout.)"""
    return (url_path or "") in MULTI_PAGES


# --------------------------------------------------------------------------- the state
def current() -> str:
    """ALL, MANY or a sport key."""
    ss = _ss()
    if ss.get(MANY_KEY):
        return MANY
    if ss.get(FLAG, True):                                      # a new visit starts on All sports (owner rule)
        return ALL
    return ss.get("sport") or ""


def many() -> List[str]:
    return list(_ss().get(MANY_KEY) or [])


def choose(k: Optional[str]) -> None:
    """The one place the choice changes: ALL, or a sport key."""
    ss = _ss()
    ss[MANY_KEY] = []
    if not k or k == ALL:
        ss[FLAG] = True
    elif k != MANY:
        ss[FLAG] = False
        ss["sport"] = k


def choose_many(sel: Sequence[str]) -> None:
    """A page filter holding several sports (none = All, one = that sport)."""
    sel = [k for k in sel or [] if k]
    if len(sel) <= 1:
        choose(sel[0] if sel else ALL)
        return
    ss = _ss()
    ss[FLAG] = False
    ss[MANY_KEY] = list(sel)
    ss["sport"] = sel[-1]                                       # single-sport pages open on the last one picked


# --------------------------------------------------------------------------- a page's own filter
def seed_single(key: str, options: Sequence[str], all_value: str = ALL) -> None:
    """Set a single-choice filter (pills / radio / selectbox) to the site's choice before it is drawn."""
    cur = current()
    val = all_value if cur in (ALL, MANY) else cur
    if val not in options:
        val = all_value if all_value in options else None
    try:
        _ss()[key] = val
    except Exception:                                           # noqa: BLE001
        pass


def from_single(key: str, all_value: str = ALL) -> None:
    v = _ss().get(key)
    choose(ALL if (v is None or v == all_value) else v)


def seed_multi(key: str, options: Sequence[str]) -> None:
    """Set a multi-select filter ([] = all sports) to the site's choice before it is drawn."""
    cur = current()
    if cur == ALL:
        val = []
    elif cur == MANY:
        val = [k for k in many() if k in options]
    else:
        val = [cur] if cur in options else []
    try:
        _ss()[key] = val
    except Exception:                                           # noqa: BLE001
        pass


def from_multi(key: str) -> None:
    choose_many(list(_ss().get(key) or []))


# --------------------------------------------------------------------------- the sidebar picker
def sidebar_options(keys: Sequence[str], multi: bool = True) -> List[str]:
    """The same list on every page: a picker whose options change between pages is a new widget to the browser, which
    can send back its first option (All sports) and wipe the choice (seen live, Nov 27)."""
    return [ALL] + list(keys)


def sidebar_value(keys: Sequence[str], multi: bool) -> str:
    """All sports on a page that spans sports when that's the choice (several picked shows as All sports here; the
    page's filter lists them); otherwise the sport the page shows."""
    cur = current()
    if multi and cur in (ALL, MANY):
        return ALL
    sp = _ss().get("sport")
    return sp if sp in keys else (list(keys) or [""])[0]


def pick_from_sidebar(k: Optional[str], multi: bool, office: bool = False, sport_goto: Optional[str] = None) -> None:
    """The sidebar picker changed. All sports on a single-sport page opens Today (every sport) -- there is no
    all-sports version of that page."""
    if not k:
        return
    choose(k)
    if k == ALL and not multi and not office:
        _ss()["_goto_page"] = "today"
    elif k != ALL and sport_goto:                               # a page with no sport filter of its own (the classic
        _ss()["_goto_page"] = sport_goto                        # Today) opens that sport's desk


def label(k: str, get=None) -> str:
    if k == ALL:
        return "🌐 All sports"
    try:
        sp = (get or __import__("sports").get)(k)
        return f"{sp.icon} {sp.label}"
    except Exception:                                           # noqa: BLE001
        return str(k)
