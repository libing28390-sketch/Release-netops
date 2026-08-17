# 2026-08-17 API-004 response and pagination

## 验证目标

验证管理员列表支持统一分页、排序、筛选元数据，且权限拒绝、参数校验和未知资源错误都能携带稳定 code 与 request_id。

## 结果

产品/别名、Source、Document 列表接入服务器 allowlist 分页排序；API 错误保留兼容 detail 并增加标准 error。后端回归 28/28、前端 20/20 文件 98/98 测试、TypeScript lint、Vite build、Python compile 全部通过。
