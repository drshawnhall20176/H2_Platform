"""
ticket_audit.py — the full pre-bet check for a sport's remaining games, as one tool (Nov 7).

Built after a night of doing it by hand: a ticket for the rest of the NBA slate was first assembled from a quick pass
that missed live prices, the Analyst Desk's angles and tonight's injury report -- and two of its legs had to come off
once those were checked (a lead player's read had changed; another's teammates were ruled out that day). This does all
of it, every time:

  1. the board's props-model reads for games that haven't started (older recent-games reads are left out),
  2. each game's logged scenario chances and the script-adjusted chance for every prop (script_effects),
  3. LIVE prices from every book (the odds feed's player-prop offers), the edge at DraftKings' live price,
  4. the Analyst Desk's angles for each prop (game-script and matchup evidence on, line history from the snapshots),
  5. today's injury report (ESPN): the player's own status, and rotation teammates ruled out AFTER the board was built
     (the model hasn't bumped for them yet) on an Under. Absences the model already knows aren't flagged: its Unders
     with a usage bump hit 55.7% vs 55.0% without news (research/under_with_absences.py) -- the raw effect is large
     (research/teammate_out_study.py: +6 to +12 points beat-own-average with 25+ rotation minutes out) but priced.
  6. a search over 4-5 leg tickets: one leg per player, at most two per game, the platform's own tags respected
     (🎯 Single only legs limited), every flagged leg excluded, ranked by edge at live prices.

Run:  python ticket_audit.py NBA          (or via the ticket-audit workflow)
"""
from __future__ import annotations

import itertools
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

import pytz

ET = pytz.timezone("US/Eastern")
ESPN_PATH = {"NBA": "basketball/nba", "WNBA": "basketball/wnba", "NCAAMB": "basketball/mens-college-basketball",
             "NHL": "hockey/nhl", "NFL": "football/nfl", "NCAAF": "football/college-football"}
ROTATION_MIN = 15.0          # a teammate ruled out matters from this many minutes a game (study: research/teammate_out_study)


# ---------------------------------------------------------------- live prices
def live_price(index: Dict, player: str, odds_market: Optional[str], side: str, line: float,
               book: str = "draftkings") -> Dict:
    """{"price", "line_now", "others"} for one prop from analyst.index_offers(offers). The odds feed groups offers by
    point: {"point", "over": {book: price}, "under": {book: price}}. price is None when `book` no longer offers this
    exact line; line_now is then the line it does offer."""
    import analyst as A
    rows = index.get((A._norm(player), odds_market)) or []
    sd = side.lower()
    same = [x for x in rows if x.get("point") is not None and float(x["point"]) == float(line)]
    price = next((x[sd][book] for x in same if book in (x.get(sd) or {})), None)
    lines = sorted({float(x["point"]) for x in rows if book in (x.get(sd) or {})})
    others = sorted(v for x in same for b, v in (x.get(sd) or {}).items() if b != book and v is not None)
    return {"price": price, "line_now": None if price is not None else (lines[0] if lines else None), "others": others}


# ---------------------------------------------------------------- injuries
def league_injuries(sport: str) -> Dict[str, Dict]:
    """{normalized player name: {"status", "team", "note"}} from ESPN's league injury report (empty on failure)."""
    import requests
    import props_engine as PE
    out: Dict[str, Dict] = {}
    path = ESPN_PATH.get(sport)
    if not path:
        return out
    try:
        j = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/injuries", timeout=20,
                         headers={"User-Agent": "Mozilla/5.0"}).json()
    except Exception:                                           # noqa: BLE001
        return out
    for t in j.get("injuries") or []:
        for it in t.get("injuries") or []:
            nm = (it.get("athlete") or {}).get("displayName") or ""
            out[PE.norm_name(nm)] = {"status": it.get("status") or "", "team": t.get("displayName") or "",
                                     "note": (it.get("shortComment") or "")[:140]}
    return out


def _tkey(team: Optional[str]) -> str:
    return (team or "").lower().split()[-1] if team else ""


def is_out(status: str) -> bool:
    return str(status).lower() in ("out", "doubtful")


def same_team(a: Optional[str], b: Optional[str]) -> bool:
    a, b = (a or "").lower(), (b or "").lower()
    return bool(a and b) and (a in b or b in a or a.split()[-1] == b.split()[-1])


