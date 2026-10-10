"""
Analyst Desk — the day's action, read like a commentator, a handicapper and a data analyst, with a
public scoreboard that keeps it honest.

What it does: scans the day's board for ANGLES (model vs market, a soft book, a form run, a role
surge, team momentum, regression due, line movement), calls out where several independent angles
agree on a play the headline ranking doesn't surface (a "hidden gem"), and writes the day up in
words. Every call is LOCKED the first time it is published and graded afterwards, so the Proof tab
shows which angles actually hold up — the claim is predictability and repeatability, not a promise
of profit. See analyst.py / analyst_ledger.py for the rules.
"""

import os
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

import analyst as A
import analyst_ledger as AL
import best_bets_data as BBD
import components as C
import line_history
import sports
from streamlit_page_cache import compute_once

_active = sports.active()
E = _active.engine

C.base_css()
C.page_header("🎙️", "Analyst Desk",
              f"The day's action read like a commentator, a handicapper and a data analyst — and a "
              f"scoreboard that keeps it honest — {_active.icon} {_active.label}")

if not sports.require_live_engine("Analyst Desk"):
    st.stop()
if not _active.has_projections:
    st.info("🥊 The Analyst Desk reads counting-stat boards, so it doesn't apply to UFC — head to "
            "**UFC Fight Card** in the sidebar.")
    st.stop()

eastern = pytz.timezone("US/Eastern")
today_str = datetime.now(eastern).strftime("%Y-%m-%d")


def _secret(name: str):
    try:
        v = st.secrets.get(name)
    except Exception:                                  # noqa: BLE001
        v = None
    return (str(v).strip() if v else None) or os.environ.get(name)


# --- controls ----------------------------------------------------------------
target = st.date_input("Slate date", datetime.now(eastern))
date_str = target.strftime("%Y-%m-%d")
C.season_notice(_active.key, date_str)
preferred_book = st.session_state.get(f"_preferred_book_{_active.key.lower()}", BBD.O.DEFAULT_BOOK)


# --- the board ---------------------------------------------------------------
def _load_board(sport_key: str, d: str, book: str):
    if sport_key == "MLB":
        plays, meta, _books = BBD.load_mlb_best_bets_board(d, E.FIP_CONSTANT_DEFAULT, book, None, None)
    else:
        plays, meta, _books = BBD.load_generic_best_bets_board(sport_key, d, book)
    return plays, meta


with st.spinner("Reading the slate..."):
    try:
        plays, meta = compute_once(f"analyst_{_active.key}", _load_board, _active.key, date_str, preferred_book)
    except Exception:                                  # noqa: BLE001
        st.warning(f"No slate data available for {_active.label} on {date_str}. "
                   "Normal during the off-season — try a date when games are scheduled.")
        st.stop()

if not plays:
    st.info(f"No {_active.label} plays found for {date_str}. Try a different date or switch sports.", icon="📅")
    st.stop()

plays, meta = C.scope_plays(_active.key, _active.label, plays, meta, date_str, key="analyst_scope")

# --- Time slot + Game filters (same shape as the other pages), and the order the lists use ---
_with_day = C.scope_is_week(_active.key)
times = A.game_times(meta, with_day=_with_day)
for _p in plays:                                       # a game missing from meta still gets a time from its plays
    times.setdefault(_p.get("Game"), A.time_info(_p.get("GameDate"), _with_day))
_chrono = lambda g: A.chrono_key(times[g]["slot"], times[g]["start"])
slots_present = sorted({t["slot"] for t in times.values()}, key=lambda s: sports.SLOT_ORDER.get(s, 9))
f1, f2, f3 = st.columns([1, 2, 1])
with f1:
    slot_pick = st.selectbox("Time slot", ["All slate"] + slots_present)
