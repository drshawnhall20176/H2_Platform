"""
reports.py — P&L statements from the Bet Log (Nov 6). The Reports page (views/48_Reports.py) shows them.

A statement covers any date range and reads only real-money bets (tracking bets never count), with parlays counted
once (their header row carries the money; legs carry none -- betlog.money_bets). Deposits and withdrawals come from
the Progression Plan (progression.SETTINGS_KEY "transfers"); they move the balance but are never profit.

    starting balance            plan's starting bankroll + every settled bet's P&L and every transfer before the range
  + gross winnings              profit on every bet that made money in the range (wins, profitable cash-outs)
  - gross losses                every bet that lost money in the range (stakes lost, losing cash-outs)
  = net betting result
  + deposits - withdrawals      in the range
  = ending balance

Bets are dated by their slate date (the night the game was played), the same day the Bet Log and the Progression Plan
use. The tax view keeps winnings and losses apart, the way US returns ask for them (winnings as income, losses only
as an itemized deduction, capped at winnings) -- a summary for whoever prepares the return, not tax advice.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional, Sequence

import betlog as B

SETTLED = ("win", "loss", "push", "void")


def _day(b: Dict) -> str:
    return str(b.get("slate_date") or b.get("created_at") or b.get("ts") or "")[:10]


def _real(b: Dict) -> bool:
    return b.get("is_real_bet") not in (False, 0, "0", "false", "False")


def _settled(b: Dict) -> bool:
    return B._result(b) in SETTLED or B._cashed_out_amount(b) is not None


def _kind(b: Dict) -> str:
    return "Parlay" if B.is_parlay_header(b) or B._ticket(b) else "Single"


def _strategy(b: Dict) -> str:
    try:
        import progression as P
        return P.strategy_of(b)
    except Exception:                                           # noqa: BLE001
        return "untagged"


def _block(rows: Sequence[Dict]) -> Dict:
    pnl = [B.bet_pnl(b) or 0.0 for b in rows]
    staked = sum(float(b.get("stake") or 0) for b in rows)
    won = sum(p for p in pnl if p > 0)
    lost = -sum(p for p in pnl if p < 0)
    res = [B._result(b) for b in rows]
    return {"bets": len(rows), "wins": res.count("win"), "losses": res.count("loss"),
            "pushes": res.count("push") + res.count("void"), "staked": round(staked, 2),
            "winnings": round(won, 2), "losses_amt": round(lost, 2), "net": round(won - lost, 2),
            "roi": (won - lost) / staked if staked > 0 else None}


def statement(bets: Sequence[Dict], start: str, end: str, plan: Optional[Dict] = None) -> Dict:
    """The P&L statement for slate dates start..end (inclusive, 'YYYY-MM-DD')."""
    plan = plan or {}
    plan_start = str(plan.get("start_date") or "0000-00-00")[:10]
    money = [b for b in B.money_bets([b for b in bets if _real(b)])
             if float(b.get("stake") or 0) > 0 or B.is_parlay_header(b)]
    settled = [b for b in money if _settled(b)]
    in_range = sorted([b for b in settled if start <= _day(b) <= end], key=lambda b: (_day(b), b.get("id") or 0))
    open_bets = [b for b in money if not _settled(b) and start <= _day(b) <= end]

    transfers = []
    for t in plan.get("transfers") or []:
        try:
            transfers.append({"date": str(t["date"])[:10], "amount": float(t["amount"])})
        except (KeyError, TypeError, ValueError):
            continue
    before_bets = sum(B.bet_pnl(b) or 0.0 for b in settled if plan_start <= _day(b) < start)
    before_moves = sum(t["amount"] for t in transfers if plan_start <= t["date"] < start)
    starting = float(plan.get("start_bankroll") or 0.0) + before_bets + before_moves
    moves = [t for t in transfers if start <= t["date"] <= end]
    deposits = sum(t["amount"] for t in moves if t["amount"] > 0)
    withdrawals = -sum(t["amount"] for t in moves if t["amount"] < 0)

    total = _block(in_range)

    def group(key) -> List[Dict]:
        g = defaultdict(list)
        for b in in_range:
            g[key(b)].append(b)
        return [dict(_block(rows), name=k) for k, rows in sorted(g.items(), key=lambda kv: -_block(kv[1])["net"])]

    by_month = defaultdict(list)
    for b in in_range:
        by_month[_day(b)[:7]].append(b)
    ledger = [{"date": _day(b), "sport": b.get("sport") or "", "type": _kind(b),
               "bet": _describe(b), "odds": b.get("entry_odds"), "stake": float(b.get("stake") or 0),
               "result": B._result(b) or ("cashed out" if B._cashed_out_amount(b) is not None else ""),
               "pnl": round(B.bet_pnl(b) or 0.0, 2), "strategy": _strategy(b), "book": b.get("book") or ""}
              for b in in_range]
    return {"start": start, "end": end, "starting_balance": round(starting, 2), **total,
            "deposits": round(deposits, 2), "withdrawals": round(withdrawals, 2),
            "ending_balance": round(starting + total["net"] + deposits - withdrawals, 2),
            "open": {"bets": len(open_bets), "staked": round(sum(float(b.get("stake") or 0) for b in open_bets), 2)},
            "by_sport": group(lambda b: b.get("sport") or "—"),
            "by_type": group(_kind),
            "by_strategy": group(_strategy),
            "by_month": [dict(_block(rows), name=m) for m, rows in sorted(by_month.items())],
            "transfers": moves, "ledger": ledger,
            "tax": {"winnings": total["winnings"], "losses": total["losses_amt"],
                    "deductible_cap": round(min(total["winnings"], total["losses_amt"]), 2)}}


def _describe(b: Dict) -> str:
    if B.is_parlay_header(b):
        return f"Parlay: {B._ticket(b)}"
    bits = [b.get("player") or "", b.get("market") or "", b.get("side") or ""]
    if b.get("line") not in (None, ""):
        bits.append(str(b.get("line")))
    return " ".join(x for x in bits if x).strip() or (b.get("description") or "")


def period(kind: str, today: Optional[date] = None, custom=None) -> tuple:
    """(start, end) for 'This month', 'Last month', 'This quarter', 'Year to date', 'Last year', 'All time', 'Custom'."""
    today = today or date.today()
    y, m = today.year, today.month
    if kind == "This month":
        return date(y, m, 1).isoformat(), today.isoformat()
    if kind == "Last month":
        ly, lm = (y, m - 1) if m > 1 else (y - 1, 12)
        nxt = date(y, m, 1)
        from datetime import timedelta
        return date(ly, lm, 1).isoformat(), (nxt - timedelta(days=1)).isoformat()
    if kind == "This quarter":
        return date(y, 3 * ((m - 1) // 3) + 1, 1).isoformat(), today.isoformat()
    if kind == "Year to date":
        return date(y, 1, 1).isoformat(), today.isoformat()
    if kind == "Last year":
        return date(y - 1, 1, 1).isoformat(), date(y - 1, 12, 31).isoformat()
    if kind == "Custom" and custom:
        return custom[0].isoformat(), custom[1].isoformat()
    return "0000-01-01", today.isoformat()


# --------------------------------------------------------------------------- downloads
def ledger_csv(st_: Dict) -> bytes:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "sport", "type", "bet", "odds", "stake", "result", "pnl", "strategy", "book"])
    for r in st_["ledger"]:
        w.writerow([r[k] for k in ("date", "sport", "type", "bet", "odds", "stake", "result", "pnl", "strategy", "book")])
    for t in st_["transfers"]:
        w.writerow([t["date"], "", "Deposit" if t["amount"] > 0 else "Withdrawal", "", "", "", "", t["amount"], "", ""])
    return buf.getvalue().encode("utf-8")


def _latin(s) -> str:
    return str(s).encode("latin-1", "ignore").decode("latin-1")


def statement_pdf(st_: Dict, owner: str = "H2 Sports, LLC") -> bytes:
    """A printable statement (fpdf2, built-in fonts: emoji and other non-Latin characters are dropped)."""
    from fpdf import FPDF
    pdf = FPDF(orientation="P", unit="mm", format="Letter")
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 8, _latin(f"{owner} - Betting P&L Statement"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _latin(f"Period: {st_['start']} to {st_['end']}  (real-money bets, by game date)"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    def row(label, value, bold=False):
        pdf.set_font("Helvetica", "B" if bold else "", 10)
        pdf.cell(110, 6, _latin(label))
        pdf.cell(40, 6, _latin(value), align="R", new_x="LMARGIN", new_y="NEXT")

    money = lambda x: f"${x:,.2f}" if x >= 0 else f"-${-x:,.2f}"     # noqa: E731
    row("Starting balance", money(st_["starting_balance"]), True)
    row("  Gross winnings", money(st_["winnings"]))
    row("  Gross losses", money(-st_["losses_amt"]))
    row("Net betting result", money(st_["net"]), True)
    row("  Deposits", money(st_["deposits"]))
    row("  Withdrawals", money(-st_["withdrawals"]))
    row("Ending balance", money(st_["ending_balance"]), True)
    pdf.ln(2)
    roi = "-" if st_["roi"] is None else f"{st_['roi']:+.1%}"
    row(f"Bets settled: {st_['bets']}  (W {st_['wins']} - L {st_['losses']} - P {st_['pushes']})",
        f"staked {money(st_['staked'])}")
    row("Return on money staked", roi)
    if st_["open"]["bets"]:
        row(f"Still open: {st_['open']['bets']} bet(s)", f"staked {money(st_['open']['staked'])}")

    def table(title, rows):
        if not rows:
            return
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, _latin(title), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 9)
        for h, wd in (("", 52), ("Bets", 16), ("W-L-P", 24), ("Staked", 26), ("Net", 26), ("ROI", 20)):
            pdf.cell(wd, 6, h, border="B", align="L" if not h else "R")
        pdf.ln()
        pdf.set_font("Helvetica", "", 9)
        for r in rows:
            vals = (r["name"], str(r["bets"]), f"{r['wins']}-{r['losses']}-{r['pushes']}", money(r["staked"]),
                    money(r["net"]), "-" if r["roi"] is None else f"{r['roi']:+.1%}")
            for v, wd in zip(vals, (52, 16, 24, 26, 26, 20)):
                pdf.cell(wd, 5.5, _latin(v)[:30], align="L" if wd == 52 else "R")
            pdf.ln()

    table("By sport", st_["by_sport"])
    table("By bet type", st_["by_type"])
    table("By strategy", st_["by_strategy"])
    table("By month", st_["by_month"])

    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Tax summary (for your preparer - not tax advice)", new_x="LMARGIN", new_y="NEXT")
    row("Gambling winnings (income)", money(st_["tax"]["winnings"]))
    row("Gambling losses (itemized deduction only)", money(st_["tax"]["losses"]))
    row("Deductible losses, capped at winnings", money(st_["tax"]["deductible_cap"]))

    if st_["ledger"]:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Ledger", new_x="LMARGIN", new_y="NEXT")
        cols = (("Date", 20), ("Sport", 14), ("Bet", 82), ("Odds", 14), ("Stake", 18), ("Result", 18), ("P&L", 20))
        pdf.set_font("Helvetica", "B", 8)
        for h, wd in cols:
            pdf.cell(wd, 5, h, border="B")
        pdf.ln()
        pdf.set_font("Helvetica", "", 8)
        for r in st_["ledger"]:
            odds = "" if r["odds"] in (None, "") else f"{int(float(r['odds'])):+d}"
            vals = (r["date"], r["sport"], _latin(r["bet"])[:52], odds, money(r["stake"]), r["result"], money(r["pnl"]))
            for v, (_, wd) in zip(vals, cols):
                pdf.cell(wd, 4.8, _latin(v))
            pdf.ln()
        for t in st_["transfers"]:
            pdf.cell(20, 4.8, t["date"])
            pdf.cell(14, 4.8, "")
            pdf.cell(82, 4.8, "Deposit" if t["amount"] > 0 else "Withdrawal")
            pdf.cell(70, 4.8, money(t["amount"]))
            pdf.ln()
    return bytes(pdf.output())
