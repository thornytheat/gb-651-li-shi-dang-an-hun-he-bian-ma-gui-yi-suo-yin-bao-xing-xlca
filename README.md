# 历史档案混合编码归一与索引保形

        面向一线复核人员的单服务数据工作台。样例数据随仓库提供，结论保留行号、原因码和原值。

        ## 业务模块

        - M1 文件采信：`/api/intake/run`
- M2 编码判定：`/api/encoding/detect`
- M3 字段保形：`/api/fields/normalize`
- M4 内容归一：`/api/content/normalize`
- M5 索引对账：`/api/reconcile`
- M6 批次导出：`/api/export/evidence.csv`

        ## 核心规则

        候选解码必须完整且无替换字符；档号、盒号与超大流水号始终按字符串逐字保留。

        ## M1 分段接收

        馆方文件常在中途被同名修订。接收按「文件名 + 接收版本」建档，同名新内容自动另起版本，
        旧版本的已确认字节与回执永久保留、只读可查。

        ```bash
        # 1. 开启接收版本（同摘要同长度重复调用会复用原版本）
        POST /api/intake/sessions            {"file_name":"a.csv","total_length":100,"sha256":"..."}
        # 2. 从确认位置续传，可重试
        POST /api/intake/sessions/{id}/chunks {"offset":0,"hex":"..."}   # 或 {"data":"<base64>"}
        # 3. 只读复核
        GET  /api/intake/sessions/{id}                  # confirmed_length / next_offset
        GET  /api/intake/sessions/{id}/receipt          # 整份核验通过后的回执
        GET  /api/intake/sessions/{id}/content          # 已确认字节本身
        GET  /api/intake/files/{name}/receipts          # 历史的全部版本回执
        ```

        版本寻址等价入口：`/api/intake/files/{name}/versions/{v}/chunks` 与 `/complete`。
        同一段重发不重复追加；乱序、越界、摘要不符、与已确认字节不一致的片段一律拒收；
        写入使用 `BEGIN IMMEDIATE` 事务，并发续传不会互相覆盖。
        整份长度、摘要与完整解码全部通过后才解析并生成回执；缺段或错版不产出档案。

        ## 启动

        ```bash
        docker compose up --build
        ```

        浏览器访问 `http://localhost:18210`。运行测试：

        ```bash
        docker compose exec -T app pytest -q
        ```

        ## 样例流程

        依次运行六个模块；最后在批次页复核输入、有效、隔离与输出合计。同一输入摘要重复执行时复用原 `run_id`。

        ## 已知不覆盖

        不处理加密文件与需要外部密钥的对象；不连接真实生产存储。
