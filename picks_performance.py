"""
picks_performance.py — how the picks worth betting are actually doing (Nov 24).

Owner, Nov 24: "I would like metrics made available that show me how these specific picks are performing. I would like
to see a dashed line that shows what a profitable baseline looks like." The picks are the ones the Bet? column calls
🃏 Bet or 🧪 Tracking, graded at the price they showed (pick_ledger.py, first sighting kept):

  * 🧪 Close-gap spreads (college basketball) -- ledger kind "cand", from Nov 23;
  * 🃏 💰 Money props -- ledger kind "money", every props sport;
  * 🃏 💰 Money game lines -- ledger kind "games" (paused for college basketball since Nov 22; shown as recorded).

Each group gets: the record, units at $1 a pick, return per $1, the hit rate the prices needed, and a running-units
chart against two references -- a dashed "profitable pace" line (+5% per $1, what a strong long-run betting edge earns:
about 55% at -110) and the break-even line at 0. The owner's Bet Log adds his own 🃏 / 🧪 bets the same way
(owner build only; the public pages show the model's picks alone).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Dict, List, Optional, Sequence

PACE = 0.05                                     # +5% per $1: a strong, sustainable edge (≈55% at -110)
SPORTS = ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB")
GROUPS = [
    {"key": "cand", "label": "🧪 Close-gap spreads · college basketball", "kind": "cand", "sports": ("NCAAMB",),
     "from": "2026-11-23",
     "what": "the model's side of the spread when the model and the market are within 2 points (Tracking)"},
    {"key": "money", "label": "🃏 💰 Money props", "kind": "money", "sports": SPORTS, "from": "2026-11-21",
     "what": "every 💰 player prop, the first time a board showed it"},
    {"key": "games", "label": "🃏 💰 Money game lines", "kind": "games", "sports": SPORTS, "from": "2026-11-21",
     "what": "every 💰 game line (college basketball's paused since Nov 22)"},
]


def _dec(price) -> Optional[float]:
    try:
        a = float(price)
    except (TypeError, ValueError):
        return None
    if -100 < a < 100:
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a)


def ledger_picks(kind: str, sports_: Sequence[str], start: str, end: str, get=None) -> List[Dict]:
    """Every graded pick of one ledger kind, oldest first: {day, sport, pick, result, price, units}. A pick with no price
    counts at -110."""
    import pick_ledger as PL
    out: List[Dict] = []
    d0, d1 = date.fromisoformat(max(start, PL.SINCE)), date.fromisoformat(end)
    while d0 <= d1:
        day = d0.isoformat()
        for sp in sports_:
            try:
                led = PL.load(kind, sp, day, get)
            except Exception:                                   # noqa: BLE001 -- one bad read never stops the page
                continue
            if not led.get("graded_at"):
                continue
            for r in sorted(led["rows"].values(), key=lambda x: x.get("first_seen") or ""):
                res = r.get("result")
                if res not in ("win", "loss", "push"):
                    continue
                d = _dec(r.get("price")) or _dec(-110)
                out.append({"day": day, "sport": sp, "pick": r.get("pick"), "result": res, "price": r.get("price"),
                            "units": (d - 1) if res == "win" else -1.0 if res == "loss" else 0.0, "dec": d})
        d0 += timedelta(days=1)
    return out


def bet_picks(bets: Sequence[Dict], want: Callable[[Dict], bool]) -> List[Dict]:
    """The owner's settled Bet Log singles that `want` keeps, oldest first, in units of their stake."""
    import betlog as B
    out = []
    for b in sorted(bets, key=lambda b: (str(b.get("slate_date") or ""), str(b.get("ts_placed") or ""))):
        if B.is_parlay_header(b) or B._ticket(b) or not want(b):
            continue
        res = B._result(b)
        if res not in ("win", "loss", "push"):
            continue
        st_ = float(b.get("stake") or 0) or 1.0
        pnl = B.bet_pnl(b) or 0.0
        out.append({"day": str(b.get("slate_date") or ""), "sport": b.get("sport"), "pick": B.bet_label(b),
                    "result": res, "price": b.get("entry_odds"), "units": pnl / st_, "dec": _dec(b.get("entry_odds"))})
    return out


def summary(picks: Sequence[Dict]) -> Dict:
    w = sum(p["result"] == "win" for p in picks)
    l = sum(p["result"] == "loss" for p in picks)
    pu = sum(p["result"] == "push" for p in picks)
    n = w + l
    units = sum(p["units"] for p in picks)
    decs = [p["dec"] for p in picks if p["result"] in ("win", "loss") and p.get("dec")]
    return {"wins": w, "losses": l, "pushes": pu, "n": n, "units": units,
            "hit_rate": w / n if n else None, "roi": units / (n + pu) if (n + pu) else None,
            "needed": (sum(1 / d for d in decs) / len(decs)) if decs else None,
            "pace_units": PACE * (n + pu)}


