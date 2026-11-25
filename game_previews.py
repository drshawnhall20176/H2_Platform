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

import re

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
    return f"{head}model: {model} · market: {book} → model favors {lean}"


# Nov 23 (owner: members couldn't tell what "Leans" meant or where to look): plainer headers, the win chance and
# total beside the model's read instead of at the far right, and a bulleted "How to read this table"
# Nov 23 (owner): "Model" and "Market" -- not "book" and "model's side" ("does that mean the model's final pick?")
SIDE = "Model favors (spread)"
MARKET = "Market has"
TOTAL = "Total points (model / market)"
WIN = "Win chance (model / market)"


def blow_col(league: str) -> str:
    """'Blowout risk (15+ pts)' -- the header names the size, per sport (game_sim.BLOWOUT)."""
    import game_sim as GS
    fam = GS.family(league)
    return f"Blowout risk ({GS.BLOWOUT[fam]}+ {'goals' if fam == 'hockey' else 'pts'})"


AGREE = "Model & market agree?"


def agreement(p: Dict, league: str = "") -> str:
    """Nov 23 (owner: "a column right next to Blowout Risk that shows if the model and the market agree", like the
    Anytime TD lab's): ✅ same winner and within 2 points (the tracked candidate rule's games) · 🟨 same winner, further
    apart · ⚠️ the model has the other team winning. Hockey (Nov 23): the spread is always the 1.5-goal puck line, so
    points say nothing -- it compares win chances instead (✅ same favorite within 4 points)."""
    import game_sim as GS
    if league and GS.family(league) == "hockey":
        mp, fh = PR._num(p.get("model_p")), PR._num(p.get("fair_home"))
        if mp is None or fh is None:
            return "—"
        gap = abs(mp - fh) * 100
        if (mp > 0.5) != (fh > 0.5) and abs(mp - 0.5) > 0.01 and abs(fh - 0.5) > 0.01:
            return f"⚠️ Model has {p.get('home') if mp > 0.5 else p.get('away')} winning"
        return "✅ Agree" if gap < 4 else f"🟨 Same favorite · win chance {gap:.0f} pts apart"
    hs, mm = PR._num(p.get("home_spread")), PR._num(p.get("model_margin"))
    if hs is None or mm is None:
        return "—"
    gap = abs(mm + hs)
    mkt = -hs
    if gap < 2:
        return "✅ Agree"
    if mkt == 0 or mm == 0 or (mm > 0) == (mkt > 0):
        return f"🟨 Same winner · {gap:.1f} pts apart"
    return f"⚠️ Model has {p.get('home') if mm > 0 else p.get('away')} winning"


def blowout(league: str, p: Dict) -> str:
    """Nov 23 (owner: "does the game lab table have a blow out risk indicator column?"): the chance the game is decided
    by game_sim.BLOWOUT[family]+ (15+ points in basketball, 14+ in football, 3+ goals in hockey), simulated around the
    MARKET's spread and total -- the market sizes margins better than our model, whose mismatch margins run small.
    Checked on 768 college basketball games (Nov 5-22): spreads 8-12 said 33%, 33% happened; 18-25 said 71%, 70%."""
    import game_sim as GS
    hs = PR._num(p.get("home_spread"))
    m = -hs if hs is not None else PR._num(p.get("model_margin"))
    t = PR._num(p.get("line_total")) or PR._num(p.get("model_total"))
    if m is None or t is None:
        return "—"
    try:
        sim = GS.simulate(league, m, t, key=f"blow-{p.get('game_id') or p.get('home')}", n=4000)
    except Exception:                                           # noqa: BLE001
        sim = None
    if not sim:
        return "—"
    x = sim["blowout"]
    return f"{'🟥' if x >= BLOW_HIGH else '🟨' if x >= BLOW_MID else '🟩'} {x:.0%}"


BLOW_HIGH, BLOW_MID = 0.60, 0.35


def prop_agreement(chance, price) -> str:
    """Nov 24 (owner: "expand this metric to player props"): does the market lean the same way as the model on this
    prop? The model's chance vs. the chance the price implies (vig left in, so ~52% is a coin flip at -110).
    ✅ both above a coin flip · ⚠️ the price says this side is the underdog while the model likes it · ➖ the price is
    about even. One side's price only, so it reads the market's lean, not a no-vig fair line."""
    c, pr = PR._num(chance), PR._num(price)
    if c is None or pr is None or pr == 0:
        return "—"
    imp = (-pr / (-pr + 100)) if pr < 0 else (100 / (pr + 100))
    model_yes = c > 0.5
    if imp >= 0.535:
        return "✅ Agree" if model_yes else "⚠️ Market favors this side"
    if imp <= 0.49:
        return "⚠️ Market leans the other way" if model_yes else "✅ Agree"
    return "➖ Market near even"


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9 ]", "", str(s or "").lower()).strip()


