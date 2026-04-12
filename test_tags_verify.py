"""Verify tag features: inventory page tags column + filter, automation tab tag filter."""
from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})

    # --- Login ---
    page.goto("http://localhost:4300")
    page.wait_for_load_state("networkidle")
    time.sleep(1)

    # Check if login screen
    if page.locator('input[type="password"]').count() > 0:
        page.locator('input[placeholder*="用户名"], input[placeholder*="Username"], input[name="username"]').first.fill("admin")
        page.locator('input[type="password"]').first.fill("admin123")
        page.locator('button:has-text("登录"), button:has-text("Login"), button[type="submit"]').first.click()
        page.wait_for_load_state("networkidle")
        time.sleep(2)

    # --- Navigate to Network Devices via sidebar ---
    page.locator('text=Network Devices').or_(page.locator('text=网络设备')).first.click()
    time.sleep(2)
    page.wait_for_load_state("networkidle")
    time.sleep(1)
    page.screenshot(path="d:/tools/netops/verify_01_inventory_page.png", full_page=False)
    print("Screenshot 1: Network Devices page saved")

    # --- Screenshot 2: Look for the tag filter button in the toolbar (not sidebar) ---
    # The tag filter is inside the filter toolbar area, not the sidebar
    toolbar = page.locator('.flex.items-center.gap-2.flex-wrap')
    if toolbar.count() > 0:
        tag_btns = toolbar.locator('button:has-text("标签"), button:has-text("Tags")')
        if tag_btns.count() > 0:
            tag_btns.first.click()
            time.sleep(1)
            page.screenshot(path="d:/tools/netops/verify_02_tag_filter_open.png", full_page=False)
            print("Screenshot 2: Tag filter dropdown saved")
            # Close by clicking elsewhere
            page.mouse.click(10, 10)
            time.sleep(0.5)
        else:
            print("WARNING: Tag filter button not found in toolbar")
            page.screenshot(path="d:/tools/netops/verify_02_tag_filter_open.png", full_page=False)

    # --- Screenshot 3: Click first device row to see detail with tags ---
    # Look for a details/eye button in the table
    eye_btns = page.locator('table button').filter(has=page.locator('svg'))
    if eye_btns.count() >= 1:
        # Click first action group's first button (details)
        eye_btns.first.click()
        time.sleep(1)
        page.screenshot(path="d:/tools/netops/verify_03_device_detail.png", full_page=False)
        print("Screenshot 3: Device detail modal saved")
        page.keyboard.press("Escape")
        time.sleep(0.5)
    else:
        print("WARNING: No detail buttons found")

    # --- Navigate to Automation via sidebar ---
    page.locator('a:has-text("Automation"), a:has-text("自动化")').first.click()
    time.sleep(2)
    page.wait_for_load_state("networkidle")
    time.sleep(1)
    page.screenshot(path="d:/tools/netops/verify_04_automation_page.png", full_page=False)
    print("Screenshot 4: Automation page saved")

    # --- Screenshot 5: Click tag filter in automation filter bar ---
    # The automation filter bar is inside a specific div with a search input
    auto_toolbar = page.locator('.flex-shrink-0.flex.items-center')
    if auto_toolbar.count() > 0:
        tag_btns2 = auto_toolbar.locator('button:has-text("标签"), button:has-text("Tags")')
        if tag_btns2.count() > 0:
            tag_btns2.first.click()
            time.sleep(1)
            page.screenshot(path="d:/tools/netops/verify_05_automation_tag_filter.png", full_page=False)
            print("Screenshot 5: Automation tag filter saved")
        else:
            print("WARNING: Tag filter button not found in automation toolbar, trying general search")
            # Try global locator but exclude sidebar
            main_area = page.locator('main, .flex-1')
            tag_btn_global = main_area.locator('button:has-text("Tags"), button:has-text("标签")')
            if tag_btn_global.count() > 0:
                tag_btn_global.first.click()
                time.sleep(1)
                page.screenshot(path="d:/tools/netops/verify_05_automation_tag_filter.png", full_page=False)
                print("Screenshot 5: Automation tag filter saved (via main)")
            else:
                page.screenshot(path="d:/tools/netops/verify_05_automation_tag_filter.png", full_page=False)
                print("WARNING: No tag filter in automation at all")
    else:
        page.screenshot(path="d:/tools/netops/verify_05_automation_tag_filter.png", full_page=False)
        print("WARNING: No auto toolbar found")

    browser.close()
    print("Done!")
