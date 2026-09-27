# Nexora v1.0.10

## v1.0.10 本次更新

- 定时作业等敏感审批支持按审批人可用能力选择 MFA 动态码、邮箱验证码或飞书验证码，不再限定只能通过飞书授权。
- 修正 Grafana、vmagent 与 Nginx 子路径之间的内部采集路径，避免 Grafana `/metrics` 请求被重定向到公网 HTTPS 地址后抓取失败。
- 修正 Docker cAdvisor 采集配置与容器指标看板，完善容器 CPU、内存工作集、磁盘读取/写入速率的观测，并改善容器缺少数据时的排查线索。
- 优化多个 Grafana 看板的运行时间展示；告警运营看板将 `retrying` 纳入失败尝试，并区分“暂无已完成投递”和“数据暂不可用”。
- 优化告警级别中文显示，并将通知投递指标名称调整为“告警成功率”。

升级后请确认 Compose 已按新版本重新创建 cAdvisor、vmagent、Grafana 与 Nginx 容器；旧容器日志中关于 Docker overlay layer 的错误不会因只替换看板文件而消失。

## 发布定位

v1.0.9 起，Nexora 服务端的发布形态收敛为 **Linux / Ubuntu / Docker**。v1.0.8 是最后一个提供 Windows 原生桌面服务端发行包的版本；v1.0.9 不再构建或发布 Windows 桌面安装包、桌面启动器或 Windows 服务端发布分支。Windows 操作员工作站 Agent 仍作为独立附件发布，用于从 Windows 浏览器访问 Linux 服务端并拉起本机浏览器/终端。

Windows 网络设备的资产管理、SNMP 采集、SSH/WinRM 远程管理能力继续保留。这里的变化只针对 Nexora 平台自身的部署与发行形态。

## v1.0.9 基线更新

- 移除 Windows 桌面启动器、原生安装包、Windows 专用打包资源及 Windows 发布流水线。
- 发布工作流只生成 Linux / Ubuntu / Docker 归档，并将本说明作为 GitHub Release 正文。
- 前端 Terminal Agent 配置入口按浏览器所在工作站提供 Windows Agent 或 Linux/Ubuntu 安装方式。
- Windows 工作站 Agent 独立构建并挂载到同一版本 Release，不代表恢复 Windows 服务端部署支持。
- 配置备份与 PAM 录像接入统一对象存储接口，支持本地存储和 S3 兼容存储配置。
- SNMP 同步主机名时同步更新资产管理中的主机名，资产管理数据继续作为初始数据源。
- Docker 构建过程保留阶段日志，便于查看构建进度和失败原因。
- 增加 SNMP Walk 诊断与公共/厂商 MIB 查询，解析结果突出展示设备、系统和 LLDP 邻居等关键信息。
- 高级 OID 浏览器显示资产模板中的完整厂商目录，并通过 LibreNMS 规则、sysObjectID 和 sysDescr 自动识别受管设备厂商；登记信息与探测结果冲突时明确提示。
- LLDP 诊断补齐本地接口名映射，可结合 LLDP 本地端口表和 IF-MIB `ifName` 将邻居端口索引解析为接口名称。
- 修正网络接口指标的序列身份与 Grafana 面板聚合，减少重复接口曲线并完善 Linux/Windows 主机监控视图。
- Docker 新安装默认启用内置 SeaweedFS S3 并生成安装专用凭据；现有本地录像和配置备份不会自动迁移。
- Grafana 通过同源认证代理复用 Nexora 登录会话，匿名访问保持关闭；专用认证网络使用 Docker IPAM 动态分配，并由 Nginx 统一剥离外部 `/grafana/` 前缀。
- Docker 前端镜像只安装构建所需依赖，避免与 Promptfoo 相关的原生 SQLite 开发依赖影响离线或受限环境构建。

### v1.0.9 监控与告警基线

- 告警规则支持租户范围隔离、从 CMDB 确认执行设备、资产范围匹配，以及按通知组投递 Webhook/邮件告警；历史通知方式按当前支持的渠道兼容归一化。
- 告警详情和事件时间线查询按设备租户范围过滤，确保跨租户事件不会出现在详情中。
- 修复在线设备返回 SNMP CPU/内存指标时告警采集循环引用缺失设备名、导致本轮处理提前中断的问题。
- 邮件告警支持管理多条 SMTP 通道，并按已启用通道选择收件目标。宿主机 CPU、内存和磁盘阈值用于平台健康状态计算，不作为告警投递渠道。
- 新增平台健康、告警运营和出向探测质量看板；出向探测补充 ICMP 丢包与抖动数据，并显示明确的速率单位和接口别名。
- Prometheus 可抓取聚合后的平台、告警和出向探测指标，为 Grafana 提供看板数据。
- 新增 PostgreSQL 迁移以支持租户告警规则、出向探测质量字段和旧告警通知数据归一化。升级前请备份数据库。

## 升级提示

- Windows 原生服务端部署请继续使用 v1.0.8；Linux/Docker 新部署和升级使用 v1.0.10。
- Windows 用户访问 v1.0.10 的 Linux 服务端时，安装同一版本 Release 中的 Windows Workstation Agent。
- 从 v1.0.8 或更早版本迁移到 v1.0.10 前，请先备份数据库、`data/` 及现有配置备份/PAM 录像数据。
- Docker 新安装默认使用内置 SeaweedFS S3；总可用空间由 Docker 数据目录所在磁盘决定，当前没有前端 bucket 容量配额。
- 更新现有 `.env` 时保留原有存储后端；切换到 S3 不会自动迁移本地录像和配置备份，需按单独迁移流程处理。
