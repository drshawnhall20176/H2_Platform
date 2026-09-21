"""
book_menu.py — the FULL menu of what one sportsbook offers for a game: game lines, alternate lines,
team totals, period markets, and every player prop the book lists (main, alternate and special),
turned into the same "leg" dicts Slip Lab already prices. Pure logic — no Streamlit; the network
call takes an injectable `get` so it is tested without the internet.

WHY A SEPARATE, EXPLICIT FETCH. Slip Lab's normal leg pool covers only the props the model prices
(that is what gets a model probability and an edge). Everything else a book posts — a spread, a
team total, a 75+ receiving-yards ladder — costs one Odds API credit per market per game, and a
full NFL menu is dozens of markets. So the menu is a button the user presses after seeing the
credit estimate, restricted to ONE book (a single bookmaker keeps the response small and the
no-vig maths clean), and each (game, market) is its own request: a market key the API does not
know for that sport returns a 4xx for that one request and is reported as "not offered", instead
of failing the whole fetch.

WHERE A LEG'S PROBABILITY COMES FROM. A menu leg has no model of its own unless one is matched:
  * a player prop the board's model already prices (same player, market, side and line) takes the
    model's probability and evidence — it becomes a "model" leg, eligible for suggestions;
  * anything else takes the book's own NO-VIG probability when the book posted both sides (a two-way
    or three-way group is de-vigged proportionally), or the plain implied probability when it
    posted only one side (that number still contains the book's margin — flagged as such);
  * the user can overwrite either with their own number, which makes it a "yours" leg.
A market-derived leg has no edge by construction: its probability is the book's own, so its EV is
minus the book's margin (a de-vigged two-way leg) or exactly zero (a one-sided leg, whose implied
probability is the price itself) — never a real advantage. The suggester therefore never builds
tickets from them; they exist so a slip can hold whatever the user wants
to test, with correlation and stress-testing still applied.

VERIFICATION NOTE. The market keys below follow The Odds API's documented taxonomy, but the
sandbox this was built in cannot reach the API, so the exact key set per sport is unverified
against a live response. The per-market isolation above is the safety net: a wrong key shows up as
"not offered" in the fetch report rather than an error.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import odds_api as O
import slip_lab as SL

MENU_N_EFF = 40.0    # "games of evidence" credited to a market-derived probability (it is a liquid price)

# --------------------------------------------------------------------------- market catalog
_PERIOD_TITLES = {"_h1": "1H", "_h2": "2H", "_q1": "1Q", "_q2": "2Q", "_q3": "3Q", "_q4": "4Q",
                  "_p1": "P1", "_p2": "P2", "_p3": "P3",
                  "_1st_1_innings": "1st inning", "_1st_3_innings": "First 3", "_1st_5_innings": "First 5",
                  "_1st_7_innings": "First 7"}
_GAME_BASE = {"h2h": "Moneyline", "spreads": "Spread", "totals": "Game Total", "team_totals": "Team Total",
              "alternate_spreads": "Spread", "alternate_totals": "Game Total",
              "alternate_team_totals": "Team Total", "h2h_3_way": "Moneyline (3-way)",
              "draw_no_bet": "Draw No Bet"}

_FOOTBALL = {
    "Game lines": ["h2h", "spreads", "totals"],
    "Alternate lines": ["alternate_spreads", "alternate_totals"],
    "Team totals": ["team_totals", "alternate_team_totals"],
    "First half": ["h2h_h1", "spreads_h1", "totals_h1"],
    "First quarter": ["h2h_q1", "spreads_q1", "totals_q1"],
}
_BASKETBALL = {
    "Game lines": ["h2h", "spreads", "totals"],
    "Alternate lines": ["alternate_spreads", "alternate_totals"],
    "Team totals": ["team_totals", "alternate_team_totals"],
    "First half": ["h2h_h1", "spreads_h1", "totals_h1"],
    "First quarter": ["h2h_q1", "spreads_q1", "totals_q1"],
}
_HOCKEY = {
    "Game lines": ["h2h", "spreads", "totals"],
    "Alternate lines": ["alternate_spreads", "alternate_totals"],
    "Team totals": ["team_totals", "alternate_team_totals"],
    "First period": ["h2h_p1", "spreads_p1", "totals_p1"],
}
_BASEBALL = {
    "Game lines": ["h2h", "spreads", "totals"],
    "Alternate lines": ["alternate_spreads", "alternate_totals"],
    "Team totals": ["team_totals", "alternate_team_totals"],
    "First 5 innings": ["h2h_1st_5_innings", "spreads_1st_5_innings", "totals_1st_5_innings"],
    "First inning": ["h2h_1st_1_innings", "totals_1st_1_innings"],
}

_FOOTBALL_PLAYER_EXTRA = [
    "player_pass_tds", "player_pass_completions", "player_pass_attempts", "player_pass_interceptions",
    "player_pass_longest_completion", "player_rush_attempts", "player_rush_longest",
    "player_reception_longest", "player_rush_reception_yds", "player_kicking_points",
    "player_field_goals", "player_tackles_assists", "player_sacks"]
_FOOTBALL_ALT = ["player_pass_yds_alternate", "player_pass_tds_alternate", "player_rush_yds_alternate",
                 "player_receptions_alternate", "player_reception_yds_alternate",
                 "player_rush_reception_yds_alternate"]
_FOOTBALL_SPECIAL = ["player_anytime_td", "player_1st_td", "player_last_td", "player_tds_over"]

_BASKETBALL_PLAYER_EXTRA = [
    "player_points", "player_rebounds", "player_assists", "player_threes", "player_blocks",
    "player_steals", "player_turnovers", "player_blocks_steals", "player_points_rebounds_assists",
    "player_points_rebounds", "player_points_assists", "player_rebounds_assists"]
_BASKETBALL_ALT = ["player_points_alternate", "player_rebounds_alternate", "player_assists_alternate",
                   "player_threes_alternate", "player_blocks_alternate", "player_steals_alternate",
                   "player_points_assists_alternate", "player_points_rebounds_alternate",
                   "player_rebounds_assists_alternate", "player_points_rebounds_assists_alternate"]
_BASKETBALL_SPECIAL = ["player_double_double", "player_triple_double", "player_first_basket"]

_HOCKEY_PLAYER_EXTRA = ["player_points", "player_assists", "player_goals", "player_shots_on_goal",
                        "player_total_saves", "player_power_play_points", "player_blocked_shots"]
_HOCKEY_ALT = ["player_points_alternate", "player_assists_alternate", "player_goals_alternate",
               "player_shots_on_goal_alternate", "player_total_saves_alternate"]
_HOCKEY_SPECIAL = ["player_goal_scorer_anytime", "player_goal_scorer_first", "player_goal_scorer_last"]

_BASEBALL_PLAYER_EXTRA = [
    "batter_home_runs", "batter_hits", "batter_total_bases", "batter_rbis", "batter_runs_scored",
    "batter_hits_runs_rbis", "batter_singles", "batter_doubles", "batter_triples", "batter_walks",
    "batter_strikeouts", "batter_stolen_bases", "pitcher_strikeouts", "pitcher_hits_allowed",
    "pitcher_walks", "pitcher_earned_runs", "pitcher_outs"]
_BASEBALL_ALT = ["batter_total_bases_alternate", "batter_hits_alternate", "batter_rbis_alternate",
                 "batter_runs_scored_alternate", "batter_home_runs_alternate",
                 "batter_strikeouts_alternate", "pitcher_strikeouts_alternate",
                 "pitcher_hits_allowed_alternate"]
_BASEBALL_SPECIAL = ["batter_first_home_run", "pitcher_record_a_win"]

_FAMILY = {
    "americanfootball_nfl": (_FOOTBALL, _FOOTBALL_PLAYER_EXTRA, _FOOTBALL_ALT, _FOOTBALL_SPECIAL),
    "americanfootball_ncaaf": (_FOOTBALL, _FOOTBALL_PLAYER_EXTRA, _FOOTBALL_ALT, _FOOTBALL_SPECIAL),
    "basketball_nba": (_BASKETBALL, _BASKETBALL_PLAYER_EXTRA, _BASKETBALL_ALT, _BASKETBALL_SPECIAL),
    "basketball_wnba": (_BASKETBALL, _BASKETBALL_PLAYER_EXTRA, _BASKETBALL_ALT, _BASKETBALL_SPECIAL),
    "basketball_ncaab": (_BASKETBALL, _BASKETBALL_PLAYER_EXTRA, _BASKETBALL_ALT, _BASKETBALL_SPECIAL),
    "icehockey_nhl": (_HOCKEY, _HOCKEY_PLAYER_EXTRA, _HOCKEY_ALT, _HOCKEY_SPECIAL),
    "baseball_mlb": (_BASEBALL, _BASEBALL_PLAYER_EXTRA, _BASEBALL_ALT, _BASEBALL_SPECIAL),
}


def _dedupe(seq: Iterable[str]) -> List[str]:
    out, seen = [], set()
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def catalog(odds_sport_key: str, model_markets: Optional[Sequence[str]] = None) -> Dict[str, List[str]]:
    """Market groups for a sport: {group label: [Odds API market keys]}, in display order. The
    sport's own model-priced player markets come first among the player groups so they are the
    default; an unknown sport gets just the three universal game lines."""
    fam = _FAMILY.get(odds_sport_key)
    if fam is None:
        return {"Game lines": ["h2h", "spreads", "totals"]}
    game, extra, alt, special = fam
    groups: Dict[str, List[str]] = dict(game)
    main = _dedupe(list(model_markets or []) + extra)
    groups["Player props — main"] = main
    groups["Player props — alternate lines"] = _dedupe(alt)
    groups["Player props — specials"] = _dedupe(special)
    return groups


def market_kind(key: str) -> str:
    if key.startswith(("team_totals", "alternate_team_totals")):
        return "team_total"
    if key.startswith(("totals", "alternate_totals")):
        return "total"
    if key.startswith(("spreads", "alternate_spreads")):
        return "spread"
    if key.startswith(("h2h", "draw_no_bet")):
        return "moneyline"
    if key.startswith(("player_", "batter_", "pitcher_")):
        return "player"
    return "other"


def _period_suffix(key: str) -> Tuple[str, str]:
    for suf in sorted(_PERIOD_TITLES, key=len, reverse=True):
        if key.endswith(suf):
            return key[: -len(suf)], _PERIOD_TITLES[suf]
    return key, ""


def market_title(key: str, market_map: Optional[Dict[str, str]] = None) -> str:
    """Display name for a market key. Player markets the sport's own market_map knows reuse the
    board's display name ("Points"), so a menu leg and the same leg from the board share an id."""
    inv = {v: k for k, v in (market_map or {}).items()}
    if key in inv:
        return inv[key]
    base, period = _period_suffix(key)
    if base in _GAME_BASE:
        return f"{period} {_GAME_BASE[base]}".strip()
    alt = base.endswith("_alternate")
    core = re.sub(r"_alternate$", "", base)
    core = re.sub(r"^(player|batter|pitcher)_", "", core)
    fixes = {"Yds": "Yards", "Td": "TD", "Tds": "TDs", "Rbis": "RBIs", "1St": "1st"}
    words = " ".join(fixes.get(w, w) for w in core.replace("_", " ").title().split())
    prefix = {"batter": "Batter ", "pitcher": "Pitcher "}.get(key.split("_", 1)[0], "")
    return f"{prefix}{words}{' (alt)' if alt else ''}".strip()


