"""
tour.py — a short first-visit tour of Today for the commercial layout (Nov 25, PropSeason scrub item 7).

PropSeason opens each board with a quick tour (matchup grade, formula, history, how to read a card). Ours walks a new
member through how H2 reads: the earned chance, the Bet? verdict, the cards, and where the record lives. Shown once
per visit until dismissed (remembered in the link with ?tour=done, like favorites); "❓ How to read Today" reopens it.
"""
from __future__ import annotations

from typing import List, Tuple

STEPS: List[Tuple[str, str]] = [
    ("👋 Welcome to H2",
     "**Today** puts every sport's picks and games on one page. Pick a sport in the bar at the top, or leave it on "
     "**All sports**. Use ◀ ▶ to look at another day."),
    ("🎯 Reading a pick card",
     "The big number is the **earned chance**: how often picks like this have actually hit, not just what the model "
     "hoped. The gold number is the price. **🃏 Bet** means a tested pick type whose earned chance beats its price; "
     "**🧪 Tracking** is being watched but hasn't earned a bet yet; **Info only** is the model's read and nothing more."),
    ("👤 Player cards",
     "Tap **Open →** on a pick for the player card: his last 10 games against tonight's line, the model's read in "
     "plain bullets, tonight's matchup, his minutes, and anything on the injury report."),
    ("🏟️ Game cards",
     "Each game opens to the model's score next to the market's, the line and total, each team's form, who's out, "
     "and the rotations (goalies for hockey). Context only: the projection already counts all of it."),
    ("🔎 Search, favorites & the screener",
     "Search any player on tonight's boards, ⭐ the ones you follow, and use the **Screener** to stack filters (our "
     "chance, last-10 hit rate, streak, soft matchup) over every playable pick."),
    ("📖 Your sportsbook",
     "Set your sportsbook and pick'em app in the sidebar. Every page prices picks there when it can."),
    ("📊 We show our record",
     "Every pick type carries its own record under **Track record**, losing ones included, and a losing type stops "
     "being shown as a pick until it earns its way back. Bet within your means. 21+."),
]
DONE_PARAM = "tour"
STEP_KEY = "_tour_step"
OPEN_KEY = "_tour_open"


def seen() -> bool:
    import streamlit as st
    try:
        if st.query_params.get(DONE_PARAM) == "done":
            return True
    except Exception:                                           # noqa: BLE001
        pass
    if st.session_state.get("_tour_done"):
        return True
    try:                                                        # Nov 25 (owner): every restart reopened it for him;
        return st.secrets.get("AUDIENCE", "owner") == "owner"   # on his site it opens only from its button
    except Exception:                                           # noqa: BLE001
        return False


def finish() -> None:
    import streamlit as st
    st.session_state["_tour_done"] = True
    st.session_state[OPEN_KEY] = False
    st.session_state[STEP_KEY] = 0
    try:
        st.query_params[DONE_PARAM] = "done"
    except Exception:                                           # noqa: BLE001
        pass


def _go(n: int) -> None:
    import streamlit as st
    st.session_state[STEP_KEY] = max(0, min(len(STEPS) - 1, n))


import streamlit as _st


def _dismissed() -> None:
    """Closing the pop-up with ✕ counts as done (it never reopens by itself)."""
    finish()


def _decorate(fn):
    try:
        return _st.dialog("Quick tour", width="large", on_dismiss=_dismissed)(fn)
    except TypeError:                                           # an older Streamlit without on_dismiss
        return _st.dialog("Quick tour", width="large")(fn)


@_decorate
def _show():
    st = _st
    i = int(st.session_state.get(STEP_KEY, 0))
    title, body = STEPS[i]
    st.markdown(f"### {title}")
    st.markdown(body)
    st.caption(" ".join("●" if k == i else "○" for k in range(len(STEPS))) + f"  ·  {i + 1} of {len(STEPS)}")
    c1, c2, c3 = st.columns(3)
    if c1.button("Skip tour", key="tour_skip", width="stretch"):
        finish()
        st.rerun()
    if i > 0 and c2.button("← Back", key="tour_back", width="stretch"):
        _go(i - 1)
        st.rerun()
    last = i == len(STEPS) - 1
    if c3.button("Got it" if last else "Next →", key="tour_next", type="primary", width="stretch"):
        if last:
            finish()
        else:
            _go(i + 1)
        st.rerun()


def render() -> None:
    """The reopen button, and the tour itself on a first visit."""
    import streamlit as st
    if st.button("❓ How to read Today", key="tour_reopen"):
        st.session_state[OPEN_KEY] = True
        st.session_state[STEP_KEY] = 0
    if st.session_state.get(OPEN_KEY) or not seen():
        st.session_state[OPEN_KEY] = True
        _show()
