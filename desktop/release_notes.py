"""Versioned release notes for the Windows desktop client."""

CLIENT_VERSION = "1.0.2"
CLIENT_BUILD = "20260713.1721"

RELEASE_NOTES = {
    "zh": (
        "• 全新简洁界面，统一深色、明亮主题与弹窗样式。",
        "• 修复部署器启动导入失败及处理器信息显示不完整。",
        "• 优化数据库清理确认，读取 .env 并展示备份路径。",
        "• 修复配置复制、资产导入 SSH 端口等常用操作。",
        "• 修复厂商、平台和命令集联动，避免华为/H3C 错用 Cisco 命令。",
    ),
    "en": (
        "• Refreshed the interface with consistent dark, light, and dialog styles.",
        "• Fixed launcher import failures and clipped processor information.",
        "• Improved database reset confirmation, .env loading, and backup visibility.",
        "• Fixed configuration copy and imported SSH port handling.",
        "• Fixed vendor-platform command dispatch for Huawei, H3C, and Cisco devices.",
    ),
}


def build_release_notes(lang: str) -> tuple[str, str, str]:
    language = "en" if lang == "en" else "zh"
    title = f"NetOps Agent v{CLIENT_VERSION} 更新说明" if language == "zh" else f"What's New in NetOps Agent v{CLIENT_VERSION}"
    intro = "本次更新已完成，主要改进如下：" if language == "zh" else "This update includes:"
    confirm_text = "知道了" if language == "zh" else "Got it"
    return title, f"{intro}\n\n" + "\n".join(RELEASE_NOTES[language]), confirm_text
