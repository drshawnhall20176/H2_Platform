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
CATCHER_FRAMING_PATH = os.path.join(DATA_DIR, "catcher_framing.csv")
 
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
        # ACTUAL and EXPECTED wOBA — same leaderboard row as xSLG above (Savant's expected-stats
        # export returns "actual BA, SLG, wOBA for comparison" alongside the expected versions,
        # confirmed during scoping), same column-name hedging convention already proven for xSLG
        # (pybaseball's column names have drifted between versions before; _series' multi-
        # candidate fallback is exactly the guard against that, not new to this addition).
        "woba": _series(merged, "woba", fill=0.0),
        "xwoba": _series(merged, "est_woba", "xwoba", fill=0.0),
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


# --------------------------------------------------------------------- pitcher xERA
# Added directly on request: this platform had expected-stats data for BATTERS (above) but
# nothing equivalent for PITCHERS. Mirrors the exact same architecture as the batter side --
# same pybaseball library (already a proven dependency here, not a new one), same pure/testable
# frame-builder pattern, same "Statcast is always optional, never required" load contract.
#
# ONE leaderboard here, not two merged: xERA doesn't need a separate exit-velo/barrels pull the
# way batter-side xHR-rate calibration does (see expected_hr_rate's own barrel-rate-to-HR-rate
# calibration, a batter-specific need pitchers don't have here) -- pybaseball's own
# statcast_pitcher_expected_stats() already returns actual ERA alongside xERA in one leaderboard,
# the same "actual + expected together" shape the batter-side expected-stats leaderboard already
# has (confirmed for batters during that feature's own scoping; assumed to hold for the pitcher
# sibling function by the same vendor, not independently re-confirmed).
DEFAULT_PITCHER_PATH = os.path.join(DATA_DIR, "statcast_pitchers.csv")


def _build_pitcher_statcast_frame(xs: pd.DataFrame) -> pd.DataFrame:
    """Pure, Savant-free, unit-tested -- mirrors _build_statcast_frame's own pattern exactly for
    the pitcher side. xs = pybaseball's own statcast_pitcher_expected_stats() leaderboard.

    Raises the same KeyError/ValueError shape _build_statcast_frame does on a missing id column
    or an empty result, for the same reason: a silent empty frame here would make xERA look like
    "no data for anyone" rather than surfacing the real column-name mismatch that caused it."""
    xs = xs.copy()
    xs_id = _pick(xs, "player_id", "playerid", "mlbam", "key_mlbam", "pitcher")
    if xs_id is None:
        raise KeyError(
            "player-id column not found in Savant pitcher expected-stats data (pybaseball may "
            f"have renamed it). columns: {list(xs.columns)[:10]}")
    xs["_pid"] = pd.to_numeric(xs_id, errors="coerce")
    xs = xs.dropna(subset=["_pid"])
    if xs.empty:
        raise ValueError("no valid player_id rows in pitcher expected-stats data")

    return pd.DataFrame({
        "player_id": xs["_pid"].astype(int),
        "name": _build_name(xs),
        "pa": _series(xs, "pa", fill=0),
        "era": _series(xs, "era", fill=0.0),
        "xera": _series(xs, "xera", "est_era", "x_era", fill=0.0),
        "woba": _series(xs, "woba", fill=0.0),
        "xwoba": _series(xs, "est_woba", "xwoba", fill=0.0),
    })


