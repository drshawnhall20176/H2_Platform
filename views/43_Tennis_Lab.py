"""
Tennis Lab — ATP / WTA match model (Nov 3). TRACKING ONLY until the record proves it. Owner only.

Every upcoming match the books price (The Odds API: the main ATP and WTA events), saved every 3 hours by the
capture-intl workflow with the model's read: surface Elo win chance vs the market's no-vig chance, total games and the
game handicap vs the posted lines, and a tracking pick where the model clears its bar. Graded from ESPN results.
Model: tennis_model.py; capture / grading / record: intl_picks.py.
"""
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import components as C
import intl_picks as IP
import model_store as MS
import props_engine as PE
import sports
import tennis_model as T

C.base_css()
C.page_header("🎾", "Tennis Lab",
              "ATP and WTA: surface Elo win chances against the books, total games and game handicaps. Tracking only "
              "until the record proves it.")
st.warning("Information only — no picks. Backtested on 5,952 priced 2025-26 matches, the books' prices beat this "
           "model clearly (log loss 0.558 vs 0.608), and betting its side lost 6–11% at every edge size; game handicaps "
           "hit 47% and total games 51%. Use it as a second look at a match, not a reason to bet.")

picks = MS.load_game_picks("TENNIS")
now = datetime.now(timezone.utc).isoformat()
upcoming = [p for p in picks if str(p.get("kickoff")) > now and p.get("result") is None]
done = [p for p in picks if p.get("result")]


def _pct(x):
    return "—" if x is None else f"{x:.0%}"


def _odds(x):
    return "—" if x is None else f"{float(x):+.0f}"


def _pick(p):
    out = []
    if p.get("pick"):
        side = p["home"] if p["pick"] == "home" else p["away"]
        out.append(f"🎯 {side} ML")
    if p.get("spread_pick") and p.get("home_spread") is not None:
        pt = p["home_spread"] if p["spread_pick"] == "home" else -p["home_spread"]
        out.append(f"{p['home'] if p['spread_pick'] == 'home' else p['away']} {pt:+g} games")
    if p.get("total_pick") and p.get("line_total") is not None:
        out.append(f"{p['total_pick'].title()} {p['line_total']:g} games")
    return " · ".join(out) or "—"


def _et(p):
    try:
        return pd.to_datetime(p["kickoff"]).tz_convert("America/New_York").to_pydatetime()
    except Exception:                                           # noqa: BLE001
        return None


f1, f2, f3 = st.columns([1, 1, 2])
day = f1.date_input("Slate date", pd.Timestamp.now(tz="America/New_York").date(), key="tl_date")
rows = [p for p in upcoming if _et(p) is not None and _et(p).date() == day]
_slots = sorted({sports.slot_of(_et(p)) for p in rows}, key=lambda x: sports.SLOT_ORDER.get(x, 9))
slot = f2.selectbox("Time slot", ["All slate"] + _slots, key="tl_slot")
if slot != "All slate":
    rows = [p for p in rows if sports.slot_of(_et(p)) == slot]
tours = f3.radio("Tour", ["All", "ATP", "WTA"], horizontal=True, key="tl_tour")
rows = [p for p in rows if tours == "All" or p.get("tour") == tours.lower()]
g1, g2 = st.columns([2, 2])
_heads = sorted({T.event_label(p).split(" · ")[0] for p in rows})
ev_pick = g1.multiselect("Events, as DraftKings names them (empty = all)", _heads, key="tl_events_all")
if ev_pick:
    rows = [p for p in rows if T.event_label(p).split(" · ")[0] in ev_pick]
q = g2.text_input("Find a player", key="tl_find").strip().lower()
if q:
    rows = [p for p in rows if q in T.norm(f"{p['home']} {p['away']}")]
rows = C.game_select(rows, key="tl_match", title="Match",                       # Nov 7: Match filter, start order
                     label=lambda p: f"{p.get('away')} vs {p.get('home')}")