def all_keys(groups: Dict[str, List[str]], chosen: Iterable[str]) -> List[str]:
    return _dedupe(k for g in chosen for k in groups.get(g, []))


def estimate_cost(n_events: int, n_markets: int) -> int:
    """Upper-bound Odds API credits for a menu fetch: one request per (game, market) at one
    bookmaker, each billed at most 1 credit per market actually returned."""
    return max(0, int(n_events)) * max(0, int(n_markets))


# --------------------------------------------------------------------------- fetch
def _is_unavailable(msg: str) -> bool:
    low = msg.lower()
    return low.startswith("http 422") or "invalid_market" in low or "invalid market" in low \
        or "not supported" in low or low.startswith("http 404")


def fetch_menu(api_key: str, sport: str, event_ids: Sequence[str], market_keys: Sequence[str], book: str,
               *, progress: Optional[Callable[[int, int], None]] = None, max_workers: int = 4,
               get: Optional[Callable] = None) -> Dict:
    """Fetch `market_keys` for each event at ONE book. Returns
    {"quotes": [...], "events": {id: {home, away, commence}}, "errors": [...], "unavailable": [...],
     "remaining": str|None, "requests": n, "aborted": str|None}.

    Every (event, market) is its own request; a market the API rejects is listed in
    "unavailable", any other failure in "errors", and neither stops the rest. A bad API key (401)
    or exhausted quota (429) aborts the remaining requests (they would all fail the same way) and
    is reported in "aborted" alongside whatever was already fetched."""
    get = get or O._get
    book = O.canonical_book(book)
    jobs = [(e, m) for e in event_ids for m in market_keys]
    quotes: List[Dict] = []
    events: Dict[str, Dict] = {}
    errors: List[Dict] = []
    unavailable: List[Tuple[str, str]] = []
    remaining = None
    aborted: Optional[str] = None
    done = 0

    def one(job):
        eid, mk = job
        return get(f"sports/{sport}/events/{eid}/odds",
                   {"apiKey": api_key, "markets": mk, "oddsFormat": "american", "dateFormat": "iso",
                    "bookmakers": book})

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        fut_job = {pool.submit(one, j): j for j in jobs}
        for fut in as_completed(fut_job):
            eid, mk = fut_job[fut]
            done += 1
            if progress:
                progress(done, len(jobs))
            if fut.cancelled():
                continue
            try:
                data, hdr = fut.result()
            except O.OddsAPIError as e:
                msg = str(e)
                if msg.startswith(("401", "429")):
                    aborted = aborted or msg
                    for f in fut_job:
                        f.cancel()
                elif _is_unavailable(msg):
                    unavailable.append((eid, mk))
                else:
                    errors.append({"event": eid, "market": mk, "error": msg})
                continue
            except Exception as e:                       # noqa: BLE001 — one odd response must not sink the rest
                errors.append({"event": eid, "market": mk, "error": str(e)})
                continue
            remaining = hdr.get("remaining") or remaining
            if isinstance(data, dict):
                events[eid] = {"id": eid, "home": data.get("home_team"), "away": data.get("away_team"),
                               "commence": data.get("commence_time")}
                quotes.extend(parse_menu_event(data, book))
    return {"quotes": quotes, "events": events, "errors": errors, "unavailable": unavailable,
            "remaining": remaining, "requests": len(jobs), "aborted": aborted}


