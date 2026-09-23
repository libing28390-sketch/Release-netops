"""Versioned release notes for the Windows desktop client."""

CLIENT_VERSION = "1.0.9"
CLIENT_BUILD = "20260923.0001"
RELEASE_NOTES_BASELINE = "1.0.8"

RELEASE_NOTES = {
    "zh": (
        "• 【新增】引入统一对象存储抽象，支持本地存储和 S3-compatible Provider；SeaweedFS 可通过 Docker Profile 以单节点模式启用，PAM 录像和配置备份支持 spool、重试、状态可视化及旧路径迁移。",
        "• 【新增】配置备份中心增加对象存储状态面板，展示 Provider、健康状态、待处理/失败/旧路径对象数量和最近错误原因，帮助运维快速定位存储问题。",
        "• 【新增】SNMP 主机名同步以资产管理的 physical_assets 为源数据，手工同步、批量同步、后台采集和 SNMP discovery 均会同步资产、设备和拓扑观察。",
        "• 【新增】Docker 部署在 STORAGE_BACKEND=s3 时自动启用 object-storage Profile；构建阶段保留 npm、APT 和部署进度日志，便于定位安装失败原因。",
        "• 【加固】PostgreSQL-only 门禁清理 SQLite PRAGMA 兼容路径；对象存储凭据仅保留在服务端环境变量，不暴露给前端。",
        "• 【新增】Windows 发布基线升级为 PostgreSQL 18.6，安装包内置匹配的 pgvector 0.8.6，并增加数据库、扩展和运行时就绪检查。",
        "• 【新增】Windows 客户端与托盘统一 Nexora 品牌，保留 NetOps.exe 兼容入口；启动前显示数据库目标并要求密码二次确认，明确在线更新与完整安装包升级的边界。",
        "• 【新增】RackVision 机柜工作台支持 2D/3D 共用布局、容量/功耗/健康概览、设备端口信息和 3D 资产目录；3D 视图保持只读，避免误操作。",
        "• 【新增】NSOT 网络事实库新增采集模板、操作目录、任务预览、范围/定位摘要和模板管理；定时作业支持多对象筛选。",
        "• 【新增】IP 定位支持 Redis 协同缓存、并发任务租约、依赖代际、任务保留和 LLDP 快照证据。",
        "• 【新增】AI 中心新增 Provider、模型与场景路由、Prompt、Agent、模型健康、知识库和 RAG 检索测试能力。",
        "• 【新增】Copilot 支持配置范围澄清、结构化意图、引用证据和网络/IP 诊断；官方知识模板与评估流程同步完善。",
        "• 【新增】资产与终端新增 Web SSH、访问收藏、批量资产导入/管理入口、设备平台目录和 TextFSM 模板版本信息。",
        "• 【新增】监控增强设备健康维度、WAN 链路/出口拨测、告警证据、健康趋势和 SNMP 指标能力。",
        "• 【修复】修复 Windows 启动器 psycopg2 打包缺失、Qt ICU DLL 冲突、启动导入失败、处理器信息截断和数据库清理/备份提示问题。",
        "• 【修复】修复 RackVision 在 PostgreSQL 下的读模型、机柜索引和设备位置一致性问题。",
        "• 【修复】修复 IP 定位缓存与任务并发、MAC 查询状态、LLDP 来源、Redis 协同和任务失效边界问题。",
        "• 【修复】修复资产导入 SSH 端口、Web SSH 管理入口、系统默认站点提示，以及 H3C/Ruijie/Huawei 平台别名导致的错误命令回退。",
        "• 【修复】修复 AI 检索范围、官方模板映射、对话幂等、敏感信息脱敏和端口安全边界问题。",
        "• 【修复】修复 SNMP 传输、遥测删除、调度器租约、PostgreSQL 时区和跨租户管理员归属问题。",
        "• 【修复】修复配置备份、告警、审计/合规、容量规划、配置差异/漂移和监控空数据页面未携带认证头导致 401 错误提示的问题；未登录时不再发起受保护请求。",
        "• 【加固】增强认证、RBAC、凭据审计、终端安全、Redis/Docker 发布链路和 3D 静态资源加载；外部 AI 与网络写入继续默认关闭。",
    ),
    "en": (
        "• [New] Added a provider-neutral object-storage layer with local and S3-compatible providers; SeaweedFS can be enabled through a Docker profile, while PAM recordings and config snapshots support spooling, retries, status visibility, and legacy migration.",
        "• [New] Added an object-storage status panel to Config Backup Center with provider, health, pending/error/legacy counts, and recent error details for faster operations triage.",
        "• [New] SNMP hostname synchronization now treats physical_assets as the inventory source of truth and projects normalized names to devices and topology observations across manual, batch, background, and discovery flows.",
        "• [New] Docker deployments automatically enable the object-storage profile when STORAGE_BACKEND=s3; npm, APT, and deployment progress remain visible for troubleshooting.",
        "• [Hardening] Removed the SQLite PRAGMA compatibility path from the PostgreSQL-only gate; object-storage credentials stay server-side and are never exposed to the frontend.",
        "• [New] Raised the Windows release baseline to PostgreSQL 18.6 with matching pgvector 0.8.6, plus readiness checks for the database, extensions, and runtimes.",
        "• [New] Unified the Windows client and tray under the Nexora brand while keeping NetOps.exe as a compatibility entry point; added database-target visibility, double-entry password confirmation, and clearer launcher-versus-full-package upgrade boundaries.",
        "• [New] Added the RackVision rack workbench with shared 2D/3D layout data, capacity/power/health summaries, port details, and a 3D asset catalog; the 3D view remains read-only to prevent accidental changes.",
        "• [New] Added NSOT collection templates, an operations catalog, job previews, scope/location summaries, template management, and multi-object scheduled-job filtering.",
        "• [New] Added Redis-coordinated IP locator caching, concurrent task leases, dependency generations, retention controls, and LLDP snapshot evidence.",
        "• [New] Expanded AI administration with provider, model and scene routing, prompts, agents, model health, knowledge-base management, and RAG retrieval testing.",
        "• [New] Copilot now supports configuration-scope clarification, structured intent, citation evidence, and network/IP diagnostics; official knowledge templates and evaluation flows were refreshed.",
        "• [New] Added Web SSH, access favorites, batch asset import/management entries, device platform catalogs, and TextFSM template version metadata.",
        "• [New] Enhanced monitoring with device health dimensions, WAN link/egress probes, alert evidence, health trends, and SNMP metric capabilities.",
        "• [Fix] Fixed missing psycopg2 packaging, the Windows Qt ICU DLL collision, launcher import failures, clipped processor information, and database reset/backup guidance.",
        "• [Fix] Hardened the RackVision read model, rack indexes, and device-placement consistency on PostgreSQL.",
        "• [Fix] Stabilized IP locator cache and task concurrency, MAC lookup status, LLDP provenance, Redis coordination, and task-expiration boundaries.",
        "• [Fix] Fixed imported SSH ports, Web SSH entries, system-default-site guidance, and vendor alias handling that could route H3C/Ruijie/Huawei devices to the wrong commands.",
        "• [Fix] Fixed AI retrieval scope, official-template mapping, conversation idempotency, sensitive-data redaction, and port-security boundaries.",
        "• [Fix] Fixed SNMP transport, telemetry cleanup, scheduler leases, PostgreSQL timezone handling, and cross-tenant administrator assignment.",
        "• [Fix] Fixed 401 error noise on empty backup, alert, audit/compliance, capacity, config-diff/drift, and monitoring views by attaching auth headers to protected requests and skipping them while signed out.",
        "• [Hardening] Strengthened authentication, RBAC, credential auditing, terminal security, Redis/Docker release paths, and 3D static-asset delivery; external AI and network writes remain disabled by default.",
    ),
}


def build_release_notes(lang: str) -> tuple[str, str, str]:
    language = "en" if lang == "en" else "zh"
    title = f"Nexora Agent v{CLIENT_VERSION} 更新说明" if language == "zh" else f"What's New in Nexora Agent v{CLIENT_VERSION}"
    intro = (
        f"以下是相对 v{RELEASE_NOTES_BASELINE} 的主要新增、修复与加固："
        if language == "zh"
        else f"Here are the main new features, fixes, and hardening changes since v{RELEASE_NOTES_BASELINE}:"
    )
    confirm_text = "知道了" if language == "zh" else "Got it"
    return title, f"{intro}\n\n" + "\n".join(RELEASE_NOTES[language]), confirm_text
