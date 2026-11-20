"""
money_score.py — the Money Score for game lines (Nov 20).

Owner: "conceptualize a measure that would suggest a money pick potential in addition to the other two [Winner and
Pick] ... the one metric that would differentiate this site."

Winner asks who wins; Pick asks which side of the number. The Money Score asks whether the PRICE pays: the expected
return per $1, at the best price posted, of a chance that starts from the books' no-vig chance and adds the model's
disagreement only as far as it has earned it --

    logit P = a + b * logit(books' no-vig) + c * (logit(model) - logit(books' no-vig))

fit per league family x market (moneyline, spread, total) on every game already graded, refit every night
(`python money_score.py fit`, daily-review workflow). b and c are pulled toward "trust the books" (b = 1, c = 0) until
the record says otherwise, so a league with little history scores close to the books and shows no edge.

research/money_score_games.py, walk-forward (each day scored by a fit on earlier days only), Nov 2-19:
  moneyline + spread scoring +4% to +12%: 323 picks, hit 56.0% vs 52.1% needed, +10.9% per $1 (halves +7.5% / +14.3%);
  college basketball alone 262, +17.9% (+10.6% / +25.1%). NBA (26) and NHL (24) lost; totals lost in every version;
  scores over +12% lost (the model's biggest disagreements). So 💰 on a game line = college basketball, moneyline or
  spread, score +4% to +12% (MONEY_LEAGUES, BAND) -- in the live test (props_engine.MONEY_TEST). Every other league
  shows its score as information only.
"""
from __future__ import annotations

import math
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

KEY = "money_score:coefs"
MARKETS = ("ML", "SP", "TOT")
MARKET_NAME = {"ML": "Moneyline", "SP": "Spread", "TOT": "Total"}
BAND = (0.04, 0.12)
MONEY_LEAGUES = ("NCAAMB",)
MONEY_MARKETS = ("ML", "SP")
MIN_FIT = 80                     # graded games a league x market needs before its own fit is used
RIDGE = 1.0
_CACHE: Dict[str, object] = {}