def curve(picks: Sequence[Dict], pace: float = PACE) -> List[Dict]:
    """Running totals by pick number: actual units, the profitable pace, the running hit rate and the rate needed."""
    out, units, w, n, need = [], 0.0, 0, 0, 0.0
    for i, p in enumerate(picks, 1):
        units += p["units"]
        if p["result"] in ("win", "loss"):
            n += 1
            w += p["result"] == "win"
            need += 1 / (p.get("dec") or _dec(-110))
        out.append({"Pick #": i, "Day": p["day"], "Pick": p.get("pick"), "Result": p["result"],
                    "Units": round(units, 2), "Profitable pace": round(pace * i, 2),
                    "Hit rate": (w / n) if n else None, "Needed": (need / n) if n else None})
    return out


def verdict(s: Dict) -> str:
    """One plain line: where the group stands against break-even and the profitable pace."""
    if not s["n"]:
        return "No graded picks yet."
    if s["n"] < 30:
        lead = f"Only {s['n']} graded — far too few to judge; "
    elif s["n"] < 100:
        lead = f"{s['n']} graded — an early read; "
    else:
        lead = f"{s['n']} graded — "
    if s["units"] >= s["pace_units"]:
        state = "at or above the profitable pace"
    elif s["units"] > 0:
        state = "profitable, below the +5% pace"
    else:
        state = "below break-even"
    return lead + state + "."


# --------------------------------------------------------------------------- display
ACTUAL, PACE_C, ZERO_C = "#3B82F6", "#94A3B8", "#64748B"


def chart(points: Sequence[Dict], title: str):
    """Running units (solid) with the profitable pace (dashed) and break-even (0) -- one y-axis, units."""
    import altair as alt
    import pandas as pd
    df = pd.DataFrame(points)
    if df.empty:
        return None
    long = pd.concat([df.assign(Series="Actual units", Value=df["Units"]),
                      df.assign(Series="Profitable pace (+5% per $1)", Value=df["Profitable pace"])])
    tip = [alt.Tooltip("Pick #:Q"), alt.Tooltip("Day:N"), alt.Tooltip("Pick:N"), alt.Tooltip("Result:N"),
           alt.Tooltip("Series:N"), alt.Tooltip("Value:Q", title="Units", format="+.2f")]
    color = alt.Color("Series:N", scale=alt.Scale(domain=["Actual units", "Profitable pace (+5% per $1)"],
                                                  range=[ACTUAL, PACE_C]),
                      legend=alt.Legend(orient="top", title=None))
    dash = alt.StrokeDash("Series:N", scale=alt.Scale(domain=["Actual units", "Profitable pace (+5% per $1)"],
                                                      range=[[1, 0], [6, 4]]), legend=None)
    lines = alt.Chart(long).mark_line(strokeWidth=2).encode(
        x=alt.X("Pick #:Q", title="Picks graded", axis=alt.Axis(tickMinStep=1, grid=False)),
        y=alt.Y("Value:Q", title="Units ($1 a pick)", axis=alt.Axis(gridOpacity=0.15)),
        color=color, strokeDash=dash, tooltip=tip)
    pts = alt.Chart(long[long["Series"] == "Actual units"]).mark_circle(size=40, opacity=0).encode(
        x="Pick #:Q", y="Value:Q", tooltip=tip)
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=ZERO_C, strokeWidth=1, opacity=0.7).encode(y="y:Q")
    return (zero + lines + pts).properties(height=240, title=title)


