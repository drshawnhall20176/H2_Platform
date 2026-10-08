"""
position_matchups.py — depth-chart position vs opposing defense, and team head-to-head.

PURE LOGIC, NO NETWORK. Every function takes plain lists/dicts and returns plain lists/dicts so the
whole thing is testable with synthetic data; position_data.py owns the per-sport loading.

THE IDEA (the standard "defense vs position" method, adapted per sport):
  * Every game, each offense's players are sorted into SLOTS by how they were actually used that day.
      Football : QB, RB1, RB2, WR1, WR2, WR3, TE1   (RB by carries, WR/TE by targets — receptions /
                 receiving yards when a data source has no targets, as in the NCAAF cache)
      Basketball: G, F, C                            (position group from the roster; every player in
                 the group counts, since rotations differ game to game)
  * What a defense ALLOWED to each slot in each game is summed, then averaged over the games it has
    played, and every defense is ranked per slot (rank 1 = allows the MOST = the softest matchup).
  * A team's depth chart (its starter per slot) is then lined up against the opposing defense's rank
    at that slot.

HONEST LIMITS (the page repeats these): a slot is defined by usage, so "WR1" is the receiver who was
targeted most in that game, not necessarily the one listed first on a depth chart; early-season
samples are thin (the table shows the game count and the page flags < 3 games); college football has
no published depth-chart feed here, so its depth is the usage ranking over recent games.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

FOOTBALL_SLOTS: Tuple[str, ...] = ("QB", "RB1", "RB2", "WR1", "WR2", "WR3", "TE1")
BASKETBALL_SLOTS: Tuple[str, ...] = ("G", "F", "C")
SLOTS_BY_SPORT: Dict[str, Tuple[str, ...]] = {
    "NFL": FOOTBALL_SLOTS, "NCAAF": FOOTBALL_SLOTS, "NBA": BASKETBALL_SLOTS, "NCAAMB": BASKETBALL_SLOTS}
FAMILY_BY_SPORT: Dict[str, str] = {"NFL": "football", "NCAAF": "football", "NBA": "basketball", "NCAAMB": "basketball"}
SUPPORTED_SPORTS: Tuple[str, ...] = tuple(SLOTS_BY_SPORT)

METRIC_LABEL = {"football": "PPR-style fantasy points", "basketball": "points + rebounds + assists"}
SLOT_LABEL = {"QB": "Quarterback", "RB1": "Running back 1", "RB2": "Running back 2", "WR1": "Wide receiver 1",
              "WR2": "Wide receiver 2", "WR3": "Wide receiver 3", "TE1": "Tight end 1",
              "G": "Guards", "F": "Forwards", "C": "Centers"}

# The stat lines shown next to the headline metric for each slot (key, short label).
SLOT_STATS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "QB": (("pass_yds", "pass yds"), ("pass_td", "pass TD"), ("rush_yds", "rush yds")),
    "RB1": (("rush_yds", "rush yds"), ("rec", "rec"), ("rush_td", "rush TD")),
    "RB2": (("rush_yds", "rush yds"), ("rec", "rec"), ("rush_td", "rush TD")),
    "WR1": (("rec", "rec"), ("rec_yds", "rec yds"), ("rec_td", "rec TD")),
    "WR2": (("rec", "rec"), ("rec_yds", "rec yds"), ("rec_td", "rec TD")),
    "WR3": (("rec", "rec"), ("rec_yds", "rec yds"), ("rec_td", "rec TD")),
    "TE1": (("rec", "rec"), ("rec_yds", "rec yds"), ("rec_td", "rec TD")),
    "G": (("pts", "pts"), ("reb", "reb"), ("ast", "ast"), ("fg3m", "3PM")),
    "F": (("pts", "pts"), ("reb", "reb"), ("ast", "ast"), ("fg3m", "3PM")),
    "C": (("pts", "pts"), ("reb", "reb"), ("ast", "ast"), ("fg3m", "3PM")),
}

THIN_SAMPLE_GAMES = 3          # a defense with fewer games than this at a slot is flagged as a thin sample
MIN_GAMES_FOR_RANK = 3         # a defense needs this many games at a slot to be ranked at all
MIN_TEAMS_FOR_RANK = 8         # below this many ranked defenses a rank / tier / league average means nothing
TREND_PCT = 15.0               # recent window must differ from the season by this much to call a trend
RECENT_N = 4                   # the "lately" window, in games


def _num(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(v) or math.isinf(v) else v


# --------------------------------------------------------------------------- the headline metric
def football_points(s: Dict) -> float:
    """PPR-style fantasy points from a normalized football stat line — one number that lets a QB, a
    back and a receiver each be compared against a defense's league average at their own slot."""
    return (0.04 * _num(s.get("pass_yds")) + 4.0 * _num(s.get("pass_td")) - 2.0 * _num(s.get("pass_int"))
            + 0.1 * (_num(s.get("rush_yds")) + _num(s.get("rec_yds")))
            + 6.0 * (_num(s.get("rush_td")) + _num(s.get("rec_td"))) + _num(s.get("rec")))


