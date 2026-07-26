"""
quick_log.py — a shared "log this pick to the Bet Log" component, added directly on request for
a real, stated reason: during an actual, narrow pick-making window, requiring a separate manual
entry into Bet Log is real friction that gets skipped in favor of prioritizing pick selection
itself. Reusable across every page that surfaces plays -- Command Center's Top Leans, Best Bets,
Graded Picks, Suggested Parlays, Speculative Basket -- so this is built once, tested once, and
wired in consistently rather than copy-pasted with subtle differences on each page.

OWNER-ONLY, ALWAYS -- a second real reason stated directly alongside the friction one: this is
explicitly framed as a future "role ability," a paid feature once multi-user login exists. Right
now there's only one real owner, so this gates the SAME way regardless of whether the calling
page itself is public (Command Center) or already owner-only (Graded Picks, Suggested Parlays,
Speculative Basket, Best Bets) -- Bet Log is fundamentally personal trade tracking, not a shared
Discord feature at this stage, and a public page showing picks doesn't mean a public visitor
should be able to write into the owner's own trade log.

HONEST ABOUT WHAT GETS LOGGED: unlike Edge Board's own existing bet-logging flow (which prices
against REAL, live sportsbook odds and computes a real Kelly stake), none of the five pages this
widget is wired into have live odds integration. The "entry odds" logged here is the MODEL's own
fair price -- clearly labeled as such in the UI, not presented as if it were a real, live book
price. A person can still edit the odds/stake in Bet Log itself after logging, once they know
what they actually got filled at.
"""

from typing import Dict, List, Optional

STAKE_QUICK_PICKS: List[float] = [round(i * 0.5, 1) for i in range(1001)]   # 0.0, 0.5, 1.0, ...,
                                                                            # 500.0 -- covers
                                                                            # typical unit sizes
                                                                            # across a real range
                                                                            # of bankroll sizes,
                                                                            # added directly on
                                                                            # request as a quick-
                                                                            # pick dropdown that
                                                                            # still allows a free,
                                                                            # exact typed amount


def bet_log_fields_from_play(play: Dict, date_str: str, sport_key: str,
                             stake: float = 0.0) -> Dict:
    """Pure, testable mapping from a play/leg dict (the same shape produced by build_best_bets,
    organize_graded_picks, build_suggested_parlays, and build_speculative_basket across every
    sport) to the exact kwargs betlog.add_bet needs. Separated from the Streamlit UI specifically
    so this mapping itself is unit tested, not just trusted by eye in the browser -- a wrong field
    mapping here would silently corrupt real trade-log data, which is the one thing on this whole
    platform that must never be wrong.

    entry_odds is the play's own "Fair" field -- the MODEL's fair price, not a real book price
    (see this module's own docstring for why that distinction matters). model_prob and line
    default to 0.0 rather than raising if genuinely absent, since a play missing one of these
    fields should still be loggable (a person can fill in the gap in Bet Log itself) rather than
    crash the whole logging flow over one incomplete field.

    player_id comes straight from the play's own "PlayerId" (set on every play by build_best_
    bets, present all the way through every downstream function in grading.py) -- this is what
    lets a logged bet be automatically settled later: retro.py's existing, already-tested grade_
    play/get_player_results match by numeric player ID, not by name, since name matching alone
    is genuinely fragile."""
    return {
        "slate_date": date_str,
        "game": play.get("Game"),
        "player": play.get("Player"),
        "player_id": play.get("PlayerId"),
        "market": play.get("Market"),
        "side": play.get("Side"),
        "line": float(play.get("Line") or 0.0),
        "entry_odds": play.get("Fair"),
        "model_prob": float(play.get("ModelProb") or 0.0),
        "stake": float(stake or 0.0),
        "sport": sport_key,
    }


def bet_log_signature(play: Dict, date_str: str) -> tuple:
    """A real, deliberate dedup key -- the same real fields that would make two logged bets
    genuinely the same pick, not a fabricated ID. Matches Edge Board's own existing dedup
    approach (session-scoped, not database-level) exactly, so behavior is consistent across
    every page that can log to the Bet Log, not silently different depending on which page a
    person logged from."""
    return (date_str, play.get("Player"), play.get("Market"), play.get("Side"),
           float(play.get("Line") or 0.0), play.get("Fair"))


