"""
Best Bets — the model's strongest leans across the whole slate, with reasoning.
"""

import streamlit as st
import styling  # installs theme-proof .theme_gradient (readable in light + dark)
import pandas as pd
from datetime import datetime
import pytz

import sports

_active = sports.active()
E, P = _active.engine, _active.projections

st.title("⭐ Best Bets")
st.caption(f"The model's strongest leans across the slate — ranked, reasoned, and by time slot "
           f"— {_active.icon} {_active.label}")

if not sports.require_live_engine("Best Bets"):
    st.stop()

eastern = pytz.timezone("US/Eastern")

def game_dt(iso_utc):
    if not iso_utc: return None
    try: return datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(eastern)
    except (ValueError, TypeError): return None

def slot_of(dt):
    if dt is None: return "TBD"
    h = dt.hour
    if h < 17: return "Afternoon"
    if h < 20: return "Evening"
    return "Late"

SLOT_ORDER = {"Afternoon": 0, "Evening": 1, "Late": 2, "TBD": 3}


@st.cache_data(ttl=300, show_spinner=False)
def load_best_bets_mlb(date_str: str, fip_constant: float):
    import statcast_data as SC
    import weather as WX

    @st.cache_data(ttl=3600, show_spinner=False)
    def load_statcast():
        return SC.load()

    @st.cache_data(ttl=1800, show_spinner=False)
    def load_weather(meta_keys: tuple):
        out = {}
        for vid, gdate, vname in meta_keys:
            if vid is not None and vid not in out:
                try: out[vid] = WX.get_game_weather(vid, gdate, vname)
                except Exception: out[vid] = None
        return out

    rows, meta = E.build_slate(date_str, fip_constant)
    sc, k = load_statcast()
    wx = load_weather(tuple((m.get("venue_id"), m.get("game_date"), m.get("venue")) for m in meta))
    for r in rows:
        w = wx.get(r.get("_venue_id"))
        r["_weather_hr"] = w["hr_factor"] if w else 1.0
        if w:                              # keep the pieces so the inspector can decompose weather
            r["_wx_temp"] = w.get("temp_f")
            r["_wx_outwind"] = w.get("out_wind_mph", 0.0)
            r["_wx_desc"] = w.get("wind_desc")
            r["_wx_roof"] = w.get("roof", "open")
    P.enrich_hitter_rows(rows, seed=7, statcast=sc, statcast_k=k)
    pitcher_rows = P.build_pitcher_projection_rows(rows, meta, seed=11)
    plays = P.build_best_bets(rows, pitcher_rows)
    slot_by_game = {m["label"]: (game_dt(m.get("game_date")), m.get("venue")) for m in meta}
    for pl in plays:
        dt, _ = slot_by_game.get(pl["Game"], (None, None))
        pl["Slot"] = slot_of(dt)
        pl["Time"] = dt.strftime("%I:%M %p").lstrip("0") + " ET" if dt else "TBD"
    return plays, len(meta)


@st.cache_data(ttl=300, show_spinner=False)
def load_best_bets_generic(sport_key: str, date_str: str):
    """Any sport whose engine/projections don't need MLB's statcast/weather enrichment path —
    currently WNBA, and any future sport built the same way."""
    sport = sports.get(sport_key)
    engine, proj = sport.engine, sport.projections
    rows, meta = engine.build_slate(date_str)
    plays = proj.build_best_bets(rows)
    slot_by_game = {m["label"]: game_dt(m.get("game_date")) for m in meta}
    for pl in plays:
        dt = slot_by_game.get(pl["Game"])
        pl["Slot"] = slot_of(dt)
        pl["Time"] = dt.strftime("%I:%M %p").lstrip("0") + " ET" if dt else "TBD"
    return plays, len(meta)


