"""
soccer_data.py — fixtures, results and prices for the Soccer Lab (Nov 13).

Results: ESPN's free scoreboard (one request per league per day), archived in results_archive under the league key
(SOCCER_EPL ...). The first capture backfills ~13 months; later ones fetch the last week.
Prices: the Odds API, one call per league for h2h (3-way), spreads (Asian handicap) and totals across Pinnacle (the
sharpest book; its no-vig price is the "fair" line) and the US books. Team names are matched to ESPN's loosely.
Player stats for props: ESPN match summaries (goals, shots, shots on target, starts) -- see player_stats().
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import requests

ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary"
ODDS = "https://api.the-odds-api.com/v4/sports/{key}/odds"
EVENT_ODDS = "https://api.the-odds-api.com/v4/sports/{key}/events/{event}/odds"

# key -> title, ESPN slug, Odds API key, home (domestic) or europe
LEAGUES = {
    "SOCCER_EPL": {"title": "Premier League", "slug": "eng.1", "odds": "soccer_epl"},
    "SOCCER_LALIGA": {"title": "La Liga", "slug": "esp.1", "odds": "soccer_spain_la_liga"},
    "SOCCER_SERIEA": {"title": "Serie A", "slug": "ita.1", "odds": "soccer_italy_serie_a"},
    "SOCCER_BUNDESLIGA": {"title": "Bundesliga", "slug": "ger.1", "odds": "soccer_germany_bundesliga"},
    "SOCCER_LIGUE1": {"title": "Ligue 1", "slug": "fra.1", "odds": "soccer_france_ligue_one"},
    "SOCCER_UCL": {"title": "Champions League", "slug": "uefa.champions", "odds": "soccer_uefa_champs_league",
                   "europe": True},
    "SOCCER_UEL": {"title": "Europa League", "slug": "uefa.europa", "odds": "soccer_uefa_europa_league",
                   "europe": True},
    "SOCCER_CHAMPIONSHIP": {"title": "EFL Championship", "slug": "eng.2", "odds": "soccer_efl_champ"},
    "SOCCER_MLS": {"title": "MLS", "slug": "usa.1", "odds": "soccer_usa_mls"},
    "SOCCER_LIGAMX": {"title": "Liga MX", "slug": "mex.1", "odds": "soccer_mexico_ligamx"},
}
DOMESTIC_EUROPE = ("SOCCER_EPL", "SOCCER_LALIGA", "SOCCER_SERIEA", "SOCCER_BUNDESLIGA", "SOCCER_LIGUE1",
                   "SOCCER_CHAMPIONSHIP")
US_BOOKS = ("draftkings", "fanduel", "betmgm", "williamhill_us", "betrivers", "fanatics", "espnbet", "ballybet")
SHARP = "pinnacle"
BACKFILL_DAYS = 400
FINAL = ("STATUS_FULL_TIME", "STATUS_FINAL", "STATUS_FINAL_AET", "STATUS_FINAL_PEN", "STATUS_FINAL_ET")


def _http(url: str, params: Optional[Dict] = None):
    for i in range(3):
        try:
            r = requests.get(url, params=params, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                return None
        except requests.RequestException:
            pass
        time.sleep(1 + i)
    return None


# --------------------------------------------------------------------------- results (ESPN)
def parse_day(data: Optional[Dict], league: str) -> List[Dict]:
    """ESPN scoreboard -> finished matches {id, date, home_team, away_team, home_points, away_points, neutral}.
    A match decided on penalties counts as the 90/120-minute draw it was (the score ESPN reports)."""
    out = []
    for e in (data or {}).get("events") or []:
        st = ((e.get("status") or {}).get("type") or {})
        if st.get("name") not in FINAL and not st.get("completed"):
            continue
        comp = (e.get("competitions") or [{}])[0]
        cs = {c.get("homeAway"): c for c in comp.get("competitors") or []}
        h, a = cs.get("home"), cs.get("away")
        if not h or not a:
            continue
        try:
            hp, ap = int(float(h.get("score"))), int(float(a.get("score")))
        except (TypeError, ValueError):
            continue
        out.append({"id": str(e.get("id")), "date": str(e.get("date"))[:10], "kickoff": e.get("date"),
                    "home_team": (h.get("team") or {}).get("displayName"),
                    "away_team": (a.get("team") or {}).get("displayName"),
                    "home_points": hp, "away_points": ap, "neutral": bool(comp.get("neutralSite")),
                    "league": league, "status": st.get("name")})
    return out


def espn_day(league: str, day: date, fetch: Callable = _http) -> List[Dict]:
    return parse_day(fetch(ESPN.format(slug=LEAGUES[league]["slug"]), {"dates": day.strftime("%Y%m%d")}), league)


def espn_range(league: str, start: date, end: date, fetch: Callable = _http, workers: int = 8) -> List[Dict]:
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    with ThreadPoolExecutor(workers) as ex:
        chunks = list(ex.map(lambda d: espn_day(league, d, fetch), days))
    return [g for c in chunks for g in c]


def refresh(league: str, today: date, fetch: Callable = _http, db_path: Optional[str] = None) -> int:
    """Archive finished matches: a ~13-month backfill the first time, then the last 7 days."""
    import model_store as MS
    have = MS.load_results(league, since=(today - timedelta(days=BACKFILL_DAYS)).isoformat(), db_path=db_path)
    start = today - timedelta(days=BACKFILL_DAYS if len(have) < 30 else 7)
    rows = espn_range(league, start, today, fetch)
    return MS.save_results(league, rows, db_path=db_path)


def matches(rows: Iterable[Dict]) -> List[Dict]:
    """Archive rows -> soccer_model.fit input."""
    out = []
    for g in rows:
        try:
            d = datetime.fromisoformat(str(g.get("kickoff") or g["date"]).replace("Z", "+00:00"))
        except ValueError:
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        out.append({"home": g["home_team"], "away": g["away_team"], "hg": g["home_points"], "ag": g["away_points"],
                    "date": d, "neutral": g.get("neutral", False)})
    return out


# --------------------------------------------------------------------------- prices (the Odds API)
def _dec(american) -> Optional[float]:
    try:
        a = float(american)
    except (TypeError, ValueError):
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a) if a else None


def _devig(decs: Sequence[float]) -> List[float]:
    inv = [1 / d for d in decs]
    s = sum(inv)
    return [x / s for x in inv]


def _best(cands: List[tuple]):
    """[(american, book)] -> the best price for the bettor."""
    cands = [c for c in cands if c[0] is not None]
    return max(cands, key=lambda c: _dec(c[0])) if cands else (None, None)


def prices(ev: Dict, home_team: str, away_team: str) -> Dict:
    """One Odds API event -> the sharp no-vig chances and the best US price per outcome, for 3-way, totals (the most
    common line) and Asian handicap (the most common US line)."""
    out: Dict = {}
    sharp3 = None
    us3 = {"home": [], "draw": [], "away": []}
    tot: Dict[float, Dict[str, list]] = {}
    sharp_tot: Dict[float, List[float]] = {}
    ah: Dict[float, Dict[str, list]] = {}
    sharp_ah: Dict[float, List[float]] = {}
    for b in ev.get("bookmakers") or []:
        key = b.get("key")
        for m in b.get("markets") or []:
            oc = m.get("outcomes") or []
            if m.get("key") == "h2h":
                by = {}
                for o in oc:
                    n = o.get("name")
                    side = "draw" if str(n).lower() == "draw" else ("home" if n == home_team else
                                                                   ("away" if n == away_team else None))
                    if side:
                        by[side] = o.get("price")
                if len(by) == 3:
                    if key == SHARP:
                        sharp3 = by
                    if key in US_BOOKS:
                        for s in by:
                            us3[s].append((by[s], key))
            elif m.get("key") == "totals":
                for o in oc:
                    pt = o.get("point")
                    if pt is None:
                        continue
                    side = str(o.get("name")).lower()
                    if key in US_BOOKS:
                        tot.setdefault(float(pt), {"over": [], "under": []})[side].append((o.get("price"), key))
                    if key == SHARP:
                        sharp_tot.setdefault(float(pt), [None, None])[0 if side == "over" else 1] = _dec(o.get("price"))
            elif m.get("key") == "spreads":
                hp = next((o for o in oc if o.get("name") == home_team), None)
                ap = next((o for o in oc if o.get("name") == away_team), None)
                if not hp or not ap or hp.get("point") is None:
                    continue
                L = float(hp["point"])
                if key in US_BOOKS:
                    d = ah.setdefault(L, {"home": [], "away": []})
                    d["home"].append((hp.get("price"), key))
                    d["away"].append((ap.get("price"), key))
                if key == SHARP:
                    sharp_ah[L] = [_dec(hp.get("price")), _dec(ap.get("price"))]
    if sharp3:
        f = _devig([_dec(sharp3[s]) for s in ("home", "draw", "away")])
        out.update(mkt_home=round(f[0], 4), mkt_draw=round(f[1], 4), mkt_away=round(f[2], 4), sharp=True)
    elif all(us3[s] for s in us3):                              # no Pinnacle: the US books' average, no-vig
        avg = [sum(_dec(p) for p, _ in us3[s]) / len(us3[s]) for s in ("home", "draw", "away")]
        f = _devig(avg)
        out.update(mkt_home=round(f[0], 4), mkt_draw=round(f[1], 4), mkt_away=round(f[2], 4), sharp=False)
    for s in ("home", "draw", "away"):
        p, bk = _best(us3[s])
        out[f"best_{s}"], out[f"book_{s}"] = p, bk
    if tot:
        L = max(tot, key=lambda x: (len(tot[x]["over"]) + len(tot[x]["under"]), x == 2.5))
        out["line_total"] = L
        for s in ("over", "under"):
            out[f"{s}_price"], out[f"{s}_book"] = _best(tot[L][s])
        sp = sharp_tot.get(L)
        if sp and all(sp):
            out["mkt_over"] = round(_devig(sp)[0], 4)
    if ah:
        L = max(ah, key=lambda x: (len(ah[x]["home"]), -abs(x)))
        out["home_spread"] = L
        out["spread_price_home"], out["spread_book_home"] = _best(ah[L]["home"])
        out["spread_price_away"], out["spread_book_away"] = _best(ah[L]["away"])
        sp = sharp_ah.get(L)
        if sp and all(sp):
            out["mkt_ah_home"] = round(_devig(sp)[0], 4)
    return out


def fetch_odds(league: str, api_key: str, fetch: Callable = _http) -> List[Dict]:
    """One call: 3 markets x (Pinnacle + the US books) -- the bookmakers list counts as one region (3 credits)."""
    return fetch(ODDS.format(key=LEAGUES[league]["odds"]),
                 {"apiKey": api_key, "bookmakers": ",".join((SHARP,) + US_BOOKS), "markets": "h2h,spreads,totals",
                  "oddsFormat": "american"}) or []


# --------------------------------------------------------------------------- player stats (ESPN match summaries)
STAT_KEYS = {"totalGoals": "goals", "totalShots": "shots", "shotsOnTarget": "sot", "goalAssists": "assists"}


def parse_summary(data: Optional[Dict]) -> List[Dict]:
    """A match summary -> one row per player who played: team, name, started, goals, shots, sot, assists."""
    out = []
    for r in (data or {}).get("rosters") or []:
        team = (r.get("team") or {}).get("displayName")
        for p in r.get("roster") or []:
            st = {s.get("name"): s.get("value") for s in p.get("stats") or []}
            played = p.get("starter") or p.get("subbedIn") or (st.get("appearances") or 0) > 0
            if not played:
                continue
            row = {"team": team, "player": (p.get("athlete") or {}).get("displayName"),
                   "pid": str((p.get("athlete") or {}).get("id") or ""), "started": bool(p.get("starter")),
                   "position": ((p.get("position") or {}).get("abbreviation") or "")}
            for k, v in STAT_KEYS.items():
                try:
                    row[v] = float(st.get(k) or 0)
                except (TypeError, ValueError):
                    row[v] = 0.0
            out.append(row)
    return out


def player_stats(league: str, event_id: str, fetch: Callable = _http) -> List[Dict]:
    return parse_summary(fetch(SUMMARY.format(slug=LEAGUES[league]["slug"]), {"event": event_id}))
