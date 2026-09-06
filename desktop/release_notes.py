"""Versioned release notes for the Windows desktop client."""

CLIENT_VERSION = "1.0.7"
CLIENT_BUILD = "20260816.0001"

RELEASE_NOTES = {
    "zh": (
        "• Windows 客户端界面与托盘品牌统一为 Nexora，保留 NetOps.exe 作为兼容启动文件名。",
        "• Windows 部署器新增 PostgreSQL 登录、业务库和 pgvector/pg_trgm 就绪检查。",
        "• 明确在线更新与完整 Windows 发布包升级的边界，降低升级不完整风险。",
        "• 全新简洁界面，统一深色、明亮主题与弹窗样式。",
        "• 修复部署器启动导入失败及处理器信息显示不完整。",
        "• 优化数据库清理确认，读取 .env 并展示备份路径。",
        "• 修复配置复制、资产导入 SSH 端口等常用操作。",
        "• 修复厂商、平台和命令集联动，避免华为/H3C 错用 Cisco 命令。",
    ),
    "en": (
        "• Unified the Windows client and tray branding under Nexora while keeping NetOps.exe as the compatibility launcher name.",
        "• Added PostgreSQL login, database, and pgvector/pg_trgm readiness checks to the Windows setup wizard.",
        "• Clarified the difference between launcher updates and full Windows package upgrades.",
        "• Refreshed the interface with consistent dark, light, and dialog styles.",
        "• Fixed launcher import failures and clipped processor information.",
        "• Improved database reset confirmation, .env loading, and backup visibility.",
        "• Fixed configuration copy and imported SSH port handling.",
        "• Fixed vendor-platform command dispatch for Huawei, H3C, and Cisco devices.",
    ),
}


def build_release_notes(lang: str) -> tuple[str, str, str]:
    language = "en" if lang == "en" else "zh"
    title = f"Nexora Agent v{CLIENT_VERSION} 更新说明" if language == "zh" else f"What's New in Nexora Agent v{CLIENT_VERSION}"
    intro = "本次更新已完成，主要改进如下：" if language == "zh" else "This update includes:"
    confirm_text = "知道了" if language == "zh" else "Got it"
    return title, f"{intro}\n\n" + "\n".join(RELEASE_NOTES[language]), confirm_text
