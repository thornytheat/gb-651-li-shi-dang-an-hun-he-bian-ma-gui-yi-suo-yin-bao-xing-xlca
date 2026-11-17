SAMPLE={"hex":"e6a1a3e58fb7"}
def detect(blob: bytes):
    if blob.startswith(b"\xef\xbb\xbf"):
        text=blob.decode("utf-8-sig","strict")
        return {"encoding":"utf-8-sig","text":text,"score":sum(1 for c in text if "\u4e00"<=c<="\u9fff")*4,"reason":"OK"}
    candidates=[]
    for name in ("utf-8-sig","gb18030"):
        try:
            text=blob.decode(name,"strict")
            score=sum(1 for c in text if "\u4e00"<=c<="\u9fff")*4-sum(1 for c in text if ord(c)<32 and c not in "\r\n\t")*8
            candidates.append((score,name,text))
        except UnicodeDecodeError: pass
    if not candidates: return {"encoding":"REJECTED","text":"","reason":"DECODE_FAILED"}
    score,name,text=max(candidates,key=lambda x:(x[0],x[1]=="utf-8-sig"))
    return {"encoding":name,"text":text,"score":score,"reason":"OK"}
def run(payload):
    raw=bytes.fromhex(payload.get("hex",SAMPLE["hex"])); out=detect(raw); return {"status":"READY","input_count":len(raw),"valid_count":1 if out["reason"]=="OK" else 0,"quarantine_count":0 if out["reason"]=="OK" else 1,**out}
