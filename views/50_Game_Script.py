"""
Game Script — every sport with player props (Nov 7). Owner only.

Pick a date and a game; see how likely each kind of game is (from the pre-game line). Then pick a condition --
Favorite blows it open / Middle / Close game / Underdog blows it open -- and every prop is re-read under it: the side
the script favors, its chance, the edge at that side's price, and the Use tag re-run through the platform's own rules
(props_engine.use_tag) on those numbers. Build the legs that win together under it; the ticket's chance counts the
script. Earlier dates load the kickoff snapshots (the board as it stood before the game) and show how each prop and the
game actually went, so a script call can be checked after the fact.

Shifts come from research/script_study.py (script_effects.py), each market only as far as its effect held up when the
script happens (held-out games).
"""
from datetime import datetime, timedelta

import pandas as pd
import pytz
import streamlit as st

import best_bets_data as BBD
import components as C
import model_store as MS
import props_engine as PE
import script_effects as SE
import sports

C.base_css()
C.page_header("🎬", "Game Script", "How each kind of game moves every prop — and the legs that win together.")

SPORT = sports.active_key()
if SPORT not in SE.SPORTS:
    st.info(f"Game Script covers {', '.join(SE.SPORTS)}. Switch sport on the Home page.")
    st.stop()
FIT = SE.refresh(SPORT)                                         # Nov 7: the nightly fit (script_learn.py), when there is one

ET = pytz.timezone("US/Eastern")
today = datetime.now(ET).date()
day = st.date_input("Date", today, max_value=today, key="gs_date", format="MM/DD/YYYY",
                    help="Earlier dates show the board as it stood before each game, and how it went.")
DAY = day.strftime("%Y-%m-%d")
PAST = day < today


@st.cache_data(ttl=900, show_spinner="Loading the board…")
def _rows(sport, d, live):
    snaps = [r for r in (SE.from_snapshot(s) for s in MS.load_snapshots(sport, [d])) if r]
    if snaps or not live:
        return snaps, "snapshots"
    plays, _meta, _ = BBD.load_generic_best_bets_board(sport, d, BBD.O.DEFAULT_BOOK)
    return [SE.from_play(p) for p in plays if p.get("Side") in ("Over", "Under") and p.get("Line") is not None
            and p.get("ModelProb") is not None and p.get("LineSource") != "default"], "board"


@st.cache_data(ttl=3600, show_spinner="Reading minutes before that date…")
def _minutes(sport, d):
    try:
        rows, _ = sports.get(sport).engine.build_slate(d)
    except Exception:                                           # noqa: BLE001
        return {}
    return {PE.norm_name(r.get("Player") or ""): r.get("AvgMin") for r in rows or [] if r.get("AvgMin") is not None}


@st.cache_data(ttl=1800, show_spinner=False)
def _lines(sport, d):
    d0 = datetime.strptime(d, "%Y-%m-%d")
    return SE.fetch_lines(sport, [d0.strftime("%Y%m%d"), (d0 + timedelta(days=1)).strftime("%Y%m%d")])


@st.cache_data(ttl=1800, show_spinner="Grading against the box scores…")
def _results(sport, d):
    import postgame as PG
    snaps = MS.load_snapshots(sport, [d])
    if not snaps:
        return {}
    res = PG.fetch_results(sport, d, sorted({(s["team"], s["opp"]) for s in snaps}))
    return {(PE.norm_name(g.get("player") or ""), g.get("market")): g.get("actual") for g in PG.grade(snaps, res)
            if g.get("actual") is not None}


try:
    rows, source = _rows(SPORT, DAY, not PAST)
except Exception as exc:                                        # noqa: BLE001
    st.error(f"Couldn't load the {SPORT} board ({type(exc).__name__}).")
    st.stop()
if not rows:
    st.info(f"No {SPORT} props saved for {day:%a %b %-d}." if PAST else f"No {SPORT} props on today's board yet.")
    st.stop()
if SE.FAMILY[SPORT] == "hoops" and any(r.get("mins") is None for r in rows):
    mins = _minutes(SPORT, DAY)
    for r in rows:
        if r.get("mins") is None:
            r["mins"] = mins.get(PE.norm_name(r.get("player") or ""))
