"""
h2h.py — "Last meetings": how two teams' recent games against each other went (Nov 24).

Owner: "it should be expanded to include h2h in the game lab as well." Each game on today's boards gets a short line —
"Duke won 2 of 3 (by 6.3 a game)" — from the two teams' meetings in the last ~14 months (this season and last), read
from ESPN's public team schedules.

It is shown as context, not folded into the chances. Tested Nov 24 (research/h2h_test.py): on 5,401 graded NBA props
the player's average against tonight's opponent added nothing beyond the earned chance (coefficient 0.05 ± 0.07), and
prior-meeting margins against the spread were a coin flip in NBA, NHL and college basketball games. The model already
prices the opponent's defense; a few old games against one team are mostly noise.

The morning job (daily-review: `python h2h.py refresh`) saves one blob per league and day, so the pages never call ESPN.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

LAST = "Last meetings"
SITE = {"NBA": "basketball/nba", "NHL": "hockey/nhl", "NCAAMB": "basketball/mens-college-basketball",
        "NFL": "football/nfl", "NCAAF": "football/college-football"}
FOOTBALL = ("NFL", "NCAAF")
WINDOW_DAYS = 420
KIND = "h2h"


def _get(url: str, params: Optional[Dict] = None, http=None):
    if http is None:
        import requests
        http = requests.get
    for _ in range(2):
        try:
            r = http(url, params=params or {}, timeout=15)
            if getattr(r, "status_code", 200) == 200:
                return r.json()
        except Exception:                                       # noqa: BLE001
            time.sleep(0.5)
    return None


def _seasons(league: str, day: str) -> List[str]:
    d = date.fromisoformat(day)
    if league in FOOTBALL:                                      # football seasons are named by their start year
        cur = d.year if d.month >= 3 else d.year - 1
    else:                                                       # basketball / hockey by the year they end
        cur = d.year + 1 if d.month >= 8 else d.year
    return [str(cur), str(cur - 1)]


def team_ids(league: str, http=None) -> Dict[str, str]:
    j = _get(f"https://site.api.espn.com/apis/site/v2/sports/{SITE[league]}/teams", {"limit": 1000}, http) or {}
    out: Dict[str, str] = {}
    for t in ((j.get("sports") or [{}])[0].get("leagues") or [{}])[0].get("teams") or []:
        t = t.get("team") or {}
        for k in ("displayName", "abbreviation", "shortDisplayName", "location"):
            if t.get(k):
                out.setdefault(str(t[k]).lower(), str(t.get("id")))
    return out


def schedule(league: str, tid: str, season: str, http=None) -> List[Dict]:
    """Completed games for one team: [{date, opp, margin (this team's points minus the opponent's)}]."""
    j = _get(f"https://site.api.espn.com/apis/site/v2/sports/{SITE[league]}/teams/{tid}/schedule",
             {"season": season}, http) or {}
    out = []
    for e in j.get("events") or []:
        try:
            c = e["competitions"][0]
            if not ((c.get("status") or {}).get("type") or {}).get("completed", True):
                continue
            me = next(x for x in c["competitors"] if str(x["id"]) == str(tid))
            op = next(x for x in c["competitors"] if str(x["id"]) != str(tid))

            def sc(x):
                s = x.get("score")
                return float(s["value"]) if isinstance(s, dict) else float(s)
            out.append({"date": str(e["date"])[:10], "opp": str(op["id"]), "margin": sc(me) - sc(op)})
        except Exception:                                       # noqa: BLE001
            continue
    return out


def describe(home: str, away: str, meetings: List[Dict], league: str = "") -> str:
    """meetings: the HOME team's games against this opponent, newest first (margin from the home team's side)."""
    if not meetings:
        return "No meetings in the last year"
    unit = "goals" if league == "NHL" else "pts"
    hw = sum(1 for m in meetings if m["margin"] > 0)
    aw = sum(1 for m in meetings if m["margin"] < 0)
    avg = sum(m["margin"] for m in meetings) / len(meetings)
    last = meetings[0]
    lw = home if last["margin"] > 0 else away if last["margin"] < 0 else "Tie"
    try:
        when = datetime.fromisoformat(last["date"]).strftime("%b %-d, %Y")
    except ValueError:
        when = last["date"]
    n = len(meetings)
    if hw == aw:
        head = f"Split {hw}–{aw}"
    else:
        lead = home if hw > aw else away
        head = f"{lead} won {max(hw, aw)} of {n}"
    side = home if avg > 0 else away
    return (f"{head} (by {abs(avg):.1f} {unit} a game{' for ' + side if hw == aw and avg else ''}) · last: "
            f"{lw} by {abs(last['margin']):g}, {when}" if last["margin"] else f"{head} · last: tie, {when}")


def build(league: str, games: List[Dict], day: str, http=None) -> Dict[str, str]:
    """{"home|away": text} for today's games (dicts with home / away names). One schedule call per home team and
    season; the home team's schedule holds every meeting."""
    ids = team_ids(league, http)
    lo = (date.fromisoformat(day) - timedelta(days=WINDOW_DAYS)).isoformat()
    out: Dict[str, str] = {}
    cache: Dict = {}
    for g in games:
        home, away = g.get("home"), g.get("away")
        hid, aid = ids.get(str(home or "").lower()), ids.get(str(away or "").lower())
        if not hid or not aid:
            continue
        ms: List[Dict] = []
        for s in _seasons(league, day):
            if (hid, s) not in cache:
                cache[(hid, s)] = schedule(league, hid, s, http)
            ms += [m for m in cache[(hid, s)] if m["opp"] == aid and lo <= m["date"] < day]
        seen, uniq = set(), []
        for m in sorted(ms, key=lambda m: m["date"], reverse=True):
            if m["date"] not in seen:
                seen.add(m["date"])
                uniq.append(m)
        out[f"{home}|{away}"] = describe(home, away, uniq[:4], league)
    return out


