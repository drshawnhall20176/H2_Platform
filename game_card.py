"""
game_card.py — click into a game: one game on one screen (Nov 25, commercial preview first).

Owner, Nov 24: "we are missing some good functionality like the ability to click a card and have it jump to a game or
prop." The player card (player_card.py) answers "this prop"; this card answers "this game", in H2's own look
(h2_brand.py), from what the boards already saved -- no Odds API calls, nothing written:

  * the header: both teams, league, start time and the Bet? verdict;
  * the score: the model's projected score next to the score the market's spread and total imply;
  * the lines: spread, total and moneyline -- market vs model;
  * three meters: how far the model is from the market (inside 2 points = the 🧪 close-gap zone), blowout risk, and
    the model's win chance for its likely winner;
  * the read: the Line pick, the 💰 Money pick, how the spread has moved, and the teams' last meetings;
  * H2's player picks in this game, each opening its player card.

`build(row)` turns one board row (todays_best.winner_rows) into plain data, so it is tested without Streamlit;
`render(card, props)` draws it.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

import h2_brand as HB

GAP_ZONE = 2.0          # the close-gap rule's 2 points (game_previews.agreement / gap_text)
GAP_SCALE = 8.0         # the meter runs 0-8 points; anything past that reads "far apart"


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _pct_of(text) -> Optional[float]:
    m = re.search(r"(\d+)%", str(text or ""))
    return int(m.group(1)) / 100 if m else None


def scores(margin, total) -> Optional[Dict[str, float]]:
    """{home, away} from a home margin and a game total."""
    m, t = _num(margin), _num(total)
    if m is None or t is None:
        return None
    return {"home": (t + m) / 2, "away": (t - m) / 2}


def build(r: Dict) -> Dict:
    """One board row -> the card's data. Every field is optional; a missing one shows as '—'."""
    import game_lines_table as GLT
    import game_previews as GP
    p = r.get("_full") or {}
    lg = r.get("league") if r.get("sport") == "INTL" else (r.get("sport") or r.get("league") or "")
    home, away = p.get("home") or (r.get("_rec") or {}).get("home"), p.get("away") or (r.get("_rec") or {}).get("away")
    hs, lt = _num(p.get("home_spread")), _num(p.get("line_total"))
    if hs is None and _num(p.get("line")) is not None:
        hs = -_num(p.get("line"))
    mm, mt = _num(p.get("model_margin")), _num(p.get("model_total"))
    gap = None if (mm is None or hs is None) else abs(mm - (-hs))

    def safe(f, *a, default="—"):
        try:
            return f(*a)
        except Exception:                                       # noqa: BLE001 -- one bad helper never blanks the card
            return default
    blow = safe(GP.blowout, lg, p) if p else "—"
    return {
        "league": lg, "label": r.get("league") or lg, "game": r.get("game") or f"{away} @ {home}",
        "home": home, "away": away, "time": r.get("time") or "", "final": r.get("final"),
        "bet": safe(GLT.bet, r, default=""),
        "model": scores(mm, mt), "market": scores(None if hs is None else -hs, lt),
        "spread": r.get("spread_txt") or "—", "total": r.get("total_txt") or "—",
        "model_txt": r.get("model_txt") or "—",
        "model_spread": None if mm is None else (f"{home if mm >= 0 else away} by {abs(mm):.1f}"),
        "model_total": mt, "market_total": lt,
        "gap": gap, "gap_text": safe(GP.gap_text, p, lg) if p else "—",
        "agree": safe(GP.agreement, p, lg) if p else "—",
        "blowout": blow, "blowout_pct": _pct_of(blow),
        "winner": r.get("winner"), "win_chance": _num(r.get("chance")), "win_price": r.get("price"),
        "line_pick": r.get("best"), "line_chance": _num(r.get("best_chance")), "line_price": r.get("best_price"),
        "line_tested": bool(r.get("best_tested")),
        "money_pick": r.get("money_pick") if r.get("money") else None, "money_chance": _num(r.get("money_chance")),
        "money_price": r.get("money_price"),
        "move": " ".join(x for x in (r.get("spread_move") or "", r.get("spread_move_why") or "") if x) or "—",
        "last": safe(GP._last, lg, p) if p else "—",
    }


def for_game(winners: List[Dict], game: str) -> Optional[Dict]:
    """The board row for a game string ("Away @ Home")."""
    g = str(game or "").strip().lower()
    return next((r for r in winners or [] if str(r.get("game") or "").strip().lower() == g), None)


def _price(x) -> str:
    v = _num(x)
    return "" if v is None else f" · {v:+.0f}"


