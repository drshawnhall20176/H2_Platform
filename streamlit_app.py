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


def connection_status() -> str:
    """One sidebar line: is this deployment reading the shared model database and live odds?"""
    import betlog as B
    import best_bets_data as BBD
    db = bool(getattr(B, "USING_POSTGRES", False))
    odds = bool(BBD.get_odds_api_key())
    if db and odds:
        return "🟢 Connected: model database + live odds"
    missing = [x for x, ok in (("model database (DATABASE_URL)", db), ("live odds (ODDS_API_KEY)", odds)) if not ok]
    return "🔴 Not connected: " + ", ".join(missing) + " — numbers here won't match the learned model"


TODAY_SIDEBAR_SPORTS = ("NBA", "NCAAMB", "NHL", "NFL", "NCAAF")


@st.cache_data(ttl=1800, show_spinner=False)
def _model_record_rows():
    """[(sport, bet-tagged hits, graded, pass hits, graded, trust)] over the last 30 days, from the morning reviews."""
    import pick_records as PR
    import calibration as CAL
    out = []
    for sp in TODAY_SIDEBAR_SPORTS:
        rec = PR.tag_records(sp) or {}
        import props_engine as PE
        bh = sum(h for t, (h, n) in rec.items() if not PE.is_pass(t) and t != PE.USE_WATCH)
        bn = sum(n for t, (h, n) in rec.items() if not PE.is_pass(t) and t != PE.USE_WATCH)
        ph = sum(h for t, (h, n) in rec.items() if PE.is_pass(t))
        pn = sum(n for t, (h, n) in rec.items() if PE.is_pass(t))
        try:
            tr = CAL.trust(sp)
        except Exception:                                       # noqa: BLE001
            tr = None
        if bn or pn:
            out.append((sp, bh, bn, ph, pn, tr))
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def _side_rows():
    """[(sport, "Over text", "Under text")] from each sport's latest morning review (trend "sides", Nov 17)."""
    import model_store as MS
    out = []
    for sp in TODAY_SIDEBAR_SPORTS:
        for m in MS.daily_review_mornings(sp)[:3]:
            sides = ((MS.load_daily_review(sp, m) or {}).get("trend") or {}).get("sides")
            if sides:
                txt = {r["Side"]: (f"{r['Hits'] / r['Graded']:.0%} ({r['Graded']:,})" if r["Graded"] else "—")
                       for r in sides}
                out.append((sp, txt.get("Over", "—"), txt.get("Under", "—")))
                break
    return out


def _today_sidebar() -> None:
    """The model's 30-day record in the sidebar on the Today page."""
    try:
        rows = _model_record_rows()
    except Exception:                                           # noqa: BLE001
        rows = []
    with st.sidebar:
        st.markdown("**📊 Model record · last 30 days**")
        if not rows:
            st.caption("The record appears after the first morning reviews.")
            return
        lines = ["| Sport | Bet picks | No edge |", "|---|---|---|"]
        for sp, bh, bn, ph, pn, tr in rows:
            bet = f"{bh / bn:.0%} ({bn})" if bn else "—"
            pas = f"{ph / pn:.0%}" if pn else "—"
            lines.append(f"| {sp} | {bet} | {pas} |")
        st.markdown("\n".join(lines))
        st.caption("**Bet picks** = every read tagged 🎯 / 🎟️ (hit rate, graded count); **No edge** = the coin flips "
                   "the platform said to skip — near 50% is what it should be. A −110 price needs 52.4%.")
        try:
            sides = _side_rows()
        except Exception:                                       # noqa: BLE001
            sides = []
        if sides:
            st.markdown("**⬆️⬇️ Overs vs Unders · last 30 days**")
            sl = ["| Sport | Over calls | Under calls |", "|---|---|---|"]
            for sp, o, u in sides:
                sl.append(f"| {sp} | {o} | {u} |")
            st.markdown("\n".join(sl))
            st.caption("How often the model's called side was right, every read (graded count). Bet-tagged picks only "
                       "are on Model Record.")
        trusts = [f"{sp} {tr:.2f}" for sp, *_x, tr in rows if tr is not None and tr < 1.0]
        if trusts:
            st.caption("**Trust in the model vs the books** (1.00 = the model as is): " + ", ".join(trusts) +
                       ". Refit every morning; it rises only when the model beats the books on held-out games.")


