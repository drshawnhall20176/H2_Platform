"""
Soft Spots — tonight's softest defense-vs-position matchups, NBA (Nov 25, second PropSeason pass).

Each defense's allowed-per-game to guards / forwards / centers, ranked across the league (soft_spots.py), the players
who line up there tonight, and each player's H2 pick on tonight's board with its earned chance and Bet? verdict.
Context, not a call: a soft spot with no pick is just a tendency.
"""
import json
from datetime import datetime

import pytz
import streamlit as st

import components as C
import h2_brand as HB
import position_data as PD
import position_matchups as PM
import soft_spots as SS
import todays_best as TB

C.base_css()
C.page_header("🎯", "Soft Spots",
              "Tonight's defenses that give up the most to a position, and who lines up there. Context, not a call: "
              "each player shows his H2 pick (if any) with its earned chance and Bet? verdict.")
eastern = pytz.timezone("US/Eastern")
day = st.date_input("Date", datetime.now(eastern).date(), key="ss_day", format="MM/DD/YYYY").strftime("%Y-%m-%d")
# Nov 26 (owner, "build all 7"): every sport with a league-wide defense table -- NFL, college football, NBA, college
# hoops. NHL isn't here: our hockey sample is only the two teams' last 10 games, so there's no league ranking to make.
try:
    import sports as _sports
    _act = _sports.active().key
except Exception:                                               # noqa: BLE001
    _act = "NBA"
sport = st.pills("Sport", list(SS.SPORTS), default=_act if _act in SS.SPORTS else "NBA", key="ss_sport") or "NBA"


def _other_sport(sport: str, day: str) -> None:
    try:
        data = SS.cached_league(sport, day)
    except Exception as exc:                                    # noqa: BLE001
        st.warning(f"The league's defensive numbers couldn't be read just now ({type(exc).__name__}). "
                   "Try again shortly.")
        return
    if not data.get("games") or not data.get("summary"):
        st.info(f"No {sport} games for this date (football reads the week the date falls in).")
        return
    stats_ = SS.stats_for(sport)
    slots_ = SS.slots_for(sport)
    c1, c2 = st.columns(2)
    stat = c1.pills("Stat", ["all"] + list(stats_), default="all", key=f"ss_stat_{sport}",
                    format_func=lambda k: "All" if k == "all" else stats_[k].title()) or "all"
    slot = c2.pills("Position", ["all"] + list(slots_), default="all", key=f"ss_slot_{sport}",
                    format_func=lambda k: "All" if k == "all" else k) or "all"
    rows = SS.spots_any(sport, data["summary"], SS.tonight_pairs(data["games"]), SS.depth_fn(sport, data),
                        data.get("names") or {}, stats=None if stat == "all" else (stat,),
                        slots=None if slot == "all" else (slot,))
    st.caption(f"{len(rows)} soft spot{'s' if len(rows) != 1 else ''} — defenses in the league's top sixth for what "
               f"they allow at a position, and {SS.SOFT_PCT:.0%}+ above the average defense. Most-allowed first.")
    if not rows:
        st.info("No soft spots for this filter.")
    try:
        picks = TB.load_all_props(sport, day)
    except Exception:                                           # noqa: BLE001
        picks = []
    for s in rows[:40]:
        with st.container(border=True):
            st.markdown(f'<span style="color:{HB.BLUE};font-weight:800;font-size:12px;letter-spacing:.06em;">'
                        f'{s["grade"]} · {s["slot"]} · {stats_[s["stat"]].upper()}</span>'
                        f'<div style="color:{HB.INK};font-weight:700;margin-top:2px;">{SS.headline_any(s)}</div>'
                        f'<div style="color:{HB.INK_SOFT};font-size:12px;">{s["offense"]} · {s["game"]}'
                        f'{" · " + s["time"] if s.get("time") else ""}</div>', unsafe_allow_html=True)
            names_ = [p.get("name") for p in s["players"] if p.get("name")]
            if not names_:
                st.caption("No regular at this position for them lately.")
            for nm in names_:
                pk = SS.pick_for(nm, picks)
                st.markdown(f"**{nm}** · " + (f"H2 pick: {pk.get('pick')}"
                                               + ("" if pk.get("chance") is None else f" · earned {float(pk['chance']):.0%}")
                                               if pk else "no H2 pick on him"))
    st.caption("A soft spot is a tendency, not a pick: the model already prices each defense into its projections. "
               "The letter is the rank as a grade (A+ = among the softest).")


if sport != "NBA":
    _other_sport(sport, day)
    st.stop()


@st.cache_data(ttl=900, show_spinner="Reading the league's defenses…", max_entries=4)
def _load(day: str):
    games = PD.list_games("NBA", day)
    if not games:
        return [], None
    b = PD.load_bundle("NBA", day, games[0], False)
    pg = (b.get("props") or {}).get("pgames") or []
    return games, {"summary": PM.summarize(b.get("allowed") or {}, "NBA"),
                   "pgames": pg, "names": b.get("all_names") or {}}


