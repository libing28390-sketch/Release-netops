# EVAL-017 浏览器关键路径验证入口

## 验证入口

服务启动后依次打开：

- `http://192.168.56.1:5400/ai/providers`
- `http://192.168.56.1:5400/ai/models`
- `http://192.168.56.1:5400/ai/copilot`
- `http://192.168.56.1:5400/ai/knowledge`
- `http://192.168.56.1:5400/ai/security`

## 预期结果

- Provider 页面显示脱敏 Key、Provider 数量和“所有请求经过安全网关”。
- Model 页面显示模型与 Provider 关联、场景路由和添加入口。
- Copilot 页面显示模型选择器、诊断范围和发送入口；空输入时发送按钮禁用。
- Knowledge 页面显示文档/版本、Source Registry、RAG Evaluation、Retrieval Trace 视图。
- Security 页面默认拒绝/安全网关状态、出口控制和策略演练入口可见。
- 浏览器缩窄到约 390px 时，页面不出现横向溢出。

## 实测结果

自动化前端 52 passed；已认证浏览器五条路径与窄屏检查通过；V1 PostgreSQL 基线 10/10。用户确认前 Checkbox 保持未勾选。

## PostgreSQL 说明

本任务的持久化权威验证使用 PostgreSQL；前端组件测试不建立数据库连接；SQLite 不作为测试或验收证据。
