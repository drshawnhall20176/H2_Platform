"""
statcast_data.py — Statcast expected-power layer for the Dinger Engine.
 
WHY: a hitter's actual HR count is noisy and luck-contaminated. His quality of contact
(barrel rate, exit velocity) is far more stable and predicts FUTURE power better. So a
hitter crushing the ball with a cold HR count is a positive-regression dinger bet the
market may be slow to price — the "buy the dip" logic, pointed at bats.
 
ARCHITECTURE: Savant pulls are slow/heavy, so we cache to disk nightly and the dashboard
reads the file instantly. Run `python refresh_statcast.py` (or statcast_data.refresh())
once a day; the app uses the last good file and never blocks on Savant.
 
This module imports pybaseball ONLY inside refresh(), so the dashboard can import and run
even if pybaseball isn't installed or Savant is unreachable — load() just returns empty
and projections fall back to the league prior. Nothing breaks without Statcast.
"""
 
from __future__ import annotations
 
import os
from typing import Dict, Optional, Tuple
 
import pandas as pd
 
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DEFAULT_PATH = os.path.join(DATA_DIR, "statcast_batters.csv")
 
LG_HR_PA = 0.033          # league HR per PA, the anchor for calibration
MIN_PA_QUALIFIED = 100    # PA floor for computing the league barrel->HR calibration
 
 
# --------------------------------------------------------------------- refresh
def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df
 
 
def _pick(df: pd.DataFrame, *candidates):
    """First matching column (already normalized to lowercase) as a Series, or None."""
    for c in candidates:
        if c in df.columns:
            return df[c]
    return None
 
 
def _series(df: pd.DataFrame, *candidates, fill=0.0):
    """Like _pick, but always a Series aligned to df (filled with `fill` if none match).
    This is what makes us safe against column-name drift: a missing column becomes a
    fill-value Series instead of crashing when Series methods are called on it."""
    s = _pick(df, *candidates)
    return s if s is not None else pd.Series(fill, index=df.index)
 
 
def _build_name(df: pd.DataFrame) -> pd.Series:
    """Player display name across pybaseball layouts: a combined 'last_name, first_name'
    column (flip to 'First Last'), OR separate first/last columns, OR a player_name column."""
    combined = _pick(df, "last_name, first_name", "name", "player_name", "name_xs")
    if combined is not None:
        def flip(v):
            v = str(v).strip()
            if "," in v:
                last, first = (p.strip() for p in v.split(",", 1))
                return f"{first} {last}".strip()
            return v
        return combined.map(flip)
    first = _pick(df, "first_name")
    last = _pick(df, "last_name")
    f = (first if first is not None else pd.Series("", index=df.index)).astype(str).str.strip()
    l = (last if last is not None else pd.Series("", index=df.index)).astype(str).str.strip()
    return (f + " " + l).str.strip()
 
 
def _build_statcast_frame(ev: pd.DataFrame, xs: pd.DataFrame) -> pd.DataFrame:
    """Merge the two (already lowercase-normalized) Savant leaderboards into our compact
    schema. Pure and Savant-free so it can be unit-tested; resilient to column renames.
 
    ev = exit-velo/barrels leaderboard, xs = expected-stats leaderboard."""
    ev = ev.copy()
    xs = xs.copy()
    ev_id = _pick(ev, "player_id", "playerid", "mlbam", "key_mlbam", "batter")
    xs_id = _pick(xs, "player_id", "playerid", "mlbam", "key_mlbam", "batter")
    if ev_id is None or xs_id is None:
        raise KeyError(
            "player-id column not found in Savant data (pybaseball may have renamed it). "
            f"exit-velo cols: {list(ev.columns)[:10]}; expected-stats cols: {list(xs.columns)[:10]}")
    ev["_pid"] = pd.to_numeric(ev_id, errors="coerce")
    xs["_pid"] = pd.to_numeric(xs_id, errors="coerce")
    ev = ev.dropna(subset=["_pid"])
    xs = xs.dropna(subset=["_pid"])
 
    merged = pd.merge(ev, xs, on="_pid", how="inner", suffixes=("", "_xs"))
    if merged.empty:
        raise ValueError("merge of exit-velo and expected-stats produced 0 rows")
 
    out = pd.DataFrame({
        "player_id": merged["_pid"].astype(int),
        "name": _build_name(merged),
        "pa": _series(merged, "pa", fill=0),
        "brl_pa": _series(merged, "brl_pa", fill=0.0),
        "brl_pct": _series(merged, "brl_pct", "brl_percent", fill=0.0),
        "hardhit": _series(merged, "hardhit", "ev95percent", "ev95plus_percent", fill=0.0),
        "avg_ev": _series(merged, "avg_ev", "avg_hit_speed", fill=0.0),
        "slg": _series(merged, "slg", fill=0.0),
        "xslg": _series(merged, "est_slg", "xslg", fill=0.0),
        "xiso": _series(merged, "est_slg", "xslg", fill=0.0) - _series(merged, "est_ba", "xba", fill=0.0),
    })
    return out
 
 