st.caption("DraftKings files tennis by tour and city (\"WTA Cali 125\", \"ATP Paris\"), while the data feeds use sponsor "
           "names (\"Reto Win Tennis Cali Open\"), so each event here leads with DK's tour + city. DK's ATP Challenger, "
           "ITF and UTR events aren't in either feed, so they don't appear here.")
priced = [p for p in rows if p.get("source") != "espn"]
sched = [p for p in rows if p.get("source") == "espn"]


def _start(p):
    try:
        return pd.to_datetime(p["kickoff"]).tz_convert("America/New_York").strftime("%a %I:%M %p")
    except Exception:                                           # noqa: BLE001
        return "—"


st.markdown(f"##### Every match on the schedule ({len(sched)})")
st.caption("All ATP and WTA singles ESPN lists for today and tomorrow, including WTA 125 / Challenger-level events "
           "the odds feed doesn't carry (Cali, Chennai, Luanda...). The model's chance and the fair price for each "
           "player; type a sportsbook price below to see its value.")
if not sched:
    st.info("Nothing scheduled captured yet — the capture runs every 3 hours.")
else:
    show = st.radio("Show", ["All", PE.MOST_PROBABLE, "Playable (🎟️ / 🎯)", PE.USE_PASS], horizontal=True, key="tl_use_filter")
    tagged = [(p, IP.tennis_use(p)) for p in sorted(sched, key=lambda x: x["kickoff"])]
    tagged = [(p, t) for p, t in tagged if show == "All" or (show == PE.MOST_PROBABLE and t.get("lock"))
              or (show.startswith("Playable") and t.get("use") in (PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE))
              or (show == PE.USE_PASS and t.get("use") == PE.USE_PASS)]
    st.dataframe(pd.DataFrame([{
        "Start (ET)": _start(p),
        "Event": T.event_label(p),
        "Round": p.get("round") or "",
        "Match": f"{p['home']} vs {p['away']}",
        "Model's pick": f"{t['player']} {t['chance']:.0%}" if t.get("player") else "—",
        "Fair": _odds(t.get("fair")),
        "Use": IP.tag_label(t),
        "Why": t.get("why", ""),
        "Rated matches": f"{p.get('n_home', 0)} / {p.get('n_away', 0)}"} for p, t in tagged]),
        hide_index=True, width="stretch")
    st.caption("Model's pick = the player the model favors and its chance. Use reads like the props pages: 🔒 Most probable "
               "+ 🎟️ Parlay + Single = 60%+ with enough history on both players; 🎯 Single only = 55-60% (or thin history); "
               "⛔ Pass = too close to call. \"(-150 or better)\" = the price you need for +3% value — at a shorter price it's a "
               "pass. Fair = the no-margin price at the model's chance. These events have no tested edge yet; the "
               "favorite record below is the check.")

    with st.expander("💲 Check a price · 📒 log it"):
        opts = {f"{p['home']} vs {p['away']} ({p.get('tournament')})": p for p in sched}
        if opts:
            m = opts[st.selectbox("Match", list(opts), key="tl_chk_match")]
            who = st.radio("Player", [m["home"], m["away"]], horizontal=True, key="tl_chk_who")
            price = st.number_input("Sportsbook price (American)", value=-110, step=5, key="tl_chk_price")
            pchance = m["model_p"] if who == m["home"] else 1 - m["model_p"]
            dec = 1 + (price / 100 if price > 0 else 100 / -price) if abs(price) >= 100 else None
            if dec:
                ev = pchance * dec - 1
                trusted = min(int(m.get("n_home") or 0), int(m.get("n_away") or 0)) >= IP.TENNIS_MIN_MATCHES
                tg = IP.chance_use(pchance, price, trusted)
                st.markdown(f"Model chance **{pchance:.0%}** · fair **{_odds(T.fair_odds(pchance))}** · at {price:+d}: "
                            f"**{ev:+.1%}** expected value → **{IP.tag_label(dict(tg, priced=True))}**")
                c1, c2 = st.columns(2)
                stake = c1.number_input("Stake ($)", min_value=0.0, value=1.0, step=1.0, key="tl_chk_stake")
                real = c2.toggle("Real money", value=True, key="tl_chk_real")
                if st.button(f"📒 Log {who} at {price:+d}", key="tl_chk_log", type="primary"):
                    import betlog as B
                    f = IP.bet_fields(m, "Moneyline", "home" if who == m["home"] else "away", None, price, stake, real,
                                      round(pchance, 4))
                    try:
                        st.success(f"Logged #{B.add_bet(**f)}: {who} to win at {price:+d}, ${stake:,.2f} "
                                   f"{'real' if real else 'tracking'}. It settles once the result is in.")
                    except Exception as exc:                    # noqa: BLE001
                        st.error(f"Couldn't log it: {exc}")
            else:
                st.caption("Enter a price of +100 or more, or -100 or less.")

