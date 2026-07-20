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
    crash the whole logging flow over one incomplete field."""
    return {
        "slate_date": date_str,
        "game": play.get("Game"),
        "player": play.get("Player"),
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


def render_quick_log(plays: List[Dict], date_str: str, sport_key: str, key_prefix: str,
                     expanded: bool = False) -> None:
    """Render a compact "log this pick" widget for a flat list of play/leg dicts -- the actual
    UI wired into Top Leans, Best Bets, Graded Picks, Suggested Parlays, and Speculative Basket.

    OWNER-ONLY: renders nothing at all for a non-owner session, regardless of whether the
    calling page itself is public -- see this module's own docstring for the full reasoning.

    key_prefix must be unique per call site (e.g. the page name, or page name + game/tier label)
    so Streamlit's own widget-key requirements don't collide when this is rendered more than
    once on the same page (e.g. once per game on Graded Picks, once per tier on Suggested
    Parlays)."""
    import streamlit as st   # lazy import -- this module's pure functions above are meant to be
                            # importable and testable without a Streamlit runtime; only this one
                            # rendering function actually needs it

    if st.secrets.get("AUDIENCE", "owner") != "owner":
        return
    if not plays:
        return

    with st.expander("📒 Log a pick to the Bet Log", expanded=expanded):
        st.caption("Logs the model's own fair price as entry odds — this page has no live "
                  "sportsbook integration. Edit the odds/stake in Bet Log after logging once "
                  "you know your real fill.")

        def _label(i: int) -> str:
            p = plays[i]
            fair = p.get("Fair")
            fair_str = f"{fair:+d}" if fair is not None else "—"
            line = p.get("Line")
            line_str = f"{line:g}" if line is not None else "—"
            return (f"{p.get('Player', '?')} · {p.get('Market', '?')} {p.get('Side', '')} "
                   f"{line_str} @ {fair_str}")

        picks = st.multiselect("Select the picks you're taking", list(range(len(plays))),
                               format_func=_label, key=f"{key_prefix}_ql_picks")
        # A real, deliberate two-widget design, not a single control: a dropdown quick-picks a
        # common unit size (0.5 increments, $0-$500, covering typical unit sizes across a real
        # range of bankroll sizes as it grows), while a SEPARATE number_input stays freely
        # editable for an exact, arbitrary amount (e.g. $37.23) the dropdown's fixed grid can't
        # represent. Re-keying the number_input on the dropdown's own current value is a real,
        # deliberate Streamlit pattern -- selecting a new quick-pick gives the number_input a
        # fresh key, so it re-initializes to that value, while still allowing free typing right
        # after, rather than the two controls fighting over which one "owns" the value.
        c_pick, c_stake = st.columns(2)
        with c_pick:
            quick_pick = st.selectbox("Quick-pick stake ($)", options=STAKE_QUICK_PICKS,
                                      index=0, format_func=lambda v: f"${v:,.2f}",
                                      key=f"{key_prefix}_ql_stake_pick")
        with c_stake:
            stake = st.number_input("Stake per pick ($) — or type an exact amount",
                                    min_value=0.0, value=quick_pick, step=0.5,
                                    key=f"{key_prefix}_ql_stake_{quick_pick}")
        if st.button("Log selected picks", type="primary", disabled=not picks,
                     key=f"{key_prefix}_ql_btn"):
            import betlog as B   # lazy for the same testability reason as the streamlit import
            logged_sigs = st.session_state.setdefault("logged_sigs", set())
            n = skipped = 0
            for i in picks:
                play = plays[i]
                sig = bet_log_signature(play, date_str)
                if sig in logged_sigs:
                    skipped += 1
                    continue
                B.add_bet(**bet_log_fields_from_play(play, date_str, sport_key, stake=stake))
                logged_sigs.add(sig)
                n += 1
            msg = f"Logged {n} pick(s) to the Bet Log — settle them there after the games."
            if skipped:
                msg += f" Skipped {skipped} already logged this session."
            st.success(msg)
