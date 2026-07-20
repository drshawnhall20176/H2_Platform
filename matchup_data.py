"""
matchup_data.py — pitch-level "arsenal vs. vulnerability" layer for the Matchup Lab.

WHY: season rate stats tell you a hitter is good or bad overall; pitch-level data tells you
*how* to get him out — which pitch types he whiffs on and which he punishes. Pairing a pitcher's
arsenal (what he throws, how much he misses bats with it) against a hitter's per-pitch-family
performance surfaces the specific pitches to attack with. That's the edge behind pitch-level props.

ARCHITECTURE (mirrors statcast_data.py): pitch-level Savant pulls are enormous and slow, so a
nightly job (refresh_matchups.py / a GitHub Action) pulls a full season, aggregates into two
compact tables, and writes them to data/. The dashboard reads those instantly and never blocks
on Savant. pybaseball is imported ONLY inside refresh(), so the app runs fine without it.

DESIGN CHOICES:
  * Pitcher arsenal is aggregated by SPECIFIC pitch type (FF, SL, CH ...) — that's his repertoire.
  * Hitter performance is aggregated by pitch FAMILY (Fastball / Breaking / Offspeed) — a single
    pitch type is often too thin per hitter to trust; families stabilize the sample.
  * The matchup score is a TRANSPARENT scouting heuristic (see matchup_score), NOT a probability.

Pure NumPy/pandas. The aggregation functions take a plain pitch DataFrame so they can be unit
tested with mock data shaped like real Statcast, without touching the network.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ARSENAL_PATH = os.path.join(DATA_DIR, "pitcher_arsenals.csv")
HITTER_PATH = os.path.join(DATA_DIR, "hitter_pitch_splits.csv")
HITTER_TYPE_PATH = os.path.join(DATA_DIR, "hitter_pitch_type_splits.csv")

# Minimum pitches to trust an aggregate (below this, a rate is too noisy to show without a caveat).
MIN_PITCHES_ARSENAL = 30       # a pitch is "in the arsenal" only if thrown at least this often
MIN_PITCHES_FAMILY = 40        # a hitter's vs-family rate needs at least this many pitches
MIN_PITCHES_TYPE = 25          # a hitter's vs-specific-pitch rate (noisier) floor to appear at all

# Map Statcast pitch_type codes to families. Unlisted codes -> "Other".
PITCH_FAMILY = {
    "FF": "Fastball", "FA": "Fastball", "SI": "Fastball", "FT": "Fastball", "FC": "Fastball",
    "SL": "Breaking", "CU": "Breaking", "KC": "Breaking", "ST": "Breaking", "SV": "Breaking",
    "CS": "Breaking", "SC": "Breaking", "KN": "Breaking",
    "CH": "Offspeed", "FS": "Offspeed", "FO": "Offspeed",
}
# Human-readable names for the common codes (for display).
PITCH_NAME = {
    "FF": "4-Seam FB", "FA": "Fastball", "SI": "Sinker", "FT": "2-Seam FB", "FC": "Cutter",
    "SL": "Slider", "CU": "Curveball", "KC": "Knuckle-Curve", "ST": "Sweeper", "SV": "Slurve",
    "CH": "Changeup", "FS": "Splitter", "FO": "Forkball", "KN": "Knuckleball",
}

FAMILIES = ["Fastball", "Breaking", "Offspeed"]

# Statcast `description` values that count as a swing, and the subset that are whiffs.
_SWING_DESCS = {"swinging_strike", "swinging_strike_blocked", "foul", "foul_tip",
                "hit_into_play", "foul_bunt", "missed_bunt", "bunt_foul_tip"}
_WHIFF_DESCS = {"swinging_strike", "swinging_strike_blocked", "foul_tip", "missed_bunt",
                "bunt_foul_tip"}
# Total bases by `events` value, for SLG-against.
_TB_BY_EVENT = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
# `events` values that count as an at-bat (excludes walks, HBP, sac, etc.).
_AB_EVENTS = {"single", "double", "triple", "home_run", "field_out", "strikeout",
              "grounded_into_double_play", "force_out", "double_play", "field_error",
              "fielders_choice", "fielders_choice_out", "strikeout_double_play",
              "triple_play", "sac_fly_double_play"}


# --------------------------------------------------------------------- helpers
def _col(df: pd.DataFrame, *names, fill=np.nan) -> pd.Series:
    """First matching column as a Series, else a fill-value Series (drift-safe)."""
    for n in names:
        if n in df.columns:
            return df[n]
    return pd.Series(fill, index=df.index)


def _swing_whiff(desc: pd.Series) -> Tuple[pd.Series, pd.Series]:
    """(is_swing, is_whiff) boolean Series from a `description` column."""
    d = desc.astype("string").fillna("")
    return d.isin(_SWING_DESCS), d.isin(_WHIFF_DESCS)


def _none_safe_float(raw) -> Optional[float]:
    """None on an older cached CSV that predates a given field entirely (the key is simply
    absent from this row's dict), NaN once the column exists but this specific row has no real
    value for it (e.g. no batted-ball sample for exit_velo). Both cases surface as Python None
    to the caller, never a fabricated 0.0 -- shared by every load() path below (pitcher arsenal,
    hitter family splits, hitter pitch-type splits) for zone_pct/contact_pct/exit_velo alike, a
    REAL, CONFIRMED FIX after a real, live bug: a fabricated 0.0 doesn't just look wrong, it
    actively misleads once styled (a 0% contact rate reads as excellent for the pitcher under
    the reversed colormap, the exact opposite of "no data")."""
    return None if raw is None or pd.isna(raw) else float(raw)


# --------------------------------------------------------------------- pitcher arsenal
def build_pitcher_arsenal(pitches: pd.DataFrame) -> pd.DataFrame:
    """One row per (pitcher, pitch_type): usage%, whiff%, put-away%, avg velo, zone%, contact%,
    avg exit velo, count.

    `pitches` is raw pitch-level Statcast (many pitchers OK). Pure — no network.

    zone/contact/exit-velo added directly on request -- all three already live in the SAME raw
    Statcast pull this function already consumes (Statcast's own `zone` code, the `description`
    classification already used for whiff, and `launch_speed`), so this is a real extension of
    an existing aggregation, not a new data source.

    zone%: fraction of ALL pitches (not just swings) Statcast's own `zone` field placed inside
    the strike zone -- Statcast codes 1-9 for the 9 in-zone regions, 11-14 for the 4 out-of-zone
    regions, so zone% = share of pitches with zone in 1..9. A command/approach metric, distinct
    from whiff% (which only asks what happens once a hitter swings).

    contact%: the complement of whiff% on the SAME swing/whiff classification already used
    (1 - whiff, not a separately-defined FanGraphs-style metric), so it stays internally
    consistent with the whiff% number already shown right next to it rather than quietly
    using a different definition of "swing."

    avg exit velo: mean `launch_speed` on balls actually put in play against this specific pitch
    type -- the direct, real quality-of-contact number when a hitter DOES connect, complementing
    whiff%/contact% (which only describe whether contact happened, not how hard). NaN (not 0.0)
    when a pitch type has no batted-ball sample at all -- a real, honest "not enough data" state,
    not a fabricated "zero exit velocity.\""""
    if pitches is None or len(pitches) == 0:
        return pd.DataFrame(columns=["pitcher", "pitch_type", "pitch_name", "family",
                                     "pitches", "usage", "whiff", "putaway", "velo",
                                     "zone_pct", "contact_pct", "exit_velo"])
    df = pitches.copy()
    df["_pid"] = pd.to_numeric(_col(df, "pitcher"), errors="coerce")
    df["_ptype"] = _col(df, "pitch_type").astype("string").fillna("")
    df = df.dropna(subset=["_pid"])
    df = df[df["_ptype"] != ""]
    swing, whiff = _swing_whiff(_col(df, "description"))
    df["_swing"] = swing.values
    df["_whiff"] = whiff.values
    df["_velo"] = pd.to_numeric(_col(df, "release_speed"), errors="coerce")
    strikes = pd.to_numeric(_col(df, "strikes"), errors="coerce").fillna(0)
    df["_two_strk"] = (strikes >= 2).values
    zone_code = pd.to_numeric(_col(df, "zone"), errors="coerce")
    df["_in_zone"] = zone_code.between(1, 9)   # Statcast's own 9 in-zone region codes
    df["_exit_velo"] = pd.to_numeric(_col(df, "launch_speed"), errors="coerce")

    total_by_pitcher = df.groupby("_pid").size().rename("_tot")
    rows = []
    for (pid, ptype), g in df.groupby(["_pid", "_ptype"]):
        n = len(g)
        if n < MIN_PITCHES_ARSENAL:
            continue
        swings = int(g["_swing"].sum())
        whiffs = int(g["_whiff"].sum())
        two_strk = g[g["_two_strk"]]
        two_swings = int(two_strk["_swing"].sum())
        two_whiffs = int(two_strk["_whiff"].sum())
        ev_series = g["_exit_velo"]
        rows.append({
            "pitcher": int(pid),
            "pitch_type": ptype,
            "pitch_name": PITCH_NAME.get(ptype, ptype),
            "family": PITCH_FAMILY.get(ptype, "Other"),
            "pitches": n,
            "usage": n / float(total_by_pitcher.loc[pid]),
            "whiff": (whiffs / swings) if swings else 0.0,          # whiff per swing
            "putaway": (two_whiffs / two_swings) if two_swings else 0.0,  # 2-strike whiff/swing
            "velo": float(np.nanmean(g["_velo"])) if g["_velo"].notna().any() else 0.0,
            "zone_pct": float(g["_in_zone"].sum()) / n,
            "contact_pct": (1.0 - whiffs / swings) if swings else 0.0,
            "exit_velo": float(np.nanmean(ev_series)) if ev_series.notna().any() else float("nan"),
        })
    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values(["pitcher", "usage"], ascending=[True, False])
    return out


# --------------------------------------------------------------------- hitter splits
def build_hitter_splits(pitches: pd.DataFrame) -> pd.DataFrame:
    """One row per (batter, family): whiff%, contact%, SLG-against, xwOBA-against, exit velo
    (the HITTER'S OWN average exit velocity when he puts this family in play), count.

    Aggregated by pitch family (Fastball/Breaking/Offspeed) for a stable per-hitter sample.

    contact_pct/exit_velo added directly on request, mirroring the pitcher-side arsenal
    extension exactly -- contact_pct is the real complement of whiff% already computed here
    (1 - whiff, same swing/whiff classification, not a separately-defined metric), and exit_velo
    is this hitter's own real quality-of-contact number against this family, distinct from SLG/
    xwOBA (which are outcome-based) and distinct from the PITCHER's own exit-velo-allowed number
    on the arsenal table (this is what happens when THIS hitter specifically connects, not the
    pitcher's own season-long average against everyone). NaN (not a fabricated 0.0) when this
    hitter has no real batted-ball sample against this family -- an honest "not enough data"
    state, not a fabricated "zero exit velocity.\""""
    cols = ["batter", "family", "pitches", "whiff", "contact", "slg", "xwoba", "exit_velo"]
    if pitches is None or len(pitches) == 0:
        return pd.DataFrame(columns=cols)
    df = pitches.copy()
    df["_bid"] = pd.to_numeric(_col(df, "batter"), errors="coerce")
    ptype = _col(df, "pitch_type").astype("string").fillna("")
    df["_family"] = ptype.map(PITCH_FAMILY).fillna("Other")
    df = df.dropna(subset=["_bid"])
    df = df[df["_family"].isin(FAMILIES)]
    swing, whiff = _swing_whiff(_col(df, "description"))
    df["_swing"] = swing.values
    df["_whiff"] = whiff.values
    events = _col(df, "events").astype("string").fillna("")
    df["_tb"] = events.map(_TB_BY_EVENT).fillna(0).astype(float).values
    df["_ab"] = events.isin(_AB_EVENTS).values
    df["_xwoba"] = pd.to_numeric(_col(df, "estimated_woba_using_speedangle"), errors="coerce")
    df["_exit_velo"] = pd.to_numeric(_col(df, "launch_speed"), errors="coerce")

    rows = []
    for (bid, fam), g in df.groupby(["_bid", "_family"]):
        n = len(g)
        if n < MIN_PITCHES_FAMILY:
            continue
        swings = int(g["_swing"].sum())
        whiffs = int(g["_whiff"].sum())
        abs_ = int(g["_ab"].sum())
        tb = float(g["_tb"].sum())
        ev_series = g["_exit_velo"]
        rows.append({
            "batter": int(bid),
            "family": fam,
            "pitches": n,
            "whiff": (whiffs / swings) if swings else 0.0,
            "contact": (1.0 - whiffs / swings) if swings else 0.0,
            "slg": (tb / abs_) if abs_ else 0.0,                   # SLG against this family
            "xwoba": float(np.nanmean(g["_xwoba"])) if g["_xwoba"].notna().any() else 0.0,
            "exit_velo": float(np.nanmean(ev_series)) if ev_series.notna().any() else float("nan"),
        })
    return pd.DataFrame(rows, columns=cols)


# --------------------------------------------------------------------- hitter splits by pitch type
def build_hitter_pitch_type_splits(pitches: pd.DataFrame) -> pd.DataFrame:
    """One row per (batter, SPECIFIC pitch_type): whiff%, contact%, SLG-against, xwOBA-against,
    exit velo (this hitter's own), count.

    Same math as build_hitter_splits (see its own docstring for the real reasoning behind
    contact_pct/exit_velo) but by individual pitch (4-Seam, Slider, Curveball ...) rather than
    family — more granular, but noisier per hitter, so it uses a higher pitch floor
    (MIN_PITCHES_TYPE) and always carries the pitch count so a thin sample is visible, not hidden."""
    cols = ["batter", "pitch_type", "pitch_name", "family", "pitches", "whiff", "contact",
           "slg", "xwoba", "exit_velo"]
    if pitches is None or len(pitches) == 0:
        return pd.DataFrame(columns=cols)
    df = pitches.copy()
    df["_bid"] = pd.to_numeric(_col(df, "batter"), errors="coerce")
    df["_ptype"] = _col(df, "pitch_type").astype("string").fillna("")
    df = df.dropna(subset=["_bid"])
    df = df[df["_ptype"] != ""]
    swing, whiff = _swing_whiff(_col(df, "description"))
    df["_swing"] = swing.values
    df["_whiff"] = whiff.values
    events = _col(df, "events").astype("string").fillna("")
    df["_tb"] = events.map(_TB_BY_EVENT).fillna(0).astype(float).values
    df["_ab"] = events.isin(_AB_EVENTS).values
    df["_xwoba"] = pd.to_numeric(_col(df, "estimated_woba_using_speedangle"), errors="coerce")
    df["_exit_velo"] = pd.to_numeric(_col(df, "launch_speed"), errors="coerce")

    rows = []
    for (bid, ptype), g in df.groupby(["_bid", "_ptype"]):
        n = len(g)
        if n < MIN_PITCHES_TYPE:
            continue
        swings = int(g["_swing"].sum())
        whiffs = int(g["_whiff"].sum())
        abs_ = int(g["_ab"].sum())
        tb = float(g["_tb"].sum())
        ev_series = g["_exit_velo"]
        rows.append({
            "batter": int(bid),
            "pitch_type": ptype,
            "pitch_name": PITCH_NAME.get(ptype, ptype),
            "family": PITCH_FAMILY.get(ptype, "Other"),
            "pitches": n,
            "whiff": (whiffs / swings) if swings else 0.0,
            "contact": (1.0 - whiffs / swings) if swings else 0.0,
            "slg": (tb / abs_) if abs_ else 0.0,
            "xwoba": float(np.nanmean(g["_xwoba"])) if g["_xwoba"].notna().any() else 0.0,
            "exit_velo": float(np.nanmean(ev_series)) if ev_series.notna().any() else float("nan"),
        })
    out = pd.DataFrame(rows, columns=cols)
    if len(out):
        out = out.sort_values(["batter", "pitches"], ascending=[True, False])
    return out


# --------------------------------------------------------------------- matchup score
def matchup_score(pitcher_whiff: float, hitter_whiff: float, hitter_slg: float) -> float:
    """Transparent scouting heuristic: how good a weapon is this pitch vs this hitter?

    High when the pitcher misses bats with it AND the hitter both whiffs at it and does little
    damage against that family. Range roughly 0-1+. NOT a probability — a sortable edge signal.

        score = pitcher_whiff * (0.6 * hitter_whiff + 0.4 * (1 - clamp(hitter_slg / 0.550)))

    hitter_slg is normalized against a .550 "strong SLG" anchor so low-damage families score high.
    """
    slg_norm = min(max(hitter_slg / 0.550, 0.0), 1.0)
    hitter_vuln = 0.6 * hitter_whiff + 0.4 * (1.0 - slg_norm)
    return round(max(pitcher_whiff, 0.0) * hitter_vuln, 4)


def build_matchup(pitcher_id: int, hitter_id: int,
                  arsenals: Dict[int, List[Dict]], hitter_splits: Dict[int, Dict[str, Dict]]
                  ) -> List[Dict]:
    """Join one pitcher's arsenal to one hitter's family splits into per-pitch matchup rows,
    sorted by matchup score (best weapon first). Empty if either player is missing from cache."""
    arsenal = arsenals.get(int(pitcher_id)) or []
    splits = hitter_splits.get(int(hitter_id)) or {}
    rows = []
    for pitch in arsenal:
        fam = pitch.get("family", "Other")
        hs = splits.get(fam)
        h_whiff = hs["whiff"] if hs else None
        h_slg = hs["slg"] if hs else None
        h_contact = hs.get("contact") if hs else None
        h_exit_velo = hs.get("exit_velo") if hs else None
        rows.append({
            "pitch_name": pitch.get("pitch_name", pitch.get("pitch_type")),
            "pitch_type": pitch.get("pitch_type"),
            "family": fam,
            "usage": pitch.get("usage", 0.0),
            "velo": pitch.get("velo", 0.0),
            "p_whiff": pitch.get("whiff", 0.0),
            "p_putaway": pitch.get("putaway", 0.0),
            # None (not 0.0) when genuinely absent -- a REAL, CONFIRMED FIX: a fabricated 0.0
            # here doesn't just look wrong, it actively misleads, since it gets STYLED as if it
            # were real data (a 0% contact rate reads as excellent for the pitcher under the
            # reversed colormap, when it actually means "no data," the exact opposite of what
            # it displays as). Same honest-fallback principle already applied to exit_velo below.
            "zone_pct": pitch.get("zone_pct"),
            "contact_pct": pitch.get("contact_pct"),
            "exit_velo": pitch.get("exit_velo"),
            "h_whiff": h_whiff,
            "h_slg": h_slg,
            "h_xwoba": hs["xwoba"] if hs else None,
            "h_contact": h_contact,
            "h_exit_velo": h_exit_velo,
            "score": (matchup_score(pitch.get("whiff", 0.0), h_whiff, h_slg)
                      if hs else None),
        })
    rows.sort(key=lambda r: (r["score"] is not None, r["score"] or 0), reverse=True)
    return rows


# --------------------------------------------------------------------- refresh (network)
def refresh(year: int, arsenal_path: str = ARSENAL_PATH, hitter_path: str = HITTER_PATH,
            hitter_type_path: str = HITTER_TYPE_PATH) -> Tuple[str, str, str]:
    """Pull a full season of pitch-level Statcast, aggregate, and write the compact CSVs.

    HEAVY: this pulls the whole league's pitches for the season (chunked by day inside
    pybaseball). Run it in a scheduled job (GitHub Action), never in the app. Returns the three
    paths written. Column names occasionally drift between pybaseball versions; the aggregation
    is drift-tolerant, but verify the printed row counts look sane."""
    from pybaseball import statcast

    start, end = f"{year}-03-01", f"{year}-11-30"
    pitches = statcast(start_dt=start, end_dt=end)      # all pitches, all games in range
    if pitches is None or len(pitches) == 0:
        raise ValueError(f"Savant returned no pitches for {start}..{end}")

    arsenal = build_pitcher_arsenal(pitches)
    hitters = build_hitter_splits(pitches)
    hitter_types = build_hitter_pitch_type_splits(pitches)
    if arsenal.empty or hitters.empty:
        raise ValueError("aggregation produced empty tables — check pitch_type/description columns")

    os.makedirs(DATA_DIR, exist_ok=True)
    arsenal.to_csv(arsenal_path, index=False)
    hitters.to_csv(hitter_path, index=False)
    hitter_types.to_csv(hitter_type_path, index=False)
    print(f"Wrote {len(arsenal)} arsenal rows -> {arsenal_path}")
    print(f"Wrote {len(hitters)} hitter-family rows -> {hitter_path}")
    print(f"Wrote {len(hitter_types)} hitter-pitch-type rows -> {hitter_type_path}")
    return arsenal_path, hitter_path, hitter_type_path


# --------------------------------------------------------------------- load (fast)
def load(arsenal_path: str = ARSENAL_PATH, hitter_path: str = HITTER_PATH
         ) -> Tuple[Dict[int, List[Dict]], Dict[int, Dict[str, Dict]]]:
    """Read the cached tables into fast lookups:
        arsenals[pitcher_id]        -> [ {pitch_type, pitch_name, family, usage, whiff, ...}, ... ]
        hitter_splits[batter_id]    -> { family -> {whiff, slg, xwoba, pitches} }
    Returns ({}, {}) if the cache files are missing — callers must treat this layer as optional."""
    arsenals: Dict[int, List[Dict]] = {}
    hitter_splits: Dict[int, Dict[str, Dict]] = {}

    if os.path.exists(arsenal_path):
        try:
            a = pd.read_csv(arsenal_path)
            for r in a.itertuples(index=False):
                d = r._asdict()
                arsenals.setdefault(int(d["pitcher"]), []).append({
                    "pitch_type": d.get("pitch_type"), "pitch_name": d.get("pitch_name"),
                    "family": d.get("family"), "pitches": int(d.get("pitches", 0) or 0),
                    "usage": float(d.get("usage", 0) or 0), "whiff": float(d.get("whiff", 0) or 0),
                    "putaway": float(d.get("putaway", 0) or 0), "velo": float(d.get("velo", 0) or 0),
                    "zone_pct": _none_safe_float(d.get("zone_pct")),
                    "contact_pct": _none_safe_float(d.get("contact_pct")),
                    "exit_velo": _none_safe_float(d.get("exit_velo")),
                })
        except Exception:
            pass

    if os.path.exists(hitter_path):
        try:
            h = pd.read_csv(hitter_path)
            for r in h.itertuples(index=False):
                d = r._asdict()
                hitter_splits.setdefault(int(d["batter"]), {})[str(d.get("family"))] = {
                    "whiff": float(d.get("whiff", 0) or 0), "slg": float(d.get("slg", 0) or 0),
                    "xwoba": float(d.get("xwoba", 0) or 0), "pitches": int(d.get("pitches", 0) or 0),
                    "contact": _none_safe_float(d.get("contact")),
                    "exit_velo": _none_safe_float(d.get("exit_velo")),
                }
        except Exception:
            pass

    return arsenals, hitter_splits


def load_hitter_types(path: str = HITTER_TYPE_PATH) -> Dict[int, List[Dict]]:
    """Read the by-specific-pitch hitter table into a fast lookup:
        hitter_types[batter_id] -> [ {pitch_type, pitch_name, family, pitches, whiff, contact,
                                     slg, xwoba, exit_velo}, ... ]
    Sorted most-seen pitch first. Returns {} if the file is missing (page treats it as optional)."""
    out: Dict[int, List[Dict]] = {}
    if not os.path.exists(path):
        return out
    try:
        t = pd.read_csv(path)
        for r in t.itertuples(index=False):
            d = r._asdict()
            out.setdefault(int(d["batter"]), []).append({
                "pitch_type": d.get("pitch_type"), "pitch_name": d.get("pitch_name"),
                "family": d.get("family"), "pitches": int(d.get("pitches", 0) or 0),
                "whiff": float(d.get("whiff", 0) or 0), "slg": float(d.get("slg", 0) or 0),
                "xwoba": float(d.get("xwoba", 0) or 0),
                "contact": _none_safe_float(d.get("contact")),
                "exit_velo": _none_safe_float(d.get("exit_velo")),
            })
    except Exception:
        pass
    return out
