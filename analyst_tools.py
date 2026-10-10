"""
analyst_tools.py — the Analyst Desk's "alive" features, kept out of analyst.py so each stays small:

  * CLOSING-LINE TRACKING (clv_board): did the market move toward a call after it was locked? That is
    known BEFORE the game is played, so it gives the desk a learning signal long before enough results
    settle to say anything about hit rate. It is a second opinion on an angle, never a replacement for
    the graded record.
  * LOCKED-CALL STATUS (locked_status): for the day's locked calls, what the selected book is showing
    now — still posted, price moved, line moved, or pulled.
  * DISCORD (discord_picks_text / discord_recap_text / post_to_discord): the desk's calls and graded
    recap as a message, posted only when the owner presses the button.
  * ASK THE ANALYST (qa_facts / ask_analyst): free-text questions answered by the language model from
    the day's structured findings ONLY.

Nothing here edits a probability, a locked call or a result.
"""

from __future__ import annotations

import json
from typing import Callable, Dict, List, Optional

import analyst as A
import odds_api as O

# ---------------------------------------------------------------------------
# Closing-line tracking
# ---------------------------------------------------------------------------
FLAT_BAND = 0.005          # a price change smaller than half an implied-probability point is "flat"
CLV_MIN_N = 30             # moves needed before an angle is judged on them


def clv_move(r: Dict) -> Optional[Dict]:
    """How the market moved on one ledger row since it was locked, or None when it was never marked
    (or can't be compared like for like). {"kind": "line"|"price", "toward": bool|None, "move": float}.
    toward=True means the market now agrees with the call more than when it was locked: a higher line
    for an Over (the call took the lower number), a lower line for an Under, a shorter price on the
    same line. toward=None is flat."""
    if r.get("last_line") is None or r.get("line") is None:
        return None
    line, last = float(r["line"]), float(r["last_line"])
    over = r.get("side") == "Over"
    if abs(last - line) > 1e-6:
        toward = (last > line) if over else (last < line)
        return {"kind": "line", "toward": toward, "move": abs(last - line) * (1 if toward else -1)}
    if r.get("price") is None or r.get("last_price") is None:
        return None
    d = O.implied_prob(float(r["last_price"])) - O.implied_prob(float(r["price"]))
    if abs(d) < FLAT_BAND:
        return {"kind": "price", "toward": None, "move": d}
    return {"kind": "price", "toward": d > 0, "move": d}


def _clv_summary(rows: List[Dict]) -> Dict:
    moves = [m for m in (clv_move(r) for r in rows) if m is not None]
    toward = sum(1 for m in moves if m["toward"] is True)
    away = sum(1 for m in moves if m["toward"] is False)
    flat = sum(1 for m in moves if m["toward"] is None)
    n = toward + away
    lo, hi = A.wilson(toward, n)
    rate = toward / n if n else None
    if n < CLV_MIN_N:
        status = f"Collecting data ({n}/{CLV_MIN_N})"
    elif lo is not None and lo > 0.5:
        status = "Beating the close"
    elif hi is not None and hi < 0.5:
        status = "Losing to the close"
    else:
        status = "Within the noise"
    price_moves = [m["move"] for m in moves if m["kind"] == "price"]
    return {"marked": len(moves), "toward": toward, "away": away, "flat": flat, "n": n,
            "toward_rate": rate, "ci_low": lo, "ci_high": hi, "status": status,
            "avg_price_move": (sum(price_moves) / len(price_moves)) if price_moves else None}


def clv_board(rows: List[Dict]) -> List[Dict]:
    """One line per angle (plus ALL and Hidden gems) from ledger rows (settled or not) that were
    marked pre-game: how often the market moved toward the call."""
    out = [{"angle": "ALL", "label": "All published calls", **_clv_summary(rows)},
           {"angle": "gem", "label": "Hidden gems (2+ angles, not chalk)", **_clv_summary([r for r in rows if r.get("gem")])}]
    for name, (label, _d) in A.ANGLES.items():
        out.append({"angle": name, "label": label,
                    **_clv_summary([r for r in rows if name in (r.get("angles") or [])])})
    return out


