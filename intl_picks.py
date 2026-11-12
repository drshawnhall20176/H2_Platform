"""
intl_picks.py — live tracking for tennis and international basketball (Nov 3). TRACKING ONLY: nothing here is a
recommendation to bet until the record proves it (the thresholds come from research/backtest_tennis.py and
research/backtest_intl_hoops.py).

Every capture (capture-intl workflow, every 3 hours):
  1. refreshes the results archive (model_store.results_archive) -- tennis matches from ESPN, EuroLeague games from
     its API, NBL games from ESPN -- seeding the full history the first time;
  2. refits the model (surface Elo for tennis, season ratings for basketball);
  3. prices every upcoming match / game the books list (The Odds API) and saves it to model_store.game_picks with the
     model's read and a tracking pick where the model clears its bar. The first capture is the OPEN line, later ones
     before the start overwrite the CLOSE;
  4. grades started matches / games from the archive.

Stored per sport key: TENNIS, EUROLEAGUE, NBL. "line" is the home side's market chance (tennis) or the home margin the
spread implies (basketball); final_home / final_away are games won (tennis) or points (basketball); result is the
winner ("home" / "away") so each market's pick is graded from the payload by summary().
"""
from __future__ import annotations

import os
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import intl_hoops as I
import tennis_calibration as TC
import tennis_model as T

ODDS = "https://api.the-odds-api.com/v4/sports/{key}/odds"
SPORTS_URL = "https://api.the-odds-api.com/v4/sports"
# Backtests, Nov 3 (research/backtest_tennis.py, backtest_intl_hoops.py, against The Odds API's historical lines):
# * Tennis, 5,952 priced 2025-26 matches: the market's chance beat surface Elo clearly (log loss 0.558 vs 0.608).
#   Betting Elo's side lost 6-11% at every edge size (bigger edges lost more); game handicaps hit 47%, total games
#   51%. NO PICKS: the model is shown for information only. (None = off.)
# * EuroLeague, 1,001 games 2022-26: spreads with the model 4+ points off the line 119-98 (54.8%), 6+ 59-39
#   (60.2%), 8+ 27-15; totals and moneylines no edge. Spread picks at 4+.
# * NBL, 295 games 2023-26: spreads 50-51% at every edge, totals no; moneyline at a 5%+ edge +2.5% over 204 (weak).
#   Moneyline tracked, nothing else.
TENNIS_ML_EDGE = None
TENNIS_MIN_MATCHES = 30        # both players need this many rated matches
TENNIS_GAMES_EDGE = None
HOOPS_RULES = {"EUROLEAGUE": {"spread": 4.0, "total": None, "ml": None},
               "NBL": {"spread": None, "total": None, "ml": 0.05},
               "NCAAMB": {"spread": None, "total": None, "ml": None},   # Nov 3: OFF -- opening-week model bug; re-testing
               "NBA": {"spread": None, "total": None, "ml": None},       # set from research/backtest_pro_games.py
               "NHL": {"spread": None, "total": None, "ml": None}}
# NCAAMB (research/backtest_ncaamb_games.py, 5,554 games 2024-26 with a pre-game line): spreads improved steadily
# with the gap -- 4+ 53.1%, 6+ 54.4%, 8+ 55.2% (1065-866), 10+ 57.6% (n=1,425); both seasons alike, November best.
# Totals 51-53% (off). The moneyline "showed" +15-21%, which is too good to be real (stale outlier prices at
# small books) -- off.
# Nov 3 correction: those cumulative numbers hid where the edge is. By gap BAND the covers were 8-10 48.2% (n=506),
# 10-16 52.9% (879), 16-20 56.6% (251), 20+ 72.5% (295) -- the edge is in the biggest disagreements only, so the
# college pick bar is 16+. EuroLeague by band: 4-6 50.4% (119), 6-8 57.1% (56), 8+ 64.3% (42) -> 6+.
HOOPS_RULES["EUROLEAGUE"]["spread"] = 6.0    # Nov 4: re-confirmed by the corrected backtest (33-16 at 6+), tracking
# Estimated cover chance by gap band (from those backtests) -> the same Use tags the props pages show.
COVER_BANDS = {
    # Nov 4, corrected backtests (no home-side guessing). Small samples are shrunk toward 50% ((wins+25)/(n+50)) so a
    # 49-game band can't earn a lock by itself.
    "NCAAMB": ((0, 999, 0.508, 5184),),                     # 50.8-52.4% at every gap up to 8+; no edge
    "EUROLEAGUE": ((0, 4, 0.51, 956), (4, 6, 0.514, 109), (6, 999, 0.586, 49)),     # 6+: 33-16 raw, 58.6% shrunk
}
HOOPS_EVIDENCE = {
    "NBA": "Information only — no picks. Backtest vs real lines (779 games, 2024-26): spreads covered 46-54% across gap "
           "sizes with no steady pattern, totals and moneylines were inconsistent season to season. NBA lines are "
           "sharp; use the model as a second look.",
    "NHL": "Information only — no picks. Backtest vs real lines (1,026 games, 2024-26): the model's side of the puck "
           "line covered 64-67%, but that is the +1.5 side's built-in cover rate (it's priced around -200), not an "
           "edge; totals 45-55% and moneylines lost at the median price.",
    "NCAAMB": "Information only — no picks. Corrected backtest vs real lines (5,184 games, 2024-26): the model's side "
              "of the spread covered 50.8-52.4% at every gap size up to 8+ points (10+ was 55% over 502, too thin to "
              "act on); totals 46-50%, moneylines -5%. An earlier run that looked far better had lines read upside "
              "down for some games; that's fixed.",
    "EUROLEAGUE": "Tracking only. Corrected backtest vs real lines (1,124 games, 2022-26): spreads with the model 6+ "
                  "points off went 33-16 (67%), 4-6 points 51%; by season at 4+: 62%, 47%, 67%, 55%. Promising but small "
                  "— the cover chance shown is shrunk toward 50% for that reason. Totals and moneylines showed no edge.",
}


