"""
Dinger Engine — refactored from the original page 3.
 
Same idea (every projected hitter on the slate, platoon edges, matchup leaderboards),
but it runs on the shared concurrent backend: one hydrated request per hitter, per-team
lineup detection, and a real Confirmed/Projected badge. Loads a full slate in seconds.
"""
 
import streamlit as st
import components as C
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import pandas as pd
 
import mlb_engine as E
import odds_api as O
import projections as P
import statcast_data as SC
import weather as WX
from datetime import datetime
import pytz
 
C.base_css()
C.page_header("💣", "H2 Sports — Dinger Engine",
             "Live hitter matchups, platoon edges, and power leaderboards")
 
 
@st.cache_data(ttl=3600, show_spinner=False)
def load_statcast():
    return SC.load()  # (lookup_by_player_id, calibration_k); ({}, None) if no cache file
 
 
@st.cache_data(ttl=1800, show_spinner=False)
def load_weather(meta_keys: tuple):
    """meta_keys: tuple of (venue_id, game_date, venue_name). Returns {venue_id: weather|None}."""
    out = {}
    for vid, gdate, vname in meta_keys:
        if vid is not None and vid not in out:
            try:
                out[vid] = WX.get_game_weather(vid, gdate, vname)
            except Exception:
                out[vid] = None
    return out
 
 
@st.cache_data(ttl=300, show_spinner=False)
def load_slate(date_str: str, fip_constant: float, venue_split=None, time_split=None):
    import best_bets_data as BBD
    rows, meta = E.build_slate(date_str, fip_constant)
    # Real, confirmed fix for a structural gap: this page built its own slate independently and
    # never fetched real sportsbook lines at all, even after Best Bets/Graded Picks/Command
    # Center/Model Dashboard/Retrospective were already fixed to use them. Every HR%/hit
    # probability shown here was ALWAYS measured against this platform's own DEFAULT_LINES/
    # BEST_BET_REF placeholders -- the same player's HR pick could show a genuinely different
    # (and wrong) number here than on Best Bets, for the exact same game, the same night. Calls
    # the SAME shared fetch_mlb_real_lines function build_mlb_board and Pitching Lab already use.
    api_key = BBD.get_odds_api_key()
    preferred_book = st.session_state.get("_preferred_book_mlb", O.DEFAULT_BOOK)
    real_lines, _offers, _books = BBD.fetch_mlb_real_lines(date_str, api_key, preferred_book)
    sc, k = load_statcast()
    wx_by_venue = load_weather(tuple((m.get("venue_id"), m.get("game_date"), m.get("venue")) for m in meta))
    for r in rows:
        wx = wx_by_venue.get(r.get("_venue_id"))
        r["_weather_hr"] = wx["hr_factor"] if wx else 1.0
    if venue_split or time_split:
        season = int(date_str[:4])
        parts = [p for p in [venue_split, time_split] if p]
        label_base = "/".join(parts)
        for r in rows:
            pid = r.get("_pid")
            if not pid:
                continue
            split_stat, n = E.get_hitter_split_stat(pid, season, date_str,
                                                     venue=venue_split, time_of_day=time_split)
            if split_stat is not None:
                r["_stat"] = split_stat
                r["_split_label"] = f"{label_base} split ({n} games)"
            else:
                r["_split_label"] = f"full-season ({n} {label_base} games only)"
    P.enrich_hitter_rows(rows, seed=7, statcast=sc, statcast_k=k, real_lines=real_lines)
    P.add_starter_exposure_context(rows)
    return rows, meta, (len(sc) if sc else 0), wx_by_venue, real_lines
 
 
@st.cache_data(ttl=1800, show_spinner=False)
def load_bullpen_aggregate(team_id, exclude_pid):
    if not team_id:
        return None
    return E.get_bullpen_aggregate_stat(team_id, exclude_pid=exclude_pid)


@st.cache_data(ttl=1800, show_spinner=False)
def load_bullpen_handedness(team_id, exclude_pid):
    if not team_id:
        return {"L": 0, "R": 0, "total": 0, "pct_L": 0.0, "pct_R": 0.0}
    return E.get_bullpen_handedness_mix(team_id, exclude_pid=exclude_pid)


