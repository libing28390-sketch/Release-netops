"""
NetPilot POC 详细测试脚本 v3
特别强化：自动化操作、告警处置、合规审计、变更工单、设备巡检等关键业务流程的交互截图。
每个测试用例包含完整的操作步骤与多张截图。
"""
import os
from playwright.sync_api import sync_playwright, Page, expect

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
    print(f"    [截图] {name}.png")


def settle(page: Page, ms: int = 3000):
    try:
        page.wait_for_load_state("networkidle", timeout=ms)
    except Exception:
        pass
    page.wait_for_timeout(1000)


def nav(page: Page, path: str):
    """SPA 客户端路由导航"""
    page.evaluate(f"""(() => {{
        window.history.pushState({{}}, '', '{path}');
        window.dispatchEvent(new PopStateEvent('popstate'));
    }})()""")
    page.wait_for_timeout(2500)
    settle(page)


def click_nav(page: Page, label: str, fallback_path: str = ""):
    """点击侧边栏菜单，找不到回退 JS 路由"""
    try:
        btn = page.locator("aside[role='navigation'] button").filter(has_text=label).first
        btn.click(timeout=3000)
        page.wait_for_timeout(2000)
        settle(page)
    except Exception:
        if fallback_path:
            nav(page, fallback_path)
        else:
            raise