# ---------------------------------------------------------------------------
# Locked-call status (today's calls vs what the book shows now)
# ---------------------------------------------------------------------------
def locked_status(rows: List[Dict], index: Dict, odds_map: Dict[str, str], book: Optional[str]) -> List[Dict]:
    """For ledger rows locked at `book`, what that book shows now. Rows locked at another book are
    skipped (their price can't be compared here)."""
    bk = O.canonical_book(book) if book else None
    out = []
    for r in rows:
        if not bk or O.canonical_book(r.get("price_book")) != bk or r.get("line") is None:
            continue
        pseudo = {"Player": r["player"], "Market": r["market"], "Side": r["side"], "Line": r["line"]}
        st = A.book_status(pseudo, index, odds_map, book)
        state, now_price = st["state"], st["price"]
        move = None
        if state == A.STATE_POSTED:
            if r.get("price") is not None and now_price is not None:
                move = (O.implied_prob(float(now_price)) - O.implied_prob(float(r["price"]))) * 100
            if move is None:
                text = f"Still posted at {now_price:+.0f}" if now_price is not None else "Still posted"
            elif abs(move) < FLAT_BAND * 100:
                text = "Unchanged"
            else:
                text = (f"Price {r['price']:+.0f} → {now_price:+.0f} ("
                        f"{'toward' if move > 0 else 'away from'} the call)")
        elif state == A.STATE_OTHER_LINE:
            text = f"Line moved — {O.book_label(bk)} now posts {', '.join(st['lines'])}"
        elif state == A.STATE_NOT_POSTED:
            text = "Pulled — no longer posted"
        else:
            text = "Can't check (no props loaded)"
        out.append({"player": r["player"], "game": r.get("game"), "market": r["market"], "side": r["side"],
                    "line": r["line"], "locked_price": r.get("price"), "state": state, "now_price": now_price,
                    "move_pts": move, "text": text, "gem": bool(r.get("gem"))})
    return out


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------
DISCORD_LIMIT = 2000
_DISCORD_HOSTS = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/",
                  "https://ptb.discord.com/api/webhooks/", "https://canary.discord.com/api/webhooks/")
DISCLAIMER = "Analysis from the model's own numbers, not a guarantee of any result."


def _fit(lines: List[str], footer: str, more_word: str) -> str:
    """Join lines under Discord's 2000-character cap, dropping the tail (and saying so)."""
    head_len = 0
    kept: List[str] = []
    for i, ln in enumerate(lines):
        remaining = len(lines) - i - 1
        tail = f"\n…and {remaining} more {more_word} on the Desk." if remaining else ""
        if head_len + len(ln) + 1 + len(tail) + len(footer) + 2 > DISCORD_LIMIT:
            dropped = len(lines) - len(kept)
            return "\n".join(kept) + f"\n…and {dropped} more {more_word} on the Desk.\n\n{footer}"
        kept.append(ln)
        head_len += len(ln) + 1
    return "\n".join(kept) + "\n\n" + footer


def discord_picks_text(calls: List[Dict], *, sport_label: str, date_str: str, book_label: str,
                       max_calls: int = 8) -> str:
    """The desk's suggestions as a Discord message. `calls` must already be the bettable ones; gems
    lead, then the strongest. Empty string when there is nothing to post."""
    if not calls:
        return ""
    ordered = sorted(calls, key=lambda c: (c.get("gem", False), c.get("score", 0)), reverse=True)[:max_calls]
    lines = [f"🎙️ **H2 Analyst Desk — {sport_label}, {date_str}**",
             f"Lines are from {book_label} at the time of posting. Each call is locked to the public record before kickoff."]
    for c in ordered:
        price = f" at {c['price']:+.0f}" if c.get("price") is not None else ""
        when = f" · {c['kickoff']}" if c.get("kickoff") and c["kickoff"] != "time TBD" else ""
        angles = ", ".join(a["label"] for a in c.get("angles", []))
        lines.append(f"{'💎' if c.get('gem') else '•'} **{A.describe_call(c)}**{price}{when} — {angles}")
    return _fit(lines, DISCLAIMER, "plays")


def discord_recap_text(rows: List[Dict], *, sport_label: str, date_str: str,
                       board: Optional[List[Dict]] = None) -> str:
    """The graded results for one day's locked calls (ledger rows for that day). Empty string when none
    of them has been graded yet."""
    graded = [r for r in rows if r.get("settled_at")]
    if not graded:
        return ""
    hits = [r for r in graded if r.get("hit") == 1]
    misses = [r for r in graded if r.get("hit") == 0]
    voids = [r for r in graded if r.get("hit") is None]
    lines = [f"🧾 **H2 Analyst Desk recap — {sport_label}, {date_str}**",
             f"{len(hits)}-{len(misses)}" + (f" ({len(voids)} void — didn't play)" if voids else "") + " on the day's locked calls."]
    for r in hits + misses:
        mark = "✅" if r.get("hit") == 1 else "❌"
        act = f" (actual {r['actual']:g})" if r.get("actual") is not None else ""
        ln = f"{r['side']} {r['line']:g} {r['market']}" if r.get("line") is not None else f"{r['side']} {r['market']}"
        lines.append(f"{mark} {r['player']} {ln}{act}")
    if board:
        al = next((b for b in board if b["angle"] == "ALL" and b["n"]), None)
        if al:
            lines.append(f"Record so far: {al['hits']}-{al['n'] - al['hits']} ({al['hit_rate']:.0%}); the model said "
                         f"{al['mean_prob']:.0%} on average — {al['status'].lower()}.")
    return _fit(lines, DISCLAIMER, "results")


