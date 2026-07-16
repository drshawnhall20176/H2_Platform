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
]
_MLB_MARKET_MAP = {
    "Batter HR": "batter_home_runs", "Batter Total Bases": "batter_total_bases",
    "Batter Total Hits": "batter_hits", "Batter Strikeouts": "batter_strikeouts",
    "Pitcher Strikeouts": "pitcher_strikeouts", "Pitcher Outs": "pitcher_outs",
    "Pitcher Walks": "pitcher_walks",
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
        markets=[], market_map={},              # filled in when NFL wiring is finished
        engine_module="nfl_engine", projections_module="nfl_projections",
        config_module="config_nfl",
        enabled=False,                          # engine present; not yet live end-to-end
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
    "NCAAMB": Sport("NCAAMB","NCAA Men's Basketball",   "🏀", "basketball_ncaab",     [], {}, enabled=False),
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
