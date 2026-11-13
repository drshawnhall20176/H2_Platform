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

# Nov 13 (owner sent DraftKings' soccer list): every league DK posts that ESPN and/or the Odds API carry.
# key -> title, ESPN slug, Odds API key (None = no odds feed: the model's read only), group (the page's grouping),
# pool (whose results the ratings are fitted on: the country's leagues and cups together; "europe" / "conmebol" for the
# continental cups, which need every member league; national teams and women's leagues on their own).
_L = [
    # Europe -- top 5
    ("SOCCER_EPL", "Premier League", "eng.1", "soccer_epl", "Europe — top 5", "eng"),
    ("SOCCER_LALIGA", "La Liga", "esp.1", "soccer_spain_la_liga", "Europe — top 5", "esp"),
    ("SOCCER_SERIEA", "Serie A", "ita.1", "soccer_italy_serie_a", "Europe — top 5", "ita"),
    ("SOCCER_BUNDESLIGA", "Bundesliga", "ger.1", "soccer_germany_bundesliga", "Europe — top 5", "ger"),
    ("SOCCER_LIGUE1", "Ligue 1", "fra.1", "soccer_france_ligue_one", "Europe — top 5", "fra"),
    # Europe -- more leagues
    ("SOCCER_CHAMPIONSHIP", "EFL Championship", "eng.2", "soccer_efl_champ", "Europe — more leagues", "eng"),
    ("SOCCER_LEAGUE1", "England League One", "eng.3", "soccer_england_league1", "Europe — more leagues", "eng"),
    ("SOCCER_LEAGUE2", "England League Two", "eng.4", "soccer_england_league2", "Europe — more leagues", "eng"),
    ("SOCCER_LALIGA2", "La Liga 2", "esp.2", "soccer_spain_segunda_division", "Europe — more leagues", "esp"),
    ("SOCCER_SERIEB", "Serie B", "ita.2", "soccer_italy_serie_b", "Europe — more leagues", "ita"),
    ("SOCCER_BUNDESLIGA2", "2. Bundesliga", "ger.2", "soccer_germany_bundesliga2", "Europe — more leagues", "ger"),
    ("SOCCER_LIGUE2", "Ligue 2", "fra.2", "soccer_france_ligue_two", "Europe — more leagues", "fra"),
    ("SOCCER_EREDIVISIE", "Netherlands Eredivisie", "ned.1", "soccer_netherlands_eredivisie", "Europe — more leagues", "ned"),
    ("SOCCER_EERSTE", "Netherlands Eerste Divisie", "ned.2", None, "Europe — more leagues", "ned"),
    ("SOCCER_PORTUGAL", "Portugal Primeira Liga", "por.1", "soccer_portugal_primeira_liga", "Europe — more leagues", "por"),
    ("SOCCER_SCOTLAND", "Scotland Premiership", "sco.1", "soccer_spl", "Europe — more leagues", "sco"),
    ("SOCCER_SCOTCHAMP", "Scotland Championship", "sco.2", None, "Europe — more leagues", "sco"),
    ("SOCCER_BELGIUM", "Belgium Pro League", "bel.1", "soccer_belgium_first_div", "Europe — more leagues", "bel"),
    ("SOCCER_AUSTRIA", "Austria Bundesliga", "aut.1", "soccer_austria_bundesliga", "Europe — more leagues", "aut"),
    ("SOCCER_SWISS", "Switzerland Super League", "sui.1", "soccer_switzerland_superleague", "Europe — more leagues", "sui"),
    ("SOCCER_TURKEY", "Turkey Super Lig", "tur.1", "soccer_turkey_super_league", "Europe — more leagues", "tur"),
    ("SOCCER_GREECE", "Greece Super League", "gre.1", "soccer_greece_super_league", "Europe — more leagues", "gre"),
    ("SOCCER_DENMARK", "Denmark Superliga", "den.1", "soccer_denmark_superliga", "Europe — more leagues", "den"),
    ("SOCCER_NORWAY", "Norway Eliteserien", "nor.1", "soccer_norway_eliteserien", "Europe — more leagues", "nor"),
    ("SOCCER_SWEDEN", "Sweden Allsvenskan", "swe.1", "soccer_sweden_allsvenskan", "Europe — more leagues", "swe"),
    # continental cups
    ("SOCCER_UCL", "Champions League", "uefa.champions", "soccer_uefa_champs_league", "European cups", "europe"),
    ("SOCCER_UEL", "Europa League", "uefa.europa", "soccer_uefa_europa_league", "European cups", "europe"),
    ("SOCCER_UECL", "Conference League", "uefa.europa.conf", "soccer_uefa_europa_conference_league", "European cups", "europe"),
    # domestic cups
    ("SOCCER_EFLCUP", "England EFL Cup", "eng.league_cup", "soccer_england_efl_cup", "Domestic cups", "eng"),
    ("SOCCER_FACUP", "England FA Cup", "eng.fa", "soccer_fa_cup", "Domestic cups", "eng"),
    ("SOCCER_DFBPOKAL", "Germany DFB-Pokal", "ger.dfb_pokal", "soccer_germany_dfb_pokal", "Domestic cups", "ger"),
    ("SOCCER_COPADELREY", "Spain Copa del Rey", "esp.copa_del_rey", "soccer_spain_copa_del_rey", "Domestic cups", "esp"),
    ("SOCCER_COUPEFRANCE", "France Coupe de France", "fra.coupe_de_france", "soccer_france_coupe_de_france",
     "Domestic cups", "fra"),
    # Americas
    ("SOCCER_MLS", "MLS", "usa.1", "soccer_usa_mls", "Americas", "usa"),
    ("SOCCER_USL", "USL Championship", "usa.usl.1", None, "Americas", "usa"),
    ("SOCCER_LIGAMX", "Liga MX", "mex.1", "soccer_mexico_ligamx", "Americas", "mex"),
    ("SOCCER_BRAZIL", "Brazil Serie A", "bra.1", "soccer_brazil_campeonato", "Americas", "bra"),
    ("SOCCER_BRAZILB", "Brazil Serie B", "bra.2", "soccer_brazil_serie_b", "Americas", "bra"),
    ("SOCCER_ARGENTINA", "Argentina Liga Profesional", "arg.1", "soccer_argentina_primera_division", "Americas", "arg"),
    ("SOCCER_CHILE", "Chile Primera", "chi.1", "soccer_chile_campeonato", "Americas", "chi"),
    ("SOCCER_COLOMBIA", "Colombia Primera A", "col.1", None, "Americas", "col"),
    ("SOCCER_PERU", "Peru Liga 1", "per.1", None, "Americas", "per"),
    ("SOCCER_URUGUAY", "Uruguay Primera", "uru.1", None, "Americas", "uru"),
    ("SOCCER_GUATEMALA", "Guatemala Liga Nacional", "gua.1", None, "Americas", "gua"),
    ("SOCCER_LIBERTADORES", "Copa Libertadores", "conmebol.libertadores", "soccer_conmebol_copa_libertadores",
     "Americas", "conmebol"),
    ("SOCCER_SUDAMERICANA", "Copa Sudamericana", "conmebol.sudamericana", "soccer_conmebol_copa_sudamericana",
     "Americas", "conmebol"),
    # Asia & Oceania
    ("SOCCER_ALEAGUE", "Australia A-League", "aus.1", "soccer_australia_aleague", "Asia & Oceania", "aus"),
    ("SOCCER_JLEAGUE", "Japan J.League", "jpn.1", "soccer_japan_j_league", "Asia & Oceania", "jpn"),
    # women
    ("SOCCER_NWSL", "NWSL", "usa.nwsl", None, "Women", "usa-w"),
    ("SOCCER_WSL", "England Women's Super League", "eng.w.1", None, "Women", "eng-w"),
    ("SOCCER_ALEAGUEW", "Australia A-League Women", "aus.w.1", None, "Women", "aus-w"),
    ("SOCCER_UWCL", "Women's Champions League", "uefa.wchampions", None, "Women", "eng-w"),
    # national teams
    ("SOCCER_NATIONS", "UEFA Nations League", "uefa.nations", "soccer_uefa_nations_league", "National teams", "nations"),
    ("SOCCER_WCQ_UEFA", "World Cup qualifying (Europe)", "fifa.worldq.uefa",
     "soccer_fifa_world_cup_qualifiers_europe", "National teams", "nations"),
    ("SOCCER_CONCACAF_NL", "CONCACAF Nations League", "concacaf.nations.league", None, "National teams", "nations"),
    ("SOCCER_AFCON_Q", "Africa Cup of Nations qualifying", "caf.nations_qual", "soccer_africa_cup_of_nations",
     "National teams", "nations"),
    ("SOCCER_FRIENDLY", "International friendlies", "fifa.friendly", None, "National teams", "nations"),
]
LEAGUES = {k: {"title": t, "slug": s, "odds": o, "group": g, "pool": p, "europe": p == "europe"}
           for k, t, s, o, g, p in _L}
