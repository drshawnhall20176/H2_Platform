"""
Postgame Review — grade what the model said at kickoff against the box score, see why each miss missed, and approve
the adjustments the results point to (Oct 30). Owner only.

The snapshots are written automatically (model_store): every props row Best Bets / Edge Board / Position Matchups
priced with a line before the game started. This page reads them, pulls ESPN's box scores and grades each one
(postgame.py). Suggestions look across every graded day in the window; a projection multiplier only takes effect
when approved here, and can be retired here.
"""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import components as C
import model_store as MS
import model_tuning as MT
import postgame as PG
import sports

C.base_css()
C.page_header("🧾", "Postgame Review",
              "What the model said at kickoff vs the box score: hits, misses, whether the Use tag was right, why each "
              "miss missed, and the adjustments the results point to.")

SPORT_KEY = st.session_state.get("sport", "NFL")
if SPORT_KEY not in PG.ESPN:
    st.info(f"The Postgame Review covers {', '.join(PG.ESPN)} so far. Switch sport on the Home page.")
    st.stop()


@st.cache_data(ttl=1800, show_spinner=False)
def load_results(sport: str, slate_date: str, games: tuple) -> dict:
    return PG.fetch_results(sport, slate_date, list(games))


def graded_for(sport: str, dates: list) -> list:
    snaps = MS.load_snapshots(sport, dates)
    out = []
    for d in sorted({s["slate_date"] for s in snaps}):
        day = [s for s in snaps if s["slate_date"] == d]
        res = load_results(sport, d, tuple(sorted({(s["team"], s["opp"]) for s in day})))
        out += PG.grade(day, res)
    return out


dates = MS.snapshot_dates(SPORT_KEY)
if not dates:
    st.info("No kickoff snapshots yet. They're saved automatically whenever Best Bets, Edge Board or Position Matchups "
            "price props with book lines before a game starts — open one of those before the next slate, then come "
            "back here after the games.")
    st.stop()

tab_day, tab_trend, tab_adj = st.tabs(["📋 One slate", "📈 Patterns & suggestions", "🛠️ Approved adjustments"])

with tab_day:
    pick = st.selectbox("Slate date", dates, key="pgr_date")
    with st.spinner("Pulling the box scores..."):
        graded = graded_for(SPORT_KEY, [pick])
    done = [r for r in graded if r["result"] in ("hit", "miss", "push")]
    pending = sum(1 for r in graded if r["result"] == "pending")
    void = sum(1 for r in graded if r["result"] == "void")
    if not done:
        st.info("Nothing to grade yet for this date" + (f" — {pending} props are waiting on final box scores." if pending else "."))
    else:
        mh, mn = PG.model_record(done)
        hits = sum(r["result"] == "hit" for r in done)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Props graded", len(done), help=f"{void} void (no box-score line) · {pending} pending")
        m2.metric("Pick side record", f"{hits}-{len(done) - hits}")
        m3.metric("Model side (projection vs line)", f"{mh}/{mn}", f"{mh / mn:.0%}" if mn else None)
        cc = PG.cause_counts(done)
        model_misses = sum(cc.get(c, 0) for c in PG.MODEL_CAUSES)
        m4.metric("Misses on the model", f"{model_misses} of {sum(cc.values())}",
                  help="Volume or role misses (the model's opportunity call). The rest is the player or the game script.")
        st.markdown("##### Was the Use tag right?")
        ur = PG.use_record(done)
        if ur:
            st.dataframe(pd.DataFrame([{**r, "Hit rate": f"{r['Hit rate']:.0%}",
                                        "Model said": "—" if r["Model said"] is None else f"{r['Model said']:.0%}"}
                                       for r in ur]), hide_index=True, width="stretch")
        st.markdown("##### Why the misses missed")
        st.caption("**Volume** / **Role change**: the targets, carries, attempts or minutes were 25%+ off the model's "
                   "call — that's the model. **Player**: the chances came and weren't converted. **Blowout**: decided by "
                   "17+. A volume swing that favored the bet doesn't count against the model.")
        if cc:
            st.dataframe(pd.DataFrame([{"Cause": k, "Misses": v} for k, v in sorted(cc.items(), key=lambda kv: -kv[1])]),
                         hide_index=True)
        games = ["All games"] + sorted({r["game"] for r in done})
        gpick = st.selectbox("Game", games, key="pgr_game")
        rows = [r for r in graded if gpick == "All games" or r["game"] == gpick]
        icon = {"hit": "✅", "miss": "❌", "push": "➖", "void": "∅ void", "pending": "⏳"}
        st.dataframe(pd.DataFrame([{
            "Game": r["game"], "Player": r["player"], "Market": r["market"], "Slot": r.get("slot") or "",
            "Proj": round(r["projection"], 1), "Line": r["line"], "Actual": r["actual"], "Pick": r["side"],
            "Result": icon.get(r["result"], r["result"]),
            "Model side": "—" if r["model_hit"] is None else ("✅" if r["model_hit"] else "❌"),
            "Use": r.get("use_tag") or "—",
            "Volume": "—" if r.get("proj_opp") is None or r.get("actual_opp") is None
            else f"{r['proj_opp']:.1f} → {r['actual_opp']:.0f}",
            "Cause": r.get("cause") or "",
        } for r in rows]), hide_index=True, width="stretch")

