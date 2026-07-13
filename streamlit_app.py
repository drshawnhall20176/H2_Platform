"""
Entry point for the H2 Sports MLB dashboard (explicit st.navigation).

Each page is given a STABLE, clean url_path so navigation state round-trips across reruns even
though the page filenames contain emoji. Without an explicit url_path, Streamlit derives the slug
from the (emoji-escaped) filename, which can fail to match on rerun and silently fall back to the
default page (Home) — the "every click goes back to Home" bug.

DEPLOY NOTE: set the app's "Main file path" to  streamlit_app.py  (not Home.py).
"""

import re
import streamlit as st
from pathlib import Path

st.set_page_config(page_title="H2 Sports MLB Dashboard", page_icon="⚾", layout="wide")

_HERE = Path(__file__).parent
_VIEWS = _HERE / "views"

# leading page-number -> (title, icon, stable url slug). The url_path is the key fix: it pins each
# page to a predictable URL so reruns keep you on the same page instead of defaulting to Home.
_META = {
    "0": ("Command Center", "🏆", "command_center"),
    "1": ("Pitching Lab",   "🎯", "pitching_lab"),
    "2": ("Dinger Engine",  "💣", "dinger_engine"),
    "3": ("Edge Board",     "📈", "edge_board"),
    "4": ("Bet Log",        "📒", "bet_log"),
    "5": ("Best Bets",      "⭐", "best_bets"),
    "6": ("Retrospective",  "🔍", "retrospective"),
    "7": ("Media Room",     "📣", "media_room"),
    "8": ("Podcast Studio", "🎙️", "podcast_studio"),
    "9": ("Track Record",   "📊", "track_record"),
    "10": ("Matchup Lab",   "🔬", "matchup_lab"),
}


def _lead(name: str) -> str:
    """Leading page number as a string ('10_Matchup_Lab.py' -> '10'), else the stem."""
    m = re.match(r"(\d+)", name)
    return m.group(1) if m else Path(name).stem


# Sort by the NUMERIC leading value so 10 comes after 9 (not after 1 alphabetically).
_view_files = sorted(_VIEWS.glob("*.py"),
                     key=lambda p: (int(_lead(p.name)) if _lead(p.name).isdigit() else 999, p.name))

# Home is the landing page but NOT a forced default fallback (default= is intentionally omitted,
# so a rerun on any other page stays on that page).
pages = [st.Page(str(_HERE / "Home.py"), title="Home", icon="⚾", url_path="home")]
for f in _view_files:
    key = _lead(f.name)
    title, icon, slug = _META.get(key, (f.stem, "📄", f"page_{key}"))
    pages.append(st.Page(str(f), title=title, icon=icon, url_path=slug))

st.navigation(pages).run()
