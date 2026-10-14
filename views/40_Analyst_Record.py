"""
Analyst Record — H2 Sports Media's public, verifiable track record.

Every call the Analyst Desk makes is LOCKED before kickoff and graded afterwards against the real result.
This page shows that record as it stands: the hit rate against the chance the model itself stated, how
each kind of angle has held up, calibration, every locked call with its lock time, a CSV of the whole record
and a fingerprint anyone can recompute. It is read-only — nothing here writes, posts or spends anything — so
it is safe for the public build. See analyst.py / analyst_ledger.py / analyst_tools.py for the rules.
"""

from datetime import datetime

import pandas as pd
import pytz
import streamlit as st

import analyst as A
import analyst_calibration as CAL
import analyst_ledger as AL
import analyst_tools as AT
import components as C
import sports

C.base_css()
C.page_header("🧾", "Analyst Record",
              f"{AT.BRAND} — every call locked before kickoff and graded afterward. Nothing is back-filled or edited.")

try:
    all_rows = AL.fetch_calls()
except Exception:                                      # noqa: BLE001 — the record being unreachable must be said, not hidden
    st.warning("The record couldn't be read right now. Try again in a minute.")
    st.stop()

if not all_rows:
    st.info("No calls have been locked yet. The record starts the first time the Analyst Desk publishes a card for a game "
            "that hasn't started — nothing is ever added after the fact.")
    st.stop()

# Every sport the Desk covers, not just the ones with calls so far: a sport with no calls yet should read as "none yet",
# not look like it's missing from the record.
_covered = [s.key for s in sports.enabled_sports() if s.has_projections]
sport_options = _covered + sorted({r["sport"] for r in all_rows} - set(_covered))
c1, c2 = st.columns([1, 2])
with c1:
    sport_pick = st.selectbox("Sport", ["All sports"] + sport_options, key="record_sport")
with c2:
    basis = st.radio("Record basis", ["Everything the model flagged", "Published to the audience only"], horizontal=True,
                     key="record_basis",
                     help="The first is every call the Desk locked. The second is only the calls actually posted to the "
                          "audience (stamped when posted).")
rows = [r for r in all_rows if sport_pick == "All sports" or r["sport"] == sport_pick]
if basis.startswith("Published"):
    rows = [r for r in rows if r.get("published_at")]
if not rows and sport_pick != "All sports":
    st.info(f"No {sport_pick} calls have been locked yet" + (" for the audience." if basis.startswith("Published") else ".")
            + " The record for a sport starts the first time the Desk locks a call for it.")
graded = [r for r in rows if r.get("hit") is not None]      # a void (player didn't play) or an open call is neither a hit nor a miss
board = A.scoreboard(graded)
overall = board[0]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Calls locked", len(rows))
m2.metric("Graded", overall["n"], help="Hits and misses. A call for a player who didn't play is a void, not a loss.")
m3.metric("Hit rate", "—" if overall["hit_rate"] is None else f"{overall['hit_rate']:.0%}")
m4.metric("Model said", "—" if overall["mean_prob"] is None else f"{overall['mean_prob']:.0%}",
          help="The average chance the model itself gave those calls before they were played.")
st.markdown(f"**Status: {overall['status']}.** " + (
    f"95% range for the hit rate: {overall['ci_low']:.0%}–{overall['ci_high']:.0%}." if overall["ci_low"] is not None else
    f"A verdict needs {A.STATUS_MIN_N} graded calls — until then this is a record being built, not a result."))
st.caption("'Predictable' here means the hit rate matches the chance the model stated, over enough calls. It does not mean "
           "the calls were profitable.")

# Which locked calls are graded, void, or waiting for a result. A big "waiting" count means grading isn't getting results for that
# sport (the game is over but no stat line has been recorded) — not that the calls lost.
_today = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
_status = AT.grading_status([r for r in all_rows if sport_pick == "All sports" or r["sport"] == sport_pick], _today)
_stuck = [x for x in _status if x["waiting"] >= max(10, 0.2 * x["locked"])]
with st.expander("📬 Grading status — which calls are still waiting for a result", expanded=bool(_stuck)):
    for x in _stuck:
        st.warning(f"{x['sport']}: {x['waiting']} locked call(s) from {x['waiting_days']} earlier day(s) have no result yet "
                   f"(oldest {x['oldest_waiting']}). The game is over, so this means the stats for that sport haven't come back — "
                   "the calls are not losses, they just aren't counted until results arrive.")
    st.dataframe(pd.DataFrame([{
        "Sport": x["sport"], "Locked": x["locked"], "Graded": x["graded"], "Void (didn't play)": x["void"],
        "Today / upcoming": x["open_today"], "Waiting for results": x["waiting"], "Days waiting": x["waiting_days"],
        "Oldest waiting": x["oldest_waiting"] or ""} for x in _status]), width="stretch", hide_index=True)
    st.caption("Void = the player didn't play. Waiting = the game date has passed but no result has been recorded; the Analyst "
               "Desk and the scheduled run grade these as soon as the sport's results are published.")