def cover_estimate(league: str, gap: Optional[float]) -> Optional[Dict]:
    """The backtest's cover rate for this size of disagreement: {"chance", "n", "band"}; None without a table."""
    if gap is None:
        return None
    for lo, hi, ch, n in COVER_BANDS.get(league, ()):
        if lo <= abs(gap) < hi:
            return {"chance": ch, "n": n, "band": f"{lo}–{hi}" if hi < 999 else f"{lo}+"}
    return None


def use_tag(chance: Optional[float]) -> Dict:
    """The props pages' tags for a game line: 60%+ -> Parlay + Single and Most probable; 55-60% -> Single only."""
    import props_engine as PE
    if chance is None:
        return {"use": "—", "lock": False}
    if chance >= PE.MOST_PROBABLE_CHANCE:
        return {"use": PE.USE_BOTH, "lock": True}
    if chance >= 0.55:
        return {"use": PE.USE_SINGLE, "lock": False}
    return {"use": PE.USE_PASS, "lock": False}


# --------------------------------------------------------------------------- one set of Use tags for every game page (Nov 4)
# The props pages' symbols, applied to tennis matches and basketball / hockey games so every page reads the same way:
#   🔒 Most probable  = 60%+ to win AND the backing to trust it (a tested edge, or enough history on both players)
#   🎟️ Parlay + Single = 60%+ and a price that pays (+3% or better)      🎯 Single only = 55-60% at a price that pays
#   ⛔ Pass            = a coin flip, a price that doesn't pay, or no tested edge for this league / market
# Where there's no price yet (lower-tier tennis, EuroCup) the tag says the price it needs ("at -150 or better").
def american(dec: Optional[float]) -> Optional[int]:
    if dec is None or dec <= 1:
        return None
    return int(round((dec - 1) * 100)) if dec >= 2 else int(round(-100 / (dec - 1)))


def price_needed(chance: Optional[float], min_ev: Optional[float] = None) -> Optional[int]:
    """The worst American price at which this chance still earns min_ev (default the props pages' +3%)."""
    import props_engine as PE
    if chance is None or chance <= 0:
        return None
    return american((1 + (PE.MIN_EV if min_ev is None else min_ev)) / chance)


def _odds_txt(a: Optional[int]) -> str:
    return "—" if a is None else f"{a:+d}"


def chance_use(chance: Optional[float], price=None, trusted: bool = True) -> Dict:
    """Use tag for one side from its chance and (when there is one) the price you'd get.
    trusted=False (thin history): never a lock and never a parlay leg -- a single at most."""
    import props_engine as PE
    if chance is None:
        return {"use": "—", "lock": False, "why": "no read"}
    if chance < 0.55:
        return {"use": PE.USE_PASS, "lock": False, "why": f"{chance:.0%} is too close to a coin flip"}
    need = price_needed(chance)
    if price is None:                                           # no price yet: say what it needs
        if chance >= PE.MOST_PROBABLE_CHANCE and trusted:
            return {"use": PE.USE_BOTH, "lock": True, "why": f"{chance:.0%}; a single needs {_odds_txt(need)} or better",
                    "need": need}
        return {"use": PE.USE_SINGLE, "lock": False, "need": need,
                "why": f"{chance:.0%}" + ("" if trusted else ", thin history") + f"; needs {_odds_txt(need)} or better"}
    dec = _dec(price)
    if dec is None:
        return {"use": "—", "lock": False, "why": "no price"}
    ev = chance * dec - 1
    bits = f"{chance:.0%} at {float(price):+.0f} = {ev:+.1%}"
    if chance >= PE.MOST_PROBABLE_CHANCE and trusted and ev > 0:
        return {"use": PE.USE_BOTH if ev >= PE.MIN_EV else PE.USE_PARLAY, "lock": True, "why": bits, "need": need}
    if ev >= PE.MIN_EV:
        return {"use": PE.USE_SINGLE, "lock": False, "why": bits + ("" if trusted else ", thin history"), "need": need}
    return {"use": PE.USE_PASS, "lock": False, "why": bits + f" (needs {_odds_txt(need)} or better)", "need": need}


def tag_label(t: Dict) -> str:
    import props_engine as PE
    u = t.get("use") or "—"
    if t.get("need") is not None and t.get("use") not in (PE.USE_PASS, "—") and not t.get("priced"):
        u = f"{u} ({_odds_txt(t['need'])} or better)"
    return f"{PE.MOST_PROBABLE} · {u}" if t.get("lock") else u


TENNIS_UNPROVEN = 0.70


def tennis_use(p: Dict, k: Optional[float] = None) -> Dict:
    """The model's player and Use tag for one tennis record. Main-tour (odds feed) matches: the books beat this model
    in the backtest, so they're ⛔ Pass whatever the model says; everything else is read off the model's chance with
    the price it needs (or the best posted price), and a player with under TENNIS_MIN_MATCHES rated matches can't be a lock."""
    import props_engine as PE
    mp = p.get("model_p")
    if mp is None:
        return {"player": None, "chance": None, "use": "—", "lock": False, "why": "no read"}
    home = mp >= 0.5
    who, ch = (p["home"], mp) if home else (p["away"], 1 - mp)
    trusted = min(int(p.get("n_home") or 0), int(p.get("n_away") or 0)) >= TENNIS_MIN_MATCHES
    out = {"player": who, "chance": ch, "fair": american(1 / ch) if ch > 0 else None}
    if p.get("source") != "espn":                               # priced main-tour event
        price = p.get("best_home") if home else p.get("best_away")
        out.update(use=PE.USE_PASS, lock=False, priced=True,
                   why="main tour: the books beat this model in the backtest" + (f"; best price {float(price):+.0f}" if price else ""))
        return out
    if k is None:
        k = TC.current_k()
    if ch >= TENNIS_UNPROVEN and abs(k - 1.0) < 1e-9:           # Nov 12: until the automatic correction passes
        out.update(use=PE.USE_PASS, lock=False, unproven=True,
                   why="⚠️ not proven: over the last month the model's 70-80% favorites won only ~60%. Held back "
                       "until the automatic tennis correction passes its check.")
        return out
    out.update(chance_use(ch, None, trusted))
    return out


