"""
log_plays.py — log a list of picks to the Bet Log without a browser (Nov 1). Run by the log-plays workflow.

Input: JSON list of {"player", "market", "side", "line", "odds", "game", "model_prob"?, "note"?}. Each pick is matched to
today's board (export_board.board) for its player ID (so overnight settlement can grade it) and model %; a pick
already in the Bet Log (same date, player, market, side, line) is skipped, so re-running is safe.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

import pytz


def _key(player, market, side):
    import ufc_review as U
    return (U.norm(player), str(market).strip().lower(), str(side).strip().lower())


def build(picks, board_plays, sport, date_str, real=False, stake=1.0, category=None, tag=None):
    import betlog as B
    by = {_key(p["Player"], p["Market"], p["Side"]): p for p in board_plays}
    out = []
    for pk in picks:
        bp = by.get(_key(pk["player"], pk["market"], pk["side"])) or {}
        pid = bp.get("PlayerId")
        try:
            pid = int(pid) if pid is not None else None
        except (TypeError, ValueError):
            pid = None
        notes = ",".join(x for x in ([tag] if tag else []) + ([pk["note"]] if pk.get("note") else [])
                         + ([bp["Notes"]] if bp.get("Notes") else []) if x) or None
        out.append({"slate_date": date_str, "sport": sport, "game": pk.get("game") or bp.get("Game"),
                    "player": pk["player"], "player_id": pid, "market": pk["market"], "side": pk["side"],
                    "line": float(pk["line"]), "entry_odds": float(pk["odds"]), "entry_odds_source": "book",
                    "model_prob": pk.get("model_prob") or bp.get("ModelProb"), "stake": stake,
                    "book": pk.get("book", "draftkings"), "is_real_bet": bool(real),
                    "category": category or B.default_category(sport, from_model=True), "notes": notes})
    return out


def main(argv=None) -> int:
    import betlog as B
    import export_board as X
    ap = argparse.ArgumentParser()
    ap.add_argument("--picks", required=True, help="JSON list, or @file")
    ap.add_argument("--sport", default="NFL")
    ap.add_argument("--date", default="")
    ap.add_argument("--real", default="false")
    ap.add_argument("--stake", type=float, default=1.0)
    ap.add_argument("--tag", default="")
    a = ap.parse_args(argv)
    raw = open(a.picks[1:]).read() if a.picks.startswith("@") else a.picks
    picks = json.loads(raw)
    date_str = a.date or datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
    try:
        board = X.board(a.sport, date_str, "draftkings")
    except Exception as exc:                                    # noqa: BLE001 -- log without IDs rather than not at all
        print(f"Couldn't load the board ({type(exc).__name__}: {exc}); logging without player IDs.")
        board = []
    rows = build(picks, board, a.sport, date_str, real=a.real.lower() in ("1", "true", "yes"), stake=a.stake,
                 tag=a.tag or None)
    have = {(b.get("slate_date"), _key(b.get("player"), b.get("market"), b.get("side")), float(b.get("line") or 0))
            for b in B.list_bets(sport=a.sport)}
    n = 0
    for r in rows:
        k = (r["slate_date"], _key(r["player"], r["market"], r["side"]), r["line"])
        if k in have:
            print(f"skip (already logged): {r['player']} {r['market']} {r['side']} {r['line']}")
            continue
        B.add_bet(**r)
        have.add(k)
        n += 1
        print(f"logged: {r['player']} {r['market']} {r['side']} {r['line']} @ {r['entry_odds']:+.0f} "
              f"(id {'✓' if r['player_id'] else '—'}, model {r['model_prob'] if r['model_prob'] is not None else '—'})")
    print(f"{n} logged, {len(rows) - n} skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
