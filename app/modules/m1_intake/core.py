import csv, io
SAMPLE={"text":"档号,盒号,题名\n000123,07,年度 汇编\n档号,盒号,题名\n9007199254740993,08,会议\nBAD,09\n"}
def scan(text: str):
    rows=[]; quarantine=[]; empty=0; header=None
    reader=csv.reader(io.StringIO(text, newline=""))
    for line,row in enumerate(reader,1):
        if not row or not any(x.strip() for x in row): empty+=1; continue
        if header is None: header=[x.lstrip("\ufeff") for x in row]; continue
        if [x.lstrip("\ufeff") for x in row]==header: continue
        if len(row)!=len(header): quarantine.append({"source_line":line,"reason":"BAD_COLUMNS","raw":row}); continue
        rows.append(dict(zip(header,row))|{"source_line":line})
    return {"rows":rows,"quarantine":quarantine,"empty":empty,"header":header}
def run(payload):
    out=scan(payload.get("text",SAMPLE["text"])); return {"status":"READY","input_count":len(out["rows"])+len(out["quarantine"])+out["empty"],"valid_count":len(out["rows"]),"quarantine_count":len(out["quarantine"]),"header":out["header"],"reason":out["quarantine"][0]["reason"] if out["quarantine"] else "OK"}