# ---------------------------------------------------------------- the audit
def audit(sport: str, day: Optional[str] = None, lead_minutes: int = 10, deps: Optional[Dict] = None,
          plays: Optional[List[Dict]] = None, injuries: Optional[Dict] = None) -> List[Dict]:
    """Every props-model read for games starting more than lead_minutes from now, fully checked."""
    import analyst as A
    import analyst_publisher as AP
    import best_bets_data as BBD
    import components as C
    import line_history as LH
    import props_engine as PE
    import script_effects as SE
    import sports
    day = day or datetime.now(ET).strftime("%Y-%m-%d")
    cut = datetime.now(timezone.utc) + timedelta(minutes=lead_minutes)
    deps = deps or AP.default_deps()
    key = deps["api_key"]()
    if plays is None:
        plays, meta, _ = BBD.load_generic_best_bets_board(sport, day, BBD.O.DEFAULT_BOOK)
    else:
        meta = []
    pp = [p for p in plays if p.get("Model") == "player-props" and p.get("Side") in ("Over", "Under")
          and p.get("Line") is not None and p.get("ModelProb") is not None and p.get("LineSource") != "default"
          and (C._kick_dt(p.get("GameDate")) or cut) > cut]
    if not pp:
        return []
    SE.refresh(sport) if sport in SE.SPORTS else None
    offers = deps["fetch_offers"](sport, day, key) if key else []
    omap = sports.get(sport).market_map
    idx = A.index_offers(offers or [])
    try:
        game_env, _ = deps["game_env"](sport, day, meta, key)
        matchups, _ = deps["matchups"](sport, day)
    except Exception:                                           # noqa: BLE001
        game_env, matchups = {}, {}
    lidx = LH.sport_index(sport, (datetime.now(ET) - timedelta(days=14)).strftime("%Y-%m-%d"))
    calls = A.scan(pp, sport, day, offers=offers, odds_map=omap, history_fn=A.history_lookup(lidx, omap),
                   expect_book_lines=bool(offers), book="draftkings", game_env=game_env, matchups=matchups,
                   history_limit=len(pp))
    angles = {(PE.norm_name(c.get("player") or ""), c.get("market"), c.get("side")): A.angle_names(c) for c in calls}
    inj = injuries if injuries is not None else league_injuries(sport)
    # rotation minutes per player from the board's own game logs (who counts as a rotation teammate)
    mins = {}
    for p in plays:
        log = p.get("_game_log") or []
        m = [float(g.get("min") or 0) for g in log[-10:] if g.get("min") is not None]
        if m:
            mins[PE.norm_name(p.get("Player") or "")] = (sum(m) / len(m), p.get("Team"))
    # absences the model already knows about: the names in each team's usage-bump flags, and players the board has as out
    import re
    known_out: Dict[str, set] = defaultdict(set)
    for p in plays:
        for f in (p.get("Warnings") or []) + (p.get("Flags") or []):
            m = re.search(r"usage bump \((.+?) out\)", str(f))
            if m:
                for nm in m.group(1).split(","):
                    known_out[_tkey(p.get("Team"))].add(PE.norm_name(nm.strip()))
        if p.get("Out") or str(p.get("Status") or "").lower() == "out":
            known_out[_tkey(p.get("Team"))].add(PE.norm_name(p.get("Player") or ""))
    lines = SE.fetch_lines(sport, [day.replace("-", "")]) if sport in SE.SPORTS else []
    scen = SE.calls(sport) if sport in SE.SPORTS else {}
    out = []
    for p in pp:
        r = SE.from_play(p)
        sh, ch = None, None
        if sport in SE.SPORTS:
            teams = SE.game_teams([SE.from_play(q) for q in pp if q["Game"] == p["Game"]], p["Game"])
            g = SE.game_for(teams, lines)
            call = SE.scenario_call(sport, teams, day, scen)
            sh = dict(call["p"]) if call else SE.scenario_probs(sport, g["strength"] if g else None)[0]
            fav_names = SE.fav_names(g) if g else set()
            grp = SE.group(sport, r["market"], r.get("mins"))
            is_fav = bool(fav_names) and SE.team_matches(r.get("team"), fav_names)
            ch = SE.side_chance(SE.over_by_script(r["p_over"], grp if fav_names else None, is_fav, sh, sport), r["side"])
            chance = sum(sh[s] * ch[s] for s in SE.SCRIPTS)
        else:
            chance = p["ModelProb"]
        lp = live_price(idx, r["player"], omap.get(r["market"]), r["side"], r["line"])
        ev = chance * PE.decimal(lp["price"]) - 1 if lp["price"] is not None else None
        me = inj.get(PE.norm_name(r["player"]))
        mates_out = sorted(nm for nm, v in inj.items() if is_out(v["status"]) and same_team(v["team"], r.get("team"))
                           and nm != PE.norm_name(r["player"]) and (mins.get(nm, (0, None))[0] >= ROTATION_MIN))
        flags = []
        if me and str(me["status"]).lower() not in ("active",):
            flags.append(f"own status: {me['status']}")
        if lp["price"] is None:
            flags.append("no live price at this line" + (f" (now {lp['line_now']:g})" if lp["line_now"] is not None else ""))
        if r.get("lean") == "Check news":
            flags.append("check news")
        # Only absences the model hasn't seen. research/under_with_absences.py: model Unders with the model's own usage
        # bump applied hit 55.7% (playable 60.5%, n=124) vs 55.0% with no news -- the bump and the books price a known
        # absence. What can hurt an Under is a teammate ruled out AFTER the board was built (no bump for him yet).
        unseen = [nm for nm in mates_out if nm not in known_out.get(_tkey(r.get("team")), set())]
        if unseen and r["side"] == "Under":
            flags.append("teammate ruled out after the board was built: " + ", ".join(unseen[:3]) +
                         " — the model hasn't adjusted this Under yet")
        out.append({"game": p["Game"], "kick": p.get("GameDate"), "player": r["player"], "team": r.get("team"),
                    "market": r["market"], "side": r["side"], "line": r["line"], "board_price": p.get("RealPrice"),
                    "price": lp["price"], "others": lp["others"], "chance": chance, "by_script": ch, "scripts": sh,
                    "ev": ev, "use": p.get("Use") or "", "angles": angles.get((PE.norm_name(r["player"]), r["market"],
                                                                                r["side"]), []),
                    "mates_out": mates_out, "flags": flags})
    return out