def meter(title: str, frac: Optional[float], left: str, right: str, color: str, value: str,
          zone: Optional[float] = None) -> str:
    """A thin horizontal meter (HTML): a filled bar from the left, an optional shaded zone at the left edge."""
    f = 0.0 if frac is None else max(0.0, min(1.0, frac))
    z = "" if zone is None else (f'<div style="position:absolute;left:0;top:0;bottom:0;width:{zone * 100:.0f}%;'
                                 f'background:{HB.TEAL}22;border-right:1px dashed {HB.TEAL};"></div>')
    return (f'<div style="margin:6px 0 12px;"><div style="display:flex;justify-content:space-between;'
            f'font-size:12.5px;color:{HB.INK_SOFT};"><span style="font-weight:700;color:{HB.INK};">{title}</span>'
            f'<span style="font-weight:800;color:{color};">{value}</span></div>'
            f'<div style="position:relative;height:9px;border-radius:999px;background:{HB.EDGE};margin-top:5px;'
            f'overflow:hidden;">{z}<div style="position:absolute;left:0;top:0;bottom:0;width:{f * 100:.0f}%;'
            f'background:{color};border-radius:999px;opacity:.9;"></div></div>'
            f'<div style="display:flex;justify-content:space-between;font-size:11px;color:{HB.GRAY};margin-top:2px;">'
            f'<span>{left}</span><span>{right}</span></div></div>')


def _score_block(title: str, s: Optional[Dict], away: str, home: str, color: str) -> str:
    if not s:
        body = f'<div style="color:{HB.GRAY};font-size:14px;">—</div>'
    else:
        body = (f'<div style="font-size:15px;color:{HB.INK};line-height:1.5;">{away} '
                f'<b style="color:{color};font-size:20px;">{s["away"]:.0f}</b><br>{home} '
                f'<b style="color:{color};font-size:20px;">{s["home"]:.0f}</b></div>')
    return (f'<div style="flex:1;min-width:140px;background:{HB.PANEL};border:1px solid {HB.EDGE};border-radius:10px;'
            f'padding:10px 14px;"><div style="color:{HB.INK_SOFT};font-size:11.5px;letter-spacing:.06em;">{title}</div>'
            f'{body}</div>')


def header_html(g: Dict) -> str:
    status = (f'Final: {g["final"]}' if g.get("final") else g.get("time") or "")
    return (f'<div style="background:linear-gradient(110deg,{HB.NAVY},{HB.SLATE});border:1px solid {HB.EDGE};'
            f'border-radius:14px;padding:16px 20px;margin:4px 0 10px;">'
            f'<div style="color:{HB.INK_SOFT};font-size:12.5px;letter-spacing:.06em;">{g["label"]} · {status}</div>'
            f'<div style="color:{HB.INK};font-size:22px;font-weight:800;line-height:1.2;margin-top:3px;">'
            f'{g.get("away") or ""} <span style="color:{HB.GRAY};">@</span> {g.get("home") or ""}</div>'
            f'<div style="margin-top:9px;display:flex;gap:6px;flex-wrap:wrap;">{HB.bet_chip(g.get("bet") or "Info only")}'
            + (f' {HB.chip(g["agree"], HB.BLUE)}' if g.get("agree") not in (None, "", "—") else "")
            + '</div><div style="display:flex;gap:10px;margin-top:12px;flex-wrap:wrap;">'
            + _score_block("MODEL'S PROJECTED SCORE", g.get("model"), g.get("away") or "", g.get("home") or "", HB.BLUE)
            + _score_block("WHAT THE MARKET IMPLIES", g.get("market"), g.get("away") or "", g.get("home") or "",
                           HB.GOLD)
            + '</div></div>')


def meters_html(g: Dict) -> str:
    gap = g.get("gap")
    out = meter("Model vs market", None if gap is None else gap / GAP_SCALE, "same number",
                f"{GAP_SCALE:g}+ pts apart", HB.TEAL if (gap is not None and gap <= GAP_ZONE) else HB.BLUE,
                "—" if gap is None else f"{gap:.1f} pts apart", zone=GAP_ZONE / GAP_SCALE)
    bp = g.get("blowout_pct")
    out += meter("Blowout risk", bp, "close game", "lopsided", HB.GRAY if bp is None else
                 (HB.GOLD if bp >= 0.60 else HB.BLUE if bp >= 0.35 else HB.TEAL),
                 "—" if bp is None else f"{bp:.0%}")
    wc = g.get("win_chance")
    out += meter(f"Likely winner: {g.get('winner') or '—'}", None if wc is None else (wc - 0.5) * 2, "coin flip",
                 "sure thing", HB.BLUE, "—" if wc is None else f"{wc:.0%}")
    return out