def basketball_pra(s: Dict) -> float:
    return _num(s.get("pts")) + _num(s.get("reb")) + _num(s.get("ast"))


def metric_value(sport: str, stats: Dict) -> float:
    return football_points(stats) if FAMILY_BY_SPORT.get(sport) == "football" else basketball_pra(stats)


# --------------------------------------------------------------------------- slot assignment
_RB_POS = {"RB", "FB", "HB"}


def _usage_football(p: Dict, kind: str) -> Tuple:
    s = p.get("stats") or {}
    if kind == "QB":
        return (_num(s.get("pass_att")), _num(s.get("pass_yds")))
    if kind == "RB":
        return (_num(s.get("rush_att")), _num(s.get("rec")), _num(s.get("rush_yds")))
    # receivers: targets when the source has them, otherwise receptions then yards
    return (_num(s.get("tgt")), _num(s.get("rec")), _num(s.get("rec_yds")))


def assign_football_slots(players: Iterable[Dict]) -> Dict[str, List[Dict]]:
    """One team's player-game lines for ONE game -> {slot: [player-game]}. A player with no usage at
    all (nothing thrown, carried, caught or targeted) holds no slot."""
    pool = list(players or [])

    def ranked(posset, kind):
        group = [p for p in pool if str(p.get("pos") or "").upper() in posset]
        group = [p for p in group if any(v > 0 for v in _usage_football(p, kind))]
        return sorted(group, key=lambda p: _usage_football(p, kind), reverse=True)

    out: Dict[str, List[Dict]] = {}
    qbs, rbs, wrs, tes = ranked({"QB"}, "QB"), ranked(_RB_POS, "RB"), ranked({"WR"}, "WR"), ranked({"TE"}, "TE")
    if qbs:
        out["QB"] = [qbs[0]]
    for i, slot in enumerate(("RB1", "RB2")):
        if len(rbs) > i:
            out[slot] = [rbs[i]]
    for i, slot in enumerate(("WR1", "WR2", "WR3")):
        if len(wrs) > i:
            out[slot] = [wrs[i]]
    if tes:
        out["TE1"] = [tes[0]]
    return out


_G_TOKENS = {"G", "PG", "SG"}
_F_TOKENS = {"F", "SF", "PF"}


def position_group(abbr) -> Optional[str]:
    """Basketball position abbreviation -> 'G' / 'F' / 'C', or None when it can't be read. Hybrid
    labels go to the position they list FIRST (G-F -> G, F-C -> F, C-F -> C), which is how ESPN
    orders a player's main spot."""
    if abbr is None:
        return None
    text = str(abbr).upper().strip()
    if not text or text == "NAN":
        return None
    first = text.replace("/", "-").split("-")[0].strip()
    if first in _G_TOKENS:
        return "G"
    if first in _F_TOKENS:
        return "F"
    if first == "C":
        return "C"
    return None


def assign_basketball_slots(players: Iterable[Dict]) -> Dict[str, List[Dict]]:
    """One team's player-game lines for ONE game -> {G/F/C: [every player of that group who played]}.
    The group's total is what a defense allowed to that position."""
    out: Dict[str, List[Dict]] = {}
    for p in players or []:
        grp = position_group(p.get("pos"))
        if grp is None:
            continue
        s = p.get("stats") or {}
        if _num(s.get("min")) <= 0 and not any(_num(s.get(k)) for k in ("pts", "reb", "ast", "fg3m")):
            continue                                   # DNP lines
        out.setdefault(grp, []).append(p)
    return out


