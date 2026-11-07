"""
Game Script — NBA (Nov 7). Owner only.

Pick a game; see how likely each kind of game is (from the pre-game spread) and how every player prop reads under each
one: favorite blows it open, middle, close, underdog blows it open. Then pick a script and build the legs that win
together under it, with the ticket's chance counting the script (legs that move together) next to the plain multiplied
chance. Base reads come from today's Best Bets board (player-props model); the script shifts are measured in
research/blowout_study.py (script_effects.py).
"""
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

import best_bets_data as BBD
import components as C
import model_store as MS
import script_effects as SE

C.base_css()
C.page_header("🎬", "Game Script", "How each kind of game moves every prop — and the legs that win together.")

today = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")


@st.cache_data(ttl=900, show_spinner="Loading today's board…")
def _board(day):
    plays, meta, _ = BBD.load_generic_best_bets_board("NBA", day, BBD.O.DEFAULT_BOOK)
    return [p for p in plays if p.get("Model") == "player-props" and p.get("Side") in ("Over", "Under")
            and p.get("Line") is not None]


@st.cache_data(ttl=900, show_spinner=False)
def _lines(day):
    import todays_best as TB
    out = {}
    for r in MS.load_game_picks("NBA", ungraded=True):
        if TB._et_date(r.get("kickoff")) == day:
            out[(r.get("away"), r.get("home"))] = r
    return out


try:
    plays = _board(today)
except Exception as exc:                                        # noqa: BLE001
    st.error(f"Couldn't load today's NBA board ({type(exc).__name__}).")
    st.stop()
if not plays:
    st.info("No NBA props on today's board yet.")
    st.stop()

# Nov 7: games in tip order, each with its start time
_first = {}
for p in C.by_kickoff(plays, when=lambda x: x.get("Kickoff") or x.get("kickoff") or x.get("game_date")):
    if p.get("Game") and p["Game"] not in _first:
        _first[p["Game"]] = C._kick_dt(p.get("Kickoff") or p.get("kickoff") or p.get("game_date"))
games = list(_first)
game = st.selectbox("Game", games, key="gs_game",
                    format_func=lambda g: g if _first.get(g) is None else f"{_first[g].strftime('%a %-I:%M %p')} — {g}")
gl = _lines(today)
rec = next((r for (a, h), r in gl.items() if a and h and a in game and h in game), None)
if rec and rec.get("home_spread") is not None:
    spread = float(rec["home_spread"])
    fav = rec["home"] if spread < 0 else rec["away"]
    dog = rec["away"] if fav == rec["home"] else rec["home"]
else:
    spread, fav, dog = None, None, None
sh = SE.shares(spread)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Spread", "—" if spread is None else f"{fav.split()[-1]} −{abs(spread):g}")
c2.metric(f"{fav.split()[-1] if fav else 'Favorite'} by 15+", f"{sh['fav_blowout']:.0%}")
c3.metric("Within 6", f"{sh['close']:.0%}")
c4.metric(f"{dog.split()[-1] if dog else 'Underdog'} by 15+", f"{sh['dog_blowout']:.0%}")
if spread is None:
    st.caption("No pre-game spread found for this game: script chances use the close-spread mix.")
st.caption(f"Middle (decided by 7–14): {sh['middle']:.0%}. From 1,111 NBA games over the last season and a half, by "
           "the pre-game spread.")


def _avg_min(p):
    log = p.get("_game_log") or []
    mins = [float(g.get("min") or 0) for g in log[-10:] if g.get("min") is not None]
    return sum(mins) / len(mins) if mins else None


rows = []
for p in [p for p in plays if p.get("Game") == game]:
    p_over = p["ModelProb"] if p["Side"] == "Over" else 1 - p["ModelProb"]
    rl = SE.role(_avg_min(p))
    is_fav = bool(fav) and p.get("Team") == fav
    by = SE.over_by_script(p_over, rl, is_fav, p["Market"], sh)
    rows.append({"p": p, "role": rl, "is_fav": is_fav, "by": by, "p_over": p_over})

st.markdown("##### Every prop under each script")
show_flips = st.toggle("Only props whose side changes with the script", value=False, key="gs_flips")


