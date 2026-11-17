import csv, io
from app.manifest import canonical_digest, run_id
SAMPLE={"store":None,"rows":[{"source_line":2,"archive_id":"000123","reason":"OK"},{"source_line":5,"archive_id":"BAD","reason":"BAD_COLUMNS"}]}
def csv_text(rows):
    out=io.StringIO(); writer=csv.DictWriter(out,fieldnames=["source_line","archive_id","reason"],lineterminator="\n"); writer.writeheader(); writer.writerows(rows); return out.getvalue()
def run(payload):
    rows=payload.get("rows",SAMPLE["rows"]); digest=canonical_digest(rows); rid=run_id(rows); store=payload.get("store")
    result={"input_count":len(rows),"valid_count":sum(r["reason"]=="OK" for r in rows),"quarantine_count":sum(r["reason"]!="OK" for r in rows)}
    if store: rid=store.record(digest,rid,result)["run_id"]
    return {"status":"READY","run_id":rid,"digest":digest,"csv":csv_text(rows),**result,"reason":"OK"}
