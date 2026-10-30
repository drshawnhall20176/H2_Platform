"""
nba_positions.py — the NBA "Position breakout" tab on Position Matchups (Oct 29, beta).

NFL-style: five rows (PG / SG / SF / PF / C), tonight's depth chart at each spot against what the defense has allowed
to THAT position, with its own rank. Display only -- nothing here feeds the projections, Use tags or other pages, so
the tab can be removed (delete this file + the tab block in views/38) without touching the model.

How past games get a five-position label: ESPN publishes only tonight's NBA depth chart and box scores mostly say
G / F / C, so every player in the league sample is labelled from his team's CURRENT depth chart (his highest listing).
Players rarely change spots mid-season, so that is a sound read of who played where. Players on no chart (deep bench)
are left out of the five-position totals.

Small samples: each position's number is also shown blended toward the defense's broader group (PG/SG -> guards,
SF/PF -> forwards): weight n / (n + SHRINK_GAMES) on the position's own number.
"""
from typing import Dict, Iterable, List, Optional, Sequence

import position_matchups as PM

POSITIONS = ("PG", "SG", "SF", "PF", "C")
GROUP_OF = {"PG": "G", "SG": "G", "SF": "F", "PF": "F", "C": "C"}
LABEL = {"PG": "Point guard", "SG": "Shooting guard", "SF": "Small forward", "PF": "Power forward", "C": "Center"}
SHRINK_GAMES = 10.0
STATS = ("pts", "reb", "ast", "fg3m", "stl", "blk")
PRA = ("pts", "reb", "ast")
BACKUPS_SHOWN = 2


