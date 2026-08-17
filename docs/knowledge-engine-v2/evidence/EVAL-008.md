# EVAL-008 Evidence

## Task ID

EVAL-008

## 目标

建立人工 Golden Answer、适用版本和引用标注流程。

## 修改文件

- `docs/knowledge-engine-v2/eval/eval-golden-annotations-v1.yaml`
- `docs/knowledge-engine-v2/eval/eval-golden-annotations-v1.manifest.json`
- `docs/knowledge-engine-v2/architecture/EVAL-008-GOLDEN-ANNOTATION-CONTRACT.yaml`
- `scripts/knowledge_engine_v2_eval_golden_annotation_check.py`
- `tests/knowledge_engine_v2/test_eval008_golden_annotations.py`
- `docs/walkthrough/20260817_eval008_golden_annotations.md`

## 实现内容

冻结 12 条人工 Golden Answer，覆盖两家厂商六类意图；每条记录适用 vendor/product/OS/train/release relation、官方 fixture、source version、locator、claim ID、annotator/reviewer 和冻结状态。契约同时定义 clarify/no-match 不产 citation 的规则和 adjudication 流程。

## 执行命令

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts/knowledge_engine_v2_eval_golden_annotation_check.py
.venv\Scripts\python.exe -m pytest tests/knowledge_engine_v2/test_eval008_golden_annotations.py -q -p no:cacheprovider
.venv\Scripts\python.exe -m py_compile scripts/knowledge_engine_v2_eval_golden_annotation_check.py tests/knowledge_engine_v2/test_eval008_golden_annotations.py
git diff --check
```

## 测试结果

PASS。Annotation count `12`、citation count `12`、12 个厂商/意图组合各 1 条、全部 frozen；专项测试 `1 passed`；YAML、py_compile、diff 检查通过。

## 数据库影响

无表、无迁移、无生产数据写入。本任务没有连接 PostgreSQL 或 SQLite；SQLite 未作为验收证据。后续持久化评测只接受 PostgreSQL。

## 安全影响

标注集只保存 bounded 答案、fixture locator 和 claim ID，不嵌入原始 source 正文、凭据、租户或 ACL；校验器扫描敏感标记。

## 回滚方式

删除 EVAL-008 fixture、manifest、校验器、测试和文档即可回滚；无数据库 rollback。

## 已知限制

当前为首批人工黄金样本，不代表完整 120 条都已人工审阅；扩展集必须使用新 revision ID 并重复双人复核。

## 最终结论

PASS
