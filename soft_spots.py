"""
soft_spots.py — tonight's softest defense-vs-position spots, NBA (Nov 25, second PropSeason pass).

PropSeason's Cheat Sheet lists the defenses that give up the most to a position and the players who line up there --
"context, not a call". H2's version keeps the context and adds what they don't have: each player's H2 pick on
tonight's board (if any) with its earned chance and Bet? verdict, so a soft spot never reads as a pick by itself.

The numbers come from the same league sample Position Matchups uses (position_data.load_bundle): every NBA defense's
average allowed per game to guards / forwards / centers over its recent games, ranked 1 (gives up the most) to 30.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

STATS = {"pts": "points", "reb": "rebounds", "ast": "assists", "fg3m": "threes"}
SLOT_NAME = {"G": "guards", "F": "forwards", "C": "centers"}
SOFT_PCT = 0.10          # at least 10% above the league average
MIN_GAMES = 3


def table(summary: Dict, stat: str) -> Dict[str, Dict[str, Tuple[float, int, float]]]:
    """{slot: {defense: (allowed per game, rank 1 = most, % above league average)}} for one stat, defenses with
    MIN_GAMES+ games."""
    out: Dict[str, Dict] = {}
    for slot in SLOT_NAME:
        rows = [(d, float((s.get(slot) or {}).get("stats", {}).get(stat) or 0.0))
                for d, s in summary.items() if (s.get(slot) or {}).get("games", 0) >= MIN_GAMES]
        if len(rows) < 5:
            continue
        avg = sum(v for _, v in rows) / len(rows)
        rows.sort(key=lambda r: (-r[1], str(r[0])))
        out[slot] = {d: (v, i + 1, (v / avg - 1) if avg else 0.0) for i, (d, v) in enumerate(rows)}
    return out


def spots(summary: Dict, tonight: Sequence[Tuple], depth_of: Callable, names: Dict,
          stats: Sequence[str] = tuple(STATS), slots: Sequence[str] = tuple(SLOT_NAME)) -> List[Dict]:
    """Tonight's soft spots, softest first. `tonight`: [(defense id, offense id, game label, time)]. `depth_of(team)`
    -> {slot: [{"name", "avg_min", ...}]} (most minutes first)."""
    out = []
    for st in stats:
        tb = table(summary, st)
        for de, off, label, when in tonight:
            for slot in slots:
                rec = (tb.get(slot) or {}).get(de)
                if not rec or rec[2] < SOFT_PCT:
                    continue
                try:
                    players = [p for p in (depth_of(off) or {}).get(slot) or [] if (p.get("avg_min") or 0) >= 10][:4]
                except Exception:                               # noqa: BLE001
                    players = []
                out.append({"defense": names.get(de, de), "offense": names.get(off, off), "slot": slot, "stat": st,
                            "allowed": rec[0], "rank": rec[1], "pct": rec[2], "of": len(tb[slot]), "game": label,
                            "time": when, "players": players})
    return sorted(out, key=lambda s: -s["pct"])


def ordinal(n: int) -> str:
    return "most" if n == 1 else f"{n}{'tsnrhtdd'[(n // 10 % 10 != 1) * (n % 10 < 4) * n % 10::4]} most"


def headline(s: Dict) -> str:
    return (f"{s['defense']} allows the {ordinal(s['rank'])} {STATS[s['stat']]} to {SLOT_NAME[s['slot']]} "
            f"({s['allowed']:.1f} a game, {s['pct']:+.0%} vs the average defense, of {s['of']} teams)")


def pick_for(name: str, rows: Sequence[Dict], stat: Optional[str] = None) -> Optional[Dict]:
    """The player's H2 pick on tonight's board: the one in this stat when there is one, else his strongest."""
    import re
    key = re.sub(r"[^a-z]", "", str(name or "").lower())
    mine = [r for r in rows or [] if r.get("kind") == "Prop"
            and re.sub(r"[^a-z]", "", str(r.get("player") or "").lower()) == key]
    if not mine:
        return None
    word = {"pts": "point", "reb": "rebound", "ast": "assist", "fg3m": "three"}.get(stat or "", "")
    same = [r for r in mine if word and word in str(r.get("market") or "").lower()]
    return max(same or mine, key=lambda r: r.get("chance") or 0)


# --------------------------------------------------------------------------- every sport (Nov 26, owner: "build all 7")
# Football and college basketball join the NBA: the same allowed-per-slot tables Position Matchups builds, ranked per
# stat. NHL is left out: our hockey sample is the two teams' last 10 games, so there is no league-wide ranking to make.
FOOTBALL_STATS = {"pass_yds": "passing yards", "pass_td": "passing TDs", "rush_yds": "rushing yards",
                  "rush_td": "rushing TDs", "rec": "receptions", "rec_yds": "receiving yards", "rec_td": "receiving TDs"}
FOOTBALL_SLOTS = {"QB": "QBs", "RB1": "lead RBs", "RB2": "backup RBs", "WR1": "WR1s", "WR2": "WR2s", "WR3": "WR3s",
                  "TE1": "tight ends"}
FOOTBALL_STAT_SLOTS = {"QB": ("pass_yds", "pass_td", "rush_yds"),
                       "RB1": ("rush_yds", "rush_td", "rec", "rec_yds"), "RB2": ("rush_yds", "rec"),
                       "WR1": ("rec", "rec_yds", "rec_td"), "WR2": ("rec", "rec_yds", "rec_td"),
                       "WR3": ("rec", "rec_yds"), "TE1": ("rec", "rec_yds", "rec_td")}
SPORTS = ("NFL", "NCAAF", "NBA", "NCAAMB")


def family(sport: str) -> str:
    return "football" if sport in ("NFL", "NCAAF") else "basketball"


def stats_for(sport: str) -> Dict[str, str]:
    return FOOTBALL_STATS if family(sport) == "football" else STATS


def slots_for(sport: str) -> Dict[str, str]:
    return FOOTBALL_SLOTS if family(sport) == "football" else SLOT_NAME


def pairs_for(sport: str, stats: Optional[Sequence[str]] = None, slots: Optional[Sequence[str]] = None):
    """The (slot, stat) pairs worth ranking: football's by role (no QB receptions), basketball's every pair."""
    out = []
    for slot in slots or slots_for(sport):
        allowed = FOOTBALL_STAT_SLOTS.get(slot) if family(sport) == "football" else tuple(STATS)
        out += [(slot, st) for st in (allowed or ()) if stats is None or st in stats]
    return out


def table_any(summary: Dict, stat: str, slots: Sequence[str], min_teams: int = 5) -> Dict[str, Dict]:
    """table() for any sport's slots."""
    out: Dict[str, Dict] = {}
    for slot in slots:
        rows = [(d, float((s.get(slot) or {}).get("stats", {}).get(stat) or 0.0))
                for d, s in summary.items() if (s.get(slot) or {}).get("games", 0) >= MIN_GAMES]
        if len(rows) < min_teams:
            continue
        avg = sum(v for _, v in rows) / len(rows)
        rows.sort(key=lambda r: (-r[1], str(r[0])))
        out[slot] = {d: (v, i + 1, (v / avg - 1) if avg else 0.0) for i, (d, v) in enumerate(rows)}
    return out


