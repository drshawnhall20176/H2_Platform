"""
football_weather.py — wind and cold for NFL and college football player props (Nov 8).

Measured, not assumed (research/nfl_weather_env.py): NFL 2016-2025 regular seasons, every player-game against his own
previous five games, AFTER the game's implied team total (the model already moves projections with it, and books
lower totals in wind), outdoor games vs calm outdoor games. Each effect below showed up in both halves of the data
(even and odd seasons); the numbers are the measured ones pulled about a fifth of the way back toward no effect.

                      wind 10-14   15-19    20+      cold (40°F or under)
    Pass Yards          0.975      0.935    0.89      0.97
    Passing TDs         0.94       0.93     0.88      —
    Receiving Yards     0.97       0.93     0.92      0.97
    Receptions          0.995      0.965    0.95      0.985
    Rush Yards / Att    1.015      1.015    1.10      1.03

Not used: kickers (field goals and extra points moved, but not the same way in both halves), pass attempts (only at
20+ mph, in one half). Domes and closed roofs: no adjustment. College uses the NFL numbers (same air, no college
weather history here) -- flagged on the row.

Live weather: ESPN's scoreboard (venue, indoor or not, kickoff) + Open-Meteo (free, keyless; the MLB pages already
use it): wind at 10 m and temperature averaged over the first three hours from kickoff. Any failure = no adjustment.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional

import requests

H = {"User-Agent": "Mozilla/5.0"}
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/{path}/scoreboard"
PATHS = {"NFL": ("nfl", {}), "NCAAF": ("college-football", {"groups": "80", "limit": "400"})}
GEO = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"

WIND = {"Pass Yards": (0.975, 0.935, 0.89), "Passing TDs": (0.94, 0.93, 0.88),
        "Receiving Yards": (0.97, 0.93, 0.92), "Receptions": (0.995, 0.965, 0.95),
        "Rush Yards": (1.015, 1.015, 1.10), "Rush Attempts": (1.015, 1.015, 1.10)}
COLD = {"Pass Yards": 0.97, "Receiving Yards": 0.97, "Receptions": 0.985, "Rush Yards": 1.03, "Rush Attempts": 1.03}
COLD_F = 40.0

STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
          "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
          "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
          "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
          "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
          "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
          "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
          "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
          "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
          "WI": "Wisconsin", "WY": "Wyoming"}

_CACHE: Dict = {}
TTL = 3600


def _http(url: str, params: Dict) -> Optional[Dict]:
    try:
        r = requests.get(url, params=params, headers=H, timeout=15)
        return r.json() if r.ok else None
    except Exception:                                           # noqa: BLE001
        return None


def _cached(key, fn, ttl: float = TTL):
    """Remembers an answer for an hour -- but never a failed lookup (None), so one network hiccup doesn't leave a
    game without weather for the rest of the hour."""
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < hit[2]:
        return hit[1]
    val = fn()
    if val is not None:
        _CACHE[key] = (time.time(), val, ttl)
    return val


def wind_bucket(mph: Optional[float]) -> Optional[int]:
    if mph is None or mph < 10:
        return None
    return 0 if mph < 15 else 1 if mph < 20 else 2


def multiplier(market: str, wx: Optional[Dict]) -> float:
    """The weather multiplier for one market's projection (1.0 indoors, calm, unknown, or a market weather doesn't move)."""
    if not wx or wx.get("indoor"):
        return 1.0
    m = 1.0
    b = wind_bucket(wx.get("wind"))
    if b is not None and market in WIND:
        m *= WIND[market][b]
    t = wx.get("temp")
    if t is not None and t <= COLD_F and market in COLD:
        m *= COLD[market]
    return m


def flag(market: str, wx: Optional[Dict], sport: str = "NFL") -> Optional[str]:
    m = multiplier(market, wx)
    if abs(m - 1.0) < 0.004:
        return None
    bits = []
    if wind_bucket(wx.get("wind")) is not None:
        bits.append(f"wind {wx['wind']:.0f} mph")
    if wx.get("temp") is not None and wx["temp"] <= COLD_F:
        bits.append(f"{wx['temp']:.0f}°F")
    tail = " (NFL-measured)" if sport != "NFL" else ""
    return f"🌬️ Weather: {', '.join(bits)} → {m - 1:+.0%} {market.lower()}{tail}"


def _geocode(city: str, state: Optional[str], fetch: Callable) -> Optional[tuple]:
    def go():
        d = fetch(GEO, {"name": city, "count": 10, "language": "en", "format": "json"}) or {}
        res = d.get("results") or []
        want = STATES.get(str(state or "").upper(), state)
        for r in res:
            if want and r.get("admin1") == want:
                return r["latitude"], r["longitude"]
        return (res[0]["latitude"], res[0]["longitude"]) if res else None
    return _cached(("geo", city, state), go)


def _forecast(lat: float, lon: float, kickoff: datetime, fetch: Callable) -> Optional[Dict]:
    day = kickoff.strftime("%Y-%m-%d")
    day2 = (kickoff + timedelta(hours=4)).strftime("%Y-%m-%d")

    def go():
        return fetch(FORECAST, {"latitude": round(lat, 3), "longitude": round(lon, 3),
                                "hourly": "temperature_2m,wind_speed_10m,weather_code,precipitation_probability",
                                "temperature_unit": "fahrenheit",
                                "wind_speed_unit": "mph", "timezone": "UTC", "start_date": day, "end_date": day2})
    d = _cached(("wx", round(lat, 2), round(lon, 2), day), go) or {}
    h = d.get("hourly") or {}
    times, temps, winds = h.get("time") or [], h.get("temperature_2m") or [], h.get("wind_speed_10m") or []
    start = kickoff.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    pick = [i for i, t in enumerate(times)
            if start <= datetime.fromisoformat(t) <= start + timedelta(hours=3)]
    if not pick:
        return None
    w = [winds[i] for i in pick if i < len(winds) and winds[i] is not None]
    t = [temps[i] for i in pick if i < len(temps) and temps[i] is not None]
    if not w:
        return None
    codes = [h.get("weather_code")[i] for i in pick if i < len(h.get("weather_code") or []) and h["weather_code"][i] is not None]
    pops = [h.get("precipitation_probability")[i] for i in pick
            if i < len(h.get("precipitation_probability") or []) and h["precipitation_probability"][i] is not None]
    return {"wind": sum(w) / len(w), "temp": sum(t) / len(t) if t else None,
            "code": max(codes, key=lambda c: (_severity(c), c)) if codes else None, "precip": max(pops) if pops else None}


# WMO weather codes (Open-Meteo) -> (icon, word). The worst sky over the first three hours is the one shown.
SKY = {0: ("☀️", "Clear"), 1: ("🌤️", "Mostly clear"), 2: ("⛅", "Partly cloudy"), 3: ("☁️", "Cloudy"),
       45: ("🌫️", "Fog"), 48: ("🌫️", "Fog"), 51: ("🌦️", "Drizzle"), 53: ("🌦️", "Drizzle"), 55: ("🌧️", "Drizzle"),
       56: ("🌧️", "Freezing drizzle"), 57: ("🌧️", "Freezing drizzle"), 61: ("🌧️", "Light rain"), 63: ("🌧️", "Rain"),
       65: ("🌧️", "Heavy rain"), 66: ("🌧️", "Freezing rain"), 67: ("🌧️", "Freezing rain"), 71: ("🌨️", "Light snow"),
       73: ("🌨️", "Snow"), 75: ("❄️", "Heavy snow"), 77: ("🌨️", "Snow grains"), 80: ("🌦️", "Showers"),
       81: ("🌧️", "Showers"), 82: ("⛈️", "Heavy showers"), 85: ("🌨️", "Snow showers"), 86: ("❄️", "Heavy snow showers"),
       95: ("⛈️", "Thunderstorms"), 96: ("⛈️", "Thunderstorms"), 99: ("⛈️", "Thunderstorms")}


def _severity(code) -> int:
    c = int(code)
    return 3 if c >= 71 and c not in (80, 81, 82, 95, 96, 99) else 2 if c >= 51 else 1 if c >= 45 else 0 if c <= 3 else 0


def label(wx: Optional[Dict]) -> str:
    """'☀️ Clear 59°F · 💨 6 mph', '🌧️ Rain 44°F · 💨 17 mph ⚠️', '🏟️ Dome' -- ⚠️ when the model adjusts for it."""
    if not wx:
        return "—"
    if wx.get("indoor"):
        return "🏟️ Dome"
    icon, word = SKY.get(int(wx["code"]), ("", "")) if wx.get("code") is not None else ("", "")
    bits = [" ".join(x for x in (icon, word) if x)]
    if wx.get("temp") is not None:
        bits[0] = (bits[0] + f" {wx['temp']:.0f}°F").strip()
        if wx["temp"] <= COLD_F:
            bits[0] += " 🥶"
    if wx.get("wind") is not None:
        bits.append(("💨 " if wind_bucket(wx["wind"]) is not None else "") + f"{wx['wind']:.0f} mph")
    if wx.get("precip") is not None and wx["precip"] >= 40 and (wx.get("code") or 0) < 51:
        bits.append(f"{wx['precip']:.0f}% chance of rain")
    out = " · ".join(b for b in bits if b) or "—"
    impacted = wind_bucket(wx.get("wind")) is not None or (wx.get("temp") is not None and wx["temp"] <= COLD_F)
    return out + (" ⚠️" if impacted else "")


def label_for(sport: str, date_str: str, game: str) -> str:
    """The weather label for a game label 'Away @ Home' on the date (football only; '' otherwise)."""
    if sport not in PATHS or " @ " not in str(game or ""):
        return ""
    try:
        away, home = [x.strip() for x in str(game).split(" @ ", 1)]
        return label(for_game(slate(sport, date_str), home, away))
    except Exception:                                           # noqa: BLE001
        return "—"


def _names(team: Dict) -> set:
    t = team.get("team") or {}
    return {str(x).lower() for x in (t.get("abbreviation"), t.get("displayName"), t.get("shortDisplayName"),
                                     t.get("location"), t.get("name")) if x}


def slate(sport: str, date_str: str, fetch: Callable = _http) -> list:
    """[{"names": {home team names}, "away": {away team names}, "indoor", "wind", "temp", "venue"}] for the date."""
    if sport not in PATHS:
        return []

    def go():
        path, extra = PATHS[sport]
        d = fetch(ESPN.format(path=path), dict(extra, dates=date_str.replace("-", ""))) or {}
        out = []
        todo = []
        for ev in d.get("events") or []:
            comp = (ev.get("competitions") or [{}])[0]
            teams = comp.get("competitors") or []
            home = next((t for t in teams if t.get("homeAway") == "home"), None)
            away = next((t for t in teams if t.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            v = comp.get("venue") or {}
            rec = {"home": _names(home), "away": _names(away), "indoor": bool(v.get("indoor")),
                   "venue": v.get("fullName"), "wind": None, "temp": None}
            if not rec["indoor"]:
                todo.append((rec, v.get("address") or {}, ev.get("date")))
            out.append(rec)

        def fill(job):                                          # one geocode + forecast per outdoor game, in parallel
            rec, addr, when = job
            try:
                ko = datetime.fromisoformat(str(when).replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                return
            ll = _geocode(addr.get("city"), addr.get("state"), fetch) if addr.get("city") else None
            if ll:
                rec.update(_forecast(ll[0], ll[1], ko, fetch) or {})
        if todo:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=8) as ex:
                list(ex.map(fill, todo))
        return out
    key = ("slate", sport, date_str)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < hit[2]:
        return hit[1]
    out = go() or []
    if out:                                                     # a slate missing an outdoor game's weather retries soon
        complete = all(g["indoor"] or g.get("wind") is not None for g in out)
        _CACHE[key] = (time.time(), out, TTL if complete else 300)
    return out


def for_game(wx_slate: list, home: str, away: str, home_name: Optional[str] = None,
             away_name: Optional[str] = None) -> Optional[Dict]:
    """The slate entry for one game, matched on any of the teams' names or abbreviations."""
    def norm(x):
        return str(x or "").lower().strip()
    hs, as_ = {norm(home), norm(home_name)} - {""}, {norm(away), norm(away_name)} - {""}
    alias = {"la": "lar", "wsh": "was", "was": "wsh", "lar": "la", "jax": "jac", "jac": "jax"}
    hs |= {alias[h] for h in hs if h in alias}
    as_ |= {alias[a] for a in as_ if a in alias}
    for g in wx_slate or []:
        if (hs & g["home"]) and (as_ & g["away"]):
            return g
    return None
