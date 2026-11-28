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
import sport_scope as SC

# Nov 27 (owner: a PrizePicks entry mixes sports, and the 4 PM slate meant switching sport three times): every sport
# the props model reads, in one board -- or one sport, from this bar or the sidebar (one choice, sport_scope).
_SPORTS = [k for k in BBD.PROPS_MODEL_SPORTS if sports.get(k) and sports.in_season(k)] or list(BBD.PROPS_MODEL_SPORTS)
C.page_header("🎲", "Pick'em Board",
              "PrizePicks, Underdog, DK Pick6, Dabble and ParlayPlay lines — More or Less, checked against the "
              "sportsbooks — every sport in one board")
SC.seed_single("pk_sport", [SC.ALL] + _SPORTS, SC.ALL)
_pick_sport = st.pills("Sports", [SC.ALL] + _SPORTS, key="pk_sport", on_change=SC.from_single, args=("pk_sport",),
                       format_func=lambda k: "🌐 All sports" if k == SC.ALL else f"{sports.get(k).icon} {k}")
CHOSEN = _SPORTS if _pick_sport in (None, SC.ALL) else [_pick_sport]
SPORT_KEY = CHOSEN[0]
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
               on_change=_pk_changed,
               help="This is your saved pick'em app: changing it here changes it in the sidebar and on every page.")
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

def _load(sk):
    """This sport's app lines the model has read, as legs (pickem.legs), or (None, why) when there are none."""
    main = BBD.fetch_generic_offers(sk, date_str, api)
    # Nov 18: only the games the books already posted props for (college basketball lists 70+ games a night)
    _ids = tuple(sorted({o["event_id"] for o in main if o.get("event_id")}))
    offers = BBD.merge_offers(main, BBD.fetch_pickem_extra_offers(sk, date_str, api, _ids))
    reads = BBD.load_slate_reads(sk, date_str, BBD.O.DEFAULT_BOOK)
    got = PK.legs(reads or {}, offers or [], app, sk)
    if got:
        return got, None, {}
    _in_feed = sum(1 for o in offers or [] if app in (o.get("pickem") or {}))
    feed = {a: sum(1 for o in offers or [] if a in (o.get("pickem") or {})) for a in PK.APPS}
    return [], ("not in our odds feed yet" if not _in_feed else
                f"{_in_feed} lines in the feed, none for players the model has read yet"), feed


def _load_safe(sk):
    try:
        return _load(sk)
    except Exception as e:                                      # noqa: BLE001 -- one sport's feed never blanks the rest
        return [], f"couldn't load ({type(e).__name__})", {}


legs, _why, _feed_apps = [], {}, {}
with st.spinner("Reading the apps' lines…"):
    # Nov 28: the sports load side by side -- each is mostly waiting on the odds feed, and one after another the
    # first visit after a restart took 106 s. Results are gathered in the same order as before.
    _results = {}
    try:
        from concurrent.futures import ThreadPoolExecutor
        from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
        _ctx = get_script_run_ctx()

        def _run(sk):
            if _ctx is not None:
                add_script_run_ctx(ctx=_ctx)
            return _load_safe(sk)
        with ThreadPoolExecutor(max_workers=max(1, min(6, len(CHOSEN)))) as _ex:
            _results = dict(zip(CHOSEN, _ex.map(_run, CHOSEN)))
    except Exception:                                           # noqa: BLE001 -- fall back to one at a time
        _results = {}
    for _sk in CHOSEN:
        _got, _w, _feed = _results.get(_sk) or _load_safe(_sk)
        legs += _got
        if _w:
            _why[_sk] = _w
        for a, k in (_feed or {}).items():
            _feed_apps[a] = _feed_apps.get(a, 0) + k
