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
