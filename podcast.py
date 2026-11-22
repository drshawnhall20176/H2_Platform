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


TEACHING_SEGMENTS_WNBA = [
    {
        "topic": "What CLV is (why we 'win' even when the bet loses)",
        "beats": [
            _line("Deezy", "Dad, you keep sayin' we 'beat the number' on a bet that LOST. That makes zero sense. We lost. L. Loss."),
            _line("Dr. Hall", "Right, but here's the thing — closing-line value. We took a points prop in the morning at one number. By tip-off the whole market moved past it. We got a better price than everyone who bet it later."),
            _line("Deezy", "Okay but the shot didn't fall. We still lost the money."),
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
        "topic": "Why recent form beats season averages",
        "beats": [
            _line("Deezy", "Why you always talkin' 'last 10 games' instead of just the season average? Ain't that more data?"),
            _line("Dr. Hall", "More data, but staler data. A role change, a new starting five, coming back from an injury — season averages blend all of that together. The last 10 games are what she's actually doing right now."),
            _line("Deezy", "So the season average is basically lying to us?"),
            _line("Dr. Hall", "Not lying — just slow. Recent form catches a hot streak or a shrinking role before the box score average does. That's the whole model, honestly: what's she actually been doing lately."),
            _note("Land it: recency isn't a gimmick, it's the model refusing to trust a number that's months out of date."),
        ],
    },
    {
        "topic": "Rotation minutes and blowout risk",
        "beats": [
            _line("Deezy", "Why'd we skip that girl, she's a walking bucket when she plays."),
            _line("Dr. Hall", "'When she plays' is doing a lot of work there. If her minutes have been inconsistent — foul trouble, a blowout, a coach shortening the bench — we can't trust the average enough to price a line on it."),
            _line("Deezy", "So no minutes, no bet, simple as that?"),
            _line("Dr. Hall", "Basically. Twelve solid minutes a night, every night, is worth more to the model than one huge outlier game off the bench. Consistency of role is its own signal."),
            _note("Land it: a rotation player with steady minutes is more projectable than a boom-or-bust bench piece, even if the bench piece has the higher ceiling."),
        ],
    },
    {
        "topic": "Variance and cold streaks (the board didn't 'fail' you)",
        "beats": [
            _line("Deezy", "Real talk — the board went 0-fer the other night. The comments were BRUTAL."),
            _line("Dr. Hall", "Yep, and that's sports betting. A genuinely good process has losing nights all the time. If a model never had a cold night, it'd be a scam."),
            _line("Deezy", "Try explainin' THAT to the group chat at 11pm."),
            _line("Dr. Hall", "That's literally why we teach this. Judge us over fifty plays, not one slate. The night the board looks dumb is the night discipline matters most."),
            _note("Land it: variance is the price of admission. Bankroll management and patience are the actual skills."),
        ],
    },
]


TEACHING_SEGMENTS_NHL = [
    {
        "topic": "What CLV is (why we 'win' even when the bet loses)",
        "beats": [
            _line("Deezy", "Dad, you keep sayin' we 'beat the number' on a bet that LOST. That makes zero sense. We lost. L. Loss."),
            _line("Dr. Hall", "Right, but here's the thing — closing-line value. We took a shots prop in the morning at one number. By puck drop the whole market moved past it. We got a better price than everyone who bet it later."),
            _line("Deezy", "Okay but the puck didn't go in. We still lost the money."),
            _line("Dr. Hall", "One night, yeah. But if we consistently get better numbers than where the line closes, the math says we win long-term — even with cold nights mixed in. CLV is the proof we're on the right side."),
            _note("Land it: results are one night of luck; beating the close, over and over, is skill. That's why we track CLV, not just W/L."),
        ],
    },
    TEACHING_SEGMENTS_WNBA[1],   # parlays
    {
        "topic": "Why recent form beats season averages",
        "beats": [
            _line("Deezy", "Why you always talkin' 'last 10 games' instead of just the season average? Ain't that more data?"),
            _line("Dr. Hall", "More data, but staler data. A line change, a new power-play unit, coming back from an injury — season averages blend all of that together. The last ten games are what he's actually doing right now."),
            _line("Deezy", "So the season average is basically lying to us?"),
            _line("Dr. Hall", "Not lying — just slow. Recent form catches a guy who got bumped up to the top line before the season stats do. And early in the year, honestly, we're leaning on preseason and a handful of games, so we shrink the numbers toward normal until there's more to go on."),
            _note("Land it: recency isn't a gimmick, it's the model refusing to trust a number that's stale — and refusing to trust a tiny sample too much."),
        ],
    },
    {
        "topic": "Ice time, role, and the goalie question",
        "beats": [
            _line("Deezy", "Why'd we skip that dude, he scores every time he touches the puck."),
            _line("Dr. Hall", "'Every time he touches it' — but how much is he on the ice? A guy who bounces between the second and fourth line has a wildly different shot total night to night. Steady ice time is what makes a shots or points line projectable."),
            _line("Deezy", "And the goalie props? Saves seems like free money."),
            _line("Dr. Hall", "Only if he actually starts. Goalies aren't confirmed until game day, so every saves number is an 'if he plays' number. Check the confirmed starter before you touch it."),
            _note("Land it: role and confirmed lineup matter more than a hot name. A saves prop with an unconfirmed starter is a coin flip on who's in net."),
        ],
    },
    TEACHING_SEGMENTS_WNBA[4],   # variance
]


# Nov 22 (owner: overhaul the Podcast Studio): NBA, college basketball, the NFL and college football all got the WNBA
# lessons ("she", rotation minutes in a 40-minute game). Each now has its own set, and every set carries the two
# lessons the record itself teaches: the earned chance, and why the show grades the picks it actually showed.
_EARNED = {
    "topic": "Why our chance is lower than the model's (the earned chance)",
    "beats": [
        _line("Deezy", "Hold up. The model says 64% on this one and you're tellin' the people 56%? Which is it?"),
        _line("Dr. Hall", "Both, honestly. 64% is what the model thinks. 56% is what its record says it's earned. We graded "
                          "every pick it showed — when it said 60-something, those hit closer to the mid-50s."),
        _line("Deezy", "So you're nerfing your own model on air?"),
        _line("Dr. Hall", "I'm telling the truth about it. The books' price is the starting point, and the model only gets "
                          "credit for the part of its disagreement it's actually been right about. As the record grows, "
                          "that number moves — up or down."),
        _note("Land it: a number you can trust beats a big number. The earned chance is how much of the model's opinion "
              "the results have paid for."),
    ],
}
_SHOWN = {
    "topic": "Why we grade the picks we showed, not the whole board",
    "beats": [
        _line("Deezy", "Everybody on the timeline posts their winners. Why do we post our losers too?"),
        _line("Dr. Hall", "Because every pick we showed gets saved before the game and graded after — wins and losses, at "
                          "the price we said. Nothing added after tip, nothing deleted after it loses."),
        _line("Deezy", "That sounds like a great way to look bad on a cold night."),
        _line("Dr. Hall", "On a cold night, sure. But it's the only kind of record worth anything. If you can't see the "
                          "losses, you can't trust the wins. And we check one more thing: did we get a better price than "
                          "where the line closed? That shows up long before the money does."),
        _note("Land it: a record you can't edit is the whole brand. Point people to the running record every show."),
    ],
}
_PRICE = {
    "topic": "The price matters more than the pick",
    "beats": [
        _line("Deezy", "I like the Over. Why do I care if it's -110 or -140? Over is over."),
        _line("Dr. Hall", "Because the price is the chance you need to be right. At -110 you need about 52%. At -140 you "
                          "need 58%. Same pick, totally different bet."),
        _line("Deezy", "So a pick can be good at one book and bad at another?"),
        _line("Dr. Hall", "Exactly. That's why every pick we show has a price and a book on it. If you can't get that "
                          "number or better, the edge we're talking about isn't there for you."),
        _note("Land it: shop the number. A great read at a bad price is a bad bet."),
    ],
}
TEACHING_SEGMENTS_BASKETBALL = [
    {
        "topic": "What CLV is (why we 'win' even when the bet loses)",
        "beats": [
            _line("Deezy", "Dad, you keep sayin' we 'beat the number' on a bet that LOST. That makes zero sense. We lost. L. Loss."),
            _line("Dr. Hall", "Right, but here's the thing — closing-line value. We took a rebounds prop in the morning at one number. By tip-off the whole market moved past it. We got a better price than everyone who bet it later."),
            _line("Deezy", "Okay but the board didn't come off his way. We still lost the money."),
            _line("Dr. Hall", "One night, yeah. But if we consistently get better numbers than where the line closes, the math says we win long-term — even with cold nights mixed in. CLV is the proof we're on the right side."),
            _note("Land it: results are one night of luck; beating the close, over and over, is skill. That's why we track CLV, not just W/L."),
        ],
    },
    _EARNED,
    {
        "topic": "Minutes, rest and blowout risk",
        "beats": [
            _line("Deezy", "Why'd we skip him? Dude's a walking bucket when he plays."),
            _line("Dr. Hall", "'When he plays' is doing a lot of work. Second night of a back-to-back, a minutes limit, a game that's over by the third quarter — any of those and the starters sit. A points line is really a minutes line first."),
            _line("Deezy", "So no minutes, no bet?"),
            _line("Dr. Hall", "Basically. Steady minutes are worth more to the model than one huge game off the bench. Check the injury report and the rest news before you lock anything in."),
            _note("Land it: role and minutes come before talent in a prop. A blowout is an Under's best friend."),
        ],
    },
    TEACHING_SEGMENTS_WNBA[1],   # parlays
    _PRICE,
    _SHOWN,
    TEACHING_SEGMENTS_WNBA[4],   # variance
]
TEACHING_SEGMENTS_FOOTBALL = [
    {
        "topic": "What CLV is (why we 'win' even when the bet loses)",
        "beats": [
            _line("Deezy", "Dad, you keep sayin' we 'beat the number' on a bet that LOST. That makes zero sense. We lost. L. Loss."),
            _line("Dr. Hall", "Right, but here's the thing — closing-line value. We took a receptions prop early in the week at one number. By kickoff the whole market moved past it. We got a better price than everyone who bet it later."),
            _line("Deezy", "Okay but he dropped the ball on third down. We still lost the money."),
            _line("Dr. Hall", "One game, yeah. But if we consistently get better numbers than where the line closes, the math says we win long-term. In football that matters even more — one game a week means the results take forever to prove anything. CLV shows up first."),
            _note("Land it: one game is luck; beating the close, week after week, is skill. That's why we track CLV, not just W/L."),
        ],
    },
    _EARNED,
    {
        "topic": "Snaps and targets before talent",
        "beats": [
            _line("Deezy", "Why we on some WR3 nobody's heard of instead of the star?"),
            _line("Dr. Hall", "Because a receiving line is really a targets line. If the WR3 is on the field every snap and the star is banged up or getting shadowed, the volume goes somewhere. We follow the snaps and the targets, not the name."),
            _line("Deezy", "So the boring guy with the job beats the famous guy with the highlights?"),
            _line("Dr. Hall", "More often than you'd think, at the price. The books price the name. We price the role."),
            _note("Land it: volume — snaps, routes, targets, carries — is the foundation of every football prop."),
        ],
    },
    {
        "topic": "Game script and weather",
        "beats": [
            _line("Deezy", "The QB's been cookin'. Over on passing yards, easy."),
            _line("Dr. Hall", "Unless his team is up 21 at halftime and runs the ball for thirty minutes. Or it's 25 mph wind. How the game is likely to go changes every number on the board."),
            _line("Deezy", "So we gotta predict the whole game to bet one guy?"),
            _line("Dr. Hall", "We gotta respect it. The spread and the total tell you what the market expects. A big favorite leans run late; a shootout total leans throw. Wind and rain hit the passing game and the kickers first."),
            _note("Land it: check the spread, the total and the forecast before any yardage prop."),
        ],
    },
    _PRICE,
    _SHOWN,
    TEACHING_SEGMENTS_WNBA[4],   # variance
]


def rotating_teaching(date_str: str, sport: str = "MLB") -> Dict:
    """Deterministically rotate the teaching topic by date, so each show gets a fresh one."""
    try:
        doy = datetime.fromisoformat(date_str).timetuple().tm_yday
    except (ValueError, TypeError):
        doy = 0
    if sport == "MLB":
        segments = TEACHING_SEGMENTS
    elif sport == "NHL":
        segments = TEACHING_SEGMENTS_NHL
    elif sport in ("NFL", "NCAAF"):
        segments = TEACHING_SEGMENTS_FOOTBALL
    elif sport in ("NBA", "NCAAMB"):
        segments = TEACHING_SEGMENTS_BASKETBALL
    else:
        segments = TEACHING_SEGMENTS_WNBA
    return segments[doy % len(segments)]


# --- per-selection banter beats --------------------------------------------
_DEEZY_PUSH = {
    "Batter HR": "{prob}% to homer? So you're tellin' me he does NOT homer {inv}% of the time and we're hyped?",
    "Batter Total Bases": "Total bases over 1.5 — so he needs a double or two singles. What if he just walks twice and we're cooked?",
    "Batter Total Hits": "One hit. We're trusting a big-leaguer to get ONE hit. Groundbreaking, Dad.",
    "Batter Strikeouts": "You want me to root for a strikeout? That feels illegal.",
    "Pitcher Strikeouts": "So this dude just mows down the whole lineup? What if he gets shelled in the 3rd and they yank him?",
    "Pitcher Outs": "Outs? We're betting on a guy to record OUTS? Riveting television right here, folks.",
    "Pitcher Walks": "Walks?? Now we're handicappin' ball four. Who hurt you, Dad?",
    "Points": "{prob}% to clear that? So she's UNDER it {inv}% of the time and we're pumped about that?",
    "Rebounds": "Rebounds, really? We're out here bettin' on boxing out. Thrilling stuff.",
    "Assists": "So we need her to be UNSELFISH tonight specifically? What if she just goes bucket mode instead?",
    "Goals": "{prob}% to score? So he does NOT light the lamp {inv}% of the time and we're hyped?",
    "Shots on Goal": "Shots on goal — so he just has to throw pucks at the net. What if the coach parks him on the fourth line?",
    "Blocked Shots": "Blocked shots?! We're rooting for a guy to eat a puck for a living. Who hurt you, Dad?",
    "Saves": "Saves depends on the goalie even starting, Dad. What if the backup gets the nod?",
    "Threes Made": "Threes are the most streaky shot in the sport and THAT'S the one we're leanin' on?",
}


def selection_beats(p: Dict) -> List[Dict]:
    """A talking-points beat for one selection: Dr. Hall's case -> Deezy's gut check -> reality."""
    prob = round(p.get("ModelProb", 0) * 100)
    inv = 100 - prob
    push = _DEEZY_PUSH.get(p.get("Market"), "Break this one down for me, Doc.").format(prob=prob, inv=inv)
    opp = f" vs {p['Opp']}" if p.get("Opp") else ""
    fair = f"{p['Fair']:+.0f}" if p.get("Fair") is not None else "—"
    if p.get("EV") is not None and p.get("LivePrice") is not None:     # Nov 22: the board's own EV isn't a live read
        live = f"{p['LivePrice']:+.0f}"
        price_beat = (f"Live price is {live} — that's about {p['EV']:+.1f}% value by our math. "
                      f"Model has it ~{prob}%. That's a real edge at this number, not just a lean.")
    elif p.get("PriceSource") == "book" and p.get("RealPrice") is not None:
        # Real, easy improvement: RealPrice may already be sitting on this play (from the same
        # already-fetched board data, zero extra Odds API cost) even without the dedicated
        # "Live value" EV fetch above -- show it directly instead of always defaulting to the
        # model-only fair-price framing below.
        price_beat = (f"Real price right now is {p['RealPrice']:+.0f}. Model has it ~{prob}% — "
                      f"a lean we like, not a lock.")
    else:
        price_beat = (f"Fair price is around {fair}. Model has it ~{prob}% — a lean we like, not a "
                      f"lock. We only fire if the live number beats {fair}.")
    if p.get("Earned") is not None:                    # Nov 22: the chance quoted is the earned one (show_picks.py)
        price_beat = price_beat.replace("Model has it", "Our earned chance has it")
    flag = "💰 " if p.get("Money") else "🔒 " if p.get("Lock") else ""
    edge = (f"[earned edge {p['EarnedEdge'] * 100:+.1f} pts]" if p.get("EarnedEdge") is not None
            else f"[conviction {p.get('Conviction', 0):.1f}x]")
    return [
        _note(f"SELECTION: {flag}{p['Player']} ({p['Team']}) — {p['Market']} {p['Side']} {p['Line']:g}{opp}  {edge}"),
        _line("Dr. Hall", f"Here's the case: {p.get('Why', 'the model likes the matchup')}."),
        _line("Deezy", push),
        _line("Dr. Hall", price_beat),
        _note("Reality check (say it every time): interesting, not guaranteed. Check the price."),
    ]


# --- full script assembly --------------------------------------------------
def assemble_script(date_str: str, headliners: List[Dict], sleepers: List[Dict],
                    retro: Optional[Dict], caught_homers: Optional[List[Dict]],
                    sport: str = "MLB", slate_note: str = "", ledger: Optional[Dict] = None,
                    running: Optional[Dict] = None) -> List[Dict]:
    """Return ordered sections: {title, time, beats[]}. Pure — no Streamlit, fully testable.

    `sport` swaps the handful of baseball-flavored phrases (park/weather, "went deep", the
    generic "that's baseball" line) for basketball-appropriate ones — everything else (the
    Dr. Hall/Deezy dynamic, section structure, teaching-segment slot) is genuinely sport-agnostic.
    `caught_homers` keeps its MLB-origin name but holds the same shape for whichever market is
    the sport's marquee single-event market (Points, for WNBA)."""
    is_mlb = sport == "MLB"
    teaching = rotating_teaching(date_str, sport)
    S = []

    # 1) Yesterday in Review (the cold open)
    review = [
        _line("Deezy", "Yo what's good everybody, welcome back to H2 Sports! Before we touch tonight — "
                       "we GOTTA talk about last night, because it was a MOVIE."),
        _fill(("⚡ Wild moment of the night? (ejection, walk-off, meltdown — whatever you actually saw)")
             if is_mlb else
             ("⚡ Wild moment of the night? (overtime winner, goalie meltdown, a brawl — whatever you actually saw)")
             if sport == "NHL" else
             ("⚡ Wild moment of the week? (a walk-off field goal, a pick-six, a meltdown — whatever you actually saw)")
             if sport in ("NFL", "NCAAF") else
             ("⚡ Wild moment of the night? (buzzer-beater, blowout, meltdown — whatever you actually saw)")),
        _fill("⚡ Who let us down? (the team/player that went ice cold)"),
        _fill("⚡ Any robbery? (a great play, a blown call, something that made you yell)"),
    ]
    if ledger:                                          # Nov 22: the picks we SHOWED, graded (show_picks.py)
        import show_picks as SP
        moved = ledger["beat"] + ledger["lost"]
        review.append(_note("THE RECORD, HONESTLY: " + SP.record_line(ledger, "the picks we showed yesterday")
                            + (f" Since {running['since']}: {running['hits']}–{running['misses']}, "
                               f"{running['units']:+.2f}u." if running else "")))
        if ledger["wins"]:
            names = ", ".join(SP.pick_name(r) for r in ledger["wins"][:3])
            review.append(_line("Dr. Hall", f"Cashed: {names}. Saved before the game, graded at the price we said."))
        if ledger["losses"]:
            names = ", ".join(SP.pick_name(r) for r in ledger["losses"][:3])
            review.append(_line("Deezy", f"And we gotta own these: {names}. Keep it a buck."))
        if moved:
            review.append(_line("Dr. Hall", f"And the number that matters most early: we beat the closing line on "
                                            f"{ledger['beat']} of the {moved} prices that moved."))
    elif retro and retro.get("graded"):
        hr = retro.get("hit_rate")
        review.append(_note(f"THE BOARD, HONESTLY: of the plays we'd have flagged, "
                            f"{retro['hits']}/{retro['graded']} hit"
                            + (f" ({hr*100:.0f}%)." if hr is not None else ".")))
        if caught_homers:
            names = ", ".join(f"{c['Player']} (ranked #{c['Rank']})" for c in caught_homers[:3])
            if is_mlb:
                review.append(_line("Dr. Hall", f"And a little flex — the model had {names} as top power "
                                                f"plays before the game, and they went deep. That's the model "
                                                f"finding bats before the names pop."))
            else:
                review.append(_line("Dr. Hall", f"And a little flex — the model had {names} as top scoring "
                                                f"plays before the game, and they cashed. That's the model "
                                                f"finding form before the names pop."))
        review.append(_line("Deezy", "Okay but we also got cooked on some, keep it a buck."))
        if is_mlb:
            review.append(_line("Dr. Hall", "Always keep it a buck. That's baseball — one night's variance. "
                                            "We'll get into why a cold night isn't a broken board later."))
        else:
            review.append(_line("Dr. Hall", "Always keep it a buck. That's variance — one cold night. "
                                            "We'll get into why that doesn't mean the board's broken later."))
    elif running:                                       # Nov 22: no picks yesterday (a weekly slate) -- the tab
        review.append(_note(f"THE RECORD, HONESTLY: no {sport} picks were shown yesterday. Since {running['since']}: "
                            f"{running['hits']}–{running['misses']}, {running['units']:+.2f}u at the prices shown."))
    else:
        review.append(_fill("📊 THE RECORD: nothing graded yet — the picks we show are graded the morning after "
                            "their games, and this fills in automatically."))
    review.append(_note("Reframe for the subs: nights like that are the game, not a broken model. "
                        "Acknowledge the pain, then move on — don't dwell, don't make excuses."))
    S.append({"title": "🎬 Yesterday in Review", "time": "0:00–8:00", "beats": review})

    # 2) Slate overview
    overview = [
        _line("Dr. Hall", "Alright, enough cryin' about yesterday. Let's set the table for tonight."),
        _fill("🗓️ Headline storyline of the slate? (marquee arm, big series, a weather game)" if is_mlb
             else "🗓️ Headline storyline of the slate? (marquee matchup, a big rivalry, a player to watch)"),
        _line("Deezy", ("How many games we workin' with and what's the vibe — pitchers' duels or are we "
                        "hittin' bombs tonight?") if is_mlb else
             "How many games we workin' with and what's the vibe tonight?"),
        _note(("Dr. Hall: give the shape of the slate — number of games, any obvious park/weather spots, "
              "the one matchup you're most fired up about.") if is_mlb else
             ("Dr. Hall: give the shape of the slate — number of games, any rest/back-to-back spots, "
              "the one matchup you're most fired up about.")),
    ]
    if slate_note:
        # Day/game framing (see media_focus.slate_phrase): the real shape of tonight's ticket, so a
        # one-game night is framed as ONE game rather than a generic "how many games" riff.
        overview.insert(1, _note(f"TONIGHT'S TICKET: {slate_note}."))
    S.append({"title": "🗒️ Slate Overview", "time": "8:00–13:00", "beats": overview})

    # 3) Top selections (the meat)
    top_beats = [_line("Deezy", "Aight, the people came for the picks. What we likin' tonight?"),
                 _note("These come from the platform's own list — the same picks on the Command Center, ranked by "
                       "earned edge (💰 = a Money pick). Work each as a beat: Dr. Hall makes the case, Deezy "
                       "gut-checks it, land the reality check.")]
    for p in headliners:
        top_beats += selection_beats(p)
    if not headliners:
        top_beats.append(_fill("No selections loaded — pick a date with scheduled games."))
    S.append({"title": "⭐ Tonight's Top Selections", "time": "13:00–35:00", "beats": top_beats})

    # 4) Sleepers & fades
    sleeper_beats = [
        _line("Deezy", "Now hit me with the under-the-radar stuff — the ones nobody's talkin' about."),
        _note(("Interesting plays that didn't crack the headline list — a sleeper bat, a fade, a "
              "weather/platoon angle worth a mention. Lighter touch than the top tier.") if is_mlb else
             ("Interesting plays that didn't crack the headline list — a depth forward getting more ice "
              "time, a shots-trend worth a mention. Lighter touch than the top tier.") if sport == "NHL" else
             ("Interesting plays that didn't crack the headline list — a role player heating up, a "
              "minutes-trend worth a mention. Lighter touch than the top tier.")),
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
    if running:
        plan.insert(2, _line("Dr. Hall", f"And the running tab, since {running['since']}: {running['hits']}–"
                                         f"{running['misses']}, {running['units']:+.2f}u at the prices we showed. "
                                         "Every pick, wins and losses."))
    S.append({"title": "🧭 Game Plan & Honest Reality Check", "time": "52:00–58:00", "beats": plan})

    # 7) Sign-off + banter button
    signoff = [
        _fill(("🏀 Banter button: tonight's hot-take/GOAT debate to tease next show "
              "(LeBron/Jordan, Lamar slander, Skubal's a cheat code, etc.)") if is_mlb else
             ("🏀 Banter button: tonight's hot-take/GOAT debate to tease next show "
              "(an MVP-race take, a coaching decision, a trade rumor, etc.)")),
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