def _num(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _pra(stats: Dict) -> float:
    return _num(stats.get("pts")) + _num(stats.get("reb")) + _num(stats.get("ast"))


def label_players(charts: Dict) -> Dict:
    """{team id: chart} -> {athlete id: PG/SG/SF/PF/C} (each player's highest listing)."""
    out: Dict = {}
    for chart in (charts or {}).values():
        for pid, e in (chart or {}).items():
            pos = str(e.get("pos") or "").upper()
            if pos in POSITIONS:
                out[pid] = pos
    return out


def _played(p: Dict) -> bool:
    s = p.get("stats") or {}
    return _num(s.get("min")) > 0 or any(_num(s.get(k)) for k in ("pts", "reb", "ast", "fg3m"))


def allowed_by_position(pgames: Iterable[Dict], labels: Dict, key=lambda p: p) -> Dict:
    """{defense: [{"game","order","pos": {PG: summed stats, ...}, "grp": {G: ..., F: ..., C: ...}}]} -- per game, what
    the offense's players at each spot put up against that defense. A spot nobody filled counts as zero."""
    games: Dict = {}
    for p in pgames or []:
        if not _played(p):
            continue
        g = games.setdefault((p.get("game"), p.get("opp")), {"game": p.get("game"), "order": p.get("order"),
                                                            "pos": {}, "grp": {}})
        pos = labels.get(p.get("pid"))
        grp = GROUP_OF.get(pos) if pos else PM.position_group(p.get("pos"))
        for bucket, k in (("pos", pos), ("grp", grp)):
            if not k:
                continue
            tot = g[bucket].setdefault(k, {})
            for stat in STATS:
                tot[stat] = tot.get(stat, 0.0) + _num((p.get("stats") or {}).get(stat))
    out: Dict = {}
    for (gid, defense), g in games.items():
        out.setdefault(defense, []).append(g)
    for lst in out.values():
        lst.sort(key=lambda g: str(g.get("order") or ""), reverse=True)
    return out


def summarize(allowed: Dict, n: Optional[int] = None, keys: Sequence[str] = PRA) -> Dict:
    """{defense: {"pos": {PG: {"pra","games","stats"}}, "grp": {G: {...}}}} over each defense's latest `n` games.
    "pra" is the chosen stat (`keys` summed; PRA by default)."""
    out: Dict = {}
    for d, games in allowed.items():
        window = games[:n] if n else games
        if not window:
            continue
        per = {"pos": {}, "grp": {}}
        for bucket, spots in (("pos", POSITIONS), ("grp", ("G", "F", "C"))):
            for k in spots:
                lines = [g[bucket].get(k) or {} for g in window]
                stats = {s: sum(_num(l.get(s)) for l in lines) / len(lines) for s in STATS}
                per[bucket][k] = {"pra": sum(stats[x] for x in keys), "games": len(window), "stats": stats}
        out[d] = per
    return out


def _pool(summary: Dict, bucket: str, key: str) -> Dict[object, float]:
    return {d: v[bucket][key]["pra"] for d, v in summary.items()
            if key in v[bucket] and v[bucket][key]["games"] >= PM.MIN_GAMES_FOR_RANK}


def blended_pct(pos_pct: Optional[float], grp_pct: Optional[float], games: int) -> Optional[float]:
    """The position's vs-league % pulled toward its group's for a small sample."""
    if pos_pct is None:
        return grp_pct
    if grp_pct is None:
        return pos_pct
    w = games / (games + SHRINK_GAMES)
    return w * pos_pct + (1 - w) * grp_pct


def depth_lists(feed: Optional[Dict]) -> Dict[str, List[Dict]]:
    """Raw ESPN depthcharts response -> {PG: [{"pid","name"}, ...] starter first}."""
    out: Dict[str, List[Dict]] = {}
    for chart in (feed or {}).get("depthchart") or []:
        positions = (chart or {}).get("positions") or {}
        for key in ("pg", "sg", "sf", "pf", "c"):
            ath = (positions.get(key) or {}).get("athletes") or []
            if ath:
                out[key.upper()] = [{"pid": _int(a.get("id")), "name": a.get("displayName")} for a in ath]
        if out:
            break
    return out


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return x


def breakout_rows(defense, depth: Dict[str, List[Dict]], season: Dict, recent: Dict, form_pgames,
                  status: Optional[Dict[str, str]] = None) -> List[Dict]:
    """One row per position: tonight's starter (+ backups) vs `defense` at that position."""
    status = status or {}
    rows = []
    for pos in POSITIONS:
        grp = GROUP_OF[pos]
        pool = _pool(season, "pos", pos)
        rankable = len(pool) >= PM.MIN_TEAMS_FOR_RANK and (max(pool.values()) - min(pool.values())) > 1e-9
        ordered = sorted(pool, key=lambda d: (-pool[d], str(d)))
        rank = ordered.index(defense) + 1 if rankable and defense in pool else None
        league = sum(pool.values()) / len(pool) if rankable else None
        d = ((season.get(defense) or {}).get("pos") or {}).get(pos)
        rec = ((recent.get(defense) or {}).get("pos") or {}).get(pos)
        gpool = _pool(season, "grp", grp)
        g_league = sum(gpool.values()) / len(gpool) if len(gpool) >= PM.MIN_TEAMS_FOR_RANK else None
        gd = ((season.get(defense) or {}).get("grp") or {}).get(grp)
        pos_pct = (d["pra"] - league) / league * 100 if d and league else None
        grp_pct = (gd["pra"] - g_league) / g_league * 100 if gd and g_league else None
        players = depth.get(pos) or []
        starter = players[0] if players else None
        form = PM.player_form(form_pgames, starter["pid"], "NBA") if starter else None
        rows.append({
            "pos": pos, "label": LABEL[pos], "starter": starter, "backups": players[1:1 + BACKUPS_SHOWN],
            "form": form, "rank": rank, "n_teams": len(pool), "tier": PM.tier(rank, len(pool)),
            "allowed": d["pra"] if d else None, "league": league, "pos_pct": pos_pct, "grp": grp, "grp_pct": grp_pct,
            "blend_pct": blended_pct(pos_pct, grp_pct, d["games"] if d else 0),
            "games": d["games"] if d else 0, "stats": d["stats"] if d else None,
            "trend": PM.trend_label(d["pra"] if d else None, rec["pra"] if rec else None),
            "status": {p["name"]: status.get(p["name"]) for p in players if status.get(p["name"])},
        })
    return rows


def _name(p: Optional[Dict], status: Dict) -> str:
    if not p:
        return "—"
    s = status.get(p["name"])
    return p["name"] + (f" ({s})" if s else "")


def display(rows: List[Dict], unit: str = "PRA") -> List[Dict]:
    out = []
    for r in rows:
        st = r["status"]
        s = r["stats"]
        out.append({
            "Pos": r["pos"],
            "Starter": _name(r["starter"], st),
            "Backups": ", ".join(_name(b, st) for b in r["backups"]) or "—",
            f"Last 4 ({unit})": PM._form_text(r["form"]),
            "D rank (1 = softest)": f"{r['rank']}/{r['n_teams']}" if r["rank"] else "—",
            "Verdict": PM.TIER_BADGE.get(r["tier"], "—"),
            f"Allowed / g ({unit})": "—" if r["allowed"] is None else
                                 f"{r['allowed']:.1f}" + (" ⚠️ thin" if r["games"] < PM.THIN_SAMPLE_GAMES else ""),
            f"League avg ({unit})": "—" if r["league"] is None else f"{r['league']:.1f}",
            "vs league": "—" if r["pos_pct"] is None else f"{r['pos_pct']:+.0f}%",
            "Group vs league": "—" if r["grp_pct"] is None else f"{r['grp']} {r['grp_pct']:+.0f}%",
            "Blended": "—" if r["blend_pct"] is None else f"{r['blend_pct']:+.0f}%",
            "Trend": r["trend"],
            "What it allows": "—" if not s else
                              f"{s['pts']:.1f} pts · {s['reb']:.1f} reb · {s['ast']:.1f} ast · {s['fg3m']:.1f} 3PM"
                              f" · {s['stl']:.1f} stl · {s['blk']:.1f} blk",
        })
    return out


def build(bundle: Dict, eng, stat: str = "PRA") -> Optional[Dict]:
    """Both directions of one NBA game's breakout from a Position Matchups bundle, or None when no depth charts
    could be read (the tab then says so). Fetches every team's depth chart in the sample (cached by the engine)."""
    import position_data as PD
    props = bundle.get("props") or {}
    pgames = props.get("pgames") or []
    if not pgames:
        return None
    teams = {p.get("team") for p in pgames} | {bundle["home"], bundle["away"]}
    charts = PD.depth_charts("NBA", teams)
    if not charts:
        return None
    labels = label_players(charts)
    allowed = allowed_by_position(pgames, labels)
    keys = (PM.STAT_CHOICES["basketball"].get(stat) or PRA)
    season, recent = summarize(allowed, keys=keys), summarize(allowed, PM.RECENT_N, keys=keys)
    status = {}
    for rot in (props.get("rotation") or {}).values():
        for r in rot or []:
            if r.get("status"):
                status[r["name"]] = r["status"]
    form_pgames = props.get("cur_pgames") or pgames
    out = {"labelled": len(labels), "teams_charted": len(charts)}
    for side, off, de in (("away_off", bundle["away"], bundle["home"]), ("home_off", bundle["home"], bundle["away"])):
        feed = None
        try:
            feed = eng._get_json_cached(f"{eng.SITE_API}/teams/{off}/depthcharts")
        except Exception:                                       # noqa: BLE001
            feed = None
        with PM.using_metric("basketball", stat):
            out[side] = breakout_rows(de, depth_lists(feed), season, recent, form_pgames, status)
    return out