# ═══════════════════════════════════════════════════════════
# TC-01: 登录流程
# ═══════════════════════════════════════════════════════════
def tc_login(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 登录流程（3步）")

    # 步骤 1: 访问首页 → 展示登录页
    print(f"  步骤1: 访问首页，展示登录界面")
    page.goto(BASE_URL)
    page.evaluate("localStorage.removeItem('netops_token')")
    page.reload()
    page.wait_for_timeout(4000)
    settle(page)
    shot(page, f"TC{cid}_01_login_page")

    username_input = page.locator("input[type='text']").first
    password_input = page.locator("input[type='password']").first
    username_input.wait_for(state="visible", timeout=10000)

    # 步骤 2: 输入错误密码 → 提示错误
    print(f"  步骤2: 输入错误密码，验证错误提示")
    username_input.fill(USERNAME)
    password_input.fill("wrongpassword")
    page.locator("button:has-text('Login'), button:has-text('登录')").first.click()
    page.wait_for_timeout(2000)
    shot(page, f"TC{cid}_02_login_error")

    # 步骤 3: 输入正确密码 → 跳转 Dashboard
    print(f"  步骤3: 输入正确密码，登录成功跳转 Dashboard")
    password_input.fill("")
    password_input.fill(PASSWORD)
    page.locator("button:has-text('Login'), button:has-text('登录')").first.click()
    page.wait_for_timeout(5000)
    settle(page)
    shot(page, f"TC{cid}_03_login_success")
    print(f"    当前URL: {page.url}")


# ═══════════════════════════════════════════════════════════
# TC-02: 仪表盘
# ═══════════════════════════════════════════════════════════
def tc_dashboard(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 仪表盘概览")

    click_nav(page, "Dashboard", "/dashboard")
    print(f"  步骤1: 查看仪表盘顶部 KPI 卡片与主机资源")
    shot(page, f"TC{cid}_01_dashboard_top")

    print(f"  步骤2: 滚动查看合规趋势图与平台分布饼图")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(600)
    shot(page, f"TC{cid}_02_dashboard_bottom")


# ═══════════════════════════════════════════════════════════
# TC-03: 监控中心
# ═══════════════════════════════════════════════════════════
def tc_monitoring(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 监控中心")

    click_nav(page, "Monitoring", "/monitoring")
    print(f"  步骤1: 查看监控面板")
    shot(page, f"TC{cid}_01_monitoring")


# ═══════════════════════════════════════════════════════════
# TC-04: 网络拓扑
# ═══════════════════════════════════════════════════════════
def tc_topology(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 网络拓扑")

    click_nav(page, "Topology", "/topology")
    print(f"  步骤1: 查看拓扑可视化画布")
    shot(page, f"TC{cid}_01_topology")


# ═══════════════════════════════════════════════════════════
# TC-05: 告警中心 — 完整操作流程
# ═══════════════════════════════════════════════════════════
def tc_alerts(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 告警中心 — 完整操作流程")

    click_nav(page, "Alert Center", "/alerts")
    print(f"  步骤1: 查看告警列表（Open 标签）")
    shot(page, f"TC{cid}_01_alert_list_open")

    # 步骤 2: 点击第一条告警 查看 按钮查看详情
    print(f"  步骤2: 点击第一条告警的「查看」按钮查看详情")
    try:
        view_btn = page.locator("button:has-text('查看'), button:has-text('View')").first
        view_btn.click(timeout=3000)
        page.wait_for_timeout(2000)
        shot(page, f"TC{cid}_02_alert_detail_panel")
    except Exception:
        print(f"    [跳过] 查看按钮未找到")

    # 步骤 3: 确认告警
    print(f"  步骤3: 点击「确认告警」按钮")
    try:
        ack_btn = page.locator("button:has-text('确认告警'), button:has-text('Acknowledge')").first
        if ack_btn.is_visible(timeout=3000):
            ack_btn.click()
            page.wait_for_timeout(2000)
            shot(page, f"TC{cid}_03_alert_acknowledged")
    except Exception:
        print(f"    [跳过] 确认告警按钮未找到")

    # 步骤 4: 切换到已确认标签
    print(f"  步骤4: 切换到「已确认」标签查看已确认告警")
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    try:
        acked_tab = page.locator("button:has-text('已确认'), button:has-text('Acknowledged')").first
        if acked_tab.is_visible(timeout=2000):
            acked_tab.click()
            page.wait_for_timeout(1500)
            shot(page, f"TC{cid}_04_alert_acknowledged_tab")
    except Exception:
        print(f"    [跳过] 已确认标签未找到")

    # 步骤 5: 切回待处理标签
    print(f"  步骤5: 切回「待处理」标签查看")
    try:
        open_tab = page.locator("button:has-text('待处理'), button:has-text('Open')").first
        open_tab.click(timeout=2000)
        page.wait_for_timeout(1500)
        shot(page, f"TC{cid}_05_alert_open_tab")
    except Exception:
        print(f"    [跳过] 待处理标签切换失败")


# ═══════════════════════════════════════════════════════════
# TC-06: 历史告警
# ═══════════════════════════════════════════════════════════
def tc_alert_history(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 历史告警")

    click_nav(page, "Alert History", "/alert-history")
    print(f"  步骤1: 查看历史告警记录")
    shot(page, f"TC{cid}_01_alert_history")


# ═══════════════════════════════════════════════════════════
# TC-07: 告警规则
# ═══════════════════════════════════════════════════════════
def tc_alert_rules(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 告警规则")

    click_nav(page, "Alert Rules", "/alert-rules")
    print(f"  步骤1: 查看告警规则列表")
    shot(page, f"TC{cid}_01_alert_rules")


# ═══════════════════════════════════════════════════════════
# TC-08: 维护窗口
# ═══════════════════════════════════════════════════════════
def tc_maintenance(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 维护窗口")

    click_nav(page, "Maintenance", "/maintenance")
    print(f"  步骤1: 查看维护期列表")
    shot(page, f"TC{cid}_01_maintenance")


# ═══════════════════════════════════════════════════════════
# TC-09: 资产管理
# ═══════════════════════════════════════════════════════════
def tc_assets(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 资产管理")

    click_nav(page, "Assets", "/assets")
    print(f"  步骤1: 查看资产概览")
    shot(page, f"TC{cid}_01_assets")


# ═══════════════════════════════════════════════════════════
# TC-10: 网络设备清单 — 详细操作
# ═══════════════════════════════════════════════════════════
def tc_devices(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 网络设备清单 — 详细操作")

    click_nav(page, "Device List", "/inventory/devices")
    print(f"  步骤1: 查看设备列表（503台设备）")
    shot(page, f"TC{cid}_01_devices_list")

    # 步骤 2: 搜索设备
    print(f"  步骤2: 搜索设备 'SW-BJ'")
    try:
        search = page.locator("input[placeholder*='Search'], input[placeholder*='搜索']").first
        if search.is_visible(timeout=2000):
            search.fill("SW-BJ")
            page.wait_for_timeout(1500)
            shot(page, f"TC{cid}_02_devices_search")
            search.fill("")
            page.wait_for_timeout(1000)
    except Exception:
        pass

    # 步骤 3: 平台筛选
    print(f"  步骤3: 筛选平台 — 点击 All Platforms 下拉")
    try:
        platform_select = page.locator("select, button:has-text('All Platforms'), button:has-text('全部厂商')").first
        if platform_select.is_visible(timeout=2000):
            platform_select.click()
            page.wait_for_timeout(800)
            shot(page, f"TC{cid}_03_platform_filter")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
    except Exception:
        pass

    # 步骤 4: 点击设备行 → 弹出详情模态框
    print(f"  步骤4: 点击第一台设备查看详情模态框")
    try:
        # 点击展开箭头或设备名
        expand = page.locator("table tbody tr").first.locator("button, svg").first
        expand.click(timeout=3000)
        page.wait_for_timeout(2500)
        shot(page, f"TC{cid}_04_device_detail_modal")
    except Exception:
        pass

    # 步骤 5: 设备详情 — 查看运行数据 & 连通性测试按钮
    print(f"  步骤5: 查看设备详情底部按钮（连通性测试、SNMP测试等）")
    try:
        page.evaluate("document.querySelector('[class*=modal], [role=dialog]')?.scrollTo(0, 9999)")
        page.wait_for_timeout(800)
        shot(page, f"TC{cid}_05_device_detail_buttons")
    except Exception:
        pass

    # 关闭模态框
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)


# ═══════════════════════════════════════════════════════════
# TC-11: 服务器清单
# ═══════════════════════════════════════════════════════════
def tc_servers(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 服务器清单")

    click_nav(page, "Servers", "/inventory/servers")
    print(f"  步骤1: 查看服务器列表")
    shot(page, f"TC{cid}_01_servers")


# ═══════════════════════════════════════════════════════════
# TC-12: IP/VLAN 管理
# ═══════════════════════════════════════════════════════════
def tc_ipam(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] IP/VLAN 管理")

    click_nav(page, "IP/VLAN Mgmt", "/ipam")
    print(f"  步骤1: 查看 IP 地址管理")
    shot(page, f"TC{cid}_01_ipam")


# ═══════════════════════════════════════════════════════════
# TC-13: IP 工具箱
# ═══════════════════════════════════════════════════════════
def tc_ip_locator(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] IP 工具箱")

    click_nav(page, "IP Toolbox", "/ip-locator")
    print(f"  步骤1: 查看 IP 定位工具")
    shot(page, f"TC{cid}_01_ip_locator")


# ═══════════════════════════════════════════════════════════
# TC-14: 配置备份 — 完整操作流程
# ═══════════════════════════════════════════════════════════
def tc_config_backup(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 配置备份 — 完整操作流程")

    click_nav(page, "Backup Center", "/config/backup")
    print(f"  步骤1: 查看配置备份列表")
    shot(page, f"TC{cid}_01_backup_list")

    # 步骤 2: 点击「备份全部在线设备」
    print(f"  步骤2: 点击「备份全部在线设备」按钮")
    try:
        backup_btn = page.locator("button:has-text('备份全部在线设备'), button:has-text('Backup All Online')").first
        if backup_btn.is_visible(timeout=3000):
            backup_btn.click()
            page.wait_for_timeout(5000)
            settle(page, 3000)
            shot(page, f"TC{cid}_02_backup_triggered")
    except Exception:
        print(f"    [跳过] 备份全部在线设备按钮未找到")

    # 步骤 3: 查看某条备份配置
    print(f"  步骤3: 点击「查看」按钮查看某台设备的备份配置内容")
    try:
        view_btn = page.locator("button:has-text('查看'), button:has-text('View')").first
        if view_btn.is_visible(timeout=3000):
            view_btn.click()
            page.wait_for_timeout(2000)
            shot(page, f"TC{cid}_03_backup_view_config")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
    except Exception:
        print(f"    [跳过] 查看按钮未找到")


# ═══════════════════════════════════════════════════════════
# TC-15: 备份计划
# ═══════════════════════════════════════════════════════════
def tc_config_schedule(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 备份计划")

    click_nav(page, "Backup Schedule", "/config/schedule")
    print(f"  步骤1: 查看备份计划列表")
    shot(page, f"TC{cid}_01_schedule")


# ═══════════════════════════════════════════════════════════
# TC-16: 配置对比
# ═══════════════════════════════════════════════════════════
def tc_config_diff(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 配置对比")

    click_nav(page, "Config Diff", "/config/diff")
    print(f"  步骤1: 查看配置差异比对界面")
    shot(page, f"TC{cid}_01_config_diff")


# ═══════════════════════════════════════════════════════════
# TC-17: 配置搜索
# ═══════════════════════════════════════════════════════════
def tc_config_search(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 配置搜索")

    click_nav(page, "Config Search", "/config/search")
    print(f"  步骤1: 查看全局配置搜索页面")
    shot(page, f"TC{cid}_01_config_search")

    # 步骤 2: 输入搜索关键词
    print(f"  步骤2: 输入搜索关键词 'vlan' 并执行搜索")
    try:
        search_input = page.locator("input[placeholder*='192.168'], input[type='text']").first
        if search_input.is_visible(timeout=2000):
            search_input.fill("vlan")
            # 按回车或点搜索
            page.keyboard.press("Enter")
            page.wait_for_timeout(3000)
            settle(page)
            shot(page, f"TC{cid}_02_config_search_result")
    except Exception:
        print(f"    [跳过] 搜索操作失败")


# ═══════════════════════════════════════════════════════════
# TC-18: 自动化执行控制台 — 完整向导
# ═══════════════════════════════════════════════════════════
def tc_automation_execute(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 自动化执行控制台 — 完整向导")

    # 使用 SPA 客户端路由导航（page.goto 会命中后端 404）
    nav(page, "/automation/execute")
    page.wait_for_timeout(2000)
    settle(page)
    print(f"  步骤1: 进入自动化执行页面 — Step 1 设备选择面板")
    shot(page, f"TC{cid}_01_step1_device_grid")

    # 步骤 2: 搜索设备
    print(f"  步骤2: 搜索设备 — 输入关键词 'AS-BJ'")
    try:
        search = page.locator("input[placeholder*='搜索主机名'], input[placeholder*='Search hostname']").first
        if search.is_visible(timeout=3000):
            search.fill("AS-BJ")
            page.wait_for_timeout(1500)
            shot(page, f"TC{cid}_02_step1_search_result")
            search.fill("")
            page.wait_for_timeout(800)
    except Exception:
        print(f"    [跳过] 搜索框未找到")

    # 步骤 3: 筛选在线设备
    print(f"  步骤3: 筛选在线设备")
    try:
        status_select = page.locator("select").first
        if status_select.is_visible(timeout=2000):
            status_select.select_option(value="online")
            page.wait_for_timeout(1500)
            shot(page, f"TC{cid}_03_step1_filter_online")
    except Exception:
        print(f"    [跳过] 状态筛选失败")

    # 步骤 4: 选择一台设备（点击第一个设备卡片）
    print(f"  步骤4: 选择一台在线设备（点击设备卡片）")
    try:
        # 设备卡片在 main 区域的 grid 中，是 motion.button
        device_cards = page.locator("main button").filter(has=page.locator("span"))
        # 跳过工具栏按钮，找包含 IP 地址格式文字的卡片
        for i in range(min(device_cards.count(), 30)):
            txt = device_cards.nth(i).text_content() or ""
            if "." in txt and any(c.isdigit() for c in txt):
                device_cards.nth(i).click()
                page.wait_for_timeout(1000)
                break
        shot(page, f"TC{cid}_04_step1_device_selected")
    except Exception:
        print(f"    [跳过] 设备选择失败")

    # 步骤 5: 快捷查询面板（仅单设备选中时可见）
    print(f"  步骤5: 展开快捷查询面板")
    try:
        qq_btn = page.locator("button:has-text('快捷查询'), button:has-text('Quick Query')").first
        if qq_btn.is_visible(timeout=3000):
            qq_btn.click()
            page.wait_for_timeout(1500)
            shot(page, f"TC{cid}_05_quick_query_panel")

            # 步骤 6: 执行快捷查询 — 接口状态
            print(f"  步骤6: 执行快捷查询 — 接口状态")
            intf_btn = page.locator("button:has-text('接口状态'), button:has-text('Interfaces')").first
            if intf_btn.is_visible(timeout=2000):
                intf_btn.click()
                page.wait_for_timeout(8000)
                settle(page, 5000)
                shot(page, f"TC{cid}_06_quick_query_result")
    except Exception:
        print(f"    [跳过] 快捷查询未找到")

    # 步骤 7: 点击「下一步：选择任务」
    print(f"  步骤7: 点击下一步进入步骤2 — 场景选择")
    try:
        next_btn = page.locator("button:has-text('下一步'), button:has-text('Next')").first
        if next_btn.is_visible(timeout=3000):
            next_btn.click()
            page.wait_for_timeout(2500)
            settle(page)
            shot(page, f"TC{cid}_07_step2_scenario_grid")
    except Exception:
        print(f"    [跳过] 下一步按钮未找到")

    # 步骤 8: 选择一个自动化场景（优先找低风险/show类）
    print(f"  步骤8: 选择一个自动化场景")
    try:
        # 场景卡片有 rounded-xl border-2 border-l-4，找包含风险标签的按钮
        scenarios = page.locator("main button[class*='rounded-xl']").filter(has_text="show")
        if scenarios.count() == 0:
            scenarios = page.locator("main button[class*='rounded-xl']").filter(has_text="低")
        if scenarios.count() == 0:
            scenarios = page.locator("main button[class*='rounded-xl']").filter(has_text="Low")
        if scenarios.count() == 0:
            # fallback: 任何带 border-l-4 的卡片
            scenarios = page.locator("main button[class*='border-l-4']")
        if scenarios.count() > 0:
            scenarios.first.click()
            page.wait_for_timeout(2500)
            settle(page)
            shot(page, f"TC{cid}_08_step3_cli_preview")
        else:
            print(f"    [跳过] 未找到可选场景")
    except Exception:
        print(f"    [跳过] 场景选择失败")

    # 步骤 9: 查看 CLI 预览终端区域
    print(f"  步骤9: 查看 CLI 预览与参数配置区域")
    shot(page, f"TC{cid}_09_step3_params_and_terminal")

    # 步骤 10: 点击「运行校验」
    print(f"  步骤10: 点击「运行校验」按钮")
    try:
        validate_btn = page.locator("button:has-text('运行校验'), button:has-text('Validate')").first
        if validate_btn.is_visible(timeout=3000):
            validate_btn.click()
            page.wait_for_timeout(2000)
            # 等待确认弹窗
            confirm = page.locator("[role='dialog'] button:has-text('确认'), [role='dialog'] button:has-text('Confirm')").first
            if confirm.is_visible(timeout=3000):
                shot(page, f"TC{cid}_10_validate_confirm_dialog")
                confirm.click()
                page.wait_for_timeout(12000)
                settle(page, 8000)
                shot(page, f"TC{cid}_11_validate_result")
            else:
                # 无确认弹窗，直接等待校验结果
                page.wait_for_timeout(10000)
                settle(page, 8000)
                shot(page, f"TC{cid}_11_validate_result")
        else:
            print(f"    [跳过] 运行校验按钮未找到或禁用")
    except Exception:
        print(f"    [跳过] 运行校验操作失败")

    # 步骤 11: 点击「应用变更」执行配置下发
    print(f"  步骤11: 点击「应用变更」按钮执行配置下发")
    try:
        apply_btn = page.locator("button:has-text('应用变更'), button:has-text('Apply')").first
        if apply_btn.is_visible(timeout=3000):
            apply_btn.click()
            page.wait_for_timeout(2000)
            confirm = page.locator("[role='dialog'] button:has-text('确认'), [role='dialog'] button:has-text('Confirm')").first
            if confirm.is_visible(timeout=3000):
                shot(page, f"TC{cid}_12_apply_confirm_dialog")
                confirm.click()
                page.wait_for_timeout(15000)
                settle(page, 10000)
                shot(page, f"TC{cid}_13_apply_execution_result")
            else:
                page.wait_for_timeout(12000)
                settle(page, 8000)
                shot(page, f"TC{cid}_13_apply_execution_result")
        else:
            print(f"    [跳过] 应用变更按钮未找到或禁用")
    except Exception:
        print(f"    [跳过] 应用变更操作失败")


# ═══════════════════════════════════════════════════════════
# TC-19: 自定义命令模态框
# ═══════════════════════════════════════════════════════════
def tc_custom_command(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 自定义命令模态框")

    # 确保在自动化执行页面
    nav(page, "/automation/execute")
    page.wait_for_timeout(2000)
    settle(page)

    # 步骤 1: 点击「自定义命令」按钮
    print(f"  步骤1: 点击「自定义命令」打开弹窗")
    try:
        custom_btn = page.locator("button:has-text('自定义命令'), button:has-text('Custom Command')").first
        if custom_btn.is_visible(timeout=3000):
            custom_btn.click()
            page.wait_for_timeout(2000)
            shot(page, f"TC{cid}_01_custom_cmd_modal")

            # 步骤 2: 在 Query 模式输入 show 命令
            print(f"  步骤2: 在「查看」模式输入 show 命令")
            textarea = page.locator("textarea").first
            if textarea.is_visible(timeout=2000):
                textarea.fill("show ip interface brief\nshow version\nshow running-config")
                page.wait_for_timeout(800)
                shot(page, f"TC{cid}_02_query_mode_filled")

            # 步骤 3: 切换到「配置」模式
            print(f"  步骤3: 切换到「配置」模式")
            config_tab = page.locator("button:has-text('配置'), button:has-text('Config')").first
            if config_tab.is_visible(timeout=2000):
                config_tab.click()
                page.wait_for_timeout(1000)
                shot(page, f"TC{cid}_03_config_mode")

            # 步骤 4: 输入配置变更命令
            print(f"  步骤4: 输入配置变更命令")
            textarea2 = page.locator("textarea").first
            if textarea2.is_visible(timeout=2000):
                textarea2.fill("interface Vlan100\n description POC-Test-VLAN\n ip address 10.100.0.1 255.255.255.0\n no shutdown")
                page.wait_for_timeout(800)
                shot(page, f"TC{cid}_04_config_mode_filled")

            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        else:
            print(f"    [跳过] 自定义命令按钮不可见")
    except Exception as e:
        print(f"    [跳过] 自定义命令操作失败: {str(e)[:80]}")
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)


# ═══════════════════════════════════════════════════════════
# TC-20: 设备巡检 — 完整流程
# ═══════════════════════════════════════════════════════════
def tc_inspection(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 设备巡检 — 完整流程")

    # "Device Inspection" 不在侧边栏导航中，使用 page.goto 直接导航
    nav(page, "/automation/inspection")
    page.wait_for_timeout(2000)
    settle(page)
    print(f"  步骤1: 查看巡检概览页 — KPI 指标")
    shot(page, f"TC{cid}_01_inspection_overview")

    # 步骤 2: 点击「立即巡检」
    print(f"  步骤2: 点击「立即巡检」触发全局巡检")
    try:
        run_btn = page.locator("button:has-text('立即巡检'), button:has-text('Run Inspection')").first
        if run_btn.is_visible(timeout=3000):
            run_btn.click()
            page.wait_for_timeout(8000)
            settle(page, 5000)
            shot(page, f"TC{cid}_02_inspection_running")
    except Exception:
        print(f"    [跳过] 立即巡检按钮未找到")

    # 步骤 3: 切换到巡检记录标签
    print(f"  步骤3: 切换到「巡检记录」标签")
    try:
        records_tab = page.locator("button:has-text('巡检记录'), button:has-text('Records')").first
        if records_tab.is_visible(timeout=3000):
            records_tab.click()
            page.wait_for_timeout(2000)
            shot(page, f"TC{cid}_03_inspection_records")
    except Exception:
        print(f"    [跳过] 巡检记录标签未找到")

    # 步骤 4: 查看某条巡检记录详情
    print(f"  步骤4: 点击查看巡检记录详情")
    try:
        # 巡检记录行可能是 div 或 tr
        detail_btn = page.locator("button:has-text('查看'), button:has-text('View')").first
        if detail_btn.is_visible(timeout=2000):
            detail_btn.click()
            page.wait_for_timeout(2000)
            shot(page, f"TC{cid}_04_inspection_detail")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# TC-21: 执行计划
# ═══════════════════════════════════════════════════════════
def tc_scheduled_tasks(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 执行计划")

    click_nav(page, "Scheduled Tasks", "/automation/schedule")
    print(f"  步骤1: 查看执行计划列表")
    shot(page, f"TC{cid}_01_schedule")


# ═══════════════════════════════════════════════════════════
# TC-22: 变更工单 — 完整生命周期
# ═══════════════════════════════════════════════════════════
def tc_change_orders(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 变更工单 — 完整生命周期")

    click_nav(page, "Change Orders", "/change-orders")
    print(f"  步骤1: 查看变更工单列表")
    shot(page, f"TC{cid}_01_change_orders_list")

    # 步骤 2: 新建工单
    print(f"  步骤2: 点击「+ 新建工单」新建变更工单")
    try:
        new_btn = page.locator("button:has-text('新建工单'), button:has-text('New Order')").first
        if new_btn.is_visible(timeout=3000):
            new_btn.click()
            page.wait_for_timeout(2000)
            shot(page, f"TC{cid}_02_new_order_form_top")

            # 步骤 3: 填写工单信息
            print(f"  步骤3: 填写工单表单 — 标题、描述、类型")
            try:
                # 标题
                title_input = page.locator("input[name='title'], input[placeholder*='标题'], input[placeholder*='Title'], input[placeholder*='title']").first
                if title_input.is_visible(timeout=2000):
                    title_input.fill("POC测试 — 核心交换机VLAN配置变更")

                # 描述
                desc_input = page.locator("textarea[name='description'], textarea[placeholder*='描述'], textarea[placeholder*='escription'], textarea").first
                if desc_input.is_visible(timeout=2000):
                    desc_input.fill("在核心交换机 AS-BJ-DC1-0020 上新增 VLAN 200 配置，用于 POC 测试环境隔离")

                page.wait_for_timeout(500)
                shot(page, f"TC{cid}_03_new_order_filled")
            except Exception:
                print(f"    [跳过] 表单填写失败")

            # 步骤 4: 滚动到命令区域
            print(f"  步骤4: 查看工单表单 — 命令区域与回退方案")
            try:
                page.evaluate("document.querySelector('[role=dialog], [class*=modal]')?.scrollTo(0, 9999)")
                page.wait_for_timeout(500)
                shot(page, f"TC{cid}_04_new_order_commands")
            except Exception:
                pass

            # 关闭模态框
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
    except Exception:
        print(f"    [跳过] New Order 按钮未找到")

    # 步骤 5: 查看现有工单详情
    print(f"  步骤5: 查看现有工单详情面板")
    try:
        row = page.locator("table tbody tr, [class*='order-card'], [class*='row']").filter(has_text="draft").first
        if not row.is_visible(timeout=2000):
            row = page.locator("table tbody tr, [class*='card']").first
        if row.is_visible(timeout=2000):
            row.click()
            page.wait_for_timeout(2000)
            shot(page, f"TC{cid}_05_order_detail_panel")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# TC-23: 合规检查 — 完整流程
# ═══════════════════════════════════════════════════════════
def tc_compliance(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 合规检查 — 完整流程")

    nav(page, "/compliance")
    print(f"  步骤1: 查看合规概览 — KPI 卡片")
    shot(page, f"TC{cid}_01_compliance_overview")

    # 步骤 2: 点击「执行审计」
    print(f"  步骤2: 点击「执行审计」执行合规审计")
    try:
        audit_btn = page.locator("button:has-text('执行审计'), button:has-text('Run Audit')").first
        if audit_btn.is_visible(timeout=3000):
            audit_btn.click()
            page.wait_for_timeout(5000)
            settle(page, 5000)
            shot(page, f"TC{cid}_02_compliance_audit_result")
    except Exception:
        print(f"    [跳过] Run Audit 按钮未找到")

    # 步骤 3: 筛选高严重级别
    print(f"  步骤3: 筛选 Severity = High/Critical")
    try:
        sev_select = page.locator("select").filter(has_text="All Severity").first
        if not sev_select.is_visible(timeout=2000):
            sev_select = page.locator("select").first
        if sev_select.is_visible(timeout=2000):
            sev_select.select_option(label="high")
            page.wait_for_timeout(1500)
            shot(page, f"TC{cid}_03_compliance_filter_high")
    except Exception:
        pass

    # 步骤 4: 点击「Details」查看某条发现
    print(f"  步骤4: 点击某条合规发现的「Details」查看详情")
    try:
        detail_link = page.locator("button:has-text('DETAILS'), a:has-text('DETAILS'), button:has-text('详情')").first
        if detail_link.is_visible(timeout=2000):
            detail_link.click()
            page.wait_for_timeout(2000)
            shot(page, f"TC{cid}_04_compliance_finding_detail")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
    except Exception:
        pass

    # 步骤 5: 滚动到底部看更多发现
    print(f"  步骤5: 滚动查看更多合规发现记录")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(500)
    shot(page, f"TC{cid}_05_compliance_bottom")


# ═══════════════════════════════════════════════════════════
# TC-24: 容量分析
# ═══════════════════════════════════════════════════════════
def tc_capacity(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 容量分析")

    click_nav(page, "Capacity", "/capacity")
    print(f"  步骤1: 查看容量规划")
    shot(page, f"TC{cid}_01_capacity")


# ═══════════════════════════════════════════════════════════
# TC-25: 报表中心
# ═══════════════════════════════════════════════════════════
def tc_reports(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 报表中心")

    click_nav(page, "Reports", "/reports")
    print(f"  步骤1: 查看报表中心")
    shot(page, f"TC{cid}_01_reports")


# ═══════════════════════════════════════════════════════════
# TC-26: 审计日志
# ═══════════════════════════════════════════════════════════
def tc_audit(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 审计日志")

    click_nav(page, "Audit Logs", "/history")
    print(f"  步骤1: 查看审计日志列表")
    shot(page, f"TC{cid}_01_audit_logs")

    # 步骤 2: 点击某条审计记录查看详情
    print(f"  步骤2: 点击某条审计记录查看详情")
    try:
        row = page.locator("table tbody tr").first
        if row.is_visible(timeout=2000):
            row.click()
            page.wait_for_timeout(2000)
            shot(page, f"TC{cid}_02_audit_detail")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# TC-27: 平台设置
# ═══════════════════════════════════════════════════════════
def tc_platform_settings(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 平台设置")

    click_nav(page, "Settings", "/configuration")
    print(f"  步骤1: 查看平台配置")
    shot(page, f"TC{cid}_01_settings")


# ═══════════════════════════════════════════════════════════
# TC-28: 用户管理
# ═══════════════════════════════════════════════════════════
def tc_users(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 用户管理")

    click_nav(page, "Users", "/users")
    print(f"  步骤1: 查看用户列表")
    shot(page, f"TC{cid}_01_users")

    # 步骤 2: 点击「Add User」
    print(f"  步骤2: 点击「+ Add User」查看新增用户表单")
    try:
        add_btn = page.locator("button:has-text('Add User'), button:has-text('添加用户')").first
        if add_btn.is_visible(timeout=2000):
            add_btn.click()
            page.wait_for_timeout(1500)
            shot(page, f"TC{cid}_02_add_user_form")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# TC-29: 设备健康检测
# ═══════════════════════════════════════════════════════════
def tc_device_health(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 设备健康检测")

    click_nav(page, "Health Detection", "/health")
    print(f"  步骤1: 查看设备健康检测面板")
    shot(page, f"TC{cid}_01_health")


# ═══════════════════════════════════════════════════════════
# TC-30: 配置漂移
# ═══════════════════════════════════════════════════════════
def tc_config_drift(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 配置漂移")

    nav(page, "/config/drift")
    print(f"  步骤1: 查看配置漂移检测页面")
    shot(page, f"TC{cid}_01_config_drift")


# ═══════════════════════════════════════════════════════════
# TC-31: 执行历史 — 查看自动化作业结果
# ═══════════════════════════════════════════════════════════
def tc_execution_history(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 执行历史 — 查看自动化作业结果")

    nav(page, "/automation/history")
    print(f"  步骤1: 查看执行历史列表")
    page.wait_for_timeout(2000)
    settle(page)
    shot(page, f"TC{cid}_01_execution_history")

    # 步骤 2: 查看某条作业输出
    print(f"  步骤2: 点击查看某条作业的输出详情")
    try:
        view_btn = page.locator("button:has-text('View'), button:has-text('查看'), table tbody tr button").first
        if view_btn.is_visible(timeout=3000):
            view_btn.click()
            page.wait_for_timeout(2000)
            shot(page, f"TC{cid}_02_job_output_modal")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
    except Exception:
        print(f"    [跳过] 作业输出查看失败")


# ═══════════════════════════════════════════════════════════
# TC-32: 响应式布局
# ═══════════════════════════════════════════════════════════
def tc_responsive(page: Page):
    cid = case_id()
    print(f"\n[TC-{cid}] 响应式布局测试")

    click_nav(page, "Dashboard", "/dashboard")

    print(f"  步骤1: 桌面宽度 1920px")
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.wait_for_timeout(500)
    shot(page, f"TC{cid}_01_desktop_1920")

    print(f"  步骤2: 平板宽度 768px")
    page.set_viewport_size({"width": 768, "height": 1024})
    page.wait_for_timeout(500)
    shot(page, f"TC{cid}_02_tablet_768")

    print(f"  步骤3: 手机宽度 375px")
    page.set_viewport_size({"width": 375, "height": 812})
    page.wait_for_timeout(500)
    shot(page, f"TC{cid}_03_mobile_375")

    page.set_viewport_size({"width": 1920, "height": 1080})


# ═══════════════════════════════════════════════════════════
# TC-33: API 性能验证
# ═══════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
def main():
    print("=" * 70)
    print("  NetPilot POC 详细自动化测试 v3")
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
            tc_login,              # TC-01
            tc_dashboard,          # TC-02
            tc_monitoring,         # TC-03
            tc_topology,           # TC-04
            tc_alerts,             # TC-05: 告警完整操作
            tc_alert_history,      # TC-06
            tc_alert_rules,        # TC-07
            tc_maintenance,        # TC-08
            tc_assets,             # TC-09
            tc_devices,            # TC-10: 设备详细操作
            tc_servers,            # TC-11
            tc_ipam,               # TC-12
            tc_ip_locator,         # TC-13
            tc_config_backup,      # TC-14: 备份完整操作
            tc_config_schedule,    # TC-15
            tc_config_diff,        # TC-16
            tc_config_search,      # TC-17: 配置搜索操作
            tc_automation_execute, # TC-18: 自动化4步向导
            tc_custom_command,     # TC-19: 自定义命令
            tc_inspection,         # TC-20: 设备巡检完整
            tc_scheduled_tasks,    # TC-21
            tc_change_orders,      # TC-22: 变更工单完整
            tc_compliance,         # TC-23: 合规完整操作
            tc_capacity,           # TC-24
            tc_reports,            # TC-25
            tc_audit,              # TC-26: 审计详情
            tc_platform_settings,  # TC-27
            tc_users,              # TC-28: 用户管理操作
            tc_device_health,      # TC-29
            tc_config_drift,       # TC-30
            tc_execution_history,  # TC-31: 执行历史
            tc_responsive,         # TC-32
            tc_api_perf,           # TC-33
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
