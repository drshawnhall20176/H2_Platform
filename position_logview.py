"""
position_logview.py — the Position Matchups game log as one aligned HTML table (pure; the page just hands the
string to st.markdown(unsafe_allow_html=True)).

A dataframe can't hold an average row, a hit-rate row and a best-lines row UNDER the same columns, and can't show
team logos, so the log is drawn as a table. Everything user- or data-supplied is HTML-escaped; image URLs must be
https. Colours are translucent so the table reads on a light or a dark theme.

Layout (Doink-style):  DATE | OPPONENT | W/L | PLAYER | <stat columns> | <headline metric>
                       rows, newest first, each stat cell shaded green/red against its own column's average;
                       then AVG, HIT RATE, LINE, BEST OVER, BEST UNDER rows (the last three only when book lines
                       were loaded).
"""

from __future__ import annotations

import html
from typing import Dict, Optional, Sequence

import position_lines as PL
import position_matchups as PM

_CSS = (
    "<style>"
    ".pmlog-wrap{overflow-x:auto;border:1px solid rgba(128,128,128,.25);border-radius:10px;margin:.25rem 0 .5rem}"
    ".pmlog{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}"
    ".pmlog th{font-size:10px;letter-spacing:.04em;font-weight:600;opacity:.65;padding:6px 8px;text-align:center;white-space:nowrap}"
    ".pmlog td{padding:4px 8px;text-align:center;border-top:1px solid rgba(128,128,128,.18);white-space:nowrap}"
    ".pmlog td.l,.pmlog th.l{text-align:left}"
    ".pmlog img.lg{height:18px;width:18px;object-fit:contain;vertical-align:middle;margin:0 4px}"
    ".pmlog img.hs{height:22px;width:22px;object-fit:cover;border-radius:50%;vertical-align:middle;margin-right:5px}"
    ".pmlog .w{color:#1f9d55;font-weight:700}.pmlog .lo{color:#d64444;font-weight:700}"
    ".pmlog tr.sum td{border-top:2px solid rgba(128,128,128,.35);font-weight:600}"
    ".pmlog tr.sub td{font-size:11px;opacity:.95}"
    ".pmlog .hit-hi{color:#1f9d55;font-weight:700}.pmlog .hit-lo{color:#d64444;font-weight:700}"
    ".pmlog small{opacity:.7;font-weight:400}"
    "</style>"
)


def _e(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _img(url, cls: str) -> str:
    u = str(url or "")
    return f'<img class="{cls}" src="{_e(u)}" alt="">' if u.startswith("https://") else ""


def fmt_value(key: str, value: float, whole: bool, average: bool = False) -> str:
    """One stat cell as text: shares as whole percents, the headline metric to a decimal, counts as whole numbers
    (averages keep a decimal, so 27.3 attempts reads as 27.3)."""
    if key in PM.PERCENT_KEYS:
        return f"{value:.0f}%"
    if key == "pts" or average or not whole:
        return f"{value:.1f}"
    return f"{value:.0f}"


def _hit_class(pct: float) -> str:
    return "hit-hi" if pct >= 60 else "hit-lo" if pct <= 40 else ""


def log_html(log: Dict, names: Dict, metric_name: str, *, whole: bool = True, logos: Optional[Dict] = None,
             headshots: Optional[Dict] = None, hits: Optional[Dict] = None, best: Optional[Dict] = None) -> str:
    """The game log as one HTML string. `whole` shows counts as whole numbers (football); `logos` {team key: https
    url} and `headshots` {player id: https url} are optional; `hits` is PM.hit_rates() output and `best` is
    PL.best_lines() output — the rows for them appear only when given."""
    logos, headshots, hits, best = logos or {}, headshots or {}, hits or {}, best or {}
    cols = list(log["stat_cols"])
    rows = log["rows"]
    keys = [k for k, _ in cols] + ["pts"]
    heat = {k: PM.heat_css([(r["pts"] if k == "pts" else r["stats"][k]) for r in rows]) for k in keys}
    head = ('<tr><th class="l">DATE</th><th class="l">OPPONENT</th><th>W/L</th><th class="l">PLAYER</th>'
            + "".join(f"<th>{_e(label)}</th>" for _, label in cols) + f"<th>{_e(metric_name.upper())}</th></tr>")
    body = []
    for i, r in enumerate(rows):
        opp_name = names.get(r["opp"], r["opp"])
        prefix = {"Away": "at", "Home": "vs"}.get(r["venue"], "")
        res = r["result"]
        res_html = (f'<span class="{"w" if res == "W" else "lo" if res == "L" else ""}">{_e(res)}</span>' if res else "—")
        score = f' <small>{_e(r["score"])}</small>' if r["score"] else ""
        cells = [f'<td class="l">{_e(PM.when_label(r["order"], r["date"]))}</td>',
                 f'<td class="l">{_e(prefix) + " " if prefix else ""}{_img(logos.get(r["opp"]), "lg")}{_e(opp_name)}</td>',
                 f"<td>{res_html}{score}</td>",
                 f'<td class="l">{_img(headshots.get(r["pid"]), "hs")}{_e(r["who"] or "—")}</td>']
        for k in keys:
            v = r["pts"] if k == "pts" else r["stats"][k]
            css = heat[k][i]
            cells.append(f'<td style="{_e(css)}">{_e(fmt_value(k, v, whole))}</td>' if css else f"<td>{_e(fmt_value(k, v, whole))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    avg = log["avg"]
    foot = []
    if avg:
        cells = [f'<td class="l" colspan="4">AVG ({log["games"]} game{"s" if log["games"] != 1 else ""})</td>']
        cells += [f"<td>{_e(fmt_value(k, avg['pts'] if k == 'pts' else avg['stats'][k], whole, average=True))}</td>" for k in keys]
        foot.append('<tr class="sum">' + "".join(cells) + "</tr>")
    if hits:
        cells = ['<td class="l" colspan="4">HIT RATE <small>(over the line)</small></td>']
        for k in keys:
            h = hits.get(k)
            cells.append(f'<td class="{_hit_class(h["pct"])}">{h["pct"]:.0f}%<br><small>{h["hits"]}/{h["games"]}</small></td>'
                         if h else "<td>—</td>")
        foot.append('<tr class="sum">' + "".join(cells) + "</tr>")
    if best:
        def line_row(label: str, cell) -> str:
            return ('<tr class="sub"><td class="l" colspan="4">' + _e(label) + "</td>"
                    + "".join(f"<td>{cell(best.get(k))}</td>" for k in keys) + "</tr>")

        def price(side):
            def cell(b):
                got = (b or {}).get(side)
                return f"{_e(PL.fmt_price(got[1]))}<br><small>{_e(PL.O.book_label(got[0]))}</small>" if got else "—"
            return cell
        foot.append(line_row("LINE", lambda b: _e(f"{b['point']:g}") if b else "—"))
        foot.append(line_row("BEST OVER", price("over")))
        foot.append(line_row("BEST UNDER", price("under")))
    return (_CSS + '<div class="pmlog-wrap"><table class="pmlog"><thead>' + head + "</thead><tbody>" + "".join(body)
            + "</tbody><tfoot>" + "".join(foot) + "</tfoot></table></div>")
