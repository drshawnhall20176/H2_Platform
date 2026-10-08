"""
position_pbp.py — NFL play-by-play and snap-count helpers for the Position Matchups game log.

PURE (pandas in, plain dicts out; the loading lives in position_data.py).

WHAT IT BUILDS
  period_lines()      {(order, team, player_id): {period: stats}} — every skill player's line in each game, for the
                      whole game and for each half / quarter, with the columns the official weekly stats lack
                      (longest completion / rush / reception, rush share, target share, anytime-TD flag).
  defense_absences()  who of a team's regular defenders did NOT play on defense in a given game, from the snap
                      counts — the data behind the log's "Without players" filter.

Checked against nflreadpy's official weekly player stats for the whole 2025 regular season: attempts,
completions, passing TDs, interceptions, carries, rushing yards and TDs, targets, receptions and receiving TDs
match on 100% of player-games; passing yards and receiving yards on 99.8% / 99.1% (the gaps are lateral plays,
which play-by-play credits to the passer/receiver of record). Two-point tries are excluded exactly as the weekly
stats exclude them; QB kneels and spikes count as the official stats count them.

ORDER is the same composite the log uses for every game: season * 100 + week (so 2026 week 4 is 202604), which
sorts correctly across the season boundary.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

PERIODS: Tuple[str, ...] = ("Full Game", "1st Half", "2nd Half", "Q1", "Q2", "Q3", "Q4")
_PERIOD_QTRS: Dict[str, Optional[Tuple[int, ...]]] = {
    "Full Game": None, "1st Half": (1, 2), "2nd Half": (3, 4, 5),            # overtime (qtr 5) counts in the 2nd half
    "Q1": (1,), "Q2": (2,), "Q3": (3,), "Q4": (4,)}

PBP_COLUMNS: Tuple[str, ...] = (
    "week", "season", "posteam", "qtr", "yards_gained", "complete_pass", "pass_attempt", "rush_attempt", "sack",
    "two_point_attempt", "passer_player_id", "rusher_player_id", "receiver_player_id", "pass_touchdown",
    "rush_touchdown", "interception")

STAT_KEYS: Tuple[str, ...] = (
    "pass_att", "pass_cmp", "pass_yds", "pass_td", "pass_int", "pass_long", "rush_att", "rush_yds", "rush_td",
    "rush_long", "tgt", "rec", "rec_yds", "rec_td", "rec_long", "td", "atd", "rush_rec_yds", "rush_share", "tgt_share")


def season_order(season: int, week: int) -> int:
    """The composite game order: season * 100 + week."""
    return int(season) * 100 + int(week)


def _flag(df: pd.DataFrame, col: str) -> pd.Series:
    return df[col].fillna(0).astype(float) if col in df.columns else pd.Series(0.0, index=df.index)


def _lines_for(plays: pd.DataFrame) -> pd.DataFrame:
    """Plays of ONE period -> one row per (player, season, week, team) with the STAT_KEYS columns."""
    d = plays[_flag(plays, "two_point_attempt") != 1].copy()
    d["_att"] = _flag(d, "pass_attempt")
    d["_sack"] = _flag(d, "sack")
    d["_cmp"] = _flag(d, "complete_pass")
    d["_rush"] = _flag(d, "rush_attempt")
    d["_y"] = _flag(d, "yards_gained")
    d["_ptd"] = _flag(d, "pass_touchdown")
    d["_rtd"] = _flag(d, "rush_touchdown")
    d["_int"] = _flag(d, "interception")
    keys = ["season", "week", "posteam"]
    thrown = d[(d["_att"] == 1) & (d["_sack"] != 1)]               # a sack is not an attempt
    caught = thrown[thrown["_cmp"] == 1]
    rushed = d[d["_rush"] == 1]
    targeted = thrown[thrown["receiver_player_id"].notna()]
    caught_t = targeted[targeted["_cmp"] == 1]

    def grp(df, pid_col, **aggs):
        if len(df) == 0:
            return pd.DataFrame(columns=["pid", *keys, *aggs])
        out = df.groupby([pid_col, *keys]).agg(**aggs).reset_index().rename(columns={pid_col: "pid"})
        return out

    parts = [
        grp(thrown[thrown["passer_player_id"].notna()], "passer_player_id", pass_att=("_att", "sum"), pass_cmp=("_cmp", "sum"),
            pass_td=("_ptd", "sum"), pass_int=("_int", "sum")),
        grp(caught[caught["passer_player_id"].notna()], "passer_player_id", pass_yds=("_y", "sum"), pass_long=("_y", "max")),
        grp(rushed[rushed["rusher_player_id"].notna()], "rusher_player_id", rush_att=("_rush", "sum"), rush_yds=("_y", "sum"),
            rush_td=("_rtd", "sum"), rush_long=("_y", "max")),
        grp(targeted, "receiver_player_id", tgt=("_att", "sum"), rec=("_cmp", "sum"), rec_td=("_ptd", "sum")),
        grp(caught_t, "receiver_player_id", rec_yds=("_y", "sum"), rec_long=("_y", "max")),
    ]
    out = None
    for part in parts:
        out = part if out is None else out.merge(part, on=["pid", *keys], how="outer")
    out = out.fillna(0.0)
    for k in STAT_KEYS:
        if k not in out.columns:
            out[k] = 0.0
    out["td"] = out["rush_td"] + out["rec_td"]
    out["atd"] = (out["td"] > 0).astype(float)
    out["rush_rec_yds"] = out["rush_yds"] + out["rec_yds"]
    team_rush = rushed.groupby(keys).size().rename("_team_rush").reset_index()
    team_tgt = targeted.groupby(keys).size().rename("_team_tgt").reset_index()
    out = out.merge(team_rush, on=keys, how="left").merge(team_tgt, on=keys, how="left")
    out["rush_share"] = (out["rush_att"] / out["_team_rush"].where(out["_team_rush"] > 0) * 100.0).fillna(0.0)
    out["tgt_share"] = (out["tgt"] / out["_team_tgt"].where(out["_team_tgt"] > 0) * 100.0).fillna(0.0)
    return out


def period_lines(pbp: pd.DataFrame, before: Optional[int] = None) -> Dict[Tuple[int, str, str], Dict[str, Dict[str, float]]]:
    """Play-by-play -> {(order, team, player_id): {period: {stat: value}}}.

    `before` is an exclusive composite-order cutoff (2026 week 5 is 202605): games at or after it are left out so
    the game being looked at never leaks into its own history. A (player, game) with no activity in a period has
    no entry for that period (the caller reads a missing period as all zeros)."""
    if pbp is None or len(pbp) == 0:
        return {}
    d = pbp[pbp["posteam"].notna() & pbp["week"].notna() & pbp["season"].notna()].copy()
    d["_order"] = d["season"].astype(int) * 100 + d["week"].astype(int)
    if before is not None:
        d = d[d["_order"] < before]
    out: Dict[Tuple[int, str, str], Dict[str, Dict[str, float]]] = {}
    for period, qtrs in _PERIOD_QTRS.items():
        plays = d if qtrs is None else d[d["qtr"].isin(qtrs)]
        if len(plays) == 0:
            continue
        for rec in _lines_for(plays).to_dict("records"):
            order = int(rec["season"]) * 100 + int(rec["week"])
            out.setdefault((order, rec["posteam"], rec["pid"]), {})[period] = {k: float(rec[k]) for k in STAT_KEYS}
    return out


# --------------------------------------------------------------------------- snap counts: who sat out
def defense_absences(snaps: pd.DataFrame, min_games: int = 2, min_avg_pct: float = 0.35
                     ) -> Tuple[Dict[Tuple[int, str], List[str]], Dict[str, List[Dict]]]:
    """Snap counts (nflreadpy shape: season, week, team, player, defense_snaps, defense_pct) ->
    (absences, regulars).

    regulars  {team: [{"name","avg_pct","games"}]} — a team's defenders who played at least `min_games` games on
              defense averaging `min_avg_pct` of the snaps, taken from the team's NEWEST season in the data,
              most-used first. These are the names the "Without players" picker offers.
    absences  {(order, team): [names]} — for each game the team played, the regulars (any season) who did not
              play on defense that game. A player counts as out only BETWEEN his first and last defensive game of
              that season for the team, so a rookie who hadn't arrived, or a player who was cut or traded, is not
              reported as injured; the cost is that a player who missed the END of a season never shows as out.

    Bye weeks produce no entry (the team has no rows that week)."""
    if snaps is None or len(snaps) == 0:
        return {}, {}
    df = snaps[snaps["team"].notna() & snaps["player"].notna()].copy()
    df["_def"] = df["defense_snaps"].fillna(0.0).astype(float)
    df["_pct"] = df["defense_pct"].fillna(0.0).astype(float)
    df["season"] = df["season"].astype(int)
    df["week"] = df["week"].astype(int)
    absences: Dict[Tuple[int, str], List[str]] = {}
    regulars: Dict[str, List[Dict]] = {}
    newest = df.groupby("team")["season"].max().to_dict()
    for (season, team), tdf in df.groupby(["season", "team"]):
        weeks = sorted(tdf["week"].unique())
        for player, pdf in tdf.groupby("player"):
            played = pdf[pdf["_def"] > 0]
            if len(played) < min_games:
                continue
            avg = float(played["_pct"].mean())
            if avg < min_avg_pct:
                continue
            first, last = int(played["week"].min()), int(played["week"].max())
            played_weeks = set(played["week"].astype(int))
            for w in weeks:
                if first < w < last and w not in played_weeks:
                    absences.setdefault((season_order(season, w), team), []).append(player)
            if season == newest[team]:
                regulars.setdefault(team, []).append({"name": player, "avg_pct": avg, "games": int(len(played))})
    for lst in regulars.values():
        lst.sort(key=lambda r: (-r["avg_pct"], r["name"]))
    for names in absences.values():
        names.sort()
    return absences, regulars
