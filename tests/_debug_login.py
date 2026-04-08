"""调试登录页 DOM"""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()
    page.goto("http://127.0.0.1:8003")
    page.evaluate("localStorage.removeItem('netops_token')")
    page.reload()
    page.wait_for_timeout(5000)

    inputs = page.evaluate("""() => {
        const all = document.querySelectorAll('input');
        return Array.from(all).map(el => ({
            id: el.id, name: el.name, type: el.type,
            visible: el.offsetParent !== null,
            rect: JSON.stringify(el.getBoundingClientRect()),
        }));
    }""")
    print("All inputs:", inputs)
    print("URL:", page.url)
    forms = page.evaluate("document.querySelectorAll('form').length")
    print("Form count:", forms)
    html = page.evaluate("document.body.innerHTML.substring(0, 2000)")
    print("Body HTML:", html[:2000])
    browser.close()