# --- controls ---------------------------------------------------------------
if _active.key == "MLB":
    c1, c2 = st.columns([2, 1])
    with c1: target = st.date_input("Slate date", datetime.now())
    with c2: fip_constant = st.number_input("FIP constant", value=E.FIP_CONSTANT_DEFAULT, step=0.01)
    date_str = target.strftime("%Y-%m-%d")
    with st.spinner("Scanning the slate..."):
        plays, n_games = load_best_bets_mlb(date_str, fip_constant)
else:
    target = st.date_input("Slate date", datetime.now(eastern))
    date_str = target.strftime("%Y-%m-%d")
    with st.spinner("Scanning the slate..."):
        plays, n_games = load_best_bets_generic(_active.key, date_str)

if not plays:
    st.info("No plays for this date.")
    st.stop()

# --- filters ---------------------------------------------------------------
slots_present = sorted({p["Slot"] for p in plays}, key=lambda s: SLOT_ORDER.get(s, 9))
f1, f2, f3 = st.columns([1, 2, 1])
with f1: slot_pick = st.selectbox("Time slot", ["All slate"] + slots_present)
with f2:
    markets = sorted({p["Market"] for p in plays})
    mkt_pick = st.multiselect("Markets", markets, default=markets)
with f3: min_conv = st.slider("Min conviction", 1.0, 3.0, 1.2, 0.1)

view = [p for p in plays
        if (slot_pick == "All slate" or p["Slot"] == slot_pick)
        and p["Market"] in mkt_pick and p["Conviction"] >= min_conv]

# --- the board -------------------------------------------------------------
df = pd.DataFrame(view)[["Conviction", "Time", "Slot", "Player", "Team", "Market", "Side",
                         "Line", "ModelProb", "Fair", "Game", "Why"]]
df = df.rename(columns={"ModelProb": "Model %", "Why": "Why the model likes it"})
st.dataframe(df.style.format({"Model %": "{:.0%}", "Line": "{:g}", "Conviction": "{:.2f}×", "Fair": "{:+d}"},
                             na_rep="—")
             .theme_gradient(cmap="Greens", subset=["Conviction"]),
             use_container_width=True, hide_index=True, height=400)

# --- DIAGNOSTIC INSPECTOR --------------------------------------------------
st.markdown("---")
st.subheader("🔍 Inspect Bet Diagnostics")

if not view:
    st.info("No plays match the current filters — adjust the time slot, markets, or min conviction.")
    st.stop()

# Searchable picker: the box is type-to-search, so just start typing a player's name to jump to
# them — no scrolling. Plays are already ordered by conviction, so the strongest leans are on top.
selected_idx = st.selectbox(
    "Select a play to inspect for model hallucinations (type a name to search)",
    options=range(len(view)),
    format_func=lambda i: (f"{view[i]['Conviction']:.2f}×  ·  {view[i]['Player']}  ·  "
                           f"{view[i]['Market']} {view[i]['Side']} {view[i]['Line']:g}"))

