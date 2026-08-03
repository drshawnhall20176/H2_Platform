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

_H2_MARK = Path(__file__).parent / "assets" / "h2_mark.png"


def run():
    # Real H2 Sports mark as the browser tab icon when the asset is present, the original
    # emoji as an honest fallback otherwise (a stripped-down deploy missing assets/ should never
    # crash page config) -- same fail-soft posture components.hero_banner's own logo uses.
    page_icon = str(_H2_MARK) if _H2_MARK.exists() else "⚾"
    st.set_page_config(page_title="H2 Sports MLB Dashboard", page_icon=page_icon, layout="wide")

    # Sport selector state must be set BEFORE building navigation (it drives which pages show).
    # We read/set session state directly here rather than rendering UI, so the sidebar widget
    # rendered below can pick up the correct current value without a double-render issue.
    import sports as _sports
    live = _sports.enabled_sports()
    keys = [s.key for s in live]
    if st.session_state.get("sport") not in keys:
        st.session_state["sport"] = _sports.DEFAULT_SPORT
    active_sport = st.session_state["sport"]

    # Sidebar sport picker -- called here so it renders in the sidebar. Streamlit places
    # st.navigation() page links at the top of the sidebar regardless of call order, so the
    # selector ends up below the nav list. This is a known Streamlit constraint with no clean
    # workaround -- the selector is still functional, just positioned at the bottom of the nav
    # links rather than above them. The dropdown itself opens upward when near the bottom of
    # the viewport, which avoids the truncation issue seen when it was buried below "View less".
    sports.render_sport_selector()

    # Audience gate: same codebase, deployed twice on Streamlit Cloud, differing only in one
    # secret. The owner deployment's secrets.toml has no AUDIENCE (or AUDIENCE = "owner") -> sees
    # everything. The Discord-facing deployment sets AUDIENCE = "public" in ITS secrets.toml ->
    # Bet Log, Media Room, Podcast Studio, Edge Board, Matchup Lab, and Track Record are dropped
    # from st.navigation() entirely, so they're not just hidden from the sidebar, they have no
    # route at all — visiting the URL directly finds nothing to run.
    #
    # Matchup Lab and Track Record moved to this list on 2026-07-18, for two GENUINELY DIFFERENT
    # reasons, not one blanket monetization call — worth keeping straight since they point to
    # different futures for each page:
    #   - Matchup Lab: a real paid-feature decision. The analysis is genuinely valuable and
    #     working; it's being reserved for payers.
    #   - Track Record: NOT primarily monetization. Shawn's own call — there isn't enough real
    #     graded bet history logged yet for this page to show anything meaningful, so a public
    #     visitor would just find an empty page. Gated because it currently has nothing to show,
    #     not because the content itself is being held back from public view on purpose. Worth
    #     revisiting once there's enough real logged history for it to actually demonstrate
    #     something — this is closer to "not ready" than "not for you."
    # This doesn't reverse the earlier ANALYTICAL reasoning for why Track Record had been public
    # in the first place: it's still true that a track record only shows historical, already-
    # graded results ("the evidence of edge, not the edge itself") — that reasoning about what's
    # SAFE to show publicly hasn't changed, and isn't why it's gated now. Track Record's own
    # docstring was updated to match, not left describing a public-facing purpose it no longer has.
    audience = st.secrets.get("AUDIENCE", "owner")
    if audience == "public":
        st.sidebar.caption("🌐 Public build — some tools are owner-only")

    here = Path(__file__).parent
    views_dir = here / "views"

    # Pages that only make sense for a SPECIFIC SET of sports are hidden entirely — not shown
    # greyed out — when a different sport is active.
    sport_only_leads = {
        "5": ("MLB",),                                   # Bullpen Watch -- built directly on
                                                          # mlb_engine's own bullpen-fatigue
                                                          # functions, no WNBA/NFL equivalent
                                                          # exists yet, same posture as Pitching
                                                          # Lab/Dinger Engine below
        "6": ("MLB",),                                   # Game Watch -- same MLB-only posture,
                                                          # built on the same bullpen functions
                                                          # plus build_pitching_slate's FIP
        "7": ("MLB",), "8": ("MLB",), "9": ("MLB",),      # Pitching Lab, Dinger Engine, Matchup Lab (MLB)
        "10": ("WNBA", "NBA", "NCAAMB"),                 # Hot Hand Engine (opponent-adjusted leaderboard)
        "11": ("WNBA", "NBA", "NCAAMB"),                 # Matchup Lab (WNBA/NBA/NCAAMB) — same slot as page 9, different sport
        "12": ("NFL",),                                  # Matchup Lab (NFL) — own page, not the shared basketball one (see its own module docstring for why)
        "13": ("NFL",),                                  # Anytime TD Engine — NFL's Dinger Engine analog
        "14": ("NFL",),                                  # QB Lab — NFL's Pitching Lab analog
        "23": ("UFC",),                                  # UFC Fight Card -- MMA-only, no MLB/NFL equivalent
        "24": ("MLB",),                                  # Highlights -- already gated MLB-only at the
                                                          # page level (its own real fields aren't wired
                                                          # into other sports yet), just never had the
                                                          # matching sidebar-level gate until now.
        "25": ("NFL",),                                  # Hot Hand Engine (NFL) -- own page, not the
                                                          # shared basketball one, same real reasoning
                                                          # as Matchup Lab (NFL)'s own page 12.
        "26": ("MLB",),                                  # Player Lines -- recent-form trend charts,
                                                          # pitcher or batter, MLB's own real markets.
        "27": ("MLB",),                                  # First Innings Totals -- built directly on
                                                          # mlb_engine's own first-N-innings functions,
                                                          # no WNBA/NFL equivalent exists yet.
    }

    # REAL, REPORTED GAP CLOSED HERE: these titles all carry a has_projections check that shows
    # "doesn't apply to UFC, head to UFC Fight Card" and st.stop()s immediately for any sport with
    # no projections pipeline (has_projections=False -- currently just UFC) -- confirmed by
    # reading each page's own gate, not assumed. Model Dashboard doesn't literally st.stop(), but
    # every section on it is driven entirely by graded plays that are always [] for such a sport,
    # so it silently renders an all-empty page instead. None of these were graceful degradation in
    # practice — every one was a guaranteed dead end reachable from the sidebar, real clutter for
    # exactly the reason a person reported: a UFC user sees 10 live-looking links that all lead to
    # the same "this isn't for you" message. Matched by TITLE (not page number), same reasoning as
    # owner_only_titles below. Bet Log stays visible on purpose -- it's a real, functional log for
    # any sport with a market_map (UFC has one), not projections-dependent at all.
    projections_only_titles = {"Best Bets", "Graded Picks", "Suggested Parlays", "Speculative Basket",
                               "Edge Board", "Retrospective", "Model Dashboard", "Track Record",
                               "Media Room", "Podcast Studio"}

    # Internal/paid tools kept off the Discord/public build — matched by TITLE (not page number)
    # so a future re-numbering of the views/ files can't silently un-gate one of these by
    # accident. Matching by title is also what makes gating "Matchup Lab" here correctly cover
    # all three variants (MLB, WNBA/NBA/NCAAMB, NFL) with one entry, since they share the title.
    owner_only_titles = {"Bet Log", "Media Room", "Podcast Studio", "Edge Board",
                         "Matchup Lab", "Track Record", "Data Health",
                         "Suggested Parlays", "Speculative Basket", "Graded Picks"}

    # leading page-number -> (title, icon, stable url slug). The url_path is the key fix: it pins
    # each page to a predictable URL so reruns keep you on the same page instead of defaulting to
    # Home.
    #
    # NUMBERING, RE-GROUPED DIRECTLY ON REQUEST AFTER A PLATFORM AUDIT (previously reflected build
    # order, not a designed sidebar journey -- recommendation pages and self-grading pages were
    # each scattered across the full 0-22 range with unrelated pages between them): 1-4
    # recommendations (shared board, different lenses), 5-6 moneyline signals, 7-14 deep research,
    # 15 trading desk, 16-19 self-grading/proof (now cross-linked to each other, see each page's
    # own docstring), 20-22 ops/content. Command Center stays 0, the landing page throughout.
    meta = {
        "0": ("Command Center", "🏆", "command_center"),
        "1": ("Best Bets",      "⭐", "best_bets"),
        "2": ("Graded Picks",   "🏅", "graded_picks"),
        "3": ("Suggested Parlays", "🎫", "suggested_parlays"),
        "4": ("Speculative Basket", "🧺", "speculative_basket"),
        "5": ("Bullpen Watch",  "🛡️", "bullpen_watch"),
        "6": ("Game Watch",     "📡", "game_watch"),
        "7": ("Pitching Lab",   "🎯", "pitching_lab"),
        "8": ("Dinger Engine",  "💣", "dinger_engine"),
        "9": ("Matchup Lab",    "🔬", "matchup_lab"),
        "10": ("Hot Hand Engine", "🔥", "hot_hand_engine"),
        "11": ("Matchup Lab",   "🔬", "matchup_lab"),   # WNBA version — same slot as page 9
        "12": ("Matchup Lab",   "🔬", "nfl_matchup_lab"),   # NFL version — same title, distinct url_path
        "13": ("Anytime TD Engine", "🎯", "anytime_td_engine"),
        "14": ("QB Lab",        "🏈", "qb_lab"),
        "15": ("Edge Board",    "📈", "edge_board"),
        "16": ("Retrospective", "🔍", "retrospective"),
        "17": ("Model Dashboard", "🏆", "model_dashboard"),
        "18": ("Bet Log",       "📒", "bet_log"),
        "19": ("Track Record",  "📊", "track_record"),
        "20": ("Data Health",   "🩺", "data_health"),
        "21": ("Media Room",    "📣", "media_room"),
        "22": ("Podcast Studio", "🎙️", "podcast_studio"),
        "23": ("UFC Fight Card", "🥊", "ufc_fight_card"),
        "24": ("Highlights",    "✨", "highlights"),
        "25": ("Hot Hand Engine", "🔥", "nfl_hot_hand_engine"),   # NFL version — same title as
                                                                  # page 10, distinct url_path
        "26": ("Player Lines",   "📉", "mlb_player_lines"),
        "27": ("First Innings Totals", "1️⃣", "mlb_first_innings_totals"),
        "28": ("League Schedules", "📅", "league_schedules"),
    }

    # SIDEBAR SECTIONS, added directly on request: st.navigation natively supports a
    # dict-of-lists (each key becomes a real, collapsible section header in the sidebar) instead
    # of one flat list -- confirmed directly against Streamlit's own docs before using it, not
    # assumed. 6 sections. Started at 7 (the original platform-audit grouping), consolidated to
    # 5 after real, reported sidebar clutter, then split back to 6 directly on request once
    # "Research & Signals" (merged from the old Live Signals + Deep Research + Trading Desk) grew
    # to the sidebar's single largest section. This split back out along the SAME real line the
    # original 7-section grouping already used -- Live Signals is specifically tonight's-game
    # tools (bullpen freshness, game-day signals), Deep Research is projection/analysis tools
    # (pitch-level and matchup-level modeling) -- not an arbitrary 50/50 cut. Edge Board (still
    # only 1 item on its own) stayed folded into Deep Research rather than getting its own
    # section, since a true 1-item section was the original problem this whole restructuring
    # started from.
    #
    # SECTION NAMES ARE UPPERCASE for visual prominence against the page links beneath them --
    # a genuinely safe way to do this (see this comment's own earlier reasoning, preserved
    # below): CSS targeting Streamlit's own internal sidebar DOM (stSidebarNav,
    # stSidebarNavItems) is confirmed unreliable across releases, so uppercase text -- a plain
    # Python string, no dependency on internals that could silently stop working -- is the lever
    # used here instead.
    SECTION_OF = {}
    for k in ("0", "28"):
        SECTION_OF[k] = "🏠 START HERE"
    for k in ("1", "2", "3", "4", "23", "24"):
        SECTION_OF[k] = "🎯 RECOMMENDATIONS"
    for k in ("5", "6"):
        SECTION_OF[k] = "🛰️ LIVE SIGNALS"
    for k in ("7", "8", "9", "10", "11", "12", "13", "14", "15", "25", "26", "27"):
        SECTION_OF[k] = "🔬 DEEP RESEARCH"
    for k in ("16", "17", "18", "19"):
        SECTION_OF[k] = "🔍 SELF-GRADING & PROOF"
    for k in ("20", "21", "22"):
        SECTION_OF[k] = "📣 OPS & CONTENT"

    def lead(name: str) -> str:
        """Leading page number as a string ('10_Matchup_Lab.py' -> '10'), else the stem."""
        m = re.match(r"(\d+)", name)
        return m.group(1) if m else Path(name).stem

    # Sort by the NUMERIC leading value so 10 comes after 9 (not after 1 alphabetically).
    view_files = sorted(views_dir.glob("*.py"),
                        key=lambda p: (int(lead(p.name)) if lead(p.name).isdigit() else 999, p.name))

    # Home is the landing page but NOT a forced default fallback (default= is intentionally
    # omitted, so a rerun on any other page stays on that page). Placed in its own section
    # alongside Command Center (see SECTION_OF above) rather than left unsectioned -- st.
    # navigation's dict mode sections everything or nothing, there's no supported way to mix a
    # loose top-level page with sectioned ones (confirmed directly against Streamlit's own docs).
    sections: dict = {"🏠 START HERE": [st.Page(str(here / "Home.py"), title="Home", icon="⚾", url_path="home")]}
    for f in view_files:
        key = lead(f.name)
        required_sports = sport_only_leads.get(key)
        if required_sports and active_sport not in required_sports:
            continue  # e.g. Dinger Engine makes no sense once WNBA/NBA is selected, and vice versa
        title, icon, slug = meta.get(key, (f.stem, "📄", f"page_{key}"))
        if title in projections_only_titles and not sports.get(active_sport).has_projections:
            continue  # Best Bets / Graded Picks / Edge Board / Retrospective / etc: every one of
                      # these is a guaranteed dead end for an outcome-based sport like UFC -- see
                      # projections_only_titles' own comment above for the real, reported gap this closes
        if title in owner_only_titles and audience != "owner":
            continue  # Bet Log / Media Room / Podcast Studio / Edge Board / Matchup Lab / Track Record: owner deployment only
        section = SECTION_OF.get(key, "🔬 DEEP RESEARCH")   # a real, sensible default for any
        # future page whose number isn't added to SECTION_OF yet -- never silently disappears,
        # never crashes, just lands somewhere reasonable until explicitly categorized.
        sections.setdefault(section, []).append(st.Page(str(f), title=title, icon=icon, url_path=slug))

    # Bold/colored sidebar section-header styling was attempted here and confirmed (via a real
    # screenshot, pixel-sampled) to be inert against this Streamlit version's actual DOM -- see
    # the "CSS risk" section of the project handoff. Removed rather than left as dead code.
    # UPPERCASE section names remain the confirmed, real, working lever for visual separation.
    st.navigation(sections).run()


if __name__ == "__main__":
    run()
