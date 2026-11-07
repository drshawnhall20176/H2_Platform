"""
Game Script — every sport with player props (Nov 7; NBA-only earlier the same day). Owner only.

Pick a game; see how likely each kind of game is (from the pre-game line) and how every player prop reads under each
one: favorite blows it open, middle, close, underdog blows it open -- with each sport's own thresholds and its own
measured effects (football: the losing team throws, the winning team runs; hockey: points follow the score). Then
pick a script and build the legs that win together under it, with the ticket's chance counting the script next to
the plain multiplied chance. Base reads come from today's board; the shifts come from research/script_study.py
(script_effects.py), applied only as far as they held up on games they weren't fit on.
"""
from datetime import datetime, timedelta

import pandas as pd
import pytz
import streamlit as st

import best_bets_data as BBD
import components as C
import script_effects as SE
import sports

C.base_css()
C.page_header("🎬", "Game Script", "How each kind of game moves every prop — and the legs that win together.")

SPORT = sports.active_key()
if SPORT not in SE.SPORTS:
    st.info(f"Game Script covers {', '.join(SE.SPORTS)}. Switch sport on the Home page.")
    st.stop()

now_et = datetime.now(pytz.timezone("US/Eastern"))
today = now_et.strftime("%Y-%m-%d")


@st.cache_data(ttl=900, show_spinner="Loading today's board…")
def _board(sport, day):
    plays, meta, _ = BBD.load_generic_best_bets_board(sport, day, BBD.O.DEFAULT_BOOK)
    return [p for p in plays if p.get("Side") in ("Over", "Under") and p.get("Line") is not None
            and p.get("ModelProb") is not None and p.get("LineSource") != "default"]


@st.cache_data(ttl=1800, show_spinner=False)
def _lines(sport, day):
    d0 = datetime.strptime(day, "%Y-%m-%d")
    return SE.fetch_lines(sport, [d0.strftime("%Y%m%d"), (d0 + timedelta(days=1)).strftime("%Y%m%d")])


try:
    plays = _board(SPORT, today)
except Exception as exc:                                        # noqa: BLE001
    st.error(f"Couldn't load today's {SPORT} board ({type(exc).__name__}).")
    st.stop()
if not plays:
    st.info(f"No {SPORT} props on today's board yet.")
    st.stop()

# ---------------------------------------------------------------- evidence for this sport
ev = SE.evidence(SPORT)
if not ev["trusted"]:
    st.warning(f"**{SPORT}: the script effects didn't hold up** on games they weren't fit on, so no prop is shifted "
               "here — every script shows the model's own read. The scenario chances below are still real (how "
               f"{SPORT} games finish by the pre-game line); the ticket math still counts legs that win together.")
else:
    st.caption(f"{SPORT}: shifts applied for **{', '.join(SE.role_label(g) if ':' not in g else g.replace(':', ' ') for g in ev['trusted'])}**"
               + (f"; not for {', '.join(g.replace(':', ' ').replace('_', ' ') for g in ev['untrusted'])} (didn't hold up)"
                  if ev["untrusted"] else "") + f". Measured on {ev['games']:,} games ({ev['lined']:,} with a pre-game line).")

# ---------------------------------------------------------------- game
_kick = lambda p: p.get("GameDate") or p.get("Kickoff") or p.get("kickoff")         # noqa: E731
first = {}
for p in C.by_kickoff(plays, when=_kick):
    if p.get("Game") and p["Game"] not in first:
        first[p["Game"]] = C._kick_dt(_kick(p))
game = st.selectbox("Game", list(first), key="gs_game",
                    format_func=lambda g: g if first.get(g) is None or (first[g].hour == 0 and first[g].minute == 0)
                    else f"{first[g].strftime('%a %-I:%M %p')} — {g}")
gp = [p for p in plays if p.get("Game") == game]
teams = sorted({p.get("Team") for p in gp if p.get("Team")})
if len(teams) < 2 and " @ " in game:
    teams = [t.strip() for t in game.split(" @ ")]
try:
    strength, fav, dog = SE.line_for(teams, _lines(SPORT, today))
except Exception:                                               # noqa: BLE001
    strength, fav, dog = None, None, None
