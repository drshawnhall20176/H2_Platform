"""
news.py -- the news that matters for a game or a player today, on the game and player cards (Nov 26).

Owner, Nov 26: "add to the game and player cards site wide a new section that pulls the important news bits that are
relevant to the game or players of the day."

Two sources, both ESPN (the injury report already comes from there):
  * the league's news feed (site.api.espn.com .../{league}/news): each article's headline, short summary, publish time
    and link, tagged with the teams and players it is about -- kept when a tag (or the headline) names the card's
    teams or player and it was published in the last HOURS;
  * the injury report's own notes (injury_check): the latest short note on each flagged player.
Headline, a one-line summary and a link back to the source -- never the article itself. Cached TTL seconds; a feed
that can't be reached leaves the section out.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

URL = "https://site.api.espn.com/apis/site/v2/sports/{path}/news"
TTL = 900
HOURS = 72
SUMMARY_MAX = 180
_cache: Dict[str, tuple] = {}


def _paths():
    import injury_check as IC
    return IC.LEAGUES


def _norm(s) -> str:
    import injury_check as IC
    return IC._norm(s)


def _get_json(sport: str, limit: int = 100) -> Dict:
    import requests
    path = _paths().get(sport)
    if not path:
        return {}
    return requests.get(URL.format(path=path), params={"limit": limit}, timeout=8).json() or {}


def parse(js: Dict) -> List[Dict]:
    """[{headline, summary, published (UTC datetime or None), url, teams [names], athletes [names]}], newest first."""
    out = []
    for a in (js or {}).get("articles") or []:
        head = str(a.get("headline") or "").strip()
        if not head:
            continue
        try:
            pub = datetime.fromisoformat(str(a.get("published") or "").replace("Z", "+00:00"))
        except ValueError:
            pub = None
        cats = a.get("categories") or []
        summary = str(a.get("description") or "").strip()
        if len(summary) > SUMMARY_MAX:
            summary = summary[:SUMMARY_MAX].rsplit(" ", 1)[0] + "…"
        out.append({"headline": head, "summary": summary, "published": pub,
                    "url": (((a.get("links") or {}).get("web") or {}).get("href")) or "",
                    "teams": [c.get("description") for c in cats if c.get("type") == "team" and c.get("description")],
                    "athletes": [c.get("description") for c in cats
                                 if c.get("type") == "athlete" and c.get("description")]})
    out.sort(key=lambda x: x["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out


def items(sport: str, get=None, now: Optional[float] = None) -> List[Dict]:
    """The league's recent news, cached TTL seconds; [] when the feed can't be reached."""
    now = time.time() if now is None else now
    hit = _cache.get(sport)
    if hit and now - hit[0] < TTL:
        return hit[1]
    try:
        got = parse((get or _get_json)(sport))
    except Exception:                                           # noqa: BLE001 -- news is a bonus
        got = []
    _cache[sport] = (now, got)
    return got


def _recent(it: Dict, hours: float, now: datetime) -> bool:
    return it["published"] is not None and (now - it["published"]).total_seconds() <= hours * 3600


COLLEGE = ("NCAAMB", "NCAAF")                                   # nicknames repeat across schools: tags only


BROAD = 4                                                       # tagged with more teams = a league-wide roundup


def _named_in_headline(it: Dict, team: str) -> bool:
    head = " " + _norm(it["headline"]) + " "
    words = _norm(team).split(" ")
    if not words or not words[0]:
        return False
    if f" {' '.join(words)} " in head:
        return True
    nick = words[-1]
    return len(nick) > 3 and f" {nick} " in head


def _team_hit(it: Dict, team: str, sport: str = "") -> bool:
    import injury_check as IC
    want = IC._team_keys(team)
    if not want:
        return False
    if len(it["teams"]) > BROAD:                                # odds for every game, draft order, power rankings
        if sport in COLLEGE:
            return f" {_norm(team)} " in " " + _norm(it["headline"]) + " "
        return _named_in_headline(it, team)
    for t in it["teams"]:
        if want & IC._team_keys(t) or _norm(t) == _norm(team):
            return True
    if sport in COLLEGE:
        return False
    head = " " + _norm(it["headline"]) + " "
    nick = _norm(team).split(" ")[-1] if _norm(team) else ""
    return bool(nick) and len(nick) > 3 and f" {nick} " in head


def for_game(news: Iterable[Dict], away: str, home: str, hours: float = HOURS, n: int = 5,
             now: Optional[datetime] = None, sport: str = "") -> List[Dict]:
    now = now or datetime.now(timezone.utc)
    return [it for it in news if _recent(it, hours, now)
            and (_team_hit(it, away, sport) or _team_hit(it, home, sport))][:n]


def for_player(news: Iterable[Dict], name: str, team: Optional[str] = None, hours: float = HOURS * 2, n: int = 4,
               now: Optional[datetime] = None, sport: str = "") -> List[Dict]:
    """His own news first (tagged with him, or naming him), then his team's, up to n."""
    now = now or datetime.now(timezone.utc)
    who = _norm(name)
    last = who.split(" ")[-1] if who else ""
    mine, team_items = [], []
    for it in news:
        if not _recent(it, hours, now):
            continue
        text = " " + _norm(it["headline"] + " " + it["summary"]) + " "
        if any(_norm(a) == who for a in it["athletes"]) or (who and f" {who} " in text):
            mine.append(dict(it, about="him"))
        elif team and _team_hit(it, team, sport):
            team_items.append(dict(it, about="team"))
    return (mine + team_items)[:n]