def refresh_pitchers(year: int, out_path: str = DEFAULT_PITCHER_PATH) -> str:
    """Pull Savant's pitcher expected-stats leaderboard via pybaseball, mirroring refresh()'s own
    pattern for the pitcher side. Run nightly, same as refresh() (a real, separate cron/manual
    step -- this does NOT run automatically inside refresh() itself, since a failure on one side
    shouldn't silently block the other).

    HONEST LIMITATION, same posture as every other Savant-shape assumption on this platform: the
    exact column names statcast_pitcher_expected_stats() returns are NOT verified against a live
    response from this sandbox (no network path to pybaseball/Savant here). _build_pitcher_
    statcast_frame's own multi-candidate _series()/_pick() lookups are the same real defense
    refresh()'s own batter-side pull already relies on for this exact risk (pybaseball's column
    names have drifted between versions before) -- but worth a real, early check of the printed
    row count the first time this actually runs somewhere with live access."""
    from pybaseball import statcast_pitcher_expected_stats

    xs = _norm_cols(statcast_pitcher_expected_stats(year))
    out = _build_pitcher_statcast_frame(xs)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"Wrote {len(out)} pitchers to {out_path}")
    return out_path


def load_pitchers(path: str = DEFAULT_PITCHER_PATH) -> Dict[int, Dict]:
    """Read the cached pitcher-xERA CSV. Returns {player_id: {...}}, or {} if the file is
    missing -- mirrors load()'s own "Statcast is always optional, never required" contract
    exactly. No calibration_k here (unlike load()'s own return) -- xERA is already on the real
    ERA scale directly, it doesn't need the barrel-rate-to-HR-rate calibration constant the
    batter side computes for a completely different purpose."""
    if not os.path.exists(path):
        return {}
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}
    if df.empty or "player_id" not in df.columns:
        return {}

    lookup: Dict[int, Dict] = {}
    for r in df.itertuples(index=False):
        d = r._asdict()
        lookup[int(d["player_id"])] = {
            "name": d.get("name"),
            "pa": float(d.get("pa", 0) or 0),
            "era": float(d.get("era", 0) or 0),
            "xera": float(d.get("xera", 0) or 0),
            "woba": float(d.get("woba", 0) or 0),
            "xwoba": float(d.get("xwoba", 0) or 0),
        }
    return lookup


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
            "woba": float(d.get("woba", 0) or 0),
            "xwoba": float(d.get("xwoba", 0) or 0),
        }
    return lookup, k
 
 
def expected_hr_rate(brl_pa: float, k: Optional[float]) -> Optional[float]:
    """Contact-implied HR per PA. Returns None if uncalibrated."""
    if k is None or brl_pa is None:
        return None
    return max(k * brl_pa, 0.0)


def build_hitter_regression_table(rows: list, statcast: Dict[int, Dict],
                                  min_pa: int = MIN_PA_QUALIFIED) -> list:
    """Actual wOBA vs. expected wOBA (quality-of-contact-implied) for the hitters on tonight's
    slate — the honest hitter counterpart to Pitching Lab's ERA-vs-FIP table. Same underlying
    idea (a results metric can be noisy/luck-affected; a quality-of-contact-based expected metric
    is a steadier read on true talent), applied to the other side of the ball.

    SIGN FLIPS RELATIVE TO ERA-VS-FIP, WORTH STATING EXPLICITLY: for a pitcher, LOWER ERA is
    better, so Delta = ERA - FIP > 0 (actual worse than deserved) is the "expect improvement"
    read. For a hitter, HIGHER wOBA is better, so here Delta = wOBA - xwOBA is inverted: a
    NEGATIVE Delta (actual wOBA below what his contact quality supports) is the "expect
    improvement" read, and a POSITIVE Delta (outperforming his contact quality) is the "expect
    regression" read. Getting this backwards would flag exactly the wrong hitters, so the Tag
    text spells out the direction in words rather than relying on a sign convention alone.

    rows: hitter rows from mlb_engine.build_slate (or any list of dicts with "Hitter"/"_pid").
    statcast: the {player_id: {...}} lookup from load() above — same object Dinger Engine already
    loads once per pageview, reused here at zero extra fetch cost, not a second Statcast pull.
    min_pa defaults to this module's own MIN_PA_QUALIFIED (the same PA floor already used to
    calibrate the barrel-rate-to-HR-rate constant elsewhere in this file) — small-PA samples
    produce noisy wOBA/xwOBA on both sides, not a real signal worth surfacing."""
    out = []
    for r in rows:
        pid = r.get("_pid")
        sc = statcast.get(pid) if pid is not None else None
        if not sc or sc.get("pa", 0) < min_pa:
            continue
        woba, xwoba = sc.get("woba", 0.0), sc.get("xwoba", 0.0)
        if woba <= 0 or xwoba <= 0:
            continue   # cache predates this field (pre-refresh), or genuinely no data — don't
                       # show a fabricated 0.000 vs 0.000 "regression candidate"
        delta = round(woba - xwoba, 3)
        if delta <= -0.020:
            tag = "🟢 Underperforming contact quality — due for positive regression"
        elif delta >= 0.020:
            tag = "🔴 Outperforming contact quality — due for negative regression"
        else:
            tag = "➡️ Results in line with contact quality"
        out.append({
            "Hitter": r.get("Hitter"), "_pid": pid, "Team": r.get("Team"),
            "PA": int(sc.get("pa", 0)), "wOBA": round(woba, 3), "xwOBA": round(xwoba, 3),
            "Delta": delta, "Tag": tag,
        })
    # Most extreme divergence first, either direction — a person scanning for "who's most out of
    # line with their real performance" wants both tails, not just one.
    out.sort(key=lambda x: abs(x["Delta"]), reverse=True)
    return out


