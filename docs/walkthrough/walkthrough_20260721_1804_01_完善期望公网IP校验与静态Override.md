# 完善企业级公网IP校验与静态Override 验证报告

## 完成摘要

本次重构全面解决了前一版本实现中真实检测结果与人工配置混淆、缺少连续确认导致误报、配置格式错误静默失效以及健康状态强绑定等问题，使互联网出口 IP 校验模块达到生产级水平。

### 核心改动

1. **数据模型升级**：新建 `m0027_outbound_egress_metadata` 迁移，为 `outbound_probe_runs` 和 `outbound_egress_ip_events` 增加 `public_ip_source`（VARCHAR(32)）与 `public_ip_verified`（BOOLEAN）字段，区分 `detected` / `static_override` / `cached` / `unknown` 四种来源。

2. **多来源可信度识别**：重构 `detect_egress_ip()`，返回结构化字典包含 `public_ip_source`、`public_ip_verified`、`confidence`（high/medium/low）、`providers_succeeded`、`providers_total`。静态 Override 直接标记为 `static_override` + `verified=false`，不伪装为真实检测结果。

3. **启动时严格配置校验**：实现 `validate_expected_egress_ip_config()`，在模块加载和运行时动态校验 `OUTBOUND_PROBE_EXPECTED_EGRESS_IP` 配置。遇到非法 IP/CIDR（如 `abc`、`/33`）时输出 ERROR 日志，禁用期望校验但不阻止服务启动，避免静默失效。

4. **连续 2 次确认防抖**：在 `_record_egress_event()` 中实现基于历史事件的防抖状态机——必须连续 2 次检测到同一非预期 IP 才确认漂移告警，连续 2 次恢复才确认关闭告警，避免偶发网络波动误报。

5. **连通性与 IP 合规状态解耦**：
   - API 返回 `connectivity_status`（纯连通性）和 `overall_status`（综合状态）分离字段。
   - 新增 `OUTBOUND_PROBE_EGRESS_IP_MISMATCH_AFFECT_HEALTH` 环境变量控制 IP 漂移是否影响综合健康状态（默认 `true`）。
   - 新增 `OUTBOUND_PROBE_EGRESS_IP_MISMATCH_SEVERITY` 环境变量控制告警级别（`info` / `warning` / `critical`，默认 `warning`）。

6. **结构化 API 返回**：`get_outbound_status()` 返回完整的 `egress_ip` 元数据对象和 `status_reasons[]` 结构化告警列表，包含 IP 漂移类型、严重等级、中文消息。

7. **IPv6 双栈支持**：`_check_ip_matches_expected()` 使用 `ipaddress` 标准库的 `version` 属性进行 IPv4/IPv6 跨协议隔离匹配，支持压缩格式 IPv6、混合配置。

9. **前端默认历史展示时间调整**：将 `src/store/monitoringStore.ts` 中的默认 `outboundHistoryHours` 从 24 小时缩减为 1 小时，使用户在打开互联网出口健康仪表盘时默认看到最近 1 小时的高分辨率图表。

10. **后端冷启动探测兜底**：优化 `run_outbound_probe_once`，当缓存的 `outbound_egress_ip_events` 为空（如全新数据库或冷启动）时，自动触发一次真实的出口 IP 在线检测并写入数据库，解决首次运行时公网 IP 字段显示为 `--` 的问题。

11. **中文化翻译优化**：将 `.env` 及 `.env.example` 中的所有英文注释与配置说明全部翻译为中文；同时将后端状态输出的默认提示 "X of Y targets available" / "No enabled targets" 翻译为对应的中文提示，并在告警及状态描述中完全汉化。

## 实际修改文件

| 文件 | 动作 |
|------|------|
| `backend/database/migrations/m0027_outbound_egress_metadata.py` | 新建 |
| `backend/services/outbound_probe_service.py` | 重构 |
| `backend/tests/scheduled_jobs/test_outbound_expected_ip.py` | 重写 |
| `src/types/outbound.ts` | 扩展 |
| `src/components/OutboundHealthPanel.tsx` | 升级 |
| `src/store/monitoringStore.ts` | 修改 |
| `.env` | 追加配置 |
| `.env.example` | 追加配置 |

## 验证命令与结果

### 后端单元测试
```bash
.venv\Scripts\python -m pytest backend/tests/scheduled_jobs/test_outbound_expected_ip.py -v
```
```
6 passed in 7.45s
```

### 全量后端回归
```bash
.venv\Scripts\python -m pytest backend/tests -v
```
```
126 passed, 25 subtests passed in 7.84s
```

### 前端 TypeScript 类型检查
```bash
npm run lint
```
```
tsc --noEmit — 0 errors
```

### 前端生产构建
```bash
npm run build
```
```
✓ 3365 modules transformed, built in 14.74s
```

## 未验证项

- 实际多运营商出口切换场景的端到端验证（需要真实双出口网络环境）
- IPv6 双栈出口的实际检测（需要具备 IPv6 公网出口的环境）
- 前端 UI 在实际漂移告警触发时的渲染效果（需要触发真实 IP 漂移）

## 剩余风险与后续建议

- 当前 `outbound_egress_ip_events` 表没有自动清理老旧事件的机制，长期运行可能需要增加保留策略
- `OUTBOUND_PROBE_EXPECTED_EGRESS_IP` 的运行时热更新依赖环境变量缓存比对，如果通过 `.env` 文件修改需要重启服务才能生效
