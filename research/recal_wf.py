import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
from datetime import date, timedelta
def fit(xs):
    n=len(xs); mx=sum(a for a,_ in xs)/n; my=sum(b for _,b in xs)/n
    sxx=sum((a-mx)**2 for a,_ in xs); b=sum((a-mx)*(y-my) for a,y in xs)/sxx; return my-b*mx, b
for lg in ("NCAAMB","NBA","NCAAF","NHL"):
    recs=[r for r in MS.load_game_picks(lg) if r.get("final_home") is not None and r.get("model_margin") is not None and r.get("kickoff")]
    recs.sort(key=lambda r:r["kickoff"])
    for win in (21,35):
      for shrink in (1.0,0.5):
        st={"raw":[0,0,0.0],"cal":[0,0,0.0]}; n=0; bs=[]
        for r in recs:
            d=str(r["kickoff"])[:10]
            if d<"2026-11-01": continue
            lo=(date.fromisoformat(d)-timedelta(days=win)).isoformat()
            tr=[(float(q["model_margin"]),float(q["final_home"])-float(q["final_away"])) for q in recs if lo<=str(q["kickoff"])[:10]<d]
            if len(tr)<40: continue
            a,b=fit(tr); a*=shrink; b=1+(b-1)*shrink; bs.append(b)
            m=float(r["model_margin"]); act=float(r["final_home"])-float(r["final_away"]); n+=1
            for k,mm in (("raw",m),("cal",a+b*m)):
                st[k][2]+=abs(mm-act)
                hs=r.get("home_spread")
                if hs is not None and act+float(hs)!=0 and abs(mm+float(hs))>=1.0:
                    st[k][0]+=1; st[k][1]+=(mm+float(hs)>0)==(act+float(hs)>0)
        if n: print(lg,"win",win,"shrink",shrink,"n",n,"b avg %.2f"%(sum(bs)/len(bs)),
                    " ".join(f"{k}: MAE {v[2]/n:.2f} ATS {v[1]}/{v[0]}={v[1]/max(v[0],1):.3f}" for k,v in st.items()))