actuals = _results(SPORT, DAY) if PAST else {}

# ---------------------------------------------------------------- evidence for this sport
ev = SE.evidence(SPORT)
if not ev["trusted"]:
    st.warning(f"**{SPORT}: no market's script effect held up** on held-out games, so props read the same under every "
               "condition. The scenario chances are still real, and the ticket math still counts legs that win together.")

# ---------------------------------------------------------------- game
_kick = lambda r: r.get("kickoff")                              # noqa: E731
first = {}
for r in C.by_kickoff(rows, when=_kick):
    if r.get("game") and r["game"] not in first:
        first[r["game"]] = C._kick_dt(_kick(r))
game = st.selectbox("Game", list(first), key="gs_game",
                    format_func=lambda g: g if first.get(g) is None else f"{first[g].strftime('%a %-I:%M %p')} — {g}")
gp = [r for r in rows if r.get("game") == game]
teams = SE.game_teams(gp, game)
try:
    lines = _lines(SPORT, DAY)
    g_espn = SE.game_for(teams, lines)
except Exception:                                               # noqa: BLE001
    g_espn = None
strength = g_espn["strength"] if g_espn else None
fav = g_espn["teams"][g_espn["fav"]]["display"] if g_espn else None
dog = g_espn["teams"][1 - g_espn["fav"]]["display"] if g_espn else None
FAV_NAMES = SE.fav_names(g_espn)
CALL = SE.scenario_call(SPORT, teams, DAY)
if CALL:                                                        # the call logged before the game (graded once it's final)
    sh, SRC = dict(CALL["p"]), CALL.get("source") or "table"
    if not g_espn:
        strength, fav, dog = CALL.get("strength"), CALL.get("fav"), CALL.get("dog")
        FAV_NAMES = {SE.norm(fav), SE.norm(str(CALL.get("fav_id")))}
else:
    sh, SRC = SE.scenario_probs(SPORT, strength)
LAB = SE.labels(SPORT)
D = SE.DATA[SPORT]


def _nick(t):
    return (t or "").split()[-1] if t else ""


c1, c2, c3, c4 = st.columns(4)
if strength is None:
    c1.metric("Line", "—")
elif SE.strength_kind(SPORT) == "ml":
    c1.metric("Favorite", f"{_nick(fav)} {strength:.0%}")
else:
    c1.metric("Spread", f"{_nick(fav)} −{strength:g}")
c2.metric(f"{_nick(fav) or 'Favorite'} by {D['blow']}+", f"{sh['fav_blowout']:.0%}")
c3.metric(f"Within {D['close']}", f"{sh['close']:.0%}")
c4.metric(f"{_nick(dog) or 'Underdog'} by {D['blow']}+", f"{sh['dog_blowout']:.0%}")
happened = SE.actual_script(g_espn, SPORT) if g_espn else None
if g_espn and g_espn.get("final"):
    t0, t1 = g_espn["teams"]
    st.success(f"**Final:** {t0['display']} {t0['score']:g} – {t1['display']} {t1['score']:g} → "
               f"**{LAB[happened]}**" if happened else "Final.")
if strength is None:
    st.caption("No pre-game line found for this game: script chances use the most even-game mix, and neither side is "
               "treated as the favorite (no prop is shifted).")
SRC_TEXT = {"table": "the scenario table (how games with this size of line finished)",
            "line": "the line curve (refit nightly; beat the table on held-out games)",
            "matchup": "the line + matchup model (refit nightly; beat the line alone on held-out games)"}
st.caption(f"{LAB['middle']}: {sh['middle']:.0%}. Scenario chances from {SRC_TEXT.get(SRC, SRC)}"
           + (", logged before the game" if CALL else "") + f" · {D.get('lined') or 0:,} {SPORT} games with a line"
           + (f", learned through {str(D.get('fit_at'))[:10]}" if D.get("fit_at") else " (shipped numbers — the nightly "
              "learning job hasn't run yet)") + ".")
