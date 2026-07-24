"""
Data Health — is the data this platform depends on actually current?

Built after this session found four separate real bugs in the catcher-framing refresh pipeline
alone, every one invisible until someone opened a page and noticed something looked off. This
page exists so that noticing happens here, in one place, at a glance — not downstream, by luck.
"""

import streamlit as st
import pandas as pd

import data_freshness as DF

st.title("🩺 Data Health")
st.caption("A single, honest answer to \"is the data behind this platform actually current, or "
          "silently stale?\" — checked directly against each file's own real state, not a "
          "workflow's own claimed success.")

results = DF.check_all_sources()
overall = DF.overall_status(results)

STATUS_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
STATUS_LABEL = {"green": "All tracked sources are healthy", "yellow": "One or more sources are stale",
               "red": "One or more sources need attention"}

st.markdown(f"### {STATUS_ICON[overall]} {STATUS_LABEL[overall]}")
st.caption("Green = fresh and healthy · Yellow = stale, likely a silently failed refresh · "
          "Red = missing, unreadable, or an implausibly thin row count")

st.divider()

for r in results:
    icon = STATUS_ICON[r["status"]]
    with st.container(border=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            st.markdown(f"**{icon} {r['name']}**")
            if r["reason"]:
                st.caption(r["reason"])
        with c2:
            if r["last_modified"] is not None:
                st.metric("Last updated", r["last_modified"].strftime("%b %d, %I:%M %p"))
            else:
                st.metric("Last updated", "—")
        with c3:
            st.metric("Rows", r["row_count"] if r["row_count"] is not None else "—")

st.divider()
st.caption("Tracks the file-based sources refreshed by refresh-statcast.yml and "
          "refresh-matchups.yml (both on a real, confirmed daily schedule) — the exact files "
          "behind this session's real bugs. Line-history/CLV data lives in a database instead "
          "of a committed file, a genuinely different mechanism, and isn't tracked here yet.")
