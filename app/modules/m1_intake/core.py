"""M1 文件采信：整份字节核验通过后的解码与逐行解析。

解析只接受完整解码后的文本；行号按原文件 physical line 记录，
带换行的引号字段只算一条记录，但后续记录的行号仍与原文对齐。
"""

import csv
import io
from hashlib import sha256

SAMPLE = {"text": "档号,盒号,题名\n000123,07,年度 汇编\n档号,盒号,题名\n9007199254740993,08,会议\nBAD,09\n"}


def digest_bytes(blob: bytes) -> str:
    return sha256(blob).hexdigest()


def decode_bytes(blob: bytes) -> dict:
    """用 M2 的完整候选解码规则解码整份字节，绝不使用替换字符。"""
    from app.modules.m2_encoding.core import detect

    return detect(blob)


def scan(text: str) -> dict:
    """解析 CSV 文本，保留物理行号、原始字符串与前导零。"""
    rows: list[dict] = []
    quarantine: list[dict] = []
    empty = 0
    header = None
    reader = csv.reader(io.StringIO(text, newline=""))
    while True:
        start_line = reader.line_num + 1
        try:
            row = next(reader)
        except StopIteration:
            break
        if not row or not any(x.strip() for x in row):
            empty += 1
            continue
        cleaned = [x.lstrip("﻿") for x in row]
        if header is None:
            header = cleaned
            continue
        if cleaned == header:
            continue
        if len(row) != len(header):
            quarantine.append({"source_line": start_line, "reason": "BAD_COLUMNS", "raw": row})
            continue
        rows.append(dict(zip(header, row)) | {"source_line": start_line})
    return {"rows": rows, "quarantine": quarantine, "empty": empty, "header": header}


def parse_bytes(blob: bytes) -> dict:
    """整份字节 -> 编码判定 + 档案。解码不完整时不产出任何档案。"""
    decoded = decode_bytes(blob)
    result = {
        "encoding": decoded.get("encoding"),
        "decode_score": decoded.get("score", 0),
        "decode_reason": decoded.get("reason"),
        "byte_length": len(blob),
        "sha256": digest_bytes(blob),
        "header": None,
        "rows": [],
        "quarantine": [],
        "empty": 0,
        "input_count": 0,
        "valid_count": 0,
        "quarantine_count": 0,
        "reason": decoded.get("reason") or "DECODE_FAILED",
        "archive": None,
    }
    if decoded.get("reason") != "OK":
        return result
    parsed = scan(decoded["text"])
    quarantine = parsed["quarantine"]
    reason = quarantine[0]["reason"] if quarantine else "OK"
    result.update(
        {
            "header": parsed["header"],
            "rows": parsed["rows"],
            "quarantine": quarantine,
            "empty": parsed["empty"],
            "input_count": len(parsed["rows"]) + len(quarantine) + parsed["empty"],
            "valid_count": len(parsed["rows"]),
            "quarantine_count": len(quarantine),
            "reason": reason,
        }
    )
    result["archive"] = {
        "header": parsed["header"],
        "rows": parsed["rows"],
        "quarantine": quarantine,
        "empty": parsed["empty"],
        "input_count": result["input_count"],
        "valid_count": result["valid_count"],
        "quarantine_count": result["quarantine_count"],
        "reason": reason,
    }
    return result


def run(payload):
    """既有整份文本入口，保持原有返回字段。"""
    out = scan(payload.get("text", SAMPLE["text"]))
    return {
        "status": "READY",
        "input_count": len(out["rows"]) + len(out["quarantine"]) + out["empty"],
        "valid_count": len(out["rows"]),
        "quarantine_count": len(out["quarantine"]),
        "header": out["header"],
        "reason": out["quarantine"][0]["reason"] if out["quarantine"] else "OK",
    }
