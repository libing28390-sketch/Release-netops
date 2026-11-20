# Nexora 配置管理模块使用手册

## 功能入口

备份中心 `/config/backup`、备份计划 `/config/schedule`、配置对比 `/config/diff`、配置搜索 `/config/search`、配置模板 `/config/templates`。

## 备份中心重点操作

默认显示最近 10 条批次。点击日期范围按钮打开自绘日历，选择开始和结束日期后查询；未来日期不可选，后端也会拒绝未来日期请求。批次详情支持 Site 切换、状态筛选、分页、Esc 关闭和导出 XLSX。

## 故障排查

“no valid config obtained”通常表示命令返回了错误、空结果或解析器未匹配。先检查凭据和连接，再核对厂商平台与 TextFSM 模板。导出文件包含批次汇总和设备明细，时间统一为本地可读格式。

