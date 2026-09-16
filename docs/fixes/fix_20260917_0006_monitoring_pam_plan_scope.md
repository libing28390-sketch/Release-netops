# 监控计划范围、SNMP 凭据与 PAM 提示修复

## 目的

整理 Monitoring V1 的 Docker 部署、计划编辑/测试和目标范围配置，并明确区分 SNMP 凭据与 SSH 管理凭据；同时让 Web PAM 在本机 Terminal Agent 不可用时给出可执行的诊断提示。

## 根因

- Compose 新增监控服务的健康检查会被本机代理返回 502，且部署脚本未纳入监控镜像和服务。
- 计划页只有原始 JSON 和编译按钮，没有结构化模块、目标范围和编辑反馈。
- 监控编译器曾在缺少 `snmp_credential_id` 时回退到 SSH `credential_id`。
- Web PAM 将本机 Agent 连接失败统一显示为泛化网络错误；远程页面来源也可能未加入 Agent allowlist。

## 修改

- 监控服务健康检查统一使用本地地址和 `wget -Y off`；部署脚本的在线、离线和镜像归档流程纳入 VictoriaMetrics、vmagent、SNMP Exporter。
- 采集计划支持编辑、结构化模块/Variant、间隔/超时校验、目标范围（全部在线、复合筛选、IP、站点、角色、标签）和编译测试结果展示。
- 计划目标只匹配 CMDB 设备；SNMP Credential 优先，设备/资产 Community 作为兼容回退，绝不复用 SSH 凭据。
- Web PAM/Terminal Agent 错误提示区分 Agent 未运行、来源未允许、版本不支持和会话过期。

## 验证

- `npm run lint`
- `npm run test:frontend -- --run src/utils/localTerminal.test.ts`（2 passed）
- 隔离目录 `npm run build -- --outDir .tmp-monitoring-build`
- Python 编译、Compose YAML 解析、目标范围与 SNMP 凭据分离脚本检查通过

## 未验证项

- 本机未安装 pytest，未运行后端 pytest 套件。
- Docker 真实设备 SNMP 数据面仍需在目标主机用已授权设备和 SNMP 凭据验收。

## 回滚

回滚本提交即可恢复旧的计划表单、Agent 提示、编译凭据选择和部署服务清单；不会删除数据库数据卷或设备凭据。
