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


def _by(team, pts) -> str:
    return f"{team} by {pts:g}"


def says(p: Dict, playable: bool = False) -> str:
    """Nov 17 (owner: "Model leans, Model's winner, Book line, Model line are telling different stories"): ONE
    sentence in place of those four columns -- who the model has winning and by how much, the same for the book,
    and the side of the spread that difference points to. A game without a tested rule says "No bet" first, so a
    lean is never read as a pick."""
    hs, mm = PR._num(p.get("home_spread")), PR._num(p.get("model_margin"))
    if hs is None or mm is None:
        return "—"
    home, away = p.get("home"), p.get("away")
    model = "a toss-up" if abs(mm) < 0.5 else _by(home, round(mm, 1)) if mm > 0 else _by(away, round(-mm, 1))
    bm = -hs
    book = "pick'em" if bm == 0 else _by(home, bm) if bm > 0 else _by(away, -bm)
    lean = _lean(p)
    head = "" if playable else "No bet — "
    return f"{head}model: {model} · book: {book} → leans {lean}"


# Nov 23 (owner: members couldn't tell what "Leans" meant or where to look): plainer headers, the win chance and
# total beside the model's read instead of at the far right, and a bulleted "How to read this table"
SIDE = "Model's side (spread)"
TOTAL = "Total points (model / book)"
WIN = "Win chance (model / book)"


def legend_md(extra: Optional[List[str]] = None, rules: str = "") -> str:
    """The table's key as bullets (it was one long paragraph). `extra`: bullets a page adds (Use, ticks, backtest)."""
    b = [
        "**Game** is listed **Away @ Home** — the team after the @ is the home team.",
        "**Model has / Book has** — who each one has winning, and by how many points.",
        f"**{SIDE}** — the side of the book's spread the model's number points to. Example: the book has Davidson by 5, "
        "the model has Davidson by only 0.3 → the model's side is **Northern Iowa +5** (it thinks Northern Iowa keeps it "
        "closer than 5). \"No bet\" in front means no tested rule backs it here: information, not a pick.",
        f"**{WIN}** — the chance the named team wins: the model's, then the book's (its price with the cut taken out). "
        "A big gap between the two is where the model disagrees most about the winner.",
        f"**{TOTAL}** — the model's projected combined score next to the book's total. Model higher → it leans Over; "
        "lower → Under.",
        "**Gap (pts)** — how far the model's margin is from the book's spread.",
        "**⭐** — the model's side in each market, **named by team** (or Over / Under), next to that market's tick boxes.",
        f"**Form (30 days)** — how the model's side did on games with a gap this size in the last 30 days: {HOT} won 55%+ "
        f"of 20+ graded games · {EVEN} about break-even · {COLD} losing · {NEW} fewer than 20 games. A −110 spread needs "
        "52.4% to break even.",
    ]
    out = "\n".join(f"- {x}" for x in b + list(extra or []))
    return out + (f"\n- **Rules for this league:** {rules}" if rules else "")


def says_parts(p: Dict, playable: bool = False, tagged: bool = False) -> Dict[str, str]:
    """Nov 22 (owner: "The model says column could benefit from some text wrapping"): the same sentence as says(), in
    three short columns the table can show without cutting off -- Model has, Book has, Leans. `tagged`: the table has
    a Use column, which already says whether it's a bet; otherwise a game without a tested rule reads "No bet"."""
    hs, mm = PR._num(p.get("home_spread")), PR._num(p.get("model_margin"))
    if hs is None or mm is None:
        return {"Model has": "—", "Book has": "—", SIDE: "—"}
    home, away = p.get("home"), p.get("away")
    model = "a toss-up" if abs(mm) < 0.5 else _by(home, round(mm, 1)) if mm > 0 else _by(away, round(-mm, 1))
    bm = -hs
    book = "pick'em" if bm == 0 else _by(home, bm) if bm > 0 else _by(away, -bm)
    lean = _lean(p)
    return {"Model has": model, "Book has": book,
            SIDE: lean if (playable or tagged) else f"No bet · {lean}"}


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
        try:
            import todays_best as TB
            mv = TB.spread_move(p, league)
        except Exception:                                       # noqa: BLE001
            mv = {}
        move = " ".join(x for x in (mv.get("spread_move") or "", f"({mv['spread_move_why']})"
                                    if mv.get("spread_move_why") else "") if x)
        out.append({"Tip (ET)": tip(p), "Game": f"{p.get('away')} @ {p.get('home')}", **lead,
                    **says_parts(p, playable, tagged=bool(use)),
                    TOTAL: f"{p.get('model_total')} / {p.get('line_total') or '—'}",
                    "Gap (pts)": None if e is None else round(abs(e), 1),
                    **({"Spread move": move} if league in getattr(TB, "MOVE_GAME_LEAGUES", ()) else {}),
                    "Form (30 days)": form_text(w, n) if b is not None else "—",
                    **(extras(p) if extras else {}),
                    "_lean": _lean(p), "_playable": playable, "_move": mv.get("spread_move") or "",
                    "_form": form_of(w, n) if b is not None else NEW, "_i": len(out)})
    return out


def spotlight(rows: List[Dict], k: int = 3) -> List[Dict]:
    """Nov 17: the games worth opening first are ones with a TESTED reason -- a playable tag, or (college basketball)
    the spread moving toward the model's side. A lean that's merely "hot" is no longer spotlighted: on Nov 16 that's
    how Hofstra +11.5 and Rutgers +16.5 (both ⛔ Pass) got picked."""
    have = [r for r in rows or [] if r.get("Gap (pts)")]
    good = [r for r in have if r.get("_playable")] + [r for r in have if not r.get("_playable") and r.get("_move") == "📈 our way"]
    return sorted(good, key=lambda r: (not r.get("_playable"), -r["Gap (pts)"]))[:k]


def public(rows: List[Dict]) -> List[Dict]:
    """Rows for display: private keys dropped; the Pick column only when some game has one."""
    any_pick = any(r.get("Pick") for r in rows or [])
    return [{k: v for k, v in r.items() if not k.startswith("_") and (any_pick or k != "Pick")} for r in rows or []]


def sim_row(label: str, kick: str, home: str, away: str, res: Optional[Dict]) -> Dict:
    """One slate row from a game simulation (the NFL Game Lab: no book line is stored, so no lean or form).
    `res`: {"home_win_prob", "proj_spread" (home minus away), "proj_total", "proj_home_score", "proj_away_score"}."""
    if not res:
        return {"Kickoff (ET)": kick, "Game": label, "Projected score": "—", "Model's winner": "—",
                "Model spread": "—", "Model total": None, "_close": 1.0}
    hp = res["home_win_prob"]
    fav, margin = (home, res["proj_spread"]) if res["proj_spread"] > 0 else (away, -res["proj_spread"])
    return {"Kickoff (ET)": kick, "Game": label,
            "Projected score": f"{res['proj_away_score']:.0f}–{res['proj_home_score']:.0f}",
            "Model's winner": f"{home} {hp:.0%}" if hp >= 0.5 else f"{away} {1 - hp:.0%}",
            "Model spread": f"{fav} -{margin:.1f}", "Model total": round(res["proj_total"], 1),
            "_close": abs(hp - 0.5)}