# --------------------------------------------------------------------------- parse
_OVER = ("over", "o")
_UNDER = ("under", "u")
_YES = ("yes",)
_NO = ("no",)


def parse_menu_event(event_json: Dict, book: str) -> List[Dict]:
    """Flatten one event response into quotes (one per outcome) for `book` only:
    {event_id, away, home, commence, market, kind, name, description, point, price}. Outcomes
    without a price are dropped; everything else is kept exactly as the API gave it."""
    book = O.canonical_book(book)
    out = []
    for bm in event_json.get("bookmakers", []):
        if O.canonical_book(bm.get("key")) != book:
            continue
        for mk in bm.get("markets", []):
            key = mk.get("key")
            if not key:
                continue
            for oc in mk.get("outcomes", []):
                price = oc.get("price")
                if price is None:
                    continue
                try:
                    price = float(price)
                except (TypeError, ValueError):
                    continue
                if price == 0:
                    continue
                out.append({"event_id": event_json.get("id"), "away": event_json.get("away_team"),
                            "home": event_json.get("home_team"), "commence": event_json.get("commence_time"),
                            "market": key, "kind": market_kind(key), "name": oc.get("name"),
                            "description": oc.get("description"), "point": oc.get("point"), "price": price})
    return out


# --------------------------------------------------------------------------- game / team labels
def _strip_game_suffix(label: str) -> str:
    return re.sub(r"\s*\(Game \d+\)\s*$", "", label or "").strip()


