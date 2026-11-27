"""
role_history.py -- on the player card: what tonight's defense has allowed to his role in its last few games (Nov 26).

Owner, Nov 26 ("build all 7", PropSeason pass 3): their Trends rows end with "VS NYJ, LAST 2 RUSH YDS · Wk11 Hampton 89 ·
Wk10 Cook 157" -- who held the same job against this defense lately, and what he did. Ours comes from the same
league-wide tables Soft Spots uses (soft_spots.load_league):
  * football: the slot (QB / RB1 / WR1 ...) he has held for his team lately, and the player who held that slot against
    tonight's defense in each of its last games, with his number in the card's stat;
  * NBA: his position group's top player in the card's stat against tonight's defense, from the league box scores;
  * college hoops: the group's combined number (the sample has no per-player lines).
Context, not a pick: the projection already counts the defense.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

STAT_OF_MARKET = {"pass yards": "pass_yds", "passing yards": "pass_yds", "passing tds": "pass_td", "pass tds": "pass_td",
                  "rush yards": "rush_yds", "rushing yards": "rush_yds", "rush attempts": "rush_att",
                  "receiving yards": "rec_yds", "receptions": "rec", "points": "pts", "rebounds": "reb",
                  "assists": "ast", "threes made": "fg3m", "3pm": "fg3m", "pra": "pra", "pts+reb+ast": "pra"}
WORD = {"pass_yds": "pass yds", "pass_td": "pass TDs", "rush_yds": "rush yds", "rush_att": "carries",
        "rec_yds": "rec yds", "rec": "catches", "pts": "pts", "reb": "reb", "ast": "ast", "fg3m": "threes", "pra": "PRA"}
N_GAMES = 3


def _norm(s) -> str:
    return " ".join(re.sub(r"[^a-z ]", " ", str(s or "").lower()).replace(" jr", "").split())


def stat_key(market: str) -> Optional[str]:
    return STAT_OF_MARKET.get(str(market or "").strip().lower())


def _val(stats: Dict, key: str) -> Optional[float]:
    if key == "pra":
        try:
            return float(stats.get("pts") or 0) + float(stats.get("reb") or 0) + float(stats.get("ast") or 0)
        except (TypeError, ValueError):
            return None
    v = stats.get(key)
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def his_slot(allowed: Dict, team, name: str) -> Optional[str]:
    """The slot he has held most for `team` lately (soft_spots.depth_from_allowed)."""
    import soft_spots as SS
    me = _norm(name)
    best = None
    for slot, lst in SS.depth_from_allowed(allowed, team, n=4, per_slot=3).items():
        for i, p in enumerate(lst):
            if _norm(p.get("name")) == me and (best is None or i < best[1]):
                best = (slot, i)
    return best[0] if best else None


def when(order, sport: str) -> str:
    if order is None:
        return ""
    if sport in ("NFL", "NCAAF"):
        return f"Wk{order}"
    s = str(order)[:10]
    try:
        from datetime import date
        d = date.fromisoformat(s)
        return f"{d:%b} {d.day}"
    except ValueError:
        return s


def football_rows(allowed: Dict, defense, slot: str, key: str, names: Dict, n: int = N_GAMES) -> List[Dict]:
    """The player who held `slot` against `defense` in each of its last n games, with his number."""
    out = []
    for g in (allowed.get(defense) or [])[:n]:
        who = ((g.get("who") or {}).get(slot) or [None])[0]
        # the slot's summed line IS his line for a one-man football slot
        v = _val((g.get("slots") or {}).get(slot) or {}, key)
        if who is None or v is None:
            continue
        out.append({"when": g.get("order"), "name": who, "value": v, "vs": g.get("offense")})
    return out


def nba_rows(pgames: List[Dict], defense, group: str, key: str, n: int = N_GAMES) -> List[Dict]:
    """The top player of his position group in the stat against `defense`, in each of its last n games."""
    import position_matchups as PM
    games: Dict = {}
    for p in pgames or []:
        if p.get("opp") == defense and PM.position_group(p.get("pos")) == group:
            v = _val(p.get("stats") or {}, key)
            if v is not None:
                games.setdefault((p.get("order"), p.get("game")), []).append((v, p.get("name"), p.get("team")))
    out = []
    for (order, _), lst in sorted(games.items(), key=lambda x: str(x[0][0]), reverse=True)[:n]:
        v, name, team = max(lst, key=lambda t: t[0])
        out.append({"when": order, "name": name, "value": v, "vs": team})
    return out


def for_player(sport: str, data: Dict, name: str, team_label: str, game: str, market: str) -> Optional[Dict]:
    """{"slot", "stat", "defense", "rows"} for the card, or None when the role or the stat can't be read."""
    import position_matchups as PM
    import soft_spots as SS
    key = stat_key(market)
    if not key or " @ " not in str(game or "") or not data.get("allowed"):
        return None
    away, home = [x.strip() for x in str(game).split(" @ ", 1)]
    x = SS.match_game(sport, data.get("games") or [], away, home)
    if not x:
        return None
    t = _norm(team_label)
    home_keys = {_norm(x.get("home")), _norm(x.get("home_abbr")), _norm(home)}
    mine, opp = ((x["home_id"], x["away_id"]) if t in home_keys or any(k and (k.endswith(" " + t) or t.endswith(" " + k))
                                                                         for k in home_keys)
                 else (x["away_id"], x["home_id"]))
    names = dict(data.get("names") or {})
    opp_name = away if opp == x["away_id"] else home
    allowed = data["allowed"]
    if SS.family(sport) == "football":
        slot = his_slot(allowed, mine, name)
        if not slot or key not in ("pass_yds", "pass_td", "rush_yds", "rush_att", "rec_yds", "rec"):
            return None
        rows = football_rows(allowed, opp, slot, key, names)
        label = SS.FOOTBALL_SLOTS.get(slot, slot)
    else:
        slot = his_slot(allowed, mine, name)
        if not slot:
            return None
        rows = nba_rows(data.get("pgames") or [], opp, slot, key) if sport == "NBA" and data.get("pgames") else []
        if not rows:
            rows = [{"when": g.get("order"), "name": f"{SS.SLOT_NAME.get(slot, slot)} combined",
                     "value": _val((g.get("slots") or {}).get(slot) or {}, key), "vs": g.get("offense")}
                    for g in (allowed.get(opp) or [])[:N_GAMES]]
            rows = [r for r in rows if r["value"] is not None]
        label = SS.SLOT_NAME.get(slot, slot)
    if not rows:
        return None
    for r in rows:
        r["vs"] = names.get(r["vs"], r["vs"])
    return {"slot": slot, "label": label, "stat": key, "defense": opp_name, "rows": rows}


