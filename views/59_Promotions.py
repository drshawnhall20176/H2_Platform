"""
59_Promotions.py -- the sportsbooks' promotions: what's on today, the tool that plays it, and the full schedule
(Nov 17). Data and rules live in promos.py; the owner adds one-offs and new recurring promos at the bottom.
"""
from datetime import date, datetime

import pandas as pd
import pytz
import streamlit as st

import components as C
import promos as PR
import sports

ET = pytz.timezone("US/Eastern")
C.base_css()
try:
    _owner = st.secrets.get("AUDIENCE", "owner") == "owner"
except Exception:                                               # noqa: BLE001
    _owner = True

today = datetime.now(ET).date()
C.section_header("🎁", f"Promotions · {today:%A, %B %-d}")
st.caption("The books' recurring promotions show up here on the days they run, and as a banner on Today. Rules "
           "change: always confirm the details in the book's app before you bet.")

custom = PR.custom_promos()
playing = [s.key for s in sports.enabled_sports() if sports.in_season(s.key)]
on = PR.on_today(today, playing, custom)

st.markdown("#### On today")
if not on:
    st.caption("No scheduled promotion today.")
for p in on:
    with st.container(border=True):
        st.markdown(f"**{p['name']}** · {p['book']} · {', '.join(p.get('sports') or [])}")
        st.write(p["rules"])
        if p.get("tool") == "kotc":
            st.markdown("**The model's play:** the 👑 King of the Court table ranks tonight's players by their chance "
                        "of posting the slate's top PRA (20,000 simulated nights, the model's PRA projections, "
                        "blowout minutes taken off).")
            if st.button("Open King of the Court →", key=f"promo_tool_{p['id']}", type="primary"):
                st.session_state["sport"] = "NBA"
                st.session_state["_goto_page"] = "hot_hand_engine"
                st.rerun()
        else:
            st.caption("No model for this promotion yet: the rules are here so you don't miss it, not as an edge.")
        st.caption(f"Checked {p.get('checked', '—')}" + (f" · [source]({p['source']})" if p.get("source") else ""))

st.markdown("#### Every promotion we track")
rows = [{"Book": p["book"], "Promotion": p["name"], "Sports": ", ".join(p.get("sports") or []),
         "When": PR.schedule_text(p), "Season": " – ".join(p["window"]) if p.get("window") else "—",
         "Model": "yes" if p.get("tool") else "—", "Added by": "you" if p.get("custom") else "platform"}
        for p in PR.all_promos(custom)]
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

if _owner:
    with st.expander("➕ Add a promotion (shows on its days from then on)"):
        books = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "BetRivers", "Fanatics", "Hard Rock Bet", "Bet365",
                 "DK Pick6", "PrizePicks", "Underdog"]
        with st.form("add_promo", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name = c1.text_input("Name", placeholder="e.g. NBA Tuesday profit boost")
            book = c2.selectbox("Book", books)
            sp = st.multiselect("Sports", [s.key for s in sports.enabled_sports()])
            kind = st.radio("When", ["Every week on…", "One day only"], horizontal=True)
            days = st.multiselect("Weekdays", list(PR.WEEKDAYS))
            one = st.date_input("Date (one day only)", value=today)
            c3, c4 = st.columns(2)
            start = c3.date_input("Season start", value=today)
            end = c4.date_input("Season end", value=date(today.year + 1, 6, 30))
            rules = st.text_area("Rules in plain words")
            link = st.text_input("Link (optional)")
            if st.form_submit_button("Save promotion", type="primary"):
                if not name or not rules:
                    st.error("A name and the rules are needed.")
                else:
                    new = {"id": f"custom_{len(custom) + 1}_{int(datetime.now().timestamp())}", "book": book,
                           "name": name, "sports": sp, "banner": True, "tool": None, "rules": rules,
                           "days": [PR.WEEKDAYS.index(x) for x in days] if kind.startswith("Every") else [],
                           "dates": [one.isoformat()] if kind.startswith("One") else [],
                           "window": [start.isoformat(), end.isoformat()] if kind.startswith("Every") else None,
                           "checked": f"added {today:%b %-d, %Y}", "source": link or None}
                    if PR.save_custom(custom + [new]):
                        st.success("Saved. It will show on its days.")
                        st.rerun()
                    else:
                        st.error("Couldn't save (database not reachable).")
        if custom:
            drop = st.selectbox("Remove one of yours", ["—"] + [p["name"] for p in custom])
            if drop != "—" and st.button("Remove"):
                PR.save_custom([p for p in custom if p["name"] != drop])
                st.rerun()