def hoops_use(league: str, p: Dict) -> Dict:
    """Use tag for a game-lines record: the backtest's cover rate where the league has one (EuroLeague), the tracked
    moneyline rule (NBL), otherwise ⛔ Pass -- NBA, NHL and college showed no edge against real lines."""
    import props_engine as PE
    if p.get("use") and p.get("use") != "—":
        return {"use": p["use"], "lock": bool(p.get("lock")), "priced": True,
                "why": f"backtest: this gap covered {p['cover_est']:.0%}" if p.get("cover_est") is not None else ""}
    if p.get("ml_pick"):
        side = p["home"] if p["ml_pick"] == "home" else p["away"]
        return {"use": PE.USE_SINGLE, "lock": False, "priced": True, "why": f"{side} moneyline: the tracked 5%+ edge rule"}
    if league in COVER_BANDS or HOOPS_EVIDENCE.get(league):
        return {"use": PE.USE_PASS, "lock": False, "priced": True, "why": "no tested edge in this league"}
    return {"use": PE.USE_PASS, "lock": False, "priced": True, "why": "no tested edge yet"}
HOOPS_ML_EDGE = 0.05
TENNIS_SEED_FROM = date(2023, 1, 1)


def _http(url: str, params: Optional[Dict] = None):
    import requests
    try:
        r = requests.get(url, params=params or {}, timeout=30, headers={"User-Agent": "H2Sports/1.0"})
        return r.json() if r.ok else None
    except Exception:                                           # noqa: BLE001
        return None


def _implied(a) -> Optional[float]:
    try:
        a = float(a)
    except (TypeError, ValueError):
        return None
    if -100 < a < 100:
        return None
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def _dec(a) -> Optional[float]:
    try:
        a = float(a)
    except (TypeError, ValueError):
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a) if abs(a) >= 100 else None


def market(ev: Dict, home: str, away: str) -> Dict:
    """Consensus no-vig home chance, best prices by side (with the book), median spread / total lines and prices."""
    fair, best_h, best_a = [], (None, None), (None, None)
    sp, sp_price, tot, tot_o, tot_u = [], [], [], [], []
    for b in ev.get("bookmakers") or []:
        for m in b.get("markets") or []:
            oc = m.get("outcomes") or []
            if m.get("key") == "h2h":
                d = {o.get("name"): o.get("price") for o in oc}
                if home in d and away in d:
                    ph, pa = _implied(d[home]), _implied(d[away])
                    if ph and pa:
                        fair.append(ph / (ph + pa))
                        if best_h[0] is None or _dec(d[home]) > _dec(best_h[0]):
                            best_h = (d[home], b.get("title"))
                        if best_a[0] is None or _dec(d[away]) > _dec(best_a[0]):
                            best_a = (d[away], b.get("title"))
            elif m.get("key") == "spreads":
                for o in oc:
                    if o.get("name") == home and o.get("point") is not None:
                        sp.append(float(o["point"]))
                        sp_price.append(float(o.get("price") or -110))
            elif m.get("key") == "totals":
                for o in oc:
                    if o.get("point") is None:
                        continue
                    if o.get("name") == "Over":
                        tot.append(float(o["point"]))
                        tot_o.append(float(o.get("price") or -110))
                    elif o.get("name") == "Under":
                        tot_u.append(float(o.get("price") or -110))
    return {"fair_home": statistics.mean(fair) if fair else None, "books": len(fair),
            "best_home": best_h[0], "best_home_book": best_h[1], "best_away": best_a[0], "best_away_book": best_a[1],
            "home_spread": statistics.median(sp) if sp else None,
            "spread_price": statistics.median(sp_price) if sp_price else None,
            "total": statistics.median(tot) if tot else None,
            "over_price": statistics.median(tot_o) if tot_o else None,
            "under_price": statistics.median(tot_u) if tot_u else None}


# --------------------------------------------------------------------------- tennis
def tennis_refresh(fetch: Callable = _http, today: Optional[date] = None, db_path: Optional[str] = None) -> int:
    import model_store as MS
    today = today or datetime.now(timezone.utc).date()
    have = MS.load_results("TENNIS", since=(today - timedelta(days=30)).isoformat(), db_path=db_path)
    start = today - timedelta(days=6) if have else TENNIS_SEED_FROM
    rows = T.crawl(start, today, fetch=fetch, step_days=1 if have else 2)
    return MS.save_results("TENNIS", rows, db_path=db_path)


def tennis_keys(api_key: str, fetch: Callable = _http) -> List[str]:
    return [s["key"] for s in fetch(SPORTS_URL, {"apiKey": api_key}) or []
            if s.get("group") == "Tennis" and s.get("active") and ("_atp_" in s["key"] or "_wta_" in s["key"])]