def board_player_info(pool: Sequence[Dict], normalize_name: Callable[[str], str]) -> Dict[str, Dict]:
    """{normalized player: {"game", "team"}} from the board's legs — how a menu event is tied back
    to the board's own game label and team spelling."""
    info: Dict[str, Dict] = {}
    for l in pool:
        if l.get("player") and l.get("game"):
            info.setdefault(normalize_name(l["player"]), {"game": l["game"], "team": l.get("team")})
    return info


def label_events(events: Dict[str, Dict], quotes: Sequence[Dict], info: Dict[str, Dict],
                 normalize_name: Callable[[str], str],
                 offers: Optional[Sequence[Dict]] = None) -> Dict[str, Dict]:
    """For each fetched event: {"game", "away", "home", "away_team", "home_team"}.

    The board's game label wins when any of the event's player props belong to a player the board
    knows (majority vote) — that is what makes a menu leg share a game with the board's own legs
    for correlation. The team names are mapped to the board's spelling by position ("AWAY @ HOME").
    An event with no known player (in the menu OR in the board's own offers) falls back to the API's own
    "Away @ Home" and full team names."""
    votes: Dict[str, Dict[str, int]] = {}

    def _vote(eid, player):
        rec = info.get(normalize_name(player)) if (eid and player) else None
        if rec:
            d = votes.setdefault(eid, {})
            d[rec["game"]] = d.get(rec["game"], 0) + 1

    for q in quotes:
        if q.get("kind") == "player":
            _vote(q.get("event_id"), q.get("description"))
    # The board's own already-fetched offers carry the event id (odds_api.parse_event_offers), so a game
    # whose menu holds only team markets can still be tied to the board's label via its player props.
    for off in offers or []:
        _vote(off.get("event_id"), off.get("player"))
    out = {}
    for eid, ev in events.items():
        away, home = ev.get("away") or "?", ev.get("home") or "?"
        label, away_t, home_t = f"{away} @ {home}", away, home
        v = votes.get(eid)
        if v:
            label = max(v.items(), key=lambda kv: (kv[1], kv[0]))[0]
            parts = [_strip_game_suffix(x) for x in _strip_game_suffix(label).split(" @ ")]
            if len(parts) == 2 and all(parts):
                away_t, home_t = parts
        out[eid] = {"game": label, "away": away, "home": home, "away_team": away_t, "home_team": home_t,
                    "commence": ev.get("commence")}
    return out


