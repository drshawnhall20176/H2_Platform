"""Nov 13: soccer goals model (soccer_model.py) walk-forward vs real prices (football-data.co.uk).
Big 5 + Championship: Pinnacle pre-match (bet) and closing prices for 1X2, O/U 2.5 and Asian handicap.
MLS / Liga MX: closing 1X2 only. Refit weekly on everything before that week."""
import csv, io, math, os, sys, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import soccer_model as S

SEASONS = ["2021", "2122", "2223", "2324", "2425", "2526"]
DIVS = {"EPL": "E0", "CHAMPIONSHIP": "E1", "LALIGA": "SP1", "SERIEA": "I1", "BUNDESLIGA": "D1", "LIGUE1": "F1"}
NEW = {"MLS": "USA", "LIGAMX": "MEX"}
TEST_FROM = datetime(2023, 7, 1, tzinfo=timezone.utc)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=60).read().decode("latin-1")


def fnum(x):
    try:
        v = float(x)
        return v if v > 1 else None
    except (TypeError, ValueError):
        return None


def pdate(s):
    for f in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s.strip(), f).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def load_old(div):
    out = []
    for s in SEASONS:
        try:
            txt = get(f"https://www.football-data.co.uk/mmz4281/{s}/{div}.csv")
        except Exception as e:
            print("  miss", div, s, e); continue
        for r in csv.DictReader(io.StringIO(txt)):
            d = pdate(r.get("Date") or "")
            if not d or not r.get("HomeTeam") or r.get("FTHG") in (None, ""):
                continue
            out.append({"home": r["HomeTeam"], "away": r["AwayTeam"], "hg": int(r["FTHG"]), "ag": int(r["FTAG"]),
                        "date": d,
                        "x12": [fnum(r.get(k)) for k in ("PSH", "PSD", "PSA")],
                        "x12c": [fnum(r.get(k)) for k in ("PSCH", "PSCD", "PSCA")],
                        "ou": [fnum(r.get("P>2.5")), fnum(r.get("P<2.5"))],
                        "ouc": [fnum(r.get("PC>2.5")), fnum(r.get("PC<2.5"))],
                        "ah": fnum(r.get("AHh")) if False else (float(r["AHh"]) if r.get("AHh") not in (None, "") else None),
                        "ahp": [fnum(r.get("PAHH")), fnum(r.get("PAHA"))],
                        "ahc": float(r["AHCh"]) if r.get("AHCh") not in (None, "") else None,
                        "ahpc": [fnum(r.get("PCAHH")), fnum(r.get("PCAHA"))]})
    return out


def load_new(code):
    txt = get(f"https://www.football-data.co.uk/new/{code}.csv")
    out = []
    for r in csv.DictReader(io.StringIO(txt)):
        d = pdate(r.get("Date") or "")
        if not d or r.get("HG") in (None, ""):
            continue
        out.append({"home": r["Home"], "away": r["Away"], "hg": int(r["HG"]), "ag": int(r["AG"]), "date": d,
                    "x12": [None] * 3, "x12c": [fnum(r.get(k)) for k in ("PSCH", "PSCD", "PSCA")],
                    "ou": [None, None], "ouc": [None, None], "ah": None, "ahp": [None, None], "ahc": None,
                    "ahpc": [None, None]})
    return [m for m in out if m["date"] >= datetime(2019, 1, 1, tzinfo=timezone.utc)]