def top_cut(n_teams: int) -> int:
    """How high a rank counts as a soft spot: the top sixth of the league (5 of 32 NFL, 5 of 30 NBA, ~22 of 134
    college teams), never fewer than 3."""
    return max(3, round(n_teams / 6))


def letter(rank: int, of: int) -> str:
    """A friendly A-F label from the rank (1 = gives up the most = A+). A description of the matchup, not a chance."""
    p = (rank - 1) / max(1, of - 1)
    for cut, g in ((0.04, "A+"), (0.10, "A"), (0.17, "A-"), (0.25, "B+"), (0.35, "B"), (0.45, "B-"), (0.55, "C+"),
                   (0.65, "C"), (0.75, "C-"), (0.85, "D"), (1.01, "F")):
        if p <= cut:
            return g
    return "F"


def spots_any(sport: str, summary: Dict, tonight: Sequence[Tuple], depth_of: Callable, names: Dict,
              stats: Optional[Sequence[str]] = None, slots: Optional[Sequence[str]] = None) -> List[Dict]:
    """spots() for any sport: soft = ranked in the top_cut AND 10%+ above the average defense. Softest first."""
    fam = family(sport)
    pairs = pairs_for(sport, stats, slots)
    tables = {st: table_any(summary, st, tuple(slots_for(sport)), min_teams=8) for st in {p[1] for p in pairs}}
    out = []
    for de, off, label, when in tonight:
        for slot, st in pairs:
            tb = tables[st].get(slot) or {}
            rec = tb.get(de)
            if not rec or rec[2] < SOFT_PCT or rec[1] > top_cut(len(tb)):
                continue
            try:
                lst = (depth_of(off) or {}).get(slot) or []
            except Exception:                                   # noqa: BLE001
                lst = []
            players = ([p for p in lst if p.get("avg_min") is None or p["avg_min"] >= 10][:4] if fam == "basketball"
                       else lst[:1])
            out.append({"defense": names.get(de, de), "offense": names.get(off, off), "slot": slot, "stat": st,
                        "allowed": rec[0], "rank": rec[1], "pct": rec[2], "of": len(tb), "game": label, "time": when,
                        "players": players, "grade": letter(rec[1], len(tb)), "sport": sport})
    return sorted(out, key=lambda s: (s["rank"], -s["pct"]))