# --------------------------------------------------------------------------- small maths
def _dec(a) -> Optional[float]:
    try:
        a = float(a)
    except (TypeError, ValueError):
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a) if abs(a) >= 100 else None


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _sig(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _devig(a, b) -> Optional[float]:
    da, db = _dec(a), _dec(b)
    if not da or not db:
        return None
    ia, ib = 1 / da, 1 / db
    return ia / (ia + ib)


def family(lg: str) -> str:
    import todays_best as TB
    return lg if lg in TB.MARGIN_SD else "INTL"


# --------------------------------------------------------------------------- features
def features(p: Dict, lg: str, home_p: Optional[float] = None) -> List[Dict]:
    """One row per market a game record can be scored on, oriented home / over:
    {mkt, pm (books' no-vig), pmod (model), home_price, away_price (over / under for totals), line, y (None until
    final)}."""
    import intl_picks as IP
    import todays_best as TB
    fam = family(lg)
    out = []
    fh, fa = p.get("final_home"), p.get("final_away")
    done = fh is not None and fa is not None
    mm, mt = p.get("model_margin"), p.get("model_total")
    hp = home_p
    if hp is None:
        hp = p.get("model_p")
        if hp is None and mm is not None:
            hp = _phi(float(mm) / TB.MARGIN_SD.get(fam, 11.0))
    pm = p.get("fair_home") or _devig(p.get("best_home"), p.get("best_away"))
    if hp is not None and pm:
        out.append({"mkt": "ML", "pm": float(pm), "pmod": float(hp), "home_price": p.get("best_home"),
                    "away_price": p.get("best_away"), "line": None,
                    "y": (None if not done or fh == fa else float(fh > fa))})
    hs = p.get("home_spread")
    if hs is None and p.get("line") is not None and lg == "NCAAF":
        hs = -float(p["line"])
    if hs is not None and mm is not None and lg != "TENNIS":
        sh, sa = p.get("spread_price"), IP.spread_price_for(p, "away")
        v = None if not done else (float(fh) - float(fa)) + float(hs)
        out.append({"mkt": "SP", "pm": _devig(sh, sa) or 0.5,
                    "pmod": _phi((float(mm) + float(hs)) / TB.MARGIN_SD.get(fam, 11.0)),
                    "home_price": sh if sh is not None else -110, "away_price": sa if sa is not None else -110,
                    "line": float(hs), "y": None if v is None or v == 0 else float(v > 0)})
    lt = p.get("line_total")
    if lt is not None and mt is not None and lg != "TENNIS":
        v = None if not done else float(fh) + float(fa) - float(lt)
        out.append({"mkt": "TOT", "pm": _devig(p.get("over_price"), p.get("under_price")) or 0.5,
                    "pmod": _phi((float(mt) - float(lt)) / TB.TOTAL_SD.get(fam, 16.0)),
                    "home_price": p.get("over_price") or -110, "away_price": p.get("under_price") or -110,
                    "line": float(lt), "y": None if v is None or v == 0 else float(v > 0)})
    return out


# --------------------------------------------------------------------------- fitting
def fit(rows: Sequence[Dict], lam: float = RIDGE) -> Optional[List[float]]:
    """[a, b, c] by ridge logistic regression, pulled toward a = 0, b = 1, c = 0 (trust the books). None if empty."""
    import numpy as np
    rows = [r for r in rows if r.get("y") is not None]
    if not rows:
        return None
    X = np.array([[1.0, _logit(r["pm"]), _logit(r["pmod"]) - _logit(r["pm"])] for r in rows])
    y = np.array([r["y"] for r in rows])
    prior = np.array([0.0, 1.0, 0.0])
    R = np.diag([0.0, 1.0, 1.0]) * lam
    w = prior.copy()
    for _ in range(60):
        pr = 1 / (1 + np.exp(-X @ w))
        g = X.T @ (pr - y) + R @ (w - prior)
        H = X.T @ (X * (pr * (1 - pr))[:, None]) + R
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return [float(v) for v in w]


def training_rows(leagues: Optional[Sequence[str]] = None, load=None) -> Dict[Tuple[str, str], List[Dict]]:
    """{(family, market): [feature rows]} from every graded game record."""
    import intl_hoops as H
    import todays_best as TB
    if load is None:
        import model_store as MS
        load = lambda lg: MS.load_game_picks(lg, ungraded=False)      # noqa: E731
    leagues = list(leagues) if leagues else list(TB.WINNER_LEAGUES) + [k for k in H.LEAGUES if k not in TB.WINNER_LEAGUES]
    out: Dict[Tuple[str, str], List[Dict]] = {}
    for lg in leagues:
        try:
            recs = load(lg) or []
        except Exception:                                       # noqa: BLE001
            continue
        for p in recs:
            try:
                hp = TB._home_p(p, lg)
            except Exception:                                   # noqa: BLE001
                hp = None
            for f in features(p, lg, hp):
                if f["y"] is not None:
                    out.setdefault((family(lg), f["mkt"]), []).append(f)
    return out


def refit(save=None, load=None) -> Dict:
    """Fit every league family x market with MIN_FIT graded games and save {"at", "coefs": {"FAM|MKT": [a, b, c, n]}}."""
    rows = training_rows(load=load)
    coefs = {}
    for (fam, mkt), rs in sorted(rows.items()):
        if len(rs) < MIN_FIT:
            print(f"{fam} {mkt}: {len(rs)} graded games — under {MIN_FIT}, scores stay at the books' chance")
            continue
        w = fit(rs)
        if w:
            coefs[f"{fam}|{mkt}"] = w + [len(rs)]
            print(f"{fam} {mkt}: a={w[0]:+.3f} books={w[1]:.3f} model disagreement={w[2]:+.3f} ({len(rs)} games)")
    rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "coefs": coefs}
    if save is None:
        import model_store as MS
        save = MS.save_setting
    import props_engine as PE
    save(KEY, rec)
    save(f"{KEY}:{PE._et_today()}", rec)        # the fit a day's games are scored with -- no look-ahead later
    _CACHE.clear()
    return rec


