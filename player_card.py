"""
player_card.py — click into a player: one prop on one screen (Nov 24).

Owner, Nov 24: "I like the ability to click into a player or game to see things" -- without giving up any of H2's
data, and in H2's own look (h2_brand.py), not another site's. The card for one board play:

  * the header: player, team vs opponent, start time, the Bet? verdict and Use tag;
  * the numbers: tonight's line and price, the projection, the model's chance and the Earned chance, L5 / L10 and the
    whole recent stretch against tonight's line;
  * his recent games as bars against tonight's line (H2 blue = cleared for the pick's side, slate = didn't, gold dashed
    = the line, light-blue dotted = the projection);
  * the read: why the model likes it, its cushion and any warnings;
  * the game: blowout risk.

Recent games come from the play's own reads (slate_props: "_values", newest first) -- the same numbers L5 / L10 use.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import h2_brand as HB


def cleared(v: float, line: float, side: str) -> bool:
    import props_engine as PE
    if side == "Under":
        return (not PE.clears(v, line)) and v != PE.threshold(line)
    return bool(PE.clears(v, line))


def bars(values: List[float], line: Optional[float], side: str) -> List[Dict]:
    """Chronological (oldest left) bars: {"Game", "Value", "Cleared"}; the newest is "Last"."""
    vals = list(values or [])[:10][::-1]
    n = len(vals)
    out = []
    for i, v in enumerate(vals):
        back = n - i
        out.append({"Game": "Last" if back == 1 else f"{back} ago", "Order": i, "Value": v,
                    # no line (e.g. a King of the Court PRA read): every game in H2 blue, nothing to clear
                    "Cleared": True if line is None else (side in ("Over", "Under") and cleared(v, line, side))})
    return out


def hit_text(values: List[float], line: Optional[float], side: str, n: Optional[int] = None) -> str:
    vals = list(values or [])[:n] if n else list(values or [])
    if line is None or not vals or side not in ("Over", "Under"):
        return "—"
    k = sum(cleared(v, line, side) for v in vals)
    return f"{k}/{len(vals)} ({k / len(vals):.0%})"


def bar_chart(rows: List[Dict], line: Optional[float], projection: Optional[float], label: str):
    import altair as alt
    import pandas as pd
    df = pd.DataFrame(rows)
    if df.empty:
        return None
    order = list(df.sort_values("Order")["Game"])
    base = alt.Chart(df).encode(x=alt.X("Game:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)))
    barsl = base.mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, width={"band": 0.7}).encode(
        y=alt.Y("Value:Q", title=label, axis=alt.Axis(gridOpacity=0.12)),
        color=alt.Color("Cleared:N", scale=alt.Scale(domain=[True, False], range=[HB.BLUE, HB.GRAY_SOFT]),
                        legend=None),
        tooltip=[alt.Tooltip("Game:N"), alt.Tooltip("Value:Q", title=label),
                 alt.Tooltip("Cleared:N", title="Cleared tonight's line")])
    text = base.mark_text(dy=-8, fontSize=12, fontWeight="bold", color=HB.INK_SOFT).encode(
        y="Value:Q", text=alt.Text("Value:Q", format=".3~f"))
    layers = [barsl, text]
    if line is not None:
        ln = pd.DataFrame({"y": [line], "t": [f"Line {line:g}"]})
        layers.append(alt.Chart(ln).mark_rule(color=HB.GOLD, strokeDash=[6, 4], strokeWidth=2.5).encode(y="y:Q"))
        layers.append(alt.Chart(ln).mark_text(align="left", dx=-18, dy=-8, color=HB.GOLD, fontWeight="bold",
                                              fontSize=12).encode(y="y:Q", x=alt.datum(order[0], type="nominal"),
                                                                  text="t:N"))
    if projection is not None:
        pj = pd.DataFrame({"y": [projection], "t": [f"Projection {projection:g}"]})
        layers.append(alt.Chart(pj).mark_rule(color=HB.BLUE_SOFT, strokeDash=[2, 3], strokeWidth=1.5).encode(y="y:Q"))
        layers.append(alt.Chart(pj).mark_text(align="left", dx=-18, dy=-8, color=HB.BLUE_SOFT, fontSize=11.5).encode(
            y="y:Q", x=alt.datum(order[0], type="nominal"), text="t:N"))
    return alt.layer(*layers).properties(height=260)


SLOT_NAME = {"G": "guards", "F": "forwards", "C": "centers", "PG": "point guards", "SG": "shooting guards",
             "SF": "small forwards", "PF": "power forwards", "QB": "quarterbacks", "RB": "running backs",
             "WR": "wide receivers", "TE": "tight ends", "D": "defensemen"}


def matchup_chip(factor, slot=None) -> Optional[Dict]:
    """Nov 25: tonight's defense against his position, from the matchup factor the projection already uses (what this
    defense allows his position vs the league average, this season blended with last). Words, not a letter grade:
    {"text", "tone": soft | tough | even}; None when there's no factor."""
    try:
        f = float(factor)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    who = SLOT_NAME.get(str(slot or ""), "his position")
    pct = (f - 1) * 100
    if f >= 1.03:
        return {"text": f"{'Soft' if f >= 1.08 else 'Leans soft'} matchup · allows {pct:+.0f}% to {who}", "tone": "soft"}
    if f <= 0.97:
        return {"text": f"{'Tough' if f <= 0.92 else 'Leans tough'} matchup · allows {pct:+.0f}% to {who}",
                "tone": "tough"}
    return {"text": f"Even matchup · about league average vs {who}", "tone": "even"}