def game_blowouts(league: str, games) -> Dict[str, str]:
    """Nov 24: the game-level Blowout risk for each prop's game string ("Away @ Home"), matched to the saved game
    picks by team names. A prop in a likely blowout carries minutes risk for starters (and garbage-time upside)."""
    import model_store as MS
    try:
        recs = MS.load_game_picks(league, ungraded=True)
    except Exception:                                           # noqa: BLE001
        recs = []
    out: Dict[str, str] = {}
    for g in {x for x in games if x}:
        ng = _norm(g)
        hit = None
        for p in recs:
            h, a = _norm(p.get("home")), _norm(p.get("away"))
            if h and a and h in ng and a in ng:
                hit = p
                break
        if hit is None:                                         # fall back to the teams' last words ("Lakers")
            for p in recs:
                h = (_norm(p.get("home")).split() or [""])[-1]
                a = (_norm(p.get("away")).split() or [""])[-1]
                if h and a and re.search(rf"\b{h}\b", ng) and re.search(rf"\b{a}\b", ng):
                    hit = p
                    break
        out[g] = blowout(league, hit) if hit else "—"
    return out


USE_NOTE = ("**Use:** every game here reads ⚪ No edge — no game-line rule for this league has passed testing yet, so the "
            "model's leans are information, not bets. The Use column comes back on its own the day a rule earns a tag.")


def collapse_use(df, col: str = "Use"):
    """Nov 23 (owner: "if the Use column shows no edge for everything is it useful?"): a Use column with one value on
    every row says nothing per game -- drop it and return a one-line note instead. (df, note or None)."""
    try:
        if col not in df.columns or df.empty:
            return df, None
        vals = {str(v).strip() for v in df[col]}
        if len(vals) == 1 and next(iter(vals)) in ("⚪ No edge", "⛔ Pass", "—", "", "None"):
            return df.drop(columns=[col]), USE_NOTE
    except Exception:                                           # noqa: BLE001
        pass
    return df, None


def legend_md(extra: Optional[List[str]] = None, rules: str = "") -> str:
    """The table's key as bullets (it was one long paragraph). `extra`: bullets a page adds (Use, ticks, backtest)."""
    b = [
        "**Model** = our projection. **Market** = the sportsbooks' line. Every column compares the two.",
        "**Game** is listed **Away @ Home** — the team after the @ is the home team.",
        f"**Model has / {MARKET}** — who each one has winning, and by how many points.",
        f"**{SIDE}** — the side of the market's spread the model's number points to. Example: the market has Davidson "
        "by 5, the model has Davidson by only 0.3 → the model favors **Northern Iowa +5** (it thinks Northern Iowa "
        "keeps it closer than 5). It is a lean, not a bet: \"No bet\" in front means no tested rule backs it, and "
        "the Use column says when one does.",
        f"**{WIN}** — the chance the named team wins: the model's, then the market's (its price with the books' cut "
        "taken out). A big gap is where the model disagrees most about the winner.",
        f"**{TOTAL}** — the model's projected combined score next to the market's total. Model higher → it favors the "
        "Over; lower → the Under.",
        "**Gap (pts)** — how far the model's margin is from the market's spread.",
        "**Blowout risk** — the chance the game is decided by the size in the header (15+ points in basketball, 14+ in "
        "football, 3+ goals in hockey), from the market's spread: 🟥 60%+ · 🟨 35-60% · 🟩 under 35%. It runs off the "
        "market because the market sizes margins better than our model. Use it for props (starters sit late in "
        "blowouts) and big-spread picks; on the season, the model's spread picks at big gaps were only a coin flip.",
        "**Model & market agree?** — ✅ Agree = same winner and within 2 points of each other (hockey: same favorite, "
        "win chances within 4 points) · 🟨 same winner, further apart · ⚠️ the model has the other team winning "
        "outright. It has meant something only in college basketball so far (the model's side won 60% of ✅ games on "
        "Nov 5–22, now being tested forward); in the NBA ✅ games went 52% against the spread — break-even.",
        BET_NOTE,
        "**Last meetings** — how the two teams' games against each other went over the last year (up to 4). "
        "Context only: tested Nov 24, past meetings added nothing to the model's chances or against the spread "
        "(NBA props: 5,401 graded; NBA, NHL and college basketball games), because the model already prices each "
        "team's form and defense.",
        "**⭐ = model favors** — in each market column, the star marks the team (or Over / Under) the model's numbers "
        "favor against that line. Like the column above, a lean, not a final pick.",
        f"**Form (30 days)** — how the model's favored side did on games with a gap this size in the last 30 days: "
        f"{HOT} won 55%+ of 20+ graded games · {EVEN} about break-even · {COLD} losing · {NEW} fewer than 20 games. A "
        "−110 spread needs 52.4% to break even.",
    ]
    out = "\n".join(f"- {x}" for x in b + list(extra or []))
    return out + (f"\n- **Rules for this league:** {rules}" if rules else "")


