# OBS-006 检索质量监控

检索监控现在把四类质量问题分开:

- No Match：最终没有可用文档，输出 `no_match_rate`。
- 错误厂商：结果厂商与请求的规范厂商不一致，计数但不会静默修正。
- 版本冲突：显式请求与已知不兼容版本冲突，继续 hard-filter，并记录冲突次数。
- 低置信度：最终 relevance score 小于 0.45，保留 top score 和计数供运维观察。

运维可从 `/api/ai/metrics` 查看聚合计数，从 Retrieval Trace 的 `runtime.quality` 查看单次脱敏质量信号。原始查询、文档正文、SQL 和异常正文不进入这些监控字段。
