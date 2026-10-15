from __future__ import annotations
import json, os, sys, time
from pathlib import Path
from urllib.parse import urlparse
import requests

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/"NextGen Research"
sys.path.insert(0,str(ROOT))
from fundamental_research_v2_phase2a.scaled_mapping_validation import latest_event_groups
from fundamental_research_v2_phase2a.xbrl_extraction import parse_xbrl_document, parse_ixbrl_document

TARGET={"BDL","BSE","GODREJCP","HINDZINC","OFSS"}
events=json.loads((Path(os.environ["SRE_PHASE5_DIAGNOSTICS_ROOT"])/"fundamental_v2_phase2a1_scaled"/"all_target_events.json").read_text(encoding="utf-8"))
groups=latest_event_groups(events)
selected=[]
for sym in sorted(TARGET):
    items=[x for x in groups if x.get("symbol")==sym and x.get("xbrl_url")]
    items=sorted(items,key=lambda x:(str(x.get("quarter_end") or ""),x.get("reporting_basis")=="CONSOLIDATED"),reverse=True)
    selected.append(next((x for x in items if x.get("reporting_basis")=="CONSOLIDATED"),items[0]))

s=requests.Session();s.headers.update({"User-Agent":"Mozilla/5.0 Chrome/155","Accept":"application/xml,text/xml,*/*"})
out=[]
for e in selected:
    url=e["xbrl_url"]
    r=s.get(url,timeout=45)
    if r.status_code==404 and e.get("ixbrl_url"):
        r=s.get(e["ixbrl_url"],timeout=45);r.raise_for_status()
        doc=parse_ixbrl_document(r.content,source_url=e["ixbrl_url"],source_event=e)
    else:
        r.raise_for_status();doc=parse_xbrl_document(r.content,source_url=url,source_event=e)
    ctx={x.get("context_id"):x for x in doc.get("contexts",[])}
    units={x.get("unit_id"):x for x in doc.get("units",[])}
    hits=[]
    for f in doc.get("numeric_facts",[]):
        if f.get("concept_local_name")!="DebtEquityRatio": continue
        c=ctx.get(f.get("context_ref")) or {}
        hits.append({
          "raw_value":f.get("raw_value"),"scale":f.get("scale"),"decimals":f.get("decimals"),
          "sign":f.get("sign"),"unit_ref":f.get("unit_ref"),"unit":units.get(f.get("unit_ref")),
          "context_ref":f.get("context_ref"),"instant":c.get("instant"),
          "start_date":c.get("start_date"),"end_date":c.get("end_date"),
          "dimensions":c.get("dimensions"),
        })
    display_snippets=[]
    ixurl=e.get("ixbrl_url")
    if ixurl:
        try:
            hr=s.get(ixurl,timeout=45)
            if hr.ok:
                text=hr.text
                for token in ("Debt Equity Ratio","Debt-Equity Ratio","DebtEquityRatio"):
                    pos=text.lower().find(token.lower())
                    if pos>=0:
                        display_snippets.append(text[max(0,pos-500):pos+1200])
        except Exception as exc:
            display_snippets.append("IXBRL_DISPLAY_ERROR:"+type(exc).__name__+":"+str(exc))
    out.append({"symbol":e.get("symbol"),"quarter_end":e.get("quarter_end"),"basis":e.get("reporting_basis"),"hits":hits,"display_snippets":display_snippets})
print(json.dumps(out,indent=2))
Path(os.environ["SRE_DEBT_SEMANTICS_OUT"]).write_text(json.dumps(out,indent=2),encoding="utf-8")
