"""
Soccer Lab — the Big 5 leagues, Champions / Europa League, the EFL Championship, MLS and Liga MX (Nov 13).
TRACKING ONLY until the record proves it. Owner: add soccer, domestic and international.

Every upcoming match the books price, saved every 3 hours by capture-intl (soccer_picks.py): the goals model's read
(soccer_model.py), Pinnacle's no-vig "fair" chance, the best US price, totals and Asian handicap, and a 📈 flag when a
US price beats the sharp line. Player props (soccer_props.py) load on demand for one match (~3 Odds API credits).
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytz
import streamlit as st

import components as C
import log_ui as LU
import model_store as MS
import soccer_data as D
import soccer_picks as SP
import sports

C.base_css()
C.page_header("⚽", "Soccer Lab",
              "Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions and Europa League, the Championship, "
              "MLS and Liga MX: the goals model and the sharp line against the US books. Tracking only.")
st.warning("**Tracking only — no picks yet.** Backtested on ~10,000 matches (2023-26, 8 leagues) against Pinnacle, the "
           "sharpest book: the goals model was **less accurate than the closing price in every league**, and betting "
           "its edges lost 6–37% on the match result. US prices that beat Pinnacle's no-vig line (📈 below) beat the "
           "closing line by 2–16% but only broke even over four seasons. Use the model as a second look; the 📈 flags "
           "are tracked here until the live record says more.", icon="⚠️")

if not sports.require_sport(["SOCCER"], "Soccer Lab"):
    st.stop()

ET = pytz.timezone("US/Eastern")
league = st.radio("League", list(D.LEAGUES), format_func=lambda k: D.LEAGUES[k]["title"], horizontal=True,
                  key="soccer_league")
picks = MS.load_game_picks(league)
now = datetime.now(timezone.utc)
upcoming = [p for p in picks if str(p.get("kickoff")) > now.isoformat()[:19] and p.get("result") is None
            and str(p.get("kickoff")) < (now + timedelta(days=8)).isoformat()]
done = [p for p in picks if p.get("result")]


def _pct(x):
    return "—" if x is None else f"{x:.0%}"


def _am(x):
    return "—" if x is None else f"{int(x):+d}"


def _ko(p):
    try:
        return datetime.fromisoformat(str(p["kickoff"]).replace("Z", "+00:00")).astimezone(ET).strftime("%a %-I:%M %p")
    except ValueError:
        return ""


def _flags(p):
    out = []
    for v in p.get("value") or []:
        who = {"home": p["home"], "away": p["away"], "draw": "Draw", "over": "Over", "under": "Under"}[v["side"]]
        ln = "" if v.get("line") is None else f" {v['line']:+g}" if v["market"] == "Spread" else f" {v['line']:g}"
        out.append(f"📈 {who}{ln} {_am(v['price'])} ({v.get('book') or ''}, {v['ev']:+.1%})")
    return " · ".join(out) or "—"


st.markdown(f"#### Upcoming — {D.LEAGUES[league]['title']} ({len(upcoming)})")
if not upcoming:
    st.info("No priced matches in the next week. During international breaks and the off-season there's nothing to "
            "show; the capture checks every 3 hours.")
else:
    ordered = C.by_kickoff(upcoming)
    kind = st.radio("☑️ Tick matches to log", ["📈 Flagged price", "Model's result pick", "Total (model's side)"],
                    horizontal=True, key="soccer_kind")
    df = pd.DataFrame([{
        "Kickoff (ET)": _ko(p), "Match": f"{p['home']} vs {p['away']}",
        "Model H / D / A": "not rated yet" if p.get("p_home") is None else
        f"{_pct(p['p_home'])} / {_pct(p['p_draw'])} / {_pct(p['p_away'])}",
        "Sharp line H / D / A": "—" if p.get("mkt_home") is None else
        f"{_pct(p['mkt_home'])} / {_pct(p['mkt_draw'])} / {_pct(p['mkt_away'])}" + ("" if p.get("sharp") else " (US avg)"),
        "Best US H / D / A": f"{_am(p.get('best_home'))} / {_am(p.get('best_draw'))} / {_am(p.get('best_away'))}",
        "xG": "—" if p.get("xg_home") is None else f"{p['xg_home']:.2f} – {p['xg_away']:.2f}",
        "Total: model / sharp": "—" if p.get("line_total") is None else
        f"O{p['line_total']:g}: {_pct(p.get('p_over'))} / {_pct(p.get('mkt_over'))}",
        "Handicap": "—" if p.get("home_spread") is None else
        f"{p['home']} {p['home_spread']:+g}: {_pct(p.get('p_ah_home'))} / {_pct(p.get('mkt_ah_home'))}",
        "Both score": _pct(p.get("p_btts")), "Flags": _flags(p), "Use": p.get("use", SP.PASS)} for p in ordered])
    ticked = LU.selectable(df, f"soccer_tick_{league}", hide_index=True, width="stretch")
    st.caption("Model = the goals model; Sharp line = Pinnacle's price with the margin removed (the market's honest "
               "chance); Best US = the best price at DraftKings, FanDuel, BetMGM, Caesars, BetRivers, Fanatics or ESPN "
               "Bet. 📈 = that US price beats the sharp chance by 2%+ (expected value shown). Handicap and total show "
               "model / sharp. Quarter handicap lines settle by hand in the Bet Log.")

    def _item(p):
        if kind.startswith("📈"):
            vs = p.get("value") or []
            if not vs:
                return None
            v = max(vs, key=lambda x: x["ev"])
            mk, side, line, price, ch = v["market"], v["side"], v.get("line"), v["price"], v["fair"]
        elif kind.startswith("Model"):
            if p.get("p_home") is None:
                return None
            probs = {"home": p["p_home"], "draw": p["p_draw"], "away": p["p_away"]}
            side = max(probs, key=probs.get)
            mk, line, price, ch = "Moneyline", None, p.get(f"best_{side}"), probs[side]
        else:
            if p.get("line_total") is None or p.get("p_over") is None:
                return None
            side = "over" if p["p_over"] >= 0.5 else "under"
            mk, line, price = "Total", p["line_total"], p.get(f"{side}_price")
            ch = p["p_over"] if side == "over" else 1 - p["p_over"]
        who = {"home": p["home"], "away": p["away"], "draw": "Draw", "over": "Over", "under": "Under"}[side]
        label = f"{who}" + ("" if line is None else f" {line:+g}" if mk == "Spread" else f" {line:g}") + \
                ("" if mk != "Moneyline" or side == "draw" else " to win")
        return {"sport": "SOCCER", "pick": f"{label} ({p['home']} vs {p['away']})", "price": price,
                "game": f"{p['away']} @ {p['home']}", "chance": ch, "_rec": p, "bet_market": mk, "bet_side": side,
                "bet_line": line, "best_tested": ch is not None, "best_chance": ch}

    items = [it for it in (_item(ordered[i]) for i in ticked if 0 <= i < len(ordered)) if it]
    if ticked and not items:
        st.caption("Nothing to log for that choice on the ticked matches (no 📈 flag, or no price yet).")
    LU.panel(items, f"soccer_panel_{league}", now.astimezone(ET).strftime("%Y-%m-%d"), tag="soccer-lab")

    # ---------------------------------------------------------------- player props, one match at a time
    with st.expander("🎯 Player props — anytime goalscorer, shots on target, shots (untested)"):
        st.caption("Loads the US books' player props for one match (~3 Odds API credits) and reads each with the "
                   "player's last 10 matches (per start, ESPN) scaled to this opponent. No history of these prices "
                   "exists to test on, so this is a reference that's tracked, never a pick. Assumes the player starts — "
                   "check the lineup (about an hour before kickoff).")
        m = st.selectbox("Match", ordered, format_func=lambda p: f"{_ko(p)} — {p['home']} vs {p['away']}",
                         key=f"soccer_props_match_{league}")
        k = f"soccer_props_{m['game_id']}"
        import best_bets_data as BBD
        api_key = BBD.get_odds_api_key()
        if api_key and st.button("📈 Load player props for this match", key=f"soccer_props_btn_{league}"):
            with st.spinner("Loading props and the players' recent matches…"):
                import soccer_props as SPR
                props = SPR.fetch_props(league, m["game_id"], api_key)
                res = MS.load_results(league, since=(now.date() - timedelta(days=200)).isoformat())
                if D.LEAGUES[league].get("europe"):
                    res += [g for kk in D.DOMESTIC_EUROPE for g in MS.load_results(kk, since=(now.date() - timedelta(days=200)).isoformat())]
                r = SP.ratings(league, now.date())
                hid = SPR.team_matches(res, m["home"])
                aid = SPR.team_matches(res, m["away"])
                rows = {}
                for lg_ids in (hid, aid):
                    for e in lg_ids:
                        g = next((x for x in res if str(x["id"]) == e), None)
                        lg = g.get("league", league) if g else league
                        rows.update(SPR.summaries(lg, [e]))
                st.session_state[k] = SPR.read(props, m, r, SPR.rates(rows, m["home"]), SPR.rates(rows, m["away"]))
        elif not api_key:
            st.caption("No Odds API key on this app.")
        got = st.session_state.get(k)
        if got is not None:
            if not got:
                st.info("No player props posted for this match yet — the US books usually post them a day or two "
                        "before kickoff.")
            else:
                pdf = pd.DataFrame([{"Player": x["player"], "Team": x["team"] or "?", "Bet": x["market"] + (
                    "" if x.get("line") is None else f" Over {x['line']:g}"), "Best price": x["price"],
                    "Book": x["book"], "Model": x["chance"], "EV": x["ev"], "Starts (last 10)": x["starts"]}
                    for x in got])
                sel = LU.selectable(pdf, f"soccer_props_tick_{league}", hide_index=True, width="stretch",
                                    column_config={"Best price": st.column_config.NumberColumn(format="%+d"),
                                                   "Model": st.column_config.NumberColumn(format="percent"),
                                                   "EV": st.column_config.NumberColumn(format="percent")})
                pitems = [{"sport": "SOCCER", "pick": f"{x['player']} {x['market']}" + (
                    "" if x.get("line") is None else f" Over {x['line']:g}"), "price": x["price"],
                    "game": f"{m['away']} @ {m['home']}", "chance": x["chance"], "player": x["player"],
                    "market": x["market"], "side": "Yes" if x["market"] == "Anytime Goal" else "Over",
                    "line": 0.5 if x.get("line") is None else x["line"], "book": x["book"]}
                    for x in LU.picked(got, sel)]
                LU.panel(pitems, f"soccer_props_panel_{league}", now.astimezone(ET).strftime("%Y-%m-%d"),
                         tag=f"soccer-props,sp:{league}")

# -------------------------------------------------------------------- the record
st.markdown("#### Tracking record")
rec = SP.record(done)
if not rec["graded"]:
    st.caption("No graded matches yet — they're graded from ESPN results after full time.")
else:
    fw, fn = rec["fav"]
    vw, vn = rec["value"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Graded matches", rec["graded"])
    c2.metric("Model's favourite won", f"{fw}-{fn - fw}", None if not fn else
              f"{fw / fn:.0%} (said {rec['fav_said']:.0%})", delta_color="off")
    c3.metric("📈 result flags", f"{vw}-{vn - vw}", f"{rec['value_units']:+.2f} units", delta_color="off")
fin = C.by_kickoff(done)[-30:][::-1]
if fin:
    st.dataframe(pd.DataFrame([{"Kickoff (ET)": _ko(p), "Match": f"{p['home']} vs {p['away']}",
                                "Score": f"{int(p['final_home'])}–{int(p['final_away'])}",
                                "Model H / D / A": "—" if p.get("p_home") is None else
                                f"{_pct(p['p_home'])} / {_pct(p['p_draw'])} / {_pct(p['p_away'])}",
                                "Flags": _flags(p)} for p in fin]), hide_index=True, width="stretch")
