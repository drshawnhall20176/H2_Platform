"""
Highlights — saved, named filter criteria that auto-flag matching plays on today's board.

Modeled on a real workflow the community already runs through a third-party tool (PropFinder):
build a NAMED profile once ("Due for a Homer"), and every day the platform tells you who on
tonight's board actually matches it, instead of re-scanning the whole slate by eye. See
highlights.py's own module docstring for the full design reasoning.
"""

import streamlit as st

import sports
import best_bets_data as BBD
import highlights as H

_active = sports.active()

st.title("⭐ Highlights")
st.caption("Save a named filter once, see who matches it every day — the same workflow as a "
          "PropFinder Highlight Profile, built on this platform's own real fields.")

if _active.key != "MLB":
    st.info("Highlights is MLB-only for now — the real fields these profiles filter on "
           "(Due, real captured prices, real market-based grading) aren't wired into other "
           "sports yet. Come back once you're on the MLB tab.")
    st.stop()

if not sports.require_live_engine("Highlights"):
    st.stop()

H.ensure_starter_profiles("MLB")

# Who's asking -- the same honest, no-real-login-yet convention betlog.py's own "trader" field
# already uses (see highlights.py's own docstring). A typed name, not an account.
with st.sidebar:
    st.subheader("Your name")
    my_name = st.text_input("For your personal profiles (optional)", value="",
                            help="Leave blank to only see shared house profiles. Type your "
                                "name to also see (and build) your own personal ones.")

import datetime as _dt
date_str = st.date_input("Slate date", _dt.datetime.now()).strftime("%Y-%m-%d")

with st.spinner("Loading tonight's board..."):
    try:
        plays, _meta, _books = BBD.load_mlb_best_bets_board(
            date_str, BBD.E.FIP_CONSTANT_DEFAULT)
    except Exception:
        plays = []
plays = [pl for pl in plays if sports.has_started(pl.get("GameDate")) is not True]

profiles = H.list_profiles("MLB", owner=my_name or None)

st.divider()
st.subheader("Today's Highlights")
if not plays:
    st.info("No games on the board right now, or every game has already started.")
elif not profiles:
    st.info("No profiles yet — build one below.")
else:
    result = H.highlights_by_profile(plays, profiles)
    for r in result:
        owner_tag = f" · personal to {r['owner']}" if r.get("owner") else " · shared"
        with st.expander(f"{r['emoji']} {r['name']}{owner_tag} — {len(r['matches'])} match(es)",
                         expanded=bool(r["matches"])):
            if not r["matches"]:
                st.caption("No plays on tonight's board match this profile.")
            else:
                for m in r["matches"]:
                    grade = H._play_value(m, "Grade")
                    grade_str = f" · {grade}" if grade else ""
                    price_marker = " 📊" if m.get("PriceSource") == "book" else ""
                    line_val = m.get("Line")
                    line_str = f"{line_val:g}" if isinstance(line_val, (int, float)) else "?"
                    st.markdown(f"**{m['Player']}** ({m.get('Team', '')}) — {m['Market']} "
                              f"{m['Side']} {line_str} · {m['ModelProb']:.0%}"
                              f"{grade_str}{price_marker} — {m.get('Game', '')}")
            cdel1, _ = st.columns([1, 5])
            with cdel1:
                if st.button("Delete", key=f"del_{r['id']}"):
                    H.delete_profile(r["id"])
                    st.rerun()

st.divider()
st.subheader("Build a new profile")
st.caption("Every condition below runs against real fields already on tonight's board — "
          "nothing here is a placeholder or a guess. A play must clear EVERY condition you add "
          "to match (AND logic).")

FIELD_HELP = {
    "Market": "e.g. Batter HR, Batter Total Bases, Pitcher Strikeouts",
    "Side": "Over or Under",
    "Grade": "This platform's own letter grade (A/B/C/D) — real, validated edge, computed live",
    "ModelProb": "The model's own real probability of hitting (0-1)",
    "Conviction": "Edge relative to what's typical for this market",
    "PriceSource": "\"book\" = a real captured sportsbook price exists; \"model_fair\" = theoretical only",
    "ConvictionSource": "\"book\" = graded against a real market rate; \"model_typical\" = a hand-typed guess",
    "LineSource": "\"book\" = a real captured line; \"default\" = placeholder",
    "OppERA": "The opposing starter's real season ERA",
    "Due": "Batter HR only — Statcast barrels running ahead of the real HR count (percentage points)",
    "AVG": "The batter's real season batting average",
    "SLG": "The batter's real season slugging percentage",
}

with st.form("new_profile_form", clear_on_submit=True):
    name = st.text_input("Profile name", placeholder="e.g. Due for a Homer")
    emoji = st.text_input("Emoji", value="⭐", max_chars=4)
    scope = st.radio("Visibility", ["Shared (everyone sees it)", "Personal (just me)"],
                     horizontal=True)
    st.markdown("**Conditions** (fill in the ones you want, leave the rest blank)")
    conditions = []
    for i in range(3):
        c1, c2, c3 = st.columns([2, 1, 2])
        with c1:
            field = st.selectbox(f"Field {i + 1}", [""] + H.CONDITION_FIELDS,
                                 key=f"field_{i}", help=None)
        with c2:
            op = st.selectbox("Op", H.SUPPORTED_OPS, key=f"op_{i}")
        with c3:
            raw_value = st.text_input("Value", key=f"value_{i}",
                                      help=FIELD_HELP.get(field, ""))
        if field and raw_value:
            if op == "in":
                value = [v.strip() for v in raw_value.split(",")]
            else:
                try:
                    value = float(raw_value)
                    if value == int(value):
                        value = int(value)
                except ValueError:
                    value = raw_value
            conditions.append({"field": field, "op": op, "value": value})

    submitted = st.form_submit_button("Save profile")
    if submitted:
        if not name:
            st.error("Give the profile a name first.")
        elif not conditions:
            st.error("Add at least one real condition — a profile with none would match "
                     "everything on the board, which isn't a real highlight.")
        elif scope.startswith("Personal") and not my_name:
            st.error("Type your name in the sidebar first to save a personal profile.")
        else:
            owner = my_name if scope.startswith("Personal") else None
            H.add_profile(name, "MLB", conditions, emoji=emoji, owner=owner)
            st.success(f"Saved {emoji} {name}.")
            st.rerun()
