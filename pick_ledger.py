"""
pick_ledger.py — the picks as they were SHOWN, graded at the price they showed (Nov 21).

Owner, Nov 21: "I think your 14-1 record is overstated" -- then "yes" to grading every page's record from what was on
the screen. Until now the 💰 scoreboard, the report card and the Command Center's past days graded the model's LAST
read before each game (the final pre-game snapshot, or the last saved Today's-best list), not what he saw and logged
hours earlier: a pick that was 💰 at 2 PM and dropped off by 7 PM vanished from the record, and one that turned 💰 at
6:55 PM counted though nobody saw it. This keeps a ledger, per kind, sport and slate:

  * "money"  -- every 💰 prop the moment a board first shows it (todays_best.save_props: warm job and in-app builds);
  * "strong" -- the Command Center's "strongest picks, every sport" list: every pick that was in the top 15 while its
                game was still to start (sport "ALL");
  * "games"  -- the game-line 💰 (money_score.py), whenever the board or the warm job reads the day's games.

The FIRST time a pick appears is what's kept -- its line, price, book, chance and the time -- and later reads never
overwrite it. Picks are only added before their game starts. The daily-review workflow grades yesterday's ledgers
(`python pick_ledger.py grade`) against final box scores / final scores and stores the results, so the pages read a
finished record instead of fetching box scores. Slates before Nov 21 have no ledger: their records stay as they were.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Sequence

KEY = "LEDGER:{kind}:{sport}:{day}"
SINCE = "2026-11-21"                     # the first slate with a ledger
STRONG_N = 15
PER_SPORT = 5                            # Nov 21: no one sport fills the list (the first earned list was 15 NCAAF Unders)
KEEP = ("sport", "kind", "pick", "player", "pid", "market", "side", "line", "price", "book", "chance", "money", "lock",
        "game", "time", "pickem_only", "edge", "use", "stake", "raw_chance", "earned", "earned_edge", "rule_v", "kind",
        # game lines
        "league", "game_id", "money_market", "money_side", "money_line", "money_score", "kickoff")


# --------------------------------------------------------------------------- storage
def _get(key, get=None):
    if get is None:
        import model_store as MS
        get = MS.get_setting
    try:
        return get(key, None) or {}
    except Exception:                                           # noqa: BLE001
        return {}


def _save(key, value, save=None) -> None:
    if save is None:
        import model_store as MS
        save = MS.save_setting
    try:
        save(key, value)
    except Exception:                                           # noqa: BLE001 -- the ledger is a bonus, never a failure
        pass


def row_key(r: Dict) -> str:
    if r.get("money_market"):
        return f"{r.get('game_id') or r.get('game')}|{r['money_market']}|{r.get('money_side')}"
    return f"{r.get('sport')}|{r.get('pid') or (r.get('player') or '').lower()}|{r.get('market')}|{r.get('side')}"


def load(kind: str, sport: str, day: str, get=None) -> Dict:
    """{"rows": {key: row}, "graded_at": iso or None}."""
    got = _get(KEY.format(kind=kind, sport=sport, day=day), get)
    return {"rows": dict(got.get("rows") or {}), "graded_at": got.get("graded_at")}


def rows(kind: str, sport: str, day: str, get=None) -> List[Dict]:
    return sorted(load(kind, sport, day, get)["rows"].values(), key=lambda r: r.get("first_seen") or "")


def add(kind: str, sport: str, day: str, new: Sequence[Dict], now: Optional[datetime] = None, get=None,
        save=None) -> int:
    """Adds the picks not already in the ledger (first sighting wins). Returns how many were new."""
    if not new:
        return 0
    now = now or datetime.now(timezone.utc)
    key = KEY.format(kind=kind, sport=sport, day=day)
    cur = _get(key, get)
    have = dict(cur.get("rows") or {})
    n = 0
    try:                                                        # Nov 21: the rule version in force (rules.py)
        import rules as _RU
        rv = _RU.version({"strong": "strong", "money": "money_props", "games": "money_games"}.get(kind, kind), day)
    except Exception:                                           # noqa: BLE001
        rv = None
    for r in new:
        k = row_key(r)
        if k in have:
            continue
        have[k] = dict({f: r.get(f) for f in KEEP if r.get(f) is not None}, first_seen=now.isoformat(timespec="seconds"),
                       rule_v=rv)
        n += 1
    if n:
        _save(key, dict(cur, rows=have), save)
    return n


# --------------------------------------------------------------------------- has the game started?
def _et():
    import pytz
    return pytz.timezone("US/Eastern")


def kick(day: str, time_txt: Optional[str]) -> Optional[datetime]:
    """"7:30 PM" on `day` (New York) as an aware datetime; times before 6 AM are the next morning's."""
    if not time_txt:
        return None
    try:
        t = datetime.strptime(str(time_txt).strip().upper(), "%I:%M %p").time()
    except ValueError:
        return None
    d = date.fromisoformat(day) + (timedelta(days=1) if t.hour < 6 else timedelta(0))
    return _et().localize(datetime.combine(d, t))