if CALL and CALL.get("why"):
    st.caption("**Why the call moved off the line:** " + "; ".join(
        f"{w[0]} → {'more' if w[2] > 0 else 'less'} likely {SE.short(SPORT, w[1]).lower()}" for w in CALL["why"]))
if CALL and CALL.get("y"):
    st.caption(f"**Graded:** called {sh[CALL['y']]:.0%} for what happened ({LAB[CALL['y']]}); favorite's margin "
               f"{CALL.get('margin'):+g}.")
ctx = (CALL or {}).get("context") or {}
if ctx.get("fav") or ctx.get("dog"):
    def _ctx(lbl, t):
        if not t:
            return None
        return {"Team": lbl, "Games": t["n"], f"Won by {D['blow']}+": t["won_big"], f"Lost by {D['blow']}+": t["lost_big"],
                f"Within {D['close']}": t["close"], "Avg margin": t["avg_margin"],
                "Last 5 margins": " ".join(f"{m:+d}" for m in t["last5"]), "Back-to-back": "yes" if t["b2b"] else ""}
    with st.expander("Matchup context this season"):
        st.dataframe(pd.DataFrame([x for x in (_ctx(f"{_nick(fav)} (fav)", ctx.get("fav")), _ctx(f"{_nick(dog)}", ctx.get("dog"))) if x]),
                     hide_index=True, width="stretch")
        st.caption("Background, not part of the numbers: tested nightly against games it wasn't fit on, this season's "
                   "blowout records, schedule-adjusted margins, pace and rest haven't improved the call beyond the line "
                   "yet — the line already prices them. The job promotes them automatically if that changes.")

# ---------------------------------------------------------------- condition buttons
COND = ["model"] + list(SE.SCRIPTS)
COND_LABEL = {"model": "Model (no script)", "fav_blowout": f"⬆️ {_nick(fav) or 'Favorite'} blows it open",
              "middle": "↔️ Middle", "close": "🤝 Close game", "dog_blowout": f"⬇️ {_nick(dog) or 'Underdog'} blows it open"}
cond = st.segmented_control("If the game goes…", COND, format_func=lambda c: COND_LABEL[c], default="model",
                            key="gs_cond", selection_mode="single") or "model"
if cond != "model":
    st.caption(f"Every prop below re-read **as if the game goes '{SE.short(SPORT, cond)}'** ({sh[cond]:.0%} likely from "
               "the line): the side the script favors, its chance, the edge at that side's price, and the Use tag from "
               "the platform's own rules on those numbers. A tag here is conditional — it's only as good as the call.")

# ---------------------------------------------------------------- the whole roster, minutes and usage (basketball)
@st.cache_data(ttl=3600, show_spinner="Reading both rosters (minutes and usage)…")
def _roster(sport, d, teams_key):
    import roster_usage as RU
    return RU.game_rows(sport, [{"id": i, "name": n} for i, n in teams_key], d)


roster = []
if SE.FAMILY[SPORT] == "hoops" and g_espn and all(t.get("id") for t in g_espn["teams"]):
    try:
        roster = _roster(SPORT, DAY, tuple((str(t["id"]), t["display"]) for t in g_espn["teams"]))
    except Exception:                                           # noqa: BLE001
        roster = []
R_BY = {PE.norm_name(x["player"] or ""): x for x in roster}
# Nov 7: saved boards store ESPN team ids ("7", "11"); show names
TEAM_NAME = {str(t.get("id")): t["display"] for t in (g_espn or {}).get("teams", []) if t.get("id") is not None}


def _team(t):
    return TEAM_NAME.get(str(t), t) if t is not None else t
for r in gp:                                                    # the roster's minutes place props players too
    rr = R_BY.get(PE.norm_name(r.get("player") or ""))
    if rr and rr.get("min") is not None and r.get("mins") is None:
        r["mins"] = rr["min"]

