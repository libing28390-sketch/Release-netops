# ING-010 walkthrough

1. `parse_and_clean_document` 生成同一份受限 `CleanedDocument`。
2. `scan_document_security` 必须对相同 format 和 document SHA-256 返回结果；
   缺失、错配或隔离结果不能绕过。
3. `extract_document_metadata` 合并文档 Metadata 与受限 Source Metadata，执行
   NFKC、Key/值/类型/枚举/大小/冲突/安全验证。
4. 缺失或不识别的 Product、OS、Version、Platform、Vendor 和必填字段转换为
   `UNKNOWN` 或 `null`，记录原因与短哈希，不从正文或目录猜测。
5. 完整结果生成确定性 Metadata Hash 与 m0113 标量列投影；UNKNOWN 结果标记
   REVIEW 并交给 ING-011，隔离结果不允许进入 Entity Resolution。
6. 服务无网络、文件系统和数据库副作用；V1 Front Matter 路径保持不变。

Focused verification is in
`backend/tests/ai/test_ing010_document_metadata_extraction.py`.