def refresh(day: Optional[str] = None, leagues=tuple(SITE), load=None, save=None, http=None, out=print) -> Dict[str, int]:
    """Morning job: today's (and tomorrow's early) games per league -> one saved blob per league and day."""
    import model_store as MS
    if day is None:
        import pytz
        day = datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
    load = load or (lambda lg: MS.load_game_picks(lg, ungraded=True))
    save = save or (lambda items: MS.save_blobs(KIND, items))
    done = {}
    for lg in leagues:
        try:
            games = [p for p in load(lg) if str(p.get("kickoff") or "")[:10] in
                     (day, (date.fromisoformat(day) + timedelta(days=1)).isoformat())]
            got = build(lg, games, day, http) if games else {}
            if got:
                save({f"{lg}|{day}": json.dumps(got)})
            done[lg] = len(got)
        except Exception as exc:                                # noqa: BLE001 — one league never stops the rest
            out(f"{lg}: h2h failed ({type(exc).__name__}: {str(exc)[:120]})")
            done[lg] = 0
    out(f"h2h saved: {done}")
    return done


_MEM: Dict[str, tuple] = {}


def lookup(league: str, home: str, away: str, day: Optional[str] = None, load: Optional[Callable] = None) -> str:
    """The saved "Last meetings" line for one game ("—" when the morning job hasn't covered it). One read per
    league and day, kept 10 minutes."""
    import pytz
    day = day or datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
    k = f"{league}|{day}"
    hit = _MEM.get(k)
    if hit is None or time.time() - hit[0] > 600:
        try:
            if load is None:
                import model_store as MS
                raw = MS.load_blobs(KIND, [k]).get(k)
                yday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
                if not raw:                                     # a late game saved under yesterday's run
                    raw = MS.load_blobs(KIND, [f"{league}|{yday}"]).get(f"{league}|{yday}")
            else:
                raw = load(k)
            data = json.loads(raw) if raw else {}
        except Exception:                                       # noqa: BLE001
            data = {}
        hit = (time.time(), data)
        _MEM[k] = hit
    return hit[1].get(f"{home}|{away}", "—")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "refresh":
        refresh(sys.argv[2] if len(sys.argv) > 2 else None)