def assigner_for(sport: str) -> Callable[[Iterable[Dict]], Dict[str, List[Dict]]]:
    return assign_football_slots if FAMILY_BY_SPORT.get(sport) == "football" else assign_basketball_slots


# --------------------------------------------------------------------------- what defenses allowed
def _sum_stats(players: Sequence[Dict]) -> Dict[str, float]:
    tot: Dict[str, float] = {}
    for p in players:
        for k, v in (p.get("stats") or {}).items():
            tot[k] = tot.get(k, 0.0) + _num(v)
    return tot


def allowed_by_slot(pgames: Iterable[Dict], sport: str) -> Dict[str, List[Dict]]:
    """Player-game lines -> {defense: [{"game", "order", "offense", "slots": {slot: summed stats}}]}.

    Each pgame: {"game", "order", "team", "opp", "pid", "name", "pos", "stats": {...}}. Lines are
    grouped per (game, offense team); the offense's slots are assigned; the totals are credited to
    the DEFENSE (`opp`). A game in which an offense simply had nobody at a slot counts as zero at
    that slot (it is a real "allowed nothing there")."""
    assign = assigner_for(sport)
    by_game: Dict[Tuple, List[Dict]] = {}
    for p in pgames or []:
        if not p.get("team") or not p.get("opp"):
            continue
        by_game.setdefault((p.get("game"), p["team"], p["opp"]), []).append(p)
    out: Dict[str, List[Dict]] = {}
    for (gid, offense, defense), players in by_game.items():
        slots = {slot: _sum_stats(lst) for slot, lst in assign(players).items()}
        order = max((p.get("order") for p in players if p.get("order") is not None), default=None)
        out.setdefault(defense, []).append({"game": gid, "order": order, "offense": offense, "slots": slots})
    for lst in out.values():
        lst.sort(key=lambda g: (g["order"] is None, g["order"]), reverse=True)     # newest first
    return out


def summarize(allowed: Dict[str, List[Dict]], sport: str, n: Optional[int] = None) -> Dict[str, Dict[str, Dict]]:
    """{defense: {slot: {"games", "pts", "stats": {k: avg allowed per game}}}} over the defense's `n`
    most recent games (all of them when n is None). "pts" is the sport's headline metric."""
    out: Dict[str, Dict[str, Dict]] = {}
    for defense, games in allowed.items():
        window = games if n is None else games[:n]
        if not window:
            continue
        keys = sorted({k for g in window for st in g["slots"].values() for k in st})
        per_slot: Dict[str, Dict] = {}
        for slot in SLOTS_BY_SPORT[sport]:
            lines = [g["slots"].get(slot) or {} for g in window]
            avg = {k: sum(_num(l.get(k)) for l in lines) / len(lines) for k in keys}
            per_slot[slot] = {"games": len(window), "pts": sum(metric_value(sport, l) for l in lines) / len(lines),
                              "stats": avg}
        out[defense] = per_slot
    return out


def rank_slot(summary: Dict[str, Dict[str, Dict]], slot: str) -> Dict[str, int]:
    """{defense: rank} at one slot, 1 = allows the MOST (softest). Ties broken by name so the order is stable."""
    rows = [(d, s[slot]["pts"]) for d, s in summary.items() if slot in s]
    rows.sort(key=lambda r: (-r[1], r[0]))
    return {d: i + 1 for i, (d, _) in enumerate(rows)}


def league_average(summary: Dict[str, Dict[str, Dict]], slot: str) -> Optional[float]:
    vals = [s[slot]["pts"] for s in summary.values() if slot in s]
    return sum(vals) / len(vals) if vals else None


def tier(rank: Optional[int], n_teams: int) -> str:
    """Soft (top third of allowers) / Tough (bottom third) / Neutral. 1 = softest."""
    if not rank or n_teams < 3:
        return "—"
    third = n_teams / 3.0
    if rank <= third:
        return "Soft"
    if rank > n_teams - third:
        return "Tough"
    return "Neutral"


def trend_label(season_pts: Optional[float], recent_pts: Optional[float]) -> str:
    if not season_pts or recent_pts is None or season_pts <= 0:
        return "—"
    change = (recent_pts - season_pts) / season_pts * 100.0
    if change >= TREND_PCT:
        return "▲ softer lately"
    if change <= -TREND_PCT:
        return "▼ tougher lately"
    return "steady"