def _cell(po):
    return f"O {po:.0%}" if po >= 0.5 else f"U {1 - po:.0%}"


tab = []
for r in rows:
    p = r["p"]
    sides = {("Over" if r["by"][s] >= 0.5 else "Under") for s in SE.SCRIPTS}
    if show_flips and len(sides) < 2:
        continue
    tab.append({"Player": p["Player"], "Team": (p.get("Team") or "").split()[-1] + (" (fav)" if r["is_fav"] else ""),
                "Role": r["role"] or "deep bench", "Market": p["Market"], "Line": p["Line"],
                "Model": _cell(r["p_over"]),
                **{SE.LABEL[s].split(" (")[0]: _cell(r["by"][s]) for s in SE.SCRIPTS},
                "Use": p.get("Use") or ""})
if tab:
    st.dataframe(pd.DataFrame(tab), hide_index=True, width="stretch")
else:
    st.caption("No prop changes side across the scripts in this game.")
st.caption("Each cell is the side the model favors under that script and its chance. **Model** is the board's own read "
           "(all scripts mixed by how likely they are). Starters = 26+ minutes; bench = 12–26; deep bench gets no "
           "script shift (not measured).")

# ---------------------------------------------------------------- build a script ticket
st.markdown("##### Build a script ticket")
script = st.radio("If the game goes…", list(SE.SCRIPTS), format_func=lambda s: SE.LABEL[s], horizontal=True,
                  key="gs_script")
cands = []
for r in rows:
    po = r["by"][script]
    side = "Over" if po >= 0.5 else "Under"
    ch = po if side == "Over" else 1 - po
    if ch >= 0.55:
        price = r["p"].get("RealPrice") if side == r["p"]["Side"] else None
        cands.append({"key": f"{r['p']['Player']} {r['p']['Market']} {side} {r['p']['Line']:g}", "r": r, "side": side,
                      "ch": ch, "price": price})
cands.sort(key=lambda c: -c["ch"])
if not cands:
    st.caption("No prop reaches 55% under this script.")
    st.stop()
default, seen = [], set()
for c in cands:
    if c["r"]["p"]["Player"] not in seen and len(default) < 3:
        default.append(c["key"])
        seen.add(c["r"]["p"]["Player"])
pick = st.multiselect("Legs (best fits for this script first)", [c["key"] for c in cands], default=default,
                      key=f"gs_legs_{game}_{script}")
chosen = [c for c in cands if c["key"] in pick]
if chosen:
    legs = [SE.side_chance(c["r"]["by"], c["side"]) for c in chosen]
    scripted, plain, per = SE.ticket(legs, sh)
    k1, k2, k3 = st.columns(3)
    k1.metric("Chance, counting the script", f"{scripted:.1%}",
              f"fair {SE.fair_american(scripted):+d}" if SE.fair_american(scripted) else None, delta_color="off")
    k2.metric("Chance, legs multiplied", f"{plain:.1%}", None)
    k3.metric(f"If it goes '{SE.LABEL[script].split(' (')[0]}'", f"{per[script]:.1%}",
              f"that script: {sh[script]:.0%} likely", delta_color="off")
    st.dataframe(pd.DataFrame([{"Leg": c["key"], "In this script": c["ch"],
                                "Overall (all scripts)": sum(sh[s] * SE.side_chance(c["r"]["by"], c["side"])[s]
                                                             for s in SE.SCRIPTS),
                                "Board price": "" if c["price"] is None else f"{float(c['price']):+.0f}",
                                "Board's tag": c["r"]["p"].get("Use") or ""} for c in chosen]),
                 hide_index=True, width="stretch",
                 column_config={"In this script": st.column_config.NumberColumn(format="percent"),
                                "Overall (all scripts)": st.column_config.NumberColumn(format="percent")})
    st.caption("**Counting the script** is the honest chance for legs that win together; it's above the multiplied "
               "chance when the legs share a script. A same-game parlay is worth it only if the book's payout beats "
               "the fair price shown. Legs priced on the board's other side show no price — check the book.")
st.caption("⚠️ Early tool: script effects are measured against players' own averages (points; other markets get half), "
           "not against prop lines — the books know the spread too, so some of it may already be priced in. Ticket "
           "results are tracked under the game-script tag.")
