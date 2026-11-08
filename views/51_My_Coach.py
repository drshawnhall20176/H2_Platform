"""
My Coach (Nov 8) — simple tables from your own settled bets that point you toward better choices. Owner only.
Numbers: coach.py. Updates every morning as the review settles last night's bets.
"""
import pandas as pd
import streamlit as st

import betlog as B
import coach as CO
import components as C

C.base_css()
C.page_header("🧑‍🏫", "My Coach", "What's working, what isn't, and simple rules for your next bet — from your own bets.")

period = st.radio("Look at", ["Last 7 days", "Last 30 days", "All time"], index=1, horizontal=True, key="coach_period")
days = {"Last 7 days": 7, "Last 30 days": 30, "All time": None}[period]
try:
    bets = CO.in_period(B.list_bets(), days)
except Exception:                                               # noqa: BLE001
    bets = []

PCT = st.column_config.NumberColumn(format="percent")
MONEY = st.column_config.NumberColumn(format="$%.2f")
CFG = {"Win %": PCT, "Need to win": PCT, "Money": MONEY, "Model said": PCT}


def show(rows, cols=None):
    if not rows:
        st.caption("Nothing here yet for this period.")
        return
    df = pd.DataFrame(rows)
    if cols:
        df = df[[c for c in cols if c in df]]
    st.dataframe(df, hide_index=True, width="stretch", column_config=CFG)


with st.expander("📖 How to read these tables", expanded=False):
    st.markdown(
        "- **Record**: wins–losses.\n"
        "- **Win %**: how often you won.\n"
        "- **Need to win**: how often the price needs you to win just to break even. At −110 that's 52%; at −150 it's 60%.\n"
        "  If *Win %* is below *Need to win*, that kind of bet loses money over time even when it wins more than it loses.\n"
        "- **Money**: what you actually won or lost.\n"
        "- **Verdict**: 🟢 keep doing it · 🟡 close, watch the price · 🔴 stop or bet smaller · ⚪ fewer than "
        f"{CO.MIN_N} bets, too early to judge.")

# ---- Nov 8: the bet finder -- pick a sport, time and game; every bet on offer gets 🟢 / 🟡 / 🔴 and why
st.markdown("#### 🔎 Find a bet")
st.caption("Pick a sport, then narrow to a start time or a game. Every bet with a live price is checked against "
           "the model, the price, how that kind of pick has done lately, and how you've done with it.")
import datetime as _d
import pytz as _pytz
_now = _d.datetime.now(_pytz.timezone("US/Eastern")).date()
f1, f2 = st.columns([1, 1])
f_sport = f1.selectbox("Sport", ["NFL", "NBA", "NHL", "NCAAF", "NCAAMB"], key="coach_sport")
f_day = f2.date_input("Date", _now, min_value=_now, max_value=_now + _d.timedelta(days=2), key="coach_day",
                      format="MM/DD/YYYY")
f_date = f_day.strftime("%Y-%m-%d")


@st.cache_data(ttl=900, show_spinner=False)
def _cands(sport, day):
    import best_bets_data as BBD
    import todays_best as TB
    import pick_records as PR
    cands, err = [], []
    try:
        plays, meta, _ = BBD.load_generic_best_bets_board(sport, day, BBD.O.DEFAULT_BOOK)
        cands += CO.prop_candidates(sport, plays, meta)
    except Exception as exc:                                    # noqa: BLE001
        err.append(f"props: {type(exc).__name__}")
    try:
        rows = [r for r in TB.winner_rows(day) if r.get("sport") == sport]
        PR.annotate_leans(rows)
        cands += CO.lean_candidates(rows)
    except Exception as exc:                                    # noqa: BLE001
        err.append(f"game lines: {type(exc).__name__}")
    try:
        tags = PR.tag_records(sport)
    except Exception:                                           # noqa: BLE001
        tags = {}
    return cands, tags, err


with st.spinner(f"Loading {f_sport} bets… (the first load can take a minute)"):
    _c, _tags, _err = _cands(f_sport, f_date)


def _tk(t):
    try:
        return _d.datetime.strptime(t, "%I:%M %p").time()
    except (TypeError, ValueError):
        return _d.time(23, 59)


g1, g2 = st.columns([1, 2])
_times = sorted({c["time"] for c in _c if c.get("time")}, key=_tk)
f_times = g1.multiselect("Start time", _times, key="coach_times", placeholder="All times")
_gt = {}
for c in _c:
    if c.get("game"):
        _gt[c["game"]] = min(_gt.get(c["game"], _tk(c.get("time"))), _tk(c.get("time")))