def run(name, ms):
    ms.sort(key=lambda m: m["date"])
    test = [m for m in ms if m["date"] >= TEST_FROM]
    weeks = defaultdict(list)
    for m in test:
        weeks[m["date"].isocalendar()[:2]].append(m)
    ll_m = ll_c = n_ll = 0.0
    bets = defaultdict(lambda: [0, 0.0, 0.0])          # key -> n, profit at bet price, profit at close
    clv = defaultdict(list)
    for wk, games in sorted(weeks.items()):
        start = min(g["date"] for g in games)
        r = S.fit(ms, start)
        for m in games:
            lam = S.rates(r, m["home"], m["away"])
            if lam is None or min(r["n"].get(m["home"], 0), r["n"].get(m["away"], 0)) < 6:
                continue
            g = S.grid(*lam)
            p3 = S.one_x_two(g)
            res = 0 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 2)
            if all(m["x12c"]):
                c3 = S.devig(m["x12c"])
                ll_m -= math.log(max(p3[res], 1e-9)); ll_c -= math.log(max(c3[res], 1e-9)); n_ll += 1
            for blend in (1.0, 0.5):
                for i, lab in enumerate(("H", "D", "A")):
                    pc = m["x12c"][i]
                    pb = m["x12"][i] or pc
                    if not pc or not all(m["x12c"]):
                        continue
                    mkt = S.devig(m["x12c"] if not all(m["x12"]) else m["x12"])[i]
                    p = blend * p3[i] + (1 - blend) * mkt
                    e = p * pb - 1
                    for th in (0.03, 0.06, 0.10):
                        if e > th:
                            k = (f"1X2 b{blend}", th)
                            win = (res == i)
                            bets[k][0] += 1; bets[k][1] += (pb - 1) if win else -1; bets[k][2] += (pc - 1) if win else -1
                            if m["x12"][i]:
                                clv[k].append(pb / pc - 1)
                # totals 2.5
                if all(m["ouc"]):
                    po = S.total_outcome(g, 2.5)["win"]
                    mk_src = m["ou"] if all(m["ou"]) else m["ouc"]
                    mo = S.devig(mk_src)[0]
                    for j, side in enumerate(("over", "under")):
                        p = blend * (po if side == "over" else 1 - po) + (1 - blend) * (mo if side == "over" else 1 - mo)
                        pb = m["ou"][j] or m["ouc"][j]; pc = m["ouc"][j]
                        e = p * pb - 1
                        win = (m["hg"] + m["ag"] > 2.5) == (side == "over")
                        for th in (0.03, 0.06, 0.10):
                            if e > th:
                                k = (f"O/U2.5 b{blend}", th)
                                bets[k][0] += 1; bets[k][1] += (pb - 1) if win else -1; bets[k][2] += (pc - 1) if win else -1
                                if m["ou"][j]:
                                    clv[k].append(pb / pc - 1)
                # Asian handicap at the pre-match line/price
                if m["ah"] is not None and all(m["ahp"]):
                    for j, side in enumerate(("home", "away")):
                        line = m["ah"] if side == "home" else -m["ah"]
                        o = S.handicap_outcome(g, line, side)
                        mo = S.devig(m["ahp"])[j]
                        pw = blend * (o["win"] / max(o["win"] + o["loss"], 1e-9)) + (1 - blend) * mo
                        # compare on the win-vs-loss share; EV with pushes back
                        pb = m["ahp"][j]
                        e = pw * pb - 1
                        d = (m["hg"] - m["ag"]) if side == "home" else (m["ag"] - m["hg"])
                        prof = 0.0
                        parts = S._half_lines(line)
                        for L in parts:
                            x = d + L
                            prof += ((pb - 1) if x > 0 else (0 if x == 0 else -1)) / len(parts)
                        for th in (0.03, 0.06, 0.10):
                            if e > th:
                                k = (f"AH b{blend}", th)
                                bets[k][0] += 1; bets[k][1] += prof
    print(f"\n=== {name}: {len(ms)} matches, tested {len(test)} since {TEST_FROM:%Y-%m}")
    if n_ll:
        print(f"  1X2 log-loss  model {ll_m / n_ll:.4f}   closing market {ll_c / n_ll:.4f}   (lower is better; n={int(n_ll)})")
    for k in sorted(bets):
        n, pb, pc = bets[k]
        if n:
            c = clv.get(k)
            print(f"  {k[0]:<14} edge>{k[1]:.2f}: n={n:5d}  ROI at bet price {pb / n:+.1%}  at close {pc / n:+.1%}"
                  + (f"  CLV {sum(c) / len(c):+.2%}" if c else ""))


for name, div in DIVS.items():
    try:
        run(name, load_old(div))
    except Exception as e:
        print(name, "failed", type(e).__name__, e)
for name, code in NEW.items():
    try:
        run(name, load_new(code))
    except Exception as e:
        print(name, "failed", type(e).__name__, e)
