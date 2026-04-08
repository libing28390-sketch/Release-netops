"""
NetPilot POC 测试脚本 v2
使用 Playwright 自动化浏览器，对所有核心功能模块进行截图取证。
关键改进：登录后通过侧边栏按钮点击 + React Router popstate 导航。
截图保存到 tests/poc_screenshots/
"""
import os
from playwright.sync_api import sync_playwright, Page

BASE_URL = "http://127.0.0.1:8003"
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "poc_screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

USERNAME = "admin"
PASSWORD = "Libing123456."

_case_num = 0


def case_id():
    global _case_num
    _case_num += 1
    return f"{_case_num:02d}"


def shot(page: Page, name: str, full_page: bool = True):
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    page.screenshot(path=path, full_page=full_page)
    print(f"  [截图] {name}.png")


def settle(page: Page, ms: int = 3000):
    """等待网络空闲 + 额外延迟"""
    try:
        page.wait_for_load_state("networkidle", timeout=ms)
    except Exception:
        pass
    page.wait_for_timeout(1000)


def nav(page: Page, path: str):
    """SPA 客户端导航：通过 BrowserRouter popstate 触发路由切换"""
    page.evaluate(f"""(() => {{
        window.history.pushState({{}}, '', '{path}');
        window.dispatchEvent(new PopStateEvent('popstate'));
    }})()""")
    page.wait_for_timeout(2500)
    settle(page)


def click_nav(page: Page, label: str, fallback_path: str = ""):
    """点击侧边栏菜单按钮，找不到时回退到 JS 路由导航"""
    try:
        btn = page.locator("aside[role='navigation'] button").filter(has_text=label).first
        btn.click(timeout=3000)
        page.wait_for_timeout(2000)
        settle(page)
    except Exception:
        if fallback_path:
            print(f"  [回退] 侧边栏 '{label}' 不可见，使用 JS 导航 → {fallback_path}")
            nav(page, fallback_path)
        else:
            raise


