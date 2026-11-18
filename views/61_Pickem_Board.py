"""
61_Pickem_Board.py -- PrizePicks / Underdog / DK Pick6 / Dabble / ParlayPlay: every app line the model has read, its chance at the app's
line, and the strongest entries (pickem.py). Nov 18, owner: "a section specific to those [pick'em apps] for the sports".
"""
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

import best_bets_data as BBD
import components as C
import pickem as PK
import sports

ET = pytz.timezone("US/Eastern")
C.base_css()
_active = sports.active()
SPORT_KEY = _active.key
C.page_header("🎲", "Pick'em Board",
              f"PrizePicks, Underdog, DK Pick6, Dabble and ParlayPlay lines — More or Less, checked against the sportsbooks — "
              f"{_active.icon} {_active.label}")
# Nov 18 (owner): follows the sport picked on the Sport desk, and can switch right here -- the choice is the same
# shared one (session "sport"), so the desk and the sidebar follow it too.
try:
    _owner = st.secrets.get("AUDIENCE", "owner") == "owner"
except Exception:                                               # noqa: BLE001
    _owner = True
_choices = [s for s in sports.selectable_sports(_owner) if s.key in BBD.PROPS_MODEL_SPORTS]
if _choices:
    _keys = [s.key for s in _choices]

    def _switch():
        k = st.session_state.get("pk_sport_pick")
        if k:
            st.session_state["sport"] = k

    _cur = st.session_state.get("sport")
    st.session_state["pk_sport_pick"] = _cur if _cur in _keys else None    # mirror the shared pick (desk, sidebar)
    st.pills("Sport", _keys, key="pk_sport_pick", on_change=_switch,
             format_func=lambda k: f"{sports.get(k).icon} {sports.get(k).label}")

if SPORT_KEY not in BBD.PROPS_MODEL_SPORTS:
    st.info(f"The Pick'em Board reads player props from the props model, which covers "
            f"{', '.join(BBD.PROPS_MODEL_SPORTS)}. Pick one of those in the sport picker.")
    st.stop()
api = BBD.get_odds_api_key()
if not api:
    st.info("No odds key on this build, so there are no app lines to read.")
    st.stop()

date_str = datetime.now(ET).strftime("%Y-%m-%d")
c1, c2, c3 = st.columns([1.2, 1, 1])
app = c1.radio("App", list(PK.APPS), format_func=lambda k: PK.APPS[k]["name"], horizontal=True, key="pk_app")
cfg = PK.APPS[app]
priced = PK.is_priced(app)
n = c2.select_slider("Picks in the entry", options=sorted(cfg["power"]), value=min(3, max(cfg["power"])), key="pk_n")
flex = c3.toggle("Flex play", value=False, key="pk_flex", disabled=not (cfg.get("flex") or {}).get(n),
                 help="PrizePicks only: pays for most picks hitting, at lower multipliers.") \
    if cfg.get("flex") else False
mult = cfg["power"][n]
floor = PK.breakeven(mult, n)
st.caption(f"**{cfg['name']} {n}-pick {'Flex' if flex else 'Power'}**: "
           + (f"pays {mult:g}x if every pick hits — each pick needs **{floor:.1%}** to break even"
              + (", and more if the app prices it heavy (the **Needs** column). " if priced else ". ") if not flex else
              "pays " + ", ".join(f"{k} of {n}: {v:g}x" for k, v in sorted(cfg['flex'][n].items(), reverse=True)) + ". ")
           + cfg["note"] + f" [source]({cfg['source']})")

with st.spinner("Reading the apps' lines…"):
    try:
        # the boards' fetch (PrizePicks, Pick6, the sportsbooks) + the Pick'em Board's own (Underdog, Dabble,
        # ParlayPlay, and the Novig / ProphetX exchanges, whose prices sharpen the books-checked chance)
        offers = BBD.merge_offers(BBD.fetch_generic_offers(SPORT_KEY, date_str, api),
                                  BBD.fetch_pickem_extra_offers(SPORT_KEY, date_str, api))
        reads = BBD.load_slate_reads(SPORT_KEY, date_str, BBD.O.DEFAULT_BOOK)
    except Exception as e:                                      # noqa: BLE001
        st.error(f"Couldn't load today's lines ({type(e).__name__}).")
        st.stop()
legs = PK.legs(reads or {}, offers or [], app, SPORT_KEY)
if not legs:
    st.info(f"{cfg['name']} hasn't posted {_active.label} lines the model has read yet today. App lines usually go "
            "up the morning of the games — or pick another sport above.")
    st.stop()
legs = C.date_slot_select(legs, key=f"pk_slot_{SPORT_KEY}", when=lambda x: x.get("kickoff"))

checked = [x for x in legs if x["basis"] == "books"]
def _bar(x):
    return max(floor, x["needed"]) if x.get("needed") is not None else floor


