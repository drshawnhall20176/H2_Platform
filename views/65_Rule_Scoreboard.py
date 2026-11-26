"""
65_Rule_Scoreboard.py -- the H2 Rulebook's scoreboard, in the Owner Office (Nov 26).

Every rule's stage, forward record, trend and distance to its next gate (rule_scoreboard.py, refreshed every morning),
then one rule's charts against the profitable pace, and the owner's own testing discipline from the Bet Log.
"""
from datetime import date, datetime, timedelta

import pandas as pd
import pytz
import streamlit as st

import components as C
import rule_scoreboard as RS

ET = pytz.timezone("US/Eastern")
C.base_css()
C.page_header("📈", "Rule scoreboard",
              "Every rule in the H2 Rulebook: where it stands, how it's trending, and how far it is from its next gate. "
              "Refreshed every morning from the graded picks.")


@st.cache_data(ttl=600, show_spinner="Reading the scoreboard…")
def _load():
    return RS.load()


rec = _load()
if not rec or not rec.get("rules"):
    st.info("The scoreboard hasn't been built yet. It runs every morning after the review (and can be run by hand from "
            "GitHub: the rule-scoreboard workflow).")
    st.stop()
st.caption(f"Graded through the slate before {rec['day']} · the last {rec.get('window', RS.WINDOW)} days · "
           "close gap since Nov 23. Paper and paused rules are scored exactly like live ones.")


def _pct(v, signed=False):
    if v is None:
        return "—"
    return f"{v * 100:+.1f}%" if signed else f"{v:.1%}"


def _trend(m):
    r7, r30 = m.get("roi7"), m.get("roi30")
    if r7 is None or r30 is None or (m.get("n7") or 0) < 10:
        return "—"
    return "↗ improving" if r7 > r30 + 0.02 else "↘ slipping" if r7 < r30 - 0.02 else "→ steady"


rules = rec["rules"]
f1, f2 = st.columns(2)
stages = ["Live test", "Paused", "Paper"]
pick_stage = f1.pills("Stage", stages, selection_mode="multi", default=stages, key="rs_stage")
sports_ = sorted({r["sport"] for r in rules})
pick_sport = f2.multiselect("Sports", sports_, placeholder="All sports", key="rs_sport")
shown = [r for r in rules if r["stage"] in (pick_stage or stages) and (not pick_sport or r["sport"] in pick_sport)]
order = {"Live test": 0, "Paused": 1, "Paper": 2}
shown.sort(key=lambda r: (order.get(r["stage"], 9), -(r["m"].get("n") or 0)))

_today = datetime.now(ET).date().isoformat()
fc = {id(r): RS.forecast(r, _today) for r in rules}            # Nov 26: when could each rule clear its next gate?
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Rules scored", len(rules))
k2.metric("Live test", sum(r["stage"] == "Live test" for r in rules))
k3.metric("Clear their next gate", sum(r["ready"] for r in rules))
k4.metric("On track this season", sum(fc[id(r)]["state"] in ("on_track", "proven") for r in rules),
          help="At its current return and pace, the rule reaches its next gate before its season ends. A forecast, "
               "not a promise -- the return moves as the sample grows.")
k5.metric("On a watch / pause line", sum(bool(r["health"]) for r in rules))

table = []
for r in shown:
    m = r["m"]
    gate_n = (RS.CLOSE_GAP_GATE["n"] if r["rule"] == "close_gap" else
              RS.GATE2["n"] if r["stage"] in ("Live test", "Paused") else RS.GATE1["n"])
    table.append({"Rule": r["label"], "Sport": r["sport"], "Stage": r["stage"],
                  "Record": f"{m.get('wins', 0)}–{m.get('n', 0) - m.get('wins', 0)}" if m.get("n") else "—",
                  "Hit / needed": f"{_pct(m.get('hit'))} / {_pct(m.get('needed'))}" if m.get("n") else "—",
                  "Return per $1": _pct(m.get("roi"), True), "90% range": (f"{_pct(m.get('lo'), True)} to "
                                                                          f"{_pct(m.get('hi'), True)}" if m.get("n") else "—"),
                  "Last 7 days": f"{_pct(m.get('roi7'), True)} ({m.get('n7', 0)})" if m.get("n") else "—",
                  "Last 30 days": f"{_pct(m.get('roi30'), True)} ({m.get('n30', 0)})" if m.get("n") else "—",
                  "Trend": _trend(m),
                  "Close agrees": f"{_pct(m.get('beat'))} of {m.get('moved')}" if m.get("beat") is not None else "—",
                  "Next": r["next"], "To next gate": min(1.0, (m.get("n") or 0) / gate_n),
                  "Ready?": "✅" if r["ready"] else "—", "Proof forecast": fc[id(r)]["text"],
                  "Health": r["health"] or "OK"})
