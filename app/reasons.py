REASONS = {
    "BAD_COLUMNS": "字段数量不符", "EMPTY_VALUE": "必要值为空",
    "DUPLICATE_CONFLICT": "同一业务键取值冲突", "TRUNCATED": "尾记录不完整",
    "INVALID_VALUE": "值不符合定义", "STALE_VERSION": "提交版本已过期",
    # 分段接收
    "INVALID_CHUNK": "片段为空或格式不合法",
    "CHUNK_CONFLICT": "同一段号的已确认字节不可改写",
    "CHUNK_DIGEST_MISMATCH": "片段摘要与声明不符",
    "CHUNK_OFFSET_MISMATCH": "片段偏移与已确认位置不符",
    "CHUNK_TOO_LARGE": "片段超出整份声明长度",
    "OUT_OF_ORDER": "片段乱序，须从确认位置续传",
    "REVISION_CONFLICT": "同名同版本的文件摘要不一致",
    "REVISION_MISMATCH": "片段属于其他接收版本",
    "SESSION_NOT_FOUND": "接收版本不存在",
    "UPLOAD_CLOSED": "接收版本已封存，不能再追加片段",
    "INCOMPLETE": "缺少片段，整份尚未收齐",
    "LENGTH_MISMATCH": "整份长度与声明不符",
    "DIGEST_MISMATCH": "整份内容摘要与声明不符",
    "DECODE_FAILED": "整份内容无法按完整候选解码",
}


def reason(code: str) -> str:
    return REASONS.get(code, "未登记原因")