def coefs(day: Optional[str] = None, get=None) -> Dict[str, List[float]]:
    """The fit for `day`'s games: the one saved that morning (fit on earlier games only), else the latest. A past day
    with no fit of its own is scored with none (empty) rather than with a fit that already saw its results."""
    import props_engine as PE
    today = PE._et_today()
    k = (day or today)[:10]
    hit = _CACHE.get(k)
    if hit and time.time() - hit[0] < 600 and get is None:
        return hit[1]
    try:
        if get is None:
            import model_store as MS
            get = MS.get_setting
        rec = get(f"{KEY}:{k}", None)
        if rec is None and k >= today:
            rec = get(KEY, None)
        c = (rec or {}).get("coefs") or {}
    except Exception:                                           # noqa: BLE001
        c = {}
    _CACHE[k] = (time.time(), c)
    return c


# --------------------------------------------------------------------------- scoring
def score_market(f: Dict, w: Optional[Sequence[float]]) -> Optional[Dict]:
    """The better side of one market: {side ('home'/'away' or 'over'/'under'), chance, price, score}."""
    if not w:
        return None
    ph = _sig(w[0] + w[1] * _logit(f["pm"]) + w[2] * (_logit(f["pmod"]) - _logit(f["pm"])))
    best = None
    names = ("over", "under") if f["mkt"] == "TOT" else ("home", "away")
    for side, pr, ps in ((names[0], f["home_price"], ph), (names[1], f["away_price"], 1 - ph)):
        d = _dec(pr)
        if d and (best is None or ps * d - 1 > best["score"]):
            best = {"side": side, "chance": ps, "price": pr, "score": ps * d - 1}
    return best


def score_record(p: Dict, lg: str, home_p: Optional[float] = None, w_by=None, day: Optional[str] = None) -> Dict:
    """{"ML": {...}, "SP": {...}, "TOT": {...}, "best": the highest-scoring market (moneyline / spread only)}."""
    cf = w_by if w_by is not None else coefs(day)
    fam = family(lg)
    out: Dict[str, Optional[Dict]] = {}
    for f in features(p, lg, home_p):
        s = score_market(f, cf.get(f"{fam}|{f['mkt']}"))
        if s:
            s.update(mkt=f["mkt"], line=f["line"], y=f["y"])
            out[f["mkt"]] = s
    cands = [v for k, v in out.items() if k in MONEY_MARKETS and v]
    out["best"] = max(cands, key=lambda v: v["score"]) if cands else None
    return out


def label(p: Dict, s: Dict) -> str:
    """'Duke moneyline', 'Duke -4.5', 'Over 151.5'."""
    if s["mkt"] == "TOT":
        return f"{s['side'].capitalize()} {s['line']:g}"
    team = p.get("home") if s["side"] == "home" else p.get("away")
    if s["mkt"] == "ML":
        return f"{team} moneyline"
    ln = s["line"] if s["side"] == "home" else -s["line"]
    return f"{team} {ln:+g}"


def result(s: Dict) -> Optional[str]:
    """win / loss for a scored side once final (pushes were left out of the features)."""
    if not s or s.get("y") is None:
        return None
    home_or_over = s["side"] in ("home", "over")
    return "win" if (s["y"] == 1) == home_or_over else "loss"


def is_money(lg: str, s: Optional[Dict], day: Optional[str] = None) -> bool:
    """💰 on a game line: a MONEY_LEAGUES moneyline / spread scoring inside BAND, while the live test (or the sport's
    weekly 💰 verdict) has 💰 on for that league."""
    import props_engine as PE
    if not s or lg not in MONEY_LEAGUES or s.get("mkt") not in MONEY_MARKETS:
        return False
    return BAND[0] <= s["score"] < BAND[1] and lg in PE.money_sports(day=day)


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if (argv[0] if argv else "fit") == "fit":
        refit()
        return 0
    print("usage: python money_score.py fit")
    return 2


if __name__ == "__main__":
    sys.exit(main())