def headline_any(s: Dict) -> str:
    sport = s.get("sport") or "NBA"
    return (f"{s['defense']} allows the {ordinal(s['rank'])} {stats_for(sport)[s['stat']]} to "
            f"{slots_for(sport)[s['slot']]} ({s['allowed']:.1f} a game, {s['pct']:+.0%} vs the average defense, "
            f"of {s['of']} teams)")


def card_lines(spots_: Sequence[Dict], per_defense: int = 4) -> Dict[str, List[str]]:
    """The game card's box: {defense: [one plain line per soft spot, with who lines up there]}."""
    out: Dict[str, List[str]] = {}
    for s in spots_:
        lst = out.setdefault(s["defense"], [])
        if len(lst) >= per_defense:
            continue
        who = ", ".join(p.get("name") for p in s["players"] if p.get("name"))
        sport = s.get("sport") or "NBA"
        lst.append(f"**{s['grade']}** · {ordinal(s['rank'])} {stats_for(sport)[s['stat']]} to "
                   f"{slots_for(sport)[s['slot']]} ({s['allowed']:.1f} a game)" + (f" → **{who}**" if who else ""))
    return out


def depth_from_allowed(allowed: Dict, team, n: int = 4, per_slot: int = 3) -> Dict[str, List[Dict]]:
    """Who has held each slot for `team` lately, from the allowed tables' own box scores: the names most often at
    the top of the slot over the team's last `n` games (ties: the most recent game first)."""
    games = sorted((g for lst in (allowed or {}).values() for g in lst if g.get("offense") == team),
                   key=lambda g: (g.get("order") is None, g.get("order")), reverse=True)[:n]
    out: Dict[str, List[Dict]] = {}
    for slot in {k for g in games for k in (g.get("who") or {})}:
        score: Dict[str, float] = {}
        for i, g in enumerate(games):
            for j, name in enumerate((g.get("who") or {}).get(slot) or []):
                score[name] = score.get(name, 0.0) + (1.0 if j == 0 else 0.3) + (n - i) * 0.01
        out[slot] = [{"name": nm, "avg_min": None} for nm, _ in sorted(score.items(), key=lambda x: -x[1])[:per_slot]]
    return out


def load_league(sport: str, day: str) -> Dict:
    """{"games", "summary", "allowed", "names", "pgames"} for the sport's slate on `day`: one bundle's league-wide
    allowed tables (they don't depend on which game the bundle was built for)."""
    import position_data as PD
    import position_matchups as PM
    games = PD.list_games(sport, day)
    if not games:
        return {"games": []}
    b = PD.load_bundle(sport, day, games[0], False)
    allowed = b.get("allowed") or {}
    return {"games": games, "summary": PM.summarize(allowed, sport), "allowed": allowed,
            "names": b.get("all_names") or {}, "pgames": (b.get("props") or {}).get("pgames") or []}


