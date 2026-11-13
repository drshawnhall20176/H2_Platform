"""Nov 13: market-based soccer value. Fair = Pinnacle pre-match, de-vigged. Bet a soft book (Bet365, and the best
price across books) when its price beats fair by a threshold. Graded on results; also vs Pinnacle closing (CLV)."""
import csv, io, os, sys, urllib.request
from collections import defaultdict
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import soccer_model as S

SEASONS = ["2223", "2324", "2425", "2526"]
DIVS = {"EPL": "E0", "CHAMPIONSHIP": "E1", "LALIGA": "SP1", "SERIEA": "I1", "BUNDESLIGA": "D1", "LIGUE1": "F1"}


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read().decode("latin-1")


def f(x):
    try:
        v = float(x)
        return v if v > 1 else None
    except (TypeError, ValueError):
        return None


tot = defaultdict(lambda: [0, 0.0, 0.0, 0.0])
for name, div in DIVS.items():
    res = defaultdict(lambda: [0, 0.0, 0.0, 0.0])
    for s in SEASONS:
        try:
            rows = list(csv.DictReader(io.StringIO(get(f"https://www.football-data.co.uk/mmz4281/{s}/{div}.csv"))))
        except Exception as e:
            print("miss", div, s, e); continue
        for r in rows:
            if r.get("FTHG") in (None, ""):
                continue
            hg, ag = int(r["FTHG"]), int(r["FTAG"])
            out3 = 0 if hg > ag else (1 if hg == ag else 2)
            markets = []
            p = [f(r.get(k)) for k in ("PSH", "PSD", "PSA")]
            pc = [f(r.get(k)) for k in ("PSCH", "PSCD", "PSCA")]
            if all(p):
                fair = S.devig(p)
                for book, ks in (("B365", ("B365H", "B365D", "B365A")), ("Best", ("MaxH", "MaxD", "MaxA"))):
                    q = [f(r.get(k)) for k in ks]
                    for i in range(3):
                        if q[i]:
                            markets.append(("1X2", book, fair[i], q[i], out3 == i, S.devig(pc)[i] if all(pc) else None))
            p = [f(r.get("P>2.5")), f(r.get("P<2.5"))]
            pc = [f(r.get("PC>2.5")), f(r.get("PC<2.5"))]
            if all(p):
                fair = S.devig(p)
                for book, ks in (("B365", ("B365>2.5", "B365<2.5")), ("Best", ("Max>2.5", "Max<2.5"))):
                    q = [f(r.get(k)) for k in ks]
                    for i in range(2):
                        if q[i]:
                            markets.append(("O/U2.5", book, fair[i], q[i], (hg + ag > 2.5) == (i == 0),
                                            S.devig(pc)[i] if all(pc) else None))
            p = [f(r.get("PAHH")), f(r.get("PAHA"))]
            if all(p) and r.get("AHh") not in (None, ""):
                fair = S.devig(p)
                L = float(r["AHh"])
                for book, ks in (("B365", ("B365AHH", "B365AHA")), ("Best", ("MaxAHH", "MaxAHA"))):
                    q = [f(r.get(k)) for k in ks]
                    for i in range(2):
                        if not q[i]:
                            continue
                        d = (hg - ag) if i == 0 else (ag - hg)
                        line = L if i == 0 else -L
                        parts = S._half_lines(line)
                        prof = sum(((q[i] - 1) if d + x > 0 else (0 if d + x == 0 else -1)) for x in parts) / len(parts)
                        markets.append(("AH", book, fair[i], q[i], prof, None))
            for mk, book, fp, price, won, fc in markets:
                e = fp * price - 1
                for th in (0.0, 0.02, 0.04, 0.07):
                    if e > th:
                        k = (mk, book, th)
                        prof = won if mk == "AH" else ((price - 1) if won else -1)
                        res[k][0] += 1; res[k][1] += prof
                        if fc:
                            res[k][2] += fc * price - 1; res[k][3] += 1
                        tot[k][0] += 1; tot[k][1] += prof
                        if fc:
                            tot[k][2] += fc * price - 1; tot[k][3] += 1
    print(f"\n=== {name}")
    for k in sorted(res):
        n, p, c, nc = res[k]
        print(f"  {k[0]:<7} {k[1]:<5} beat fair by >{k[2]:.0%}: n={n:5d}  ROI {p / n:+.1%}" + (f"  EV vs Pinnacle close {c / nc:+.1%}" if nc else ""))
print("\n=== ALL SIX LEAGUES")
for k in sorted(tot):
    n, p, c, nc = tot[k]
    print(f"  {k[0]:<7} {k[1]:<5} beat fair by >{k[2]:.0%}: n={n:5d}  ROI {p / n:+.1%}" + (f"  EV vs Pinnacle close {c / nc:+.1%}" if nc else ""))
