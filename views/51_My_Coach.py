"""
My Coach (Nov 8) — simple tables from your own settled bets that point you toward better choices. Owner only.
Numbers: coach.py. Updates every morning as the review settles last night's bets.
"""
import pandas as pd
import streamlit as st

import betlog as B
import coach as CO
import log_ui as LU
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

# ---- Nov 9: today's guardrails and yesterday's lessons -- the coach speaks first
import datetime as _dd
import pytz as _pz
_today_s = _dd.datetime.now(_pz.timezone("US/Eastern")).strftime("%Y-%m-%d")
_yday_s = (_dd.datetime.now(_pz.timezone("US/Eastern")) - _dd.timedelta(days=1)).strftime("%Y-%m-%d")
try:
    _every = B.list_bets()
except Exception:                                               # noqa: BLE001
    _every = []
_money = C.money_md
_lim = CO.limits()
_t = CO.today_so_far(_every, _today_s)
_stop = _t["pl"] <= -float(_lim["stop_loss"])
_over = _t["staked"] >= float(_lim["daily_budget"])
st.markdown("#### 🛑 Today")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Staked today", f"${_t['staked']:.0f}", help=f"Your daily budget is ${float(_lim['daily_budget']):.0f}")
k2.metric("Settled today", CO.usd(_t["pl"]), help=f"Stop-loss: −${float(_lim['stop_loss']):.0f}")
k3.metric("Parlays today", f"{_t['parlays']} of {int(_lim['max_parlays'])}")
k4.metric("Open bets", _t["open"])
if _stop:
    st.error(_money(f"**Stop for today.** You're {CO.usd(_t['pl'])}, past your −${float(_lim['stop_loss']):.0f} stop-loss. "
             "Bets placed to win it back are the ones that cost the most (Nov 8: a $20 +3400 parlay after a losing day)."))
elif _over:
    st.warning(_money(f"**Budget used.** ${_t['staked']:.0f} staked today of ${float(_lim['daily_budget']):.0f}."))
else:
    st.caption(_money(f"Room left today: ${max(0.0, float(_lim['daily_budget']) - _t['staked']):.0f} of your "
                      f"${float(_lim['daily_budget']):.0f} budget."))
with st.expander("⚙️ My limits"):
    l1, l2, l3, l4, l5 = st.columns(5)
    nb = l1.number_input("Daily budget ($)", min_value=0.0, value=float(_lim["daily_budget"]), step=5.0, key="lim_budget")
    ns = l2.number_input("Stop-loss ($ down)", min_value=0.0, value=float(_lim["stop_loss"]), step=5.0, key="lim_stop")
    nl = l3.number_input("Max parlay legs", min_value=2, max_value=10, value=int(_lim["max_legs"]), step=1, key="lim_legs")
    npar = l4.number_input("Max parlays a day", min_value=0, max_value=10, value=int(_lim["max_parlays"]), step=1,
                           key="lim_par")
    nps = l5.number_input("Max parlay stake ($)", min_value=0.0, value=float(_lim["max_parlay_stake"]), step=1.0,
                          key="lim_pstake")
    if st.button("Save my limits", key="lim_save"):
        if CO.save_limits({"daily_budget": nb, "stop_loss": ns, "max_legs": nl, "max_parlays": npar,
                           "max_parlay_stake": nps}):
            st.success("Saved. The coach checks every ticket against these.")
        else:
            st.error("Couldn't save — try again.")
    st.caption("The coach grades every ticket you tick (here, Today's best and the Analyst Desk) against these "
               "limits and flags anything over them before it's logged.")
_less = CO.lessons(_every, _yday_s)
if _less:
    with st.expander("📓 Yesterday's lessons", expanded=True):
        for x in _less:
            st.markdown(f"- {_money(x)}")

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
def _cands(sport, day, code_version=None):
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
    try:
        counts = PR.market_counts(sport)
    except Exception:                                           # noqa: BLE001
        counts = None
    return cands, tags, err, counts


