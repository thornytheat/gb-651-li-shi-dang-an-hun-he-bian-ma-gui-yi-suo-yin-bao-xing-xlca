SAMPLE={"index_ids":["000123","9007199254740993","000404"],"normalized_ids":["000123","9007199254740993","000777"],"quarantine":1,"empty":0}
def reconcile(index_ids, normalized_ids, quarantine=0, empty=0):
    left=set(map(str,index_ids)); right=set(map(str,normalized_ids)); missing=sorted(left-right); orphan=sorted(right-left)
    return {"index_count":len(index_ids),"output_count":len(normalized_ids),"missing":missing,"orphan":orphan,"quarantine_count":quarantine,"empty_count":empty,"balanced":len(normalized_ids)+quarantine+empty>=len(right)}
def run(payload):
    data=SAMPLE|payload; out=reconcile(data["index_ids"],data["normalized_ids"],data.get("quarantine",0),data.get("empty",0)); return {"status":"READY","input_count":out["index_count"],"valid_count":out["output_count"],**out,"reason":"DIFF" if out["missing"] or out["orphan"] else "OK"}
