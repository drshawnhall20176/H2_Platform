"""
sports.py — the sport registry: the heart of the H2 Sports multi-sport platform.

ONE place that describes every league. Each sport declares its data engine, projections module,
config, the Odds API sport key, its markets, and the market-map used to capture closing lines. The
shared proof/content pages (Edge Board, Bet Log, Track Record, Media Room, Podcast, Retrospective)
never import a specific sport — they ask this registry for the *active* sport and route through it.

Adding a league later = add ONE entry here (plus its engine/projections modules). Nothing in the
shared layer changes. That's the leverage that makes a seven-league platform maintainable.

The active sport is held in st.session_state["sport"] and chosen by the sidebar selector
(render_sport_selector). Sport-specific analysis pages (e.g. MLB's Dinger Engine) check the active
sport and politely no-op when a different sport is selected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class Sport:
    """Everything the shared layer needs to run one league."""
    key: str                       # short id, e.g. "MLB"
    label: str                     # display name, e.g. "MLB — Baseball"
    icon: str                      # emoji for the selector
    odds_sport_key: str            # The Odds API sport key, e.g. "baseball_mlb"
    markets: List[str]             # Odds API market keys this sport prices
    market_map: Dict[str, str]     # Bet Log display market -> Odds API key (for CLV capture)
    single_line_markets: set = field(default_factory=set)  # markets matched w/o a point (e.g. HR)
    engine_module: str = ""        # import path of the sport's data engine
    projections_module: str = ""   # import path of the sport's projections
    config_module: str = ""        # import path of the sport's config
    enabled: bool = True           # False = defined but not yet live (shown greyed / hidden)

    # lazily-imported modules (populated by .engine / .projections)
    _engine: object = None
    _projections: object = None

    @property
    def engine(self):
        if self._engine is None and self.engine_module:
            self._engine = __import__(self.engine_module)
        return self._engine

    @property
    def projections(self):
        if self._projections is None and self.projections_module:
            self._projections = __import__(self.projections_module)
        return self._projections


# --------------------------------------------------------------------------- registry
# MLB — fully built. NFL — engine present, wiring in progress. The other five are placeholders
# (enabled=False) so the vision is visible in the selector and each becomes live when its engine
# lands. Adding a real sport = fill in the modules/markets and flip enabled=True.
_MLB_MARKETS = [
    "batter_home_runs", "batter_total_bases", "batter_hits", "batter_strikeouts",
    "pitcher_strikeouts", "pitcher_outs", "pitcher_walks",
    "batter_runs_scored", "batter_rbis", "batter_stolen_bases", "pitcher_earned_runs",
]
_MLB_MARKET_MAP = {
    "Batter HR": "batter_home_runs", "Batter Total Bases": "batter_total_bases",
    "Batter Total Hits": "batter_hits", "Batter Strikeouts": "batter_strikeouts",
    "Pitcher Strikeouts": "pitcher_strikeouts", "Pitcher Outs": "pitcher_outs",
    "Pitcher Walks": "pitcher_walks",
    # Market keys confirmed directly against the-odds-api.com's own live "Betting Markets"
    # documentation (the exact provider odds_api.py integrates with) -- not guessed or inferred
    # from naming convention alone.
    "Batter Runs": "batter_runs_scored", "Batter RBIs": "batter_rbis",
    "Batter Stolen Bases": "batter_stolen_bases", "Pitcher Earned Runs": "pitcher_earned_runs",
}

REGISTRY: Dict[str, Sport] = {
    "MLB": Sport(
        key="MLB", label="MLB — Baseball", icon="⚾", odds_sport_key="baseball_mlb",
        markets=_MLB_MARKETS, market_map=_MLB_MARKET_MAP,
        single_line_markets={"batter_home_runs"},
        engine_module="mlb_engine", projections_module="projections", config_module="config",
        enabled=True,
    ),
    "NFL": Sport(
        key="NFL", label="NFL — Football", icon="🏈", odds_sport_key="americanfootball_nfl",
        markets=["player_pass_yds", "player_rush_yds", "player_receptions", "player_reception_yds"],
        market_map={"Pass Yards": "player_pass_yds", "Rush Yards": "player_rush_yds",
                    "Receptions": "player_receptions", "Receiving Yards": "player_reception_yds"},
        engine_module="nfl_engine", projections_module="nfl_projections",
        config_module="config_nfl",
        enabled=True,    # LIVE as of 2026-07-17. Engine rebuilt from scratch this session — the
                        # ORIGINAL draft's SUPPORTED_MARKETS were entirely fabricated market keys
                        # ("quarterback_passing_yards" etc.) that don't exist in Odds API's real
                        # taxonomy at all; Edge Board would have silently fetched zero real NFL
                        # odds. The real, confirmed keys above (player_pass_yds/player_rush_yds/
                        # player_receptions/player_reception_yds) come directly from Odds API's
                        # own documentation. Also rebuilt: the data source itself — the original
                        # draft depended on nfl_data_py, confirmed during this build to be
                        # DEPRECATED and archived by its own maintainers (Sep 2025) in favor of
                        # nflreadpy, which this engine now uses instead. The full pipeline
                        # (schedule -> weekly stats -> position-aware slate -> bootstrap
                        # projections -> Edge Board/Best Bets shape) was verified end to end
                        # against REAL, LIVE 2025-season data during this build — not just
                        # documentation — producing real, sensible results (513 real projected
                        # offers from 270 real players on a real Week 6 slate), plus a real review
                        # pass (team abbreviations confirmed matching across schedule/roster data,
                        # playoff weeks confirmed non-colliding with the regular season, the real
                        # Super Bowl week slate confirmed working end to end). Flipped live after
                        # that review — the only thing not checkable from this sandbox is
                        # nflreadpy's real network behavior once actually deployed on Streamlit
                        # Cloud, worth a first look once it's up.
                        # NOT yet built: a Hot Hand Engine-equivalent or Matchup Lab-equivalent
                        # (see nfl_projections.py's own staged-scope note) — this covers what
                        # Edge Board and Best Bets need, deliberately, not the full page set yet.
    ),
    # ---- vision placeholders (become live as each engine is built) ----
    "WNBA":   Sport(
        key="WNBA", label="WNBA — Basketball", icon="🏀", odds_sport_key="basketball_wnba",
        markets=["player_points", "player_rebounds", "player_assists", "player_threes"],
        market_map={"Points": "player_points", "Rebounds": "player_rebounds",
                    "Assists": "player_assists", "Threes Made": "player_threes"},
        engine_module="wnba_engine", projections_module="wnba_projections",
        config_module="config_wnba",
        enabled=True,   # live as of Stage 2's WNBA build — Core 4 markets (Pts/Reb/Ast/3PM)
    ),
    "NBA":    Sport(
        key="NBA", label="NBA — Basketball", icon="🏀", odds_sport_key="basketball_nba",
        markets=["player_points", "player_rebounds", "player_assists", "player_threes"],
        market_map={"Points": "player_points", "Rebounds": "player_rebounds",
                    "Assists": "player_assists", "Threes Made": "player_threes"},
        engine_module="nba_engine", projections_module="nba_projections",
        config_module="config_nba",
        enabled=True,   # live as of 2026-07-15 — built as a copy-adapt of the WNBA engine (see
                        # basketball_engine.py's module docstring for the extraction plan), then
                        # confirmed against a real live game (Nets @ Clippers, Jan 25 2026,
                        # gameId 401810511): both get_game_team_totals and get_game_boxscore
                        # verified correct against the actual CDN response, the same bar WNBA's
                        # build cleared before its own launch (see PLATFORM_CHECKPOINT.md for the
                        # full verification writeup, including a real "points" field bug caught
                        # and fixed along the way). Hot Hand Engine/Matchup Lab's require_sport
                        # gates updated to accept NBA too. Not yet independently re-verified:
                        # get_team_roster's exact live shape (same pattern already proven for
                        # WNBA, low risk); SEASON_START is a placeholder pending the 2026-27
                        # schedule announcement — re-check both once real slate data is flowing.
    ),
    "NHL":    Sport("NHL",   "NHL — Hockey",            "🏒", "icehockey_nhl",        [], {}, enabled=False),
    "NCAAF":  Sport("NCAAF", "NCAA Football",           "🏈", "americanfootball_ncaaf", [], {}, enabled=False),
    "NCAAMB": Sport(
        key="NCAAMB", label="NCAA Men's Basketball", icon="🏀", odds_sport_key="basketball_ncaab",
        markets=["player_points", "player_rebounds", "player_assists", "player_threes"],
        market_map={"Points": "player_points", "Rebounds": "player_rebounds",
                    "Assists": "player_assists", "Threes Made": "player_threes"},
        engine_module="ncaamb_engine", projections_module="ncaamb_projections",
        config_module="config_ncaamb",
        enabled=True,    # LIVE as of 2026-07-16, flipped after Shawn's own live verification —
                        # engine built as a copy-adapt of the live NBA engine (see
                        # basketball_engine.py's module docstring for the extraction plan).
                        # CDN boxscore endpoint CONFIRMED LIVE 2026-07-16, both team- and
                        # player-level — Shawn fetched the actual raw JSON directly (a real NCAA
                        # Tournament Elite Eight game, UConn 73, Duke 72, Mar 29 2026, gameId
                        # 401856577) and pasted the literal response back, the same bar WNBA's and
                        # NBA's builds cleared before their own launches. Verified end to end with
                        # ZERO code changes needed — see ncaamb_engine.py's module docstring for
                        # the full story. The one piece NOT independently confirmed: get_team_
                        # injuries for mens-college-basketball specifically (only NBA's version was
                        # checked) — fails soft (empty list) if wrong, not a launch blocker the way
                        # the CDN boxscore was. Genuinely CONFIRMED, not guessed, during this
                        # build: the 2026-27 season starts Nov 1 2026 (NCAA's own published
                        # calendar); Odds API's basketball_ncaab sport key with real
                        # player_points/player_rebounds props already live; and a real, load-
                        # bearing quirk — the scoreboard endpoint silently truncates Division I's
                        # 350+ teams unless groups=50 is included, confirmed live 2026-07-04 (12
                        # events without it vs. 36 with it, same date) — already baked into
                        # ncaamb_engine.py's get_schedule and get_team_recent_game_ids.
    ),
}

DEFAULT_SPORT = "MLB"


# --------------------------------------------------------------------------- accessors
def get(sport_key: str) -> Sport:
    return REGISTRY.get(sport_key, REGISTRY[DEFAULT_SPORT])


def enabled_sports() -> List[Sport]:
    return [s for s in REGISTRY.values() if s.enabled]


def active_key() -> str:
    """The currently-selected sport key from session state (defaults to MLB)."""
    try:
        import streamlit as st
        return st.session_state.get("sport", DEFAULT_SPORT)
    except Exception:
        return DEFAULT_SPORT


def active() -> Sport:
    return get(active_key())


def require_sport(required_keys, feature_name: str = "This page") -> bool:
    """Stricter than require_live_engine. Use this for pages whose LOGIC (specific columns,
    market assumptions, display contract) has only been validated against certain sports' shapes
    — even if the page itself already dispatches cleanly through sports.active().engine/
    .projections. require_live_engine alone is NOT enough here — it only checks that the ACTIVE
    sport has markets configured, which used to imply "and therefore it's MLB" back when MLB was
    the only sport with markets. That stopped being true the moment a second sport (WNBA) got
    real markets: a require_live_engine-only guard would let a WNBA-selecting user land on a page
    that silently runs MLB's engine and mislabels the output as WNBA — worse than just not being
    available.

    required_keys: a single sport key (str, e.g. "WNBA") or an iterable of keys (list/tuple/set,
    e.g. ["WNBA", "NBA"]) — any one of which is acceptable for this page. A single string is
    still accepted directly (not wrapped in a list by the caller) for backward compatibility with
    existing single-sport call sites. Returns False (caller should st.stop()) when the active
    sport isn't one of the supported ones."""
    import streamlit as st
    keys = [required_keys] if isinstance(required_keys, str) else list(required_keys)
    s = active()
    if s.key not in keys:
        labels = " or ".join(f"{get(k).icon} {get(k).label}" for k in keys)
        st.info(
            f"🚧 {feature_name} is only wired for {labels} so far. "
            f"Pick one of those from the sidebar — support for {s.label} here is "
            f"planned but not yet built for this specific page."
        )
        return False
    return True