if not legs:
    # Nov 18 (owner: "not sure why this says DK hasn't posted when I see values on their site"): say which it is --
    # the odds feed isn't carrying this app's lines, or it is but none match a player the model read
    if not _feed_apps.get(app):
        _others = ", ".join(f"{PK.APPS[a]['name']} ({k})" for a, k in _feed_apps.items() if k and a != app)
        st.info(f"Our odds feed isn't carrying any {cfg['name']} lines for these sports right now — that's the feed, "
                "not the app (the app may well have them up). "
                + (f"The feed does have: {_others} — pick one of those above." if _others else
                   "No pick'em app lines are in the feed yet; they usually arrive the morning of the games."))
    else:
        st.info(f"No {cfg['name']} lines to read right now — " + "; ".join(f"{k}: {w}" for k, w in _why.items())
                + ". The model reads the games the sportsbooks post props for; try again closer to the start.")
    st.stop()

# Nov 27 (owner): what makes a pick unplayable or untrustworthy, on every row -- a game that has started (the apps
# lock it), a player listed out or questionable, or a prop your sportsbook has pulled while others still post it
try:
    import injury_check as _IC
    import my_books as _MBK
    _mine = _MBK.book()
except Exception:                                               # noqa: BLE001
    _IC, _mine = None, None
_inj = {}
for _sk in {x["sport"] for x in legs}:
    try:
        _inj[_sk] = _IC.report(_sk) if _IC else {}
    except Exception:                                           # noqa: BLE001
        _inj[_sk] = {}


@st.cache_data(ttl=600, show_spinner=False, max_entries=8)
def _snapshots(sk, d):
    """Today's hourly line snapshots for the sport (line_history): a book that posted a prop earlier and not in the
    latest capture has pulled it (Nov 27)."""
    import line_history as LH
    return LH.sport_index(sk, since=d)


_snaps = {}
for _sk in {x["sport"] for x in legs}:
    try:
        _snaps[_sk] = _snapshots(_sk, date_str)
    except Exception:                                           # noqa: BLE001
        _snaps[_sk] = {}
for x in legs:
    PK.flag(x, _mine, (_inj.get(x["sport"]) or {}).get(_IC._norm(x["player"])) if _IC else None,
            pulled=bool(_mine) and PK.pulled_by(_snaps.get(x["sport"]) or {}, x["player"], x.get("market_key"),
                                               _mine))

f1, f2 = st.columns([1, 1])
hide_started = f2.toggle("Hide games that have started", value=True, key="pk_hide_started",
                         help="The apps lock a pick when its game starts. Off shows them, marked 🔒.")
if hide_started:
    legs = [x for x in legs if not PK.started(x)]
# the slate by its real start times, like the apps group it
_today = datetime.now(ET).date()
_starts = {}
for x in legs:
    _d = C._kick_dt(x.get("kickoff"))
    _starts.setdefault(PK.start_label(x.get("kickoff"), _today), (_d, set()))[1].add(x.get("game"))
_order = sorted(_starts, key=lambda k: (_starts[k][0] is None, str(_starts[k][0] or "")))
_slate = f1.selectbox("Starts", ["All upcoming"] + _order, key="pk_starts",
                      format_func=lambda k: k if k == "All upcoming" else
                      f"{k} · {len(_starts[k][1])} game{'s' if len(_starts[k][1]) != 1 else ''}",
                      help="Pick a start time to build an entry from that slate only.")
if not legs:
    st.info("Every game with app lines has started. Turn off “Hide games that have started” to see them.")
    st.stop()
if _slate != "All upcoming":
    legs = [x for x in legs if PK.start_label(x.get("kickoff"), _today) == _slate]


checked = [x for x in legs if x["basis"] == "books"]
def _bar(x):
    return max(floor, x["needed"]) if x.get("needed") is not None else floor


