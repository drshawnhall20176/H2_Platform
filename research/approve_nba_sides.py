"""research/approve_nba_sides.py — switch on the NBA per-side honest chance from the Nov 5 held-out test (one-off)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    import model_store as MS
    why = {"source": "Nov 5 calibration audit, held-out per-side fit (research/side_calibration_test.py)",
           "evidence": "Overs said 53% hit 45% over 1,058; Unders said 55% hit 56% over 1,421"}
    print("Over:", MS.approve_calibration("NBA:Over", 0.30, why))
    print("Under:", MS.approve_calibration("NBA:Under", 0.90, why))
    print([(c["sport"], c["s"]) for c in MS.list_calibration()])
    return 0


if __name__ == "__main__":
    sys.exit(main())