def require_live_engine(feature_name: str = "This page") -> bool:
    """Call at the top of a page that pulls real slate data from an engine (Edge Board, Media
    Room, Podcast Studio, Retrospective, Best Bets, Command Center). Returns True when the active
    sport has markets configured (i.e. its engine is actually wired end-to-end, not just a
    placeholder registry entry). When False, shows a friendly notice — the caller should st.stop()
    right after. This is what lets these pages be sport-routed today and "just work" the moment a
    future stage fills in a sport's markets/market_map, with no further page changes needed."""
    import streamlit as st
    s = active()
    if not s.markets:
        st.info(
            f"🚧 {feature_name} isn't wired up for {s.icon} {s.label} yet. "
            f"Pick {REGISTRY[DEFAULT_SPORT].icon} {REGISTRY[DEFAULT_SPORT].label} from the sidebar "
            f"— {s.label} is on the roadmap (see PLATFORM_CHECKPOINT.md)."
        )
        return False
    return True


def render_sport_selector():
    """Sidebar sport picker, shared by every page. Sets st.session_state['sport']. Only enabled
    sports are selectable; the rest are listed as 'coming soon' so the full vision is visible."""
    import streamlit as st
    live = enabled_sports()
    keys = [s.key for s in live]
    current = st.session_state.get("sport", DEFAULT_SPORT)
    if current not in keys:
        current = keys[0]
    with st.sidebar:
        choice = st.selectbox(
            "🏟️ Sport", keys, index=keys.index(current),
            format_func=lambda k: f"{REGISTRY[k].icon} {REGISTRY[k].label}",
            key="sport")
        coming = [s for s in REGISTRY.values() if not s.enabled]
        if coming:
            st.caption("Coming soon: " + " · ".join(f"{s.icon} {s.key}" for s in coming))
    return choice