def stat_line(slot: str, stats: Dict[str, float]) -> str:
    """'48.2 rec yds · 4.1 rec · 0.3 rec TD' style line for one slot's per-game allowed stats."""
    bits = []
    for key, label in SLOT_STATS.get(slot, ()):
        if key in stats:
            bits.append(f"{stats[key]:.1f} {label}")
    return " · ".join(bits)


# --------------------------------------------------------------------------- one team's depth vs a defense
def player_form(pgames: Iterable[Dict], pid, sport: str, n: int = RECENT_N, opp: Optional[str] = None) -> Optional[Dict]:
    """A player's average headline metric over his `n` latest games (or, with `opp`, only the games vs that
    opponent). {"avg", "games"} or None when he has none in the sample."""
    mine = [p for p in pgames or [] if p.get("pid") == pid and (opp is None or p.get("opp") == opp)]
    mine.sort(key=lambda p: (p.get("order") is None, p.get("order")), reverse=True)
    mine = mine[:n]
    if not mine:
        return None
    vals = [metric_value(sport, p.get("stats") or {}) for p in mine]
    return {"avg": sum(vals) / len(vals), "games": len(vals)}


def usage_depth(pgames: Iterable[Dict], team: str, sport: str, last_n: int = RECENT_N) -> Dict[str, List[Dict]]:
    """A team's depth by recent USAGE — {slot: [{"pid","name","games_in_slot","avg"}]} most-used first —
    for the sports with no published depth-chart feed here (and as the football fallback). Looks at the
    team's `last_n` most recent games, assigns slots in each exactly as the defense table does, and ranks a
    slot's occupants by how many of those games they held it, then by production."""
    assign = assigner_for(sport)
    by_game: Dict[object, List[Dict]] = {}
    order: Dict[object, object] = {}
    for p in pgames or []:
        if p.get("team") != team:
            continue
        by_game.setdefault(p.get("game"), []).append(p)
        o = p.get("order")
        if o is not None:
            order[p.get("game")] = max(o, order.get(p.get("game"), o))
    games = sorted(by_game, key=lambda g: (g not in order, order.get(g)), reverse=True)[:last_n]
    tally: Dict[str, Dict[object, Dict]] = {}
    for g in games:
        for slot, lst in assign(by_game[g]).items():
            for p in lst:
                rec = tally.setdefault(slot, {}).setdefault(p.get("pid"), {"pid": p.get("pid"), "name": p.get("name"),
                                                                           "games_in_slot": 0, "total": 0.0, "mins": 0.0})
                rec["games_in_slot"] += 1
                rec["total"] += metric_value(sport, p.get("stats") or {})
                rec["mins"] += _num((p.get("stats") or {}).get("min"))
    out: Dict[str, List[Dict]] = {}
    for slot, recs in tally.items():
        rows = []
        for r in recs.values():
            rows.append({"pid": r["pid"], "name": r["name"], "games_in_slot": r["games_in_slot"],
                         "avg": r["total"] / r["games_in_slot"], "avg_min": r["mins"] / r["games_in_slot"]})
        key = (lambda r: (r["avg_min"], r["avg"])) if FAMILY_BY_SPORT.get(sport) == "basketball" else \
              (lambda r: (r["games_in_slot"], r["avg"]))
        rows.sort(key=key, reverse=True)
        out[slot] = rows
    return out


def ranking_pool(summary: Dict[str, Dict[str, Dict]], min_games: int = MIN_GAMES_FOR_RANK) -> Dict[str, Dict[str, Dict]]:
    """The summary restricted to defenses with at least `min_games` games at each slot — only those are
    ranked and averaged (a one-game defense would otherwise rank on noise)."""
    return {d: {s: v for s, v in per.items() if v["games"] >= min_games} for d, per in summary.items()}


