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


def _pct(x) -> str:
    try:
        return f"{float(x):.0%}"
    except (TypeError, ValueError):
        return "—"


def from_row(r: Dict) -> Dict:
    """Nov 24: a saved pick row (Today's best, the college props section, a long shot) in the board-play shape the
    card reads. Board plays pass through unchanged."""
    if r.get("Player") and "Side" in r:
        return r
    use = ("💰 " if r.get("money") else "") + ("🔒 " if r.get("lock") else "") + str(r.get("use") or "")
    return {"Player": r.get("player") or r.get("Player"), "PlayerId": r.get("pid"), "Team": r.get("team") or r.get("Team"),
            "Opp": None, "Time": r.get("time"), "Side": r.get("side"), "Line": r.get("line"),
            "Market": r.get("market") or r.get("Market"), "RealPrice": r.get("price"),
            "Projection": r.get("projection") if r.get("projection") is not None else r.get("Projection"),
            "ModelProb": r.get("raw_chance") if r.get("raw_chance") is not None else r.get("chance"),
            "_earned": r.get("earned"), "_values": r.get("values") or [], "Why": r.get("why"),
            "Warnings": r.get("warnings") or [], "Use": use.strip(), "Game": r.get("game")}


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


def render(p: Dict, sport: str, bet: str = "", kpis: Optional[List[Dict]] = None) -> None:
    """One board play (Best Bets' row) as a card."""
    import streamlit as st
    import components as C
    side, line = p.get("Side") or "", p.get("Line")
    vals = list(p.get("_values") or [])
    price = p.get("RealPrice")
    head = (f'<div style="background:linear-gradient(110deg,{HB.NAVY},{HB.SLATE});border:1px solid {HB.EDGE};'
            f'border-radius:14px;padding:16px 20px;margin:4px 0 10px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;">'
            f'<div><div style="color:{HB.INK};font-size:22px;font-weight:800;line-height:1.15;">{p.get("Player")}</div>'
            f'<div style="color:{HB.INK_SOFT};font-size:13.5px;margin-top:3px;">{sport} · {p.get("Team") or ""}'
            f' vs {p.get("Opp") or p.get("Versus") or ""} · {p.get("Time") or ""}</div>'
            f'<div style="margin-top:9px;display:flex;gap:6px;flex-wrap:wrap;">{HB.bet_chip(bet or "Info only")}'
            + (f' {HB.chip(str(p.get("_use") or p.get("Use")), HB.BLUE)}' if (p.get("_use") or p.get("Use")) else "")
            + f'</div></div>'
            f'<div style="text-align:right;"><div style="color:{HB.INK_SOFT};font-size:12px;letter-spacing:.06em;">'
            f'TONIGHT</div><div style="color:{HB.GOLD};font-size:26px;font-weight:800;">{side} {"" if line is None else f"{line:g}"}'
            f'</div><div style="color:{HB.INK};font-size:14px;">{p.get("Market") or ""}'
            + (f' · {float(price):+.0f}' if price is not None else "") + '</div></div></div></div>')
    st.markdown(head, unsafe_allow_html=True)
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
    why = [x for x in (p.get("Why"), p.get("UseWhy")) if x]
    warn = p.get("Warnings") or []
    st.markdown("**The read**")
    st.markdown("  \n".join(["• " + str(w) for w in why] + ["⚠️ " + str(w) for w in warn]) or "—")
    try:
        import game_previews as GP
        blow = GP.game_blowouts(sport, [p.get("Game")]).get(p.get("Game"), "—")
        st.caption(f"**Game:** {p.get('Game')} · Blowout risk {blow} — starters can sit late in a blowout, which "
                   "hurts Overs and helps Unders.")
    except Exception:                                           # noqa: BLE001
        pass
