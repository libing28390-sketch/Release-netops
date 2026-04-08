"""
NetPilot POC 测试脚本
使用 Playwright 自动化浏览器，对所有核心功能模块进行截图取证。
截图保存到 tests/poc_screenshots/
"""
import os
import time
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8003"
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "poc_screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

USERNAME = "admin"
PASSWORD = "Libing123456."

# 测试用例计数
_case_num = 0


def case_id():
    global _case_num
    _case_num += 1
    return f"{_case_num:02d}"


def screenshot(page, name, full_page=True):
    """截图并返回文件路径"""
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    page.screenshot(path=path, full_page=full_page)
    print(f"  [截图] {name}.png")
    return path


def wait_stable(page, timeout=3000):
    """等待页面稳定"""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    page.wait_for_timeout(800)


def spa_navigate(page, path):
    """SPA 内部导航，不触发整页刷新"""
    page.evaluate(f"window.history.pushState({{}}, '', '{path}')")
    page.evaluate("window.dispatchEvent(new PopStateEvent('popstate'))")
    page.wait_for_timeout(2000)
    wait_stable(page)


# ── TC-01: 登录页面 & 登录流程 ──────────────────────────────
def test_login(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 登录页面展示与登录流程")

    # 清除 token 强制显示登录页
    page.goto(BASE_URL)
    page.evaluate("localStorage.removeItem('netops_token')")
    page.reload()
    page.wait_for_timeout(4000)
    wait_stable(page)
    screenshot(page, f"TC{cid}_01_login_page")

    # 实际 DOM 中 input 没有 id/name，按类型定位
    username_input = page.locator("input[type='text']").first
    password_input = page.locator("input[type='password']").first
    username_input.wait_for(state="visible", timeout=10000)

    # 输入错误密码 → 验证错误提示
    username_input.fill(USERNAME)
    password_input.fill("wrongpassword")
    # 查找 Login 按钮
    page.locator("button:has-text('Login'), button:has-text('登录')").first.click()
    page.wait_for_timeout(2000)
    screenshot(page, f"TC{cid}_02_login_error")

    # 输入正确密码 → 登录成功
    password_input.fill("")
    password_input.fill(PASSWORD)
    page.locator("button:has-text('Login'), button:has-text('登录')").first.click()
    page.wait_for_timeout(5000)
    wait_stable(page)
    screenshot(page, f"TC{cid}_03_login_success_dashboard")
    print(f"  当前URL: {page.url}")


# ── TC-02: 仪表盘 ────────────────────────────────────────
def test_dashboard(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 仪表盘概览")

    page.goto(f"{BASE_URL}/dashboard")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_dashboard_overview")

    # 滚动到底部看完整内容
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(500)
    screenshot(page, f"TC{cid}_02_dashboard_bottom")


# ── TC-03: 监控中心 ──────────────────────────────────────
def test_monitoring(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 监控中心")

    page.goto(f"{BASE_URL}/monitoring")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_monitoring_center")


# ── TC-04: 网络拓扑 ──────────────────────────────────────
def test_topology(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 网络拓扑")

    page.goto(f"{BASE_URL}/topology")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_topology_page")


# ── TC-05: 告警中心 ──────────────────────────────────────
def test_alerts(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 告警中心")

    page.goto(f"{BASE_URL}/alerts")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_alert_desk")

    # 尝试按严重度筛选
    try:
        # 查找筛选按钮/下拉
        filters = page.locator("select, [role='combobox'], button:has-text('筛选'), button:has-text('过滤'), button:has-text('Filter')")
        if filters.count() > 0:
            filters.first.click()
            page.wait_for_timeout(500)
            screenshot(page, f"TC{cid}_02_alert_filter")
    except Exception:
        pass


# ── TC-06: 历史告警 ──────────────────────────────────────
def test_alert_history(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 历史告警")

    page.goto(f"{BASE_URL}/alert-history")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_alert_history")


# ── TC-07: 告警规则 ──────────────────────────────────────
def test_alert_rules(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 告警规则")

    page.goto(f"{BASE_URL}/alert-rules")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_alert_rules")


# ── TC-08: 维护窗口 ──────────────────────────────────────
def test_maintenance(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 维护窗口")

    page.goto(f"{BASE_URL}/maintenance")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_maintenance")


# ── TC-09: 资产管理 ──────────────────────────────────────
def test_assets(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 资产管理")

    page.goto(f"{BASE_URL}/assets")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_assets")


# ── TC-10: 网络设备清单 ──────────────────────────────────
def test_devices(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 网络设备清单")

    page.goto(f"{BASE_URL}/inventory/devices")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_devices_list")

    # 搜索设备
    search_input = page.locator("input[type='text'], input[type='search'], input[placeholder*='搜索'], input[placeholder*='search'], input[placeholder*='Search']").first
    if search_input.is_visible():
        search_input.fill("SW-BJ")
        page.wait_for_timeout(1500)
        screenshot(page, f"TC{cid}_02_devices_search")
        search_input.fill("")

    # 点击设备查看详情
    try:
        first_row = page.locator("table tbody tr, [role='row']").first
        if first_row.is_visible():
            first_row.click()
            page.wait_for_timeout(1500)
            screenshot(page, f"TC{cid}_03_device_detail")
    except Exception:
        pass


# ── TC-11: 服务器清单 ────────────────────────────────────
def test_servers(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 服务器清单")

    page.goto(f"{BASE_URL}/inventory/servers")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_servers_list")


# ── TC-12: IP/VLAN 管理 ──────────────────────────────────
def test_ipam(page):
    cid = case_id()
    print(f"\n[TC-{cid}] IP/VLAN管理")

    page.goto(f"{BASE_URL}/ipam")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_ipam")


# ── TC-13: IP 工具箱 ─────────────────────────────────────
def test_ip_locator(page):
    cid = case_id()
    print(f"\n[TC-{cid}] IP工具箱")

    page.goto(f"{BASE_URL}/ip-locator")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_ip_locator")


# ── TC-14: 配置备份中心 ──────────────────────────────────
def test_config_backup(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 配置备份中心")

    page.goto(f"{BASE_URL}/config/backup")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_config_backup")


# ── TC-15: 备份计划 ──────────────────────────────────────
def test_config_schedule(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 备份计划")

    page.goto(f"{BASE_URL}/config/schedule")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_config_schedule")


# ── TC-16: 配置对比 ──────────────────────────────────────
def test_config_diff(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 配置对比")

    page.goto(f"{BASE_URL}/config/diff")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_config_diff")


# ── TC-17: 配置搜索 ──────────────────────────────────────
def test_config_search(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 配置搜索")

    page.goto(f"{BASE_URL}/config/search")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_config_search")


# ── TC-18: 自动化任务 ────────────────────────────────────
def test_automation_execute(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 自动化执行")

    page.goto(f"{BASE_URL}/automation/execute")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_automation_execute")


# ── TC-19: 设备巡检 ──────────────────────────────────────
def test_inspection(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 设备巡检")

    page.goto(f"{BASE_URL}/automation/inspection")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_inspection")


# ── TC-20: 执行计划 ──────────────────────────────────────
def test_automation_schedule(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 执行计划")

    page.goto(f"{BASE_URL}/automation/schedule")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_automation_schedule")


# ── TC-21: 变更工单 ──────────────────────────────────────
def test_change_orders(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 变更工单")

    page.goto(f"{BASE_URL}/change-orders")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_change_orders")


# ── TC-22: 合规检查 ──────────────────────────────────────
def test_compliance(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 合规检查")

    page.goto(f"{BASE_URL}/compliance")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_compliance")

    # 滚动查看更多
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(500)
    screenshot(page, f"TC{cid}_02_compliance_bottom")


# ── TC-23: 容量分析 ──────────────────────────────────────
def test_capacity(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 容量分析")

    page.goto(f"{BASE_URL}/capacity")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_capacity")


# ── TC-24: 报表中心 ──────────────────────────────────────
def test_reports(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 报表中心")

    page.goto(f"{BASE_URL}/reports")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_reports")


# ── TC-25: 审计日志 ──────────────────────────────────────
def test_audit(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 审计日志")

    page.goto(f"{BASE_URL}/history")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_audit_logs")


# ── TC-26: 平台设置 ──────────────────────────────────────
def test_platform_settings(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 平台设置")

    page.goto(f"{BASE_URL}/configuration")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_platform_settings")


# ── TC-27: 用户管理 ──────────────────────────────────────
def test_users(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 用户管理")

    page.goto(f"{BASE_URL}/users")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_users")


# ── TC-28: 设备健康 ──────────────────────────────────────
def test_device_health(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 设备健康")

    page.goto(f"{BASE_URL}/health")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_device_health")


# ── TC-29: 配置漂移 ──────────────────────────────────────
def test_config_drift(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 配置漂移")

    page.goto(f"{BASE_URL}/config/drift")
    wait_stable(page, 5000)
    screenshot(page, f"TC{cid}_01_config_drift")


# ── TC-30: 侧边栏展开/收缩 + 响应式 ─────────────────────
def test_sidebar_responsive(page):
    cid = case_id()
    print(f"\n[TC-{cid}] 侧边栏与响应式测试")

    page.goto(f"{BASE_URL}/dashboard")
    wait_stable(page)

    # 桌面宽度
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.wait_for_timeout(500)
    screenshot(page, f"TC{cid}_01_desktop_1920")

    # 平板宽度
    page.set_viewport_size({"width": 768, "height": 1024})
    page.wait_for_timeout(500)
    screenshot(page, f"TC{cid}_02_tablet_768")

    # 手机宽度
    page.set_viewport_size({"width": 375, "height": 812})
    page.wait_for_timeout(500)
    screenshot(page, f"TC{cid}_03_mobile_375")

    # 恢复
    page.set_viewport_size({"width": 1920, "height": 1080})


# ── TC-31: API 性能验证 ──────────────────────────────────
def test_api_performance(page):
    cid = case_id()
    print(f"\n[TC-{cid}] API 响应时间验证 (通过 DevTools)")

    page.goto(f"{BASE_URL}/inventory/devices")
    wait_stable(page, 5000)

    # 使用 Performance API 测量页面加载
    perf = page.evaluate("""() => {
        const entries = performance.getEntriesByType('navigation');
        const nav = entries[0] || {};
        const resources = performance.getEntriesByType('resource')
            .filter(r => r.name.includes('/api/'))
            .map(r => ({
                name: r.name.split('/api/')[1] || r.name,
                duration: Math.round(r.duration),
                size: r.transferSize || 0,
            }))
            .sort((a, b) => b.duration - a.duration)
            .slice(0, 10);
        return {
            pageLoad: Math.round(nav.loadEventEnd - nav.startTime),
            domReady: Math.round(nav.domContentLoadedEventEnd - nav.startTime),
            apiCalls: resources,
        };
    }""")
    print(f"  页面加载时间: {perf.get('pageLoad', '?')}ms")
    print(f"  DOM Ready: {perf.get('domReady', '?')}ms")
    print(f"  API调用 (Top 10 by duration):")
    for api in perf.get('apiCalls', []):
        print(f"    {api['name']:<50} {api['duration']}ms  {api['size']}B")


def main():
    print("=" * 70)
    print("  NetPilot POC 自动化测试")
    print(f"  目标: {BASE_URL}")
    print(f"  截图目录: {SCREENSHOT_DIR}")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        page = context.new_page()

        tests = [
            test_login,
            test_dashboard,
            test_monitoring,
            test_topology,
            test_alerts,
            test_alert_history,
            test_alert_rules,
            test_maintenance,
            test_assets,
            test_devices,
            test_servers,
            test_ipam,
            test_ip_locator,
            test_config_backup,
            test_config_schedule,
            test_config_diff,
            test_config_search,
            test_automation_execute,
            test_inspection,
            test_automation_schedule,
            test_change_orders,
            test_compliance,
            test_capacity,
            test_reports,
            test_audit,
            test_platform_settings,
            test_users,
            test_device_health,
            test_config_drift,
            test_sidebar_responsive,
            test_api_performance,
        ]

        passed = 0
        failed = 0
        results = []
        for test_fn in tests:
            name = test_fn.__name__
            try:
                test_fn(page)
                passed += 1
                results.append((name, "PASS", ""))
            except Exception as e:
                failed += 1
                err = str(e)[:120]
                print(f"  [FAIL] {name}: {err}")
                results.append((name, "FAIL", err))
                # 截取失败现场
                try:
                    screenshot(page, f"FAIL_{name}")
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
            line += f" — {err}"
        print(line)
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
