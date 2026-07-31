"""
Highlights — saved, named filter criteria that auto-flag matching plays on today's board.

Modeled on a real workflow the community already runs through a third-party tool (PropFinder):
build a NAMED profile once ("Due for a Homer"), and every day the platform tells you who on
tonight's board actually matches it, instead of re-scanning the whole slate by eye. See
highlights.py's own module docstring for the full design reasoning.
"""

import datetime as _dt

import pandas as pd
import streamlit as st

import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import sports
import best_bets_data as BBD
import highlights as H

_active = sports.active()

# Same grade colors already used on Graded Picks/Suggested Parlays/Speculative Basket -- reused
# directly here rather than re-invented, so a grade means the same thing, visually, everywhere
# on the platform.
GRADE_COLOR = {"A": "#16783c", "B": "#2e7d32", "C": "#b8860b", "D": "#6b7280"}

st.title("✨ Highlights")
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

date_str = st.date_input("Slate date", _dt.datetime.now()).strftime("%Y-%m-%d")

with st.spinner("Loading tonight's board..."):
    try:
        plays, _meta, _books = BBD.load_mlb_best_bets_board(
            date_str, BBD.E.FIP_CONSTANT_DEFAULT)
    except Exception:
        plays = []
plays = [pl for pl in plays if sports.has_started(pl.get("GameDate")) is not True]

profiles = H.list_profiles("MLB", owner=my_name or None)
result = H.highlights_by_profile(plays, profiles) if (plays and profiles) else []

# --- quick stats row ----------------------------------------------------------
# Added directly on request: the page previously gave no sense of scale at a glance -- a real
# product tells you the headline numbers before you scroll. Real counts, not decoration: every
# number here is something already computed above, just surfaced.
n_shared = sum(1 for p in profiles if not p.get("owner"))
n_personal = sum(1 for p in profiles if p.get("owner"))
total_matches = sum(len(r["matches"]) for r in result)
top_profile = max(result, key=lambda r: len(r["matches"])) if result else None

s1, s2, s3, s4 = st.columns(4)
with s1: st.metric("Live plays tonight", len(plays))
with s2: st.metric("Profiles active", f"{n_shared} shared" + (f" + {n_personal} yours" if n_personal else ""))
with s3: st.metric("Total matches", total_matches)
with s4:
    st.metric("Top profile", f"{top_profile['emoji']} {top_profile['name']}" if top_profile else "—",
              f"{len(top_profile['matches'])} matches" if top_profile else None)

st.divider()
st.subheader("Today's Highlights")

MAX_ROWS_SHOWN = 15


def _matches_dataframe(matches: list) -> pd.DataFrame:
    """Real, sortable table -- same theme_gradient/colored-grade pattern already established on
    Command Center's Top Leans and Graded Picks, not a new one-off style. Sorted by real
    ModelProb descending so the strongest match in THIS profile leads, same "most likely first"
    convention used everywhere else real plays get ranked on this platform."""
    rows = []
    for m in matches:
        grade = H._play_value(m, "Grade") or "—"
        line_val = m.get("Line")
        line_str = f"{line_val:g}" if isinstance(line_val, (int, float)) else "—"
        price_marker = "📊 " if m.get("PriceSource") == "book" else ""
        rows.append({
            "Grade": grade,
            "Model %": m.get("ModelProb", 0.0),
            "Player": m.get("Player", ""),
            "Team": m.get("Team", ""),
            "Market": m.get("Market", ""),
            "Side": m.get("Side", ""),
            "Line": f"{price_marker}{line_str}",
            "Game": m.get("Game", ""),
        })
    df = pd.DataFrame(rows).sort_values("Model %", ascending=False, kind="stable")
    return df


if not plays:
    st.info("No games on the board right now, or every game has already started.")
elif not profiles:
    st.info("No profiles yet — build one below.")
else:
    for r in result:
        owner_badge = (f"<span style='background:#374151;color:white;padding:1px 8px;"
                       f"border-radius:10px;font-size:0.78em;'>personal · {r['owner']}</span>"
                       if r.get("owner") else
                       "<span style='background:#1f6feb;color:white;padding:1px 8px;"
                       "border-radius:10px;font-size:0.78em;'>shared</span>")
        n = len(r["matches"])
        count_color = "#16783c" if n > 0 else "#6b7280"
        count_badge = (f"<span style='background:{count_color};color:white;padding:1px 10px;"
                      f"border-radius:10px;font-size:0.85em;font-weight:600;'>{n} match{'es' if n != 1 else ''}</span>")

        with st.container(border=True):
            h1, h2 = st.columns([5, 2])
            with h1:
                st.markdown(f"### {r['emoji']} {r['name']}")
                st.markdown(owner_badge, unsafe_allow_html=True)
            with h2:
                st.markdown(f"<div style='text-align:right;padding-top:14px'>{count_badge}</div>",
                          unsafe_allow_html=True)

            if not r["matches"]:
                st.caption("No plays on tonight's board match this profile.")
            else:
                df = _matches_dataframe(r["matches"])
                shown = df if n <= MAX_ROWS_SHOWN else df.head(MAX_ROWS_SHOWN)
                st.dataframe(
                    shown.style
                        .format({"Model %": "{:.0%}"})
                        .map(lambda g: f"color:{GRADE_COLOR.get(g, '#6b7280')};font-weight:700;",
                             subset=["Grade"])
                        .theme_gradient(cmap="Greens", subset=["Model %"]),
                    hide_index=True, use_container_width=True,
                    height=min(38 * (len(shown) + 1) + 3, 460))
                if n > MAX_ROWS_SHOWN:
                    with st.expander(f"Show all {n} matches"):
                        st.dataframe(
                            df.style
                                .format({"Model %": "{:.0%}"})
                                .map(lambda g: f"color:{GRADE_COLOR.get(g, '#6b7280')};font-weight:700;",
                                     subset=["Grade"])
                                .theme_gradient(cmap="Greens", subset=["Model %"]),
                            hide_index=True, use_container_width=True, height=460)

            if st.button("🗑️ Delete profile", key=f"del_{r['id']}"):
                H.delete_profile(r["id"])
                st.rerun()

st.divider()
st.subheader("Build a new profile")

with st.container(border=True):
    st.caption("Every condition below runs against real fields already on tonight's board — "
              "nothing here is a placeholder or a guess. A play must clear EVERY condition you "
              "add to match (AND logic).")

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
        c_name, c_emoji, c_vis = st.columns([3, 1, 3])
        with c_name:
            name = st.text_input("Profile name", placeholder="e.g. Due for a Homer")
        with c_emoji:
            emoji = st.text_input("Emoji", value="⭐", max_chars=4)
        with c_vis:
            scope = st.radio("Visibility", ["Shared (everyone sees it)", "Personal (just me)"])

        st.markdown("**Conditions** (fill in the ones you want, leave the rest blank)")
        conditions = []
        preview_parts = []
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
                preview_parts.append(f"**{field}** {op} **{value}**")

        if preview_parts:
            st.caption("Will match plays where " + " AND ".join(preview_parts) + ".")

        submitted = st.form_submit_button("Save profile", use_container_width=True)
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