p = view[selected_idx]
with st.expander("Diagnostic Inspector", expanded=True):
    if _active.key == "MLB":
        pa = p.get("PA")
        phr = p.get("ParkHR", 1.0)
        wxc = p.get("WxHR", 1.0)
        temp = p.get("Temp")
        temp_pct = p.get("WxTempPct")
        wind_pct = p.get("WxWindPct")
        wind_desc = p.get("WxDesc")
        driver = p.get("WxDriver")

        col1, col2, col3 = st.columns(3)
        # Plate appearances with a graduated confidence label (not just a binary warning)
        if pa is None:
            col1.metric("Plate Appearances (PA/BF)", "N/A")
        else:
            sample = "thin" if pa < 50 else "moderate" if pa < 200 else "robust"
            col1.metric("Plate Appearances (PA/BF)", f"{pa:.1f}", help="Season sample behind the projection")
            col1.caption(f"sample: **{sample}**")
        col2.metric("Park HR Factor", f"{phr:.2f}", help="Multi-year park data — stable, high-confidence")
        col3.metric("Weather Factor", f"{wxc:.2f}")

        # --- weather decomposition: split the factor into temperature vs wind, with a trust note ---
        if temp_pct is not None or wind_pct is not None:
            t_txt = (f"Temperature {int(temp)}°F ({temp_pct:+.0f}%)" if temp is not None
                     else f"Temperature ({temp_pct:+.0f}%)")
            w_txt = f"Wind — {wind_desc} ({wind_pct:+.0f}%)" if wind_desc else f"Wind ({wind_pct:+.0f}%)"
            st.markdown(f"**Weather {wxc:.2f} =** {t_txt}  ·  {w_txt}")
            if wind_pct is not None and abs(wind_pct) < 1:
                st.caption("↳ The wind is a crosswind / negligible — this factor is essentially **all "
                           "temperature**, a robust and well-understood effect. Trust it.")
            elif driver == "wind":
                st.caption("↳ This boost **leans on the wind** (the out-to-CF component), which is more "
                           "variable than heat — worth a glance at the actual conditions before leaning on it.")
            else:
                st.caption("↳ Driven mostly by **temperature** (robust), with a modest wind contribution.")

        # --- warnings, now confidence-aware ---
        if pa is not None and pa < 50:
            st.warning(f"⚠️ Low sample: projecting on only ~{pa:.0f} PA — regress hard, treat with caution.")

        stack = phr * wxc
        if stack > 1.15:
            # A stack driven by heat + park (both high-confidence) is NOT a 'perfect storm'. Only the
            # WIND-driven portion is genuinely fragile, so only sound the alarm when wind is doing the work.
            if wind_pct is not None and wind_pct >= 5:
                st.warning(f"⚠️ Multiplier stack (+{(stack - 1) * 100:.0f}%) leans on a **wind boost "
                           f"(+{wind_pct:.0f}%)** — the least reliable input. Verify the wind is real before trusting it.")
            else:
                st.info(f"ℹ️ Park × weather is ~+{(stack - 1) * 100:.0f}%, but it's driven by **heat and park** "
                        "(high-confidence inputs), not a phantom wind boost — reasonable to trust.")
    else:
        # No park/weather/platoon signals exist for basketball — the honest inspector here is
        # just the receipts: the player's actual last-N games for this exact stat, so you can see
        # precisely what the bootstrap model resampled from rather than trusting a black box.
        log = p.get("_game_log") or []
        stat_key = p.get("_stat_key")
        if not log or not stat_key:
            st.caption("No recent-game log attached to this play.")
        else:
            n = len(log)
            hits = sum(1 for g in log if (g.get(stat_key, 0) > p["Line"] if p["Side"] == "Over"
                                          else g.get(stat_key, 0) < p["Line"]))
            avg = sum(g.get(stat_key, 0) for g in log) / n
            c1, c2, c3 = st.columns(3)
            c1.metric("Games sampled", n, help="How many recent games the bootstrap model drew from")
            c2.metric(f"Cleared {p['Line']:g}", f"{hits}/{n}")
            c3.metric("Recent average", f"{avg:.1f}")
            if n < 6:
                st.warning(f"⚠️ Short sample: only {n} recent games — the model can't yet see outcomes "
                           "this player hasn't produced in that window. Treat with extra caution.")
            log_df = pd.DataFrame([{"Game #": i + 1, stat_key.upper(): g.get(stat_key, 0),
                                    "Minutes": g.get("min", 0)} for i, g in enumerate(log)])
            st.dataframe(log_df, hide_index=True, use_container_width=True)
            st.caption("Game #1 is most recent. This is the exact data the bootstrap resampled from — "
                       "no park factor, weather, or opponent adjustment yet (v1 model).")

# --- footer ----------------------------------------------------------------
st.caption("Conviction shades darker for stronger leans. ...")
with st.expander("How 'best' is defined here (read me)"):
    st.markdown("...")