prepared = []
for r in gp:
    grp = SE.group(SPORT, r["market"], r.get("mins"))
    is_fav = bool(FAV_NAMES) and SE.team_matches(r.get("team"), FAV_NAMES)
    by = SE.over_by_script(r["p_over"], grp if fav else None, is_fav, sh, SPORT)
    p_now = r["p_over"] if cond == "model" else by[cond]
    u = SE.script_use(r, p_now, SPORT) if cond != "model" else {
        "side": r["side"], "chance": r["p_over"] if r["side"] == "Over" else 1 - r["p_over"], "ev": None,
        "use": r.get("use") or "", "why": "", "price": r.get("over_price") if r["side"] == "Over" else r.get("under_price")}
    act = actuals.get((PE.norm_name(r.get("player") or ""), r["market"]))
    res = None
    if act is not None:
        thr = PE.threshold(float(r["line"]))
        res = "push" if act == thr else ("win" if (act > thr) == (u["side"] == "Over") else "loss")
    mby = SE.minutes_by_script(SPORT, r.get("mins"), is_fav, sh) if fav else {}
    prepared.append({"r": r, "grp": grp, "is_fav": is_fav, "by": by, "u": u, "actual": act, "result": res,
                     "min_if": mby.get(cond) if cond != "model" else None})

g1, g2, g3 = st.columns(3)
_groups = sorted({SE.role_label(x["grp"]) for x in prepared})
_markets = sorted({x["r"]["market"] for x in prepared})
_teams = sorted({_nick(_team(x["r"].get("team"))) for x in prepared if x["r"].get("team")})
pick_groups = g1.multiselect("Group", _groups, key="gs_f_group", placeholder="All groups")
pick_markets = g2.multiselect("Market", _markets, key="gs_f_market", placeholder="All markets")
pick_teams = g3.multiselect("Team", _teams, key="gs_f_team", placeholder="Both teams")
f1, f2 = st.columns(2)
only_play = f1.toggle("Only playable under this condition", value=False, key="gs_only_play")
only_changed = f2.toggle("Only props whose read changes", value=False, key="gs_only_changed", disabled=cond == "model")
PLAY = {PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE}
show = []
for x in prepared:
    if pick_groups and SE.role_label(x["grp"]) not in pick_groups:
        continue
    if pick_markets and x["r"]["market"] not in pick_markets:
        continue
    if pick_teams and _nick(_team(x["r"].get("team"))) not in pick_teams:
        continue
    if only_play and x["u"]["use"] not in PLAY:
        continue
    if only_changed and cond != "model" and x["u"]["use"] == (x["r"].get("use") or "") and x["u"]["side"] == x["r"]["side"]:
        continue
    show.append(x)
show.sort(key=lambda x: (x["u"]["use"] not in PLAY, -x["u"]["chance"]))
# Nov 7: everyone else on both rosters, so a condition shows its whole-roster effect here too (minutes, and how much
# likelier he is to beat his own points / rebounds / assists average); no line, so no side, price or tag
with_props = {PE.norm_name(x["r"]["player"] or "") for x in prepared}
extra = []
if roster and not pick_markets and not only_play:
    for x in roster:
        if PE.norm_name(x["player"] or "") in with_props or not x.get("games"):
            continue
        tf = bool(FAV_NAMES) and SE.team_matches(x["team"], FAV_NAMES)
        rl = SE.role(x["min"], SPORT)
        if pick_groups and (rl or "—") not in pick_groups:
            continue
        if pick_teams and _nick(x["team"]) not in pick_teams:
            continue
        bits, moved = [], False
        if cond != "model" and fav and rl:
            mby = SE.minutes_by_script(SPORT, x["min"], tf, sh)
            if mby:
                bits.append(f"minutes {x['min']:.0f} → {mby[cond]:.0f}")
            for stat, lab in (("points", "pts"), ("rebounds", "reb"), ("assists", "ast")):
                g_ = f"{rl}:{stat}"
                if SE.trust(SPORT, g_) > 0:
                    d = SE.over_by_script(0.5, g_, tf, sh, SPORT)[cond] - 0.5
                    if abs(d) >= 0.005:
                        bits.append(f"{lab} {d * 100:+.0f}%")
                        moved = moved or abs(d) >= 0.02
        if only_changed and not moved:
            continue
        extra.append({"x": x, "tf": tf, "rl": rl, "mby": (SE.minutes_by_script(SPORT, x["min"], tf, sh) if fav else {}),
                      "why": ("if it goes this way: " + ", ".join(bits) + " (vs his own averages)") if bits else ""})
