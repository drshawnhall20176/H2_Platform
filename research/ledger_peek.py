import json, pick_ledger as PL
for kind, sp in (("strong","ALL"),("money","NBA"),("money","NCAAMB"),("games","NCAAMB")):
    for day in ("2026-11-21","2026-11-22"):
        rs = PL.rows(kind, sp, day)
        print(kind, sp, day, len(rs), "books:", sorted({str(r.get("book")) for r in rs}))
        for r in rs[:2]:
            print(json.dumps(r, default=str)[:700])