@st.cache_data(ttl=900, show_spinner=False)
def load_hitter_workload(team_id, date_str_inner):
    # Moved here from Pitching Lab -- see the Hitter Workload section's own comment below for
    # the full reasoning. Same 900s ttl Pitching Lab's own version already used.
    if not team_id:
        return []
    return E.get_team_hitter_workload(team_id, date_str_inner)


import best_bets_data as BBD

eastern = pytz.timezone("US/Eastern")
default_date = datetime.now(eastern)

c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    target_date = st.date_input("Slate date", default_date)
with c2:
    fip_constant = st.number_input("FIP constant", value=E.FIP_CONSTANT_DEFAULT, step=0.01)
with c3:
    st.write("")
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

date_str = target_date.strftime("%Y-%m-%d")
venue_split, time_split = BBD.render_split_selector(key_prefix="dinger_engine")

with st.spinner("Compiling telemetry..."):
    rows, meta, n_statcast, wx_by_venue, real_lines = load_slate(date_str, fip_constant, venue_split, time_split)

# Guarantees THIS session's own quick_log real-price side-channel is populated, regardless of
# whether load_slate() above was a cache hit for this session specifically -- see best_bets_data.
# ensure_mlb_offers_session_state's own docstring for the real, confirmed cross-session bug this
# fixes. Called here, in genuinely uncached top-level page code, not inside load_slate() itself.
BBD.ensure_mlb_offers_session_state(
    date_str, BBD.get_odds_api_key(), st.session_state.get("_preferred_book_mlb", O.DEFAULT_BOOK))

# Keep all_rows intact for the game-by-game section -- it needs both sides of every game.
# The split filter applies to leaderboards and summary stats only.
all_rows = rows

if venue_split or time_split:
    filtered_rows = []
    for r in rows:
        is_home = r.get("_is_home")
        is_day = r.get("_is_day_game")
        if venue_split == "home" and is_home is False:
            continue
        if venue_split == "away" and is_home is True:
            continue
        if time_split == "day" and is_day is False:
            continue
        if time_split == "night" and is_day is True:
            continue
        filtered_rows.append(r)
    rows = filtered_rows

if not all_rows:
    st.info("No hitters compiled for this date. Pick a date with scheduled MLB games.")
    st.stop()

df = pd.DataFrame(rows) if rows else pd.DataFrame()
all_df = pd.DataFrame(all_rows)

# Walk Risk column -- 🚶 when the opposing pitcher has ≥3.5 BB/9, blank otherwise.
# Scannable at a glance across the whole lineup: if you see 🚶 on your pick,
# the pitcher is wild enough to walk your player instead of giving them a real AB.
WALK_RISK_THRESHOLD = 3.5  # BB/9 -- approximately 85th percentile, genuinely wild control
for _frame in [df, all_df]:
    if "_opp_bb9" in _frame.columns:
        _frame["Walk Risk"] = _frame["_opp_bb9"].apply(
            lambda v: f"🚶 {v:.1f}" if (v or 0) >= WALK_RISK_THRESHOLD else ""
        )

confirmed = (all_df["Lineup"] == "Confirmed").sum()
split_note = f" · showing {len(rows)} matching {' + '.join(p for p in [venue_split, time_split] if p)}" if (venue_split or time_split) else ""
st.caption(f"{len(meta)} games · {len(all_df)} hitters · "
           f"{confirmed} from confirmed lineups, {len(all_df) - confirmed} projected from active rosters{split_note}")
if n_statcast:
    st.caption(f"🟢 Statcast power model active ({n_statcast} batters) — HR regresses toward "
               f"barrel-implied expected rate.")
else:
    st.caption("⚪ Statcast model off — run `python refresh_statcast.py` to enable barrel-based "
               "HR regression and the 'Due to Homer' board.")
 
 
# --- Styling ----------------------------------------------------------------
DISPLAY_COLS = ["Hitter", "Team", "Hand", "Opp Pitcher", "Opp Hand", "Advantage", "Lineup",
                "Opp HR/9", "Walk Risk", "vs SP", "vs Pen", "HR%", "Hit%", "TB1.5%", "SO Prob", "Barrel%", "xHR/PA", "K%", "HR", "TB", "SLG", "OPS", "ISO", "PowerIndex"]