# --------------------------------------------------------------------------- devig + legs
def _implied(price: float) -> float:
    return O.implied_prob(price)


def _group_probs(prices: Sequence[float]) -> Tuple[List[float], bool]:
    """Probabilities for one group of outcomes at a book. 2-3 outcomes are de-vigged
    proportionally (True); a single outcome — or a group too large to be one market (a
    mis-grouped ladder) — returns the plain implied probabilities (False: they include the margin)."""
    imps = [_implied(p) for p in prices]
    if 2 <= len(imps) <= 3:
        tot = sum(imps)
        if tot > 0:
            return [i / tot for i in imps], True
    return imps, False


def _side_of(name: Optional[str]) -> Optional[str]:
    n = (name or "").strip().lower()
    if n in _OVER:
        return "Over"
    if n in _UNDER:
        return "Under"
    if n in _YES:
        return "Yes"
    if n in _NO:
        return "No"
    return None


def build_menu_legs(quotes: Sequence[Dict], labels: Dict[str, Dict], book: str, *,
                    market_map: Optional[Dict[str, str]] = None,
                    info: Optional[Dict[str, Dict]] = None,
                    normalize_name: Optional[Callable[[str], str]] = None) -> List[Dict]:
    """Turn parsed quotes into Slip Lab legs (see build_leg_pool for the shared fields), one per
    priced side, with probabilities from the book's own no-vig price (or implied, flagged)."""
    book = O.canonical_book(book)
    norm = normalize_name or (lambda s: str(s).strip().lower())
    info = info or {}
    groups: Dict[Tuple, List[Dict]] = {}
    for q in quotes:
        lab = labels.get(q["event_id"])
        if lab is None:
            continue
        kind, name, desc, point = q["kind"], q.get("name"), q.get("description"), q.get("point")
        side = _side_of(name)
        if kind == "moneyline":
            gk = (q["event_id"], q["market"])
        elif kind == "spread":
            if point is None:
                continue
            gk = (q["event_id"], q["market"], abs(float(point)))
        elif kind == "total":
            if point is None:
                continue
            gk = (q["event_id"], q["market"], float(point))
        elif kind == "team_total":
            if point is None or not desc:
                continue
            gk = (q["event_id"], q["market"], desc, float(point))
        elif kind == "player":
            subject = desc if (side is not None and desc) else (name if side is None else None)
            if not subject:
                continue
            gk = (q["event_id"], q["market"], subject, None if point is None else float(point))
        else:
            continue
        groups.setdefault(gk, []).append(q)

    legs: List[Dict] = []
    for gk, qs in groups.items():
        eid, mkey = gk[0], gk[1]
        lab = labels[eid]
        kind = qs[0]["kind"]
        title = market_title(mkey, market_map)
        probs, devigged = _group_probs([q["price"] for q in qs])
        for q, p in zip(qs, probs):
            name, desc, point = q.get("name"), q.get("description"), q.get("point")
            side = _side_of(name)
            team, opp, subject, line, leg_kind, player_id = None, None, None, None, kind, None
            if kind == "moneyline":
                if str(name).strip().lower() == "draw":
                    leg_kind, subject, side_word = "other", "Draw", "Draw"
                else:
                    subject, side_word = name, "Win"
                    team = _board_team(name, lab)
            elif kind == "spread":
                subject, side_word, line, team = name, "Cover", float(point), _board_team(name, lab)
            elif kind == "total":
                subject, side_word, line = lab["game"], (side or str(name)), float(point)
            elif kind == "team_total":
                subject, side_word, line, team = desc, (side or str(name)), float(point), _board_team(desc, lab)
            else:                                        # player
                if side is not None:
                    subject, side_word = desc, side
                else:                                    # outcome NAME is the player ("to score" style)
                    subject, side_word = name, "Yes"
                line = None if point is None else float(point)
                rec = info.get(norm(subject))
                team = rec.get("team") if rec else None
            if not subject:
                continue
            leg_key = SL.leg_id(subject, title, side_word, line)
            p = min(0.995, max(0.005, float(p)))
            legs.append({
                "id": leg_key, "player": subject, "player_id": player_id, "team": team,
                "game": lab["game"], "opp": opp, "market": title, "side": side_word, "line": line,
                "p": round(p, 4), "n_eff": MENU_N_EFF, "price": q["price"], "best_price": q["price"],
                "best_book": book, "p_mkt": round(p, 4) if devigged else None,
                "edge": 0.0 if devigged else None,
                "ev_pct": round((p * O.american_to_decimal(q["price"]) - 1.0) * 100.0, 2),
                "at_book": True, "book": book, "conviction": None,
                "why": f"{O.book_label(book)} menu — " + ("book's no-vig probability" if devigged
                                                          else "book's implied probability (includes margin)"),
                "game_date": lab.get("commence"), "line_source": "menu", "source": "menu",
                "play": None, "kind": leg_kind, "event_id": eid, "market_key": mkey,
                "p_source": "market" if devigged else "implied",
            })
    return legs