def tennis_build(elo: T.Elo, fit: Dict, key: str, events: Sequence[Dict], now: datetime,
                 k: Optional[float] = None) -> List[Dict]:
    tour = "atp" if "_atp_" in key else "wta"
    title = key.split("_", 2)[2].replace("_", " ").title()
    out = []
    for ev in events or []:
        try:
            ko = datetime.fromisoformat(str(ev["commence_time"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if ko <= now:
            continue
        home, away = ev.get("home_team"), ev.get("away_team")
        mk = market(ev, home, away)
        if mk["fair_home"] is None:
            continue
        surf = T.surface(title, ko.date().isoformat())
        bo = T.best_of(title, tour)
        p_raw = elo.prob(home, away, surf)
        p = TC.shrink(p_raw, k) if k is not None else p_raw     # Nov 12: the honest (calibrated) chance
        n1, n2 = elo.matches(home), elo.matches(away)
        edge = p - mk["fair_home"]
        rated = min(n1, n2) >= TENNIS_MIN_MATCHES
        pick = None
        if rated and TENNIS_ML_EDGE is not None and abs(edge) >= TENNIS_ML_EDGE:
            pick = "home" if edge > 0 else "away"
        g = T.games(fit, p, bo) if fit else None
        sp_pick = tot_pick = None
        p_cover = p_over = None
        if g and mk["home_spread"] is not None:
            p_cover = T.p_over(g["margin"], g["mar_sd"], -mk["home_spread"])
            if rated and TENNIS_GAMES_EDGE is not None and abs(p_cover - 0.5) >= TENNIS_GAMES_EDGE:
                sp_pick = "home" if p_cover > 0.5 else "away"
        if g and mk["total"] is not None:
            p_over = T.p_over(g["total"], g["tot_sd"], mk["total"])
            if rated and TENNIS_GAMES_EDGE is not None and abs(p_over - 0.5) >= TENNIS_GAMES_EDGE:
                tot_pick = "over" if p_over > 0.5 else "under"
        out.append({"sport": "TENNIS", "game_id": str(ev.get("id")), "kickoff": ko.isoformat(), "tour": tour,
                    "tournament": title, "surface": surf, "best_of": bo, "home": home, "away": away,
                    "model_p": round(p, 4), "model_p_raw": round(p_raw, 4), "n_home": n1, "n_away": n2,
                    "line": round(mk["fair_home"], 4),
                    "edge": round(edge, 4), "line_total": mk["total"], "home_spread": mk["home_spread"],
                    "best_home": mk["best_home"], "best_home_book": mk["best_home_book"], "best_away": mk["best_away"],
                    "best_away_book": mk["best_away_book"], "spread_price": mk["spread_price"],
                    "over_price": mk["over_price"], "under_price": mk["under_price"], "books": mk["books"],
                    "model_total": round(g["total"], 1) if g else None, "model_margin": round(g["margin"], 1) if g else None,
                    "p_cover": None if p_cover is None else round(p_cover, 3),
                    "p_over": None if p_over is None else round(p_over, 3),
                    "pick": pick, "spread_pick": sp_pick, "total_pick": tot_pick})
    return out


def tennis_schedule(elo: T.Elo, fetch: Callable = _http, now: Optional[datetime] = None,
                    priced: Sequence[Dict] = (), k: Optional[float] = None) -> List[Dict]:
    """Every scheduled ATP / WTA singles match ESPN lists for today and tomorrow -- including WTA 125 / lower-tier
    events the odds feed doesn't price -- with the model's chance. No line, no pick: the page shows the fair price and
    lets the owner type the sportsbook's. Matches the odds feed already priced are left to those records."""
    now = now or datetime.now(timezone.utc)
    out, seen = [], set()
    for d in (now.date(), now.date() + timedelta(days=1)):
        for tour in T.TOURS:
            for m in T.parse_upcoming(fetch(T.ESPN.format(tour=tour), {"dates": d.strftime("%Y%m%d")}) or {}, tour):
                if m["id"] in seen:
                    continue
                seen.add(m["id"])
                if any(_same_player(m["p1"], q["home"]) and _same_player(m["p2"], q["away"]) or
                       _same_player(m["p2"], q["home"]) and _same_player(m["p1"], q["away"]) for q in priced):
                    continue
                p_raw = elo.prob(m["p1"], m["p2"], m["surface"])
                p = TC.shrink(p_raw, k) if k is not None else p_raw
                out.append({"sport": "TENNIS", "game_id": f"espn-{m['id']}", "model_p_raw": round(p_raw, 4), "kickoff": m["start"], "tour": tour,
                            "tournament": m["tournament"], "city": m.get("city"), "round": m["round"], "surface": m["surface"],
                            "best_of": m["best_of"], "home": m["p1"], "away": m["p2"], "model_p": round(p, 4),
                            "n_home": elo.matches(m["p1"]), "n_away": elo.matches(m["p2"]), "line": None, "edge": None,
                            "source": "espn", "pick": None, "spread_pick": None, "total_pick": None})
    return out


def tennis_capture(api_key: str, fetch: Callable = _http, now: Optional[datetime] = None,
                   db_path: Optional[str] = None) -> Dict:
    import model_store as MS
    now = now or datetime.now(timezone.utc)
    added = tennis_refresh(fetch, now.date(), db_path)
    hist = MS.load_results("TENNIS", db_path=db_path)
    elo, rows = T.run(hist)
    fit = T.fit_games(rows)
    kcal = TC.current_k()                                       # Nov 12: automatic tennis calibration
    recs = []
    for k in tennis_keys(api_key, fetch):
        evs = fetch(ODDS.format(key=k), {"apiKey": api_key, "regions": "us", "markets": "h2h,spreads,totals",
                                         "oddsFormat": "american"})
        recs += tennis_build(elo, fit, k, evs or [], now, k=kcal)
    sched = tennis_schedule(elo, fetch, now, recs, k=kcal)
    saved = MS.save_game_picks(recs + sched, db_path=db_path)
    graded = tennis_grade(hist, db_path=db_path)
    try:
        settle_logged("TENNIS", db_path=db_path)
    except Exception:                                           # noqa: BLE001
        pass
    return {"archive_added": added, "matches_rated": len(rows), "priced": len(recs), "scheduled_unpriced": len(sched),
            "picks": sum(1 for r in recs if r["pick"]), "saved": saved, "graded": graded}


def _same_player(a: str, b: str) -> bool:
    """Same first initial and a shared surname word -- "Daniel Merida" is "Daniel Merida Aguilar" (Nov 4: the two
    feeds spell double surnames differently, so the same match showed up twice)."""
    ta, tb = T.norm(a).split(), T.norm(b).split()
    if not (ta and tb and ta[0][0] == tb[0][0]):
        return False
    return ta[-1] == tb[-1] or (len(ta) > 1 and len(tb) > 1 and bool(set(ta[1:]) & set(tb[1:])))


def tennis_grade(hist: Sequence[Dict], db_path: Optional[str] = None) -> int:
    import model_store as MS
    n = 0
    for p in MS.load_game_picks("TENNIS", ungraded=True, db_path=db_path):
        day = str(p.get("kickoff"))[:10]
        for m in hist:
            if abs((date.fromisoformat(m["date"]) - date.fromisoformat(day)).days) > 2:
                continue
            if _same_player(m["p1"], p["home"]) and _same_player(m["p2"], p["away"]):
                hg, ag, hw = m["games1"], m["games2"], m["winner"] == 1
            elif _same_player(m["p2"], p["home"]) and _same_player(m["p1"], p["away"]):
                hg, ag, hw = m["games2"], m["games1"], m["winner"] == 2
            else:
                continue
            res = "void" if m.get("status") == "walkover" else ("home" if hw else "away")
            if MS.grade_game_pick("TENNIS", p["game_id"], hg, ag, res if m.get("status") != "retired" else "retired",
                                  db_path=db_path):
                n += 1
            break
    return n


# --------------------------------------------------------------------------- international basketball
def hoops_refresh(league: str, fetch: Callable = _http, today: Optional[date] = None,
                  db_path: Optional[str] = None, fetch_text: Optional[Callable] = None) -> int:
    import model_store as MS
    today = today or datetime.now(timezone.utc).date()
    season = I.season_of(league, today.isoformat())
    fetch_text = fetch_text or getattr(I, "_http_text", None)
    if league == "EUROLEAGUE":
        rows = I.euroleague_season(f"E{season}", fetch)
    elif league == "EUROCUP":
        rows = I.euroleague_season(f"U{season}", fetch, comp="U", league="EUROCUP")
    elif league in getattr(I, "GENIUS_COMPS", {}):
        rows = I.genius_results(league, I.genius_games(league, fetch))
    elif league in getattr(I, "FIBA_PAGES", {}):
        rows = I.fiba_results(league, I.fiba_season(league, season, fetch_text))
        prev = str(int(season) - 1)
        if not MS.load_results(league, since=f"{prev}-07-01", db_path=db_path):          # first run: last season too
            rows += I.fiba_results(league, I.fiba_season(league, prev, fetch_text, current=False))
    elif league in I.ESPN_LEAGUE_URL:
        have = MS.load_results(league, since=(today - timedelta(days=30)).isoformat(), db_path=db_path)
        start = today - timedelta(days=7) if have else today - timedelta(days=400)
        rows = I.espn_range(league, start, today, fetch)
    elif league == "NCAAMB":
        # first run: last season (Nov-Apr) plus this one so the recency-weighted ratings have a prior; then a week back
        have = MS.load_results(league, since=(today - timedelta(days=30)).isoformat(), db_path=db_path)
        start = today - timedelta(days=7) if have else date(int(season) - 1, 11, 1)
        rows = I.ncaamb_range(start, today, fetch)
    else:
        have = MS.load_results(league, since=f"{season}-07-01", db_path=db_path)
        start = today - timedelta(days=7) if have else date(int(season), 9, 1)
        rows = I.nbl_range(start, today, fetch)
    for r in rows:
        r["season"] = I.season_of(league, r["date"])
    return MS.save_results(league, rows, db_path=db_path)


def hoops_build(league: str, r: Optional[Dict], events: Sequence[Dict], now: datetime, k: float = 1.0) -> List[Dict]:
    """k: the league's automatic win-chance calibration (tennis_calibration, Nov 12); 1.0 = none applied yet."""
    rules = HOOPS_RULES.get(league, {})
    se, te, me = rules.get("spread"), rules.get("total"), rules.get("ml")
    out = []
    for ev in events or []:
        try:
            ko = datetime.fromisoformat(str(ev["commence_time"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if ko <= now:
            continue
        home, away = ev.get("home_team"), ev.get("away_team")
        proj = I.project(r, home, away, loose=league != "NCAAMB")
        mk = market(ev, home, away)
        if not proj or mk["home_spread"] is None:
            continue
        line_margin = -mk["home_spread"]
        edge = proj["margin"] - line_margin
        p_raw = I.win_prob(proj["margin"], league=league)
        p = TC.shrink(p_raw, k) if k != 1.0 else p_raw
        ml_edge = None if mk["fair_home"] is None else p - mk["fair_home"]
        tot_edge = None if mk["total"] is None else proj["total"] - mk["total"]
        ce = cover_estimate(league, edge)
        tag = use_tag(ce["chance"] if ce else None)
        out.append({"sport": league, "game_id": str(ev.get("id")), "kickoff": ko.isoformat(), "home": home,
                    "cover_est": None if not ce else ce["chance"], "cover_n": None if not ce else ce["n"],
                    "use": tag["use"], "lock": tag["lock"],
                    "away": away, "model_margin": round(proj["margin"], 1), "model_total": round(proj["total"], 1),
                    "line": line_margin, "home_spread": mk["home_spread"], "edge": round(edge, 2),
                    "line_total": mk["total"], "total_edge": None if tot_edge is None else round(tot_edge, 1),
                    "model_p": round(p, 3), "model_p_raw": round(p_raw, 3), "fair_home": mk["fair_home"],
                    "ml_edge": None if ml_edge is None else round(ml_edge, 3),
                    "best_home": mk["best_home"], "best_home_book": mk["best_home_book"], "best_away": mk["best_away"],
                    "best_away_book": mk["best_away_book"], "spread_price": mk["spread_price"],
                    "over_price": mk["over_price"], "under_price": mk["under_price"],
                    "pick": ("home" if edge > 0 else "away") if se is not None and abs(edge) >= se else None,
                    "total_pick": (("over" if tot_edge > 0 else "under")
                                   if te is not None and tot_edge is not None and abs(tot_edge) >= te else None),
                    "ml_pick": (("home" if ml_edge > 0 else "away")
                                if me is not None and ml_edge is not None and abs(ml_edge) >= me else None)})
    return out


TOTAL_SD = {"NKL": 17.0, "ICELAND": 17.0, "BAHRAIN": 17.0, "ESTONIA1": 17.0, "QATAR": 17.0, "BCL": 16.0, "FEC": 16.5, "EUROCUPW": 15.0, "EUROCUP": 16.0, "EUROLEAGUE": 16.0, "NBL": 18.0, "NCAAMB": 17.0, "NBA": 18.0, "WNBA": 17.0, "NHL": 2.3}


def hoops_schedule_build(league: str, r: Optional[Dict], upcoming: Sequence[Dict], now: datetime,
                         k: float = 1.0) -> List[Dict]:
    """Games with no sportsbook line in the odds feed (EuroCup): the model's fair spread, total and win chance, so the
    page can show fair prices and check a typed one. No line, no pick."""
    out = []
    for g in upcoming:
        try:
            ko = datetime.fromisoformat(g["kickoff"])
        except (KeyError, ValueError):
            continue
        if ko <= now or ko > now + timedelta(days=8):
            continue
        proj = I.project(r, g["home"], g["away"], g.get("neutral", False), loose=True)
        if not proj:
            continue
        out.append({"sport": league, "game_id": str(g["id"]), "kickoff": ko.isoformat(), "home": g["home"], "away": g["away"],
                    "model_margin": round(proj["margin"], 1), "model_total": round(proj["total"], 1),
                    "model_p": round(TC.shrink(I.win_prob(proj["margin"], league=league), k) if k != 1.0
                                     else I.win_prob(proj["margin"], league=league), 3),
                    "model_p_raw": round(I.win_prob(proj["margin"], league=league), 3), "line": None, "edge": None,
                    "home_spread": None, "line_total": None, "source": "schedule", "pick": None, "total_pick": None,
                    "ml_pick": None})
    return out


def fair_chance(p: Dict, market: str, side: str, line: Optional[float]) -> Optional[float]:
    """The model's chance for a typed bet on a game: Spread / Total / Moneyline, side home/away/over/under; `line` is from
    that side's point of view (Spread) or the total."""
    import math
    sd = I.LEAGUES.get(p["sport"], {}).get("sd", 11.5)
    if market == "Moneyline":
        return p["model_p"] if side == "home" else 1 - p["model_p"]
    if market == "Spread" and line is not None:
        m = p["model_margin"] if side == "home" else -p["model_margin"]
        return 0.5 * math.erfc(-(m + line) / (sd * math.sqrt(2)))
    if market == "Total" and line is not None:
        tsd = TOTAL_SD.get(p["sport"], 16.0)
        over = 0.5 * math.erfc((line - p["model_total"]) / (tsd * math.sqrt(2)))
        return over if side == "over" else 1 - over
    return None


def hoops_capture(league: str, api_key: str, fetch: Callable = _http, now: Optional[datetime] = None,
                  db_path: Optional[str] = None, fetch_text: Optional[Callable] = None) -> Dict:
    import model_store as MS
    now = now or datetime.now(timezone.utc)
    cfg = I.LEAGUES[league]
    fetch_text = fetch_text or getattr(I, "_http_text", None)
    added = hoops_refresh(league, fetch, now.date(), db_path, fetch_text)
    season = I.season_of(league, now.date().isoformat())
    if cfg.get("decay"):                                       # college: last ~13 months, recency-weighted
        since = (now.date() - timedelta(days=400)).isoformat()
        games = MS.load_results(league, since=since, db_path=db_path)
        r = I.ratings_weighted(games, I.decay_weights(games, now.date().isoformat(), league), cfg["lam"],
                               I.HFA_PRIOR.get(league)) \
            if len(games) >= cfg.get("min_decay_games", 500 if league == "NCAAMB" else 300) else None
    else:
        games = [g for g in MS.load_results(league, db_path=db_path) if str(g.get("season")) == season]
        r = I.ratings(games, cfg["lam"]) if len(games) >= cfg["min_games"] else None
    if cfg.get("odds_key"):
        evs = fetch(ODDS.format(key=cfg["odds_key"]), {"apiKey": api_key, "regions": "us",
                                                        "markets": "h2h,spreads,totals", "oddsFormat": "american"}) or []
        recs = hoops_build(league, r, evs, now, TC.current_k(sport=league))
    else:                                                      # no odds feed for this league: fair lines from the schedule
        evs = []
        if league in getattr(I, "GENIUS_COMPS", {}):
            upcoming = I.genius_upcoming(league, I.genius_games(league, fetch))
        elif league in getattr(I, "FIBA_PAGES", {}):
            upcoming = I.fiba_upcoming(league, I.fiba_season(league, season, fetch_text))
        else:
            code = ("U" if league == "EUROCUP" else "E") + I.season_of(league, now.date().isoformat())
            upcoming = I.euroleague_upcoming(code, fetch, comp=cfg.get("comp", "E"), league=league)
        recs = hoops_schedule_build(league, r, upcoming, now, TC.current_k(sport=league))
    got = {x["game_id"] for x in recs}
    future = [e for e in evs if str(e.get("commence_time")) > now.isoformat()[:19]]
    missed = [f"{e.get('away_team')} @ {e.get('home_team')}" for e in future if str(e.get("id")) not in got]
    saved = MS.save_game_picks(recs, db_path=db_path)
    graded = hoops_grade(league, MS.load_results(league, since=(now.date() - timedelta(days=10)).isoformat(),
                                                 db_path=db_path), db_path=db_path)
    try:
        settled = settle_logged(league, db_path=db_path)
    except Exception:                                           # noqa: BLE001 -- settling never blocks a capture
        settled = 0
    return {"archive_added": added, "season_games": len(games), "rated": r is not None,
            "hfa": None if not r else round(r["hfa"], 2), "events": len(future),
            "bets_settled": settled,
            "priced": len(recs), "unmatched": missed[:40], "picks": sum(1 for x in recs if x["pick"]), "saved": saved,
            "graded": graded}


# --------------------------------------------------------------------------- logging a Game Lab bet (Nov 3)
BET_SPORT = {"NCAAMB": "NCAAMB", "NBA": "NBA", "NHL": "NHL", "WNBA": "WNBA", "EUROLEAGUE": "INTL", "NBL": "INTL",
             "EUROCUP": "INTL", "BCL": "INTL", "FEC": "INTL", "EUROCUPW": "INTL", "NKL": "INTL", "ICELAND": "INTL",
             "BAHRAIN": "INTL", "ESTONIA1": "INTL", "QATAR": "INTL",
             "TENNIS": "TENNIS"}
TAG = "gl"                     # notes carry "gl:<league>:<game_id>" so the capture can settle the bet itself


def bet_fields(p: Dict, market: str, side: str, line: Optional[float], odds: float, stake: float, real: bool,
               model_prob: Optional[float] = None) -> Dict:
    """Bet Log fields for a Game Lab bet. market: Spread / Total / Moneyline. side: "home" / "away" / "over" /
    "under". `line` is from that side's point of view (a spread of -7.5 on the team taken)."""
    import betlog as B
    team = p["home"] if side == "home" else (p["away"] if side == "away" else None)
    return {"slate_date": str(p.get("kickoff"))[:10] if p.get("kickoff") else None, "sport": BET_SPORT.get(p["sport"], "INTL"),
            "game": f"{p['away']} @ {p['home']}", "player": team or "Game total", "market": market,
            "side": team or side.title(), "line": line, "entry_odds": float(odds), "entry_odds_source": "manual",
            "model_prob": model_prob, "stake": float(stake), "is_real_bet": bool(real),
            "category": B.default_category(BET_SPORT.get(p["sport"]), from_model=True),
            "notes": f"{TAG}:{p['sport']}:{p['game_id']}"}


def bet_result(bet: Dict, p: Dict) -> Optional[str]:
    """win / loss / push for a logged Game Lab bet from its graded record; None until it's graded."""
    fh, fa, res = p.get("final_home"), p.get("final_away"), p.get("result")
    if fh is None or fa is None or res in (None, "void", "retired"):
        return None
    mk, side = bet.get("market"), bet.get("side")
    if mk == "Total":
        d = (fh + fa) - float(bet["line"])
        return "push" if d == 0 else ("win" if (d > 0) == (str(side).lower() == "over") else "loss")
    home = side == p["home"]
    if mk == "Moneyline":
        return "win" if (res == "home") == home else "loss"
    if mk == "Spread":
        d = (fh - fa if home else fa - fh) + float(bet["line"])
        return "push" if d == 0 else ("win" if d > 0 else "loss")
    return None


def settle_logged(league: str, db_path: Optional[str] = None) -> int:
    """Settle open Bet Log bets that were logged from a Game Lab page, once their game is graded here."""
    import betlog as B
    import model_store as MS
    graded = {p["game_id"]: p for p in MS.load_game_picks(league, db_path=db_path) if p.get("result")}
    n = 0
    every = B.list_bets()

    def _link(b):
        # the game link can sit anywhere in the notes (after a strategy tag, Nov 4)
        return next((t.strip() for t in str(b.get("notes") or "").split(",") if t.strip().startswith(f"{TAG}:{league}:")), None)
    # Nov 8: parlay legs logged before legs carried their own note have no link; borrow it from the single on the
    # same game, market, side and line (the college totals parlay of Nov 7 sat open for that reason)
    by_bet = {(b.get("slate_date"), b.get("game"), b.get("market"), str(b.get("side")).lower(), b.get("line")): _link(b)
              for b in every if _link(b)}
    for b in [x for x in every if not x.get("result")]:
        link = _link(b) or by_bet.get((b.get("slate_date"), b.get("game"), b.get("market"), str(b.get("side")).lower(),
                                       b.get("line")))
        if not link:
            continue
        p = graded.get(link.split(":", 2)[2])
        r = bet_result(b, p) if p else None
        if r:
            B.update_bet(int(b["id"]), result=r)
            n += 1
    return n


def _team_is(a: str, b: str, loose: bool = False) -> bool:
    """Strict: the same team by exact name, or a confident word match (never just a shared nickname). Loose (small
    leagues, where club names vary by source): one distinctive shared word."""
    return I.find_team([a], b, loose) is not None


def hoops_grade(league: str, results: Sequence[Dict], db_path: Optional[str] = None) -> int:
    import model_store as MS
    n = 0
    for p in MS.load_game_picks(league, ungraded=True, db_path=db_path):
        day = str(p.get("kickoff"))[:10]
        for g in results:
            if abs((date.fromisoformat(g["date"]) - date.fromisoformat(day)).days) > 1:
                continue
            lz = league != "NCAAMB"
            if _team_is(g["home_team"], p["home"], lz) and _team_is(g["away_team"], p["away"], lz):
                hp, ap = g["home_points"], g["away_points"]
            elif _team_is(g["home_team"], p["away"], lz) and _team_is(g["away_team"], p["home"], lz):
                hp, ap = g["away_points"], g["home_points"]
            else:
                continue
            if MS.grade_game_pick(league, p["game_id"], hp, ap, "home" if hp > ap else "away", db_path=db_path):
                n += 1
            break
    return n


# --------------------------------------------------------------------------- the record
def _outcome(won: Optional[bool], price=None) -> Dict:
    if won is None:
        return {"r": "push", "units": 0.0}
    d = _dec(price) or _dec(-110)
    return {"r": "win" if won else "loss", "units": (d - 1) if won else -1.0}


def grade_markets(p: Dict) -> Dict:
    """Each tracked market's result for one graded record: {"ml": {...}, "spread": {...}, "total": {...}}."""
    out = {}
    fh, fa, res = p.get("final_home"), p.get("final_away"), p.get("result")
    if fh is None or fa is None or res in (None, "void"):
        return out
    margin, total = fh - fa, fh + fa
    if p.get("sport") == "TENNIS":
        if p.get("pick") and res in ("home", "away"):
            out["ml"] = _outcome(p["pick"] == res, p["best_home"] if p["pick"] == "home" else p["best_away"])
        if p.get("spread_pick") and p.get("home_spread") is not None and res != "retired":
            d = margin + p["home_spread"]
            out["spread"] = _outcome(None if d == 0 else (d > 0) == (p["spread_pick"] == "home"), p.get("spread_price"))
        if p.get("total_pick") and p.get("line_total") is not None and res != "retired":
            d = total - p["line_total"]
            out["total"] = _outcome(None if d == 0 else (d > 0) == (p["total_pick"] == "over"),
                                    p.get("over_price") if p["total_pick"] == "over" else p.get("under_price"))
        return out
    line = p.get("close_line") if p.get("close_line") is not None else p.get("line")
    if p.get("pick") and line is not None:
        d = margin - line
        out["spread"] = _outcome(None if d == 0 else (d > 0) == (p["pick"] == "home"), p.get("spread_price"))
    if p.get("total_pick") and p.get("line_total") is not None:
        d = total - p["line_total"]
        out["total"] = _outcome(None if d == 0 else (d > 0) == (p["total_pick"] == "over"),
                                p.get("over_price") if p["total_pick"] == "over" else p.get("under_price"))
    if p.get("ml_pick"):
        out["ml"] = _outcome(p["ml_pick"] == res, p["best_home"] if p["ml_pick"] == "home" else p["best_away"])
    return out


def favorite_record(picks: Iterable[Dict]) -> Dict:
    """How often the model's favorite won, by tier ("priced" = the odds feed's events, "espn" = everything else), with
    the average chance it gave -- the honest check for events with no line history to backtest against."""
    out: Dict[str, Dict] = {}
    for p in picks:
        if p.get("sport") != "TENNIS" or p.get("result") not in ("home", "away") or p.get("model_p") is None:
            continue
        tier = "espn" if p.get("source") == "espn" else "priced"
        fav_home = p["model_p"] >= 0.5
        r = out.setdefault(tier, {"n": 0, "won": 0, "said": 0.0})
        r["n"] += 1
        r["won"] += int((p["result"] == "home") == fav_home)
        r["said"] += max(p["model_p"], 1 - p["model_p"])
    for r in out.values():
        r["rate"], r["said"] = r["won"] / r["n"], r["said"] / r["n"]
    return out


def record(picks: Iterable[Dict]) -> Dict:
    """{market: {"w","l","p","units","n"}} over graded records."""
    rec: Dict[str, Dict] = {}
    for p in picks:
        for mk, o in grade_markets(p).items():
            r = rec.setdefault(mk, {"w": 0, "l": 0, "p": 0, "units": 0.0, "n": 0})
            r["n"] += 1
            r["units"] += o["units"]
            r[{"win": "w", "loss": "l", "push": "p"}[o["r"]]] += 1
    for r in rec.values():
        r["roi"] = r["units"] / r["n"] if r["n"] else None
    return rec


def main(argv=None) -> int:
    api = os.environ.get("ODDS_API_KEY")
    if not api:
        print("ODDS_API_KEY not set")
        return 1
    which = (argv or sys.argv[1:] or ["TENNIS,EUROLEAGUE,EUROCUP,BCL,FEC,EUROCUPW,NKL,ICELAND,BAHRAIN,ESTONIA1,QATAR,NBL,NCAAMB,NBA,NHL"])[0].split(",")
    for s in which:
        try:
            out = tennis_capture(api) if s == "TENNIS" else hoops_capture(s, api)
        except Exception as exc:                                # noqa: BLE001 -- one sport failing never stops the rest
            out = {"error": f"{type(exc).__name__}: {exc}"}
        print(s, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