def hr9_band(v):
    """Fixed-threshold coloring for pitcher HR/9 (absolute, not slate-relative).
    <0.8 excellent · 0.8-1.1 solid · 1.1-1.3 average · 1.3-1.5 below avg · >1.5 homer-prone.

    Text color is set explicitly on EVERY band, not just the two deep/saturated ones — the three
    lighter bands (#a6d96a/#fee08b/#fdae61) are all light enough (luminance > 150, same threshold
    styling.py's theme-proof gradient uses) that leaving text color unset lets it inherit the
    app's theme default, which is near-white in dark mode: pale background + white text is nearly
    invisible. #111111 matches styling.py's own "black on light backgrounds" convention exactly,
    so this reads the same as every other colored table on the platform, in either theme."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if x != x:          # NaN (opposing pitcher has no season line) -> no color
        return ""
    if x < 0.8:
        return "background-color:#1a9850;color:white"           # excellent (elite arm)
    if x < 1.1:
        return "background-color:#a6d96a;color:#111111"         # above average to solid
    if x < 1.3:
        return "background-color:#fee08b;color:#111111"         # average
    if x < 1.5:
        return "background-color:#fdae61;color:#111111"         # below average
    return "background-color:#d73027;color:white"                # bad / home-run prone
 
 
def style_hitters(data: pd.DataFrame):
    cols = [c for c in DISPLAY_COLS if c in data.columns]
    view = data[cols].copy()
    # Barrel% and xHR/PA come from Statcast and are None for players without Savant data (rookies /
    # low sample). As a mixed object column that (a) breaks the color gradient for the whole column
    # and (b) renders "None" instead of "—". Coerce to numeric so None -> NaN: the gradient then
    # colors the real values and leaves the no-Statcast cells blank ("—"), instead of faking a number.
    for c in ("Barrel%", "xHR/PA", "vs SP", "vs Pen"):
        if c in view.columns:
            view[c] = pd.to_numeric(view[c], errors="coerce")
    pct = [c for c in ("HR%", "Hit%", "TB1.5%", "SO Prob", "K%", "Barrel%", "xHR/PA") if c in view.columns]
    fmt = {"HR": "{:.0f}", "TB": "{:.0f}", "SLG": "{:.2f}", "OPS": "{:.2f}",
           "ISO": "{:.2f}", "PowerIndex": "{:.1f}", "Opp HR/9": "{:.2f}",
           "vs SP": "{:.2f}", "vs Pen": "{:.2f}"}
    fmt.update({c: "{:.1%}" for c in pct})
    styler = view.style.format(fmt, na_rep="—")
    # High is good for a hitter -> green. Barrel%/xHR/PA (more power) belong here too.
    grad_up = [c for c in ("HR%", "Hit%", "TB1.5%", "Barrel%", "xHR/PA", "HR", "TB", "SLG",
                           "OPS", "ISO", "PowerIndex") if c in view.columns]
    if grad_up:
        styler = styler.theme_gradient(cmap="RdYlGn", subset=grad_up)
    # Strikeouts hurt the hitter, so high = red on both the game prob and the season rate.
    red_high = [c for c in ("SO Prob", "K%") if c in view.columns]
    if red_high:
        styler = styler.theme_gradient(cmap="RdYlGn_r", subset=red_high)
    # Opp HR/9 uses fixed bands (elite arm green -> homer-prone red), not a slate-relative gradient.
    if "Opp HR/9" in view.columns:
        styler = styler.apply(lambda s: [hr9_band(v) for v in s], subset=["Opp HR/9"])
    return styler
 
 
# --- Leaderboards -----------------------------------------------------------
C.section_header("🏆", "Slate leaderboards")
if df.empty:
    st.caption(f"No hitters match the current split filter — leaderboards require at least one "
              f"matching player. The game-by-game section below still shows all hitters.")
else:
    lc1, lc2, lc3 = st.columns(3)
    with lc1:
        st.markdown("**🎯 Top HR probability** (matchup-aware)")
        if "HR%" in df.columns:
            top_hr = df.nlargest(8, "HR%")[["Hitter", "Team", "Opp Pitcher", "HR%"]]
            st.dataframe(top_hr.style.format({"HR%": "{:.1%}"}), hide_index=True, width="stretch")
        else:
            st.dataframe(df.nlargest(8, "PowerIndex")[["Hitter", "Team", "Opp Pitcher", "PowerIndex"]],
                         hide_index=True, width="stretch")
    with lc2:
        st.markdown("**Best total-bases plays**")
        if "TB1.5%" in df.columns:
            top_tb = df.nlargest(8, "TB1.5%")[["Hitter", "Team", "Opp Pitcher", "TB1.5%"]]
            st.dataframe(top_tb.style.format({"TB1.5%": "{:.1%}"}), hide_index=True, width="stretch")
    with lc3:
        st.markdown("**Platoon-advantage bats**")
        sort_key = "HR%" if "HR%" in df.columns else "PowerIndex"
        adv = df[df["Advantage"] == "Advantage"].nlargest(8, sort_key)
        fmtcol = {sort_key: "{:.1%}"} if sort_key == "HR%" else {}
        st.dataframe(adv[["Hitter", "Team", "Hand", "Opp Hand", sort_key]].style.format(fmtcol),
                     hide_index=True, width="stretch")

# --- Statcast: due-to-homer regression candidates --------------------------
if not df.empty and "Due" in df.columns:
    st.markdown("**🔥 Due to homer** — biggest gap between barrel-implied power and actual HR results "
                "(positive = hitting the ball harder than the HR count shows)")
    due = df[df["Due"] > 0].nlargest(10, "Due")[
        ["Hitter", "Team", "Opp Pitcher", "Barrel%", "xHR/PA", "HR%", "Due"]]
    st.dataframe(
        due.style.format({"Barrel%": "{:.1%}", "xHR/PA": "{:.1%}", "HR%": "{:.1%}", "Due": "{:+.1%}"})
        .theme_gradient(cmap="RdYlGn", subset=["Due"]),
        hide_index=True, width="stretch")
 
# --- Statcast: overall hitter regression (wOBA vs xwOBA) --------------------
# The honest hitter counterpart to Pitching Lab's ERA-vs-FIP table — same underlying idea (a
# results metric can be noisy; a quality-of-contact-based expected metric is a steadier read on
# true talent), but OVERALL offensive value, not just the HR-specific "Due to homer" board above.
# Reuses the SAME statcast lookup Dinger Engine already loaded for this pageview — zero extra fetch.
sc, _k = load_statcast()
if sc:
    reg_table = SC.build_hitter_regression_table(all_rows, sc)
    if reg_table:
        st.markdown("**📊 Results vs. contact quality** — actual wOBA against expected wOBA "
                    "(quality-of-contact-implied). 🟢 Green = underperforming his contact quality, "
                    "due for positive regression. 🔴 Red = outperforming it, due for negative "
                    "regression. A different question from \"Due to homer\" above — this is about "
                    "OVERALL offensive value (every batted ball and walk), not power specifically.")
        rdf = pd.DataFrame(reg_table)[["Hitter", "Team", "PA", "wOBA", "xwOBA", "Delta", "Tag"]]
        st.dataframe(
            rdf.style.format({"wOBA": "{:.3f}", "xwOBA": "{:.3f}", "Delta": "{:+.3f}"})
            .theme_gradient(cmap="RdYlGn_r", subset=["Delta"]),   # reversed: negative delta = green (good)
            hide_index=True, width="stretch")
        st.caption(f"Qualified hitters only (≥{SC.MIN_PA_QUALIFIED} PA) — small samples produce "
                  "noisy wOBA/xwOBA on both sides, not a real signal worth surfacing.")

# --- Per-game detail --------------------------------------------------------
st.divider()
C.section_header("⚾", "Game-by-game")
 
 
def game_time_et(iso_utc):
    """Format an ISO-UTC start time as local Eastern, e.g. '7:10 PM ET'. 'TBD' if missing."""
    if not iso_utc:
        return "TBD"
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(eastern)
        return dt.strftime("%I:%M %p").lstrip("0") + " ET"   # lstrip keeps it Windows-safe
    except (ValueError, TypeError):
        return "TBD"
 
 
# Chronological order: ISO-UTC strings sort by start time; games without a time go last.
meta_sorted = sorted(meta, key=lambda m: m.get("game_date") or "9999")
 
for m in meta_sorted:
    hp, ap = m["home_pm"], m["away_pm"]
    when = game_time_et(m.get("game_date"))
    badge = "" if (all_df[all_df["GameLabel"].str.startswith(m["label"].split(" (Game")[0])]["Lineup"] == "Confirmed").any() else " · projected lineups"
    with st.expander(f"🕒 {when}  ·  {m['label']}  —  {m['venue']}  ({m['status']}){badge}"):
        wx = wx_by_venue.get(m.get("venue_id"))
        if wx:
            if wx.get("dome"):
                st.markdown("🏟️ **Indoors** (fixed roof) — weather neutral")
            else:
                f = wx["hr_factor"]
                tag = f"🟢 +{(f - 1) * 100:.0f}% HR" if f > 1.02 else (
                    f"🔴 {(f - 1) * 100:.0f}% HR" if f < 0.98 else "⚪ neutral")
                approx = " · _wind orientation approximate_" if wx.get("approx_wind") else ""
                st.markdown(f"🌤️ **{wx['summary']}** → {tag}{approx}")

        # --- SP line + bullpen toggle, each side --------------------------------
        # A lineup that struggles against the confirmed starter can look very different once his
        # bullpen takes over — this toggle swaps which pitcher's stat line feeds the OPPOSING
        # team's hitter probabilities, reusing the exact same matchup math (see
        # projections.build_bullpen_matchup_rows' own docstring), not a second model.
        sp_col, toggle_col = st.columns([3, 1])
        with sp_col:
            st.markdown(
                f"✈️ **{m['away_name']}** SP {ap.name}: K/9 {ap.k9:.1f} · ERA {ap.era:.2f} · "
                f"FIP {ap.fip:.2f} · WHIP {ap.whip:.2f}"
            )
        with toggle_col:
            away_bullpen_on = st.checkbox("🔄 Bullpen", key=f"away_bp_{m['label']}",
                                          help=f"Show {m['home_name']} hitters vs {m['away_name']}'s "
                                              "bullpen instead of the confirmed starter.")
        sp_col2, toggle_col2 = st.columns([3, 1])
        with sp_col2:
            st.markdown(
                f"🏠 **{m['home_name']}** SP {hp.name}: K/9 {hp.k9:.1f} · ERA {hp.era:.2f} · "
                f"FIP {hp.fip:.2f} · WHIP {hp.whip:.2f}"
            )
        with toggle_col2:
            home_bullpen_on = st.checkbox("🔄 Bullpen", key=f"home_bp_{m['label']}",
                                          help=f"Show {m['away_name']} hitters vs {m['home_name']}'s "
                                              "bullpen instead of the confirmed starter.")

        # --- Per-game inline split toggle ------------------------------------
        # Recomputes this game's hitter stats using the selected split game logs so the
        # HR%/Hit%/TB1.5% numbers actually change when you switch Home/Away/Day/Night.
        # Each combination is cached separately -- switching back is instant.
        # Defaults to the global split but overridable per game independently.
        import projections as _Pmod
        game_date_iso = m.get("game_date", "")
        game_is_day = _Pmod._is_day_game_from_iso(game_date_iso)

        gsvc1, gsvc2 = st.columns(2)
        with gsvc1:
            game_venue_opt = st.radio(
                "🏟️ Venue split", ["All", "Home", "Away"],
                index=({"home": 2, "away": 1}.get(venue_split, 0) if venue_split else 0),
                horizontal=True, key=f"venue_split_{m['label']}",
                help="Recomputes HR%/Hit%/TB1.5% using each hitter's home or away game logs. "
                     "This changes the actual numbers, not just which players are shown.")
        with gsvc2:
            game_time_opt = st.radio(
                "🕐 Time split", ["All", "Day", "Night"],
                index=({"day": 1, "night": 2}.get(time_split, 0) if time_split else 0),
                horizontal=True, key=f"time_split_{m['label']}",
                help="Recomputes using day or night game logs. "
                     "Combines with venue split if both are set.")

        game_venue_split = None if game_venue_opt == "All" else game_venue_opt.lower()
        game_time_split = None if game_time_opt == "All" else game_time_opt.lower()

        # Re-enrich this game's hitters with the per-game split if different from global
        if game_venue_split != venue_split or game_time_split != time_split:
            @st.cache_data(ttl=300, show_spinner=False)
            def _game_split_rows(game_label, gv, gt, _date, _fip):
                base = [dict(r) for r in all_rows if r.get("GameLabel") == game_label]
                if not base:
                    return base
                season = int(_date[:4])
                from concurrent.futures import ThreadPoolExecutor
                def _apply(r):
                    pid = r.get("_pid")
                    if pid:
                        split_stat, n = E.get_hitter_split_stat(pid, season, _date, venue=gv, time_of_day=gt)
                        if split_stat is not None:
                            r["_stat"] = split_stat
                            r["_split_label"] = f"{' + '.join(p for p in [gv, gt] if p)} split ({n} games)"
                        else:
                            r["_split_label"] = f"full-season ({n} qualifying games)"
                    return r
                with ThreadPoolExecutor(max_workers=8) as ex:
                    enriched = list(ex.map(_apply, base))
                # real_lines threaded in via closure (same pattern sc/_k already use here) -- a
                # real, confirmed second instance of the same disconnected-pipeline gap: this
                # per-game split override path calls enrich_hitter_rows independently of the
                # main load_slate() above, and was found to ALSO be missing real_lines even
                # after that first call site was fixed.
                P.enrich_hitter_rows(enriched, seed=7, statcast=sc, statcast_k=_k, real_lines=real_lines)
                return enriched

            with st.spinner("Loading split stats for this game..."):
                _enriched = _game_split_rows(m["label"], game_venue_split, game_time_split, date_str, fip_constant)
            game_df = pd.DataFrame(_enriched) if _enriched else all_df[all_df["GameLabel"] == m["label"]]
            if game_venue_split or game_time_split:
                parts = [p.title() for p in [game_venue_split, game_time_split] if p]
                st.caption(f"📊 Showing **{' + '.join(parts)} split** — HR%/Hit%/TB1.5% "
                          "reflect each hitter's performance in this context specifically. "
                          "Players showing 'full-season' had fewer than 5 qualifying games in this split.")
        else:
            game_df = all_df[all_df["GameLabel"] == m["label"]]

        sort_col = "HR%" if "HR%" in game_df.columns else "PowerIndex"

        # --- Lineup platoon map ---------------------------------------------
        # A quick "lineup construction" read before the detailed stat tables below — how many
        # hitters in EACH lineup hold the platoon edge against tonight's confirmed starter.
        # Reuses the Hand/Advantage columns every hitter row already has (mlb_engine.
        # platoon_advantage), zero extra fetches — a surfacing exercise, not new modeling.
        # Bullpen handedness mix is a genuinely separate signal (a bullpen has mixed hands, no
        # single "advantage" the way one starter has) and only fetched when that side's bullpen
        # toggle is ALREADY on, to keep this section at zero extra cost otherwise.
        st.markdown("**🔄 Platoon map**")
        pc1, pc2 = st.columns(2)
        for col, lineup_team, opp_sp, bullpen_on, bullpen_team_id, bullpen_exclude_pid in (
            (pc1, m["away_name"], hp, home_bullpen_on, m.get("home_id"), hp.id),
            (pc2, m["home_name"], ap, away_bullpen_on, m.get("away_id"), ap.id),
        ):
            with col:
                side_df = game_df[game_df["Team"] == lineup_team]
                if "Advantage" in side_df.columns and len(side_df):
                    adv_names = side_df[side_df["Advantage"] == "Advantage"]["Hitter"].tolist()
                    st.markdown(f"**{lineup_team}** vs {opp_sp.hand}HP {opp_sp.name}: "
                              f"{len(adv_names)} of {len(side_df)} hitters have the platoon edge")
                    if adv_names:
                        st.caption("✅ " + ", ".join(adv_names))
                else:
                    st.caption("No platoon data available for this lineup yet.")
                if bullpen_on:
                    mix = load_bullpen_handedness(bullpen_team_id, bullpen_exclude_pid)
                    if mix["total"]:
                        opp_name = m["home_name"] if lineup_team == m["away_name"] else m["away_name"]
                        st.caption(f"🎯 If it gets to the pen: {opp_name}'s bullpen is "
                                  f"{mix['pct_R']:.0%} RHP / {mix['pct_L']:.0%} LHP "
                                  f"({mix['R']}R / {mix['L']}L, {mix['total']} active arms)")

        # --- Hitter workload -------------------------------------------------
        # Moved here from Pitching Lab directly on request -- a fatigue/rest concern about the
        # HITTERS in this game, the same real thing pitcher rest and bullpen fatigue already
        # cover for pitchers, just landed on the pitcher-focused page originally because it
        # followed that page's own per-game pattern, not because it's conceptually a pitching
        # topic. This is the actual hitter-focused home on this platform.
        #
        # Real cost per team (same as it always was) -- an opt-in checkbox here, matching this
        # page's OWN existing convention for the "🔄 Bullpen" toggles above, rather than a
        # separate single-game picker the way Pitching Lab used to gate it. Every game's own
        # expander already runs for every game on the slate regardless of whether it's visually
        # collapsed (Streamlit doesn't defer content inside a closed expander), so this MUST stay
        # opt-in per game -- an unconditional fetch here would silently fetch workload data for
        # every game on the slate on every page load, the exact cost regression this checkbox
        # exists to prevent.
        show_workload = st.checkbox("🏃 Show hitter workload (who's played every game, no rest)",
                                    key=f"workload_{m['label']}")
        if show_workload:
            home_workload = load_hitter_workload(m.get("home_id"), date_str)
            away_workload = load_hitter_workload(m.get("away_id"), date_str)
            wlc1, wlc2 = st.columns(2)
            for col, label, workload in ((wlc1, m["away_name"], away_workload),
                                         (wlc2, m["home_name"], home_workload)):
                with col:
                    st.markdown(f"**{label}**")
                    flagged = [w for w in workload if w["consecutive_games_started"] >= 5]
                    if not flagged:
                        st.caption("No hitters with 5+ straight games started in this window.")
                    else:
                        st.dataframe(
                            pd.DataFrame(flagged)[["name", "consecutive_games_started", "tag"]]
                            .rename(columns={"name": "Hitter", "consecutive_games_started": "Streak", "tag": "Tag"}),
                            hide_index=True, width="stretch")
            st.caption("Counts backward through each TEAM's own most recent games, not "
                      "consecutive calendar days — a team's own off-day is real rest regardless "
                      "of how many calendar days it spans.")

        t_away, t_home = st.tabs([f"✈️ {m['away_name']} bats", f"🏠 {m['home_name']} bats"])

        def _bullpen_sub(rows_source: pd.DataFrame, opp_team: str, opp_team_id, exclude_pid) -> pd.DataFrame:
            """Recompute opp_team's hitter rows vs opp_team's OWN opponent's bullpen, or fall back
            to the starter-based rows (with a visible warning) if the bullpen read isn't available."""
            agg = load_bullpen_aggregate(opp_team_id, exclude_pid)
            base_rows = rows_source[rows_source["Team"] == opp_team].to_dict("records")
            if agg is None:
                st.warning(f"No usable bullpen data for the opposing team — showing the "
                          f"vs-starter read for {opp_team} instead.")
                return rows_source[rows_source["Team"] == opp_team].sort_values(sort_col, ascending=False)
            bp_rows = P.build_bullpen_matchup_rows(base_rows, opp_team, agg, seed=7,
                                                    statcast=sc, statcast_k=_k,
                                                    real_lines=real_lines)
            bp_df = pd.DataFrame(bp_rows)
            # "Opp Pitcher"/"Opp Hand"/"Advantage" describe the SINGLE starter — showing them
            # unchanged next to a bullpen-wide read would misleadingly imply one specific
            # opposing arm, when the numbers now reflect the whole relief corps combined.
            # "Opp HR/9" gets the REAL aggregate bullpen rate instead (already computed by
            # _aggregate_pitching_splits), not blanked — a genuinely useful number, not a gap.
            for col, val in (("Opp Pitcher", "Bullpen (combined)"), ("Opp Hand", "Mixed"),
                             ("Advantage", "—")):
                if col in bp_df.columns:
                    bp_df[col] = val
            if "Opp HR/9" in bp_df.columns:
                bp_df["Opp HR/9"] = agg.get("homeRunsPer9", 0.0)
            return bp_df.sort_values(sort_col, ascending=False) if sort_col in bp_df.columns else bp_df

        _col_cfg = {"Advantage": st.column_config.TextColumn(
            "Platoon", help="Advantage = opposite hands (platoon edge). "
            "Disadvantage = same hands — NOT a skip signal. Great hitters "
            "produce regardless. The model already factors this in via "
            "vs_L/vs_R splits.")}

        with t_away:
            if home_bullpen_on:
                sub = _bullpen_sub(game_df, m["away_name"], m.get("home_id"), hp.id)
                st.caption(f"Showing {m['away_name']} hitters vs {m['home_name']}'s combined "
                          "bullpen, not the confirmed starter.")
            else:
                sub = game_df[game_df["Team"] == m["away_name"]].sort_values(sort_col, ascending=False)
            st.dataframe(style_hitters(sub), width="stretch", hide_index=True,
                        column_config=_col_cfg)
        with t_home:
            if away_bullpen_on:
                sub = _bullpen_sub(game_df, m["home_name"], m.get("away_id"), ap.id)
                st.caption(f"Showing {m['home_name']} hitters vs {m['away_name']}'s combined "
                          "bullpen, not the confirmed starter.")
            else:
                sub = game_df[game_df["Team"] == m["home_name"]].sort_values(sort_col, ascending=False)
            st.dataframe(style_hitters(sub), width="stretch", hide_index=True,
                        column_config=_col_cfg)
 