games_in_slot = sorted((g for g, t in times.items() if slot_pick == "All slate" or t["slot"] == slot_pick), key=_chrono)
ALL_GAMES = "All games in this slot"
with f2:
    game_pick = st.selectbox("Game", [ALL_GAMES] + games_in_slot,
                             format_func=lambda g: g if g == ALL_GAMES else f"{times[g]['kickoff']} — {g}")
with f3:
    order = st.radio("Order by", ["Start time", "Strongest first"], horizontal=True)
view_games = games_in_slot if game_pick == ALL_GAMES else [game_pick]
view_set = set(view_games)

# Odds (soft-price angle). Fail-soft: no key or a failed fetch just means that angle stays quiet.
offers, offers_note = None, None
api_key = BBD.get_odds_api_key()
if not api_key:
    offers_note = "no Odds API key is configured, so the soft-price angle is off"
else:
    try:
        offers = (BBD.fetch_mlb_offers(date_str, api_key) if _active.key == "MLB"
                  else BBD.fetch_generic_offers(_active.key, date_str, api_key))
    except Exception as exc:                           # noqa: BLE001
        offers_note = f"the odds fetch failed ({str(exc)[:90]}), so the soft-price angle is off"
        offers = None
    else:
        if not offers:
            offers_note = "no player props are posted yet, so the soft-price angle is quiet"

# --- learn from the record, scan, lock ---------------------------------------
history = AL.fetch_calls(sport=_active.key, settled_only=True)
weights = A.learned_weights(history)


def _line_rows(sport_key, player, market, side):
    return line_history.line_series(sport_key, player, market, side)


calls = A.scan(plays, _active.key, date_str, offers=offers, odds_map=_active.market_map,
               history_fn=_line_rows, weights=weights, expect_book_lines=bool(offers),
               times=times, with_day=_with_day)

locked_note = ""
if calls:
    sig = (_active.key, date_str, len(calls), hash(tuple(c["key"] for c in calls)))
    if st.session_state.get("_analyst_logged") != sig:
        try:
            new = AL.record_calls(calls, today_str)
            st.session_state["_analyst_logged"] = sig
            if new:
                locked_note = f"{new} new call(s) locked to the record."
        except Exception as exc:                       # noqa: BLE001
            locked_note = f"⚠️ Couldn't write to the record ({str(exc)[:90]}) — calls below are not being tracked."

# Grade earlier days that are still open (a few per visit, so a cold page stays quick).
settle_note = ""
try:
    for d in AL.unsettled_dates(_active.key, today_str)[:3]:
        res = AL.settle_day(_active.key, d, E.get_player_results(d))
        if res["settled"]:
            voids = f" ({res['voids']} void — player didn't play)" if res["voids"] else ""
            settle_note = (settle_note + f" Graded {res['settled']} call(s) from {d}{voids}.").strip()
except Exception as exc:                               # noqa: BLE001
    settle_note = f"⚠️ Grading earlier calls hit a problem ({str(exc)[:90]})."

history = AL.fetch_calls(sport=_active.key, settled_only=True) if settle_note else history

captions = [t for t in (locked_note, settle_note) if t]
if offers_note:
    captions.append(f"Heads up: {offers_note}.")
if captions:
    st.caption(" · ".join(captions))

board = A.scoreboard(history)
# Everything below is the VIEW: the calls for the games picked above. (Logging and grading above always
# use the whole slate, so a filter never changes what is on the record.)
view_calls = [c for c in calls if c["game"] in view_set]
if order == "Start time":
    view_calls = sorted(view_calls, key=lambda c: A.chrono_key(c["slot"], c["start"], -c["score"]))
notes = {g: n for g, n in A.game_notes(meta).items() if g in view_set}
day = A.write_commentary(view_calls, sport_label=_active.label, date_str=date_str, n_games=len(view_games),
                         notes=notes, board=board, times={g: times[g] for g in view_games})

tab_desk, tab_gems, tab_all, tab_proof = st.tabs(
    ["🎙️ The Desk", "💎 Hidden gems", "🧭 Every angle", "🧾 Proof"])


