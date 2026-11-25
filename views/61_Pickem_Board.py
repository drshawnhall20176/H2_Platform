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
# Nov 18 / 19 (owner): follows the shared sport -- switch it with the sport bar at the top of the page.
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
# Nov 25 (owner): site-wide "My pick'em app" (my_books.py) -- this board opens on it, and a change here changes it
try:
    import my_books as _MB
    _last = st.session_state.get("_pk_app_synced")
    if _last is None and st.session_state.get("pk_app") in PK.APPS:
        st.session_state["_pk_app_synced"] = _MB.app()           # a choice already made on this page stands
    elif _last != _MB.app():                                    # first visit, or changed in the sidebar
        st.session_state["pk_app"] = _MB.app()
        st.session_state["_pk_app_synced"] = _MB.app()
except Exception:                                               # noqa: BLE001
    _MB = None


def _pk_changed():
    if _MB is not None:
        _MB.set_app(st.session_state["pk_app"])
        st.session_state["_pk_app_synced"] = st.session_state["pk_app"]


app = c1.radio("App", list(PK.APPS), format_func=lambda k: PK.APPS[k]["name"], horizontal=True, key="pk_app",
               on_change=_pk_changed)
cfg = PK.APPS[app]
priced = PK.is_priced(app)
if cfg.get("power"):
    n = c2.select_slider("Picks in the entry", options=sorted(cfg["power"]), value=min(3, max(cfg["power"])),
                         key="pk_n")
    flex = c3.toggle("Flex play", value=False, key="pk_flex", disabled=not (cfg.get("flex") or {}).get(n),
                     help="PrizePicks only: pays for most picks hitting, at lower multipliers.") \
        if cfg.get("flex") else False
    mult = cfg["power"][n]
    floor = PK.breakeven(mult, n)
    st.caption(f"**{cfg['name']} {n}-pick {'Flex' if flex else 'Power'}**: "
               + (f"pays {mult:g}x if every pick hits — each pick needs **{floor:.1%}** to break even"
                  + (", and more if the app prices it heavy (the **Needs** column). " if priced else ". ")
                  if not flex else
                  "pays " + ", ".join(f"{k} of {n}: {v:g}x" for k, v in sorted(cfg['flex'][n].items(), reverse=True))
                  + ". ")
               + cfg["note"] + f" [source]({cfg['source']})")
else:
    n, flex, floor = None, False, 0.5          # no payout table: each pick only against its own price
    st.caption(f"**{cfg['name']}**: " + cfg["note"] + f" [source]({cfg['source']})")

with st.spinner("Reading the apps' lines…"):
    try:
        # the boards' fetch (PrizePicks, Pick6, the sportsbooks) + the Pick'em Board's own (Underdog, Dabble,
        # ParlayPlay, and the Novig / ProphetX exchanges, whose prices sharpen the books-checked chance)
        main = BBD.fetch_generic_offers(SPORT_KEY, date_str, api)
        # Nov 18: only the games the books already posted props for (college basketball lists 70+ games a night;
        # asking for every one kept the spinner going and spent credits on games with no lines)
        _ids = tuple(sorted({o["event_id"] for o in main if o.get("event_id")}))
        offers = BBD.merge_offers(main, BBD.fetch_pickem_extra_offers(SPORT_KEY, date_str, api, _ids))
        reads = BBD.load_slate_reads(SPORT_KEY, date_str, BBD.O.DEFAULT_BOOK)
    except Exception as e:                                      # noqa: BLE001
        st.error(f"Couldn't load today's lines ({type(e).__name__}).")
        st.stop()
legs = PK.legs(reads or {}, offers or [], app, SPORT_KEY)
if not legs:
    # Nov 18 (owner: "not sure why this says DK hasn't posted when I see values on their site"): say which it is --
    # the odds feed isn't carrying this app's lines for this sport, or it is but none match a player the model read.
    _in_feed = {a: sum(1 for o in offers or [] if a in (o.get("pickem") or {})) for a in PK.APPS}
    if not _in_feed.get(app):
        _others = ", ".join(f"{PK.APPS[a]['name']} ({k})" for a, k in _in_feed.items() if k and a != app)
        st.info(f"Our odds feed isn't carrying any {cfg['name']} {_active.label} lines right now — that's the feed, not "
                f"the app (the app may well have them up). "
                + (f"The feed does have: {_others} — pick one of those above." if _others else
                   "No pick'em app lines for this sport are in the feed yet; they usually arrive the morning of the games."))
    else:
        st.info(f"The feed has {_in_feed[app]} {cfg['name']} {_active.label} lines, but none for players the model has "
                "read yet (it reads the games the sportsbooks post props for). Try again closer to tip-off.")
    st.stop()
legs = C.date_slot_select(legs, key=f"pk_slot_{SPORT_KEY}", when=lambda x: x.get("kickoff"))

checked = [x for x in legs if x["basis"] == "books"]
def _bar(x):
    return max(floor, x["needed"]) if x.get("needed") is not None else floor


_clear = sum(1 for x in checked if x["chance"] >= _bar(x) and not x.get("far"))
st.markdown(f"**{len(legs)} {cfg['name']} lines read** · {len(checked)} also priced at a sportsbook or exchange · "
            + (f"{_clear} clear the {floor:.1%} break-even" + (" and their own price" if priced else "") if n else
             f"{_clear} beat their own price"))

# ---- the strongest entry
def _entry_box():
    if not n:
        st.markdown("#### 🎟️ No entry built")
        st.write(f"{cfg['name']} doesn't publish what an entry pays, so there's no break-even to build one against. "
                 "Use the lines below: **vs break-even** is each pick's chance against its own posted price. Its "
                 "lines ran softer than the sportsbooks' when it was added (Nov 18), which usually means it pays less.")
        return
    entry = PK.best_entry(legs, n, floor if not flex else 0.5)
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
    st.caption("Built only from lines the sportsbooks or exchanges also price, each from a different game. A pick's "
               "chance is their no-vig chance moved to the app's line, with the model's measured say on top.")


with st.container(border=True):
    _entry_box()

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