ICON = {"win": "✅", "loss": "❌", "push": "➖"}
MIN_IF = f"Min if {SE.short(SPORT, cond).lower()}" if cond != "model" else "Min if"
if show or extra:
    df = pd.DataFrame([{
        "Player": x["r"]["player"], "Team": _nick(_team(x["r"].get("team"))) + (" (fav)" if x["is_fav"] else ""),
        "Group": SE.role_label(x["grp"]) + ("" if SE.trust(SPORT, x["grp"]) > 0 and fav else " · no shift"),
        "Min": x["r"].get("mins"),
        "Min if": x["min_if"],
        "Usage %": (R_BY.get(PE.norm_name(x["r"]["player"] or "")) or {}).get("usg"),
        "Market": x["r"]["market"], "Line": x["r"]["line"],
        "Board": f"{x['r']['side']} {(x['r']['p_over'] if x['r']['side'] == 'Over' else 1 - x['r']['p_over']):.0%} · "
                 f"{x['r'].get('use') or '—'}",
        "Side": x["u"]["side"], "Chance": x["u"]["chance"],
        "Price": "—" if x["u"].get("price") is None else f"{float(x['u']['price']):+.0f}",
        "Edge": x["u"]["ev"], "Use": x["u"]["use"], "Why": x["u"]["why"],
        "Actual": "" if x["actual"] is None else f"{x['actual']:g}",
        "Result": ICON.get(x["result"], "")} for x in show] + [{
        "Player": e["x"]["player"], "Team": _nick(e["x"]["team"]) + (" (fav)" if e["tf"] else ""),
        "Group": e["rl"] or "under 3 min", "Min": e["x"]["min"],
        "Min if": e["mby"].get(cond) if cond != "model" else None, "Usage %": e["x"]["usg"],
        "Market": "— no line", "Line": None, "Board": "", "Side": "", "Chance": None, "Price": "", "Edge": None,
        "Use": "", "Why": e["why"], "Actual": "", "Result": ""} for e in extra])
    if cond == "model":
        df = df.drop(columns=["Board", "Edge", "Why", "Min if"])
    if not PAST:
        df = df.drop(columns=["Actual", "Result"])
    df = df.drop(columns=[c for c in ("Min", "Usage %", "Min if") if c in df and not df[c].notna().any()])
    if "Min if" in df:
        df = df.rename(columns={"Min if": MIN_IF})
    st.dataframe(df, hide_index=True, width="stretch",
                 column_config={"Chance": st.column_config.NumberColumn(format="percent"),
                                "Edge": st.column_config.NumberColumn(format="percent"),
                                "Min": st.column_config.NumberColumn(format="%.1f"),
                                MIN_IF: st.column_config.NumberColumn(
                                    format="%.1f", help="His average minutes plus his role's measured change in this "
                                                        "kind of game (losing starters sit, the winners' bench plays)."),
                                "Usage %": st.column_config.NumberColumn(format="%.1f%%")})
    if extra:
        st.caption(f"Includes **{len(extra)} rostered players with no line posted** (Market '— no line'): their "
                   "minutes and how much likelier they are to beat their own averages under this condition. Pick a "
                   "Market or 'Only playable' to see props only.")
    if PAST:
        gr = [x for x in show if x["result"] in ("win", "loss")]
        pl = [x for x in gr if x["u"]["use"] in PLAY]
        if gr:
            st.caption(f"Under **{COND_LABEL[cond]}**: the listed sides went **{sum(x['result'] == 'win' for x in gr)}–"
                       f"{sum(x['result'] == 'loss' for x in gr)}**"
                       + (f"; the playable-tagged ones **{sum(x['result'] == 'win' for x in pl)}–"
                          f"{sum(x['result'] == 'loss' for x in pl)}**" if pl else "") + ".")
else:
    st.caption("No props match these filters.")
st.caption("**Board** = the board's own read and tag before the game. **no shift** = that market's script effect didn't "
           "hold up (or isn't measured, or there's no line for the game), so it reads the same under every condition — "
           "its tag can still change when the side's price differs. Blowout-risk warnings are dropped under a script "
           "(the script is the blowout call); news warnings stay.")