# --------------------------------------------------------------- catcher framing
def _build_catcher_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize Savant's catcher-framing leaderboard into a compact, resilient frame.

    Pure and Savant-free so it can be unit-tested, same discipline _build_statcast_frame above
    already follows. rv_tot (Catcher Framing Runs) is confirmed directly from pybaseball's own
    statcast_catcher_framing source (used as the sortColumn in its own URL construction) — real
    confidence, not a guess. The other column names (strike rate, team, player id) are hedged
    across multiple reasonable candidates, the same resilience-to-drift pattern _series already
    uses elsewhere in this file, since they could not be confirmed with the same certainty."""
    df = _norm_cols(raw)
    pid_series = _series(df, "id", "player_id", "playerid", "mlbam", "key_mlbam", "catcher_id", fill=0)
    out = pd.DataFrame({
        "player_id": pid_series.fillna(0).astype(int),   # fillna BEFORE astype(int) — a raw NaN
                                                          # (a real possibility in Savant's own
                                                          # CSV, not just a hedge-column miss)
                                                          # would otherwise crash astype(int)
                                                          # outright, a real bug found by re-
                                                          # reading this code, not just a guess
        "name": _build_name(df),
        "team": _series(df, "team", "team_abbrev", "team_abbr", "team_name", fill="").astype(str),
        "called_pitches": _series(df, "n_called_pitches", "called_pitches", "pitches", fill=0.0),
        "strike_rate": _series(df, "pct_tot", "strike_rate", "shadow_strike_pct", "csr",
                               "zone_strike_rate", fill=0.0),
        "framing_runs": _series(df, "rv_tot", "framing_runs", "catcher_framing_runs", fill=0.0),
    })
    return out[out["player_id"] > 0].reset_index(drop=True)


def refresh_catcher_framing(year: int, out_path: str = CATCHER_FRAMING_PATH,
                            min_called_p: int = 0) -> str:
    """Pull Savant's catcher-framing leaderboard and write a compact CSV to disk. Same
    nightly-refresh architecture already proven for hitter Statcast data above — the dashboard
    reads the cached file instantly and never blocks on Savant.

    FETCHES DIRECTLY (requests + pd.read_csv) RATHER THAN CALLING pybaseball.statcast_catcher_
    framing(), a real, deliberate change made after a real failure: the pybaseball call was
    throwing "Error tokenizing data. C error: Expected 1 fields in line 38, saw 4" in production
    — a pandas C-parser error whose shape (expecting ONE field per row, then hitting a row with
    several) is the classic signature of parsing something that ISN'T a clean CSV, not a
    genuinely malformed multi-column file. The confirmed URL construction (from pybaseball's own
    source, seen during scoping) is reused as-is; what changed is HOW it's called and diagnosed:

    1. min_called_p defaults to 0 here (a real, explicit number), not pybaseball's own default
       of the STRING "q" — plausible that Savant's catcher-framing leaderboard's own `min` URL
       parameter doesn't resolve "q" the way other Savant leaderboards do, returning something
       other than the expected CSV (an error page, a different view) that only breaks pandas'
       parser partway through, matching the observed error's shape. Reasoned from the actual
       error text, not a blind guess — but still not confirmed live, stated honestly as such.
    2. A parse failure now re-raises with the first 500 characters of the RAW response body
       attached to the exception message. The tokenizing error alone didn't say WHAT Savant
       actually sent back — an HTML error page, a redirect, a genuinely different CSV shape —
       and guessing at that blind is how the wrong fix gets shipped. If min_called_p=0 doesn't
       resolve this, the next failure's own error message will show the actual content, not
       another opaque parser error.

    Returns the path written. Run nightly alongside refresh_statcast.py."""
    import io
    import requests

    url = (f"https://baseballsavant.mlb.com/leaderboard/catcher-framing"
          f"?type=catcher&seasonStart={year}&seasonEnd={year}&team="
          f"&min={min_called_p}&sortColumn=rv_tot&sortDirection=desc&csv=true")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    raw_text = resp.content.decode("utf-8", errors="replace")
    try:
        raw = pd.read_csv(io.StringIO(raw_text))
    except Exception as e:
        preview = raw_text[:500].replace("\n", "\\n")
        raise ValueError(
            f"Could not parse Savant's catcher-framing response as CSV ({type(e).__name__}: {e}). "
            f"First 500 chars of the actual response: {preview!r}"
        ) from e

    out = _build_catcher_frame(raw)
    if len(out) < 10 and len(raw) >= 10:
        # A GENUINELY DIFFERENT failure mode than the one this function's own docstring already
        # covers: the fetch and CSV parse both succeeded (raw has real rows), but almost nothing
        # survived _build_catcher_frame's own column-hedging and player_id>0 filter — the classic
        # sign that the actual column names in this response don't match ANY of the hedged
        # candidates, so every row's player_id silently defaulted to 0 and got dropped. This is
        # a SILENT data-loss mode, not a thrown exception — nothing in the try/except above would
        # have caught it, and the workflow's own "green checkmark" wouldn't reveal it either.
        # Printed here (not raised) so this doesn't turn a partially-working pull into a hard
        # failure — but the raw column names ARE the exact piece of information needed to fix
        # the real mismatch, so they're surfaced directly rather than requiring another guess.
        print(f"::warning::Catcher framing CSV parsed ({len(raw)} raw rows) but only {len(out)} "
             f"survived column mapping — likely a column-name mismatch, not a fetch failure. "
             f"Raw response columns: {list(raw.columns)}")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"Wrote {len(out)} catchers to {out_path}")
    return out_path


def load_catcher_framing(path: str = CATCHER_FRAMING_PATH) -> Dict[int, Dict]:
    """Read the cached catcher-framing CSV. Returns {player_id: {...}}, or {} if the file is
    missing — callers must treat this as optional, same posture as load() above for hitters.

    "team_id" is None (not fabricated as 0 or "") for a cache written before refresh_statcast.py's
    own team-enrichment step ran, or for a catcher who didn't resolve a team during that step —
    team_catcher_framing below correctly treats a None team_id as "can't match this row to any
    team," not a coincidental match against some real team's id of 0."""
    if not os.path.exists(path):
        return {}
    df = pd.read_csv(path)
    if df.empty:
        return {}
    lookup: Dict[int, Dict] = {}
    for r in df.itertuples(index=False):
        d = r._asdict()
        raw_team_id = d.get("team_id")
        team_id = int(raw_team_id) if pd.notna(raw_team_id) and str(raw_team_id) != "" else None
        lookup[int(d["player_id"])] = {
            "name": d.get("name"),
            "team": d.get("team"),
            "team_id": team_id,
            "called_pitches": float(d.get("called_pitches", 0) or 0),
            "strike_rate": float(d.get("strike_rate", 0) or 0),
            "framing_runs": float(d.get("framing_runs", 0) or 0),
        }
    return lookup


