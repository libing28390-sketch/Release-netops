# 实现期望公网IP校验与静态Override 验证报告

本报告记录了期望公网 IP 段校验以及内网静态 Override 特性的验证情况。

## 完成摘要

1. **功能实现**：
   - 实现了对 `OUTBOUND_PROBE_STATIC_EGRESS_IP` 的解析，支持在离线环境完全跳过外网探测。
   - 实现了基于 Python `ipaddress` 库的 `_check_ip_matches_expected` 高精度验证引擎，完整支持单 IP、多个逗号分隔的 IP 以及 CIDR 网段白名单（如 `/29` 段）。
   - 在 `run_outbound_probe_once` 中植入漂移降级逻辑：真实公网 IP 偏移白名单时，运行状态降级为 `degraded`，并在 Reason 中展现详细的漂移警告。
2. **测试保障**：
   - 创建了 [test_outbound_expected_ip.py](file:///d:/nexora/nexora-private/backend/tests/scheduled_jobs/test_outbound_expected_ip.py) 测试套件，覆盖了全部设计场景。
   - 运行项目全量 `pytest` 122/122 个测试用例均 100% 成功通过。

## 实际修改文件清单

* [outbound_probe_service.py](file:///d:/nexora/nexora-private/backend/services/outbound_probe_service.py)
* [test_outbound_expected_ip.py](file:///d:/nexora/nexora-private/backend/tests/scheduled_jobs/test_outbound_expected_ip.py)
* [.env](file:///d:/nexora/nexora-private/.env)
* [.env.example](file:///d:/nexora/nexora-private/.env.example)

## 验证结果

### 1. 单元测试结果
运行单元测试命令：
```bash
.venv\Scripts\python -m pytest backend/tests/scheduled_jobs/test_outbound_expected_ip.py
```
输出通过：
```text
backend\tests\scheduled_jobs\test_outbound_expected_ip.py ..             [100%]
============================== 2 passed in 0.39s ==============================
```
运行全量回归测试：
```bash
.venv\Scripts\python -m pytest backend/tests
```
输出通过：
```text
============================= 122 passed in 2.80s =============================
```
验证逻辑和新增测试集工作状态完全正常。
