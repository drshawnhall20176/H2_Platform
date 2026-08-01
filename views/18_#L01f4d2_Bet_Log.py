"""
Bet Log — the proof layer, AND the working ledger.

Log every bet, capture closing lines, settle results, and see whether the model actually
works: ROI, CLV (did you beat the closing line?), and a calibration curve (do your 60%s
hit 60%?). This is the evidence a subscriber pays for and a pick-seller can't fake.

VS TRACK RECORD, CLARIFIED DIRECTLY ON REQUEST AFTER A PLATFORM AUDIT: both pages present
real evidence from the SAME logged-bet data (CLV, calibration, per-market performance) --
genuinely overlapping content, not a mistake. The real difference: this page is the FULL
working tool -- log a bet, settle it, see the raw numbers update immediately, no narrative
framing. Track Record is the polished, plain-English presentation of that same evidence,
built for an audience who wants the STORY the numbers tell, not the ledger itself -- and
currently gated for the same reason this page is (not enough real history yet to show), with
the explicit intent to un-gate it publicly once it has enough to demonstrate. Until then, both
being owner-only means this distinction isn't doing its real job yet -- worth revisiting once
Track Record goes public and the two pages actually serve two different audiences.
"""

import streamlit as st
import components as C
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

import sports
import betlog as B
import bet_settlement
import mlb_engine as E

_active = sports.active()
C.base_css()
C.page_header("📒", f"Bet Log — proof layer  ·  {_active.icon} {_active.label}",
             "Track CLV, ROI, and calibration. The record that proves the model works. "
             "Switch sports in the sidebar to see that sport's bets — every bet is logged with "
             "the sport it was placed under.")
# REAL, CONFIRMED FIX -- this link used to be unconditional, but Track Record hides itself
# entirely from the sidebar for any sport with has_projections=False (UFC today). st.page_link
# to a page that isn't part of the CURRENT navigation set raises StreamlitPageNotFoundError, not
# a graceful "page doesn't exist" -- this crashed Bet Log outright for a UFC/owner viewer. Same
# has_projections condition Track Record itself gates on, so the link and its target can never
# drift out of sync again.
if _active.has_projections:
    st.page_link("views/19_Track_Record.py",
                 label="📊 Want the polished, narrative version of this same evidence? See Track Record →",
                 icon="📊")

if not sports.require_trading_access("Bet Log"):
    st.stop()

 
if B.USING_POSTGRES:
    st.success("**Durable storage: connected.** Bets are saved to your Postgres/Supabase database — "
               "they persist through every reboot and redeploy, and are the same from any device.",
               icon="✅")
else:
    st.warning("**Ephemeral storage.** Bets are in a local SQLite file (`data/bets.db`). That's fine "
               "on your own machine, but on Streamlit Cloud this file **resets on every reboot/redeploy — "
               "logged bets can be lost.** Set a `DATABASE_URL` secret (Supabase) for durable storage; "
               "see SUPABASE_SETUP.md.", icon="⚠️")
 
MARKETS = list(_active.market_map.keys()) + ["Other"] if _active.market_map else ["Other"]
 
# --- Log a bet --------------------------------------------------------------
with st.expander("➕ Log a bet", expanded=False):
    # Player search — deliberately OUTSIDE the form below: st.form doesn't rerun reactively per
    # keystroke or on a search button press until the whole form submits, so a live search can't
    # live inside one. Added directly to fix a real, confirmed root cause: bets logged without a
    # real player_id could never be auto-settled (bet_settlement.py has no way to find them in a
    # boxscore) -- 5 real player-prop bets stuck exactly this way in a live settlement log.
    if _active.key == "MLB":
        st.caption("🔍 **Find the player first** (MLB only, for now) — this attaches a real "
                  "player ID so the bet can auto-settle later. Skip it and type the name "
                  "manually below if you prefer; auto-settle just won't be able to find that "
                  "bet without a real ID.")
        sc1, sc2 = st.columns([3, 1])
        with sc1:
            player_query = st.text_input("Search for a player", placeholder="e.g. Wade Meckler",
                                         key="player_search_query", label_visibility="collapsed")
        with sc2:
            search_clicked = st.button("🔍 Search", width="stretch")
        if search_clicked and player_query.strip():
            st.session_state["player_search_results"] = E.search_players(player_query)
        results = st.session_state.get("player_search_results") or []
        if search_clicked and not results:
            st.caption("No real matches found — you can still type the name manually below "
                      "(auto-settle won't be able to find it later without a real ID, though).")
        if results:
            options = ["— none selected, I'll type the name manually —"] + [
                f"{r['name']} — {r['team'] or 'no current team'} ({r['position'] or '?'})"
                f"{'' if r['active'] else '  [inactive]'}"
                for r in results
            ]
            picked_idx = st.selectbox("Real matches — pick one to attach a real player ID",
                                      range(len(options)), format_func=lambda i: options[i])
            if picked_idx > 0:
                chosen = results[picked_idx - 1]
                st.session_state["selected_player_id"] = chosen["id"]
                st.session_state["selected_player_name"] = chosen["name"]
                st.success(f"✅ Attached: {chosen['name']} (ID {chosen['id']}) — this bet will "
                          f"be auto-settleable once the game is Final.")
            else:
                st.session_state["selected_player_id"] = None

    with st.form("log_bet", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            d = st.date_input("Slate date", datetime.now())
            game = st.text_input("Game", placeholder="HOU @ DET")
            _prefill_name = st.session_state.get("selected_player_name", "")
            player = st.text_input("Player", value=_prefill_name, placeholder="Jose Altuve",
                                   help="Pre-filled from the search above, if you used it. You "
                                        "can still edit this — just know editing it away from "
                                        "the searched name won't change which player_id gets "
                                        "attached below.")
        with c2:
            market = st.selectbox("Market", MARKETS)
            side = st.selectbox("Side", ["Over", "Under", "Yes"])
            line = st.number_input("Line", value=1.5, step=0.5)
        with c3:
            entry_odds = st.number_input("Entry odds (American)", value=-110, step=5)
            model_prob = st.number_input("Model prob", min_value=0.0, max_value=1.0, value=0.55, step=0.01,
                                         help="The model's probability for this side, from the Edge Board.")
            stake = st.number_input("Stake ($)", min_value=0.0, value=2.50, step=0.5)
        col_b, col_t = st.columns(2)
        with col_b:
            # Default to whichever book was last selected on Best Bets / Graded Picks.
            # Session state keys follow the pattern set by render_book_selector:
            # "best_bets_book_selector", "graded_picks_book_selector", etc.
            _ss_book = (st.session_state.get("best_bets_book_selector")
                        or st.session_state.get("graded_picks_book_selector")
                        or st.session_state.get("speculative_basket_book_selector")
                        or st.session_state.get("suggested_parlays_book_selector"))
            from odds_api import US_BOOKS, DEFAULT_BOOK
            _book_keys = list(US_BOOKS.keys())
            _book_labels = [US_BOOKS[k] for k in _book_keys]
            # _ss_book is already the display label from the selectbox widget
            _default_label = _ss_book if _ss_book in _book_labels else US_BOOKS.get(DEFAULT_BOOK, "DraftKings")
            _default_idx = _book_labels.index(_default_label) if _default_label in _book_labels else 0
            book_label = st.selectbox("Book", _book_labels, index=_default_idx,
                                      help="Defaults to whichever book you selected on Best Bets / Graded Picks.")
            book = _book_keys[_book_labels.index(book_label)]
        with col_t:
            ticket = st.text_input("Parlay ticket (optional)", placeholder="e.g. Parlay 6/28 #1",
                                   help="Give every leg of the same parlay the SAME tag to group them. "
                                        "Leave blank for a straight single.")
        notes = st.text_input("Notes", placeholder="optional")
        if st.form_submit_button("Log bet", type="primary"):
            if player and game:
                _pid = st.session_state.get("selected_player_id")
                # Only trust the attached player_id if the typed name still matches what was
                # searched -- if someone selected a player then edited the name field afterward,
                # attaching the OLD id to a DIFFERENT typed name would be a real, silent
                # correctness bug (settling the wrong player's bet), worse than no id at all.
                if _pid is not None and player.strip() != st.session_state.get("selected_player_name", "").strip():
                    _pid = None
                B.add_bet(slate_date=d.isoformat(), game=game, player=player, player_id=_pid,
                          market=market, side=side, line=line, entry_odds=int(entry_odds),
                          model_prob=model_prob, stake=stake, book=book, notes=notes,
                          ticket=ticket.strip(), sport=_active.key)
                id_note = f" (player ID {_pid} attached — will auto-settle)" if _pid else \
                          " (no player ID attached — will need manual settlement)"
                st.success(f"Logged: {player} {market} {side} {line}{id_note}"
                           + (f"  ·  ticket “{ticket.strip()}”" if ticket.strip() else ""))
                st.session_state["selected_player_id"] = None
                st.session_state["selected_player_name"] = ""
                st.session_state["player_search_results"] = []
            else:
                st.warning("Player and game are required.")
 
bets = B.list_bets(sport=_active.key)
if not bets:
    st.info(f"No {_active.label} bets logged yet. Use **Log a bet** above to start your record.")
    st.stop()
 
s = B.summary(bets)
 
# --- Summary ----------------------------------------------------------------
C.section_header("📈", "Performance")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Record", f"{s['wins']}-{s['losses']}", help=f"{s['open']} open, {s['settled']} settled")
m2.metric("Profit", f"${s['profit']:,.2f}")
m3.metric("ROI", f"{s['roi']:+.1f}%" if s["roi"] is not None else "—")
m4.metric("Avg CLV", f"{s['avg_clv']:+.2f}%" if s["avg_clv"] is not None else "—",
          help=f"Over {s['clv_n']} bets with a closing line recorded.")
m5.metric("Beat-close rate", f"{s['beat_close_rate']:.0f}%" if s["beat_close_rate"] is not None else "—",
          help="Share of bets where you got a better price than the close. >50% is the goal.")
 
if s["clv_n"] == 0:
    st.caption("💡 Enter **closing odds** when you settle bets below to unlock CLV — it's the "
               "fastest signal that you're beating the market, long before ROI stabilizes.")
 
# --- Open bets: settle ------------------------------------------------------
open_bets = [b for b in bets if not b.get("result")]
if open_bets:
    C.section_header("📝", f"Open bets ({len(open_bets)}) — enter closing odds & result, then save")

    # Auto-settle, added directly on request: betlog.py's own player_id column was added
    # specifically "for automated result settlement" (see its own schema comment) referencing
    # retro.py's existing grading machinery -- this is what actually uses it, wired to real,
    # already-tested logic (bet_settlement.py) rather than left as unused schema groundwork.
    # MLB ONLY FOR NOW, same honest scope as several other features on this platform.
    if _active.key == "MLB":
        st.markdown("**🔄 Auto-settle open bets**")
        st.caption("Checks each open bet's real game against the real MLB schedule and, only "
                  "for a game already confirmed Final, fills in the real result — win, loss, "
                  "push, or void (a real scratch/DNP settles as void, not a loss). Never "
                  "touches a bet whose game is still in progress. Shows a real preview below "
                  "before anything is saved — nothing changes in the Bet Log until you "
                  "explicitly confirm. Doesn't touch closing odds — enter those in the table "
                  "below same as always, auto-settle only fills in the real result.")
        if st.button("🔍 Check for settleable bets"):
            with st.spinner("Checking real schedules and box scores..."):
                st.session_state["settlement_plan"] = bet_settlement.build_settlement_plan(open_bets)

        plan = st.session_state.get("settlement_plan")
        if plan:
            proposed = plan["proposed"]
            still_pending = plan["still_pending"]
            unresolved = plan["unresolved"]

            if proposed:
                st.markdown(f"**{len(proposed)} bet(s) ready to settle:**")
                preview_df = pd.DataFrame(proposed)[["description", "old_result", "new_result"]]
                preview_df.columns = ["Bet", "Current", "New result"]
                st.dataframe(preview_df, hide_index=True, width="stretch")
                if st.button(f"✅ Confirm and apply {len(proposed)} settlement(s)", type="primary"):
                    n = bet_settlement.apply_settlement_plan(proposed)
                    st.session_state.pop("settlement_plan", None)
                    st.success(f"Settled {n} bet(s). Enter closing odds below if you have them, "
                              "then save.")
                    st.rerun()
            else:
                st.caption("Nothing is settleable right now — check the sections below for why.")

            if still_pending:
                with st.expander(f"⏳ {len(still_pending)} still pending — game not Final yet"):
                    st.dataframe(pd.DataFrame(still_pending)[["description", "game", "status"]]
                                .rename(columns={"description": "Bet", "game": "Game", "status": "Status"}),
                                hide_index=True, width="stretch")
            if unresolved:
                with st.expander(f"❓ {len(unresolved)} couldn't be auto-settled — needs manual entry"):
                    st.dataframe(pd.DataFrame(unresolved)[["description", "reason"]]
                                .rename(columns={"description": "Bet", "reason": "Why"}),
                                hide_index=True, width="stretch")

                    # Retroactive player-ID backfill — the other half of the same real gap the
                    # Log a bet form's own player search already fixes going forward. Only
                    # offered for bets whose reason is specifically the missing-player_id one:
                    # attaching a player_id wouldn't fix a different problem (a game that
                    # couldn't be matched at all, say), so those aren't listed here.
                    fixable = [u for u in unresolved if "no player_id" in u.get("reason", "")]
                    if fixable:
                        st.markdown("**🔗 Attach a real player ID to one of these**")
                        fix_options = {f"{u['description']} (bet #{u['bet_id']})": u for u in fixable}
                        fix_choice = st.selectbox("Which bet?", list(fix_options.keys()),
                                                  key="backfill_bet_choice")
                        target = fix_options[fix_choice]

                        bc1, bc2 = st.columns([3, 1])
                        with bc1:
                            backfill_query = st.text_input(
                                "Search for the real player", placeholder="e.g. Wade Meckler",
                                key="backfill_search_query", label_visibility="collapsed")
                        with bc2:
                            backfill_clicked = st.button("🔍 Search", key="backfill_search_button",
                                                         width="stretch")
                        if backfill_clicked and backfill_query.strip():
                            st.session_state["backfill_search_results"] = E.search_players(backfill_query)
                        backfill_results = st.session_state.get("backfill_search_results") or []
                        if backfill_clicked and not backfill_results:
                            st.caption("No real matches found — try a different spelling.")
                        if backfill_results:
                            backfill_labels = [
                                f"{r['name']} — {r['team'] or 'no current team'} ({r['position'] or '?'})"
                                f"{'' if r['active'] else '  [inactive]'}"
                                for r in backfill_results
                            ]
                            backfill_idx = st.selectbox(
                                "Real matches — pick the right one", range(len(backfill_results)),
                                format_func=lambda i: backfill_labels[i], key="backfill_pick")
                            if st.button("✅ Attach this player ID", key="backfill_attach_button",
                                        type="primary"):
                                chosen = backfill_results[backfill_idx]
                                B.update_bet(target["bet_id"], player_id=chosen["id"])
                                st.session_state.pop("settlement_plan", None)
                                st.session_state.pop("backfill_search_results", None)
                                st.success(f"Attached {chosen['name']} (ID {chosen['id']}) to "
                                          f"bet #{target['bet_id']}. Click 'Check for settleable "
                                          f"bets' again to see if it now settles.")
                                st.rerun()
        st.divider()
    else:
        st.caption(f"Auto-settle isn't available for {_active.label} yet — MLB only for now. "
                  "Enter results manually in the table below.")

    odf = pd.DataFrame(open_bets)[["id", "player", "market", "side", "line", "entry_odds",
                                   "model_prob", "stake", "close_odds", "result", "cashed_out_amount"]]
    edited = st.data_editor(
        odf, hide_index=True, width="stretch", key="settle_editor",
        disabled=["id", "player", "market", "side", "line", "entry_odds", "model_prob", "stake"],
        column_config={
            "close_odds": st.column_config.NumberColumn("Closing odds", help="The price at game time / close."),
            "result": st.column_config.SelectboxColumn("Result", options=["", "win", "loss", "push", "void"]),
            "model_prob": st.column_config.NumberColumn("Model %", format="%.2f"),
            "cashed_out_amount": st.column_config.NumberColumn(
                "Cashed out ($)", help="If you cashed this bet out early, enter what you actually "
                "received here. Leave blank if you held it — a blank is not the same as a $0 "
                "cash-out. You can enter this before the bet is graded; once the real result comes "
                "in (auto-settle or manual), the Cash-out vs. held report below can compare what "
                "you actually took against what holding would have paid."),
        },
    )
    if st.button("💾 Save settlements", type="primary"):
        n = 0
        for _, r in edited.iterrows():
            co = None if pd.isna(r["close_odds"]) else int(r["close_odds"])
            res = r["result"] or None
            cashed_out = None if pd.isna(r["cashed_out_amount"]) else float(r["cashed_out_amount"])
            B.update_bet(int(r["id"]), close_odds=co, result=res, cashed_out_amount=cashed_out)
            n += 1
        st.success(f"Saved {n} bet(s).")
        st.rerun()
 
# --- Calibration ------------------------------------------------------------
C.section_header("📐", "Calibration — do your probabilities tell the truth?")
cal = B.calibration(bets, n_bins=5)
settled_n = s["settled"]
if settled_n < 20:
    st.caption(f"Only {settled_n} settled bets so far. Calibration needs volume to mean anything "
               "— aim for 50+ before reading much into the curve.")
if cal:
    fig, ax = plt.subplots(figsize=(3.6, 3.0), dpi=110)
    ax.plot([0, 1], [0, 1], "--", color="gray", label="perfect calibration", linewidth=1)
    xs = [c["predicted"] for c in cal]
    ys = [c["actual"] for c in cal]
    ns = [c["n"] for c in cal]
    ax.scatter(xs, ys, s=[max(25, n * 8) for n in ns], color="#2563eb", alpha=0.75, zorder=3)
    for c in cal:
        ax.annotate(f"n={c['n']}", (c["predicted"], c["actual"]),
                    textcoords="offset points", xytext=(6, -4), fontsize=7)
    ax.set_xlabel("Model predicted probability", fontsize=8)
    ax.set_ylabel("Actual win rate", fontsize=8)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_title("Reliability curve", fontsize=9)
    ax.tick_params(labelsize=7)
    ax.legend(loc="upper left", fontsize=7)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    _cc, _ = st.columns([2, 3])          # cap width to ~40% of the page
    with _cc:
        try:
            st.pyplot(fig, width="content")
        except TypeError:
            st.pyplot(fig)
    plt.close(fig)
    st.caption("Points on the dashed line = well-calibrated. Points BELOW = overconfident "
               "(your 70%s aren't hitting 70%). Points ABOVE = underconfident. This is the chart "
               "that catches a model lying to you — like a phantom 90% that never cashes.")
else:
    st.caption("No settled bets yet — settle some above to build the calibration curve.")
 
# --- Parlay vs straight bets -----------------------------------------------
st.divider()
C.section_header("🎫", "Parlay vs straight bets")
tickets = B.group_tickets(bets)
multi = {t: legs for t, legs in tickets.items() if len(legs) > 1}
if not multi:
    st.caption("Tag the legs of a parlay with the same ticket name (in the log form above) and "
               "this compares the parlay to betting the same money as straight singles.")
else:
    st.caption("For each parlay, this shows what it paid (or lost) versus betting the **same total "
               "money** as straight singles, split evenly across the legs. The honest lesson, in dollars.")
    pick = st.selectbox("Ticket", sorted(multi.keys()))
    legs = multi[pick]
    default_stake = round(sum(L.get("stake") or 0 for L in legs), 2) or 10.0
    pstake = st.number_input("What you risked on this parlay ($)", min_value=0.5,
                             value=float(default_stake), step=0.5)
    cmp = B.compare_parlay_vs_singles(legs, pstake)
    if cmp:
        a, b = st.columns(2)
        a.metric(f"Parlay ({cmp['parlay_american']:+d})" if cmp["parlay_american"] else "Parlay",
                 f"${cmp['parlay_pnl']:+.2f}" if cmp["parlay_pnl"] is not None else "pending",
                 help=f"All {cmp['n']} legs must hit. Status: {cmp['status']}")
        b.metric(f"Same ${cmp['parlay_stake']:.0f} as singles",
                 f"${cmp['singles_pnl']:+.2f}" if cmp["singles_pnl"] is not None else "pending",
                 delta=f"{cmp['difference']:+.2f} vs parlay" if cmp["difference"] is not None else None,
                 help=f"${cmp['per_leg_stake']:.2f} on each leg as a straight bet")
        if cmp["difference"] is not None:
            if cmp["difference"] > 0:
                st.success(f"Straight singles would have returned **${cmp['difference']:+.2f} more** "
                           f"than the parlay on this ticket.")
            else:
                st.info(f"This time the parlay beat singles by **${-cmp['difference']:.2f}** — the "
                        f"upside case, when every leg hits. It's the rarer outcome.")
        legdf = pd.DataFrame(cmp["legs"])
        legdf["as single"] = legdf["pnl"].apply(lambda v: f"${v:+.2f}" if v is not None else "—")
        st.dataframe(
            legdf[["player", "market", "side", "line", "entry_odds", "result", "as single"]]
            .style.format({"line": "{:.1f}", "entry_odds": "{:.0f}"}, na_rep="—"),
            hide_index=True, width="stretch")

# --- Cash-out vs. held --------------------------------------------------------
st.divider()
C.section_header("💵", "Cash-out vs. held")
st.caption("An honest measure of something this community jokes about a lot — is cashing out "
          "early actually costing money, or actually saving it? For every bet with a cash-out "
          "amount logged (in the settle table above) whose real result has since come in, this "
          "compares what you actually walked away with against what holding to the end would "
          "have paid. Log the cash-out amount while the bet is still open — once it's graded and "
          "drops out of the settle table above, there's currently no way to add one retroactively.")
co_report = B.cash_out_vs_held(bets)
if co_report["n"] == 0:
    st.caption("No graded cash-outs yet. Enter a cash-out amount on an open bet above, then once "
              "its real result is in (auto-settle or manual), it shows up here.")
else:
    a, b = st.columns(2)
    a.metric("Actually realized (cash-outs)", f"${co_report['total_actual_pnl']:+.2f}",
             help=f"Across {co_report['n']} graded cash-out(s) — what was actually taken.")
    b.metric("Would've realized (held to the end)", f"${co_report['total_held_pnl']:+.2f}",
             delta=f"{-co_report['net_value_of_cashing_out']:+.2f} vs actual",
             help="What the same bets would have paid had every one been held to its real result.")
    net = co_report["net_value_of_cashing_out"]
    if net < 0:
        st.success(f"Cashing out has net **saved ${-net:.2f}** across these bets compared to "
                   f"holding every one to the end.")
    elif net > 0:
        st.info(f"Holding to the end would have net **paid ${net:.2f} more** across these bets — "
                f"the real cost of the cash-out habit, in dollars, not a feeling.")
    else:
        st.caption("A wash so far — cashing out and holding have netted the same across these bets.")
    codf = pd.DataFrame(co_report["rows"])
    st.dataframe(
        codf[["game", "player", "market", "stake", "cashed_out_amount", "actual_pnl",
             "held_pnl", "difference", "final_result"]]
        .rename(columns={"cashed_out_amount": "Cashed out ($)", "actual_pnl": "Actual P&L",
                         "held_pnl": "P&L if held", "difference": "Held − actual",
                         "final_result": "Real result"})
        .style.format({"stake": "${:.2f}", "Cashed out ($)": "${:.2f}", "Actual P&L": "${:+.2f}",
                       "P&L if held": "${:+.2f}", "Held − actual": "${:+.2f}"}),
        hide_index=True, width="stretch")

 
# --- Full ledger ------------------------------------------------------------
st.divider()
C.section_header("📖", "Ledger")
df = pd.DataFrame(bets)
df["CLV%"] = df.apply(lambda r: B.clv_pct(r.get("entry_odds"), r.get("close_odds")), axis=1)
df["P&L"] = df.apply(lambda r: B.bet_pnl(r), axis=1)
cols = ["slate_date", "game", "player", "market", "side", "line", "entry_odds", "model_prob",
        "stake", "book", "close_odds", "CLV%", "result", "P&L", "ticket"]
show = df[[c for c in cols if c in df.columns]]
st.dataframe(
    show.style.format({"model_prob": "{:.2f}", "CLV%": "{:+.1f}", "P&L": "${:+.2f}",
                       "line": "{:.1f}", "stake": "${:.2f}", "entry_odds": "{:.0f}",
                       "close_odds": "{:.0f}"}, na_rep="—")
    .theme_gradient(cmap="RdYlGn", subset=["CLV%"]),
    width="stretch", hide_index=True)
 
with st.expander("Why CLV is the metric that matters"):
    st.markdown(
        """
**Closing Line Value (CLV)** is how much better your price was than the line's *close*. If
you bet a prop at +120 and it closes at +100, you beat the close — positive CLV.
 
It matters because the **closing line is the market's most accurate estimate**, sharpened by
all the money bet right up to game time. Consistently beating it is the clearest evidence you
have a real edge — and unlike ROI, which is buried in variance and takes a full season to
trust, CLV shows up in **weeks**. A bettor with positive long-run CLV is almost always a
long-run winner, even through cold streaks.
 
So the order of proof is: **beat-close rate > 50% and positive avg CLV first** (you're getting
good numbers), then **calibration** (your probabilities are honest), then **ROI** (the money
follows). Track CLV from bet #1.
"""
    )
