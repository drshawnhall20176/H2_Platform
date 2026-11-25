"""
rotation_panel.py — each team's rotation on the game card (Nov 25, PropSeason scrub item 3).

PropSeason's game page shows "projected minutes tonight" in starters / bench / deep-bench bubbles. Ours is built
from real box scores: every player's minutes over his team's last 10 games and how many of them he started, grouped
into starters / bench / deep bench, with H2's projected minutes beside it where tonight's board carries one, and
tonight's injury report marked (a starter ruled out is where the extra minutes come from). Context, not a pick.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

import h2_brand as HB

LAST_N = 10
BENCH_MIN = 12.0            # average minutes that make a bench regular; below it is the deep bench


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def rotation(pgames: Iterable[Dict], team, last_n: int = LAST_N) -> List[Dict]:
    """[{"name","pid","avg_min","starts","games","of"}] for the team's last `last_n` games, most minutes first.
    avg_min averages over the games he played; starts counts the box score's starter flag."""
    rows = [p for p in pgames or [] if p.get("team") == team]
    games = sorted({p.get("game"): p.get("order") for p in rows}.items(), key=lambda kv: str(kv[1] or ""),
                   reverse=True)[:last_n]
    keep = {g for g, _ in games}
    per: Dict[object, Dict] = {}
    for p in rows:
        if p.get("game") not in keep:
            continue
        m = _f((p.get("stats") or {}).get("min"))
        if m <= 0:
            continue
        r = per.setdefault(p.get("pid"), {"name": p.get("name"), "pid": p.get("pid"), "mins": 0.0, "starts": 0,
                                           "games": 0, "of": len(keep)})
        r["mins"] += m
        r["games"] += 1
        r["starts"] += 1 if p.get("starter") else 0
    out = [dict(r, avg_min=r["mins"] / r["games"]) for r in per.values()]
    return sorted(out, key=lambda r: -r["avg_min"] * r["games"])


def groups(rot: List[Dict]) -> Dict[str, List[Dict]]:
    """Starters: the five who started most (at least half the games); bench: 12+ minutes; deep bench: the rest."""
    starters = sorted([r for r in rot if r["starts"] * 2 >= max(1, r["of"])], key=lambda r: (-r["starts"],
                                                                                            -r["avg_min"]))[:5]
    s_ids = {r["pid"] for r in starters}
    rest = [r for r in rot if r["pid"] not in s_ids]
    return {"Starters": starters, "Bench": [r for r in rest if r["avg_min"] >= BENCH_MIN],
            "Deep bench": [r for r in rest if r["avg_min"] < BENCH_MIN]}


def _norm(s) -> str:
    import injury_check as IC
    return IC._norm(s)


def team_html(team: str, rot: List[Dict], proj: Optional[Dict[str, float]] = None,
              inj: Optional[Dict[str, str]] = None) -> str:
    """One team's column: a bar per player (last-10 minutes), H2's projection beside it when tonight's board has one."""
    proj, inj = proj or {}, inj or {}
    top = max([r["avg_min"] for r in rot] + [36.0])
    parts = [f'<div style="flex:1;min-width:250px;"><div style="color:{HB.INK_SOFT};font-size:12px;'
             f'letter-spacing:.05em;margin-bottom:4px;">{str(team).upper()}</div>']
    for label, lst in groups(rot).items():
        if not lst:
            continue
        parts.append(f'<div style="color:{HB.GOLD};font-size:11.5px;font-weight:700;margin:6px 0 2px;">'
                     f'{label.upper()}</div>')
        for r in lst:
            k = _norm(r["name"])
            st = inj.get(k)
            w = max(4, int(100 * r["avg_min"] / top))
            col = HB.GRAY if st == "out" else HB.BLUE
            pm = proj.get(k)
            right = (f'{r["avg_min"]:.0f}' + (f' → <b style="color:{HB.GOLD};">{pm:.0f}</b>' if pm else ""))
            tag = {"out": " 🚑", "questionable": " ⚠️"}.get(st or "", "")
            parts.append(
                f'<div style="display:flex;align-items:center;gap:6px;font-size:12.5px;margin:1px 0;color:{HB.INK};'
                f'{"opacity:.55;text-decoration:line-through;" if st == "out" else ""}">'
                f'<div style="width:118px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{tag.strip() + " " if tag else ""}{r["name"]}'
                f'</div><div style="flex:1;background:{HB.EDGE};border-radius:4px;height:8px;">'
                f'<div style="width:{w}%;background:{col};height:8px;border-radius:4px;"></div></div>'
                f'<div style="width:58px;text-align:right;">{right}</div></div>')
    parts.append('</div>')
    return "".join(parts)


def proj_minutes(rows: Iterable[Dict]) -> Dict[str, float]:
    """{normalized player name: H2's projected minutes} from tonight's saved board rows."""
    out: Dict[str, float] = {}
    for r in rows or []:
        pm = r.get("proj_min") if r.get("proj_min") is not None else r.get("_proj_min")
        name = r.get("player") or r.get("Player")
        if name and isinstance(pm, (int, float)) and pm > 0:
            out[_norm(name)] = float(pm)
    return out


CAPTION = ("Bars: average minutes in the games he played over his team's last 10 (box scores). Gold: H2's projected "
           "minutes tonight, where the board has a prop on him. 🚑 out · ⚠️ questionable on tonight's injury report. "
           "Starters: started at least half of those games. Context only — the projections already use it.")