with tab_trend:
    window = st.select_slider("Look back", options=[7, 14, 30, 60], value=30, key="pgr_window",
                              format_func=lambda d: f"{d} days")
    cutoff = (date.today() - timedelta(days=window)).isoformat()
    in_window = [d for d in dates if d >= cutoff]
    with st.spinner(f"Grading {len(in_window)} slates..."):
        graded_all = [r for r in graded_for(SPORT_KEY, in_window) if r["result"] in ("hit", "miss", "push")]
    if not graded_all:
        st.info("No graded props in this window yet.")
    else:
        st.caption(f"{len(graded_all)} graded props across {len(in_window)} slates.")
        by_m = {}
        for r in graded_all:
            by_m.setdefault(r["market"], []).append(r)
        st.dataframe(pd.DataFrame([{
            "Market": m, "Graded": len(rs),
            "Model side": f"{sum(1 for r in rs if r['model_hit']) / max(1, sum(1 for r in rs if r['model_hit'] is not None)):.0%}",
            "Results vs projection": f"{(sum(r['actual'] for r in rs) / max(1e-9, sum(r['projection'] for r in rs))) - 1:+.0%}",
            "Volume misses": sum(1 for r in rs if r.get("cause") in PG.MODEL_CAUSES),
        } for m, rs in sorted(by_m.items())]), hide_index=True, width="stretch")
        active = {(t["sport"], t["market"], t.get("slot") or ""): float(t["factor"]) for t in MS.list_tuning()}
        sugg = PG.suggestions(graded_all, active)
        st.markdown("##### Suggestions")
        if not sugg:
            st.caption(f"Nothing consistent enough to act on yet (a market needs {PG.MIN_MARKET_N}+ graded props running "
                       f"{PG.MARKET_BIAS:.0%}+ off before a change is suggested).")
        for i, sgt in enumerate(sugg):
            with st.container(border=True):
                st.markdown(sgt["text"])
                if sgt["kind"] == "tuning":
                    c1, c2 = st.columns([3, 1])
                    c1.caption(f"Approving sets {sgt['market']}{' · ' + sgt['slot'] if sgt['slot'] else ''} projections "
                               f"to ×{sgt['factor']:.3f} (replacing any earlier adjustment for it). Every page uses it "
                               "within 10 minutes; retire it any time on the next tab.")
                    if c2.button("Approve", key=f"pgr_ok_{i}"):
                        ok = MS.approve_tuning(sgt["sport"], sgt["market"], sgt["factor"], sgt["text"], sgt["slot"])
                        st.success("Approved.") if ok else st.error("Couldn't save the adjustment.")
                else:
                    st.caption("Advice — this one needs a rule change in the model; ask Claude to apply it.")

with tab_adj:
    rows = MS.list_tuning(active_only=False)
    if not rows:
        st.info("No adjustments approved yet.")
    for t in rows:
        with st.container(border=True):
            st.markdown(f"**{t['sport']} · {t['market']}{' · ' + t['slot'] if t.get('slot') else ''}** — ×{float(t['factor']):.3f}"
                        f" · {'🟢 active' if t.get('active') else '⚪ retired'} · approved {str(t.get('approved_ts'))[:16]}")
            st.caption(t.get("reason") or "")
            if t.get("active") and st.button("Retire", key=f"pgr_retire_{t['id']}"):
                st.success("Retired.") if MS.retire_tuning(t["id"]) else st.error("Couldn't retire it.")