def injury_notes(sport: str, teams: Iterable[str] = (), player: Optional[str] = None,
                 report: Optional[List[Dict]] = None) -> List[Dict]:
    """The injury report's latest note for the flagged players of the teams (or for one player)."""
    import injury_check as IC
    try:
        rep = report if report is not None else IC.entries(sport)
    except Exception:                                           # noqa: BLE001
        return []
    out = []
    if player:
        out = [e for e in rep if _norm(e.get("name")) == _norm(player)]
    else:
        for t in teams:
            out += IC.for_team(sport, t, rep)
    return [e for e in out if e.get("comment")]


def _ago(pub: Optional[datetime], now: Optional[datetime] = None) -> str:
    if pub is None:
        return ""
    s = ((now or datetime.now(timezone.utc)) - pub).total_seconds()
    if s < 3600:
        return f"{max(1, int(s // 60))}m ago"
    if s < 86400:
        return f"{int(s // 3600)}h ago"
    return f"{int(s // 86400)}d ago"


def markdown(news: List[Dict], notes: List[Dict]) -> str:
    lines = []
    for e in notes:
        icon = "🚑" if e.get("status") == "out" else "⚠️"
        lines.append(f"- {icon} **{e.get('name')}** ({e.get('label') or e.get('status')}): {e.get('comment')}")
    for it in news:
        link = f" · [ESPN]({it['url']})" if it.get("url") else ""
        tag = " · *team news*" if it.get("about") == "team" else ""
        lines.append(f"- **{it['headline']}** · {_ago(it['published'])}{tag}{link}"
                     + (f"  \n  {it['summary']}" if it.get("summary") else ""))
    return "\n".join(lines)


# --------------------------------------------------------------------------- this game's own story (Nov 26)
# Owner: "I would expect the news to be tagged to the specific game." ESPN writes one story per game -- the preview
# before it starts, the recap once it's final -- on the game's summary (.../summary?event=<id>, key "article").
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/{path}/summary"
_board: Dict[str, tuple] = {}
_story: Dict[str, tuple] = {}


def _get_url(url: str, params: Dict) -> Dict:
    import requests
    return requests.get(url, params=params, timeout=8).json() or {}


def _names(team: Dict) -> set:
    return {_norm(team.get(k)) for k in ("displayName", "shortDisplayName", "location", "abbreviation", "name")
            if team.get(k)}


def _same_team(ours: str, theirs: Dict) -> bool:
    o = _norm(ours)
    if not o:
        return False
    names = _names(theirs)
    full = _norm(theirs.get("displayName"))
    return o in names or (full and (full.startswith(o + " ") or o.startswith(full + " ")))


def find_event_id(board: Dict, away: str, home: str) -> Optional[str]:
    """The ESPN event id of away @ home on a scoreboard (either order: neutral sites list them either way)."""
    for e in (board or {}).get("events") or []:
        teams = [c.get("team") or {} for c in ((e.get("competitions") or [{}])[0].get("competitors") or [])]
        if len(teams) != 2:
            continue
        a, b = teams
        if (_same_team(away, a) and _same_team(home, b)) or (_same_team(away, b) and _same_team(home, a)):
            return str(e.get("id"))
    return None