st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch",
             column_config={"To next gate": st.column_config.ProgressColumn(
                 "Sample toward next gate", format="percent", min_value=0, max_value=1,
                 help="Graded picks so far against the next gate's sample size. The sample is only one of the gate's "
                      "checks: Ready? shows whether all of them hold.")})
st.caption("**Return per $1**: units won per dollar staked at the prices the picks carried. **90% range**: where the "
           "true return likely sits, from resampling whole slate days. **Trend** compares the last 7 days with the "
           "last 30. **Close agrees**: how often the closing line moved toward the pick (of the picks whose line moved). "
           "**Proof forecast**: at the current return and pace, roughly when the next gate's sample is reached (Gate 2 "
           "needs enough picks for the 90% low end to clear zero at that edge). Gate 1 (Paper → Live test): 100+ picks, +2%, both halves at or above break-even. Gate 2 (Live test → "
           "Proven): 300+ picks, +2%, 90% low end above zero, both halves up. Close gap: 200 games at 55%.")

# ---------- one rule, in detail ----------
st.markdown("#### One rule up close")
labels = [f"{r['label']} · {r['sport']} ({r['stage']})" for r in shown]
if not labels:
    st.stop()
i = st.selectbox("Rule", list(range(len(shown))), format_func=lambda j: labels[j], key="rs_one")
r = shown[i]
m = r["m"]
cols = st.columns(len(r["checks"]) or 1)
for col, (name, (ok, txt)) in zip(cols, r["checks"].items()):
    col.markdown(f"{'✅' if ok else '⬜'} **{name}**  \n{txt}")
_f = RS.forecast(r, _today)
(st.success if _f["state"] in ("on_track", "proven") else st.info)(
    f"**Proof forecast:** {_f['text']}. A small edge takes thousands of picks to separate from luck; a large one, a "
    "few hundred — so this moves as the return does.")
if r["health"]:
    st.warning(r["health"])
import picks_performance as PP

pp = [{"day": p[0], "pick": "", "result": "win" if p[1] else "loss", "units": (p[2] - 1) if p[1] else -1.0,
       "dec": p[2]} for p in r["picks"]]
if pp:
    pts = PP.curve(pp)
    a, b = st.columns(2)
    c1 = PP.chart(pts, "Running units vs the profitable pace")
    c2 = PP.rate_chart(pts, "Hit rate vs what the prices needed")
    if c1 is not None:
        a.altair_chart(c1, width="stretch")
    if c2 is not None:
        b.altair_chart(c2, width="stretch")
    wk = {}
    for p in r["picks"]:
        y, w, _ = date.fromisoformat(p[0]).isocalendar()
        k = date.fromisocalendar(y, w, 1).isoformat()
        x = wk.setdefault(k, [0, 0, 0.0])
        x[0] += 1
        x[1] += p[1]
        x[2] += (p[2] - 1) if p[1] else -1.0
    st.dataframe(pd.DataFrame([{"Week of": k, "Picks": v[0], "Record": f"{v[1]}–{v[0] - v[1]}",
                                "Hit rate": _pct(v[1] / v[0]), "Units": f"{v[2]:+.1f}",
                                "Return per $1": _pct(v[2] / v[0], True)} for k, v in sorted(wk.items(), reverse=True)]),
                 hide_index=True, width="stretch")
    st.caption("Newest week first. A single week is noise; the gate checks above judge the whole window.")

# ---------- the owner's own testing discipline (Rulebook: owner testing discipline) ----------
st.markdown("#### Your testing discipline (last 30 days)")
try:
    import betlog as B
    since = (datetime.now(ET).date() - timedelta(days=30)).isoformat()
    bets = [b for b in B.list_bets() if str(b.get("slate_date") or "") >= since]
except Exception:                                               # noqa: BLE001
    bets = []
if not bets:
    st.caption("No bets logged in the last 30 days.")
else:
    days = {}
    for b in bets:
        d = str(b.get("slate_date"))[:10]
        x = days.setdefault(d, {"n": 0, "units": 0.0, "tl": 0})
        x["n"] += 1
        x["tl"] += "test-list" in str(b.get("notes") or "")
        try:
            pnl = B.bet_pnl(b)
        except Exception:                                       # noqa: BLE001
            pnl = None
        stake = float(b.get("stake") or 0) or 1.0
        x["units"] += (pnl / stake) if pnl is not None else 0.0
    n_days = len(days)
    over_cap = sum(v["n"] > 6 for v in days.values())
    stop = sum(v["units"] <= -3 for v in days.values())
    tl = sum(v["tl"] for v in days.values()) / max(1, sum(v["n"] for v in days.values()))
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Days with bets", n_days)
    d2.metric("Days over the 6-bet cap", over_cap)
    d3.metric("Days past the −3u stop", stop)
    d4.metric("Logged from the Test list", f"{tl:.0%}", help="The Rulebook's bar for go-live: 90%+.")
    st.caption("From the Bet Log. Units are each bet's result in units of its own stake. Logged from the Test list "
               "means the bet carries the list's tag, so My Coach files it against its rule.")