# Nov 17 (owner: "a site that is considered professional ... fonts like this look quite elementary"): one set of
# type rules for every page. Big st.metric numbers were 2.25rem in the default weight -- they read like a scoreboard,
# not a trading desk. Values are now 1.55rem semibold with tabular figures; labels are small, muted and tracked.
GLOBAL_CSS = """
<style>
html, body, [class*="st-"] { font-feature-settings: "tnum" 1, "cv11" 1; }
[data-testid="stMetricValue"] { font-size: 1.55rem !important; font-weight: 600 !important; line-height: 1.2 !important;
    letter-spacing: -0.01em; font-variant-numeric: tabular-nums; }
[data-testid="stMetricValue"] > div { font-size: inherit !important; }
[data-testid="stMetricLabel"] p, [data-testid="stMetricLabel"] { font-size: 0.74rem !important; font-weight: 500 !important;
    text-transform: uppercase; letter-spacing: 0.05em; color: #9aa4b2 !important; }
[data-testid="stMetricDelta"] { font-size: 0.78rem !important; }
[data-testid="stDataFrame"] { font-variant-numeric: tabular-nums; }
[data-testid="stCaptionContainer"] { color: #9aa4b2; }
h1 { letter-spacing: -0.02em; } h2, h3, h4 { letter-spacing: -0.01em; }
</style>
"""