tab_angle, tab_market, tab_cal, tab_calls, tab_verify, tab_method = st.tabs(
    ["🧭 By angle", "🧩 By market", "🎯 Calibration", "📋 Every call", "🔐 Verify it", "📖 Method & limits"])

with tab_angle:
    shown = [r for r in board if r["n"]]
    if not shown:
        st.info("No call has been graded yet in this view.")
    else:
        st.dataframe(pd.DataFrame([{
            "Angle": r["label"], "Graded": r["n"], "Hit rate": r["hit_rate"], "Model said": r["mean_prob"],
            "95% range": "" if r["ci_low"] is None else f"{r['ci_low']:.0%}–{r['ci_high']:.0%}", "Status": r["status"],
        } for r in shown]), width="stretch", hide_index=True, column_config={
            "Hit rate": st.column_config.NumberColumn(format="percent"),
            "Model said": st.column_config.NumberColumn(format="percent")})
        st.caption("An angle is judged only after 30 graded calls; before that it reads 'Collecting data'.")
    clv = [r for r in AT.clv_board(rows) if r["marked"]]
    if clv:
        st.markdown("##### Did the market agree before the game?")
        st.dataframe(pd.DataFrame([{
            "Angle": r["label"], "Tracked": r["marked"], "Moved toward": r["toward"], "Moved away": r["away"],
            "Toward rate": r["toward_rate"], "Status": r["status"]} for r in clv]),
            width="stretch", hide_index=True, column_config={"Toward rate": st.column_config.NumberColumn(format="percent")})

with tab_market:
    mkts = AT.market_board(graded)
    if not mkts:
        st.info("No call has been graded yet in this view.")
    else:
        st.dataframe(pd.DataFrame([{
            "Market": r["market"], "Graded": r["n"], "Hit rate": r["hit_rate"], "Model said": r["mean_prob"],
            "Gap": r["gap"], "95% range": "" if r["ci_low"] is None else f"{r['ci_low']:.0%}–{r['ci_high']:.0%}",
            "Status": r["status"]} for r in mkts]), width="stretch", hide_index=True, column_config={
            "Hit rate": st.column_config.NumberColumn(format="percent"),
            "Model said": st.column_config.NumberColumn(format="percent"),
            "Gap": st.column_config.NumberColumn(format="%+.1f%%", help="Hit rate minus the chance the model stated, in "
                                                 "percentage points. Negative = the model was overconfident for this market.")})
        st.caption("This shows WHERE a shortfall lives. A market with a large negative gap over 30+ graded calls is the place to "
                   "look first; a market that is calibrated is one the stated chance can be trusted for.")

with tab_cal:
    rel = A.reliability(graded)
    if not rel:
        st.info("Calibration appears once calls have been graded.")
    else:
        df = pd.DataFrame(rel).rename(columns={"bucket": "Model said", "n": "Calls", "stated": "Avg stated", "actual": "Actual hit rate"})
        st.dataframe(df, width="stretch", hide_index=True,
                     column_config={"Avg stated": st.column_config.NumberColumn(format="percent"),
                                    "Actual hit rate": st.column_config.NumberColumn(format="percent")})
        st.bar_chart(df.set_index("Model said")[["Avg stated", "Actual hit rate"]])
        st.caption("If the bars match within each bucket, the model's stated chances can be trusted. Small buckets swing "
                   "widely, so read the Calls column before the bars.")
    st.markdown("##### Would correcting the stated chance help?")
    _evs = []
    for _sp in sorted({r["sport"] for r in graded}):
        _ev = CAL.evaluate([r for r in graded if r["sport"] == _sp])
        _evs.append((_sp, _ev))
    if not _evs:
        st.info("Appears once calls have been graded.")
    else:
        def _verdict(ev):
            if ev["status"] != "ok":
                return f"Not enough yet (needs {CAL.MIN_TRAIN}+ older and {CAL.MIN_TEST}+ recent graded calls)"
            return "Yes — the correction beat the stated chance on recent calls" if ev["helps"] else "No — the stated chance did as well or better"
        st.dataframe(pd.DataFrame([{
            "Sport": sp, "Graded": ev["n"], "Fitted on": ev["n_train"], "Tested on (newest)": ev["n_test"],
            "Stated (tested)": ev.get("test_stated"), "Actually hit": ev.get("test_hit"), "Corrected": ev.get("test_adjusted"),
            "Error before": ev.get("brier_raw"), "Error after": ev.get("brier_adj"), "Verdict": _verdict(ev)}
            for sp, ev in _evs]), width="stretch", hide_index=True, column_config={
            "Stated (tested)": st.column_config.NumberColumn(format="percent"),
            "Actually hit": st.column_config.NumberColumn(format="percent"),
            "Corrected": st.column_config.NumberColumn(format="percent"),
            "Error before": st.column_config.NumberColumn(format="%.3f"),
            "Error after": st.column_config.NumberColumn(format="%.3f")})
        for sp, ev in _evs:
            if ev["status"] == "ok" and ev["helps"]:
                ex = CAL.examples(ev["model"])
                st.write(f"**{sp}:** " + ", ".join(f"a stated {k:.0%} has really behaved like {v:.0%}" for k, v in ex.items()) + ".")
        st.caption("The correction is fitted on the OLDER graded calls and scored on the newest ones it never saw; 'Error' is the "
                   "Brier score (lower is better). A sport only shows a corrected chance on the Analyst Desk when it passed that "
                   "test. It never changes a lock or a published number.")