def says_parts(p: Dict, playable: bool = False, tagged: bool = False) -> Dict[str, str]:
    """Nov 22 (owner: "The model says column could benefit from some text wrapping"): the same sentence as says(), in
    three short columns the table can show without cutting off -- Model has, Book has, Leans. `tagged`: the table has
    a Use column, which already says whether it's a bet; otherwise a game without a tested rule reads "No bet"."""
    hs, mm = PR._num(p.get("home_spread")), PR._num(p.get("model_margin"))
    if hs is None or mm is None:
        return {"Model has": "—", MARKET: "—", SIDE: "—"}
    home, away = p.get("home"), p.get("away")
    model = "a toss-up" if abs(mm) < 0.5 else _by(home, round(mm, 1)) if mm > 0 else _by(away, round(-mm, 1))
    bm = -hs
    book = "pick'em" if bm == 0 else _by(home, bm) if bm > 0 else _by(away, -bm)
    lean = _lean(p)
    return {"Model has": model, MARKET: book,
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
        move = TB.move_cell(mv) if mv else ""                   # Nov 25 (owner): a short arrow, the detail further right
        _ag = agreement(p, league)
        out.append({"Tip (ET)": tip(p), "Game": f"{p.get('away')} @ {p.get('home')}",
                    BET: game_bet(league, playable, False, _ag),
                    AGREE: _ag, blow_col(league): blowout(league, p),     # Nov 24 (owner): the indicators up front
                    "Gap (pts)": None if e is None else round(abs(e), 1),
                    **({"Spread move": move} if league in getattr(TB, "MOVE_GAME_LEAGUES", ()) else {}),
                    **lead,     # Nov 23 (owner): left of Use
                    **says_parts(p, playable, tagged=bool(use)),
                    TOTAL: f"{p.get('model_total')} / {p.get('line_total') or '—'}",
                    "Form (30 days)": form_text(w, n) if b is not None else "—",
                    LAST: _last(league, p),                     # Nov 24 (owner): context, right of the form
                    **({"Line move": mv.get("spread_move_why") or ""} if league in getattr(TB, "MOVE_GAME_LEAGUES", ())
                       else {}),
                    **(extras(p) if extras else {}),
                    "_lean": _lean(p), "_playable": playable, "_move": mv.get("spread_move") or "",
                    "_form": form_of(w, n) if b is not None else NEW, "_i": len(out)})
    return out


LAST = "Last meetings"
# Nov 24 (owner: "is there a 'bet' column so I can identify these easily"): one column that says what a row is for.
BET = "Bet?"
BET_YES, BET_TRACK, BET_INFO = "🃏 Bet", "🧪 Tracking", "Info only"
BET_NOTE = ("**Bet?** — 🃏 Bet = a tag from a rule that has made money in testing (💰 / 🔒 / 🎟️ / 🎯) · 🧪 Tracking = "
            "the ✅ close-gap rule being tested forward (not proven yet) · Info only = what the model thinks, with no "
            "tested edge — context, not a bet.")


GAP = "Close gap (pts)"


def gap_text(p: Dict, league: str = "") -> str:
    """Nov 24 (owner: indicators up front): how far the model's margin is from the market's spread -- '✅ 1.2' inside
    the close-gap rule's 2 points, else the number. Hockey's puck line says nothing here: '—'."""
    try:
        import game_sim as GS
        if league and GS.family(league) == "hockey":
            return "—"
    except Exception:                                           # noqa: BLE001
        pass
    hs, mm = PR._num(p.get("home_spread")), PR._num(p.get("model_margin"))
    if hs is None or mm is None:
        return "—"
    g = abs(mm + hs)
    return f"✅ {g:.1f}" if g < 2 else f"{g:.1f}"


TESTED_ICONS = ("💰", "🔒", "🎟️", "🎯")


def _f(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def prop_tracking(sport: str, p: Dict) -> bool:
    """Nov 24 (owner: every league with the Bet? column and NCAAMB's Tracking): a prop the tracked prop rules would bet
    (candidate_rules.PROP_RULES -- NFL / college football Unders). Reads a board play (Side, ModelProb, MarketProb, Line,
    Pickem, PriceSource) or a saved row (side, chance, p_market, line)."""
    try:
        import candidate_rules as CR
    except Exception:                                           # noqa: BLE001
        return False
    side = p.get("Side") or p.get("side")
    if side != "Under" or p.get("Pickem") or (p.get("PriceSource") not in (None, "book")):
        return False
    ch = _f(p.get("ModelProb") if p.get("ModelProb") is not None else p.get("chance"))
    mk = _f(p.get("MarketProb") if p.get("MarketProb") is not None else p.get("p_market"))
    line = p.get("Line") if p.get("Line") is not None else p.get("line")
    if ch is None or mk is None or line is None:
        return False
    row = {"book": p.get("PricedAt") or p.get("book") or "", "over_price": -110, "under_price": -110,
           "p_model": 1 - ch, "p_market": 1 - mk, "line": line}
    return any(cfg["sport"] == sport and CR.prop_qualifies(rule, row) for rule, cfg in CR.PROP_RULES.items())


def break_even(price) -> Optional[float]:
    """The win rate a price needs to break even (American odds; the vig left in)."""
    a = _f(price)
    if a is None or a == 0:
        return None
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def earned_short(play: Optional[Dict]) -> Optional[Dict]:
    """Nov 25 (owner: a 🃏 Bet next to a 50% earned chance reads as a contradiction): {"earned", "needed", "price"}
    when the pick's EARNED chance (the model corrected to its record) is not above the break-even rate for its price;
    else None. Reads a board play (_earned, RealPrice) or a saved row (earned, price)."""
    if not play:
        return None
    e = _f(play.get("_earned") if play.get("_earned") is not None else play.get("earned"))
    price = play.get("RealPrice") if play.get("RealPrice") is not None else play.get("price")
    need = break_even(price)
    if e is None or need is None or e > need:
        return None
    return {"earned": e, "needed": need, "price": _f(price)}


def earned_rule_on() -> bool:
    """Nov 25: on everywhere -- owner, public Discord and commercial builds (the owner approved it after previewing it
    in the commercial layout). Kept as a function so it can be switched off in one place."""
    return True


def prop_bet(sport: str, use_text: str = "", play: Optional[Dict] = None, earned_rule: Optional[bool] = None) -> str:
    """Bet? for a prop (or any tagged pick): a tested tag -> 🃏 Bet; a tracked prop rule -> 🧪 Tracking; else Info only.
    Nov 25: with the earned rule on, a tested tag whose earned chance doesn't clear its price's break-even is 🧪
    Tracking, not a bet (earned_short says why)."""
    u = str(use_text or "")
    if any(i in u for i in TESTED_ICONS):
        if (earned_rule_on() if earned_rule is None else earned_rule) and earned_short(play):
            return BET_TRACK
        return BET_YES
    if play is not None and prop_tracking(sport, play):
        return BET_TRACK
    return BET_INFO


def bet_filter(key: str) -> set:
    """Nov 24 (owner: "Tracking and Info only should be filter buttons"): which Bet? kinds a table shows."""
    import streamlit as st
    opts = [BET_YES, BET_TRACK, BET_INFO]
    sel = st.pills("Show Bet?", opts, selection_mode="multi", default=opts, key=key,
                   help="🃏 Bet = a tested tag · 🧪 Tracking = a rule being tested forward · Info only = no tested edge. "
                        "Untick a kind to hide it.")
    return set(sel or opts)


def game_bet(league: str, playable: bool, money: bool, agree: str) -> str:
    """The Bet? value for a game: a tested tag -> 🃏 Bet; NCAAMB close-gap (✅ agree) -> 🧪 Tracking; else Info only."""
    if playable or money:
        return BET_YES
    if league == "NCAAMB" and str(agree).startswith("✅"):
        return BET_TRACK
    return BET_INFO


def _last(league: str, p: Dict) -> str:
    """Nov 24 (owner): the teams' recent meetings (h2h.py) -- context, not part of the chances."""
    try:
        import h2h as H
        return H.lookup(league, p.get("home"), p.get("away"))
    except Exception:                                           # noqa: BLE001
        return "—"


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
