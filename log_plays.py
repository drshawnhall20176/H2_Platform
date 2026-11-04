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


def _model_prob(pk, bp, reads, sport):
    """The model's chance for THIS pick's line. The board's ModelProb is for the board's own line, so it is used only
    when the lines match; an alt line ("50+") is read off the projection (parlay_check.read_leg), as the ticket checker
    does. None when there's no honest read (Nov 2 fix: alt-line bets were stored with the main line's chance)."""
    if pk.get("model_prob") is not None:
        return pk["model_prob"]
    if pk.get("line") is None:                                  # a moneyline: no line to read a chance off
        return None
    line = float(pk["line"])
    if bp.get("ModelProb") is not None and bp.get("Line") is not None and abs(float(bp["Line"]) - line) < 1e-9:
        return bp["ModelProb"]
    if reads:
        import parlay_check as PC
        r = PC.read_leg({"player": pk["player"], "market": pk["market"], "side": pk["side"], "line": line}, reads, sport)
        if (r.get("source") or "").startswith("model"):
            return round(float(r["p_raw"]), 4)
    return None


def build(picks, board_plays, sport, date_str, real=False, stake=1.0, category=None, tag=None, reads=None):
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
                    "line": None if pk.get("line") is None else float(pk["line"]), "entry_odds": float(pk["odds"]), "entry_odds_source": "book",
                    "model_prob": _model_prob(pk, bp, reads, sport), "stake": stake,
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
    ap.add_argument("--ticket", default="", help="log the picks as ONE parlay under this ticket name")
    ap.add_argument("--ticket-odds", default="", help="the parlay's total American odds")
    ap.add_argument("--result", default="", help="win / loss / push: record a result that's already known (e.g. a "
                    "settled live bet in a league the overnight grader doesn't cover) on everything logged in this run")
    ap.add_argument("--fix-model", default="false",
                    help="true = don't log; refresh the model %% on already-logged rows (singles AND ticket legs) for these picks")
    a = ap.parse_args(argv)
    raw = open(a.picks[1:]).read() if a.picks.startswith("@") else a.picks
    picks = json.loads(raw)
    date_str = a.date or datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
    try:
        board = X.board(a.sport, date_str, "draftkings")
    except Exception as exc:                                    # noqa: BLE001 -- log without IDs rather than not at all
        print(f"Couldn't load the board ({type(exc).__name__}: {exc}); logging without player IDs.")
        board = []
    try:
        import best_bets_data as BBD
        reads = BBD.load_slate_reads(a.sport, date_str, "draftkings") or {}
    except Exception as exc:                                    # noqa: BLE001 -- alt lines just go without a model %
        print(f"Couldn't load the model reads ({type(exc).__name__}: {exc}); alt lines logged without a model %.")
        reads = {}
    rows = build(picks, board, a.sport, date_str, real=a.real.lower() in ("1", "true", "yes"), stake=a.stake,
                 tag=a.tag or None, reads=reads)
    if a.fix_model.lower() in ("1", "true", "yes"):
        n = 0
        for r in rows:
            k = (r["slate_date"], _key(r["player"], r["market"], r["side"]), float(r["line"] or 0))
            for b in B.list_bets(sport=a.sport):
                if (b.get("slate_date"), _key(b.get("player"), b.get("market"), b.get("side")),
                        float(b.get("line") or 0)) == k and r["model_prob"] is not None:
                    B.update_bet(int(b["id"]), model_prob=r["model_prob"])
                    n += 1
            print(f"model % {r['player']} {r['market']} {r['side']} {r['line']}: {r['model_prob']}")
        print(f"{n} row(s) refreshed.")
        return 0
    if a.ticket:
        if any((b.get("ticket") or "") == a.ticket for b in B.list_bets(sport=a.sport)):
            print(f"Ticket '{a.ticket}' is already in the Bet Log — nothing logged.")
            return 0
        legs = [{"player": r["player"], "market": r["market"], "side": r["side"], "line": r["line"],
                 "game": r["game"], "model_prob": r["model_prob"]} for r in rows]
        res = B.log_parlay_ticket(a.ticket, legs, int(float(a.ticket_odds)), a.stake, date_str, a.sport,
                                  book=rows[0]["book"] if rows else None, notes=a.tag or None)
        if a.result.strip().lower() in ("win", "loss", "push"):
            B.update_bet(int(res["header_id"]), result=a.result.strip().lower())
            if a.result.strip().lower() == "win":                  # a won parlay means every leg won; a lost one
                for bid in res["leg_ids"]:                          # doesn't say which leg missed, so legs stay open
                    B.update_bet(int(bid), result="win")
        if a.real.lower() not in ("1", "true", "yes"):                # a tracking ticket: never counted as money
            for bid in [res["header_id"]] + list(res["leg_ids"]):
                B.update_bet(int(bid), is_real_bet=False)
        print(f"logged {'REAL' if a.real.lower() in ('1', 'true', 'yes') else 'tracking'} ticket '{a.ticket}': "
              f"{len(legs)} legs @ {int(float(a.ticket_odds)):+d}, stake {a.stake} "
              f"(header {res['header_id']})")
        return 0
    have = {(b.get("slate_date"), _key(b.get("player"), b.get("market"), b.get("side")), float(b.get("line") or 0))
            for b in B.list_bets(sport=a.sport) if not (b.get("ticket") or "")}   # singles only: a parlay
    # leg with the same player/line is a different bet, so it must not block logging the single (Nov 2 fix)
    n = 0
    for r in rows:
        k = (r["slate_date"], _key(r["player"], r["market"], r["side"]), float(r["line"] or 0))
        if k in have:
            print(f"skip (already logged): {r['player']} {r['market']} {r['side']} {r['line']}")
            continue
        bid = B.add_bet(**r)
        if a.result.strip().lower() in ("win", "loss", "push") and bid:
            B.update_bet(int(bid), result=a.result.strip().lower())
        have.add(k)
        n += 1
        print(f"logged: {r['player']} {r['market']} {r['side']} {r['line']} @ {r['entry_odds']:+.0f} "
              f"(id {'✓' if r['player_id'] else '—'}, model {r['model_prob'] if r['model_prob'] is not None else '—'})")
    print(f"{n} logged, {len(rows) - n} skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