def _call_rows(cs):
    out = []
    for c in cs:
        out.append({
            "Time": c["kickoff"], "Slot": c["slot"], "Game": c["game"], "Player": c["player"], "Play": f"{c['side']} {c['line']:g} {c['market']}"
            if c.get("line") is not None else f"{c['side']} {c['market']}",
            "Model": c["model_prob"], "Book price": c["price"], "Angles": ", ".join(a["label"] for a in c["angles"]),
            "Gem": "💎" if c["gem"] else "", "Cautions": "; ".join(c["cautions"]), "Score": c["score"],
        })
    return pd.DataFrame(out)


_COLS_CFG = {"Model": st.column_config.NumberColumn(format="percent"),
             "Book price": st.column_config.NumberColumn(format="%+d"),
             "Score": st.column_config.NumberColumn(format="%.2f")}

# --- The Desk ----------------------------------------------------------------
with tab_desk:
    ai_key = _secret("ANTHROPIC_API_KEY")
    use_ai = False
    if view_calls:
        if ai_key:
            use_ai = st.toggle("Write it up in the analyst's voice (AI)", value=False, key="analyst_ai",
                               help="Sends only the structured findings below to the model, which is told not to add facts.")
        else:
            st.caption("AI-written commentary is available once ANTHROPIC_API_KEY is added to the app secrets; "
                       "the commentary below is written directly from the findings.")
    if use_ai:
        fh = A.facts_hash(day["facts"])
        cache = st.session_state.setdefault("_analyst_ai_text", {})
        if fh not in cache:
            with st.spinner("The analyst is writing..."):
                try:
                    cache[fh] = A.llm_commentary(day["facts"], ai_key, _secret("ANALYST_MODEL"))
                except RuntimeError as exc:
                    cache[fh] = None
                    st.session_state["_analyst_ai_err"] = str(exc)
        if cache.get(fh):
            st.markdown(cache[fh])
            st.caption("Written by AI from the findings below; every number comes from them.")
        else:
            st.warning(f"The AI write-up isn't available — {st.session_state.get('_analyst_ai_err', 'unknown reason')}. "
                       "Showing the standard commentary instead.")
            use_ai = False
    if not use_ai:
        st.subheader(day["headline"])
        st.write(day["overview"])
        if day["focus"]:
            st.markdown("#### Where to focus")
            for f in day["focus"]:
                st.markdown(f"- {f['text']}")
        if day["games"]:
            st.markdown("#### Game by game")
            last_slot = None
            for g in day["games"]:
                if g["slot"] != last_slot:
                    st.markdown(f"##### {A.SLOT_TITLES.get(g['slot'], g['slot'])}")
                    last_slot = g["slot"]
                with st.expander(f"{g['kickoff']} — {g['game']}", expanded=False):
                    st.write(g["text"])
    st.caption("Commentary describes what the data shows; it is analysis, not a guarantee of any outcome.")

# --- Hidden gems ---------------------------------------------------------------
with tab_gems:
    gems = [c for c in view_calls if c["gem"]]
    st.caption("A hidden gem has two or more independent angles agreeing, isn't already at the top of the day's "
               "conviction list, carries a model chance of at least 55%, and has at most one caution.")
    if not gems:
        st.info("No play has cleared the hidden-gem bar for this slate. That is a real answer — it means the "
                "angles aren't lining up today, not that something is broken.")
    else:
        st.dataframe(_call_rows(gems), width="stretch", hide_index=True, column_config=_COLS_CFG)
        for c in gems[:10]:
            with st.expander(f"{c['kickoff']} · {c['player']} — {c['side']} {c['line']:g} {c['market']} ({c['game']})"):
                for a in c["angles"]:
                    st.markdown(f"- **{a['label']}** — {a['evidence']}")
                for w in c["cautions"]:
                    st.markdown(f"- ⚠️ {w}")
                if c.get("why"):
                    st.caption(f"Model note: {c['why']}")