st.caption("HR% / Hit% / TB1.5% / SO Prob are matchup-aware model probabilities for TODAY's game: "
           "each hitter's stabilized rates are combined with the opposing pitcher's allowed rates "
           "(odds-ratio method) and his platoon split, then park-adjusted. K% is the hitter's SEASON "
           "strikeout rate (a skill stat) for reference. PowerIndex is the legacy heuristic.")
st.caption("**Advantage / Disadvantage** = the handedness matchup between the batter and the opposing "
           "starter. Advantage = opposite hands (e.g. RHB vs LHP) — the standard platoon edge. "
           "Disadvantage = same hands (e.g. RHB vs RHP). **Disadvantage does NOT mean skip this player.** "
           "It means one favorable factor isn't present tonight. Great hitters produce regardless — "
           "check their season numbers vs. same-hand pitching specifically (the model already factors "
           "this in via the vs_L/vs_R platoon split). Think of it as context, not a veto.")
st.caption("**Walk Risk 🚶** = opposing pitcher's BB/9 is ≥3.5 — approximately the 85th percentile, "
           "genuinely wild control. When this shows on your pick, the pitcher may walk your player "
           "instead of giving them a real at-bat, killing HRR, Hits, and Runs props specifically. "
           "The Raley situation (July 27 — walked twice, multiple slips dead) is the real example. "
           "Not a reason to skip, but a reason to size down or hedge.")
