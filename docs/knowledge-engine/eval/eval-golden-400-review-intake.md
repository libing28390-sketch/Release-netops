# 400 条 Gold 用例审核接收单

状态：生产 Gold `NOT_READY`；本文件是填报模板，不是生产数据集。当前另有用户授权生成的 `test_only=true` 合成 CI 夹具，不能被当成人工审核证据。

目标生产数据集必须满足 [eval-golden-400-contract-v1.yaml](eval-golden-400-contract-v1.yaml)。当前仓库没有 400 条可追溯的人工案例、答案和真实来源证据；`eval-golden-400.yaml` 中的合成夹具只用于测试合同校验，不能替代生产数据。这里保留正式接收入口，不复制 50 条、不扩展旧的 120 条，也不把合成内容标记为生产人工审核。

## 提交包必须包含

提交人将以下内容放入一个新的、不可覆盖的 `dataset_id`：

1. 400 条完整案例，包含合同规定的 19 个字段；
2. 每条 `golden_answer` 对应的 `source_evidence`，至少有真实 `document_id` 和定位信息；
3. 所有知识/配置/排障/工具高风险案例的领域审核字段；
4. 主标注人、主审核人和至少 80 条独立第二审核记录；
5. 脱敏声明：没有密码、Token、SNMP Community、私钥、客户/租户/用户标识和生产数据；
6. 数据集文件、审核记录和来源证据的 SHA256，保留上一版文件。

## 固定分布矩阵

| 类别 | 总数 | 建议 train | 建议 debug | 建议 hidden |
|---|---:|---:|---:|---:|
| knowledge_config_reference | 140 | 84 | 28 | 28 |
| troubleshooting | 70 | 42 | 14 | 14 |
| configuration_validation_diagnostic | 50 | 30 | 10 | 10 |
| asset_alarm_query | 40 | 24 | 8 | 8 |
| intent_clarification_missing_parameter | 40 | 24 | 8 | 8 |
| tool_call_dangerous_operation | 30 | 18 | 6 | 6 |
| negative_security_no_match | 30 | 18 | 6 | 6 |
| 合计 | 400 | 240 | 80 | 80 |

厂商总量必须落在合同范围内：Huawei `90–110`、Cisco `90–110`、H3C `72–88`、Ruijie `54–66`、cross/unknown `54–66`。至少 80 条要有独立第二审核人，且第二审核人与主标注人、主审核人不同。

## 单条用例模板

将下面的记录复制到新数据集后逐条填充。空值、推断值和 `TBD` 不能进入 `status: frozen` 的提交包。

```yaml
- id: GOLD-400-001
  query: ""
  category: knowledge_config_reference
  vendor: Huawei
  platform: huawei_vrp
  feature: vlan
  expected_outcome: answer
  gold_document_ids: []
  acceptable_document_ids: []
  citation_required: true
  risk_level: low
  split: train
  golden_answer: ""
  source_evidence:
    - document_id: ""
      locator: ""
  annotator: ""
  reviewer: ""
  reviewed_at: ""
  annotation_status: pending_human_review
  domain_reviewed: false
  domain_reviewer: ""
  domain_reviewed_at: ""
  secondary_reviewer: ""
```

## 交付前命令

生产数据集完成人工审核并保存为新的 Dataset ID 后，才执行普通校验；当前合成夹具也可以用来验证 CI 合同链路：

```powershell
$env:PYTHONPATH = "backend"
python scripts/knowledge_eval_gold_400_check.py `
  --dataset docs/knowledge-engine/eval/eval-golden-400.yaml `
  --contract docs/knowledge-engine/eval/eval-golden-400-contract-v1.yaml `
  --output docs/knowledge-engine/eval/eval-golden-400-check.json
```

生产 Release 还必须使用 `--require-production`：

```powershell
python scripts/knowledge_eval_gold_400_check.py `
  --dataset docs/knowledge-engine/eval/eval-golden-400.yaml `
  --contract docs/knowledge-engine/eval/eval-golden-400-contract-v1.yaml `
  --require-production `
  --output docs/knowledge-engine/eval/eval-golden-400-production-check.json
```

只有生产模式输出满足 `status=PASS`、`case_count=400`、`errors=[]`、`test_only=false`、`secrets=false`、`external_network=forbidden`，并且 50-anchor 复核、真实 PostgreSQL 投影、CI 和 UAT 也通过，才可进入 Release Candidate。当前合成夹具的普通检查为 `PASS`，生产检查为 `FAIL`，真实人工 Gold 仍为 `NOT_READY`。