# --- Every angle -----------------------------------------------------------------
with tab_all:
    if not view_calls:
        st.info("No play has an angle behind it in the games picked above.")
    else:
        pick = st.multiselect("Angles", [v[0] for v in A.ANGLES.values()], default=[], key="analyst_angle_pick",
                              help="Leave empty to show every angle.")
        show_chalk = st.checkbox("Include the day's chalk (top 10% of conviction)", value=True, key="analyst_chalk")
        rows = [c for c in view_calls if (show_chalk or not c["chalk"])
                and (not pick or any(a["label"] in pick for a in c["angles"]))]
        st.write(f"{len(rows)} of {len(view_calls)} plays")
        st.dataframe(_call_rows(rows), width="stretch", hide_index=True, column_config=_COLS_CFG)
        with st.expander("What each angle means"):
            for k, (label, desc) in A.ANGLES.items():
                st.markdown(f"- **{label}** — {desc}")

# --- Proof -------------------------------------------------------------------------
with tab_proof:
    st.markdown("Every call is **locked the first time it is published** (later line moves never rewrite it, and a "
                "game that has started can't be added) and graded afterwards against the real result. A call "
                "for a player who didn't play is a void, not a loss. Hit rate is compared with the chance the "
                "model itself stated — that gap is what 'predictable' means here.")
    rows_b = [r for r in board if r["n"]]
    if not rows_b:
        st.info("No calls have been graded yet — the record starts filling as soon as the first locked day's "
                "games are final. Nothing here is back-filled.")
    else:
        df = pd.DataFrame([{
            "Angle": r["label"], "Graded": r["n"], "Hit rate": r["hit_rate"], "Model said": r["mean_prob"],
            "Gap (pts)": None if r["gap"] is None else r["gap"] * 100,
            "95% range": "" if r["ci_low"] is None else f"{r['ci_low']:.0%}–{r['ci_high']:.0%}",
            "Brier": r["brier"], "Status": r["status"], "Rank weight": weights.get(r["angle"]),
        } for r in rows_b])
        st.dataframe(df, width="stretch", hide_index=True, column_config={
            "Hit rate": st.column_config.NumberColumn(format="percent"),
            "Model said": st.column_config.NumberColumn(format="percent"),
            "Gap (pts)": st.column_config.NumberColumn(format="%+.1f"),
            "Brier": st.column_config.NumberColumn(format="%.3f"),
            "Rank weight": st.column_config.NumberColumn(format="%.2f"),
        })
        st.caption(f"Status stays 'Collecting data' until an angle has {A.STATUS_MIN_N} graded calls. "
                   "Rank weight only changes the ORDER calls are shown in (1.00 = neutral); it never edits a probability.")
        rel = A.reliability(history)
        if rel:
            st.markdown("##### Stated chance vs what happened")
            st.dataframe(pd.DataFrame(rel).rename(columns={"bucket": "Model said", "n": "Calls", "stated": "Avg stated",
                                                            "actual": "Actual hit rate"}),
                         width="stretch", hide_index=True,
                         column_config={"Avg stated": st.column_config.NumberColumn(format="percent"),
                                        "Actual hit rate": st.column_config.NumberColumn(format="percent")})
    recent = AL.fetch_calls(sport=_active.key)[-15:][::-1]
    if recent:
        with st.expander("Most recent locked calls"):
            st.dataframe(pd.DataFrame([{
                "Date": r["date"], "Player": r["player"], "Play": f"{r['side']} {r['line']:g} {r['market']}"
                if r.get("line") is not None else r["side"], "Model": r["model_prob"],
                "Angles": ", ".join(r["angles"]), "Result": ("Hit" if r["hit"] == 1 else "Miss" if r["hit"] == 0
                                                             else "Void" if r.get("settled_at") else "Open"),
            } for r in recent]), width="stretch", hide_index=True,
                column_config={"Model": st.column_config.NumberColumn(format="percent")})