_clear = sum(1 for x in checked if x["chance"] >= _bar(x) and not x.get("far"))
st.markdown(f"**{len(legs)} {cfg['name']} lines read** · {len(checked)} also priced at a sportsbook or exchange · "
            f"{_clear} clear the {floor:.1%} break-even" + (" and their own price" if priced else ""))

# ---- the strongest entry
entry = PK.best_entry(legs, n, floor if not flex else 0.5)
with st.container(border=True):
    st.markdown(f"#### 🎟️ Strongest {n}-pick entry")
    if len(entry) < n:
        st.write(f"Only {len(entry)} books-checked line{'s' if len(entry) != 1 else ''} clear the break-even today "
                 f"(one player per game). No entry worth making on {cfg['name']} right now — that's an answer too.")
    else:
        res = PK.entry_odds(entry, app, flex=flex, sport=SPORT_KEY)
        for x in entry:
            _px = f" at {int(float(x['price'])):+d}" if x.get("price") is not None else ""
            st.markdown(f"- **{x['player']}** {x['side']} {x['app_line']:g} {x['market']}{_px} — "
                        f"**{x['chance']:.0%}** (books at {x['book_line']:g}) · {x.get('game') or ''}")
        if res:
            st.markdown(f"All {n} hit: **{res['all']:.1%}** · expected return **{res['ev']:+.0%}** per entry "
                        f"({'+' if res['ev'] > 0 else ''}{res['ev'] * 10:.2f} on a $10 entry)")
    st.caption("Built only from lines the sportsbooks also price, each from a different game. A pick's chance is the "
               "books' no-vig chance moved to the app's line, with the model's measured say on top.")

# ---- every line
def _fmt(x):
    return {"Player": x["player"], "Team": x.get("team") or "", "Game": x.get("game") or "",
            "Time": (C._kick_dt(x.get("kickoff")).strftime("%a %-I:%M %p") if C._kick_dt(x.get("kickoff")) else ""),
            "Market": x["market"], "App line": x["app_line"], "Pick": x["side"],
            **({"Price": f"{int(float(x['price'])):+d}" if x.get("price") is not None else ""} if priced else {}),
            "Chance": x["chance"],
            **({"Needs": _bar(x)} if priced else {}),
            "vs break-even": x["chance"] - _bar(x),
            "Books' line": x.get("book_line"),
            "Model proj": round(x["projection"], 1),
            "Checked by": ("⚠️ far from books" if x.get("far") else "📚 books") if x["basis"] == "books" else "model only"}


only_checked = st.toggle("Only lines the sportsbooks also price", value=True, key="pk_only_books")
_shown = sorted(checked if only_checked else legs,
                key=lambda x: (C._kick_dt(x.get("kickoff")) is None, str(C._kick_dt(x.get("kickoff")) or ""), -x["chance"]))
rows = [_fmt(x) for x in _shown]                                # earliest game first, then the strongest pick
if rows:
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, width="stretch", column_config={
        "Chance": st.column_config.NumberColumn(format="percent"),
        "vs break-even": st.column_config.NumberColumn(format="percent"),
        "Needs": st.column_config.NumberColumn(format="percent"),
        "App line": st.column_config.NumberColumn(format="%.1f"),
        "Books' line": st.column_config.NumberColumn(format="%.1f")})
else:
    st.caption("No books-checked lines in this slot.")

with st.expander("How these chances are made, and how far to trust a 'model only' line"):
    st.markdown(
        f"- **📚 books**: the player is also priced at a sportsbook. His chance is the books' no-vig chance, moved "
        f"from their line to {cfg['name']}'s line along the model's curve for him, plus the model's measured say "
        "(about a fifth). When the app hangs a stale number — books at 21.5, app at 19.5 — this is where the edge is.\n"
        "- **model only**: no sportsbook posts him (most college props). On graded lines like these the model's side "
        "hit 44–51% in the NBA and NFL (Nov 18 study), so its lean is cut to a tenth here and these lines almost never "
        "clear a break-even. They're shown for reference, never put in an entry.\n"
        "- **Sportsbooks and exchanges**: the books-checked chance uses every sportsbook plus Novig and ProphetX, "
        "prediction exchanges whose two-sided prices carry almost no house margin (ProphetX also prices some "
        "college players the sportsbooks skip).\n"
        "- **ParlayPlay and Dabble** also price each pick; a pick the app prices heavy pays less, so there a pick must "
        "clear the larger of the break-even and its own price's chance, shown in **Needs**.\n"
        "- **⚠️ far from books**: the app's line sits well off the books' (more than a point, or 12% of the line). "
        "That's usually a discounted line that pays less (PrizePicks goblins), a stale number, or a different setup "
        "— check it on the app. These never go in an entry, however good the chance looks.\n"
        "- **One player per game** in every entry; the apps also pay less for same-game lineups.")