# ─────────────────────────────────────────────────────────
# TC-01: 登录
# ─────────────────────────────────────────────────────────
def tc_login(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 登录页面展示与登录流程")

    page.goto(BASE_URL)
    page.evaluate("localStorage.removeItem('netops_token')")
    page.reload()
    page.wait_for_timeout(4000)
    settle(page)
    shot(page, f"TC{cid}_01_login_page")

    # 定位输入框（DOM 中无 id/name 属性）
    username_input = page.locator("input[type='text']").first
    password_input = page.locator("input[type='password']").first
    username_input.wait_for(state="visible", timeout=10000)

    # 错误密码测试
    username_input.fill(USERNAME)
    password_input.fill("wrongpassword")
    page.locator("button:has-text('Login'), button:has-text('登录')").first.click()
    page.wait_for_timeout(2000)
    shot(page, f"TC{cid}_02_login_error")

    # 正确密码登录
    password_input.fill("")
    password_input.fill(PASSWORD)
    page.locator("button:has-text('Login'), button:has-text('登录')").first.click()
    page.wait_for_timeout(5000)
    settle(page)
    shot(page, f"TC{cid}_03_login_success_dashboard")
    print(f"  当前URL: {page.url}")


# ─────────────────────────────────────────────────────────
# TC-02: 仪表盘
# ─────────────────────────────────────────────────────────
def tc_dashboard(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 仪表盘概览")
    click_nav(page, "Dashboard", "/dashboard")
    shot(page, f"TC{cid}_01_dashboard_overview")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(500)
    shot(page, f"TC{cid}_02_dashboard_bottom")


# ─────────────────────────────────────────────────────────
# TC-03: 监控中心
# ─────────────────────────────────────────────────────────
def tc_monitoring(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 监控中心")
    click_nav(page, "Monitoring", "/monitoring")
    shot(page, f"TC{cid}_01_monitoring_center")


# ─────────────────────────────────────────────────────────
# TC-04: 网络拓扑
# ─────────────────────────────────────────────────────────
def tc_topology(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 网络拓扑")
    click_nav(page, "Topology", "/topology")
    shot(page, f"TC{cid}_01_topology_page")


# ─────────────────────────────────────────────────────────
# TC-05: 告警中心
# ─────────────────────────────────────────────────────────
def tc_alerts(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 告警中心")
    click_nav(page, "Alert Center", "/alerts")
    shot(page, f"TC{cid}_01_alert_desk")


# ─────────────────────────────────────────────────────────
# TC-06: 历史告警
# ─────────────────────────────────────────────────────────
def tc_alert_history(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 历史告警")
    click_nav(page, "Alert History", "/alert-history")
    shot(page, f"TC{cid}_01_alert_history")


# ─────────────────────────────────────────────────────────
# TC-07: 告警规则
# ─────────────────────────────────────────────────────────
def tc_alert_rules(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 告警规则")
    click_nav(page, "Alert Rules", "/alert-rules")
    shot(page, f"TC{cid}_01_alert_rules")


# ─────────────────────────────────────────────────────────
# TC-08: 维护窗口
# ─────────────────────────────────────────────────────────
def tc_maintenance(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 维护窗口")
    click_nav(page, "Maintenance", "/maintenance")
    shot(page, f"TC{cid}_01_maintenance")


# ─────────────────────────────────────────────────────────
# TC-09: 资产管理
# ─────────────────────────────────────────────────────────
def tc_assets(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 资产管理")
    click_nav(page, "Assets", "/assets")
    shot(page, f"TC{cid}_01_assets")


# ─────────────────────────────────────────────────────────
# TC-10: 网络设备清单
# ─────────────────────────────────────────────────────────
def tc_devices(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 网络设备清单")
    click_nav(page, "Device List", "/inventory/devices")
    shot(page, f"TC{cid}_01_devices_list")

    # 搜索功能
    try:
        search = page.locator("input[placeholder*='搜索'], input[placeholder*='Search'], input[placeholder*='search']").first
        if search.is_visible(timeout=2000):
            search.fill("SW-BJ")
            page.wait_for_timeout(1500)
            shot(page, f"TC{cid}_02_devices_search")
            search.fill("")
    except Exception:
        pass

    # 点击第一行查看详情
    try:
        row = page.locator("table tbody tr").first
        if row.is_visible(timeout=2000):
            row.click()
            page.wait_for_timeout(2000)
            shot(page, f"TC{cid}_03_device_detail")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
# TC-11: 服务器清单
# ─────────────────────────────────────────────────────────
def tc_servers(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 服务器清单")
    click_nav(page, "Servers", "/inventory/servers")
    shot(page, f"TC{cid}_01_servers_list")


# ─────────────────────────────────────────────────────────
# TC-12: IP/VLAN 管理
# ─────────────────────────────────────────────────────────
def tc_ipam(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] IP/VLAN管理")
    click_nav(page, "IP/VLAN Mgmt", "/ipam")
    shot(page, f"TC{cid}_01_ipam")


# ─────────────────────────────────────────────────────────
# TC-13: IP 工具箱
# ─────────────────────────────────────────────────────────
def tc_ip_locator(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] IP工具箱")
    click_nav(page, "IP Toolbox", "/ip-locator")
    shot(page, f"TC{cid}_01_ip_locator")


# ─────────────────────────────────────────────────────────
# TC-14: 配置备份中心
# ─────────────────────────────────────────────────────────
def tc_config_backup(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 配置备份中心")
    click_nav(page, "Backup Center", "/config/backup")
    shot(page, f"TC{cid}_01_config_backup")


# ─────────────────────────────────────────────────────────
# TC-15: 备份计划
# ─────────────────────────────────────────────────────────
def tc_config_schedule(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 备份计划")
    click_nav(page, "Backup Schedule", "/config/schedule")
    shot(page, f"TC{cid}_01_config_schedule")


# ─────────────────────────────────────────────────────────
# TC-16: 配置对比
# ─────────────────────────────────────────────────────────
def tc_config_diff(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 配置对比")
    click_nav(page, "Config Diff", "/config/diff")
    shot(page, f"TC{cid}_01_config_diff")


# ─────────────────────────────────────────────────────────
# TC-17: 配置搜索
# ─────────────────────────────────────────────────────────
def tc_config_search(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 配置搜索")
    click_nav(page, "Config Search", "/config/search")
    shot(page, f"TC{cid}_01_config_search")


# ─────────────────────────────────────────────────────────
# TC-18: 自动化任务
# ─────────────────────────────────────────────────────────
def tc_automation(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 自动化执行")
    click_nav(page, "Automation", "/automation/execute")
    shot(page, f"TC{cid}_01_automation_execute")


# ─────────────────────────────────────────────────────────
# TC-19: 设备巡检
# ─────────────────────────────────────────────────────────
def tc_inspection(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 设备巡检")
    click_nav(page, "Device Inspection", "/automation/inspection")
    shot(page, f"TC{cid}_01_inspection")


# ─────────────────────────────────────────────────────────
# TC-20: 执行计划
# ─────────────────────────────────────────────────────────
def tc_scheduled_tasks(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 执行计划")
    click_nav(page, "Scheduled Tasks", "/automation/schedule")
    shot(page, f"TC{cid}_01_scheduled_tasks")


# ─────────────────────────────────────────────────────────
# TC-21: 变更工单
# ─────────────────────────────────────────────────────────
def tc_change_orders(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 变更工单")
    click_nav(page, "Change Orders", "/change-orders")
    shot(page, f"TC{cid}_01_change_orders")


# ─────────────────────────────────────────────────────────
# TC-22: 合规检查  (不在侧边栏，用 JS 路由导航)
# ─────────────────────────────────────────────────────────
def tc_compliance(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 合规检查")
    nav(page, "/compliance")
    shot(page, f"TC{cid}_01_compliance")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(500)
    shot(page, f"TC{cid}_02_compliance_bottom")


# ─────────────────────────────────────────────────────────
# TC-23: 容量分析
# ─────────────────────────────────────────────────────────
def tc_capacity(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 容量分析")
    click_nav(page, "Capacity", "/capacity")
    shot(page, f"TC{cid}_01_capacity")


# ─────────────────────────────────────────────────────────
# TC-24: 报表中心
# ─────────────────────────────────────────────────────────
def tc_reports(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 报表中心")
    click_nav(page, "Reports", "/reports")
    shot(page, f"TC{cid}_01_reports")


# ─────────────────────────────────────────────────────────
# TC-25: 审计日志
# ─────────────────────────────────────────────────────────
def tc_audit(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 审计日志")
    click_nav(page, "Audit Logs", "/history")
    shot(page, f"TC{cid}_01_audit_logs")


# ─────────────────────────────────────────────────────────
# TC-26: 平台设置
# ─────────────────────────────────────────────────────────
def tc_platform_settings(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 平台设置")
    click_nav(page, "Settings", "/configuration")
    shot(page, f"TC{cid}_01_platform_settings")


# ─────────────────────────────────────────────────────────
# TC-27: 用户管理
# ─────────────────────────────────────────────────────────
def tc_users(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 用户管理")
    click_nav(page, "Users", "/users")
    shot(page, f"TC{cid}_01_users")


# ─────────────────────────────────────────────────────────
# TC-28: 设备健康  (不在侧边栏，用 JS 路由导航)
# ─────────────────────────────────────────────────────────
def tc_device_health(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 设备健康")
    click_nav(page, "Health Detection", "/health")
    shot(page, f"TC{cid}_01_device_health")


# ─────────────────────────────────────────────────────────
# TC-29: 配置漂移  (不在侧边栏，用 JS 路由导航)
# ─────────────────────────────────────────────────────────
def tc_config_drift(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 配置漂移")
    nav(page, "/config/drift")
    shot(page, f"TC{cid}_01_config_drift")


# ─────────────────────────────────────────────────────────
# TC-30: 响应式布局
# ─────────────────────────────────────────────────────────
def tc_responsive(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 响应式布局测试")
    click_nav(page, "Dashboard", "/dashboard")

    page.set_viewport_size({"width": 1920, "height": 1080})
    page.wait_for_timeout(500)
    shot(page, f"TC{cid}_01_desktop_1920")

    page.set_viewport_size({"width": 768, "height": 1024})
    page.wait_for_timeout(500)
    shot(page, f"TC{cid}_02_tablet_768")

    page.set_viewport_size({"width": 375, "height": 812})
    page.wait_for_timeout(500)
    shot(page, f"TC{cid}_03_mobile_375")

    page.set_viewport_size({"width": 1920, "height": 1080})


# ─────────────────────────────────────────────────────────
# TC-31: API 性能
# ─────────────────────────────────────────────────────────
def tc_api_perf(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] API 响应时间验证")

    page.evaluate("performance.clearResourceTimings()")
    click_nav(page, "Device List", "/inventory/devices")
    page.wait_for_timeout(3000)

    perf = page.evaluate("""() => {
        const resources = performance.getEntriesByType('resource')
            .filter(r => r.name.includes('/api/'))
            .map(r => ({
                name: r.name.split('/api/')[1] || r.name,
                duration: Math.round(r.duration),
                size: r.transferSize || 0,
            }))
            .sort((a, b) => b.duration - a.duration)
            .slice(0, 15);
        return { apiCalls: resources };
    }""")
    print(f"  API调用 (Top 15 by duration):")
    for api in perf.get('apiCalls', []):
        print(f"    {api['name']:<50} {api['duration']}ms  {api['size']}B")


def main():
    print("=" * 70)
    print("  NetPilot POC 自动化测试 v2")
    print(f"  目标: {BASE_URL}")
    print(f"  截图目录: {SCREENSHOT_DIR}")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        page = ctx.new_page()

        tests = [
            tc_login,            # TC-01
            tc_dashboard,        # TC-02
            tc_monitoring,       # TC-03
            tc_topology,         # TC-04
            tc_alerts,           # TC-05
            tc_alert_history,    # TC-06
            tc_alert_rules,      # TC-07
            tc_maintenance,      # TC-08
            tc_assets,           # TC-09
            tc_devices,          # TC-10
            tc_servers,          # TC-11
            tc_ipam,             # TC-12
            tc_ip_locator,       # TC-13
            tc_config_backup,    # TC-14
            tc_config_schedule,  # TC-15
            tc_config_diff,      # TC-16
            tc_config_search,    # TC-17
            tc_automation,       # TC-18
            tc_inspection,       # TC-19
            tc_scheduled_tasks,  # TC-20
            tc_change_orders,    # TC-21
            tc_compliance,       # TC-22
            tc_capacity,         # TC-23
            tc_reports,          # TC-24
            tc_audit,            # TC-25
            tc_platform_settings,# TC-26
            tc_users,            # TC-27
            tc_device_health,    # TC-28
            tc_config_drift,     # TC-29
            tc_responsive,       # TC-30
            tc_api_perf,         # TC-31
        ]

        passed = 0
        failed = 0
        results = []
        for fn in tests:
            name = fn.__name__
            try:
                fn(page)
                passed += 1
                results.append((name, "PASS", ""))
            except Exception as e:
                failed += 1
                err = str(e)[:150]
                print(f"  [FAIL] {name}: {err}")
                results.append((name, "FAIL", err))
                try:
                    shot(page, f"FAIL_{name}")
                except Exception:
                    pass

        browser.close()

    print(f"\n\n{'=' * 70}")
    print(f"  测试汇总: {passed} PASS / {failed} FAIL / {passed + failed} TOTAL")
    print(f"{'=' * 70}")
    for name, status, err in results:
        mark = "✓" if status == "PASS" else "✗"
        line = f"  {mark} {name}"
        if err:
            line += f" — {err[:80]}"
        print(line)
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
