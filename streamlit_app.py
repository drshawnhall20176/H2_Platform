"""
Entry point for the H2 Sports MLB dashboard (explicit st.navigation).

Each page is given a STABLE, clean url_path so navigation state round-trips across reruns even
though the page filenames contain emoji. Without an explicit url_path, Streamlit derives the slug
from the (emoji-escaped) filename, which can fail to match on rerun and silently fall back to the
default page (Home) — the "every click goes back to Home" bug.

DEPLOY NOTE (owner build): set the app's "Main file path" to  streamlit_app.py
DEPLOY NOTE (Discord/public build): Streamlit Community Cloud won't let two apps in the same repo
share one entrypoint file — trying to "create a new app" pointed at streamlit_app.py just reopens
the existing app instead of making a second one. streamlit_app_discord.py exists solely to give
the second deployment its own entrypoint path; it contains no logic of its own, just `run()`.
"""

import re
import streamlit as st
from pathlib import Path

import sports


def run():
    st.set_page_config(page_title="H2 Sports MLB Dashboard", page_icon="⚾", layout="wide")

    # Sidebar sport picker — sets st.session_state["sport"], read by every shared page below.
    sports.render_sport_selector()
    active_sport = sports.active_key()

    # Audience gate: same codebase, deployed twice on Streamlit Cloud, differing only in one
    # secret. The owner deployment's secrets.toml has no AUDIENCE (or AUDIENCE = "owner") -> sees
    # everything. The Discord-facing deployment sets AUDIENCE = "public" in ITS secrets.toml ->
    # Bet Log, Media Room, Podcast Studio, and Edge Board are dropped from st.navigation()
    # entirely, so they're not just hidden from the sidebar, they have no route at all —
    # visiting the URL directly finds nothing to run. Edge Board is gated because it's tonight's
    # live board (the actionable, priced plays) — Track Record stays public as the proof layer,
    # per its own docstring: "this page sells the evidence of edge, not the edge itself."
    audience = st.secrets.get("AUDIENCE", "owner")
    if audience == "public":
        st.sidebar.caption("🌐 Public build — some tools are owner-only")

    here = Path(__file__).parent
    views_dir = here / "views"

    # Pages that only make sense for baseball (concepts like HR/pitching don't generalize) are
    # hidden entirely — not shown greyed-out — when a non-MLB sport is active. Shared proof pages
    # (Edge Board, Bet Log, Track Record, Media Room, Podcast, Retrospective) stay visible for
    # every sport and handle "engine not wired yet" gracefully inside the page itself.
    mlb_only_leads = {"1", "2", "10"}  # Pitching Lab, Dinger Engine, Matchup Lab

    # Internal tools kept off the Discord/public build — matched by TITLE (not page number) so a
    # future re-numbering of the views/ files can't silently un-gate one of these by accident.
    owner_only_titles = {"Bet Log", "Media Room", "Podcast Studio", "Edge Board"}

    # leading page-number -> (title, icon, stable url slug). The url_path is the key fix: it pins
    # each page to a predictable URL so reruns keep you on the same page instead of defaulting to
    # Home.
    meta = {
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

    def lead(name: str) -> str:
        """Leading page number as a string ('10_Matchup_Lab.py' -> '10'), else the stem."""
        m = re.match(r"(\d+)", name)
        return m.group(1) if m else Path(name).stem

    # Sort by the NUMERIC leading value so 10 comes after 9 (not after 1 alphabetically).
    view_files = sorted(views_dir.glob("*.py"),
                        key=lambda p: (int(lead(p.name)) if lead(p.name).isdigit() else 999, p.name))

    # Home is the landing page but NOT a forced default fallback (default= is intentionally
    # omitted, so a rerun on any other page stays on that page).
    pages = [st.Page(str(here / "Home.py"), title="Home", icon="⚾", url_path="home")]
    for f in view_files:
        key = lead(f.name)
        if key in mlb_only_leads and active_sport != "MLB":
            continue  # e.g. Dinger Engine makes no sense once NFL/NBA/etc. is selected
        title, icon, slug = meta.get(key, (f.stem, "📄", f"page_{key}"))
        if title in owner_only_titles and audience != "owner":
            continue  # Bet Log / Media Room / Podcast Studio / Edge Board: owner deployment only
        pages.append(st.Page(str(f), title=title, icon=icon, url_path=slug))

    st.navigation(pages).run()


if __name__ == "__main__":
    run()