@st.cache_data(ttl=600, show_spinner=False, max_entries=4)
def _picks(day: str):
    return TB.load_all_props("NBA", day)


try:
    games, data = _load(day)
except Exception as exc:                                        # noqa: BLE001
    st.warning(f"The league's defensive numbers couldn't be read just now ({type(exc).__name__}). Try again shortly.")
    st.stop()
if not games or not data:
    st.info("No NBA games on this date.")
    st.stop()

c1, c2 = st.columns(2)
# Nov 25 (live check): small numbers make big percentages (centers' threes +84%), so Points is the default view
stat = c1.pills("Stat", list(SS.STATS) + ["all"], default="pts", key="ss_stat",
                format_func=lambda k: "All" if k == "all" else SS.STATS[k].title()) or "pts"
slot = c2.pills("Position", ["all"] + list(SS.SLOT_NAME), default="all", key="ss_slot",
                format_func=lambda k: "All" if k == "all" else SS.SLOT_NAME[k].title()) or "all"
tonight = []
for g in games:
    when = str(g.get("label") or "")
    tonight += [(g["home_id"], g["away_id"], f"{g.get('away')} @ {g.get('home')}", when),
                (g["away_id"], g["home_id"], f"{g.get('away')} @ {g.get('home')}", when)]
depth_cache = {}


def depth_of(team):
    if team not in depth_cache:
        depth_cache[team] = PM.usage_depth(data["pgames"], team, "NBA", last_n=10)
    return depth_cache[team]


rows = SS.spots(data["summary"], tonight, depth_of, data["names"],
                stats=tuple(SS.STATS) if stat == "all" else (stat,),
                slots=tuple(SS.SLOT_NAME) if slot == "all" else (slot,))
picks = _picks(day)
st.caption(f"{len(rows)} soft spot{'s' if len(rows) != 1 else ''} on this slate — defenses allowing {SS.SOFT_PCT:.0%}+ "
           "more than the average defense at a position, softest first. From each defense's recent games (the same "
           "sample Position Matchups uses).")
if not rows:
    st.info("No defense on tonight's slate is 10%+ softer than average at a position for this filter.")
try:
    import today_visual as TV
    player_dlg = TV._player_dialog
except Exception:                                               # noqa: BLE001
    player_dlg = None
import game_previews as GP
import injury_check as IC
_live = IC.live_for(day)


def _inj(name):
    """Nov 25: tonight's injury report, so a soft spot never points at a player who won't play."""
    try:
        return IC.status("NBA", name) if _live else None
    except Exception:                                           # noqa: BLE001
        return None


for i, s in enumerate(rows[:24]):
    with st.container(border=True):
        st.markdown(f'<span style="color:{HB.BLUE};font-weight:800;font-size:12px;letter-spacing:.06em;">SOFT · '
                    f'{SS.SLOT_NAME[s["slot"]].upper()} · {SS.STATS[s["stat"]].upper()}</span>'
                    f'<div style="color:{HB.INK};font-weight:700;margin-top:2px;">{SS.headline(s)}</div>'
                    f'<div style="color:{HB.INK_SOFT};font-size:12px;">{s["offense"]} tonight · {s["game"]}</div>',
                    unsafe_allow_html=True)
        cols = st.columns(max(1, len(s["players"])) if s["players"] else 1)
        if not s["players"]:
            st.caption("No regular rotation player at this position for them lately.")
        for j, p in enumerate(s["players"]):
            pk = SS.pick_for(p.get("name"), picks, s["stat"])
            inj = _inj(p.get("name"))
            with cols[j]:
                st.markdown(f"**{p.get('name')}** · {p.get('avg_min', 0):.0f} min")
                if inj == "out":
                    st.caption(IC.chip(inj) + " — not playing")
                    continue
                if inj:
                    st.caption(IC.chip(inj))
                    pk = dict(pk, _inj=inj) if pk else pk
                if pk:
                    use = ("💰 " if pk.get("money") else "") + ("🔒 " if pk.get("lock") else "") + str(pk.get("use") or "")
                    bet = GP.prop_bet("NBA", use, pk)
                    st.markdown(HB.bet_chip(bet), unsafe_allow_html=True)
                    ch = pk.get("chance")
                    st.caption(f"{pk.get('pick')}" + ("" if ch is None else f" · earned {float(ch):.0%}"))
                    if player_dlg and st.button("Open →", key=f"ss_open_{i}_{j}"):
                        player_dlg(pk, "NBA")
                else:
                    st.caption("No H2 pick on him tonight")
st.caption("A soft spot is a tendency, not a pick: the model already prices each defense into its projections. "
           "🃏 Bet / 🧪 Tracking / Info only is the model's verdict on the player's own line.")