f_games = g2.multiselect("Game", sorted(_gt, key=lambda g: (_gt[g], g)), key="coach_games", placeholder="All games")
_pick = [c for c in _c if (not f_times or c.get("time") in f_times) and (not f_games or c.get("game") in f_games)]
try:
    _all_bets = B.list_bets()
except Exception:                                               # noqa: BLE001
    _all_bets = []
_judged = CO.finder(_pick, _all_bets, _tags)
if _err:
    st.caption("Couldn't load: " + ", ".join(_err))
if not _judged:
    st.info(f"No {f_sport} bets with a live price for this selection yet. Lines usually post the day before.")
else:
    def _tbl(rows):
        st.dataframe(pd.DataFrame([{"Time": r["time"], "Game": r["game"], "Bet": r["pick"],
                                    "Price": None if r.get("price") is None else f"{float(r['price']):+.0f}",
                                    "Model chance": r.get("model_chance"), "Realistic chance": r.get("real_chance"),
                                    "Price needs": r.get("need"),
                                    "Edge": None if r.get("edge") is None else round(r["edge"] * 100, 1),
                                    "Why": r["why"]} for r in rows]),
                     hide_index=True, width="stretch",
                     column_config={"Model chance": PCT, "Realistic chance": PCT, "Price needs": PCT,
                                    "Edge": st.column_config.NumberColumn("Edge (pts)", format="%+.1f")})

    goods = [r for r in _judged if r["verdict"].startswith("🟢")]
    maybes = [r for r in _judged if r["verdict"].startswith("🟡")]
    skips = [r for r in _judged if r["verdict"].startswith("🔴")]
    st.markdown(f"**🟢 Good bets ({len(goods)})** — your normal stake.")
    if goods:
        _tbl(goods[:25])
    else:
        st.caption("None right now. No bet is better than a bad bet.")
    if len({r["game"] for r in goods}) >= 2:
        _seen, _legs = set(), []
        for r in goods:
            if r["game"] not in _seen:
                _seen.add(r["game"])
                _legs.append(r["pick"])
            if len(_legs) == 3:
                break
        st.caption("Want a small parlay? Use 2–3 🟢 bets from different games, e.g. " + " + ".join(_legs) + ".")
    with st.expander(f"🟡 Maybe ({len(maybes)}) — half stake or skip"):
        if maybes:
            _tbl(maybes[:40])
        else:
            st.caption("None.")
    with st.expander(f"🔴 Skip ({len(skips)}) — and why"):
        if skips:
            _tbl(skips[:60])
        else:
            st.caption("None.")
    st.caption("Realistic chance = the model's chance, or how often that kind of pick has really hit lately if "
               "that's lower. Edge = the realistic chance minus the chance the price needs. A good bet has 3+ points of edge, a model "
               "chance of 55%+, and nothing in its record against it. Prices move: check the price on your book "
               "before you place it, and re-check this page if it moved.")

st.markdown("#### ✅ Your rules for the next bet")
for r in CO.rules(bets):
    st.markdown(f"- {r}")

st.markdown("#### 📋 Your report card")
st.caption("Each line is one kind of choice. The model lines count every pick you made, parlay legs included; "
           "their money is from single bets only.")
show(CO.report_card(bets), ["What", "Bets", "Record", "Win %", "Need to win", "Money", "Verdict"])

best, worst = CO.best_and_worst(bets)
c1, c2 = st.columns(2)
with c1:
    st.markdown("#### 💰 Where you make money")
    show(best, ["What", "Record", "Money", "Verdict"])
with c2:
    st.markdown("#### 🕳️ Where you lose money")
    show(worst, ["What", "Record", "Money", "Verdict"])
st.caption("Sport and market, 3 or more bets.")

st.markdown("#### ⚔️ When you went against the model")
st.caption("Picks where the model gave your side less than a 50% chance.")
am = CO.against_model(bets)
show(am["by_sport"], ["What", "Bets", "Record", "Win %", "Money", "Verdict"])
if am["recent"]:
    with st.expander("The most recent ones"):
        show(am["recent"])

st.markdown("#### 🏷️ Price check")
st.caption("Single bets by the price you took. Heavier prices need you to win more often.")
show(CO.price_check(bets), ["What", "Bets", "Record", "Win %", "Need to win", "Money", "Verdict"])

with st.expander("📚 Everything, by sport and market"):
    show(CO.by_group(bets), ["What", "Bets", "Record", "Win %", "Need to win", "Money", "Verdict"])
