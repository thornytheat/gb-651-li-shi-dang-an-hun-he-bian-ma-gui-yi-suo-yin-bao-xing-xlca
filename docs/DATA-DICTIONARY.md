# 数据字典

| 字段 | 类型 | 可空 | 定义 |
|---|---|---:|---|
| `run_id` | string | 否 | 输入摘要派生的稳定运行编号 |
| `source_line` | integer | 否 | 原文件物理行号 |
| `reason_code` | string | 是 | 隔离或冲突的稳定原因码 |
| `raw_value` | string | 是 | 未归一的原始证据 |
| `normalized_value` | string | 是 | 按项目规则得到的值 |
| `rule_version` | string | 否 | 计算规则版本 |

## 分段接收

| 字段 | 类型 | 可空 | 定义 |
|---|---|---:|---|
| `session_id` | string | 否 | 接收版本编号，由文件名与版本派生 |
| `file_name` | string | 否 | 馆方文件名 |
| `version` | integer | 否 | 同名文件的接收版本，自 1 递增；修订另起新版本 |
| `total_length` | integer | 否 | 整份字节数，开启接收时声明 |
| `declared_sha256` | string | 是 | 整份内容摘要；可在收尾时补充 |
| `confirmed_length` | integer | 否 | 已确认字节数，也是续传位置 `next_offset` |
| `chunk_offset` | integer | 否 | 片段在整份中的起始字节偏移 |
| `chunk_sha256` | string | 否 | 已确认片段的字节摘要，写入后不可改写 |
| `receipt_id` | string | 是 | 整份核验通过后生成的回执编号 |

同一个 `session_id` 内，只有紧接 `confirmed_length` 的片段会被追加；
重发同一段是幂等重试，不重复追加。与已确认字节不一致的同位置片段一律拒收。
`COMPLETE` 与 `INVALID` 都是终态，此后不再接受新片段。

字符串编号逐字保留，包括前导零与超大流水号。金额与计量值用 `Decimal`。时间值带偏移并以 UTC 参与比较。区间统一采用左闭右开。

