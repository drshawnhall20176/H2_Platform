"""
matchup_card.py — click a row on Position Matchups' Depth vs defense / Position breakout tabs (Nov 24).

Owner: "can we now do Depth vs defense and Position breakout (beta) so clicking a row will open up a card for those
metrics as well?" One player against the defense he faces tonight, in H2's colors (h2_brand.py):

  * the header: player, position, team vs the defense, role and minutes, the defense's verdict;
  * the numbers: the defense's rank at his spot (1 = softest), what it allows per game against the league average,
    the model's matchup adjustment, his recent average;
  * his recent games (and his games against this defense) as bars, with what this defense allows at his spot (gold
    dashed) and the league average (slate dotted) -- is he in a spot to beat what this defense usually gives up?
  * what the defense allows, stat by stat, and its trend.
Display only, like the tables: nothing here feeds the projections.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import h2_brand as HB


def _f(v) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def bars(recent: List[float], h2h: List[float]) -> List[Dict]:
    """Oldest left. Recent games ("Recent") then the games against this defense ("vs this D")."""
    out, i = [], 0
    rec = list(recent or [])[::-1]
    for k, v in enumerate(rec):
        back = len(rec) - k
        out.append({"Game": "Last" if back == 1 else f"{back} ago", "Order": i, "Value": v, "Kind": "Recent"})
        i += 1
    hh = list(h2h or [])[::-1]
    for k, v in enumerate(hh):
        out.append({"Game": f"vs D #{k + 1}", "Order": i, "Value": v, "Kind": "vs this defense"})
        i += 1
    return out


def chart(rows: List[Dict], allowed: Optional[float], league: Optional[float], unit: str):
    import altair as alt
    import pandas as pd
    df = pd.DataFrame(rows)
    if df.empty:
        return None
    order = list(df.sort_values("Order")["Game"])
    dom = ["Recent", "vs this defense"]
    base = alt.Chart(df).encode(x=alt.X("Game:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)))
    layers = [base.mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, width={"band": 0.7}).encode(
        y=alt.Y("Value:Q", title=unit, axis=alt.Axis(gridOpacity=0.12)),
        color=alt.Color("Kind:N", scale=alt.Scale(domain=dom, range=[HB.BLUE, HB.TEAL]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=[alt.Tooltip("Game:N"), alt.Tooltip("Kind:N"), alt.Tooltip("Value:Q", title=unit, format=".1f")]),
        base.mark_text(dy=-8, fontSize=12, fontWeight="bold", color=HB.INK_SOFT).encode(
            y="Value:Q", text=alt.Text("Value:Q", format=".3~f"))]
    for val, color, dash, label in ((allowed, HB.GOLD, [6, 4], "This D allows"), (league, HB.GRAY, [2, 3], "League avg")):
        if val is None:
            continue
        d = pd.DataFrame({"y": [val], "t": [f"{label} {val:.1f}"]})
        layers.append(alt.Chart(d).mark_rule(color=color, strokeDash=dash, strokeWidth=2.2).encode(
            y="y:Q", tooltip=[alt.Tooltip("t:N", title=label)]))
    return alt.layer(*layers).properties(height=250)


def render(d: Dict, sport: str, key: str) -> None:
    """d: {player, status, pos, team, defense, role, minutes, unit, recent: [..], h2h: [..], recent_avg, rank,
    n_teams, verdict, allowed, league, vs_league, model, group, blended, trend, allows}."""
    import streamlit as st
    import components as C
    head = (f'<div style="background:linear-gradient(110deg,{HB.NAVY},{HB.SLATE});border:1px solid {HB.EDGE};'
            f'border-radius:14px;padding:16px 20px;margin:4px 0 10px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;">'
            f'<div><div style="color:{HB.INK};font-size:22px;font-weight:800;">{d.get("player") or "—"}'
            + (f' <span style="font-size:13px;color:{HB.GOLD};">{d["status"]}</span>' if d.get("status") else "")
            + f'</div><div style="color:{HB.INK_SOFT};font-size:13.5px;margin-top:3px;">{sport} · {d.get("pos") or ""}'
            f' · {d.get("team") or ""} vs {d.get("defense") or ""} defense'
            + (f' · {d["role"]}' if d.get("role") else "") + (f' · {d["minutes"]} min' if d.get("minutes") else "")
            + f'</div><div style="margin-top:9px;">{HB.chip(d.get("verdict") or "—", HB.BLUE)}</div></div>'
            f'<div style="text-align:right;"><div style="color:{HB.INK_SOFT};font-size:12px;letter-spacing:.06em;">'
            f'DEFENSE AT HIS SPOT</div><div style="color:{HB.GOLD};font-size:26px;font-weight:800;">'
            f'{d.get("rank") or "—"}</div><div style="color:{HB.INK};font-size:13px;">rank · 1 = softest</div>'
            f'</div></div></div>')
    st.markdown(head, unsafe_allow_html=True)
    u = d.get("unit") or "PRA"
    al, lg = _f(d.get("allowed")), _f(d.get("league"))
    k = [{"icon": "🛡️", "value": "—" if al is None else f"{al:.1f}", "label": f"This D allows / g ({u})"},
         {"icon": "⚖️", "value": "—" if lg is None else f"{lg:.1f}", "label": f"League avg ({u})"},
         {"icon": "📈", "value": d.get("vs_league") or "—", "label": "vs league"},
         {"icon": "🧠", "value": d.get("model") or "—", "label": "Model matchup"},
         {"icon": "🔥", "value": "—" if d.get("recent_avg") is None else f"{float(d['recent_avg']):.1f}",
          "label": f"His last {len(d.get('recent') or [])} ({u})"}]
    if d.get("blended"):
        k[3] = {"icon": "🧪", "value": d["blended"], "label": "Blended (beta)"}
    C.kpi_row(k)
    ch = chart(bars(d.get("recent") or [], d.get("h2h") or []), al, lg, u)
    if ch is not None:
        st.altair_chart(ch, width="stretch", key=key)
        st.caption(f"**Blue** = his recent games, **teal** = his games against this defense. **Gold dashed** = what this "
                   f"defense allows at his spot per game ({'—' if al is None else f'{al:.1f}'}); **slate dotted** = the "
                   f"league average ({'—' if lg is None else f'{lg:.1f}'}). Display only — the projections use the "
                   "model's own matchup number.")
    else:
        st.caption("No recent games for him in the sample yet.")
    bits = [x for x in (("**What this defense allows:** " + d["allows"]) if d.get("allows") else "",
                        ("**Trend:** " + str(d["trend"])) if d.get("trend") else "",
                        ("**Group vs league:** " + str(d["group"])) if d.get("group") else "") if x]
    if bits:
        st.markdown("  \n".join(bits))
