"""research/analyst_open.py — which Analyst Record calls are still open, and why (Nov 4). Read-only."""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    import analyst_ledger as AL
    rows = AL.fetch_calls()
    voids = Counter((r["sport"], r["date"]) for r in rows if r.get("settled_at") and r.get("hit") is None)
    opened = Counter((r["sport"], r["date"]) for r in rows if not r.get("settled_at"))
    print("VOIDS (settled, no stat line):", sum(voids.values()))
    for k, v in sorted(voids.items()):
        print("  void", k, v)
    print("OPEN (never settled):", sum(opened.values()))
    for k, v in sorted(opened.items()):
        print("  open", k, v)
    print("latest call per sport:", {s: max(r["date"] for r in rows if r["sport"] == s) for s in {r["sport"] for r in rows}})
    print("calls per sport:", Counter(r["sport"] for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
