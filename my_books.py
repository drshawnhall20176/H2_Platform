"""
my_books.py — one site-wide "My sportsbook" and "My pick'em app" setting (Nov 25).

Owner, Nov 25: "the one big thing that seems to have gotten lost along the way is our sportsbook and pickem selectors"
-- on Today, the sport desk, the commercial preview's sidebar, and site-wide. Every page used to keep its own
📖 Sportsbook dropdown, each starting at DraftKings; the Today cards had none at all.

Now the sidebar holds the two choices (every build and layout), and every page's own selector starts from them and
writes back to them, so choosing FanDuel once is FanDuel everywhere. The choices are kept for the session and in the
page's web address (?book=...&app=...), so a bookmark keeps them; nothing is saved on the server.
"""
from __future__ import annotations

from typing import List, Optional

BOOK_KEY = "my_book"
APP_KEY = "my_pickem"
DEFAULT_APP = "pick6"


def sportsbooks() -> List[str]:
    """Sportsbook keys (pick'em apps left out), DraftKings first."""
    import odds_api as O
    keys = [k for k in O.US_BOOKS if not O.is_pickem_book(k)]
    return ([O.DEFAULT_BOOK] if O.DEFAULT_BOOK in keys else []) + [k for k in keys if k != O.DEFAULT_BOOK]


def apps() -> List[str]:
    import pickem as PK
    return list(PK.APPS)


def _state():
    import streamlit as st
    return st.session_state


def _param(name: str) -> Optional[str]:
    try:
        import streamlit as st
        v = st.query_params.get(name)
        return str(v) if v else None
    except Exception:                                           # noqa: BLE001
        return None


def book() -> str:
    """The viewer's sportsbook (session, then the page address, then DraftKings)."""
    import odds_api as O
    ss = _state()
    if ss.get(BOOK_KEY) not in sportsbooks():
        p = _param("book")
        ss[BOOK_KEY] = p if p in sportsbooks() else O.DEFAULT_BOOK
    return ss[BOOK_KEY]


def app() -> str:
    """The viewer's pick'em app (session, then the page address, then DK Pick6 when listed)."""
    ss = _state()
    if ss.get(APP_KEY) not in apps():
        p = _param("app")
        ss[APP_KEY] = p if p in apps() else (DEFAULT_APP if DEFAULT_APP in apps() else apps()[0])
    return ss[APP_KEY]


def set_book(k: str) -> None:
    if k in sportsbooks():
        _state()[BOOK_KEY] = k
        _remember("book", k)


def set_app(k: str) -> None:
    if k in apps():
        _state()[APP_KEY] = k
        _remember("app", k)


def _remember(name: str, value: str) -> None:
    try:
        import streamlit as st
        st.query_params[name] = value
    except Exception:                                           # noqa: BLE001
        pass


def book_label(k: Optional[str] = None) -> str:
    import odds_api as O
    return O.book_label(k or book())


def app_label(k: Optional[str] = None) -> str:
    import pickem as PK
    return PK.APPS.get(k or app(), {}).get("name", k or app())


def sidebar() -> None:
    """The two choices in the sidebar (every page)."""
    import streamlit as st
    bk, ap = book(), app()
    st.session_state["_sb_my_book"] = bk
    st.session_state["_sb_my_app"] = ap
    st.sidebar.selectbox("📖 My sportsbook", sportsbooks(), key="_sb_my_book", format_func=book_label,
                         on_change=lambda: set_book(st.session_state["_sb_my_book"]),
                         help="Every page prices picks at this book first (where it posts the player). Kept in the "
                              "page address, so a bookmark remembers it.")
    st.sidebar.selectbox("🎟️ My pick'em app", apps(), key="_sb_my_app", format_func=app_label,
                         on_change=lambda: set_app(st.session_state["_sb_my_app"]),
                         help="The Pick'em Board opens on this app.")


def mirror(widget_key: str, value) -> None:
    """Before a page's own selector is drawn: start it at the site-wide choice."""
    _state()[widget_key] = value