st.caption("Opp HR/9 = the opposing starter's home runs allowed per 9 innings, colored on fixed bands "
           "(not slate-relative): 🟢 under 0.80 excellent · 🟩 0.80–1.10 solid · 🟡 1.10–1.30 average · "
           "🟠 1.30–1.50 below average · 🔴 over 1.50 homer-prone. A redder arm is a better power spot "
           "for the hitter.")
st.caption("**vs SP / vs Pen** = how many of this hitter's own expected plate appearances fall "
          "against the starter specifically vs. against the bullpen once his projected work is "
          "exhausted — derived from this hitter's own lineup spot and the starter's own projected "
          "batters faced (see Pitching Lab's Proj TTO for that same starter's own trip count). "
          "This is the connection between three things that would otherwise read as separate: a "
          "starter projecting a real 3rd trip through the order (Pitching Lab), which SPECIFIC "
          "hitters actually get exposed to that repeat look (a leadoff hitter far more than a "
          "7-9 spot), and which of a hitter's own PA the 🔄 Bullpen toggle above actually speaks "
          "to — a hitter with real \"vs Pen\" plate appearances genuinely has some of their night "
          "riding on that bullpen read, not just a hypothetical what-if. Not a probability "
          "adjustment — HR%/Hit%/TB1.5%/SO Prob above are still the season-long vs-starter read "
          "either way; this is honest context about exposure, not a recomputed number.")