def render(g: Dict, props: Optional[List[Dict]] = None, key: str = "gc") -> None:
    """Draw the card. `props`: H2's player picks in this game (board rows), each can open its player card."""
    import streamlit as st
    st.markdown(header_html(g), unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**The lines** — market · model")
        st.markdown(f"Spread: **{g['spread']}** · model {g.get('model_spread') or '—'}  \n"
                    f"Total: **{g['total']}** · model "
                    f"{'—' if g.get('model_total') is None else format(g['model_total'], '.1f')}  \n"
                    f"Moneyline: **{g.get('winner') or '—'}**{_price(g.get('win_price'))}")
        st.markdown("**H2's read**")
        bits = []
        if g.get("line_pick"):
            bits.append(f"📏 Line pick: **{g['line_pick']}**"
                        + (f" · {g['line_chance']:.0%}" if g.get("line_chance") is not None and g.get("line_tested")
                           else "") + (_price(g.get("line_price")) if g.get("line_tested") else ""))
        if g.get("money_pick"):
            bits.append(f"💰 Money pick: **{g['money_pick']}**"
                        + (f" · {g['money_chance']:.0%}" if g.get("money_chance") is not None else "")
                        + _price(g.get("money_price")))
        bits.append(f"📈 Spread move: {g.get('move') or '—'}")
        bits.append(f"🤝 Last meetings: {g.get('last') or '—'}")
        st.markdown("  \n".join(bits))
    with c2:
        st.markdown(meters_html(g), unsafe_allow_html=True)
    st.caption("The dashed teal zone on the first meter is the close-gap rule: the model within 2 points of the "
               "market's spread. Blowout risk is simulated around the market's spread and total; in a likely blowout "
               "starters can sit late. Last meetings are context only — tested, they add nothing to the chances.")
    props = [p for p in props or [] if p.get("player") or p.get("Player")]
    if props:
        import player_card as PC
        st.markdown(f"**H2's player picks in this game** ({len(props)})")
        PC.picker(props, lambda r: g.get("league") or r.get("sport") or "", key=f"{key}_pc",
                  label="🔎 Open a player card")



# --------------------------------------------------------------------------- soccer (Nov 25)
def build_soccer(r: Dict, flags: Optional[List[Dict]] = None) -> Dict:
    """One soccer row (todays_best.soccer_rows) -> the soccer card's data: three results, model vs market."""
    rec = r.get("_rec") or {}
    home, away = rec.get("home"), rec.get("away")
    probs, mkt, prices = r.get("_probs") or {}, r.get("_market") or {}, r.get("_prices") or {}
    names = {"home": home, "draw": "Draw", "away": away}
    results = [{"side": s, "name": names[s], "model": _num(probs.get(s)), "market": _num(mkt.get(s)),
                "price": prices.get(s)} for s in ("home", "draw", "away")]
    xg = r.get("_xg") or None
    return {"league": "SOCCER", "label": r.get("league") or "Soccer", "game": r.get("game"), "home": home,
            "away": away, "time": r.get("time") or "", "final": r.get("final"), "results": results,
            "xg": xg, "sharp": bool(r.get("_sharp")), "pick": r.get("winner"), "chance": _num(r.get("chance")),
            "flags": [f for f in flags or [] if str(f.get("game")) == str(r.get("game"))]}


def soccer_html(g: Dict) -> str:
    status = f'Final: {g["final"]}' if g.get("final") else g.get("time") or ""
    xg = g.get("xg")
    score = ("" if not xg else
             f'<div style="margin-top:10px;color:{HB.INK_SOFT};font-size:12.5px;letter-spacing:.05em;">MODEL\'S '
             f'EXPECTED GOALS</div><div style="color:{HB.INK};font-size:16px;">{g.get("away")} '
             f'<b style="color:{HB.BLUE};font-size:20px;">{xg["away"]:.1f}</b> · {g.get("home")} '
             f'<b style="color:{HB.BLUE};font-size:20px;">{xg["home"]:.1f}</b></div>')
    head = (f'<div style="background:linear-gradient(110deg,{HB.NAVY},{HB.SLATE});border:1px solid {HB.EDGE};'
            f'border-radius:14px;padding:16px 20px;margin:4px 0 10px;">'
            f'<div style="color:{HB.INK_SOFT};font-size:12.5px;letter-spacing:.06em;">{g["label"]} · {status}</div>'
            f'<div style="color:{HB.INK};font-size:22px;font-weight:800;line-height:1.2;margin-top:3px;">'
            f'{g.get("away") or ""} <span style="color:{HB.GRAY};">vs</span> {g.get("home") or ""}</div>'
            f'<div style="margin-top:9px;">{HB.bet_chip("🧪 Tracking" if g.get("flags") else "Info only")}</div>'
            f'{score}</div>')
    bars = ""
    for x in g.get("results") or []:
        m, k = x.get("model"), x.get("market")
        pr = _num(x.get("price"))
        bars += meter(x["name"] or "—", m, "", "", HB.BLUE, "—" if m is None else f"model {m:.0%}")
        if k is not None:
            bars += (f'<div style="font-size:11.5px;color:{HB.GOLD};margin:-8px 0 10px;">market {k:.0%}'
                     + (f' · best price {pr:+.0f}' if pr is not None else "") + '</div>')
    return head + bars


def render_soccer(g: Dict) -> None:
    import streamlit as st
    st.markdown(soccer_html(g), unsafe_allow_html=True)
    if g.get("pick"):
        st.markdown(f"**Model's most likely result:** {g['pick']}"
                    + (f" ({g['chance']:.0%})" if g.get("chance") is not None else ""))
    for f in g.get("flags") or []:
        pr = _num(f.get("price"))
        st.markdown(f"📈 **{f.get('pick')}**" + (f" at {pr:+.0f}" if pr is not None else "")
                    + (f" ({f.get('book')})" if f.get("book") else "")
                    + " — a US price above the sharp line by 2% or more. 🧪 Tracking, not tested.")
    st.caption("Blue bars: the goals model's chance of each result. Gold: the market's chance ("
               + ("Pinnacle's no-vig line" if g.get("sharp") else "the US books' average") + "). "
               "Soccer is tracking only: the backtest lost to the closing line, so these are reads, not bets.")


def render_basic(c: Dict) -> None:
    """Nov 25: a pick whose game has no saved board row yet (a lab sport, a late line) -- its own facts, no dead end."""
    import streamlit as st
    st.markdown(f'<div style="background:linear-gradient(110deg,{HB.NAVY},{HB.SLATE});border:1px solid {HB.EDGE};'
                f'border-radius:14px;padding:16px 20px;margin:4px 0 10px;"><div style="color:{HB.INK_SOFT};'
                f'font-size:12.5px;">{c.get("sport") or ""} · {c.get("time") or ""}</div><div style="color:{HB.INK};'
                f'font-size:20px;font-weight:800;margin-top:3px;">{c.get("game") or ""}</div>'
                f'<div style="margin-top:9px;">{HB.bet_chip(c.get("bet") or "Info only")}</div></div>',
                unsafe_allow_html=True)
    ch = _num(c.get("chance"))
    st.markdown(f"**{c.get('pick') or '—'}**" + (f" · {ch:.0%}" if ch is not None else "")
                + (f" · {c['price']}" if c.get("price") not in (None, "", "—") else ""))
    if c.get("basis"):
        st.caption(c["basis"])
    st.caption("The full game card fills in once this game is on the saved board.")



# --------------------------------------------------------------------------- tennis (Nov 25)
def build_tennis(r: Dict) -> Dict:
    """One tennis board row -> the match card: each player's chance (model vs market) and best price."""
    rec, p = r.get("_rec") or {}, r.get("_full") or {}
    home, away = rec.get("home") or p.get("home"), rec.get("away") or p.get("away")
    ch = _num(r.get("chance"))
    hp = None if ch is None else (ch if r.get("winner") == home else 1 - ch)
    fh = _num(p.get("fair_home"))
    players = [{"name": away, "model": None if hp is None else 1 - hp, "market": None if fh is None else 1 - fh,
                "price": p.get("best_away")},
               {"name": home, "model": hp, "market": fh, "price": p.get("best_home")}]
    try:
        import game_lines_table as GLT
        bet = GLT.bet(r)
    except Exception:                                           # noqa: BLE001
        bet = ""
    return {"league": "TENNIS", "label": r.get("league") or "Tennis", "time": r.get("time") or "",
            "final": r.get("final"), "game": r.get("game"), "players": players, "bet": bet,
            "winner": r.get("winner"), "chance": ch, "use": r.get("use") or "",
            "money_pick": r.get("money_pick") if r.get("money") else None, "money_price": r.get("money_price"),
            "priced": any(_num(x["price"]) is not None for x in players)}


def tennis_html(g: Dict) -> str:
    status = f'Final: {g["final"]}' if g.get("final") else g.get("time") or ""
    a, b = g["players"]
    head = (f'<div style="background:linear-gradient(110deg,{HB.NAVY},{HB.SLATE});border:1px solid {HB.EDGE};'
            f'border-radius:14px;padding:16px 20px;margin:4px 0 10px;">'
            f'<div style="color:{HB.INK_SOFT};font-size:12.5px;letter-spacing:.06em;">{g["label"]} · {status}</div>'
            f'<div style="color:{HB.INK};font-size:22px;font-weight:800;line-height:1.2;margin-top:3px;">'
            f'{a["name"] or ""} <span style="color:{HB.GRAY};">vs</span> {b["name"] or ""}</div>'
            f'<div style="margin-top:9px;">{HB.bet_chip(g.get("bet") or "Info only")}</div></div>')
    bars = ""
    for x in g["players"]:
        m, k, pr = x.get("model"), x.get("market"), _num(x.get("price"))
        bars += meter(x["name"] or "—", m, "", "", HB.BLUE, "—" if m is None else f"model {m:.0%}")
        bars += (f'<div style="font-size:11.5px;color:{HB.GOLD};margin:-8px 0 10px;">'
                 + (f"market {k:.0%}" if k is not None else "no market line yet")
                 + (f" · best price {pr:+.0f}" if pr is not None else "") + '</div>')
    return head + bars


def render_tennis(g: Dict) -> None:
    import streamlit as st
    st.markdown(tennis_html(g), unsafe_allow_html=True)
    if g.get("winner"):
        st.markdown(f"**Model's pick to win:** {g['winner']}"
                    + (f" ({g['chance']:.0%})" if g.get("chance") is not None else "")
                    + (f" · {g['use']}" if g.get("use") else ""))
    if g.get("money_pick"):
        pr = _num(g.get("money_price"))
        st.markdown(f"💰 **Money pick:** {g['money_pick']}" + (f" at {pr:+.0f}" if pr is not None else ""))
    if not g.get("priced"):
        st.caption("No sportsbook has posted this match yet — the model's read only. Prices fill in when books post.")
    st.caption("Blue: the model's chance each player wins. Gold: the market's chance (no-vig) and the best price. "
               "Tennis is tracking only (beta): its record is not proven yet.")



# --------------------------------------------------------------------------- UFC (Nov 25)
def build_fight(b: Dict) -> Dict:
    """One bout (ufc_engine.card_from_odds) -> the fight card: market only -- H2 has no UFC model."""
    pa = _num(b.get("p_a"))
    try:
        import ufc_engine as UE
        lines = UE.book_lines(b)
    except Exception:                                           # noqa: BLE001
        lines = {}
    from datetime import datetime as _dt
    import pytz
    try:
        t = _dt.fromisoformat(str(b.get("commence")).replace("Z", "+00:00")).astimezone(pytz.timezone("US/Eastern"))
        when = t.strftime("%-I:%M %p")
    except (TypeError, ValueError):
        when = ""
    return {"league": "UFC", "label": "UFC", "time": when, "game": f"{b.get('a')} vs {b.get('b')}",
            "fighters": [{"name": b.get("a"), "market": pa, "price": b.get("best_a")},
                         {"name": b.get("b"), "market": None if pa is None else 1 - pa, "price": b.get("best_b")}],
            "books": b.get("books") or 0, "total": lines.get("total") or "", "spread": lines.get("spread") or ""}


def fight_html(g: Dict) -> str:
    a, b = g["fighters"]
    head = (f'<div style="background:linear-gradient(110deg,{HB.NAVY},{HB.SLATE});border:1px solid {HB.EDGE};'
            f'border-radius:14px;padding:16px 20px;margin:4px 0 10px;">'
            f'<div style="color:{HB.INK_SOFT};font-size:12.5px;letter-spacing:.06em;">UFC · {g.get("time") or ""}</div>'
            f'<div style="color:{HB.INK};font-size:22px;font-weight:800;line-height:1.2;margin-top:3px;">'
            f'{a["name"] or ""} <span style="color:{HB.GRAY};">vs</span> {b["name"] or ""}</div>'
            f'<div style="margin-top:9px;">{HB.bet_chip("Info only")}</div></div>')
    bars = ""
    for x in g["fighters"]:
        k, pr = x.get("market"), _num(x.get("price"))
        bars += meter(x["name"] or "—", k, "", "", HB.GOLD, "—" if k is None else f"market {k:.0%}")
        bars += (f'<div style="font-size:11.5px;color:{HB.GOLD};margin:-8px 0 10px;">'
                 + (f"best price {pr:+.0f}" if pr is not None else "no price yet") + '</div>')
    return head + bars


def render_fight(g: Dict) -> None:
    import streamlit as st
    st.markdown(fight_html(g), unsafe_allow_html=True)
    bits = [f"Priced by {g['books']} book{'s' if g['books'] != 1 else ''}"]
    if g.get("total"):
        bits.append(f"Rounds {g['total']}")
    st.markdown(" · ".join(bits))
    st.caption("H2 has no UFC model yet: these are the market's no-vig chances (the median across books) and the best "
               "price, so a pick is grounded in the odds — not a pick from us. The full card and logging are on the "
               "Fight card page.")



# --------------------------------------------------------------------------- extras (Nov 25)
def profile(results: List[Dict], ratings: Optional[Dict], team: str, loose: bool = True, n: int = 5) -> Optional[Dict]:
    """One team from this season's results: offense / defense rank in the ratings model (1 = best) and its last `n`
    results ("W", margin), newest last. None when the archive doesn't know the team."""
    import intl_hoops as I
    names = {g.get(k) for g in results or [] for k in ("home_team", "away_team") if g.get(k)}
    mine = I.find_team(names, team, loose) if names else None
    if mine is None:
        return None
    games = []
    for g in results or []:
        hp, ap = _num(g.get("home_points")), _num(g.get("away_points"))
        if hp is None or ap is None:
            continue
        if g.get("home_team") == mine:
            games.append((str(g.get("date") or ""), hp - ap))
        elif g.get("away_team") == mine:
            games.append((str(g.get("date") or ""), ap - hp))
    games.sort()
    last = games[-n:]
    out = {"name": mine, "games": len(games), "last": [("W" if m > 0 else "L" if m < 0 else "T", m) for _, m in last]}
    if ratings and ratings.get("off") and mine in ratings["off"]:
        off, de = ratings["off"], ratings.get("def") or {}
        out["off_rank"] = 1 + sum(1 for v in off.values() if v > off[mine])
        out["def_rank"] = 1 + sum(1 for v in de.values() if v > de.get(mine, 0)) if mine in de else None
        out["n_teams"] = len(off)
    return out


def pace_pct(results: List[Dict], total) -> Optional[float]:
    """Where the model's total sits among this season's finished games (0 = the lowest-scoring, 1 = the highest)."""
    t = _num(total)
    tots = [hp + ap for g in results or [] for hp, ap in [(_num(g.get("home_points")), _num(g.get("away_points")))]
            if hp is not None and ap is not None]
    if t is None or len(tots) < 20:
        return None
    return sum(1 for x in tots if x < t) / len(tots)


def form_html(p: Optional[Dict], label: str) -> str:
    if not p:
        return (f'<div style="flex:1;min-width:150px;"><div style="font-weight:700;color:{HB.INK};">{label}</div>'
                f'<div style="color:{HB.GRAY};font-size:12px;">No results on file yet</div></div>')
    dots = "".join(f'<span title="{"won" if r == "W" else "lost"} by {abs(m):g}" style="display:inline-block;width:22px;'
                   f'height:22px;line-height:22px;text-align:center;border-radius:6px;margin-right:3px;font-size:11.5px;'
                   f'font-weight:800;background:{HB.WIN if r == "W" else HB.LOSS if r == "L" else HB.GRAY}33;'
                   f'color:{HB.WIN if r == "W" else HB.LOSS if r == "L" else HB.GRAY};">{r}</span>'
                   for r, m in p["last"])

    def rank_bar(title, rk):
        if rk is None or not p.get("n_teams"):
            return ""
        frac = 1 - (rk - 1) / max(1, p["n_teams"] - 1)
        return meter(title, frac, "worst", "best", HB.BLUE, f"#{rk} of {p['n_teams']}")
    return (f'<div style="flex:1;min-width:150px;"><div style="font-weight:700;color:{HB.INK};margin-bottom:4px;">'
            f'{label}</div><div style="margin-bottom:8px;">{dots or "—"}</div>'
            + rank_bar("Offense", p.get("off_rank")) + rank_bar("Defense", p.get("def_rank")) + '</div>')


def render_extras(g: Dict, w: Dict, day: str, key: str) -> None:
    """Pace, each team's form and offense / defense rank, and (owner) log boxes -- under the game card."""
    import streamlit as st
    lg = g.get("league") or ""
    try:
        res, rat = _season(lg, day)
    except Exception:                                           # noqa: BLE001
        res, rat = [], None
    if res:
        loose = lg != "NCAAMB"
        hp, ap = profile(res, rat, g.get("home") or "", loose), profile(res, rat, g.get("away") or "", loose)
        pc = pace_pct(res, g.get("model_total"))
        html = ""
        if pc is not None:
            html += meter("Pace — the model's total vs this season's games", pc, "low-scoring", "high-scoring",
                          HB.BLUE, f"higher than {pc:.0%} of games")
        html += (f'<div style="display:flex;gap:18px;flex-wrap:wrap;margin-top:6px;">'
                 + form_html(ap, f"{g.get('away')} · last {len((ap or {}).get('last') or [])}")
                 + form_html(hp, f"{g.get('home')} · last {len((hp or {}).get('last') or [])}") + '</div>')
        st.markdown("**The matchup**")
        st.markdown(html, unsafe_allow_html=True)
        st.caption("Offense / defense: each team's rank in the ratings model the projection uses (adjusted for "
                   "opponents and home court). Form: the last results, newest on the right (hover for the margin). "
                   "Context only — the projection already counts all of it.")
    try:
        _injuries(w.get("sport") or lg, g.get("away") or "", g.get("home") or "", day, key)
    except Exception:                                           # noqa: BLE001
        pass
    if (w.get("sport") or lg) == "NHL":
        try:
            _nhl(g.get("away") or "", g.get("home") or "", day)
        except Exception:                                       # noqa: BLE001
            pass
    try:                                                        # Nov 25 (owner): the Game Lab's simulation, in the card
        _simulation(w)
    except Exception:                                           # noqa: BLE001
        pass
    if (w.get("sport") or lg) == "NBA":
        try:
            _rotations(g.get("away") or "", g.get("home") or "", day, key=key)
        except Exception:                                       # noqa: BLE001
            pass
    _log_boxes(g, w, day, key)


def _future(day) -> bool:
    """ESPN leaves an old expected-return date on long-term injuries; only a date still ahead is worth showing."""
    try:
        from datetime import date as _d
        return bool(day) and _d.fromisoformat(str(day)[:10]) >= _d.today()
    except ValueError:
        return False


def injuries_html(team: str, flagged) -> str:
    """One team's column of tonight's injury report: out first, then questionable, with the expected return."""
    import injury_check as IC
    items = "".join(
        f'<div style="font-size:13px;margin:2px 0;color:{HB.INK};">{IC.chip(e["status"]).split(" ")[0]} '
        f'<b>{e["name"]}</b>{" · " + e["pos"] if e.get("pos") else ""}'
        f'<span style="color:{HB.INK_SOFT};"> — {e.get("label") or e["status"]}'
        f'{" (" + e["type"] + ")" if e.get("type") else ""}'
        f'{" · back ~" + e["returns"][5:].replace("-", "/") if _future(e.get("returns")) and e["status"] == "out" else ""}'
        f'</span></div>' for e in flagged) or f'<div style="color:{HB.INK_SOFT};font-size:13px;">Nobody listed</div>'
    return (f'<div style="flex:1;min-width:220px;"><div style="color:{HB.INK_SOFT};font-size:12px;'
            f'letter-spacing:.05em;margin-bottom:3px;">{str(team).upper()}</div>{items}</div>')


def player_link(name: str, label: str, key: str, wkey: str) -> None:
    """Nov 25 (owner: "the players' names inside the game cards ... a link that opens their player card with a return to
    the game card"): a name drawn as a link; tapping it opens his card inside the game card (today_visual._game_dialog
    reads `{key}_player` and shows "← Back to the game")."""
    import streamlit as st
    if st.button(label, key=wkey, type="tertiary", help=f"Open {name}'s player card"):
        st.session_state[f"{key}_player"] = name
        st.rerun(scope="fragment")


def _ls(sport: str, name: str) -> str:
    """💎 in front of a player with a value long shot tonight (today_visual.ls_mark)."""
    try:
        import today_visual as TV
        return TV.ls_mark(sport, name)
    except Exception:                                           # noqa: BLE001
        return ""


def _injuries(sport: str, away: str, home: str, day: str, key: str = "gc") -> None:
    """Nov 25 (PropSeason scrub): who's out on each side tonight, from ESPN's injury report (today's games only). Each
    name opens his player card."""
    import streamlit as st
    import injury_check as IC
    if sport not in IC.LEAGUES or not IC.live_for(day):
        return
    rep = IC.entries(sport)
    if not rep:
        return
    st.markdown("**Who's out**")
    for col, team in zip(st.columns(2), (away, home)):
        with col:
            st.markdown(f'<div style="color:{HB.INK_SOFT};font-size:12px;letter-spacing:.05em;">{str(team).upper()}</div>',
                        unsafe_allow_html=True)
            flagged = IC.for_team(sport, team, rep)
            if not flagged:
                st.caption("Nobody listed")
            for i, e in enumerate(flagged):
                c1, c2 = st.columns([2, 3])
                with c1:
                    player_link(e["name"], f'{IC.chip(e["status"]).split(" ")[0]} {e["name"]}', key,
                                f"{key}_inj_{IC._norm(team)}_{i}")
                c2.markdown(f'<div style="color:{HB.INK_SOFT};font-size:12.5px;padding-top:6px;">'
                            f'{e.get("pos") or ""} — {e.get("label") or e["status"]}'
                            f'{" (" + e["type"] + ")" if e.get("type") else ""}'
                            f'{" · back ~" + e["returns"][5:].replace("-", "/") if _future(e.get("returns")) and e["status"] == "out" else ""}'
                            f'</div>', unsafe_allow_html=True)
    st.caption("🚑 out · ⚠️ questionable — ESPN's injury report, checked every 10 minutes. The saved projection was "
               "built before some of this news; picks on players ruled out are taken off the boards. Tap a name for "
               "his card.")


def _nhl(away: str, home: str, day: str) -> None:
    """Nov 25 (PropSeason scrub item 2): goalies, records, back-to-back, scoring share (nhl_card.py)."""
    import streamlit as st
    import nhl_card as NC

    @st.cache_data(ttl=600, show_spinner=False, max_entries=8)
    def board(d):
        return NC._get(d)

    @st.cache_data(ttl=600, show_spinner=False, max_entries=4)
    def props(d):
        import todays_best as TB
        try:
            return TB.load_all_props("NHL", d)
        except Exception:                                       # noqa: BLE001
            return []
    NC.render(away, home, day, props(day), get=board)


def sim_cells(sim: Dict, away: str, home: str, league: str) -> List[tuple]:
    """(label, value) pairs for the card's simulation strip."""
    import game_sim as GS
    noun = GS.unit(league)
    cells = [(f"{away} likely range", GS.range_text(*sim["away_range"], league)),
             (f"{home} likely range", GS.range_text(*sim["home_range"], league)),
             ("Total likely range", GS.range_text(*sim["total_range"], league))]
    if sim.get("overtime") is not None:
        cells.append(("Goes to overtime", f"{sim['overtime']:.0%}"))
        cells.append(("One-goal game", f"{sim['close']:.0%}"))
    else:
        cells.append((f"Decided by {GS.CLOSE[sim['family']]} or fewer", f"{sim['close']:.0%}"))
    cells.append((f"Decided by {GS.BLOWOUT[sim['family']]}+ {noun}", f"{sim['blowout']:.0%}"))
    return cells


def _simulation(w: Dict) -> None:
    """20,000 games simulated around the model's projection (game_sim.py) -- the Game Lab's "One game, up close",
    now in the game card: the likely ranges and how often it's close or lopsided. One model, one answer."""
    import streamlit as st
    import game_sim as GS
    p = w.get("_full") or {}
    league = w.get("sport") or p.get("sport") or ""
    if p.get("model_margin") is None or p.get("model_total") is None:
        return
    sim = GS.simulate(league, p.get("model_margin"), p.get("model_total"), key=p.get("game_id"))
    if not sim:
        return
    away, home = p.get("away") or "", p.get("home") or ""
    st.markdown("**Simulated finishes**")
    st.markdown('<div style="display:flex;gap:8px;flex-wrap:wrap;">' + "".join(
        f'<div style="flex:1;min-width:120px;background:{HB.NAVY};border:1px solid {HB.EDGE};border-radius:10px;'
        f'padding:8px 10px;"><div style="color:{HB.INK_SOFT};font-size:11.5px;">{lab}</div>'
        f'<div style="color:{HB.INK};font-size:18px;font-weight:800;">{val}</div></div>'
        for lab, val in sim_cells(sim, away, home, league)) + '</div>', unsafe_allow_html=True)
    st.caption(f"{sim['n_sims']:,} games simulated around the model's projected score ({away} "
               f"{sim['proj_away_score']:.1f} — {home} {sim['proj_home_score']:.1f}). Likely range = 8 of 10 simulated "
               "games. It doesn't know injuries or rest — see Who's out above.")


def _bundle_game(sport: str, games: List[Dict], away: str, home: str) -> Optional[Dict]:
    """The schedule entry for this matchup (names matched loosely: 'Celtics' vs 'Boston Celtics')."""
    import injury_check as IC

    def hit(a, b):
        a, b = IC._norm(a), IC._norm(b)
        return bool(a and b) and (a == b or a.endswith(" " + b) or b.endswith(" " + a) or a.startswith(b + " ")
                                  or b.startswith(a + " "))
    return next((x for x in games or [] if (hit(x.get("home"), home) or hit(x.get("home_abbr"), home))
                 and (hit(x.get("away"), away) or hit(x.get("away_abbr"), away))), None)


def _rotation_data(sport: str, day: str, away: str, home: str):
    """(schedule entry, league player-games, tonight's saved props) -- cached 15 minutes."""
    import streamlit as st

    @st.cache_data(ttl=900, show_spinner="Reading the rotations…", max_entries=16)
    def load(sp, d, a, h):
        import position_data as PD
        import todays_best as TB
        x = _bundle_game(sp, PD.list_games(sp, d), a, h)
        if not x:
            return None, [], []
        b = PD.load_bundle(sp, d, x, False)
        try:
            props = TB.load_all_props(sp, d)
        except Exception:                                       # noqa: BLE001
            props = []
        return x, (b.get("props") or {}).get("pgames") or [], props
    return load(sport, day, away, home)


def _rotations(away: str, home: str, day: str, sport: str = "NBA", key: str = "gc") -> None:
    """Nov 25 (PropSeason scrub item 3): starters / bench / deep bench with last-10 minutes and H2's projection. Each
    name opens his player card (owner, Nov 25)."""
    import streamlit as st
    import injury_check as IC
    import rotation_panel as RP
    x, pg, props = _rotation_data(sport, day, away, home)
    if not x or not pg:
        return
    inj = {}
    if IC.live_for(day):
        inj = {IC._norm(e["name"]): e["status"] for e in IC.entries(sport)}
    proj = RP.proj_minutes(props)
    ra, rh = RP.rotation(pg, x["away_id"]), RP.rotation(pg, x["home_id"])
    if not ra and not rh:
        return
    top = RP.top_minutes(ra, rh)
    st.markdown("**Rotation & minutes**")
    for col, team, rot in zip(st.columns(2), (x["away"], x["home"]), (ra, rh)):
        with col:
            st.markdown(f'<div style="color:{HB.INK_SOFT};font-size:12px;letter-spacing:.05em;">{str(team).upper()}</div>',
                        unsafe_allow_html=True)
            for label, lst in RP.groups(rot).items():
                if not lst:
                    continue
                st.markdown(f'<div style="color:{HB.GOLD};font-size:11.5px;font-weight:700;margin-top:4px;">'
                            f'{label.upper()}</div>', unsafe_allow_html=True)
                for i, r in enumerate(lst):
                    c1, c2 = st.columns([2, 3], vertical_alignment="center")
                    with c1:
                        player_link(r["name"], RP.tag(r["name"], inj) + _ls(sport, r["name"]) + r["name"], key,
                                    f"{key}_rot_{IC._norm(team)}_{label}_{i}")
                    c2.markdown(RP.bar_html(r, top, proj, inj), unsafe_allow_html=True)
    st.caption(RP.CAPTION + " 💎 = a value long shot tonight. Tap a name for his card.")


def _season(league: str, day: str):
    """(this season's finished games, the ratings fitted on them) -- cached 30 minutes per league and day."""
    import streamlit as st

    @st.cache_data(ttl=1800, show_spinner=False, max_entries=8)
    def load(lg, d):
        import hoops_games_page as HG
        import intl_hoops as I
        res = HG._season_results(lg, d)
        rat = I.ratings_weighted(res, [1.0] * len(res), hfa_prior=I.HFA_PRIOR.get(lg)) if res else None
        return res, rat
    return load(league, day)


def _log_boxes(g: Dict, w: Dict, day: str, key: str) -> None:
    """Owner build only: tick the Line pick / Money pick / Likely winner and log them, right from the card."""
    import streamlit as st
    import components as C
    if not C.is_owner() or not (w or {}).get("_full"):
        return
    import game_lines_table as GLT
    import log_ui as LU
    opts = []
    if w.get("best") and w.get("bet_market"):
        opts.append(("✓ Pick", f"📏 Line pick: {w['best']}"))
    if w.get("money_pick") and w.get("money_market"):
        opts.append(("✓ Money", f"💰 Money pick: {w['money_pick']}"))
    if w.get("winner"):
        opts.append(("✓ Winner", f"Likely winner: {w['winner']} ML"))
    if not opts:
        return
    st.markdown("**Log it** (only you see this)")
    ticks = [(0, col) for col, label in opts if st.checkbox(label, key=f"{key}_log_{col}")]
    items = GLT.line_items([w], ticks) if ticks else []
    LU.panel(items, f"{key}_panel", day, tag=f"{str(g.get('league') or '').lower()}-games")