# ================================================================================================
# TIME-SLOT HELPERS — shared by every page that needs to bucket/filter games by tip-off time.
#
# Originally lived only in Best Bets (its own private game_dt/slot_of/SLOT_ORDER). Extracted here
# once Matchup Lab needed the identical logic for a real reason: with WNBA's small nightly slate,
# scrolling a player picker was fine, but a full NBA slate (and especially a much bigger NCAAMB
# one, still to come) makes "just scroll to find your player" genuinely painful — a time-slot
# filter narrows the picker to a manageable set first. Rather than copy Best Bets' three functions
# a second time (a third, when Hot Hand Engine likely wants this too for the same reason), this is
# the one shared home — matching the same "extract once a second real consumer exists, not before"
# philosophy basketball_engine.py's own extraction already follows.
# ================================================================================================
import pytz as _pytz
from datetime import datetime as _datetime

_EASTERN = _pytz.timezone("US/Eastern")

SLOT_ORDER: Dict[str, int] = {"Afternoon": 0, "Evening": 1, "Late": 2, "TBD": 3}


def game_dt(iso_utc: Optional[str]):
    """Parse an ISO-8601 UTC game-date string (as already stored in every sport's build_slate row/
    meta `game_date`/`_game_date` fields) into US/Eastern local time. Returns None for missing or
    malformed input — callers treat that as a real "we don't know the time" case (bucketed as
    "TBD" by slot_of below), not something to silently paper over with a guessed time."""
    if not iso_utc:
        return None
    try:
        return _datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(_EASTERN)
    except (ValueError, TypeError):
        return None