def team_catcher_framing(framing_lookup: Dict[int, Dict], team_id: Optional[int]) -> Optional[Dict]:
    """Team-level catcher-framing read: this team's catching corps combined, weighted by each
    catcher's own called-pitch volume — NOT tied to a specific start or a specific catcher on a
    specific date.

    MATCHES BY NUMERIC team_id, NOT TEAM NAME — a real fix after a real production bug, not a
    hypothetical concern: an earlier version matched by name, and Cleveland Guardians came back
    "no qualified catcher framing data found" despite the cache genuinely having real, enriched
    data. Team name strings in this codebase can come from DIFFERENT MLB Stats API endpoints
    (people/{id}.currentTeam.name here vs. the schedule endpoint's teams.home/away.team.name
    building pitcher["Team"] elsewhere) — two endpoints returning superficially similar strings
    is exactly the kind of thing that can silently fail a straight string comparison with no
    error, just a quiet "no data" result indistinguishable from a genuine data gap. Numeric ids
    are unambiguous across endpoints in a way display strings aren't guaranteed to be. Callers
    should pass a numeric team_id (e.g. pitcher["_team_id"] in Matchup Lab), not pitcher["Team"].

    "team_id" IS NOT SOURCED FROM SAVANT ITSELF — confirmed directly from a real response's own
    column list that Baseball Savant's catcher-framing leaderboard has no team column at all.
    This lookup's "team_id" values come from refresh_statcast.py's own team-enrichment step
    (mlb_engine.get_player_current_team, a separate MLB Stats API lookup run once per qualified
    catcher during the nightly refresh), not from anything in this module's own Savant pull. A
    cache read before that enrichment step has run will have every catcher's team_id as None,
    and this function will correctly return None for every team until it has.

    A REAL, DELIBERATE SCOPING CHOICE, not a shortcut: identifying which specific catcher caught
    a specific past start (or will catch tonight) would need the same kind of per-game boxscore
    lookup this file already does elsewhere for pitchers — but catchers rotate too, and Savant's
    leaderboard itself is already a SEASON-LONG aggregate per catcher, not a per-game one. Trying
    to tie a season-aggregate metric to one specific game would be a false precision this data
    doesn't actually support. A team-level read — "how much does this team's catching typically
    help or hurt a pitcher's real numbers" — is the honest, supportable question to ask instead.

    Returns None if team_id is falsy, or if no catchers with real called-pitch volume were found
    for this team (a team filter that matched nothing, or every candidate is a thin, unqualified
    sample) — callers should treat this as "no data," not show a fabricated average."""
    if not team_id:
        return None
    team_catchers = [c for c in framing_lookup.values()
                     if c.get("team_id") == team_id and c.get("called_pitches", 0) > 0]
    if not team_catchers:
        return None
    total_pitches = sum(c["called_pitches"] for c in team_catchers)
    if total_pitches <= 0:
        return None
    weighted_strike_rate = sum(c["strike_rate"] * c["called_pitches"] for c in team_catchers) / total_pitches
    total_framing_runs = sum(c["framing_runs"] for c in team_catchers)
    return {
        "team_id": team_id,
        "team": next((c.get("team") for c in team_catchers if c.get("team")), ""),  # display
                                                                                     # name, pulled
                                                                                     # from a
                                                                                     # matched
                                                                                     # catcher's
                                                                                     # own record
        "catchers": sorted(team_catchers, key=lambda c: c["called_pitches"], reverse=True),
        "strike_rate": round(weighted_strike_rate, 4),
        "framing_runs": round(total_framing_runs, 1),
    }
