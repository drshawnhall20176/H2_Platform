"""
Data Health — is the data this platform depends on actually current?

Built after this session found four separate real bugs in the catcher-framing refresh pipeline
alone, every one invisible until someone opened a page and noticed something looked off. This
page exists so that noticing happens here, in one place, at a glance — not downstream, by luck.
"""

import streamlit as st
import components as C
import pandas as pd

import data_freshness as DF

C.base_css()
C.page_header("🩺", "Data Health",
             "A single, honest answer to \"is the data behind this platform actually current, or "
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

st.divider()
C.section_header("🪙", "Odds API credits — where they go")
st.caption("Counted from what the Odds API itself reports for each call (odds_meter.py, since Nov 16). "
           "A job marked (manual) was started by hand; \"app\" is this app's own page loads. "
           "Days before the meter was added show nothing.")
try:
    import odds_meter as OM
    import model_store as MS
    from datetime import datetime as _dt, timedelta as _td
    import pytz as _pytz
    _today = _dt.now(_pytz.timezone("US/Eastern")).date()
    _rows = MS.odds_usage((_today - _td(days=6)).strftime("%Y-%m-%d"))
    _left = MS.odds_remaining()
    if _left:
        st.metric("Credits left (newest reading)", f"{_left['remaining']:,}",
                  help=f"Seen {str(_left['ts'])[:16].replace('T', ' ')} UTC")
    if not _rows:
        st.info("No usage recorded yet. Totals appear after the next scheduled job or priced page load.")
    else:
        _d = pd.DataFrame(OM.by_day(_rows)).rename(columns={"day": "Day", "credits": "Credits", "calls": "Calls"})
        _j = pd.DataFrame(OM.by_job(_rows)).rename(columns={"day": "Day", "job": "Job", "credits": "Credits",
                                                            "calls": "Calls"})
        _c1, _c2 = st.columns([1, 2])
        with _c1:
            st.markdown("**Per day**")
            st.dataframe(_d, hide_index=True, width="stretch")
        with _c2:
            st.markdown("**Per job, biggest first**")
            st.dataframe(_j, hide_index=True, width="stretch")
        with st.expander("By job and feed (sport and kind of call)"):
            _f = pd.DataFrame(sorted(_rows, key=lambda r: (r["day"], r["credits"]), reverse=True)).rename(
                columns={"day": "Day", "job": "Job", "feed": "Feed", "credits": "Credits", "calls": "Calls"})
            st.dataframe(_f, hide_index=True, width="stretch")
except Exception as _exc:                                       # noqa: BLE001 -- never blocks the rest of the page
    st.caption(f"Usage table unavailable ({type(_exc).__name__}).")

st.divider()
C.section_header("🔌", "Live Odds API diagnostic")
st.caption("Checks what market keys and books the Odds API is actually returning for tonight's "
          "slate — the direct answer to 'is my API key configured, and does it have coverage "
          "for the markets this platform uses?'")

import os
try:
    api_key = st.secrets.get("ODDS_API_KEY") or os.environ.get("ODDS_API_KEY")
except Exception:
    api_key = os.environ.get("ODDS_API_KEY")

if not api_key:
    st.warning("No ODDS_API_KEY configured — all lines are using DEFAULT_LINES placeholders. "
              "Add the key to your Streamlit secrets to enable real sportsbook lines.")
else:
    st.caption(f"API key found (ending ...{api_key[-4:]}). Running a live check...")
    import odds_api as O
    from datetime import datetime
    import pytz
    eastern = pytz.timezone("US/Eastern")
    today = datetime.now(eastern).strftime("%Y-%m-%d")

    if st.button("🔍 Run live Odds API market check"):
        with st.spinner("Fetching tonight's market coverage..."):
            try:
                offers, info = O.fetch_slate_props(today, api_key, O.SUPPORTED_MARKETS, sport=O.SPORT)
                remaining = info.get("x-requests-remaining", "unknown")
                st.success(f"Fetch succeeded — {len(offers)} total prop offers returned. "
                          f"Requests remaining: {remaining}")

                # Which markets actually came back
                markets_seen = {}
                for off in offers:
                    m = off.get("market", "unknown")
                    markets_seen[m] = markets_seen.get(m, 0) + 1

                # Which books came back
                books_seen = set()
                for off in offers:
                    books_seen.update((off.get("over") or {}).keys())
                    books_seen.update((off.get("under") or {}).keys())
                    books_seen.update((off.get("pickem") or {}).keys())   # PrizePicks / Pick6 lines
                us_books_seen = {k: O.ALL_BOOKS[k] for k in books_seen if k in O.ALL_BOOKS}

                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Markets returned vs. expected:**")
                    market_rows = []
                    for mk in O.SUPPORTED_MARKETS:
                        count = markets_seen.get(mk, 0)
                        status = "✅" if count > 0 else "❌ MISSING"
                        market_rows.append({"Market key": mk, "Offers": count, "Status": status})
                    st.dataframe(pd.DataFrame(market_rows), hide_index=True, width="stretch")

                with col2:
                    st.markdown("**Sportsbooks & pick'em apps in the response:**")
                    if us_books_seen:
                        for key, name in sorted(us_books_seen.items(), key=lambda x: x[1]):
                            st.markdown(f"✅ {name} (`{key}`)")
                    else:
                        st.warning("No recognized US sportsbooks in the response.")
                    missing_books = {k: v for k, v in {**O.US_BOOKS, **O.PICKEM_BOOKS}.items()
                                     if k not in books_seen}
                    if missing_books:
                        st.markdown("**Not in response:**")
                        for key, name in missing_books.items():
                            st.markdown(f"⬜ {name} (`{key}`)")

                if "batter_hits_runs_rbis" not in markets_seen:
                    st.error("❌ batter_hits_runs_rbis is MISSING from the API response — "
                            "H+R+RBI lines will fall back to the 1.5 DEFAULT_LINES placeholder "
                            "for every player. This market requires the Business tier ($99/mo) "
                            "on The Odds API. Your current key may be on the Professional tier.")
                elif markets_seen.get("batter_hits_runs_rbis", 0) < 5:
                    st.warning("⚠️ batter_hits_runs_rbis returned very few offers "
                              f"({markets_seen.get('batter_hits_runs_rbis', 0)}) — partial "
                              "coverage only. Some players may still fall back to 1.5.")
                else:
                    st.success(f"✅ batter_hits_runs_rbis returned "
                              f"{markets_seen['batter_hits_runs_rbis']} offers — HRR lines "
                              "should be resolving correctly from real book data.")

            except Exception as e:
                st.error(f"Odds API fetch failed: {e}")
                st.caption("This usually means the API key is invalid, quota is exhausted, "
                          "or the market keys aren't available on your subscription tier.")