def slot_of(dt) -> str:
    """Bucket a US/Eastern game datetime into a coarse time-slot label: Afternoon (<5pm ET),
    Evening (5-8pm ET), Late (8pm ET+), or TBD (no known time). Fixed hour boundaries, not
    sport-specific — the same buckets read naturally whether it's an MLB afternoon getaway game
    or a WNBA/NBA evening tip-off, and the boundaries are coarse enough not to need per-sport
    tuning."""
    if dt is None:
        return "TBD"
    h = dt.hour
    if h < 17:
        return "Afternoon"
    if h < 20:
        return "Evening"
    return "Late"


def _check_trading_password(entered: str, expected) -> bool:
    """Pure, testable comparison — the actual widget/session-state handling lives in
    require_trading_access below, which needs a real Streamlit context this doesn't.

    FAILS CLOSED, NOT OPEN, ON A MISSING SECRET: if TRADING_PASSWORD isn't configured at all
    (expected is falsy), this returns False regardless of what's entered — an unconfigured
    secret should never silently grant access. Same "refuse rather than fabricate a pass"
    discipline already used throughout this platform's own data-quality checks (e.g.
    data_freshness.py refusing to report "green" for a file that doesn't exist)."""
    if not expected:
        return False
    return entered == str(expected)


def require_trading_access(page_name: str = "This page") -> bool:
    """A second, narrower gate specifically for Bet Log and Track Record — a person's own real
    trading/betting history, separate from the existing owner/public audience split (which
    governs the WHOLE deployment, not one page). Someone with owner access sees Best Bets,
    Graded Picks, Matchup Lab, everything — but Bet Log/Track Record additionally ask for a
    second, narrower password before showing anything.

    A REAL, DELIBERATE FIRST STEP TOWARD FUTURE MULTI-USER LOGIN, NOT A FULL LOGIN SYSTEM ITSELF:
    this is one shared password, not per-person identity — there's no concept of "which person"
    entered it. betlog.py's own new "trader" column is the other half of this same forward-
    looking step: the DATA MODEL can already record whose bet something is, even though nothing
    yet asks a real per-person login question to populate it correctly. Building a full
    multi-user auth system now would be scope creep beyond what was actually asked for; this
    closes the real, current gap (Bet Log/Track Record visible to anyone with owner access, full
    stop) without pretending to solve a broader problem that hasn't been scoped yet.

    Reuses st.session_state so a correct password only needs to be entered once per browser
    session, not re-typed on every page navigation within it. Returns True once unlocked (caller
    proceeds normally); returns False and renders the password prompt itself (caller should
    st.stop() right after, matching require_live_engine/require_sport's own return contract)."""
    import streamlit as st
    if st.session_state.get("trading_unlocked"):
        return True
    st.warning(f"🔒 {page_name} needs a separate password — this is real trading history, kept "
              f"apart from the rest of the owner build.")
    entered = st.text_input("Password", type="password", key="trading_password_input")
    if entered:
        if _check_trading_password(entered, st.secrets.get("TRADING_PASSWORD")):
            st.session_state["trading_unlocked"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False