def _board_team(name: Optional[str], lab: Dict) -> Optional[str]:
    """The board's spelling of a team named by the API, by home/away position."""
    if not name:
        return None
    if name == lab.get("away"):
        return lab.get("away_team")
    if name == lab.get("home"):
        return lab.get("home_team")
    return name


# --------------------------------------------------------------------------- model matching
def model_index(pool: Sequence[Dict], market_map: Dict[str, str],
                normalize_name: Callable[[str], str]) -> Dict[Tuple, Dict]:
    """{(normalized player, market key, side, line): board leg} for every model-priced board leg."""
    idx: Dict[Tuple, Dict] = {}
    for l in pool:
        mk = market_map.get(l.get("market"))
        if not mk or l.get("source") == "menu":
            continue
        idx[(normalize_name(l["player"]), mk, l["side"], l["line"])] = l
    return idx


def attach_model(menu_legs: Sequence[Dict], index: Dict[Tuple, Dict],
                 normalize_name: Callable[[str], str]) -> List[Dict]:
    """Replace the market probability with the model's on every menu leg the board also prices
    (same player, market, side, line). Returns NEW dicts; unmatched legs pass through untouched."""
    out = []
    for l in menu_legs:
        hit = None
        if l.get("kind") == "player":
            hit = index.get((normalize_name(l["player"]), l.get("market_key"), l["side"], l["line"]))
        if hit is None:
            out.append(l)
            continue
        p = float(hit["p"])
        merged = dict(l, p=round(p, 4), n_eff=hit.get("n_eff", l["n_eff"]), player_id=hit.get("player_id"),
                      team=hit.get("team") or l.get("team"), opp=hit.get("opp"),
                      conviction=hit.get("conviction"), why=hit.get("why"), play=hit.get("play"),
                      p_source="model", line_source=hit.get("line_source") or l.get("line_source"))
        merged["edge"] = None if l.get("p_mkt") is None else round(p - l["p_mkt"], 4)
        merged["ev_pct"] = round((p * O.american_to_decimal(l["price"]) - 1.0) * 100.0, 2)
        out.append(merged)
    return out
