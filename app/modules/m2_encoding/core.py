"""M2 编码判定。

候选解码必须严格成功、完整且不产生替换字符。UTF-8 的结构冗余很高，
严格解码成功即视为强证据；否则再按中文覆盖度打分在候选间裁决。
"""

SAMPLE = {"hex": "e6a1a3e58fb7"}
BOM = b"\xef\xbb\xbf"


def _score(text: str) -> int:
    han = sum(1 for c in text if "一" <= c <= "鿿") * 4
    controls = sum(1 for c in text if ord(c) < 32 and c not in "\r\n\t") * 8
    return han - controls


def _clean(text: str) -> bool:
    """严格解码后仍含控制字符或替换字符的候选不可信。"""
    if "�" in text:
        return False
    return not any(ord(c) < 32 and c not in "\r\n\t" for c in text)


def detect(blob: bytes):
    candidates = []
    for name in ("utf-8-sig", "gb18030"):
        try:
            text = blob.decode(name, "strict")
        except UnicodeDecodeError:
            continue
        if name == "gb18030" and text.startswith("﻿"):
            # GB18030 候选把 BOM 当普通字符时，说明 UTF-8 才是原编码。
            continue
        candidates.append({"encoding": name, "text": text, "score": _score(text)})

    if not candidates:
        return {"encoding": "REJECTED", "text": "", "reason": "DECODE_FAILED"}

    utf8 = next((c for c in candidates if c["encoding"] == "utf-8-sig"), None)
    if utf8 is not None and _clean(utf8["text"]):
        best = utf8
    else:
        best = max(candidates, key=lambda c: (c["score"], c["encoding"] == "utf-8-sig"))
    return {**best, "reason": "OK"}


def run(payload):
    raw = bytes.fromhex(payload.get("hex", SAMPLE["hex"]))
    out = detect(raw)
    return {
        "status": "READY",
        "input_count": len(raw),
        "valid_count": 1 if out["reason"] == "OK" else 0,
        "quarantine_count": 0 if out["reason"] == "OK" else 1,
        **out,
    }