def format_play_label(play: Dict) -> str:
    """Pure, testable label for one play/leg in the quick-log picker -- pulled out of render_
    quick_log's own body specifically so this formatting logic is unit tested, not just trusted
    by eye in the browser (the same reasoning every other piece of real logic in this file
    already gets).

    A missing Player (None, not just absent) means a TEAM-LEVEL play -- a moneyline, added
    directly on request for Game Watch's own moneyline logging -- which has no player and no
    real "Line" either. Skips both pieces entirely rather than showing a confusing "? · ... —"
    placeholder for a play that was never meant to have a player in the first place."""
    fair = play.get("Fair")
    fair_str = f"{fair:+d}" if fair is not None else "—"
    player = play.get("Player")
    if player is None:
        return f"{play.get('Market', '?')} {play.get('Side', '')} @ {fair_str}"
    line = play.get("Line")
    line_str = f"{line:g}" if line is not None else "—"
    return f"{player} · {play.get('Market', '?')} {play.get('Side', '')} {line_str} @ {fair_str}"


def render_quick_log(plays: List[Dict], date_str: str, sport_key: str, key_prefix: str,
                     expanded: bool = False, is_parlay: bool = False,
                     parlay_tier: Optional[str] = None) -> None:
    """Quick-log widget supporting three independent logging modes in one action:
    - Log as parlay: all selected picks under one ticket name (linked in Bet Log)
    - Log as singles: each selected pick as its own independent bet entry
    - Both simultaneously: the real workflow -- one ticket + N straight bets at once

    is_parlay: when True, pre-selects all plays and defaults Log as parlay to ON.
    parlay_tier: used in the default ticket name (e.g. 'Game Coverage', 'Safer').
    OWNER-ONLY: renders nothing for non-owner sessions."""
    import streamlit as st

    if st.secrets.get("AUDIENCE", "owner") != "owner":
        return
    if not plays:
        return

    with st.expander("📒 Log picks to the Bet Log", expanded=expanded):
        st.caption("Logs the model's own fair price as entry odds — edit actual fill "
                  "odds/stakes in Bet Log after logging.")

        # ── Book selector ─────────────────────────────────────────────────────
        try:
            from odds_api import US_BOOKS, DEFAULT_BOOK
            _ss_book = (st.session_state.get("best_bets_book_selector")
                        or st.session_state.get("graded_picks_book_selector")
                        or st.session_state.get("speculative_basket_book_selector")
                        or st.session_state.get("suggested_parlays_book_selector"))
            _book_keys = list(US_BOOKS.keys())
            _book_labels = [US_BOOKS[k] for k in _book_keys]
            _default_label = (_ss_book if _ss_book in _book_labels
                              else US_BOOKS.get(DEFAULT_BOOK, "DraftKings"))
            _default_idx = (_book_labels.index(_default_label)
                            if _default_label in _book_labels else 0)
            book_label = st.selectbox("Book", _book_labels, index=_default_idx,
                                      key=f"{key_prefix}_ql_book")
            book = _book_keys[_book_labels.index(book_label)]
        except Exception:
            book = ""

        # ── Play selector ─────────────────────────────────────────────────────
        def _label(i: int) -> str:
            return format_play_label(plays[i])

        picks = st.multiselect(
            "Which plays are you taking?",
            list(range(len(plays))),
            format_func=_label,
            key=f"{key_prefix}_ql_picks",
            default=list(range(len(plays))) if is_parlay else [],
            help="Select the plays you want to log. Then choose below whether to log "
                 "them as a parlay, as individual straight bets, or both at once."
        )

        if not picks:
            st.caption("Select at least one play above, then choose how to log it.")
            return

        st.markdown(f"**{len(picks)} play{'s' if len(picks) != 1 else ''} selected** "
                   f"— choose how to log them:")

        # ── Mode toggles ──────────────────────────────────────────────────────
        # Independent checkboxes so the user can mix and match freely.
        # The typical workflow: both ON simultaneously → one parlay ticket +
        # N straight bets logged in one click, matching how most of the community trades.
        mc1, mc2 = st.columns(2)
        with mc1:
            log_parlay = st.checkbox(
                "🎫 Log as parlay",
                value=is_parlay,
                key=f"{key_prefix}_ql_mode_parlay",
                help="Logs all selected plays as one chained ticket in the Bet Log "
                     "(same ticket name links them). Use for the combined DraftKings slip."
            )
        with mc2:
            log_singles = st.checkbox(
                "1️⃣ Log as singles",
                value=True,
                key=f"{key_prefix}_ql_mode_singles",
                help="Logs each selected play as its own independent straight bet. "
                     "Tracks each leg individually for CLV and hit-rate purposes."
            )

        if not log_parlay and not log_singles:
            st.caption("Enable at least one logging mode above.")
            return

        # ── Parlay config (shown when parlay mode is ON) ──────────────────────
        ticket = ""
        parlay_stake = 0.0
        if log_parlay:
            st.markdown("**Parlay settings**")
            default_ticket = f'{parlay_tier or "Parlay"} {date_str}'
            ticket = st.text_input(
                "Ticket name",
                value=default_ticket,
                key=f"{key_prefix}_ql_ticket",
                help="All parlay legs logged under this name — find them grouped in "
                     "Bet Log under the ticket column."
            )
            pc1, pc2 = st.columns(2)
            with pc1:
                parlay_qp = st.selectbox(
                    "Parlay stake (quick-pick)",
                    options=STAKE_QUICK_PICKS, index=0,
                    format_func=lambda v: f"${v:,.2f}",
                    key=f"{key_prefix}_ql_p_stake_pick"
                )
            with pc2:
                parlay_stake = st.number_input(
                    "Parlay stake ($)",
                    min_value=0.0, value=parlay_qp, step=0.5,
                    key=f"{key_prefix}_ql_p_stake_{parlay_qp}"
                )

        # ── Singles config (shown when singles mode is ON) ───────────────────
        singles_stake = 0.0
        if log_singles:
            st.markdown("**Singles settings**")
            sc1, sc2 = st.columns(2)
            with sc1:
                singles_qp = st.selectbox(
                    "Per-pick stake (quick-pick)",
                    options=STAKE_QUICK_PICKS, index=0,
                    format_func=lambda v: f"${v:,.2f}",
                    key=f"{key_prefix}_ql_s_stake_pick"
                )
            with sc2:
                singles_stake = st.number_input(
                    "Stake per pick ($)",
                    min_value=0.0, value=singles_qp, step=0.5,
                    key=f"{key_prefix}_ql_s_stake_{singles_qp}"
                )

        # ── Summary before logging ────────────────────────────────────────────
        summary_parts = []
        if log_parlay:
            summary_parts.append(f"1 parlay ticket (${parlay_stake:.2f})")
        if log_singles:
            summary_parts.append(f"{len(picks)} straight bet{'s' if len(picks) != 1 else ''} "
                                 f"(${singles_stake:.2f} each)")
        if summary_parts:
            total = ((parlay_stake if log_parlay else 0)
                     + (singles_stake * len(picks) if log_singles else 0))
            st.info(f"Will log: {' + '.join(summary_parts)} = **${total:.2f} total risk**")

        # ── Log button ────────────────────────────────────────────────────────
        if st.button("Log to Bet Log", type="primary",
                     key=f"{key_prefix}_ql_btn"):
            import betlog as B
            logged_sigs = st.session_state.setdefault("logged_sigs", set())
            n_parlay = n_singles = n_skipped = 0

            if log_parlay and ticket:
                for i in picks:
                    play = plays[i]
                    fields = bet_log_fields_from_play(play, date_str, sport_key,
                                                      stake=parlay_stake)
                    fields["book"] = book
                    fields["ticket"] = ticket
                    B.add_bet(**fields)
                    n_parlay += 1

            if log_singles:
                for i in picks:
                    play = plays[i]
                    sig = bet_log_signature(play, date_str)
                    if sig in logged_sigs:
                        n_skipped += 1
                        continue
                    fields = bet_log_fields_from_play(play, date_str, sport_key,
                                                      stake=singles_stake)
                    fields["book"] = book
                    B.add_bet(**fields)
                    logged_sigs.add(sig)
                    n_singles += 1

            parts = []
            if n_parlay:
                parts.append(f"{n_parlay} parlay leg{'s' if n_parlay != 1 else ''} "
                             f"under '{ticket}'")
            if n_singles:
                parts.append(f"{n_singles} straight bet{'s' if n_singles != 1 else ''}")
            if n_skipped:
                parts.append(f"{n_skipped} already logged (skipped)")
            st.success("✅ Logged: " + " + ".join(parts) + " → Bet Log")