def started(day: str, r: Dict, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    k = None
    if r.get("kickoff"):
        try:
            k = datetime.fromisoformat(str(r["kickoff"]).replace("Z", "+00:00"))
            k = k if k.tzinfo else k.replace(tzinfo=timezone.utc)
        except ValueError:
            k = None
    k = k or kick(day, r.get("time"))
    if k is None:                                               # no time: only today's slate, never a past one
        return day < now.astimezone(_et()).date().isoformat()
    return now >= k


# --------------------------------------------------------------------------- recording
def record_props(sport: str, day: str, money_rows: Sequence[Dict], now: Optional[datetime] = None) -> int:
    """Every 💰 prop a board shows (todays_best.save_props), games not started."""
    import props_engine as PE
    out = []
    for r in money_rows or []:
        if not r.get("money") or started(day, r, now):
            continue
        ch = r.get("raw_chance") if r.get("raw_chance") is not None else r.get("chance")   # the 💰 rule's own chance
        out.append(dict(r, stake=PE.stake_units(ch, r.get("price"), day=day)
                        if r.get("price") is not None else None))
    return add("money", sport, day, out, now)


def strong_keys() -> List[str]:
    """The Command Center's sports: in season, with a props model, not a lab."""
    import sports
    return [s.key for s in sports.selectable_sports(True)
            if s.has_projections and s.key not in sports.LAB_SPORTS and sports.in_season(s.key)]


def earned_edge(r: Dict) -> Optional[float]:
    """Nov 21: how far the earned chance clears what the price needs (a pick'em line: its break-even), in points."""
    import props_money as PM
    e = r.get("earned")
    if e is None:
        return None
    need = PM.needed(r.get("price"), bool(r.get("pickem_only")) or r.get("price") is None)
    return None if need is None else float(e) - need


def strongest(picks: Sequence[Dict], n: int = STRONG_N) -> List[Dict]:
    """The Command Center's list. Nov 21 (owner: "proven edge A+"): ranked by EARNED edge -- the earned chance less
    what the price needs -- and only picks that clear it. Ranking by the model's raw chance picked out its biggest
    misses: Nov 20's top 15 averaged a 65% chance and went 7-8. Saved picks without an earned chance (before Nov 21)
    rank by chance, as before."""
    props = [r for r in picks if r.get("kind", "Prop") in ("Prop", "Game")]     # Nov 21: game-line 💰 too
    scored = [dict(r, earned_edge=earned_edge(r)) for r in props]
    if any(r["earned_edge"] is not None for r in scored):
        out, per = [], {}
        for r in sorted([r for r in scored if (r["earned_edge"] or 0) > 0], key=lambda r: -r["earned_edge"]):
            sp = r.get("sport")
            if per.get(sp, 0) >= PER_SPORT:
                continue
            per[sp] = per.get(sp, 0) + 1
            out.append(r)
        return out[:n]
    return sorted(props, key=lambda r: -(r.get("chance") or 0))[:n]


def game_candidates(day: str, rows_=None) -> List[Dict]:
    """Nov 21 (owner: "will these pages pull into the top 15 if there are things identified?"): game-line 💰 picks as
    strongest-list rows -- every league the Money Score has promoted to 💰 (money_score.MONEY_LEAGUES: college
    basketball today; International Hoops, Tennis and the rest join the day their record earns it). Their earned chance
    is the Money Score's chance; each row carries what the Bet Log needs to log it."""
    import hoops_games_page as HG
    if rows_ is None:
        import money_score as MSC
        import todays_best as TB
        rows_ = TB.winner_rows(day, leagues=list(MSC.MONEY_LEAGUES))
    out = []
    for r in rows_ or []:
        if not r.get("money") or not r.get("money_market") or r.get("money_price") is None:
            continue
        rec = r.get("_rec") or {}
        try:
            it = HG.side_item(r.get("_full") or {}, r["money_market"], r.get("money_side"), line=r.get("money_line"),
                              price=r.get("money_price")) or {}
        except Exception:                                       # noqa: BLE001
            it = {}
        out.append(dict(it, kind="Game", sport=r.get("sport"), pick=r.get("money_pick"), price=r.get("money_price"),
                        book=r.get("price_book") or "", chance=r.get("money_chance"), earned=r.get("money_chance"),
                        raw_chance=r.get("chance") if r.get("winner") and r.get("money_pick", "").startswith(
                            str(r.get("winner"))) else None,
                        money=True, game=r.get("game"), time=r.get("time"), game_id=rec.get("game_id"),
                        kickoff=rec.get("kickoff"), money_market=r["money_market"], money_side=r.get("money_side"),
                        money_line=r.get("money_line"), money_score=r.get("money_score")))
    return out


def record_strong(day: str, now: Optional[datetime] = None, keys: Optional[Sequence[str]] = None, load_props=None,
                  games=None) -> int:
    """The strongest-15 list as it stands now, every pick whose game is still to start."""
    if load_props is None:
        import todays_best as TB
        load_props = TB.load_props
    picks = []
    for k in keys if keys is not None else strong_keys():
        picks += [dict(r, sport=r.get("sport") or k) for r in (load_props(k, day) or {}).get("rows") or []]
    try:
        picks += game_candidates(day) if games is None else list(games)
    except Exception:                                           # noqa: BLE001 -- props still record
        pass
    return add("strong", "ALL", day, [r for r in strongest(picks) if not started(day, r, now)], now)


def record_games(day: str, rows_: Sequence[Dict], now: Optional[datetime] = None) -> int:
    """The game-line 💰 (todays_best.winner_rows with money=True), games not started, per sport."""
    import props_engine as PE
    by: Dict[str, List[Dict]] = {}
    for r in rows_ or []:
        if not r.get("money") or not r.get("money_market"):
            continue
        rec = r.get("_rec") or {}
        g = dict(r, game_id=rec.get("game_id"), kickoff=rec.get("kickoff"), pick=r.get("money_pick"),
                 price=r.get("money_price"), chance=r.get("money_chance"),
                 stake=PE.stake_units(r.get("money_chance"), r.get("money_price"), day=day)
                 if r.get("money_price") is not None else None)
        if started(day, g, now):
            continue
        by.setdefault(r.get("sport") or "?", []).append(g)
    return sum(add("games", sp, day, rs, now) for sp, rs in by.items())


# --------------------------------------------------------------------------- grading
def grade_prop(r: Dict, results: Dict, actuals_by_name: Optional[Dict] = None) -> Optional[str]:
    """win / loss / push from the engine's final box scores (by player id), else the kickoff snapshots' actuals."""
    import props_engine as PE
    import retro as R
    import pick_records as PRK
    if r.get("line") is None or r.get("side") not in ("Over", "Under"):
        return None
    pid = r.get("pid")
    a = None
    if pid is not None:
        a = results.get(pid)
        if a is None:
            try:
                a = results.get(int(pid))
            except (TypeError, ValueError):
                a = None
    if a is not None:
        res = R.settle_bet_result(r.get("market"), r["side"], PE.threshold(float(r["line"])), a)   # board lines: N = N+
        if res in ("win", "loss", "push"):
            return res
    if actuals_by_name:
        mk = PRK.COMBO_KEY.get(r.get("market"), r.get("market"))
        act = actuals_by_name.get((PE.norm_name(r.get("player") or ""), mk))
        if act is not None:
            thr = PE.threshold(float(r["line"]))
            if act == thr:
                return "push"
            return "win" if (act > thr) == (r["side"] == "Over") else "loss"
    return None


def prop_actuals(sport: str, day: str) -> Dict:
    """{(player, market): actual} from the day's kickoff snapshots graded by the Postgame Review."""
    import model_store as MS
    import pick_records as PRK
    import postgame as PG
    import props_engine as PE
    snaps = MS.load_snapshots(sport, [day])
    if not snaps:
        return {}
    res = PG.fetch_results(sport, day, sorted({(s["team"], s["opp"]) for s in snaps}))
    return {(PE.norm_name(g.get("player") or ""), PRK.COMBO_KEY.get(g.get("market"), g.get("market"))): g["actual"]
            for g in PG.grade(snaps, res) if g.get("actual") is not None}


def _sport_results(sport: str, day: str, cache: Dict) -> tuple:
    if sport not in cache:
        import sports
        res, act = {}, {}
        try:
            eng = sports.get(sport).engine
            res = eng.get_player_results(day) or {} if eng is not None and hasattr(eng, "get_player_results") else {}
        except Exception as exc:                                # noqa: BLE001
            print(f"  {sport} {day}: box scores failed ({type(exc).__name__}: {exc})")
        try:
            act = prop_actuals(sport, day)
        except Exception as exc:                                # noqa: BLE001
            print(f"  {sport} {day}: snapshot actuals failed ({type(exc).__name__}: {exc})")
        cache[sport] = (res, act)
    return cache[sport]


def grade_games(day: str, rows_: Sequence[Dict], recs: Optional[Dict] = None) -> None:
    import todays_best as TB
    if recs is None:
        recs = {}
        for r in TB.winner_rows(day, leagues=sorted({x.get("sport") for x in rows_ if x.get("sport")}), past=True):
            gid = (r.get("_rec") or {}).get("game_id")
            if gid is not None:
                recs[gid] = r.get("_full") or {}
    for r in rows_:
        p = recs.get(r.get("game_id"))
        if p:
            res = TB.grade_line(p, r.get("money_market"), r.get("money_side"), r.get("money_line"))
            if res:
                r["result"] = res


def grade_day(day: str, kinds=("money", "strong", "games"), sports_=None, get=None, save=None) -> Dict[str, str]:
    """Grades every ledger of `day` and stores the results. {ledger key: "w-l (ungraded u)"}."""
    out: Dict[str, str] = {}
    cache: Dict = {}
    sp_list = list(sports_ or ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB", "WNBA"))
    targets = [("strong", "ALL")] * ("strong" in kinds)
    targets += [("money", s) for s in sp_list] * ("money" in kinds)
    targets += [("games", s) for s in sp_list] * ("games" in kinds)
    for kind, sp in targets:
        key = KEY.format(kind=kind, sport=sp, day=day)
        cur = _get(key, get)
        rs = cur.get("rows") or {}
        if not rs or (cur.get("graded_at") and all(r.get("result") for r in rs.values())):
            continue                                            # nothing to grade, or already finished
        if kind == "games":
            grade_games(day, list(rs.values()))
        else:
            gm = [r for r in rs.values() if r.get("money_market")]          # Nov 21: game lines on the strong list
            if gm:
                grade_games(day, gm)
            for r in rs.values():
                if r.get("money_market"):
                    continue
                res, act = _sport_results(r.get("sport") or sp, day, cache)
                g = grade_prop(r, res, act)
                if g:
                    r["result"] = g
        cur = dict(cur, rows=rs, graded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        _save(key, cur, save)
        w = sum(r.get("result") == "win" for r in rs.values())
        l_ = sum(r.get("result") == "loss" for r in rs.values())
        u = sum(r.get("result") not in ("win", "loss", "push") for r in rs.values())
        out[key] = f"{w}-{l_} ({u} ungraded)"
    return out


# --------------------------------------------------------------------------- records
def record(kind: str, sport: str, day: str, get=None) -> Optional[Dict]:
    """{"hits", "misses", "units" ($1 a pick at the shown price), "needed", "n", "ungraded"} of a graded ledger, or
    None when the slate has no ledger or it hasn't been graded yet."""
    import props_engine as PE
    if day < SINCE:
        return None
    led = load(kind, sport, day, get)
    if not led["rows"] or not led["graded_at"]:
        return None
    hits = misses = ung = 0
    units = need = 0.0
    priced = 0
    for r in led["rows"].values():
        res = r.get("result")
        if res not in ("win", "loss"):
            ung += res not in ("push", "void")
            continue
        hits += res == "win"
        misses += res == "loss"
        d = PE.decimal(r.get("price")) if r.get("price") is not None else None
        if d:
            units += (d - 1) if res == "win" else -1.0
            need += 1 / d
            priced += 1
    n = hits + misses
    if not n:
        return None
    return {"hits": hits, "misses": misses, "units": units, "needed": need / priced if priced else None,
            "priced": priced, "n": n, "ungraded": ung}


# --------------------------------------------------------------------------- CLI
def main(argv: Optional[Sequence[str]] = None) -> int:
    import props_engine as PE
    argv = list(sys.argv[1:] if argv is None else argv)
    if (argv[0] if argv else "grade") == "grade":
        today = date.fromisoformat(PE._et_today())
        days = [argv[1]] if len(argv) > 1 else [(today - timedelta(days=k)).isoformat() for k in (1, 2, 3)]
        for d in days:
            for k, v in grade_day(d).items():
                print(f"{k}: {v}")
        return 0
    print("usage: python pick_ledger.py grade [YYYY-MM-DD]")
    return 2


if __name__ == "__main__":
    sys.exit(main())


def since_record(kind: str, sport: str, start: str, end: str, get=None) -> Optional[Dict]:
    """Nov 21 (rules.py): a ledger's record summed over slates start..end -- one rule version's own record."""
    d0, d1 = date.fromisoformat(max(start, SINCE)), date.fromisoformat(end)
    acc = {"hits": 0, "misses": 0, "units": 0.0, "need_sum": 0.0, "priced": 0, "slates": 0}
    while d0 <= d1:
        r = record(kind, sport, d0.isoformat(), get)
        if r:
            acc["hits"] += r["hits"]
            acc["misses"] += r["misses"]
            acc["units"] += r["units"]
            acc["need_sum"] += (r["needed"] or 0) * r["priced"]
            acc["priced"] += r["priced"]
            acc["slates"] += 1
        d0 += timedelta(days=1)
    n = acc["hits"] + acc["misses"]
    if not n:
        return None
    return dict(acc, n=n, hit_rate=acc["hits"] / n, needed=acc["need_sum"] / acc["priced"] if acc["priced"] else None,
                roi=acc["units"] / acc["priced"] if acc["priced"] else None)


def rule_records(end: str, sports_=("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"), get=None) -> List[Dict]:
    """Each current rule version's own record, from the day it started (rules.py): the strongest list, 💰 props and
    💰 game lines per sport."""
    import rules as RU
    out = []
    targets = [("strong", "ALL", "strong")] + [("money", s, "money_props") for s in sports_] + \
              [("games", s, "money_games") for s in sports_]
    for kind, sp, rule in targets:
        cur = RU.current(rule)
        r = since_record(kind, sp, cur["from"], end, get)
        if r:
            out.append(dict(r, kind=kind, sport=sp, rule=rule, v=cur["v"], since=cur["from"]))
    return out