sh = SE.shares(strength, SPORT)
LAB = SE.labels(SPORT)


def _nick(t):
    return (t or "").split()[-1] if t else ""


c1, c2, c3, c4 = st.columns(4)
if strength is None:
    c1.metric("Line", "—")
elif SE.strength_kind(SPORT) == "ml":
    c1.metric("Favorite", f"{_nick(fav)} {strength:.0%}")
else:
    c1.metric("Spread", f"{_nick(fav)} −{strength:g}")
d = SE.DATA[SPORT]
c2.metric(f"{_nick(fav) or 'Favorite'} by {d['blow']}+", f"{sh['fav_blowout']:.0%}")
c3.metric(f"Within {d['close']}", f"{sh['close']:.0%}")
c4.metric(f"{_nick(dog) or 'Underdog'} by {d['blow']}+", f"{sh['dog_blowout']:.0%}")
if strength is None:
    st.caption("No pre-game line found for this game: script chances use the most even-game mix, and no side is "
               "treated as the favorite.")
st.caption(f"{LAB['middle']}: {sh['middle']:.0%}. From {d.get('lined') or 0:,} {SPORT} games with a pre-game line, by "
           f"{'the favorite’s moneyline chance' if SE.strength_kind(SPORT) == 'ml' else 'the pre-game spread'}.")


def _avg_min(p):
    log = p.get("_game_log") or []
    mins = [float(g.get("min") or 0) for g in log[-10:] if g.get("min") is not None]
    return sum(mins) / len(mins) if mins else None


rows = []
for p in gp:
    p_over = p["ModelProb"] if p["Side"] == "Over" else 1 - p["ModelProb"]
    grp = SE.group(SPORT, p["Market"], _avg_min(p))
    is_fav = bool(fav) and SE.team_matches(p.get("Team"), {SE.norm(fav)})
    by = SE.over_by_script(p_over, grp if fav else None, is_fav, sh, SPORT)
    rows.append({"p": p, "grp": grp, "is_fav": is_fav, "by": by, "p_over": p_over})

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
    tab.append({"Player": p["Player"], "Team": _nick(p.get("Team")) + (" (fav)" if r["is_fav"] else ""),
                "Group": SE.role_label(r["grp"]) + ("" if SE.trust(SPORT, r["grp"]) > 0 else " · no shift"),
                "Market": p["Market"], "Line": p["Line"], "Model": _cell(r["p_over"]),
                **{SE.short(SPORT, s): _cell(r["by"][s]) for s in SE.SCRIPTS},
                "Use": p.get("Use") or ""})
if tab:
    st.dataframe(pd.DataFrame(tab), hide_index=True, width="stretch")
else:
    st.caption("No prop changes side across the scripts in this game.")
st.caption("Each cell is the side the model favors under that script and its chance. **Model** is the board's own read "
           "(all scripts mixed by how likely they are). **no shift** = that market's script effect didn't hold up on "
           "held-out games (or isn't measured), so it reads the same in every script.")

# ---------------------------------------------------------------- build a script ticket
st.markdown("##### Build a script ticket")
script = st.radio("If the game goes…", list(SE.SCRIPTS), format_func=lambda s: LAB[s], horizontal=True, key="gs_script")
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
                      key=f"gs_legs_{SPORT}_{game}_{script}")
chosen = [c for c in cands if c["key"] in pick]
if chosen:
    legs = [SE.side_chance(c["r"]["by"], c["side"]) for c in chosen]
    scripted, plain, per = SE.ticket(legs, sh)
    k1, k2, k3 = st.columns(3)
    k1.metric("Chance, counting the script", f"{scripted:.1%}",
              f"fair {SE.fair_american(scripted):+d}" if SE.fair_american(scripted) else None, delta_color="off")
    k2.metric("Chance, legs multiplied", f"{plain:.1%}", None)
    k3.metric(f"If it goes '{SE.short(SPORT, script)}'", f"{per[script]:.1%}",
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
st.caption("⚠️ Early tool: script effects are measured against players' own averages, not against prop lines — the "
           "books know the line too, so some of it may already be priced in. Ticket results are tracked under the "
           "game-script tag.")