def best_tickets(legs: Sequence[Dict], sizes=(4, 5), max_per_game: int = 2, max_single_only: int = 1,
                 top: int = 5) -> List[Dict]:
    """Tickets from playable, unflagged legs with an edge at the live price, ranked by edge. Same-game legs share
    their game's scenario chances (script_effects.ticket); games are independent."""
    import props_engine as PE
    import script_effects as SE
    play = {PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE}
    parlay_ok = {PE.USE_BOTH, PE.USE_PARLAY}
    pool = [x for x in legs if x["use"] in play and not x["flags"] and x["ev"] is not None and x["ev"] > 0]
    res = []
    for k in sizes:
        for combo in itertools.combinations(pool, k):
            if len({c["player"] for c in combo}) < k:
                continue
            per_game = defaultdict(list)
            for c in combo:
                per_game[c["game"]].append(c)
            if max(len(v) for v in per_game.values()) > max_per_game:
                continue
            singles = sum(1 for c in combo if c["use"] not in parlay_ok)
            if singles > max_single_only:
                continue
            p = 1.0
            for cs in per_game.values():
                if cs[0].get("by_script") and cs[0].get("scripts"):
                    p *= SE.ticket([c["by_script"] for c in cs], cs[0]["scripts"])[0]
                else:
                    for c in cs:
                        p *= c["chance"]
            dec = 1.0
            for c in combo:
                dec *= PE.decimal(c["price"])
            res.append({"legs": list(combo), "chance": p, "price": round((dec - 1) * 100), "ev": p * dec - 1,
                        "fair": SE.fair_american(p), "single_only": singles})
    res.sort(key=lambda r: -r["ev"])
    return res[:top]


def report(sport: str, day: Optional[str] = None) -> str:
    legs = audit(sport, day)
    import props_engine as PE
    play = {PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE}
    lines = [f"{sport}: {len(legs)} props-model reads in games not yet started"]
    for x in sorted([x for x in legs if x["use"] in play], key=lambda x: -(x["ev"] if x["ev"] is not None else -9)):
        lines.append(f"  {x['game'][:34]:34s} {x['player']:22s} {x['market']:12s} {x['side']:5s} {x['line']:g} | live "
                     f"{x['price']} | {x['chance']:.0%} | edge {('%+.1f%%' % (100 * x['ev'])) if x['ev'] is not None else '—'}"
                     f" | {x['use']} | angles {', '.join(x['angles']) or '—'} | {'; '.join(x['flags']) or 'clean'}")
    for size, max_s in (((4,), 0), ((4, 5), 1)):
        tix = best_tickets(legs, sizes=size, max_single_only=max_s)
        lines.append(f"\nBest tickets ({'parlay-tagged legs only' if max_s == 0 else 'at most one Single-only leg'}): "
                     f"{len(tix) or 'none'}")
        for t in tix[:3]:
            lines.append(f"  {len(t['legs'])} legs | chance {t['chance']:.1%} (fair {t['fair']:+d}) | live price product "
                         f"+{t['price']} | edge {t['ev']:+.0%}")
            for c in t["legs"]:
                lines.append(f"     {c['player']} {c['market']} {c['side']} {c['line']:g} @ {c['price']} ({c['chance']:.0%}, {c['use']})")
    return "\n".join(lines)


if __name__ == "__main__":
    for sp in (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SPORT", "NBA")).split(","):
        print(report(sp))