def post_to_discord(webhook_url: Optional[str], text: str, post: Optional[Callable] = None, timeout: int = 15) -> None:
    """POST `text` to a Discord webhook. Raises RuntimeError with a plain reason on any problem. Mentions
    are disabled so a play or player name can never ping anyone."""
    if not webhook_url or not webhook_url.startswith(_DISCORD_HOSTS):
        raise RuntimeError("no Discord webhook is configured (add DISCORD_WEBHOOK_URL to the app secrets — "
                           "it must be a discord.com webhook link)")
    if not text.strip():
        raise RuntimeError("there is nothing to post")
    if post is None:
        import requests
        post = requests.post
    try:
        resp = post(webhook_url, json={"content": text[:DISCORD_LIMIT], "allowed_mentions": {"parse": []}},
                    timeout=timeout)
    except Exception as exc:                                        # noqa: BLE001
        raise RuntimeError(f"could not reach Discord ({type(exc).__name__}: {str(exc)[:100]})") from exc
    status = getattr(resp, "status_code", 0)
    if status not in (200, 204):
        raise RuntimeError(f"Discord answered {status}" + (" — the webhook link may have been deleted" if status in (401, 404) else ""))


# ---------------------------------------------------------------------------
# Ask the Analyst
# ---------------------------------------------------------------------------
ASK_SYSTEM = (
    "You are the on-air analyst for H2 Sports answering a question from the owner about today's slate. "
    "HARD RULES: answer ONLY from the JSON facts you are given — never add a stat, injury, news item, odds "
    "figure or storyline that is not in them, and keep every number exactly as given. If the facts don't "
    "contain the answer, say the desk doesn't have it. Every play in `plays` is posted at the sportsbook "
    "named in the JSON at exactly its stated line; plays in `not_at_book` are NOT available there, so "
    "never suggest them as bets (you may say where else they are posted). Never promise or guarantee an "
    "outcome and never tell anyone how much to bet. Be concise: a few sentences, a short list only if asked. "
    "Plain markdown, no tables."
)
ASK_MAX_QUESTION = 500
ASK_MAX_PLAYS = 60


def qa_facts(calls: List[Dict], *, sport_label: str, date_str: str, book_label: str, coverage_note: str = "",
             board: Optional[List[Dict]] = None, clv: Optional[List[Dict]] = None) -> Dict:
    """Everything the Q&A model may use, JSON-able. Bettable plays and not-at-book plays are kept
    apart so the model can't blur them."""
    def row(c):
        return {"game": c.get("game"), "kickoff": c.get("kickoff"), "play": A.describe_call(c), "team": c.get("team"),
                "gem": c.get("gem"), "chalk": c.get("chalk"), "angles": [a["evidence"] for a in c.get("angles", [])],
                "cautions": c.get("cautions"), "book_price": c.get("price")}
    ok = [c for c in calls if c.get("bettable")]
    off = [c for c in calls if not c.get("bettable")]
    facts: Dict = {"sport": sport_label, "date": date_str, "sportsbook": book_label,
                   "plays": [row(c) for c in ok[:ASK_MAX_PLAYS]],
                   "not_at_book": [{"play": A.describe_call(c), "game": c.get("game"),
                                    "status": A.status_text(c, book_label)} for c in off[:ASK_MAX_PLAYS]]}
    if coverage_note:
        facts["props_posted"] = coverage_note
    if board:
        facts["track_record"] = [{"angle": r["label"], "graded": r["n"],
                                  "hit_rate": None if r["hit_rate"] is None else round(r["hit_rate"], 3),
                                  "avg_stated_chance": None if r["mean_prob"] is None else round(r["mean_prob"], 3),
                                  "status": r["status"]} for r in board if r["n"]][:8]
    if clv:
        facts["market_moves"] = [{"angle": r["label"], "marked": r["marked"], "toward_rate":
                                  None if r["toward_rate"] is None else round(r["toward_rate"], 3),
                                  "status": r["status"]} for r in clv if r["marked"]][:8]
    return facts


def ask_analyst(question: str, facts: Dict, api_key: Optional[str], model: Optional[str] = None,
                history: Optional[List[Dict]] = None, post: Optional[Callable] = None) -> str:
    """One answer. Raises RuntimeError with a plain reason on any failure (the page shows it)."""
    q = (question or "").strip()
    if not q:
        raise RuntimeError("type a question first")
    payload = {"question": q[:ASK_MAX_QUESTION], "facts": facts}
    if history:
        payload["earlier_in_this_chat"] = [{"q": h["q"], "a": h["a"][:600]} for h in history[-3:]]
    return A.llm_commentary(payload, api_key or "", model, post=post, system=ASK_SYSTEM, max_tokens=700)
