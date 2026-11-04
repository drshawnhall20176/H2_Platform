"""research/fill_player_ids.py — give today's NBA bets without a player ID the ID from the saved slate (exact name
match only, one player per name), so overnight settlement can grade them (Nov 4)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    import betlog as B
    import sports
    import ufc_review as U
    day = os.environ.get("DAY", "2026-11-04")
    rows, _meta = sports.get("NBA").engine.build_slate(day)
    ids = {}
    for r in rows:
        pid = r.get("_player_id") or r.get("PlayerId") or r.get("player_id") or r.get("id")
        if pid is not None:
            ids.setdefault(U.norm(r.get("Player")), set()).add(int(pid))
    print("sample row keys:", sorted(rows[0].keys())[:40] if rows else None)
    n = 0
    for b in B.list_bets(sport="NBA"):
        if b.get("slate_date") != day or b.get("player_id") is not None or b.get("ticket"):
            continue
        got = ids.get(U.norm(b.get("player")))
        if got and len(got) == 1:
            B.update_bet(int(b["id"]), player_id=next(iter(got)))
            n += 1
            print(f"#{b['id']} {b['player']} -> {next(iter(got))}")
        else:
            print(f"#{b['id']} {b['player']}: no single match ({got})")
    print(f"{n} filled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