def parse_story(summary: Dict) -> Optional[Dict]:
    a = (summary or {}).get("article") or {}
    head = str(a.get("headline") or "").strip()
    if not head:
        return None
    try:
        pub = datetime.fromisoformat(str(a.get("published") or "").replace("Z", "+00:00"))
    except ValueError:
        pub = None
    summ = str(a.get("description") or "").strip().lstrip("—").strip()
    if len(summ) > SUMMARY_MAX:
        summ = summ[:SUMMARY_MAX].rsplit(" ", 1)[0] + "…"
    kind = str(a.get("type") or "").strip() or "Story"
    return {"headline": head, "summary": summ, "published": pub, "kind": kind,
            "url": (((a.get("links") or {}).get("web") or {}).get("href")) or ""}


def game_story(sport: str, away: str, home: str, day: Optional[str] = None, get=None,
               now: Optional[float] = None) -> Optional[Dict]:
    """ESPN's preview (or recap) of this one game; None when there isn't one or ESPN can't be reached."""
    path = _paths().get(sport)
    if not path or not away or not home:
        return None
    get = get or _get_url
    now = time.time() if now is None else now
    params = {"dates": str(day).replace("-", "")[:8]} if day else {}
    if sport == "NCAAMB":
        params["groups"] = "50"                                 # every D-I game, not just the featured ones
    if sport == "NCAAF":
        params["groups"] = "80"
    bkey = f"{sport}:{params.get('dates', '')}"
    try:
        hit = _board.get(bkey)
        if hit and now - hit[0] < TTL:
            board = hit[1]
        else:
            board = get(SCOREBOARD.format(path=path), dict(params, limit=500))
            _board[bkey] = (now, board)
        eid = find_event_id(board, away, home)
        if not eid:
            return None
        hit = _story.get(eid)
        if hit and now - hit[0] < TTL:
            return hit[1]
        story = parse_story(get(SUMMARY.format(path=path), {"event": eid}))
        _story[eid] = (now, story)
        return story
    except Exception:                                           # noqa: BLE001 -- news is a bonus
        return None


def story_markdown(s: Dict) -> str:
    icon = "📝" if s["kind"].lower() == "recap" else "🔎"
    link = f" · [ESPN {s['kind'].lower()}]({s['url']})" if s.get("url") else ""
    when = f" · {_ago(s['published'])}" if s.get("published") else ""
    return (f"{icon} **This game — {s['headline']}**{when}{link}"
            + (f"  \n{s['summary']}" if s.get("summary") else ""))


def render_game(sport: str, away: str, home: str, day: Optional[str] = None) -> None:
    """The game card's 📰 News: ESPN's own preview / recap of this game, then both teams' injury notes and their
    headlines from the last three days."""
    import streamlit as st
    story = game_story(sport, away, home, day)
    news = for_game(items(sport), away, home, sport=sport)
    if story:
        news = [it for it in news if _norm(it["headline"]) != _norm(story["headline"])]
    notes = injury_notes(sport, (away, home))[:6]
    st.markdown("**📰 News**")
    if not story and not news and not notes:
        st.caption("No game preview, team news or injury notes in the last three days.")
        return
    if story:
        st.markdown(story_markdown(story))
    if news or notes:
        if story:
            st.markdown("*Team news and injury notes*")
        st.markdown(markdown(news, notes))
    st.caption("ESPN's write-up of this game (the preview before it starts, the recap once it's final), then the "
               "injury notes and headlines that name these teams, newest first. Context, not a pick — open the link "
               "for the full story.")


def render_player(sport: str, name: str, team: Optional[str] = None) -> None:
    """The player card's 📰 News: his injury note, then his headlines (his team's when he has none)."""
    import streamlit as st
    news = for_player(items(sport), name, team, sport=sport)
    notes = injury_notes(sport, player=name)
    st.markdown("**📰 News**")
    if not news and not notes:
        st.caption("No news on him or his team in the last six days.")
        return
    st.markdown(markdown(news, notes))
    st.caption("ESPN's injury note and recent headlines about him (team news when there's none on him). Context, "
               "not a pick.")