with tab_calls:
    result_pick = st.multiselect("Result", ["Hit", "Miss", "Void", "Open"], default=[], key="record_result",
                                 help="Leave empty to show everything.")
    table = pd.DataFrame([{
        "Locked at (UTC)": r["logged_at"], "Date": r["date"], "Sport": r["sport"], "Game": r.get("game"), "Player": r["player"],
        "Play": f"{r['side']} {r['line']:g} {r['market']}" if r.get("line") is not None else f"{r['side']} {r['market']}",
        "Model": r.get("model_prob"), "Price": r.get("price"), "Book": r.get("price_book"),
        "Angles": ", ".join(r.get("angles") or []), "Gem": "💎" if r.get("gem") else "",
        "Published": r.get("published_at") or "", "Result": AT.result_label(r), "Actual": r.get("actual"),
    } for r in sorted(rows, key=lambda r: (r["date"], r["logged_at"]), reverse=True)
        if not result_pick or AT.result_label(r) in result_pick])
    st.write(f"{len(table)} of {len(rows)} calls")
    st.dataframe(table, width="stretch", hide_index=True,
                 column_config={"Model": st.column_config.NumberColumn(format="percent"),
                                "Price": st.column_config.NumberColumn(format="%+d")})
    st.download_button("⬇️ Download the full record (CSV)", AT.record_csv(all_rows),
                       file_name="h2_sports_media_analyst_record.csv", mime="text/csv", key="record_csv")

with tab_verify:
    fp = AL.record_fingerprint(all_rows)
    st.markdown(f"**Record fingerprint (all sports, {len(all_rows)} locked calls): `{fp}`**")
    st.markdown(
        "The fingerprint is a SHA-256 hash of every call's locked fields (when it was locked, the player, market, side, line, "
        "the model's chance, and the price and book). H2 Sports Media posts it with each Discord card. If the record were ever "
        "edited after a post, the fingerprint would no longer match. Results, grading and later market moves are not part of "
        "it, so it only changes when a new call is locked.\n\n"
        "**To check it yourself**, download the CSV above. Its first ten columns are exactly the locked fields, already in "
        "order. Then:")
    st.code(
        "import csv, hashlib\n"
        "rows = list(csv.reader(open('h2_sports_media_analyst_record.csv')))[1:]\n"
        "text = '\\n'.join('|'.join(r[:10]) for r in rows)\n"
        "print(hashlib.sha256(text.encode('utf-8')).hexdigest()[:16])", language="python")
    st.caption("A fingerprint posted on a given day covers the calls locked up to that moment, so it matches the CSV only "
               "when you use the rows up to that time (filter by the 'logged_at' column).")

with tab_method:
    st.markdown(
        f"**Who:** {AT.BRAND}.\n\n"
        "**What a call is:** a play the Analyst Desk flagged because at least one angle cleared its bar, at a line the named "
        "sportsbook was actually posting for that player and side.\n\n"
        "**When it is locked:** the first time the Desk publishes it, and only for a game that hasn't started. The line, "
        "the model's chance and the price are frozen at that moment. A later line move or a re-run never rewrites it, and "
        "no call is added after its game begins.\n\n"
        "**How it is graded:** against the real box-score result with the same rules the rest of the platform uses. A call "
        "for a player who didn't play is a void, not a loss.\n\n"
        "**Where the percentage comes from:** the platform's standard projection (a replay of the player's recent games "
        "for that stat against the line, with small samples pulled toward 50%). It is not a separate model. With few recent "
        "games it is capped (4 for 4 shows as 75%).\n\n"
        "**What the angles are:** tests laid over that number — model vs market, soft price, form run, role surge, team "
        "momentum, regression due, line movement, other markets' line, game script (the spread and total) and "
        "opponent matchup (what the defense has allowed). A hidden gem needs two different *kinds* of "
        "evidence, because two angles built from the same recent games aren't independent confirmation. Game script and "
        "opponent matchup come from data the model's percentage doesn't use.\n\n"
        "**What this record is not:** it is not a profit claim and not a guarantee of any result. Small samples swing "
        "widely, and an angle is only judged after 30 graded calls.\n\n"
        "21+. Problem gambling? Call 1-800-GAMBLER.")