def matchup_rows(sport: str, depth: Dict[str, List[Dict]], defense_team: str,
                 season_summary: Dict[str, Dict[str, Dict]], recent_summary: Optional[Dict[str, Dict[str, Dict]]],
                 pgames: Optional[Iterable[Dict]] = None, max_players: int = 3) -> List[Dict]:
    """The table: one row per slot, the offense's depth at that slot lined up against `defense_team`.

    depth: {slot: [{"pid","name","status"(opt),"note"(opt)}]} best first — the starter then backups for
    football, the group's rotation by minutes for basketball. Rank / league average / tier come from the
    ranking pool (defenses with enough games); when fewer than MIN_TEAMS_FOR_RANK defenses qualify at a slot
    they are None / "—" rather than a rank out of a handful. Each listed player carries his own recent form
    and his history vs this defense (from `pgames`)."""
    rows: List[Dict] = []
    pgames = list(pgames or [])
    pool = ranking_pool(season_summary)
    for slot in SLOTS_BY_SPORT[sport]:
        d = (season_summary.get(defense_team) or {}).get(slot)
        ranks = rank_slot(pool, slot)
        n_ranked = len(ranks)
        vals = [per[slot]["pts"] for per in pool.values() if slot in per]
        rankable = n_ranked >= MIN_TEAMS_FOR_RANK and (max(vals) - min(vals)) > 1e-9      # all-equal = nothing to rank
        rank = ranks.get(defense_team) if rankable else None
        league = league_average(pool, slot) if rankable else None
        rec = ((recent_summary or {}).get(defense_team) or {}).get(slot)
        players = []
        for pl in (depth.get(slot) or [])[:max_players]:
            players.append({
                "name": pl.get("name"), "status": pl.get("status"), "note": pl.get("note"),
                "recent": player_form(pgames, pl.get("pid"), sport),
                "h2h": player_form(pgames, pl.get("pid"), sport, n=10, opp=defense_team),
            })
        allowed = d["pts"] if d else None
        rows.append({
            "slot": slot, "label": SLOT_LABEL.get(slot, slot), "players": players,
            "rank": rank, "n_teams": n_ranked, "tier": tier(rank, n_ranked),
            "allowed": allowed, "league_avg": league,
            "vs_league_pct": None if not d or not league else (allowed - league) / league * 100.0,
            "games": d["games"] if d else 0, "thin": bool(d) and d["games"] < THIN_SAMPLE_GAMES,
            "line": stat_line(slot, d["stats"]) if d else "",
            "recent_allowed": rec["pts"] if rec else None,
            "trend": trend_label(allowed, rec["pts"] if rec else None),
        })
    return rows


# --------------------------------------------------------------------------- team head-to-head
def h2h_meetings(games: Iterable[Dict], team_a: str, team_b: str) -> List[Dict]:
    """Completed games between two teams, newest first, each from team_a's point of view.

    games: [{"date","home","away","home_score","away_score"}] (any season mix). Games without both
    scores (not played yet) are skipped. A neutral-site / either-order listing is handled: only the
    pair matters."""
    out: List[Dict] = []
    for g in games or []:
        home, away = g.get("home"), g.get("away")
        if {home, away} != {team_a, team_b} or home == away:
            continue
        hs, as_ = g.get("home_score"), g.get("away_score")
        try:
            hs_f, as_f = float(hs), float(as_)
        except (TypeError, ValueError):
            continue
        if math.isnan(hs_f) or math.isnan(as_f):
            continue
        a_score, b_score = (hs_f, as_f) if home == team_a else (as_f, hs_f)
        out.append({"date": str(g.get("date") or "")[:10], "home": home, "away": away,
                    "a_score": a_score, "b_score": b_score, "margin": a_score - b_score,
                    "total": a_score + b_score, "winner": team_a if a_score > b_score else (team_b if b_score > a_score else "Tie"),
                    "season": g.get("season")})
    out.sort(key=lambda m: m["date"], reverse=True)
    return out


def h2h_summary(meetings: Sequence[Dict], team_a: str, team_b: str) -> Dict:
    """Record and averages from team_a's side. Empty meetings -> zeros and avg None (never a made-up number)."""
    n = len(meetings)
    a_wins = sum(1 for m in meetings if m["winner"] == team_a)
    b_wins = sum(1 for m in meetings if m["winner"] == team_b)
    return {"games": n, "a_wins": a_wins, "b_wins": b_wins, "ties": n - a_wins - b_wins,
            "avg_margin": (sum(m["margin"] for m in meetings) / n) if n else None,
            "avg_total": (sum(m["total"] for m in meetings) / n) if n else None,
            "last": meetings[0] if n else None}


