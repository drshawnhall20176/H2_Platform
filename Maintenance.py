"""
Maintenance.py — a restart button for when the site acts up (Nov 21).

Owner, Nov 21: "how do I add someone to streamlit that can reboot if things go wrong" -- then yes to a restart button
instead of Streamlit reboot rights (anyone who can manage the app can read its secrets, the Office password among
them). Behind its OWN password (secret MAINT_PASSWORD -- not the Office's, not the trading one; no secret = shut), this
clears what makes the app slow or stuck: every cached slate, board and score (st.cache_data, st.cache_resource, the
in-process caches), frees the memory, and starts this browser session fresh. That fixes the freezes and crashes of this
week (memory, a half-finished reload). It can't revive a server that's down -- only Streamlit's own Reboot can, and
that stays with the owner. Every restart is logged (who typed what note, when, memory before and after).
"""
from __future__ import annotations

import gc
from datetime import datetime, timezone

import streamlit as st

import cache_guard as CG

SECRET = "MAINT_PASSWORD"
LOG_KEY = "maint:log"

st.title("🛠️ Restart the site")
st.caption("For when pages freeze, spin forever, or show an error. This clears the site's caches and memory and "
           "starts fresh — it doesn't change any pick, bet or record, and it can't hurt anything.")

try:
    expected = st.secrets.get(SECRET)
except Exception:                                               # noqa: BLE001
    expected = None

if not st.session_state.get("maint_ok"):
    if not expected:
        st.info("The restart button isn't set up yet (the owner adds a MAINT_PASSWORD secret).")
        st.stop()
    pw = st.text_input("Maintenance password", type="password", key="maint_pw")
    if st.button("Unlock", type="primary"):
        if pw and str(pw) == str(expected):
            st.session_state["maint_ok"] = True
            st.rerun()
        st.error("That's not the maintenance password.")
    st.stop()

used, limit = CG.rss_mb(), CG.limit_mb()
c1, c2 = st.columns(2)
c1.metric("Memory in use", f"{used:,.0f} MB" if used is not None else "—",
          help=f"The site clears its own caches past {limit:,.0f} MB.")
c2.metric("Automatic clears since the last start", f"{CG._STATE.get('clears', 0)}")

def drop_site_modules(mods=None, here=None) -> int:
    """Forget the site's own imported modules (files in this app's folder, not Streamlit or other libraries), so the
    next page load imports today's code. Nov 26: a deploy updated a page but the server kept the old module it
    imports, and the page failed until a full reboot. Returns how many were dropped."""
    import os
    import sys
    mods = sys.modules if mods is None else mods
    here = here or os.path.dirname(os.path.abspath(__file__))
    n = 0
    for name, mod in list(mods.items()):
        f = getattr(mod, "__file__", None) or ""
        if f and os.path.abspath(f).startswith(here + os.sep) and "site-packages" not in f and name != "__main__":
            mods.pop(name, None)
            n += 1
    return n


note = st.text_input("What went wrong? (optional, goes in the log)", key="maint_note",
                     placeholder="e.g. Command Center stuck loading on NCAA Football")
if st.button("🔄 Restart the site now", type="primary"):
    before = CG.rss_mb()
    try:
        st.cache_data.clear()
    except Exception:                                           # noqa: BLE001
        pass
    try:
        st.cache_resource.clear()
    except Exception:                                           # noqa: BLE001
        pass
    for mod in ("props_money", "shutoff", "stakes", "money_score"):   # the modules' own short caches
        try:
            m = __import__(mod)
            getattr(m, "_CACHE", {}).clear()
        except Exception:                                       # noqa: BLE001
            pass
    CG.clear_module_caches()
    import os as _os                                            # Nov 26: so new code is picked up, not just caches
    reloaded = 0 if _os.environ.get("PYTEST_CURRENT_TEST") else drop_site_modules()   # (never inside the test run)
    gc.collect()
    after = CG.rss_mb()
    try:
        import model_store as MS
        log = (MS.get_setting(LOG_KEY, None) or [])[-49:]
        log.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "note": note or "",
                    "before_mb": round(before or 0), "after_mb": round(after or 0)})
        MS.save_setting(LOG_KEY, log)
    except Exception:                                           # noqa: BLE001
        pass
    keep = {"maint_ok"}
    for k in list(st.session_state.keys()):
        if k not in keep:
            del st.session_state[k]
    st.success(f"Restarted: caches cleared, {reloaded} site modules set to reload, memory {before or 0:,.0f} → "
               f"{after or 0:,.0f} MB. Open any page to "
               "carry on — the first load rebuilds what it needs, so give it a minute.")

with st.expander("If it's still broken"):
    st.markdown("1. Refresh the browser tab (or close it and open the site again).\n"
                "2. Wait a minute — the first page after a restart rebuilds its data.\n"
                "3. If every page shows an error or the site won't load at all, the server itself is down: text the "
                "owner, who can reboot it from Streamlit.")

try:
    import model_store as MS
    log = MS.get_setting(LOG_KEY, None) or []
except Exception:                                               # noqa: BLE001
    log = []
if log:
    st.markdown("**Recent restarts**")
    import pandas as pd
    import pytz
    et = pytz.timezone("US/Eastern")
    st.dataframe(pd.DataFrame([{
        "When": datetime.fromisoformat(r["at"]).astimezone(et).strftime("%b %d %-I:%M %p"),
        "Note": r.get("note") or "", "Memory before → after": f"{r.get('before_mb', 0)} → {r.get('after_mb', 0)} MB"}
        for r in reversed(log[-10:])]), hide_index=True, width="stretch")