GROUPS = list(dict.fromkeys(v["group"] for v in LEAGUES.values()))
EUROPE_COUNTRIES = ("eng", "esp", "ita", "ger", "fra", "ned", "por", "sco", "bel", "aut", "sui", "tur", "gre", "den",
                    "nor", "swe")
CONMEBOL_COUNTRIES = ("bra", "arg", "chi", "col", "per", "uru")


def pool_keys(league: str) -> list:
    """The leagues whose results rate this league's teams."""
    p = LEAGUES[league]["pool"]
    if p == "europe":
        return [k for k, v in LEAGUES.items() if v["pool"] in EUROPE_COUNTRIES + ("europe",)]
    if p == "conmebol":
        return [k for k, v in LEAGUES.items() if v["pool"] in CONMEBOL_COUNTRIES + ("conmebol",)]
    return [k for k, v in LEAGUES.items() if v["pool"] == p]


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


def parse_fixtures(data: Optional[Dict], league: str) -> List[Dict]:
    """ESPN scoreboard -> matches not started yet {id, kickoff, home, away}."""
    out = []
    for e in (data or {}).get("events") or []:
        st = ((e.get("status") or {}).get("type") or {})
        if st.get("state") not in (None, "pre"):
            continue
        comp = (e.get("competitions") or [{}])[0]
        cs = {c.get("homeAway"): c for c in comp.get("competitors") or []}
        h, a = cs.get("home"), cs.get("away")
        if not h or not a:
            continue
        out.append({"id": str(e.get("id")), "kickoff": e.get("date"), "league": league,
                    "home": (h.get("team") or {}).get("displayName"), "away": (a.get("team") or {}).get("displayName"),
                    "neutral": bool(comp.get("neutralSite"))})
    return out


