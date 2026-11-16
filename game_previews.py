"""
game_previews.py — the customer's view of a Game Lab (Nov 16).

The owner's Game Lab is a pick table: Use, Why, Est. cover, tick-to-log. For a league with no tested game-line rule
(college basketball, NBA, NHL) that is a page of ⛔ Pass, which is accurate and reads as "this tool is useless" to a
paying member. Nov 16 (later the same day): the owner made this the standard on every build -- the owner and Discord
apps show the same previews, with the Use column and (owner only) tick-to-log. Everyone sees the games as PREVIEWS: the projected score, who the model thinks wins, the
model's line beside the book's, which side it leans to and by how much -- and how leans of that size have actually
done over the last 30 days ("form"). Nothing here is called a pick unless a tested rule made it one.

  🔥 Hot    leans of this size have won 55%+ of 20+ graded games in the last 30 days
  ➖ Even   between 47.6% and 55%
  ❄️ Cold   under 47.6% (a -110 spread loses money below 52.4%)
  🆕 New    fewer than 20 graded games

Form is recent results, not a tested edge: the long backtest for these leagues found none. The page says so once.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

import pick_records as PR

HOT, EVEN, COLD, NEW = "🔥 Hot", "➖ Even", "❄️ Cold", "🆕 New"
HOT_RATE, COLD_RATE = 0.55, 0.476
NOTE = ("**Previews, not picks.** No game-line rule in this league has beaten the books in long-run testing, so "
        "nothing below is a recommended bet. Each game shows the model's projection beside the book's line, the side "
        "it leans to, and **form**: how leans of that size have done over the last 30 days. Form is recent results, "
        "not a tested edge. The tested picks are in the player props.")


def form_of(w: int, n: int) -> str:
    if n < PR.MIN_N:
        return NEW
    r = w / n
    return HOT if r >= HOT_RATE else COLD if r < COLD_RATE else EVEN


def form_text(w: int, n: int) -> str:
    if not n:
        return f"{NEW} · no graded games yet"
    return f"{form_of(w, n)} · {w}–{n - w} ({w / n:.0%})"


def _score(p: Dict) -> str:
    m, t = PR._num(p.get("model_margin")), PR._num(p.get("model_total"))
    if m is None or t is None:
        return "—"
    return f"{(t - m) / 2:.0f}–{(t + m) / 2:.0f}"                 # away–home, the order the Game column lists them


def _winner(p: Dict) -> str:
    mp = PR._num(p.get("model_p"))
    if mp is None:
        return "—"
    return f"{p.get('home')} {mp:.0%}" if mp >= 0.5 else f"{p.get('away')} {1 - mp:.0%}"


def _lean(p: Dict) -> str:
    hs, e = PR._num(p.get("home_spread")), PR._num(p.get("edge"))
    if hs is None or e is None:
        return "—"
    return f"{p.get('home')} {hs:+g}" if e >= 0 else f"{p.get('away')} {-hs:+g}"


def preview_rows(league: str, picks: List[Dict], recs: Optional[Dict], tip: Callable[[Dict], str],
                 tag: Optional[Callable[[Dict], Dict]] = None, use: Optional[Callable[[Dict], str]] = None,
                 extras: Optional[Callable[[Dict], Dict]] = None) -> List[Dict]:
    """One row per game, in the order given. "Pick" is filled only where a tested rule tagged the game playable.
    The owner and Discord builds pass `use` (the site-wide Use symbol, shown instead of Pick) and `extras` (more
    columns at the end): the same preview, with the owner's columns."""
    import props_engine as PE
    out = []
    for p in picks or []:
        hs, mm, e = PR._num(p.get("home_spread")), PR._num(p.get("model_margin")), PR._num(p.get("edge"))
        try:
            b = PR.band((PR.gaps(p, league) or {}).get("Spread"))
        except Exception:                                       # noqa: BLE001
            b = None
        w, n = (recs or {}).get(("Spread", b), (0, 0)) if b is not None else (0, 0)
        t = tag(p) if tag else {}
        playable = t.get("use") in (PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE)
        lead = {"Use": use(p)} if use else {"Pick": (("🔒 " if t.get("lock") else "") + str(t.get("use"))) if playable else ""}
        out.append({"Tip (ET)": tip(p), "Game": f"{p.get('away')} @ {p.get('home')}", **lead,
                    "Model leans": _lean(p), "Gap (pts)": None if e is None else round(abs(e), 1),
                    "Form (30 days)": form_text(w, n) if b is not None else "—",
                    "Projected score": _score(p), "Model's winner": _winner(p),
                    "Book line": "—" if hs is None else f"{p.get('home')} {hs:+g}",
                    "Model line": "—" if mm is None else f"{p.get('home')} {-mm:+.1f}",
                    "Total: model / book": f"{p.get('model_total')} / {p.get('line_total') or '—'}",
                    **(extras(p) if extras else {}),
                    "_form": form_of(w, n) if b is not None else NEW, "_i": len(out)})
    return out


def spotlight(rows: List[Dict], k: int = 3) -> List[Dict]:
    """The games worth opening first: the biggest disagreements with the book whose size of lean is running hot;
    when none is hot, the biggest that aren't cold. Never more than k, and never a game with no gap."""
    have = [r for r in rows or [] if r.get("Gap (pts)")]
    hot = sorted([r for r in have if r.get("_form") == HOT], key=lambda r: -r["Gap (pts)"])
    rest = sorted([r for r in have if r.get("_form") in (EVEN, NEW)], key=lambda r: -r["Gap (pts)"])
    return (hot + rest)[:k]


def public(rows: List[Dict]) -> List[Dict]:
    """Rows for display: private keys dropped; the Pick column only when some game has one."""
    any_pick = any(r.get("Pick") for r in rows or [])
    return [{k: v for k, v in r.items() if not k.startswith("_") and (any_pick or k != "Pick")} for r in rows or []]
