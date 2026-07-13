"""
podcast.py — generate a full ~hour show rundown for H2 Sports in the hosts' voices.

Two hosts:
  • Dr. Hall  — the numbers/model voice (does the homework, explains the "why")
  • Deezy     — the everyday-man, social-native skeptic (gut checks, hot takes, GOAT debates)

Format is talking-points + suggested host lines as CUES, never word-for-word (real hosts riff).
The model supplies what the model knows (selections, results, CLV); the hosts supply what only
humans know (ejections, vibes, hot takes) via clearly-labeled FILL prompts. The tool never
fabricates game news it can't verify.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

# A beat is a dict: {"type": "line"|"note"|"fill", "who": "Dr. Hall"|"Deezy"|None, "text": str}
def _line(who, text):  # suggested host line (a cue to riff on, not a script)
    return {"type": "line", "who": who, "text": text}


def _note(text):       # producer direction / talking point
    return {"type": "note", "who": None, "text": text}


def _fill(text):       # blank for the hosts to fill live (chaos/news the model can't verify)
    return {"type": "fill", "who": None, "text": text}


# --- rotating teaching library: Deezy-doesn't-get-it -> Dr. Hall explains -> Deezy lands it -
TEACHING_SEGMENTS = [
    {
        "topic": "What CLV is (why we 'win' even when the bet loses)",
        "beats": [
            _line("Deezy", "Dad, you keep sayin' we 'beat the number' on a bet that LOST. That makes zero sense. We lost. L. Loss."),
            _line("Dr. Hall", "Right, but here's the thing — closing-line value. We took Judge at +270. By game time the whole market moved to +220. We got a better price than everyone who bet it later."),
            _line("Deezy", "Okay but the ball didn't leave the yard. We still lost the money."),
            _line("Dr. Hall", "One night, yeah. But if we consistently get better numbers than where the line closes, the math says we win long-term — even with cold nights mixed in. CLV is the proof we're on the right side."),
            _note("Land it: results are one night of luck; beating the close, over and over, is skill. That's why we track CLV, not just W/L."),
        ],
    },
    {
        "topic": "Why parlays quietly bleed you",
        "beats": [
            _line("Deezy", "Parlays are where the money's at though! Hit a 5-leg and we're eating good."),
            _line("Dr. Hall", "And how often does that 5-leg hit? Every leg multiplies the book's juice against you. A bet that's smart as a single can turn into a money-loser the second you stack it."),
            _line("Deezy", "So you're telling me no parlays, ever? That's boring, bro."),
            _line("Dr. Hall", "I'm saying know what you're doing. Parlays are entertainment with a tax. Singles are where the actual edge lives. Bet the fun one small, grind the singles."),
            _note("Land it: the books push parlays because they're the house's best product. Sharps mostly bet straight."),
        ],
    },
    {
        "topic": "Barrel rate and 'due to homer'",
        "beats": [
            _line("Deezy", "What in the world is a 'barrel'? Sounds like somethin' on Deadliest Catch."),
            _line("Dr. Hall", "It's the perfect mix of exit velo and launch angle — the contact that turns into homers. Some guys are barreling balls at an elite rate but the homers haven't shown up yet."),
            _line("Deezy", "So the dude's been robbed and is about to pop off?"),
            _line("Dr. Hall", "Statistically, his power's real even if the box score doesn't show it yet. That's the model finding a bat before the casuals notice the name."),
            _note("Land it: process over results applies to hitters too — barrels predict future homers better than recent homers do."),
        ],
    },
    {
        "topic": "Platoon splits (lefty/righty)",
        "beats": [
            _line("Deezy", "Why does it matter if the pitcher's a lefty? A 95 is a 95."),
            _line("Dr. Hall", "Hitters see the ball way better against the opposite hand. A lefty bat facing a righty? The breaking stuff comes toward him, not away. It's a real, measurable edge."),
            _line("Deezy", "Aight so we just want all our guys on the right side of that?"),
            _line("Dr. Hall", "When the platoon edge lines up with a good bat in a good park, that's a stacked deck. That's the spots we hunt."),
            _note("Land it: handedness is one of the most reliable, least-sexy edges in the sport."),
        ],
    },
    {
        "topic": "Park and weather (why the ballpark matters)",
        "beats": [
            _line("Deezy", "Bro it's the same game in every stadium, what's the weather got to do with it?"),
            _line("Dr. Hall", "Hot air is thinner, ball carries farther. Wind blowing out turns warning-track outs into souvenirs. Coors in July is a different sport than a cold night by the bay."),
            _line("Deezy", "So we just bet every homer when it's hot and windy?"),
            _line("Dr. Hall", "It's a thumb on the scale, not the whole hand. Stack it with a good bat and a platoon edge and now the weather's pushing a play that was already live."),
            _note("Land it: park + weather is a real, physics-based input — but it nudges, it doesn't decide."),
        ],
    },
    {
        "topic": "Variance and cold streaks (the board didn't 'fail' you)",
        "beats": [
            _line("Deezy", "Real talk — the board went 0-fer the other night. The comments were BRUTAL."),
            _line("Dr. Hall", "Yep, and that's baseball. A genuinely good process has losing nights all the time. If a model never had a cold night, it'd be a scam."),
            _line("Deezy", "Try explainin' THAT to the group chat at 11pm."),
            _line("Dr. Hall", "That's literally why we teach this. Judge us over fifty plays, not one slate. The night the board looks dumb is the night discipline matters most."),
            _note("Land it: variance is the price of admission. Bankroll management and patience are the actual skills."),
        ],
    },
]


def rotating_teaching(date_str: str) -> Dict:
    """Deterministically rotate the teaching topic by date, so each show gets a fresh one."""
    try:
        doy = datetime.fromisoformat(date_str).timetuple().tm_yday
    except (ValueError, TypeError):
        doy = 0
    return TEACHING_SEGMENTS[doy % len(TEACHING_SEGMENTS)]


# --- per-selection banter beats --------------------------------------------
_DEEZY_PUSH = {
    "Batter HR": "{prob}% to homer? So you're tellin' me he does NOT homer {inv}% of the time and we're hyped?",
    "Batter Total Bases": "Total bases over 1.5 — so he needs a double or two singles. What if he just walks twice and we're cooked?",
    "Batter Total Hits": "One hit. We're trusting a big-leaguer to get ONE hit. Groundbreaking, Dad.",
    "Batter Strikeouts": "You want me to root for a strikeout? That feels illegal.",
    "Pitcher Strikeouts": "So this dude just mows down the whole lineup? What if he gets shelled in the 3rd and they yank him?",
    "Pitcher Outs": "Outs? We're betting on a guy to record OUTS? Riveting television right here, folks.",
    "Pitcher Walks": "Walks?? Now we're handicappin' ball four. Who hurt you, Dad?",
}


def selection_beats(p: Dict) -> List[Dict]:
    """A talking-points beat for one selection: Dr. Hall's case -> Deezy's gut check -> reality."""
    prob = round(p.get("ModelProb", 0) * 100)
    inv = 100 - prob
    push = _DEEZY_PUSH.get(p.get("Market"), "Break this one down for me, Doc.").format(prob=prob, inv=inv)
    opp = f" vs {p['Opp']}" if p.get("Opp") else ""
    fair = f"{p['Fair']:+d}" if p.get("Fair") is not None else "—"
    if p.get("EV") is not None:
        live = f"{p['LivePrice']:+d}" if p.get("LivePrice") is not None else "—"
        price_beat = (f"Live price is {live} — that's about {p['EV']:+.1f}% value by our math. "
                      f"Model has it ~{prob}%. That's a real edge at this number, not just a lean.")
    else:
        price_beat = (f"Fair price is around {fair}. Model has it ~{prob}% — a lean we like, not a "
                      f"lock. We only fire if the live number beats {fair}.")
    return [
        _note(f"SELECTION: {p['Player']} ({p['Team']}) — {p['Market']} {p['Side']} {p['Line']:g}{opp}  "
              f"[conviction {p.get('Conviction', 0):.1f}x]"),
        _line("Dr. Hall", f"Here's the case: {p.get('Why', 'the model likes the matchup')}."),
        _line("Deezy", push),
        _line("Dr. Hall", price_beat),
        _note("Reality check (say it every time): interesting, not guaranteed. Check the price."),
    ]


# --- full script assembly --------------------------------------------------
def assemble_script(date_str: str, headliners: List[Dict], sleepers: List[Dict],
                    retro: Optional[Dict], caught_homers: Optional[List[Dict]]) -> List[Dict]:
    """Return ordered sections: {title, time, beats[]}. Pure — no Streamlit, fully testable."""
    teaching = rotating_teaching(date_str)
    S = []

    # 1) Yesterday in Review (the cold open)
    review = [
        _line("Deezy", "Yo what's good everybody, welcome back to H2 Sports! Before we touch tonight — "
                       "we GOTTA talk about last night, because it was a MOVIE."),
        _fill("⚡ Wild moment of the night? (ejection, walk-off, meltdown — whatever you actually saw)"),
        _fill("⚡ Who let us down? (the team/player that went ice cold)"),
        _fill("⚡ Any robbery? (a great play, a blown call, something that made you yell)"),
    ]
    if retro and retro.get("graded"):
        hr = retro.get("hit_rate")
        review.append(_note(f"THE BOARD, HONESTLY: of the plays we'd have flagged, "
                            f"{retro['hits']}/{retro['graded']} hit"
                            + (f" ({hr*100:.0f}%)." if hr is not None else ".")))
        if caught_homers:
            names = ", ".join(f"{c['Player']} (ranked #{c['Rank']})" for c in caught_homers[:3])
            review.append(_line("Dr. Hall", f"And a little flex — the model had {names} as top power "
                                            f"plays before the game, and they went deep. That's the model "
                                            f"finding bats before the names pop."))
        review.append(_line("Deezy", "Okay but we also got cooked on some, keep it a buck."))
        review.append(_line("Dr. Hall", "Always keep it a buck. That's baseball — one night's variance. "
                                        "We'll get into why a cold night isn't a broken board later."))
    else:
        review.append(_fill("📊 THE BOARD: results not pulled yet — recap how last night's flagged plays did "
                            "(this fills in automatically once yesterday's games are final)."))
    review.append(_note("Reframe for the subs: nights like that are baseball, not a broken model. "
                        "Acknowledge the pain, then move on — don't dwell, don't make excuses."))
    S.append({"title": "🎬 Yesterday in Review", "time": "0:00–8:00", "beats": review})

    # 2) Slate overview
    overview = [
        _line("Dr. Hall", "Alright, enough cryin' about yesterday. Let's set the table for tonight."),
        _fill("🗓️ Headline storyline of the slate? (marquee arm, big series, a weather game)"),
        _line("Deezy", "How many games we workin' with and what's the vibe — pitchers' duels or are we "
                       "hittin' bombs tonight?"),
        _note("Dr. Hall: give the shape of the slate — number of games, any obvious park/weather spots, "
              "the one matchup you're most fired up about."),
    ]
    S.append({"title": "🗒️ Slate Overview", "time": "8:00–13:00", "beats": overview})

    # 3) Top selections (the meat)
    top_beats = [_line("Deezy", "Aight, the people came for the picks. What we likin' tonight?"),
                 _note("These are our top conviction leans across markets. Work each as a beat: "
                       "Dr. Hall makes the case, Deezy gut-checks it, land the reality check.")]
    for p in headliners:
        top_beats += selection_beats(p)
    if not headliners:
        top_beats.append(_fill("No selections loaded — pick a date with scheduled games."))
    S.append({"title": "⭐ Tonight's Top Selections", "time": "13:00–35:00", "beats": top_beats})

    # 4) Sleepers & fades
    sleeper_beats = [
        _line("Deezy", "Now hit me with the under-the-radar stuff — the ones nobody's talkin' about."),
        _note("Interesting plays that didn't crack the headline list — a sleeper bat, a fade, a "
              "weather/platoon angle worth a mention. Lighter touch than the top tier."),
    ]
    for p in sleepers:
        opp = f" vs {p['Opp']}" if p.get("Opp") else ""
        sleeper_beats.append(_line("Dr. Hall",
            f"Keep an eye on {p['Player']} ({p['Team']}) — {p['Market']} {p['Side']} {p['Line']:g}{opp}. "
            f"{p.get('Why', 'quietly interesting matchup')}. Not a headliner, but a name to watch."))
    if not sleepers:
        sleeper_beats.append(_note("No clear second-tier plays tonight — skip or riff on a storyline instead."))
    S.append({"title": "🔮 Sleepers & Fades", "time": "35:00–45:00", "beats": sleeper_beats})

    # 5) Teaching segment (rotating)
    teach_beats = [_note(f"TEACHING SEGMENT — “{teaching['topic']}.” Run it as banter, not a lecture.")]
    teach_beats += teaching["beats"]
    S.append({"title": f"🎓 Teaching: {teaching['topic']}", "time": "45:00–52:00", "beats": teach_beats})

    # 6) Tonight's game plan / reality check
    plan = [
        _line("Dr. Hall", "Before we bounce — how we actually playing this. These are leans, not locks. "
                          "Check the price, bet small, and we'll grade it together tomorrow."),
        _line("Deezy", "And if it goes cold? We do this whole thing again and laugh about it."),
        _note("Reinforce: we track every play honestly — CLV and results — and we own the misses on air. "
              "That's the brand."),
    ]
    S.append({"title": "🧭 Game Plan & Honest Reality Check", "time": "52:00–58:00", "beats": plan})

    # 7) Sign-off + banter button
    signoff = [
        _fill("🏀 Banter button: tonight's hot-take/GOAT debate to tease next show "
              "(LeBron/Jordan, Lamar slander, Skubal's a cheat code, etc.)"),
        _line("Deezy", "Smash that follow, hit us on the TikTok lives, and we'll see you tomorrow!"),
        _line("Dr. Hall", "Quick reminder, and we mean it: this is for entertainment. Selections we found "
                          "interesting with our reasoning — not locks, not advice. Variance is real. "
                          "Bet what you can afford, and bet responsibly."),
    ]
    S.append({"title": "👋 Sign-off", "time": "58:00–60:00", "beats": signoff})
    return S


def script_to_text(date_str: str, sections: List[Dict]) -> str:
    """Flatten sections into a copy-pasteable show doc."""
    out = [f"🎙️  H2 SPORTS — SHOW RUNDOWN · {date_str}",
           "Hosts: Dr. Hall (numbers) & Deezy (everyday man)  |  Format: talking points, riff freely", ""]
    for sec in sections:
        out.append(f"━━━ {sec['title']}  ({sec['time']}) ━━━")
        for b in sec["beats"]:
            if b["type"] == "fill":
                out.append(f"   [FILL IN] {b['text']}")
            elif b["type"] == "note":
                out.append(f"   » {b['text']}")
            else:
                out.append(f"   {b['who']}: {b['text']}")
        out.append("")
    return "\n".join(out)