def refresh(year: int, out_path: str = DEFAULT_PATH) -> str:
    """Pull Savant leaderboards via pybaseball, merge, and write a compact CSV to disk.
 
    Returns the path written. Run nightly. Column names occasionally drift between
    pybaseball versions, so the merge/parse is done in _build_statcast_frame, which is
    resilient to renames and unit-tested. Verify the printed row count looks right.
    """
    from pybaseball import statcast_batter_exitvelo_barrels, statcast_batter_expected_stats
 
    ev = _norm_cols(statcast_batter_exitvelo_barrels(year))      # barrels / exit velo
    xs = _norm_cols(statcast_batter_expected_stats(year))        # xBA / xSLG / xwOBA
    out = _build_statcast_frame(ev, xs)
 
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"Wrote {len(out)} batters to {out_path}")
    return out_path
 
 
# ---------------------------------------------------------------------- load
def load(path: str = DEFAULT_PATH) -> Tuple[Dict[int, Dict], Optional[float]]:
    """Read the cached CSV. Returns (lookup_by_player_id, calibration_k).
 
    Returns ({}, None) if the file is missing — callers must treat Statcast as optional.
    calibration_k maps barrel rate to expected HR rate: xHR/PA = k * brl_pa, with k chosen
    so the league-average barrel rate maps to league-average HR rate."""
    if not os.path.exists(path):
        return {}, None
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}, None
    if df.empty or "player_id" not in df.columns or "brl_pa" not in df.columns:
        return {}, None
 
    # pybaseball returns barrel% / hard-hit% as PERCENT numbers (e.g. 11.2), but the app treats
    # these as fractions for "{:.1%}" display — which renders 11.2 as "1120%". Normalize any rate
    # column that's in percent form back to a fraction. Idempotent: a column already in fraction
    # form (values < 1) is left untouched, so this is safe for old and new caches alike. Calibration
    # self-corrects (k is derived from these same values), so xHR/PA and Due are unchanged.
    for c in ("brl_pct", "hardhit", "brl_pa"):
        if c in df.columns:
            pos = df[c][df[c] > 0]
            if len(pos) and float(pos.median()) > 1.0:
                df[c] = df[c] / 100.0
 
    qualified = df[df.get("pa", 0) >= MIN_PA_QUALIFIED]
    base = qualified if len(qualified) else df
    mean_brl = float(base["brl_pa"].mean()) if len(base) else 0.0
    k = (LG_HR_PA / mean_brl) if mean_brl > 0 else None
 
    lookup: Dict[int, Dict] = {}
    for r in df.itertuples(index=False):
        d = r._asdict()
        lookup[int(d["player_id"])] = {
            "name": d.get("name"),
            "pa": float(d.get("pa", 0) or 0),
            "brl_pa": float(d.get("brl_pa", 0) or 0),
            "brl_pct": float(d.get("brl_pct", 0) or 0),
            "hardhit": float(d.get("hardhit", 0) or 0),
            "avg_ev": float(d.get("avg_ev", 0) or 0),
            "xiso": float(d.get("xiso", 0) or 0),
            "slg": float(d.get("slg", 0) or 0),
            "xslg": float(d.get("xslg", 0) or 0),
        }
    return lookup, k
 
 
def expected_hr_rate(brl_pa: float, k: Optional[float]) -> Optional[float]:
    """Contact-implied HR per PA. Returns None if uncalibrated."""
    if k is None or brl_pa is None:
        return None
    return max(k * brl_pa, 0.0)
