"""
analyst_context.py — the evidence the Analyst Desk reads from OUTSIDE the player's own recent games.

WHY THIS EXISTS: the model's percentage, a form run and a role surge are all read from the same few
recent games, so two of them agreeing is not independent confirmation (the Desk's families say so).
This module supplies two kinds of evidence that come from somewhere else:

  * GAME ENVIRONMENT — the point spread and the game total (analyst.detect_game_script reads them).
  * OPPONENT DEFENSE — how much the opponent has allowed at this stat compared with the typical
    opponent on the slate (analyst.detect_matchup reads it). The number comes from the platform's own
    Hot Hand Engine boards, so it is the same matchup factor the owner already sees there; the Best
    Bets probability does NOT include it ("Best Bets stay recent-form-only"), which is what makes it
    separate evidence.

The first half is pure (plain dicts in, plain dicts out, unit tested). The two loaders at the bottom
do the network/engine work, are injected with the engine and projections modules, and fail soft: a
missing source returns ({}, plain-language note) and the Desk simply has fewer angles that day.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

import analyst as A

# Slate-relative total ranking needs at least this many games with a posted total to mean anything.
TOTAL_MIN_GAMES = 4

# nflreadpy / the NFL engine name teams by abbreviation; the Odds API uses full names. The mascot is the
# unambiguous part of the full name ("Eagles" is in "Philadelphia Eagles"; "LA" alone is not enough).
NFL_MASCOTS: Dict[str, str] = {
    "ARI": "cardinals", "ATL": "falcons", "BAL": "ravens", "BUF": "bills", "CAR": "panthers", "CHI": "bears",
    "CIN": "bengals", "CLE": "browns", "DAL": "cowboys", "DEN": "broncos", "DET": "lions", "GB": "packers",
    "HOU": "texans", "IND": "colts", "JAX": "jaguars", "JAC": "jaguars", "KC": "chiefs", "LV": "raiders",
    "LAC": "chargers", "LAR": "rams", "LA": "rams", "MIA": "dolphins", "MIN": "vikings", "NE": "patriots",
    "NO": "saints", "NYG": "giants", "NYJ": "jets", "PHI": "eagles", "PIT": "steelers", "SF": "49ers",
    "SEA": "seahawks", "TB": "buccaneers", "TEN": "titans", "WAS": "commanders", "WSH": "commanders",
}


# ---------------------------------------------------------------------------
# Game environment (pure)
# ---------------------------------------------------------------------------
def names_match(sport_key: str, slate_name: Optional[str], odds_name: Optional[str]) -> bool:
    """Is the slate's team name (an abbreviation for the NFL, a school/club name elsewhere) the Odds
    API's team?"""
    if sport_key == "NFL":
        mascot = NFL_MASCOTS.get(str(slate_name or "").strip().upper())
        return bool(mascot and mascot in A._norm(odds_name))
    return A._team_match(slate_name, odds_name)


def _spread_for(sport_key: str, team: Optional[str], spreads: Dict[str, float]) -> Optional[float]:
    for name, pts in (spreads or {}).items():
        if names_match(sport_key, team, name):
            return float(pts)
    return None


def build_game_env(meta: Iterable[Dict], events: Optional[List[Dict]], sport_key: str) -> Dict[str, Dict]:
    """{game label: {home_name, away_name, home_spread, away_spread, total, total_pct}} for every game on
    the slate that the odds feed also has. Spreads are the Odds API's own convention (negative =
    favorite). `total_pct` is the share of the slate's games whose total is at or below this one's
    (1.0 = the highest total of the day), and is None when fewer than TOTAL_MIN_GAMES totals exist, so a
    two-game slate never calls a total 'high'."""
    env: Dict[str, Dict] = {}
    for m in meta or []:
        label, home, away = m.get("label"), m.get("home_name"), m.get("away_name")
        if not (label and home and away):
            continue
        ev = next((e for e in events or []
                   if names_match(sport_key, home, e.get("home_team")) and names_match(sport_key, away, e.get("away_team"))),
                  None)
        if ev is None:
            continue
        hs = _spread_for(sport_key, home, ev.get("spreads") or {})
        as_ = _spread_for(sport_key, away, ev.get("spreads") or {})
        if hs is None and as_ is not None:
            hs = -as_
        if as_ is None and hs is not None:
            as_ = -hs
        env[label] = {"home_name": home, "away_name": away, "home_spread": hs, "away_spread": as_,
                      "total": ev.get("total"), "total_pct": None}
    totals = [e["total"] for e in env.values() if e["total"] is not None]
    if len(totals) >= TOTAL_MIN_GAMES:
        for e in env.values():
            if e["total"] is not None:
                e["total_pct"] = sum(1 for t in totals if t <= e["total"]) / len(totals)
    return env


