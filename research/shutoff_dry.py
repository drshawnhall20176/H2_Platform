import sys
sys.path.insert(0, ".")
import shutoff as SO
rec = SO.refit(save=lambda k, v: None)
for k, v in sorted(rec["groups"].items()):
    if v["n"] >= 40:
        print(f"SD {v['state']:5} {k}: n={v['n']} roi={v['roi']:+.3f} hi={v['hi']:+.3f} clv={v['beat']} of {v['clv_n']}")