with st.spinner(f"Loading {f_sport} bets… (the first load can take a minute)"):
    # Nov 9: the cache key includes coach.py's code, so an update to how bets are read can't serve stale rows
    # (Nov 8: rows cached before an update were logged without player names)
    import hashlib as _hl
    _code = _hl.md5(open(CO.__file__, "rb").read()).hexdigest()
    _c, _tags, _err, _mcounts = _cands(f_sport, f_date, _code)


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
_judged = CO.finder(_pick, _all_bets, _tags, _mcounts or None)
if f_sport in ("NFL", "NCAAF") and _gt:                         # Nov 8: which games the weather touches
    with st.expander("🌤️ Game weather at kickoff"):
        import football_weather as _FW
        _games_wx = sorted(_gt, key=lambda g: (_gt[g], g))
        st.dataframe(pd.DataFrame([{"Time": next((c["time"] for c in _c if c.get("game") == g), ""), "Game": g,
                                    "Weather": _FW.label_for(f_sport, f_date, g)} for g in _games_wx]),
                     hide_index=True, width="stretch")
        st.caption("☀️ clear · ⛅ partly cloudy · ☁️ cloudy · 🌧️ rain · 🌨️/❄️ snow · ⛈️ storms · 🌫️ fog · 🏟️ dome. "
                   "💨 = wind 10+ mph, 🥶 = 40°F or colder. ⚠️ = the model has adjusted this game's passing, "
                   "receiving and rushing props for it. Rain and snow are shown but not yet adjusted for "
                   "(not tested yet).")
if _err:
    st.caption("Couldn't load: " + ", ".join(_err))
if not _judged:
    st.info(f"No {f_sport} bets with a live price for this selection yet. Lines usually post the day before.")
else:
    @st.cache_data(ttl=1800, show_spinner=False)
    def _wxl(sport, day, game):
        import football_weather as FW
        return FW.label_for(sport, day, game)

    def _tbl(rows, key):
        """A finder table with a tick box on every row; returns the ticked bets (Nov 8: log them below)."""
        return LU.picked(rows, LU.selectable(pd.DataFrame([{"Signal": r.get("signal") or "", "Time": r["time"], "Game": r["game"],
                                    **({"Weather": _wxl(f_sport, f_date, r["game"])} if f_sport in ("NFL", "NCAAF") else {}),
                                    "Bet": r["pick"],
                                    "Price": None if r.get("price") is None else f"{float(r['price']):+.0f}",
                                    "Model chance": CO.pct(r.get("model_chance")),
                                    "Realistic chance": CO.pct(r.get("real_chance")),
                                    "Price needs": CO.pct(r.get("need")), "Edge": CO.pts(r.get("edge")),
                                    "Why": r["why"]} for r in rows]),
                     key=key, hide_index=True, width="stretch"))

    goods = [r for r in _judged if r["verdict"].startswith("🟢")]
    maybes = [r for r in _judged if r["verdict"].startswith("🟡")]
    skips = [r for r in _judged if r["verdict"].startswith("🔴")]
    unchecked = [r for r in _judged if r["verdict"].startswith("⚪")]
    _why = CO.why_nothing(_judged, f_sport)
    if _why:
        st.info(_why)
    st.markdown(f"**🟢 Good bets ({len(goods)})** — your normal stake.")
    _ticked = []
    if goods:
        _ticked += _tbl(goods[:25], "coach_good_sel")
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
    with st.expander(f"🟡 Maybe ({len(maybes)}) — check each row's signal"):
        st.caption("🟢 Small stake OK: 2+ points of edge after any cautions · 🟡 Tiny stake only: 1–2 points · "
                   "🟠 Lean pass: under 1 point. A caution (your losing record at that price or in that market, "
                   "an untested lean) takes a point off.")
        if maybes:
            _ticked += _tbl(maybes[:40], "coach_maybe_sel")
        else:
            st.caption("None.")
    if unchecked:
        with st.expander(f"⚪ Unchecked ({len(unchecked)}) — no track record, don't bet these"):
            st.caption("Combo and defense markets (Pts+Ast, Blocks, Steals…) the platform has never graded, so the "
                       "model's chance can't be checked — that's why some show 80%+ and +30-point edges. They're "
                       "here so you can see them, not to bet. They get a record once the morning review grades them.")
            _ticked += _tbl(unchecked[:40], "coach_unchecked_sel")
    with st.expander(f"🔴 Skip ({len(skips)}) — and why"):
        if skips:
            _ticked += _tbl(skips[:60], "coach_skip_sel")
        else:
            st.caption("None.")
    # Nov 8: tick rows in any of the three tables to log them -- one box for all ticks
    _items = []
    for r in _ticked:
        if r.get("kind") == "Game line":
            if r.get("bet_market") and r.get("_rec"):
                _items.append(dict(r, price=r.get("bet_price") if r.get("price") is None else r.get("price")))
        else:
            _items.append(r)
    LU.panel(_items, "coach_log", f_date, tag="my-coach")
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
