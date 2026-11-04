"""
reconcile_bets.py — reconcile the Bet Log for given slate dates (Nov 4). Run by the reconcile-bets workflow.

1. Settles open GAME-LINE bets the overnight graders can't reach -- spreads, puck lines, totals and moneylines logged
   from a slip (not from a Game Lab, which settles its own) -- from the results archive the capture-intl workflow keeps
   (ESPN finals for NCAAMB / NBA / NHL / WNBA). A bet's game ("Away @ Home") is matched to a final within a day of
   its slate date; nothing is guessed when a team can't be matched confidently.
2. Prints every bet for those dates (singles and parlay headers, real and tracking), with results and P&L, and what's
   still open and why.

    python reconcile_bets.py --dates 2026-11-02,2026-11-03 [--apply]
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional

GAME_MARKETS = ("Spread", "Puck Line", "Total", "Moneyline")
ARCHIVE_FOR = {"NCAAMB": "NCAAMB", "NBA": "NBA", "NHL": "NHL", "WNBA": "WNBA"}


def _out(t: str = "") -> None:
    print(t)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(t + "\n")


def _teams(game: Optional[str]):
    if not game or " @ " not in game:
        return None
    a, h = game.split(" @ ", 1)
    return a.strip(), h.strip()


def find_final(bet: Dict, finals: List[Dict]) -> Optional[Dict]:
    """The archived final for this bet's game: both teams match (loosely, but uniquely) within a day of the slate."""
    import intl_hoops as I
    t = _teams(bet.get("game"))
    if not t:
        return None
    away, home = t
    try:
        d0 = date.fromisoformat(str(bet.get("slate_date"))[:10])
    except ValueError:
        return None
    near = [g for g in finals if abs((date.fromisoformat(g["date"][:10]) - d0).days) <= 1]
    hits = []
    for g in near:
        hm = I.find_team([g["home_team"]], home, True) and I.find_team([g["away_team"]], away, True)
        sw = I.find_team([g["home_team"]], away, True) and I.find_team([g["away_team"]], home, True)
        if hm or sw:
            hits.append(g)
    return hits[0] if len(hits) == 1 else None


def grade(bet: Dict, g: Dict) -> Optional[str]:
    """win / loss / push for a game-line bet from its final."""
    import intl_hoops as I
    mk, side = bet.get("market"), str(bet.get("side") or "")
    hp, ap = float(g["home_points"]), float(g["away_points"])
    if mk == "Total":
        d = hp + ap - float(bet["line"])
        if d == 0:
            return "push"
        return "win" if (d > 0) == (side.lower() == "over") else "loss"
    is_home = bool(I.find_team([g["home_team"]], side, True))
    is_away = bool(I.find_team([g["away_team"]], side, True))
    if is_home == is_away:
        return None                                              # can't tell which team the bet was on
    mine, theirs = (hp, ap) if is_home else (ap, hp)
    if mk == "Moneyline":
        return "win" if mine > theirs else "loss"
    d = mine - theirs + float(bet["line"])
    return "push" if d == 0 else ("win" if d > 0 else "loss")


def main(argv=None) -> int:
    import betlog as B
    import model_store as MS
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    dates = [d.strip() for d in a.dates.split(",") if d.strip()]
    bets = [b for b in B.list_bets() if str(b.get("slate_date") or "")[:10] in dates]
    lo = (date.fromisoformat(min(dates)) - timedelta(days=2)).isoformat()
    finals = {k: MS.load_results(v, since=lo) for k, v in ARCHIVE_FOR.items()}

    settled_now = []
    for b in bets:
        if B._result(b) or b.get("market") not in GAME_MARKETS or B.is_parlay_header(b):
            continue
        fs = finals.get(b.get("sport") or "")
        if not fs:
            continue
        g = find_final(b, fs)
        r = grade(b, g) if g else None
        if r:
            if a.apply:
                B.update_bet(int(b["id"]), result=r)
            b["result"] = r
            settled_now.append((b, g))

    _out(f"## Bet Log reconciliation — {', '.join(dates)}" + ("" if a.apply else " (preview, nothing written)"))
    _out("")
    if settled_now:
        _out(f"**Settled now from final scores: {len(settled_now)}**")
        _out("")
        _out("| id | sport | bet | final | result |")
        _out("|---|---|---|---|---|")
        for b, g in settled_now:
            line = "" if b.get("line") is None else f" {float(b['line']):+g}" if b["market"] != "Total" else f" {float(b['line']):g}"
            _out(f"| {b['id']} | {b.get('sport')} | {b.get('side')} {b['market'].lower()}{line} @ {b.get('entry_odds')} | "
                 f"{g['away_team']} {g['away_points']:g} – {g['home_team']} {g['home_points']:g} | {b['result']} |")
        _out("")

    money = B.money_bets(bets)
    headed = B.headed_tickets(bets)
    groups = defaultdict(list)
    for b in money:
        real = b.get("is_real_bet") not in (False, 0, "0", "false")
        groups[("Real" if real else "Tracking", str(b.get("slate_date"))[:10], b.get("sport") or "?")].append(b)
    for key in sorted(groups):
        rows = groups[key]
        kind, d, sport = key
        _out(f"### {kind} · {d} · {sport}")
        _out("")
        _out("| id | bet | odds | stake | result | P&L |")
        _out("|---|---|---|---|---|---|")
        tot_stake = tot_pnl = 0.0
        for b in sorted(rows, key=lambda x: x.get("id") or 0):
            if B.is_parlay_header(b):
                legs = [x for x in bets if B._ticket(x) == B._ticket(b) and not B.is_parlay_header(x)]
                lw = sum(1 for x in legs if B._result(x) == "win")
                ll = sum(1 for x in legs if B._result(x) == "loss")
                desc = f"🎟️ {B._ticket(b)} ({len(legs)} legs: {lw} won, {ll} lost, {len(legs) - lw - ll} open)"
            else:
                line = "" if b.get("line") is None else (f" {float(b['line']):g}" if b.get("market") == "Total" or
                                                         b.get("side") in ("Over", "Under") else f" {float(b['line']):+g}")
                who = b.get("player") if b.get("player") not in (None, "Game total") else ""
                desc = f"{who} {b.get('market')} {b.get('side') if b.get('side') != who else ''}{line}".replace("  ", " ").strip()
                if b.get("player") == "Game total":
                    desc += f" ({b.get('game')})"
            pnl = B.bet_pnl(b)
            st = float(b.get("stake") or 0)
            tot_stake += st
            tot_pnl += pnl or 0
            _out(f"| {b.get('id')} | {desc} | {b.get('entry_odds')} | ${st:,.2f} | {B._result(b) or 'open'} | "
                 f"{'—' if pnl is None else f'${pnl:+,.2f}'} |")
        open_n = sum(1 for b in rows if not B._result(b))
        _out(f"| | **Total** | | **${tot_stake:,.2f}** | {open_n} open | **${tot_pnl:+,.2f}** |")
        _out("")
    still = [b for b in money if not B._result(b)]
    if still:
        _out(f"**Still open: {len(still)}** — " + "; ".join(f"#{b['id']} {b.get('player') or b.get('ticket')} {b.get('market')}"
                                                          for b in still[:30]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
