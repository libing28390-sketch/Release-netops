# 400 条官方来源自动评测集接收单

状态：官方来源自动评测 Dataset 已就绪；本文件保留接收和来源校验说明，不要求人工评审。50-anchor 仍有独立的人工 Gold 审核流程，不能与本文件混用。

目标 Dataset 必须满足 [eval-golden-400-contract-v1.yaml](eval-golden-400-contract-v1.yaml)。当前 `eval-golden-400.yaml` 使用官方 URL 支撑的自动生成策略：answer 用例绑定四厂商官方 HTTPS 来源，clarify/no-match 用例可以没有 Gold 文档。自动生成的答案不是人工签核结论，但人工评审不再是本项目 400 条数据门槛。

## 2026-09-05 最新运行证据

- 生产来源合同检查：`PASS`，`case_count=400`、`synthetic_data=false`、`production_eligible=true`、官方来源证据 `300` 条、`human_review_required=false`。
- 独立临时 PostgreSQL 检索：`PASS`，300 条 answer 的 Recall@5/10=`1.0`、MRR=`1.0`、厂商隔离失败=`0`、Feature 隔离失败=`0`；另外 100 条 clarify/no-match 均由安全网关路径处理，未调用低层检索。
- 该结果只证明 400 条 Dataset 的来源合同和独立 RAG 检索质量，不替代 50-anchor 的人工 Gold 签字、完整 Assistant/Citation UAT 或生产发布审批。

## 提交包必须包含

提交人将以下内容放入一个新的、不可覆盖的 `dataset_id`：

1. 400 条完整案例，包含合同规定的字段；
2. 每个 `answer` 案例的 `source_evidence` 至少包含一个真实 `document_id`、定位信息和官方 HTTPS URL；
3. 官方 URL 的主机必须与案例厂商的允许域名一致，不允许跳转后未经重新校验的第三方来源；
4. clarify/no-match 案例不得为了凑引用伪造 Gold 文档，可使用空的 `source_evidence`；
5. 脱敏声明：没有密码、Token、SNMP Community、私钥、客户/租户/用户标识和生产数据；
6. 数据集文件、来源 manifest 和来源证据的 SHA256，保留上一版文件；不需要 annotator/reviewer/二审字段。

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

厂商总量必须落在合同范围内：Huawei `90–110`、Cisco `90–110`、H3C `72–88`、Ruijie `54–66`、cross/unknown `54–66`。不要求独立第二审核人；来源是否为官方由 URL 主机、HTTPS 和来源 manifest 机器校验。

## 单条用例模板

将下面的记录复制到新数据集后逐条填充。空值、推断值和 `TBD` 不能进入 `status: frozen` 的提交包；人工评审字段不属于本合同。

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
    - document_id: "local.huawei.huawei_vrp.vlan.v1"
      locator: "official-page:feature=vlan"
      url: "https://info.support.huawei.com/enterprise/en/doc/example"
      source_type: official_url_backed_local_summary
```

## 交付前命令

官方来源自动 Dataset 生成并保存为新的 Dataset ID 后，执行普通校验：

```powershell
$env:PYTHONPATH = "backend"
python scripts/knowledge_eval_gold_400_check.py `
  --dataset docs/knowledge-engine/eval/eval-golden-400.yaml `
  --contract docs/knowledge-engine/eval/eval-golden-400-contract-v1.yaml `
  --output docs/knowledge-engine/eval/eval-golden-400-check.json
```

生产 Release 继续使用 `--require-production`，但该模式只要求非 test-only、非 synthetic、production_eligible 和官方来源证据，不要求人工评审：

```powershell
python scripts/knowledge_eval_gold_400_check.py `
  --dataset docs/knowledge-engine/eval/eval-golden-400.yaml `
  --contract docs/knowledge-engine/eval/eval-golden-400-contract-v1.yaml `
  --require-production `
  --output docs/knowledge-engine/eval/eval-golden-400-production-check.json
```

只有生产模式输出满足 `status=PASS`、`case_count=400`、`errors=[]`、`test_only=false`、`synthetic_data=false`、`production_eligible=true`、官方来源证据完整、`secrets=false`、`external_network=forbidden`，并且 50-anchor 质量、真实 PostgreSQL 投影、CI 和 UAT 也通过，才可进入 Release Candidate。400 条数据门禁通过不代表 50-anchor 或整体 Release 已通过。