# ---------------------------------------------------------------------------
# Opponent defense (pure)
# ---------------------------------------------------------------------------
def matchup_index(board_rows: Iterable[Dict]) -> Dict[Tuple[str, str], Dict]:
    """{(normalized player, market display name): {factor, opp, allows}} from a Hot Hand Engine board
    (each row carries 'Matchup Factor', 'Opp' and, usually, 'Opp Allows'). A neutral 1.00 that came from
    missing data is kept as-is: it is below every threshold, so it never fires."""
    out: Dict[Tuple[str, str], Dict] = {}
    for r in board_rows or []:
        f = r.get("Matchup Factor")
        if f is None or not r.get("Player") or not r.get("Market"):
            continue
        out[(A._norm(r["Player"]), r["Market"])] = {"factor": float(f), "opp": r.get("Opp"), "allows": r.get("Opp Allows")}
    return out


# ---------------------------------------------------------------------------
# Loaders (network / engine; injected, fail-soft)
# ---------------------------------------------------------------------------
BASKETBALL = ("NBA", "WNBA", "NCAAMB")


def load_matchups(sport_key: str, date_str: str, engine, projections) -> Tuple[Dict[Tuple[str, str], Dict], str]:
    """Opponent-matchup index for the slate, built with the platform's own Hot Hand Engine boards.
    Returns (index, note); on any failure (index {}, a plain-language reason)."""
    try:
        if sport_key in BASKETBALL:
            rows, _meta = engine.build_slate(date_str)
            opp_ids = sorted({r["_opp_id"] for r in rows if r.get("_opp_id") is not None})
            allowed = {oid: engine.get_team_recent_allowed_stats(oid, date_str) for oid in opp_ids}
            board = projections.build_hot_hand_board(rows, allowed)
        elif sport_key in ("NFL", "NCAAF"):
            rows, _meta = engine.build_slate(date_str)
            opps = sorted({r["Opp"] for r in rows if r.get("Opp")})
            if sport_key == "NFL":
                allowed = {o: engine.get_team_allowed_stats(o, date_str) for o in opps}
                board = projections.build_hot_hand_board(rows, allowed)
            else:
                allowed = {o: engine.get_team_allowed_stats(o, date_str, n=None) for o in opps}
                board = projections.build_ncaaf_hot_hand_board(rows, allowed)
        else:
            return {}, f"there is no opponent-matchup board for {sport_key}"
    except Exception as exc:                                    # noqa: BLE001 — context, never a reason to break the page
        return {}, f"the opponent-matchup data couldn't be loaded ({str(exc)[:80]})"
    idx = matchup_index(board)
    if not idx:
        return {}, "no opponent-matchup data is available for this slate yet"
    return idx, ""


def load_game_env(sport_key: str, date_str: str, meta: Iterable[Dict], api_key: Optional[str],
                  odds_sport_key: str, fetch=None) -> Tuple[Dict[str, Dict], str]:
    """Game-environment dict for the slate (spreads and totals from the odds feed). `fetch` is injectable
    for tests; it defaults to odds_api.fetch_slate_game_lines. Returns (env, note)."""
    if not api_key:
        return {}, "no Odds API key is configured, so the game-script angle is off"
    try:
        if fetch is None:
            import odds_api
            fetch = odds_api.fetch_slate_game_lines
        events, _info = fetch(date_str, api_key, sport=odds_sport_key)
    except Exception as exc:                                    # noqa: BLE001
        return {}, f"the game-lines fetch failed ({str(exc)[:80]}), so the game-script angle is off"
    env = build_game_env(meta, events, sport_key)
    if not env:
        return {}, "no game spreads or totals are posted yet, so the game-script angle is quiet"
    return env, ""