def run():
    # Real H2 Sports mark as the browser tab icon when the asset is present, the original
    # emoji as an honest fallback otherwise (a stripped-down deploy missing assets/ should never
    # crash page config) -- same fail-soft posture components.hero_banner's own logo uses.
    page_icon = str(_H2_MARK) if _H2_MARK.exists() else "⚾"
    st.set_page_config(page_title="H2 Sports", page_icon=page_icon, layout="wide")
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

    # Sport selector state must be set BEFORE building navigation (it drives which pages show).
    # We read/set session state directly here rather than rendering UI, so the sidebar widget
    # rendered below can pick up the correct current value without a double-render issue.
    import sports as _sports
    try:
        _owner = st.secrets.get("AUDIENCE", "owner") == "owner"
    except Exception:                                           # noqa: BLE001 -- no secrets file: a local/owner run
        _owner = True
    keys = [s.key for s in _sports.selectable_sports(_owner)]     # Nov 5: in-season sports + the labs
    if st.session_state.get("sport") not in keys:
        st.session_state["sport"] = _sports.default_selectable(_owner)
    active_sport = st.session_state["sport"]

    # Sidebar sport picker -- called here so it renders in the sidebar. Streamlit places
    # st.navigation() page links at the top of the sidebar regardless of call order, so the
    # selector ends up below the nav list. This is a known Streamlit constraint with no clean
    # workaround -- the selector is still functional, just positioned at the bottom of the nav
    # links rather than above them. The dropdown itself opens upward when near the bottom of
    # the viewport, which avoids the truncation issue seen when it was buried below "View less".
    # Nov 17 (owner): on the Today entry page the sidebar shows only START HERE and the model's record -- no sport is
    # chosen yet, so "Sport: ..." and the sport-specific pages would contradict the page.
    # (the sidebar's sport line / the Today record are drawn after navigation resolves the page -- see the end of run)

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
    # Nov 16: the commercial (customer) sidebar -- nav_layout.py. A deployment with AUDIENCE = "commercial" gets it;
    # the owner can preview the layout here. The public Discord build is unchanged.
    import nav_layout as NL
    import players_hub as PH
    if audience == "owner":
        st.sidebar.toggle("👀 Preview the commercial layout", key=NL.PREVIEW_KEY,
                          help="Shows what a paying customer would see: a Today front page, four sections, owner tools hidden. "
                               "Layout only: pages still show your own log boxes while you preview.")
    commercial = NL.is_commercial(audience, st.session_state.get(NL.PREVIEW_KEY))
    if commercial and audience == "owner":
        st.sidebar.caption("👀 Previewing the commercial layout")
    # Nov 10: both builds run this same code, so if their numbers differ it's their settings. Everything the model
    # has learned (the record, calibration, tunings, cold markets) lives in the shared database -- a build that isn't
    # connected to it shows unlearned numbers.
    try:
        if audience != "commercial":                            # Nov 16: an internal note, not for a paying customer
            st.sidebar.caption(connection_status())
    except Exception:                                           # noqa: BLE001
        pass

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
        "29": ("NCAAF",),                                # QB Lab (NCAAF) -- adapted directly from
                                                          # NFL QB Lab (page 14), confirmed-matching
                                                          # function signatures and output shapes.
        "30": ("NCAAF",),                                # Matchup Lab (NCAAF) -- adapted directly
                                                          # from NFL Matchup Lab (page 12), on real,
                                                          # individually-tested engine functions.
        "31": ("NCAAF",),                                # Player Lines (NCAAF) -- adapted directly
                                                          # from MLB Player Lines (page 26), the fast
                                                          # browse-by-position trend-chart tool.
        "32": ("NCAAF",),                                # Game Lab (NCAAF) -- first game-level
                                                          # modeling page (moneyline/spread/total/
                                                          # quarter/half), built from schedule data
                                                          # + drives cache.
        "33": ("NFL",),                                  # Player Lines (NFL) -- browse-by-position
                                                          # trend charts, adapted from NCAAF/MLB
                                                          # versions, using nflreadpy column names.
        "34": ("NFL",),                                  # Game Lab (NFL) -- moneyline/spread/total
                                                          # + real injury reports via nflreadpy.
        "35": ("NCAAF",),                                # Hot Hand Engine (NCAAF) -- matchup-
                                                          # adjusted slate-wide leaderboard.
        "36": ("NCAAF",),                                # Anytime TD Engine (NCAAF) -- Bernoulli
                                                          # TD probability board.
        "43": ("TENNIS",),                               # Tennis Lab -- picked as its own sport on Home (Nov 5)
        "44": ("INTL",),                                 # International Hoops -- likewise
        "55": ("SOCCER",),                               # Soccer Lab (Nov 13)
        "45": ("NCAAMB",),                               # Game Lab (college basketball) -- game lines
        "46": ("NBA",),                                  # Game Lab (NBA)
        "47": ("NHL",),                                  # Game Lab (NHL)
        "50": ("NBA", "NCAAMB", "WNBA", "NFL", "NCAAF", "NHL"),
        "54": ("NBA", "NCAAMB", "NHL", "WNBA", "INTL", "TENNIS", "NFL", "NCAAF", "SOCCER"),   # Live Games: in-game reads (Nov 12)
        "53": ("NBA", "NFL", "NHL", "NCAAF"),             # Long Shots: tail + price tests cover these (Nov 14)   # Game Script: each sport's own study (Nov 7)
        "41": ("NFL", "NCAAF", "NBA", "NCAAMB", "NHL", "UFC"),                    # Postgame Review -- kickoff snapshots graded vs box scores
        "38": ("NFL", "NCAAF", "NBA", "NCAAMB", "NHL"),  # Position Matchups -- depth chart vs the opposing
                                                          # defense by position + team head-to-head.
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
                               "Media Room", "Podcast Studio", "Slip Lab", "Analyst Desk"}

    # Internal/paid tools kept off the Discord/public build — matched by TITLE (not page number)
    # so a future re-numbering of the views/ files can't silently un-gate one of these by
    # accident. Matching by title is also what makes gating "Matchup Lab" here correctly cover
    # all three variants (MLB, WNBA/NBA/NCAAMB, NFL) with one entry, since they share the title.
    # Nov 10: Matchup Lab and Position Matchups opened to the Discord/public build (owner's call); their odds
    # lookups stay behind a button, so opening them spends no Odds API credits.
    owner_only_titles = {"Bet Log", "Media Room", "Podcast Studio", "Edge Board",
                         "Track Record", "Data Health",
                         "Suggested Parlays", "Speculative Basket", "Graded Picks",
                         "Model Dashboard", "First Innings Totals", "Player Lines", "Slip Lab",
                         "Postgame Review", "Progression Plan", "Reports", "My Coach", "Model Performance", "Game Script"}
    # Nov 14: Tennis Lab, International Hoops and Long Shots opened to the public build (owner rule: public = owner
    # minus the Bet Log and owner data) -- their log boxes and credit-spending loads stay owner-only

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
        "37": ("Slip Lab", "🧪", "slip_lab"),   # model + pressure-test singles/parlays/pick'em slips
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
        "29": ("QB Lab",         "🏈", "ncaaf_qb_lab"),   # NCAAF version — same title as page 14, distinct url_path
        "30": ("Matchup Lab",    "🔬", "ncaaf_matchup_lab"),   # NCAAF version — same title as page 9/11/12, distinct url_path
        "31": ("Player Lines",   "📉", "ncaaf_player_lines"),   # NCAAF version — same title as page 26, distinct url_path
        "32": ("Game Lab",      "🏟️", "ncaaf_game_lab"),
        "33": ("Player Lines",   "📉", "nfl_player_lines"),   # NFL version — same title, distinct url_path
        "34": ("Game Lab",      "🏟️", "nfl_game_lab"),       # NFL version — same title, distinct url_path
        "35": ("Hot Hand Engine", "🔥", "ncaaf_hot_hand_engine"),   # NCAAF version
        "36": ("Anytime TD Engine", "🎯", "ncaaf_anytime_td_engine"),  # NCAAF version
        "38": ("Position Matchups", "🧭", "position_matchups"),   # depth chart vs opposing defense + H2H
        "39": ("Analyst Desk", "🎙️", "analyst_desk"),   # angles + hidden gems + commentary + graded record
        "40": ("Analyst Record", "🧾", "analyst_record"),   # public, verifiable record of every locked call
        "41": ("Postgame Review", "🩻", "postgame_review"),   # kickoff snapshots graded vs box scores + approvals
        "42": ("Progression Plan", "🧭", "progression_plan"),   # the slow-build business framework, from the Bet Log
        "43": ("Tennis Lab", "🎾", "tennis_lab"),   # ATP/WTA surface Elo vs the books (tracking)
        "44": ("International Hoops", "🌍", "intl_hoops"),   # EuroLeague / NBL ratings vs the books (tracking)
        "55": ("Soccer Lab", "⚽", "soccer_lab"),   # Europe / MLS / Liga MX goals model + sharp line (tracking, Nov 13)
        "45": ("Game Lab", "🏟️", "ncaamb_game_lab"),   # college basketball spreads/totals/ML (tracking)
        "46": ("Game Lab", "🏟️", "nba_game_lab"),      # NBA spreads/totals/ML (ratings vs the books)
        "47": ("Game Lab", "🏟️", "nhl_game_lab"),      # NHL puck lines/totals/ML
        "48": ("Reports", "📑", "reports"),             # P&L statements for any period + CSV / PDF (Nov 6)
        "49": ("Model Performance", "📊", "model_performance"),   # Investor Relations: the edge evidence (Nov 6)
        "50": ("Game Script", "🎬", "game_script"),
        "51": ("My Coach", "🧑‍🏫", "my_coach"),
        "57": ("Today", "🏠", "today"),                  # the customer's front page (commercial layout only, Nov 16)
        "59": ("Promotions", "🎁", "promotions"),       # the books' recurring promotions + the tools that play them (Nov 17)
        "58": ("Players", "👤", "players"),              # every player tool behind one switcher (commercial only, Nov 16)
        "56": ("Model Record", "📊", "model_record"),    # the model's graded record, no Bet Log: the public proof page (Nov 16)
        "54": ("Live Games", "🔴", "live_games"),        # in-game win chance / projected final / fair live lines (Nov 12)
        "53": ("Long Shots", "💎", "long_shots"),        # alternate-line value vs the model's honest chance (Nov 10)          # simple tables from your own bets: what works, what to stop (Nov 8)     # props under each kind of game + script tickets, every props sport (Nov 7)
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
    for k in ("0", "28", "57", "59"):
        SECTION_OF[k] = "🏠 START HERE"
    for k in ("1", "2", "3", "4", "37", "23", "24", "39", "50", "53"):
        SECTION_OF[k] = "🎯 RECOMMENDATIONS"
    for k in ("5", "6", "54"):
        SECTION_OF[k] = "🛰️ LIVE SIGNALS"
    for k in ("7", "8", "9", "10", "11", "12", "13", "14", "15", "25", "26", "27", "29", "30", "31", "32", "33", "34", "35", "36", "43", "44", "45", "46", "47", "55", "58", "38"):
        SECTION_OF[k] = "🔬 DEEP RESEARCH"
    for k in ("16", "17", "18", "19", "40", "41", "42", "48", "51", "56"):
        SECTION_OF[k] = "🔍 SELF-GRADING & PROOF"
    for k in ("20", "21", "22"):
        SECTION_OF[k] = "📣 OPS & CONTENT"
    for k in ("49",):
        SECTION_OF[k] = "💼 INVESTOR RELATIONS"     # Nov 6: material for investors (owner only)

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
    # Nov 17 (owner's design): Today -- every sport at a glance -- is the entry page (first page = the landing page);
    # Home is one sport's desk, opened from Today's sport buttons or the sidebar.
    sections: dict = {"🏠 START HERE": ([] if commercial else [st.Page(str(here / "Today.py"), title="Today", icon="📅",
                                                                        url_path="today")])
                      + [st.Page(str(here / "Home.py"), title="Sport desk" if not commercial else "Home", icon="🏠",
                                 url_path="home")]}
    lab = active_sport in sports.LAB_SPORTS
    for f in view_files:
        key = lead(f.name)
        if lab and key not in (sports.LAB_PAGES[active_sport],) + sports.LAB_COMMON_PAGES + (("56", "57") if commercial else ()):
            continue  # Tennis / Intl Hoops: their own lab page, the Bet Log and the Progression Plan only
        required_sports = sport_only_leads.get(key)
        if required_sports and active_sport not in required_sports:
            continue  # e.g. Dinger Engine makes no sense once WNBA/NBA is selected, and vice versa
        title, icon, slug = meta.get(key, (f.stem, "📄", f"page_{key}"))
        if title in projections_only_titles and not sports.get(active_sport).has_projections:
            continue  # Best Bets / Graded Picks / Edge Board / Retrospective / etc: every one of
                      # these is a guaranteed dead end for an outcome-based sport like UFC -- see
                      # projections_only_titles' own comment above for the real, reported gap this closes
        if title in owner_only_titles and (audience != "owner" or commercial):
            continue  # Bet Log / Media Room / Podcast Studio / Edge Board / Matchup Lab / Track Record: owner deployment only
        if title in NL.COMMERCIAL_ONLY and not commercial:
            continue  # Today / Players are the customer's pages; the owner and Discord sidebars keep their own
        if key == "58" and active_sport not in PH.SPORTS:
            continue  # Players: only sports that have player views
        if title == "Model Record" and audience == "public":
            continue  # Nov 16: the Discord build stays exactly as it was until the owner switches it over
        if commercial and NL.commercial_section(title) is None:
            continue  # not part of the customer product (Command Center, Retrospective ...)
        section = NL.commercial_section(title) if commercial else SECTION_OF.get(key, "🔬 DEEP RESEARCH")   # a real, sensible default for any
        # future page whose number isn't added to SECTION_OF yet -- never silently disappears,
        # never crashes, just lands somewhere reasonable until explicitly categorized.
        sections.setdefault(section, []).append(st.Page(str(f), title=NL.label(title) if commercial else title,
                                                        icon=icon, url_path=slug))

    # Bold/colored sidebar section-header styling was attempted here and confirmed (via a real
    # screenshot, pixel-sampled) to be inert against this Streamlit version's actual DOM -- see
    # the "CSS risk" section of the project handoff. Removed rather than left as dead code.
    # UPPERCASE section names remain the confirmed, real, working lever for visual separation.
    if commercial:
        sections = NL.arrange(sections)      # customer order; Today replaces Home
        sports.render_sport_selector()
        st.navigation(sections).run()
        return
    # Nov 17 (owner): on the Today entry page no sport is chosen yet, so the sidebar shows only START HERE and the
    # model's 30-day record -- not "Sport: ..." and the sport's pages, which would contradict the page. The page the
    # browser asked for is resolved first (hidden menu), then the menu is drawn for it.
    target = st.navigation(sections, position="hidden")
    if getattr(target, "title", None) == "Today":                # the default page reports an empty url_path
        _today_sidebar()
        st.navigation({"🏠 START HERE": sections.get("🏠 START HERE", [])}).run()
        return
    sports.render_sport_selector()
    nav = st.navigation(sections)
    # Nov 17: a page that changed the sport and wants another sport's page (Promotions -> King of the Court) parks its
    # target here; it can only be switched to once the menu is built for the new sport.
    goto = st.session_state.pop("_goto_page", None)
    if goto:
        for pages in sections.values():
            for pg in pages:
                if getattr(pg, "url_path", None) == goto:
                    st.switch_page(pg)
    nav.run()


if __name__ == "__main__":
    run()