# ---------------------------------------------------------------- every rostered player under this condition
if roster:
    st.markdown("##### Full roster" + ("" if cond == "model" else f" — if it goes '{SE.short(SPORT, cond)}'"))
    have = {}
    for x in prepared:
        have[PE.norm_name(x["r"]["player"] or "")] = have.get(PE.norm_name(x["r"]["player"] or ""), 0) + 1
    rr_rows = []
    for x in roster:
        team_is_fav = bool(FAV_NAMES) and SE.team_matches(x["team"], FAV_NAMES)
        rl = SE.role(x["min"], SPORT)
        _mby = SE.minutes_by_script(SPORT, x["min"], team_is_fav, sh) if (fav and cond != "model") else {}
        row = {"Player": x["player"], "Team": _nick(x["team"]) + (" (fav)" if team_is_fav else ""),
               "Role": rl or ("did not play" if not x["games"] else "under 3 min"), "Min": x["min"],
               **({"Min if": _mby.get(cond)} if cond != "model" else {}), "Usage %": x["usg"],
               "Games": x["games"], "Pts": x["pts"], "Reb": x["reb"], "Ast": x["ast"],
               "Props today": have.get(PE.norm_name(x["player"] or ""), 0)}
        if cond != "model":
            for stat, col in (("points", "Pts vs avg"), ("rebounds", "Reb vs avg"), ("assists", "Ast vs avg")):
                grp = f"{rl}:{stat}" if rl else None
                if grp and fav and SE.trust(SPORT, grp) > 0:
                    row[col] = SE.over_by_script(0.5, grp, team_is_fav, sh, SPORT)[cond] - 0.5
                else:
                    row[col] = None
        if not pick_teams or _nick(x["team"]) in pick_teams:
            if not pick_groups or (rl or "—") in pick_groups:
                rr_rows.append(row)
    if rr_rows:
        rdf = pd.DataFrame(rr_rows)
        cfg = {"Min": st.column_config.NumberColumn(format="%.1f"), "Min if": st.column_config.NumberColumn(format="%.1f"),
               "Usage %": st.column_config.NumberColumn(format="%.1f%%"),
               "Pts": st.column_config.NumberColumn(format="%.1f"), "Reb": st.column_config.NumberColumn(format="%.1f"),
               "Ast": st.column_config.NumberColumn(format="%.1f")}
        for col in ("Pts vs avg", "Reb vs avg", "Ast vs avg"):
            cfg[col] = st.column_config.NumberColumn(format="%+.0f%%", help="How much more (or less) likely than usual he "
                                                     "beats his own average in that stat, if the game goes this way.")
            if col in rdf:
                rdf[col] = rdf[col] * 100
        st.dataframe(rdf, hide_index=True, width="stretch", column_config=cfg)
    st.caption("Everyone on both rosters, by recent minutes (last 10 games before this date; early in the season some "
               "are last season's). **Usage %** = share of his team's plays he finishes while on the floor (shots, free "
               "throws, turnovers). **Props today** = lines on the board for him." + (
                   " **vs avg** = how much more or less likely he beats his own average in that stat if the game goes "
                   "this way — blank where the effect isn't measured yet (deep reserves: the nightly job is measuring "
                   "them now) or there's no line for the game." if cond != "model" else
                   " Pick a condition above to see how each player's output moves under it."))

# ---------------------------------------------------------------- build a ticket under this condition
st.markdown("##### Build a ticket" + ("" if cond == "model" else f" for '{SE.short(SPORT, cond)}'"))
cands = [x for x in prepared if x["u"]["chance"] >= 0.55]
cands.sort(key=lambda x: (x["u"]["use"] not in PLAY, -x["u"]["chance"]))
if not cands:
    st.caption("No prop reaches 55% under this condition.")
    st.stop()


def _key(x):
    return f"{x['r']['player']} {x['r']['market']} {x['u']['side']} {x['r']['line']:g}"