def espn_fixtures(league: str, start: date, days: int = 7, fetch: Callable = _http) -> List[Dict]:
    dd = [start + timedelta(days=i) for i in range(days)]
    with ThreadPoolExecutor(4) as ex:
        chunks = list(ex.map(lambda d: parse_fixtures(
            fetch(ESPN.format(slug=LEAGUES[league]["slug"]), {"dates": d.strftime("%Y%m%d")}), league), dd))
    return [g for c in chunks for g in c]


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
    # Totals: the main line is Pinnacle's (or, without it, the US line priced closest to even); alternate lines the
    # US books also post (3.5, 4.5 ...) are ignored. Nov 13 live check: picking the most-quoted line chose 3.5.
    def _balance(pair):
        a, b = (_dec(pair[0][0][0]) if pair[0] else None), (_dec(pair[1][0][0]) if pair[1] else None)
        return abs(a - b) if a and b else 9.0
    main_tot = None
    if sharp_tot:
        main_tot = min((L for L, v in sharp_tot.items() if all(v)), key=lambda L: abs(sharp_tot[L][0] - sharp_tot[L][1]),
                       default=None)
    if tot:
        if main_tot is not None and main_tot in tot:
            L = main_tot
        elif main_tot is not None:
            L = min(tot, key=lambda x: abs(x - main_tot))
        else:
            L = min(tot, key=lambda x: _balance((tot[x]["over"], tot[x]["under"])))
        out["line_total"] = L
        for s in ("over", "under"):
            out[f"{s}_price"], out[f"{s}_book"] = _best(tot[L][s])
        sp = sharp_tot.get(L)
        if sp and all(sp):
            out["mkt_over"] = round(_devig(sp)[0], 4)
    elif main_tot is not None:
        out["line_total"] = main_tot
        out["mkt_over"] = round(_devig(sharp_tot[main_tot])[0], 4)
    # Asian handicap: Pinnacle's main line; US prices when a US book posts that line (often they don't).
    main_ah = min((L for L, v in sharp_ah.items() if all(v)), key=lambda L: abs(sharp_ah[L][0] - sharp_ah[L][1]),
                  default=None) if sharp_ah else None
    if main_ah is None and ah:
        main_ah = min(ah, key=lambda x: _balance((ah[x]["home"], ah[x]["away"])))
    if main_ah is not None:
        out["home_spread"] = main_ah
        if main_ah in ah:
            out["spread_price_home"], out["spread_book_home"] = _best(ah[main_ah]["home"])
            out["spread_price_away"], out["spread_book_away"] = _best(ah[main_ah]["away"])
        sp = sharp_ah.get(main_ah)
        if sp and all(sp):
            out["mkt_ah_home"] = round(_devig(sp)[0], 4)
    return out


def fetch_odds(league: str, api_key: str, fetch: Callable = _http) -> List[Dict]:
    """One call: 3 markets x (Pinnacle + the US books) -- the bookmakers list counts as one region (3 credits)."""
    if not LEAGUES[league].get("odds"):
        return []
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