PROMOTE = {"RB2": ("RB1",), "WR2": ("WR1",), "WR3": ("WR1", "WR2")}


def without_out(depth: Dict[str, List[Dict]], out: set, norm: Callable = None) -> Dict[str, List[Dict]]:
    """Nov 26 (live check: Kenneth Walker III out, Emmett Johnson shown as the 'backup' RB): players ruled out leave
    every slot and the next man moves up; a player now leading a higher slot isn't also listed in the lower one."""
    import re
    norm = norm or (lambda s: re.sub(r"[^a-z]", "", str(s or "").lower()))
    gone = {norm(n) for n in out or ()}
    d = {slot: [p for p in lst if norm(p.get("name")) not in gone] for slot, lst in (depth or {}).items()}
    for slot, above in PROMOTE.items():
        tops = {norm((d.get(a) or [{}])[0].get("name")) for a in above if d.get(a)}
        if slot in d:
            d[slot] = [p for p in d[slot] if norm(p.get("name")) not in tops]
    return d


def depth_fn(sport: str, data: Dict, out: Optional[set] = None) -> Callable:
    """depth_of(team) for spots_any: the NBA's minutes-based rotation when the props sample has it, else the slot
    holders from the allowed tables -- minus anyone ruled out tonight (`out`: player names)."""
    import position_matchups as PM
    cache: Dict = {}

    def depth_of(team):
        if team not in cache:
            d = {}
            if sport == "NBA" and data.get("pgames"):
                d = PM.usage_depth(data["pgames"], team, "NBA", last_n=10)
            d = d or depth_from_allowed(data.get("allowed") or {}, team)
            cache[team] = without_out(d, out or set()) if out else d
        return cache[team]
    return depth_of


def out_tonight(sport: str, day: str) -> set:
    """Names ruled out on ESPN's injury report (today's games only)."""
    try:
        import injury_check as IC
        if not IC.live_for(day):
            return set()
        return {e["name"] for e in IC.entries(sport) if e.get("status") == "out"}
    except Exception:                                           # noqa: BLE001
        return set()


def tonight_pairs(games: Sequence[Dict]) -> List[Tuple]:
    """[(defense key, offense key, game label, time)] -- both directions of every game."""
    out = []
    for g in games:
        when = str(g.get("label") or "")
        lab = f"{g.get('away')} @ {g.get('home')}"
        out += [(g["home_id"], g["away_id"], lab, when), (g["away_id"], g["home_id"], lab, when)]
    return out


def match_game(sport: str, games: Sequence[Dict], away: str, home: str) -> Optional[Dict]:
    """The schedule entry for a card's matchup: full names, short names or (NFL) abbreviations."""
    import re

    def norm(x):
        return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(x or "").lower()).split())

    def names(g, side):
        out = {norm(g.get(side)), norm(g.get(f"{side}_abbr"))}
        if sport == "NFL":
            try:
                import position_lines as PL
                out.add(norm(PL.NFL_TEAMS.get(str(g.get(side)))))
            except Exception:                                   # noqa: BLE001
                pass
        return out - {""}

    def hit(card, keys):
        c = norm(card)
        return bool(c) and any(c == k or c.startswith(k + " ") or k.startswith(c + " ") or c.endswith(" " + k)
                               for k in keys)
    return next((g for g in games or [] if hit(home, names(g, "home")) and hit(away, names(g, "away"))), None)


_league_cache = None


def cached_league(sport: str, day: str) -> Dict:
    """load_league, cached 30 minutes and shared by every card and page that needs it."""
    global _league_cache
    import streamlit as st
    if _league_cache is None:
        _league_cache = st.cache_data(ttl=1800, show_spinner="Reading the league's defenses…", max_entries=8)(
            lambda sp, d: load_league(sp, d))
    return _league_cache(sport, str(day)[:10])