default, seen = [], set()
for x in cands:
    if x["r"]["player"] not in seen and len(default) < 3 and x["u"]["use"] in PLAY:
        default.append(_key(x))
        seen.add(x["r"]["player"])
pick = st.multiselect("Legs (playable under this condition first)", [_key(x) for x in cands], default=default,
                      key=f"gs_legs_{SPORT}_{DAY}_{game}_{cond}")
chosen = [x for x in cands if _key(x) in pick]
if chosen:
    legs = [SE.side_chance(x["by"], x["u"]["side"]) for x in chosen]
    scripted, plain, per = SE.ticket(legs, sh)
    k1, k2, k3 = st.columns(3)
    k1.metric("Chance, counting the script", f"{scripted:.1%}",
              f"fair {SE.fair_american(scripted):+d}" if SE.fair_american(scripted) else None, delta_color="off")
    k2.metric("Chance, legs multiplied", f"{plain:.1%}", None)
    if cond != "model":
        k3.metric(f"If it goes '{SE.short(SPORT, cond)}'", f"{per[cond]:.1%}", f"that script: {sh[cond]:.0%} likely",
                  delta_color="off")
    st.dataframe(pd.DataFrame([{"Leg": _key(x), "Chance here": x["u"]["chance"],
                                "Overall (all scripts)": sum(sh[s] * SE.side_chance(x["by"], x["u"]["side"])[s] for s in SE.SCRIPTS),
                                "Price": "" if x["u"].get("price") is None else f"{float(x['u']['price']):+.0f}",
                                "Use here": x["u"]["use"], "Board's tag": x["r"].get("use") or "",
                                **({"Result": ICON.get(x["result"], "")} if PAST else {})} for x in chosen]),
                 hide_index=True, width="stretch",
                 column_config={"Chance here": st.column_config.NumberColumn(format="percent"),
                                "Overall (all scripts)": st.column_config.NumberColumn(format="percent")})
    if PAST and all(x["result"] in ("win", "loss", "push") for x in chosen):
        won = all(x["result"] in ("win", "push") for x in chosen)
        st.markdown(f"**This ticket {'✅ would have won' if won else '❌ would have lost'}.**")
    st.caption("**Counting the script** is the honest chance for legs that win together; it's above the multiplied "
               "chance when the legs share a script. A same-game parlay is worth it only if the book's payout beats "
               "the fair price shown.")
st.caption("⚠️ Script effects are measured against players' own averages, not prop lines — the books know the line too, "
           "so some of it may already be priced in. Ticket results are tracked under the game-script tag.")

# ---------------------------------------------------------------- the feedback loop's record
with st.expander(f"📈 How the pre-game calls have done ({SPORT})"):
    tr = D.get("track") or {}
    sc = D.get("scenario") or {}
    if tr.get("n"):
        st.markdown(f"**{tr['n']:,} graded calls.** Log loss {tr['model']:.3f} vs the table's {tr['table']:.3f} on the "
                    "same games (lower is better).")
        bands = []
        for k, v in sorted((tr.get("bands") or {}).items()):
            cls, rng = k.split("|")
            bands.append({"Scenario": SE.short(SPORT, cls), "Called": rng.replace("-", "–"), "Games": v["n"],
                          "Said (avg)": v["said"], "Happened": v["happened"]})
        if bands:
            st.dataframe(pd.DataFrame(bands), hide_index=True, width="stretch",
                         column_config={"Said (avg)": st.column_config.NumberColumn(format="percent"),
                                        "Happened": st.column_config.NumberColumn(format="percent")})
    else:
        st.caption("No graded calls yet: the nightly job logs each game's call before it starts and grades it after.")
    ev_ = sc.get("eval") or {}
    if ev_:
        st.dataframe(pd.DataFrame([{"Held-out test": h, "Games": v["n"], "Table": v["table"], "Line curve": v["line"],
                                    "Line + matchup": v["matchup"]} for h, v in ev_.items()]),
                     hide_index=True, width="stretch")
        st.caption(f"Log loss on games each model wasn't fit on (lower is better). In use: **{SRC_TEXT.get(sc.get('source'), '—')}**. "
                   "Re-tested every night as games finish.")
