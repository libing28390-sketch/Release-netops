# Actions 后端失败修正走查

## 首次 Actions 结果

- workflow：`Build and Sync to Release Repo`
- run：`43328406081`
- commit：`f45952a0a975ce1591e1dfd1d8035ab93f24d94c`
- 后端 pytest 收集 4154 项，最终 3 项失败；Node、Vitest/build 与后续发布同步步骤因前置 job 失败而跳过。

## 修正

- 无路由上下文的 SNMPv2c 默认 ARP 表按已确认规则记录为 Global，因此更新对应测试预期；未知/显式 VRF 上下文仍保持其原有判定。
- 当前终端 API 测试设备标注为接入设备，使测试继续覆盖允许的终端采集源。
- 有界游标测试保留一个 router 负例，验证该设备被剔除后仍按游标从接入交换机中选取正确批次。

## 验证和后续

- 本地 pytest 因没有可验证隔离的数据库未运行；变更仅涉及测试夹具/断言。
- 新 SHA 推送后重新运行完整 Actions。最终仍需确认后端、前端和发布同步步骤都成功。
