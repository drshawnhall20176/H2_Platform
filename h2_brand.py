"""
h2_brand.py — H2 Sports' own visual identity (Nov 24).

Owner, Nov 24: "I do not want to copy their color schemes, H2Sports needs to stay distinct and not be a carbon copy of
anyone else." The site's look grows from what it already is -- the deep navy hero and the H2 blue -- with gold for
what H2 tells you to bet. One place for the colors, so every new card and chart speaks the same language:

  navy / slate    surfaces and frames (the hero's #0F172A → #1E293B)
  H2 blue         the model's read: projections, hits, the primary line in a chart
  gold            🃏 Bet -- and the line a pick has to beat (dashed)
  teal            🧪 Tracking
  slate gray      Info only, misses, references
  green / red     results only (won / lost, profit / loss) -- never decoration
"""
NAVY, SLATE, PANEL, EDGE = "#0F172A", "#1E293B", "#111827", "#334155"
BLUE, BLUE_SOFT = "#3B82F6", "#93C5FD"
GOLD = "#F5B83D"
TEAL = "#2DD4BF"
GRAY, GRAY_SOFT, INK, INK_SOFT = "#64748B", "#475569", "#F8FAFC", "#94A3B8"
WIN, LOSS = "#16A34A", "#DC2626"

BET_COLOR = {"🃏 Bet": GOLD, "🧪 Tracking": TEAL}


def chip(text: str, color: str = BLUE, filled: bool = False) -> str:
    """A small rounded label (HTML) in H2's colors."""
    bg = color if filled else "transparent"
    fg = NAVY if filled else color
    return (f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;border:1.5px solid {color};'
            f'background:{bg};color:{fg};font-weight:700;font-size:12.5px;letter-spacing:.02em;">{text}</span>')


def bet_chip(bet: str) -> str:
    c = next((v for k, v in BET_COLOR.items() if str(bet).startswith(k)), GRAY)
    return chip(bet, c, filled=c != GRAY)