def h2h_sentence(summary: Dict, team_a: str, team_b: str) -> str:
    n = summary["games"]
    if not n:
        return f"No completed {team_a}–{team_b} meetings in the data window."
    lead = team_a if summary["a_wins"] > summary["b_wins"] else team_b if summary["b_wins"] > summary["a_wins"] else None
    rec = f"{summary['a_wins']}–{summary['b_wins']}" + (f"–{summary['ties']}" if summary["ties"] else "")
    who = f"{team_a} lead the series {rec}" if lead == team_a else (
        f"{team_b} lead the series {summary['b_wins']}–{summary['a_wins']}" + (f"–{summary['ties']}" if summary["ties"] else "")
        if lead == team_b else f"Series tied {rec}")
    m = summary["avg_margin"]
    margin = f"; {team_a} average margin {m:+.1f}" if m is not None else ""
    total = f"; average total {summary['avg_total']:.1f}" if summary["avg_total"] is not None else ""
    return f"{who} over {n} meeting(s){margin}{total}."


# --------------------------------------------------------------------------- display helpers (pure)
TIER_BADGE = {"Soft": "🟢 Soft", "Tough": "🔴 Tough", "Neutral": "⚪ Neutral", "—": "—"}
_STATUS_FLAG = {"out": "🚫", "doubtful": "⚠️", "questionable": "⚠️", "injured reserve": "🚫", "ir": "🚫"}


def _form_text(form: Optional[Dict]) -> str:
    return "—" if not form else f"{form['avg']:.1f} ({form['games']} g)"


def _player_text(pl: Dict) -> str:
    status = str(pl.get("status") or "").strip()
    flag = _STATUS_FLAG.get(status.lower(), "⚠️") if status else ""
    return f"{pl.get('name') or '?'}" + (f" {flag} {status}" if status else "")


def display_rows(rows: Sequence[Dict]) -> List[Dict]:
    """Matchup rows -> flat display dicts (strings) for the table: the starter up front, the next
    players behind him, the defense's standing at that slot beside them."""
    out: List[Dict] = []
    for r in rows:
        pls = r["players"]
        first = pls[0] if pls else None
        rank_txt = "—" if not r["rank"] else f"{r['rank']}/{r['n_teams']}"
        vs = r["vs_league_pct"]
        out.append({
            "Slot": r["slot"],
            "Starter": _player_text(first) if first else "—",
            "Last 4": _form_text(first["recent"]) if first else "—",
            "vs this D": _form_text(first["h2h"]) if first else "—",
            "D rank (1 = softest)": rank_txt,
            "Verdict": TIER_BADGE.get(r["tier"], "—"),
            "Allowed / g": "—" if r["allowed"] is None else f"{r['allowed']:.1f}" + (" ⚠️ thin" if r["thin"] else ""),
            "League avg": "—" if r["league_avg"] is None else f"{r['league_avg']:.1f}",
            "vs league": "—" if vs is None else f"{vs:+.0f}%",
            "Trend": r["trend"],
            "What it allows": r["line"] or "—",
            "Next up": " · ".join(f"{_player_text(p)} {_form_text(p['recent'])}" for p in pls[1:]) or "—",
        })
    return out


def callouts(side: Dict, off_name: str, def_name: str, limit: int = 3) -> Dict[str, List[str]]:
    """Plain-language targets and fades for one direction of a game, biggest gaps first. Only slots that
    have a rank (enough defenses to compare) and a starter qualify."""
    soft, tough = [], []
    for r in side["rows"]:
        if not r["rank"] or not r["players"] or r["vs_league_pct"] is None:
            continue
        p = r["players"][0]
        text = (f"{p['name']} ({r['slot']}) — {def_name} rank {r['rank']}/{r['n_teams']} against the position, "
                f"allowing {r['allowed']:.1f} vs a {r['league_avg']:.1f} league average ({r['vs_league_pct']:+.0f}%)"
                + (f"; he's averaging {p['recent']['avg']:.1f} lately" if p.get("recent") else "")
                + (f"; {r['trend']}" if r["trend"] in ("▲ softer lately", "▼ tougher lately") else "")
                + (f" [{p['status']}]" if p.get("status") else ""))
        if r["tier"] == "Soft":
            soft.append((r["vs_league_pct"], text))
        elif r["tier"] == "Tough":
            tough.append((r["vs_league_pct"], text))
    soft.sort(key=lambda t: -t[0])
    tough.sort(key=lambda t: t[0])
    return {"targets": [t for _, t in soft[:limit]], "fades": [t for _, t in tough[:limit]]}