_clear = sum(1 for x in checked if x["chance"] >= _bar(x) and not x.get("far") and not x.get("blocked"))
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
                        f"**{x['chance']:.0%}** (books at {x['book_line']:g}) · {x['sport']} · {x.get('game') or ''} · "
                        f"{PK.start_label(x.get('kickoff'), _today)}")
        if res:
            if flex and res.get("table"):
                _paid = sum(v for k, v in res["dist"].items() if res["table"].get(k))
                st.markdown(f"Pays something **{_paid:.0%}** of the time ("
                            + ", ".join(f"{k} of {n}: {res['dist'].get(k, 0):.1%} × {m:g}x"
                                        for k, m in sorted(res["table"].items(), reverse=True))
                            + f") · expected return **{res['ev']:+.0%}** per entry "
                              f"({'+' if res['ev'] > 0 else ''}{res['ev'] * 10:.2f} on a $10 entry)")
                st.caption("Priced at PrizePicks' standard Flex payouts — the app sometimes pays less on a given "
                           "entry, so check the Flex payouts on your entry screen before you submit.")
            else:
                st.markdown(f"All {n} hit: **{res['all']:.1%}** · expected return **{res['ev']:+.0%}** per entry "
                            f"({'+' if res['ev'] > 0 else ''}{res['ev'] * 10:.2f} on a $10 entry)")
    st.caption("Built only from lines the sportsbooks or exchanges also price, each from a different game, and never "
               "from a started game or a player listed out or questionable (ℹ️ notes about your sportsbook are hints, not "
               "blocks). A "
               "pick's chance is the books' no-vig chance moved to the app's line, with the model's measured say on "
               "top.")


with st.container(border=True):
    _entry_box()

# ---- every line
def _fmt(x):
    return {"Time": PK.start_label(x.get("kickoff"), _today), "Sport": x.get("sport") or "",
            "Player": x["player"], "Pick": f"{x['side']} {x['app_line']:g} {x['market']}",
            "Chance": round(x["chance"] * 100), "vs break-even": round((x["chance"] - _bar(x)) * 100, 1),
            "Check": x.get("flag") or (("⚠️ far from books" if x.get("far") else "📚 books")
                                       if x["basis"] == "books" else "model only"),
            "Team": x.get("team") or "", "Game": x.get("game") or "",
            **({"Price": f"{int(float(x['price'])):+d}" if x.get("price") is not None else ""} if priced else {}),
            **({"Needs": _bar(x)} if priced else {}),
            "Books' line": x.get("book_line"), "Model proj": round(x["projection"], 1)}


_t1, _t2 = st.columns(2)
only_checked = _t1.toggle("Only lines the sportsbooks also price", value=True, key="pk_only_books")
# Nov 27 (owner: tables that need sideways scrolling): the columns a pick needs; the rest one switch away
_all_cols = _t2.toggle("Show all columns", value=False, key="pk_all_cols")
_shown = sorted(checked if only_checked else legs,
                key=lambda x: (C._kick_dt(x.get("kickoff")) is None, str(C._kick_dt(x.get("kickoff")) or ""), -x["chance"]))
rows = [_fmt(x) for x in _shown]                                # earliest game first, then the strongest pick
if rows:
    df = pd.DataFrame(rows)
    if not _all_cols:
        df = df[[c for c in ("Time", "Sport", "Player", "Pick", "Chance", "vs break-even", "Check") if c in df.columns]]
    if len(CHOSEN) == 1 and "Sport" in df.columns:
        df = df.drop(columns=["Sport"])
    import card_links as _CL                                    # Nov 25 (owner): a row opens the player card

    def _open(row):
        return _CL.open_player_named(row.get("sport") or SPORT_KEY)(row)
    _CL.table(df, key="pk_table", items=_shown, open_fn=_open,
              hide_index=True, width="stretch",
              caption="Tap a row to open the player's card — the sportsbooks' line and the model's read are on it.",
              column_config={
        # Nov 27 (owner: 59.35% here, 61% in the entry box): whole percents for chances, points for the edge
        "Chance": st.column_config.NumberColumn(format="%d%%"),
        "vs break-even": st.column_config.NumberColumn(format="%+.1f pts"),
        "Needs": st.column_config.NumberColumn(format="percent"),
        "Books' line": st.column_config.NumberColumn(format="%.1f")})
else:
    st.caption("No books-checked lines in this slate.")

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
        "- **One player per game** in every entry; the apps also pay less for same-game lineups.\n"
        "- **Check** column: 🔒 his game has started (the apps lock it) · ⛔ listed out · ⚠️ questionable — none of "
        "these goes in an entry. Books dropped: from today's hourly line snapshots, how many of the sportsbooks that "
        "posted him earlier have taken this prop down — the market's own status alarm, whatever app you're on. "
        "Three in four or more (of 3+ books) is ⚠️ and kept out of the entry; half is an ℹ️ hint to check.")