def minutes_rows(mins: List[float]) -> List[Dict]:
    vals = [v for v in list(mins or [])[:10] if v is not None][::-1]
    n = len(vals)
    return [{"Game": "Last" if n - i == 1 else f"{n - i} ago", "Order": i, "Minutes": float(v)}
            for i, v in enumerate(vals)]


def minutes_chart(rows: List[Dict], proj: Optional[float]):
    """His minutes, oldest left, against tonight's projected minutes (H2 blue bars, light-blue dotted rule)."""
    import altair as alt
    import pandas as pd
    df = pd.DataFrame(rows)
    if df.empty:
        return None
    order = list(df.sort_values("Order")["Game"])
    base = alt.Chart(df).encode(x=alt.X("Game:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)))
    layers = [base.mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, width={"band": 0.6}, color=HB.GRAY_SOFT).encode(
                  y=alt.Y("Minutes:Q", title="Minutes", axis=alt.Axis(gridOpacity=0.12)),
                  tooltip=[alt.Tooltip("Game:N"), alt.Tooltip("Minutes:Q", format=".1f")])]   # values on hover
    if proj is not None:
        pj = pd.DataFrame({"y": [proj], "t": [f"Tonight ~{proj:.0f}"]})
        layers.append(alt.Chart(pj).mark_rule(color=HB.BLUE_SOFT, strokeDash=[2, 3], strokeWidth=1.8).encode(y="y:Q"))
        layers.append(alt.Chart(pj).mark_text(align="left", dx=-18, dy=-8, color=HB.BLUE_SOFT, fontSize=11.5).encode(
            y="y:Q", x=alt.datum(order[0], type="nominal"), text="t:N"))
    return alt.layer(*layers).properties(height=170)


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def read_bullets(p: Dict, bet: str = "") -> List[str]:
    """Nov 25 (owner: "the read can be more descriptive ... explain why form is 14.5, what the matchup percentage
    means"): the pick explained in plain bullets, from the same numbers the model used. Markdown strings."""
    import re
    side, line, mkt = p.get("Side") or "", _f(p.get("Line")), p.get("Market") or "the stat"
    vals = [v for v in (p.get("_values") or []) if v is not None]
    why = str(p.get("Why") or "")
    out: List[str] = []
    m = re.search(r"form (-?\d+(?:\.\d+)?)", why)
    form = float(m.group(1)) if m else None
    if form is not None:
        rel = "" if line is None else (f" — {abs(form - line):.1f} {'above' if form > line else 'below'} tonight's "
                                       f"line of {line:g}" if abs(form - line) >= 0.05 else " — right on tonight's line")
        out.append(f"**Recent form {form:g} {mkt}.** His average over his recent games, weighted so newer games count "
                   f"more (a game 4 back counts half as much as his last one)"
                   + (", including some of last season's games" if "incl. last season" in why else "") + f"{rel}.")
    elif vals:
        avg = sum(vals[:10]) / len(vals[:10])
        out.append(f"**Recent form:** {avg:.1f} {mkt} a game over his last {len(vals[:10])}.")
    fac = _f(p.get("_factor"))
    if fac is None:
        mm = re.search(r"matchup ([+-]\d+)%", why)
        fac = 1 + int(mm.group(1)) / 100 if mm else None
    if fac is not None:
        who = SLOT_NAME.get(str(p.get("_slot") or ""), "players at his position")
        pct = (fac - 1) * 100
        if abs(pct) < 0.5:
            out.append(f"**Matchup: even.** Tonight's defense allows about the league average to {who}, so the model "
                       "leaves his numbers as they are.")
        else:
            out.append(f"**Matchup {pct:+.0f}%.** Tonight's defense has allowed {abs(pct):.0f}% "
                       f"{'more' if pct > 0 else 'less'} than the league average to {who} this season (blended with "
                       f"last season early on), so the model moves his projection {'up' if pct > 0 else 'down'} "
                       f"{abs(pct):.0f}%.")
    pm = _f(p.get("_proj_min"))
    mins = [v for v in (p.get("_mins") or []) if v is not None][:10]
    if pm is not None and mins:
        avg_m = sum(mins) / len(mins)
        out.append(f"**Minutes: about {pm:.0f} tonight** vs {avg_m:.1f} a game lately. Minutes drive everything — "
                   "the projection is his rate per minute times the minutes he's expected to play.")
    proj = _f(p.get("Projection"))
    if proj is not None and line is not None:
        d = proj - line
        lean = "Over" if d > 0 else "Under"
        out.append(f"**Projection {proj:.1f} vs the line {line:g}** — {abs(d):.1f} {'above' if d > 0 else 'below'}, "
                   f"which is why the model leans **{lean}**. It's built from his form, minutes, the matchup and the "
                   "game's expected pace and score.")
    if line is not None and vals and side in ("Over", "Under"):
        out.append(f"**Track record vs this line:** {hit_text(vals, line, side, 10)} of his last "
                   f"{min(10, len(vals))} games would have cashed the {side}.")
    mc, ec = _f(p.get("ModelProb")), _f(p.get("_earned"))
    if mc is not None:
        out.append(f"**Model chance {mc:.0%}**" + (f", **earned chance {ec:.0%}** — the sportsbook's own chance plus the "
                                                  "part of the model's disagreement that its track record has earned. "
                                                  "When the two differ, trust the earned chance" if ec
                                                  is not None else "") + ".")
    verdict = {"🃏": "🃏 **Bet** — this pick type has passed testing on real results.",
               "🧪": "🧪 **Tracking** — a candidate rule we're testing with small stakes; not proven yet.",
               "Info": "**Info only** — shown for context; this kind of pick hasn't earned a bet."}
    short = None
    try:
        import game_previews as GP
        short = GP.earned_short(p) if str(bet or "").startswith("🧪") else None
    except Exception:                                           # noqa: BLE001
        short = None
    if short:
        pr = "" if short["price"] is None else f" at {short['price']:+.0f}"
        out.append(f"🧪 **Tracking, not a bet** — his pick type has a winning record, but this pick's earned chance "
                   f"({short['earned']:.0%}) doesn't clear the {short['needed']:.1%} it needs to break even{pr}. "
                   "We track it instead of betting it.")
    else:
        for k, v in verdict.items():
            if str(bet or "").startswith(k):
                out.append(v)
                break
    flags = why.split(" · ", 1)[1] if " · " in why else ""
    for f in [x.strip() for x in flags.split(";") if x.strip()]:
        out.append(f"ℹ️ {f}")
    for w in p.get("Warnings") or []:
        out.append(f"⚠️ {w}")
    if p.get("UseWhy"):
        out.append(f"**Use:** {p['UseWhy']}")
    return out


def extras_on() -> bool:
    """Nov 25: the newest card pieces (matchup chip, minutes chart) show only in the commercial layout -- a
    commercial deployment, or the owner previewing it -- until the owner promotes them."""
    try:
        import streamlit as st
        import nav_layout as NL
        return bool(NL.is_commercial(st.secrets.get("AUDIENCE", "owner"), st.session_state.get(NL.PREVIEW_KEY)))
    except Exception:                                           # noqa: BLE001
        return False


def _pct(x) -> str:
    try:
        return f"{float(x):.0%}"
    except (TypeError, ValueError):
        return "—"


def opponent(game, team) -> Optional[str]:
    """Nov 25: "Brooklyn Nets @ Milwaukee Bucks" + "Milwaukee Bucks" -> "Brooklyn Nets" (None when unsure)."""
    parts = [x.strip() for x in str(game or "").replace(" vs ", " @ ").split(" @ ")]
    t = str(team or "").strip().lower()
    if len(parts) != 2 or not t:
        return None
    a, b = parts
    if a.lower() == t or (t and t in a.lower()):
        return b
    if b.lower() == t or (t and t in b.lower()):
        return a
    return None


def injury_note(p: Dict, sport: str, status=None) -> str:
    """Nov 25 (PropSeason scrub): what tonight's ESPN injury report says about him, checked when the card opens."""
    try:
        import injury_check as IC
        state = p.get("_inj") or (status or IC.status)(sport, p.get("Player") or p.get("player"))
    except Exception:                                           # noqa: BLE001
        return ""
    if state == "out":
        return "🚑 Out tonight on the injury report — this pick won't play. Don't bet it."
    if state == "questionable":
        return "⚠️ Questionable tonight on the injury report — check the news before betting."
    return ""


def from_row(r: Dict) -> Dict:
    """Nov 24: a saved pick row (Today's best, the college props section, a long shot) in the board-play shape the
    card reads. Board plays pass through unchanged."""
    if r.get("Player") and "Side" in r:
        return r
    use = ("💰 " if r.get("money") else "") + ("🔒 " if r.get("lock") else "") + str(r.get("use") or "")
    return {"Player": r.get("player") or r.get("Player"), "PlayerId": r.get("pid"), "Team": r.get("team") or r.get("Team"),
            "Opp": opponent(r.get("game"), r.get("team") or r.get("Team")), "Time": r.get("time"), "Side": r.get("side"), "Line": r.get("line"),
            "Market": r.get("market") or r.get("Market"), "RealPrice": r.get("price"),
            "Projection": r.get("projection") if r.get("projection") is not None else r.get("Projection"),
            "ModelProb": r.get("raw_chance") if r.get("raw_chance") is not None else r.get("chance"),
            "_earned": r.get("earned"), "_values": r.get("values") or [], "Why": r.get("why"),
            "Warnings": r.get("warnings") or [], "Use": use.strip(), "Game": r.get("game"),
            "_mins": r.get("mins") or [], "_proj_min": r.get("proj_min"), "_factor": r.get("factor"),
            "_slot": r.get("slot"), "_inj": r.get("_inj")}


def picker(rows, sport_of, key: str, label: str = "🔎 Open a player card") -> None:
    """A 'pick a player' box over a list of rows; the chosen one opens as a card right under it."""
    import streamlit as st
    rows = [r for r in rows or [] if (r.get("Player") or r.get("player"))]
    if not rows:
        return
    def _name(i):
        c = from_row(rows[i])
        ln = c.get("Line")
        return (f"{c.get('Player')} — {c.get('Side') or ''} {'' if ln is None else f'{ln:g}'} {c.get('Market') or ''}"
                f" ({c.get('Time') or ''})")
    i = st.selectbox(f"{label} ({len(rows)})", [None] + list(range(len(rows))), key=key,
                     format_func=lambda i: "Pick a player…" if i is None else _name(i))
    if i is None:
        return
    import game_previews as GP
    c, sp = from_row(rows[i]), sport_of(rows[i])
    with st.container(border=True):
        render(c, sp, bet=GP.prop_bet(sp, str(c.get("Use") or ""), c))


def render(p: Dict, sport: str, bet: str = "", kpis: Optional[List[Dict]] = None,
           extras: Optional[bool] = None) -> None:
    """One board play (Best Bets' row) as a card. `extras` (default: the commercial layout only) adds the matchup
    chip and the minutes chart."""
    import streamlit as st
    import components as C
    side, line = p.get("Side") or "", p.get("Line")
    vals = list(p.get("_values") or [])
    price = p.get("RealPrice")
    extras = extras_on() if extras is None else extras
    mc = matchup_chip(p.get("_factor"), p.get("_slot")) if extras else None
    mchip = "" if not mc else " " + HB.chip(mc["text"], {"soft": HB.BLUE}.get(mc["tone"], HB.GRAY))
    head = (f'<div style="background:linear-gradient(110deg,{HB.NAVY},{HB.SLATE});border:1px solid {HB.EDGE};'
            f'border-radius:14px;padding:16px 20px;margin:4px 0 10px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;">'
            f'<div><div style="color:{HB.INK};font-size:22px;font-weight:800;line-height:1.15;">{p.get("Player")}</div>'
            f'<div style="color:{HB.INK_SOFT};font-size:13.5px;margin-top:3px;">{sport} · {p.get("Team") or ""}'
            f' vs {p.get("Opp") or p.get("Versus") or ""} · {p.get("Time") or ""}</div>'
            f'<div style="margin-top:9px;display:flex;gap:6px;flex-wrap:wrap;">{HB.bet_chip(bet or "Info only")}'
            + (f' {HB.chip(str(p.get("_use") or p.get("Use")), HB.BLUE)}' if (p.get("_use") or p.get("Use")) else "")
            + mchip + f'</div></div>'
            f'<div style="text-align:right;"><div style="color:{HB.INK_SOFT};font-size:12px;letter-spacing:.06em;">'
            f'TONIGHT</div><div style="color:{HB.GOLD};font-size:26px;font-weight:800;">{side} {"" if line is None else f"{line:g}"}'
            f'</div><div style="color:{HB.INK};font-size:14px;">{p.get("Market") or ""}'
            + (f' · {float(price):+.0f}' if price is not None else "") + '</div></div></div></div>')
    st.markdown(head, unsafe_allow_html=True)
    note = injury_note(p, sport)
    if note:
        (st.error if note.startswith("🚑") else st.warning)(note)
    C.kpi_row(kpis or [
        {"icon": "📐", "value": "—" if p.get("Projection") is None else f"{float(p['Projection']):g}",
         "label": "Projection"},
        {"icon": "🎯", "value": _pct(p.get("ModelProb")), "label": "Model chance"},
        {"icon": "🧮", "value": _pct(p.get("_earned")), "label": "Earned chance"},
        {"icon": "5️⃣", "value": hit_text(vals, line, side, 5), "label": "Last 5 vs this line"},
        {"icon": "🔟", "value": hit_text(vals, line, side, 10), "label": "Last 10 vs this line"},
    ])
    rows = bars(vals, line, side)
    ch = bar_chart(rows, line, p.get("Projection"), p.get("Market") or "Value")
    if ch is not None:
        st.altair_chart(ch, width="stretch", key=f"pc_{p.get('PlayerId')}_{p.get('Market')}")
        if line is None:
            st.caption(f"His last {len(rows)} games (no book line posted tonight). **Light-blue dotted** = the model's "
                       "projection.")
        else:
            st.caption(f"His last {len(rows)} games against tonight's line — **blue** cleared it for the {side}, "
                       f"**slate** didn't. **Gold dashed** = the line; **light-blue dotted** = the model's projection. "
                       f"All {len(vals)} recent games: {hit_text(vals, line, side)}.")
    else:
        st.caption("His game-by-game bars appear after the board's next hourly rebuild (they're attached as the board "
                   "is built).")
    if extras:
        try:
            mrows = minutes_rows(p.get("_mins") or [])
            mch = minutes_chart(mrows, p.get("_proj_min")) if mrows else None
            if mch is not None:
                st.altair_chart(mch, width="stretch", key=f"pcm_{p.get('PlayerId')}_{p.get('Market')}")
                st.caption("His minutes in the same games" + (" — **light-blue dotted** = the minutes the model "
                           "projects tonight." if p.get("_proj_min") is not None else ".")
                           + " Fewer minutes than usual is the most common reason an Over misses.")
        except Exception:                                       # noqa: BLE001 -- the card never breaks on an extra
            pass
    why = [x for x in (p.get("Why"), p.get("UseWhy")) if x]
    warn = p.get("Warnings") or []
    st.markdown("**The read**")
    bullets = []
    if extras:                                                  # Nov 25: the explained read (commercial preview)
        try:
            bullets = read_bullets(p, bet)
        except Exception:                                       # noqa: BLE001
            bullets = []
    if bullets:
        st.markdown("\n".join("- " + b for b in bullets))
    else:
        st.markdown("  \n".join(["• " + str(w) for w in why] + ["⚠️ " + str(w) for w in warn]) or "—")
        try:                                                    # Nov 25: the earned-chance rule, live everywhere
            import game_previews as GP
            sh = GP.earned_short(p) if str(bet or "").startswith("🧪") else None
            if sh:
                st.caption(f"🧪 Tracking, not a bet: its earned chance ({sh['earned']:.0%}) doesn't clear the "
                           f"{sh['needed']:.1%} its price needs to break even.")
        except Exception:                                       # noqa: BLE001
            pass
    try:
        import game_previews as GP
        blow = GP.game_blowouts(sport, [p.get("Game")]).get(p.get("Game"), "—")
        st.caption(f"**Game:** {p.get('Game')} · Blowout risk {blow} — starters can sit late in a blowout, which "
                   "hurts Overs and helps Unders.")
    except Exception:                                           # noqa: BLE001
        pass
    try:                                                        # Nov 25: log it from the card (owner build only)
        log_box(p, sport)
    except Exception:                                           # noqa: BLE001 -- the card never breaks on the log box
        pass


def log_item(p: Dict, sport: str) -> Optional[Dict]:
    """The card's pick as a log_ui item (the same shape the boards' tick boxes log), or None when it can't be graded
    (no player, side or line -- e.g. a King of the Court read)."""
    side, line = p.get("Side"), p.get("Line")
    if not p.get("Player") or side not in ("Over", "Under") or line is None:
        return None
    chance = p.get("_earned") if p.get("_earned") is not None else p.get("ModelProb")
    return {"sport": sport, "kind": "Prop", "player": p.get("Player"), "pid": p.get("PlayerId"),
            "market": p.get("Market"), "side": side, "line": line, "game": p.get("Game"),
            "price": p.get("RealPrice"), "book": p.get("RealPriceBook") or p.get("PricedAt"),
            "chance": None if chance is None else float(chance),
            "pick": f"{p.get('Player')} {p.get('Market')} {side} {float(line):g}"}


def log_box(p: Dict, sport: str) -> None:
    """Owner build only (Nov 25, owner: "the ability to log bets straight from the player card ... an owner platform
    option but not discord user"): tick and log this pick with the usual log panel."""
    import streamlit as st
    import components as C
    if not C.is_owner():
        return
    it = log_item(p, sport)
    if it is None:
        return
    import log_ui as LU
    import pytz
    from datetime import datetime
    k = f"pclog_{p.get('PlayerId') or p.get('Player')}_{p.get('Market')}_{p.get('Side')}_{p.get('Line')}"
    if st.checkbox(f"📝 Log {it['pick']}", key=f"{k}_tick", help="Only you see this. The price, stake and real / "
                   "tracking choice are in the box that opens."):
        LU.panel([it], f"{k}_panel", datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d"),
                 tag=f"{str(sport).lower()}-props")
