"""
calib_chart.py — the calibration chart, split at the earned-chance change (Nov 21).

Owner, on "The proof" chart (Nov 21): the calibration points mixed every logged bet's chance -- the model's raw chance
before Nov 21, the earned chance after. Two series now: before (grey) and since (purple), each bucket's size and count
on hover, so the honest version can be judged on its own as it fills in.
"""
from __future__ import annotations

from typing import Dict, List, Sequence

ERA = "2026-11-21"          # logged chances are earned chances from this slate on (pick_ledger / props_money)


def split(bets: Sequence[Dict]) -> Dict[str, List[Dict]]:
    before = [b for b in bets if str(b.get("slate_date") or "") < ERA]
    since = [b for b in bets if str(b.get("slate_date") or "") >= ERA]
    return {"before": before, "since": since}


def figure(bets: Sequence[Dict], title: str):
    import plotly.graph_objects as go
    import betlog as B
    parts = split(bets)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines", line=dict(dash="dash", color="#94a3b8"),
                             showlegend=False, hoverinfo="skip"))
    any_ = False
    for key, name, color in (("before", "Before Nov 21 — the model's raw chance", "#94a3b8"),
                             ("since", "Since Nov 21 — earned chance", "#7c3aed")):
        cal = B.calibration(parts[key], n_bins=5) if parts[key] else []
        if not cal:
            continue
        any_ = True
        fig.add_trace(go.Scatter(
            x=[c["predicted"] for c in cal], y=[c["actual"] for c in cal], mode="markers", name=name,
            marker=dict(size=[max(8, min(22, 6 + c["n"] ** 0.5)) for c in cal], color=color,
                        line=dict(width=2, color="rgba(255,255,255,0.6)")),
            customdata=[[c["n"]] for c in cal],
            hovertemplate="said %{x:.0%} · hit %{y:.0%} · %{customdata[0]} bets<extra>" + name + "</extra>"))
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=28, b=10), title=title, template="plotly_white",
                      xaxis_range=[0, 1], yaxis_range=[0, 1], legend=dict(orientation="h", y=-0.2),
                      xaxis_title="Chance the model gave", yaxis_title="How often it hit")
    return fig if any_ else None


def caption(bets: Sequence[Dict]) -> str:
    import betlog as B
    n = len([b for b in B.pick_bets(split(bets)["since"]) if B._result(b) in ("win", "loss")
             and b.get("model_prob") is not None])
    return (f"Dots on the dashed line = honest chances; bigger dot = more bets. Purple = bets logged since Nov 21 with "
            f"the earned chance ({n} settled so far); grey = before, with the model's raw chance.")
