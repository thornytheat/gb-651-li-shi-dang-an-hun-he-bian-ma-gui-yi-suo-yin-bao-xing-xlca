from decimal import Decimal, InvalidOperation
SAMPLE={"values":["000123","9007199254740993","N/A"," 07 "]}
NULLS={"","-","N/A","NULL","未知"}
def preserve(value):
    if value is None: return {"state":"null","value":None}
    raw=str(value); stripped=raw.strip()
    if stripped in NULLS: return {"state":"sentinel","value":None,"raw":raw}
    return {"state":"value","value":stripped,"raw":raw}
def decimal_text(value):
    try: return format(Decimal(str(value).replace(",","")),"f")
    except InvalidOperation: raise ValueError("INVALID_VALUE")
def run(payload):
    values=payload.get("values",SAMPLE["values"]); out=[preserve(v) for v in values]; return {"status":"READY","input_count":len(out),"valid_count":sum(x["state"]=="value" for x in out),"quarantine_count":0,"values":[x["value"] for x in out],"reason":"OK"}