st.markdown(f"##### Priced by the odds feed ({len(priced)})")
if not priced:
    st.info("No main-tour matches priced right now. The odds feed only covers the main ATP and WTA events.")
else:
    st.dataframe(pd.DataFrame([{
        "Start (ET)": _start(p),
        "Event": T.event_label(p),
        "Match": f"{p['home']} vs {p['away']}",
        "Model's pick": (lambda t: f"{t['player']} {t['chance']:.0%}" if t.get("player") else "—")(IP.tennis_use(p)),
        "Use": IP.tag_label(IP.tennis_use(p)),
        "Model": _pct(p.get("model_p")), "Market": _pct(p.get("line")),
        "Edge": "—" if p.get("edge") is None else f"{p['edge']:+.0%}",
        "Best price": f"{_odds(p.get('best_home'))} / {_odds(p.get('best_away'))}",
        "Games: model / line": f"{p.get('model_total') or '—'} / {p.get('line_total') or '—'}",
        "Rated matches": f"{p.get('n_home', 0)} / {p.get('n_away', 0)}",
        "Tracking pick": _pick(p)} for p in sorted(priced, key=lambda x: x["kickoff"])]),
        hide_index=True, width="stretch")
    st.caption("Use is ⛔ Pass on these main-tour events: in the backtest the books' prices beat the model here. "
               "Model = the first-named player's chance from surface Elo; Market = the books' no-vig chance. "
               "Rated matches = how much history each player's rating has behind it.")

st.markdown("##### How often the model's favorite wins")
fav = IP.favorite_record(done)
if not fav:
    st.caption("Nothing graded yet — results are matched every 3 hours.")
else:
    names = {"priced": "Main-tour events (odds feed)", "espn": "Everything else (WTA 125, Challengers...)"}
    st.dataframe(pd.DataFrame([{"Events": names[k], "Graded": r["n"], "Favorite won": f"{r['rate']:.0%}",
                                "Model said": f"{r['said']:.0%}"} for k, r in fav.items()]), hide_index=True, width="stretch")
    st.caption("If the favorite wins about as often as the model said, its chances are honest for those events — the "
               "first step before trusting its fair prices there.")

rec = IP.record(done)
if rec:
    st.markdown("##### Tracking record")
    names = {"ml": "Match winner", "spread": "Game handicap", "total": "Total games"}
    st.dataframe(pd.DataFrame([{"Market": names.get(k, k), "Record": f"{r['w']}-{r['l']}" + (f"-{r['p']}" if r["p"] else ""),
                                "Profit (units)": f"{r['units']:+.1f}", "Per $1": "—" if r["roi"] is None else f"{r['roi']:+.1%}"}
                               for k, r in rec.items()]), hide_index=True, width="stretch")
st.caption("Player props (aces, double faults) aren't in the odds feed, so they aren't modeled.")
