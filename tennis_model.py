"""
tennis_model.py — ATP / WTA match model (Nov 3). TRACKING ONLY until it proves itself.

Data: ESPN's tennis scoreboards (every ATP and WTA singles match, qualifying included), crawled by date. Odds: The
Odds API, which prices the main ATP / WTA tournaments (match winner at every book; set / game handicaps and total
games at some). Challengers / ITF aren't offered there.

The model: Elo ratings, overall and by surface (hard / clay / grass), updated after every completed match with the
FiveThirtyEight tennis K-factor (K = 250 / (matches + 5)^0.4, so new players move fast and veterans slowly). A match's
win chance comes from the average of the two ratings. Total games and the game margin come from the win chance
(fitted on history: fit_games), with best-of-five Slams handled separately.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

ESPN = "https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard"
TOURS = ("atp", "wta")
START = 1500.0
SURFACE_WEIGHT = 0.5            # the match chance uses half overall rating, half surface rating
SURFACES = ("hard", "clay", "grass")
SLAMS = ("australian open", "roland garros", "french open", "wimbledon", "us open")

# Surface by tournament name (ESPN names carry sponsors, so match on distinctive words). Anything not listed is hard
# (most of the calendar, indoor and outdoor).
CLAY = ("roland garros", "french open", "monte", "madrid", "internazionali", "italian", "rome", "barcelona", "hamburg",
        "kitzbuhel", "kitzbühel", "umag", "gstaad", "bastad", "båstad", "estoril", "munich", "bmw open", "geneva",
        "lyon", "houston", "marrakech", "bucharest", "rio", "buenos aires", "argentina open", "santiago", "chile",
        "cordoba", "córdoba", "charleston", "bogota", "bogotá", "rabat", "strasbourg", "parma", "palermo", "prague",
        "budapest", "lausanne", "iasi", "iași", "cluj", "warsaw", "rouen", "oeiras", "portugal", "bad gastein",
        "hamburg", "stuttgart wta", "porsche tennis grand prix", "istanbul", "morocco", "grand prix hassan")
GRASS = ("wimbledon", "halle", "queen", "hertogenbosch", "libéma", "libema", "eastbourne", "mallorca", "newport",
         "berlin", "bad homburg", "nottingham", "birmingham", "boss open", "stuttgart open", "rothesay")


def _http(url: str, params: Optional[Dict] = None):
    import requests
    try:
        r = requests.get(url, params=params or {}, timeout=30, headers={"User-Agent": "H2Sports/1.0"})
        return r.json() if r.ok else None
    except Exception:                                           # noqa: BLE001
        return None


def norm(name: Optional[str]) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]+", " ", s).strip()


def surface(tournament: str, when: Optional[str] = None) -> str:
    t = norm(tournament)
    if any(norm(k) in t for k in GRASS):
        # Stuttgart is grass for the ATP in June, clay for the WTA in April
        if "stuttgart" in t and when and when[5:7] in ("03", "04", "05"):
            return "clay"
        return "grass"
    if any(norm(k) in t for k in CLAY):
        return "clay"
    return "hard"


def best_of(tournament: str, tour: str) -> int:
    return 5 if tour == "atp" and any(s in norm(tournament) for s in SLAMS) else 3


# --------------------------------------------------------------------------- ESPN
def parse_day(data: Dict, tour: str) -> List[Dict]:
    """Completed singles matches in one ESPN scoreboard response."""
    out = []
    for ev in (data or {}).get("events") or []:
        tname = ev.get("name") or ev.get("shortName") or ""
        for g in ev.get("groupings") or []:
            gname = ((g.get("grouping") or {}).get("displayName") or "").lower()
            if "singles" not in gname:
                continue
            for c in g.get("competitions") or []:
                st = ((c.get("status") or {}).get("type") or {})
                if not st.get("completed"):
                    continue
                status = str(st.get("name") or "")
                cps = c.get("competitors") or []
                if len(cps) != 2:
                    continue
                names = [((cp.get("athlete") or {}).get("displayName") or "") for cp in cps]
                if not all(names):
                    continue
                win = [bool(cp.get("winner")) for cp in cps]
                if win.count(True) != 1:
                    continue
                sets = [[_num(ls.get("value")) for ls in (cp.get("linescores") or [])] for cp in cps]
                n = min(len(sets[0]), len(sets[1]))
                g1 = sum(x or 0 for x in sets[0][:n])
                g2 = sum(x or 0 for x in sets[1][:n])
                s1 = sum(1 for i in range(n) if (sets[0][i] or 0) > (sets[1][i] or 0))
                s2 = sum(1 for i in range(n) if (sets[1][i] or 0) > (sets[0][i] or 0))
                when = str(c.get("date") or ev.get("date") or "")[:10]
                out.append({"id": f"{tour}-{c.get('id')}", "date": when, "tour": tour, "tournament": tname,
                            "round": (c.get("round") or {}).get("displayName"), "surface": surface(tname, when),
                            "best_of": best_of(tname, tour), "p1": names[0], "p2": names[1],
                            "winner": 1 if win[0] else 2, "sets1": s1, "sets2": s2, "games1": g1, "games2": g2,
                            "status": "retired" if "RETIRED" in status else ("walkover" if "WALKOVER" in status
                                                                             else "final")})
    return out


def _num(x) -> Optional[float]:
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def crawl(start: date, end: date, fetch: Callable = _http, step_days: int = 2) -> List[Dict]:
    """Every completed singles match between two dates (ESPN returns a tournament's whole draw for any day it's on)."""
    seen: Dict[str, Dict] = {}
    d = start
    while d <= end:
        for tour in TOURS:
            for m in parse_day(fetch(ESPN.format(tour=tour), {"dates": d.strftime("%Y%m%d")}) or {}, tour):
                seen[m["id"]] = m
        d += timedelta(days=step_days)
    return sorted(seen.values(), key=lambda m: (m["date"], m["id"]))


# --------------------------------------------------------------------------- Elo
def k_factor(n: int) -> float:
    return 250.0 / ((n + 5) ** 0.4)


def expected(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


class Elo:
    def __init__(self):
        self.r: Dict[str, float] = defaultdict(lambda: START)
        self.rs: Dict[Tuple[str, str], float] = defaultdict(lambda: START)
        self.n: Dict[str, int] = defaultdict(int)
        self.ns: Dict[Tuple[str, str], int] = defaultdict(int)

    def prob(self, a: str, b: str, surf: str) -> float:
        """Chance player a beats player b on this surface."""
        a, b = norm(a), norm(b)
        po = expected(self.r[a], self.r[b])
        ps = expected(self.rs[(a, surf)], self.rs[(b, surf)])
        return SURFACE_WEIGHT * ps + (1 - SURFACE_WEIGHT) * po

    def matches(self, name: str) -> int:
        return self.n[norm(name)]

    def update(self, m: Dict) -> None:
        if m.get("status") == "walkover":
            return
        a, b = norm(m["p1"]), norm(m["p2"])
        s = 1.0 if m["winner"] == 1 else 0.0
        surf = m.get("surface") or "hard"
        ea = expected(self.r[a], self.r[b])
        ka, kb = k_factor(self.n[a]), k_factor(self.n[b])
        self.r[a] += ka * (s - ea)
        self.r[b] -= kb * (s - ea)
        es = expected(self.rs[(a, surf)], self.rs[(b, surf)])
        ksa, ksb = k_factor(self.ns[(a, surf)]), k_factor(self.ns[(b, surf)])
        self.rs[(a, surf)] += ksa * (s - es)
        self.rs[(b, surf)] -= ksb * (s - es)
        self.n[a] += 1
        self.n[b] += 1
        self.ns[(a, surf)] += 1
        self.ns[(b, surf)] += 1


def run(matches: Iterable[Dict], elo: Optional[Elo] = None) -> Tuple[Elo, List[Dict]]:
    """Walk matches in date order; each match gets its PRE-match chance for p1 ("p") before the update."""
    elo = elo or Elo()
    out = []
    for m in sorted(matches, key=lambda x: (x["date"], x["id"])):
        if m.get("status") == "walkover":
            continue
        rec = dict(m, p=elo.prob(m["p1"], m["p2"], m.get("surface") or "hard"),
                   n1=elo.matches(m["p1"]), n2=elo.matches(m["p2"]))
        out.append(rec)
        elo.update(m)
    return elo, out


# --------------------------------------------------------------------------- games
def fit_games(rows: Sequence[Dict]) -> Dict:
    """Total games and game margin (p1 - p2) as straight lines in (p - 0.5), per best-of, from completed matches;
    plus the spread of the misses (sd) so a handicap or total can get a chance."""
    import numpy as np
    out = {}
    for bo in (3, 5):
        g = [r for r in rows if r.get("best_of") == bo and r.get("status") == "final" and r.get("games1") is not None]
        if len(g) < 50:
            continue
        x = np.array([r["p"] - 0.5 for r in g])
        tot = np.array([r["games1"] + r["games2"] for r in g], dtype=float)
        mar = np.array([r["games1"] - r["games2"] for r in g], dtype=float)
        X = np.c_[np.ones_like(x), x, x ** 2]
        bt = np.linalg.lstsq(X, tot, rcond=None)[0]
        bm = np.linalg.lstsq(np.c_[x], mar, rcond=None)[0]
        out[bo] = {"tot": [float(v) for v in bt], "mar": float(bm[0]),
                   "tot_sd": float(np.std(tot - X @ bt)), "mar_sd": float(np.std(mar - x * bm[0]))}
    return out


def games(fit: Dict, p: float, bo: int) -> Optional[Dict]:
    f = fit.get(bo) or fit.get(str(bo))
    if not f:
        return None
    x = p - 0.5
    t = f["tot"]
    return {"total": t[0] + t[1] * x + t[2] * x * x, "margin": f["mar"] * x, "tot_sd": f["tot_sd"], "mar_sd": f["mar_sd"]}


def p_over(mean: float, sd: float, line: float) -> float:
    return 0.5 * math.erfc((line - mean) / (sd * math.sqrt(2)))