def rate_chart(points: Sequence[Dict], title: str):
    """Running hit rate (solid) against the rate the prices needed (dashed)."""
    import altair as alt
    import pandas as pd
    df = pd.DataFrame([p for p in points if p.get("Hit rate") is not None])
    if df.empty:
        return None
    long = pd.concat([df.assign(Series="Hit rate", Value=df["Hit rate"]),
                      df.assign(Series="Break-even (what the prices needed)", Value=df["Needed"])])
    dom = ["Hit rate", "Break-even (what the prices needed)"]
    return alt.Chart(long).mark_line(strokeWidth=2).encode(
        x=alt.X("Pick #:Q", title="Picks graded", axis=alt.Axis(tickMinStep=1, grid=False)),
        y=alt.Y("Value:Q", title="Hit rate", axis=alt.Axis(format="%", gridOpacity=0.15),
                scale=alt.Scale(domain=[0.2, 0.8], clamp=True)),
        color=alt.Color("Series:N", scale=alt.Scale(domain=dom, range=[ACTUAL, PACE_C]),
                        legend=alt.Legend(orient="top", title=None)),
        strokeDash=alt.StrokeDash("Series:N", scale=alt.Scale(domain=dom, range=[[1, 0], [6, 4]]), legend=None),
        tooltip=[alt.Tooltip("Pick #:Q"), alt.Tooltip("Day:N"), alt.Tooltip("Series:N"),
                 alt.Tooltip("Value:Q", title="Rate", format=".1%")]).properties(height=240, title=title)


def render_group(label: str, what: str, picks: Sequence[Dict], key: str) -> None:
    import streamlit as st
    import components as C
    s = summary(picks)
    with st.container(border=True):
        st.markdown(f"**{label}** — {what}")
        if not s["n"] and not s["pushes"]:
            st.caption("No graded picks yet.")
            return
        rec = f"{s['wins']}–{s['losses']}" + (f"–{s['pushes']}" if s["pushes"] else "")
        C.kpi_row([
            {"icon": "🧾", "value": rec, "label": "Record"},
            {"icon": "🎯", "value": f"{s['hit_rate']:.0%}" if s["hit_rate"] is not None else "—",
             "label": "Hit rate" + (f" (needed {s['needed']:.0%})" if s["needed"] else ""),
             "trend": None if s["hit_rate"] is None or not s["needed"] else
             ("good" if s["hit_rate"] >= s["needed"] else "bad")},
            {"icon": "💵", "value": f"{s['units']:+.2f}u", "label": f"Units (pace {s['pace_units']:+.2f}u)",
             "trend": "good" if s["units"] >= 0 else "bad"},
            {"icon": "📈", "value": f"{s['roi']:+.1%}" if s["roi"] is not None else "—", "label": "Return per $1"},
        ])
        st.caption(verdict(s))
        pts = curve(picks)
        c1, c2 = st.columns(2)
        ch = chart(pts, "Running units vs the profitable pace")
        if ch is not None:
            c1.altair_chart(ch, width="stretch", key=f"{key}_u")
        rc = rate_chart(pts, "Hit rate vs break-even")
        if rc is not None:
            c2.altair_chart(rc, width="stretch", key=f"{key}_r")
        with st.expander(f"Every graded pick ({len(picks)})"):
            import pandas as pd
            st.dataframe(pd.DataFrame([{"Day": p["day"], "League": p["sport"], "Pick": p["pick"],
                                        "Price": p["price"], "Result": p["result"], "Units": round(p["units"], 2)}
                                       for p in picks]), hide_index=True, width="stretch")


def render(today: str, bets: Optional[Sequence[Dict]] = None, load: Optional[Callable] = None) -> None:
    """The section: each group's record and charts; with `bets` (owner build), his own 🃏 / 🧪 bets too."""
    import streamlit as st
    end = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    st.caption("Graded at the price each pick showed, $1 a pick. **Dashed line** = a profitable pace of **+5% per $1** "
               "(what a strong long-run edge earns — about 55% at −110); the thin line at 0 is break-even. On the "
               "hit-rate chart the dashed line is what the prices needed. Small samples swing a lot: judge a group "
               "after 60–100 picks, not 10.")
    for g in GROUPS:
        try:
            picks = (load or ledger_picks)(g["kind"], g["sports"], g["from"], end)
        except Exception:                                       # noqa: BLE001
            picks = []
        render_group(g["label"], g["what"], picks, f"pp_{g['key']}")
    if bets is not None:
        def _tags(b):
            return {t.strip() for t in str(b.get("notes") or "").split(",") if t.strip()}
        mine_cg = bet_picks(bets, lambda b: "close-gap-test" in _tags(b))
        mine_bet = bet_picks(bets, lambda b: "money-pick" in _tags(b)
                             or (b.get("model_prob") is not None and float(b.get("model_prob") or 0) >= 0.5
                                 and "lean" not in _tags(b) and "close-gap-test" not in _tags(b)))
        render_group("Your 🧪 close-gap bets", "your Bet Log singles logged from a 🧪 Tracking line pick", mine_cg,
                     "pp_mine_cg")
        render_group("Your 🃏 Bet bets", "your Bet Log singles on tested picks (a model chance of 50%+, or 💰)",
                     mine_bet, "pp_mine_bet")