# --------------------------------------------------------------------------- the matchup grade (Nov 27)
# Owner build list (PropSeason's matchup letter beside every prop): how much tonight's defense gives up in the pick's
# stat to the player's role, as soft_spots' A+ ... F (A+ = gives up the most). A description of the matchup, not a
# chance -- the projection already counts the defense.
def matchup_grade(sport: str, data: Dict, name: str, team_label: str, game: str, market: str,
                  tables: Optional[Dict] = None) -> Optional[Dict]:
    """{"grade", "rank", "of", "label", "stat"} or None when the role, the stat or the defense can't be read.
    `tables`: a dict reused across calls (stat -> soft_spots.table_any), so a whole board is one pass."""
    import soft_spots as SS
    key = stat_key(market)
    if not key or " @ " not in str(game or "") or not data.get("allowed") or not data.get("summary"):
        return None
    away, home = [x.strip() for x in str(game).split(" @ ", 1)]
    x = SS.match_game(sport, data.get("games") or [], away, home)
    if not x:
        return None
    t = _norm(team_label)
    home_keys = {_norm(x.get("home")), _norm(x.get("home_abbr")), _norm(home)}
    is_home = t in home_keys or any(k and (k.endswith(" " + t) or t.endswith(" " + k)) for k in home_keys)
    mine, opp = (x["home_id"], x["away_id"]) if is_home else (x["away_id"], x["home_id"])
    slot = his_slot(data["allowed"], mine, name)
    if not slot:
        return None
    tables = {} if tables is None else tables
    if key not in tables:
        tables[key] = SS.table_any(data["summary"], key, tuple(SS.slots_for(sport)), min_teams=8)
    tb = tables[key].get(slot) or {}
    rec = tb.get(opp)
    if not rec:
        return None
    label = SS.slots_for(sport).get(slot, slot)
    return {"grade": SS.letter(rec[1], len(tb)), "rank": rec[1], "of": len(tb), "label": label, "stat": key}


def grade_text(g: Optional[Dict]) -> str:
    if not g:
        return "—"
    return f"{g['grade']} · {SSord(g['rank'])} most of {g['of']} to {g['label']}"


def SSord(n: int) -> str:                                       # noqa: N802
    return f"{n}{'tsnrhtdd'[(n // 10 % 10 != 1) * (n % 10 < 4) * n % 10::4]}"


def text(h: Dict, sport: str) -> str:
    bits = [f"{when(r['when'], sport)} {r['name']} {r['value']:g}" + (f" ({r['vs']})" if r.get("vs") else "")
            for r in h["rows"]]
    return (f"**vs {h['defense']}, recent {h['label']} — {WORD.get(h['stat'], h['stat'])}:** " + " · ".join(bits))


def render(p: Dict, sport: str, day: Optional[str] = None) -> None:
    import soft_spots as SS
    if sport not in SS.SPORTS:
        return
    import streamlit as st
    from datetime import datetime
    import pytz
    d = str(day or p.get("_day") or datetime.now(pytz.timezone("US/Eastern")).date())[:10]
    h = for_player(sport, SS.cached_league(sport, d), p.get("Player") or "", p.get("Team") or "", p.get("Game") or "",
                   p.get("Market") or "")
    if not h:
        return
    st.markdown(text(h, sport))
    st.caption("Who held the same job against this defense in its last games, and what he did. Context, not a pick — "
               "the projection already counts the defense.")
