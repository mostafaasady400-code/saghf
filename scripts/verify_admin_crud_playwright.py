import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright

artifacts_dir = r"C:\Users\RINO TEK\.gemini\antigravity-ide\brain\b0700ae5-99ce-4ca6-bebf-bfb35450c9b6"
chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=chrome_path, headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})

    # 1. Login
    print("1. Navigating to login...")
    page.goto('http://127.0.0.1:5000/admin/login', wait_until='domcontentloaded')
    page.wait_for_timeout(1000)
    page.fill('#adminUsername', 'saghf_admin')
    page.fill('#adminPassword', 'SaghfSuperAdmin#2026!')
    page.click('button[type="submit"]')
    page.wait_for_timeout(1500)

    # 2. Go to Users CRUD page
    print("2. Navigating to Users CRUD...")
    page.goto('http://127.0.0.1:5000/admin/users', wait_until='domcontentloaded')
    page.wait_for_timeout(1000)
    page.screenshot(path=os.path.join(artifacts_dir, "admin_crud_users_list.png"), full_page=True)
    print("   Captured admin_crud_users_list.png")

    # 3. Open Create User Modal
    print("3. Opening Create User Modal...")
    page.click('button:has-text("ایجاد کاربر یا ادمین جدید")')
    page.wait_for_timeout(800)
    page.screenshot(path=os.path.join(artifacts_dir, "admin_crud_modal_open.png"))
    print("   Captured admin_crud_modal_open.png")

    # 4. Check Admin Dashboard
    print("4. Checking Dashboard preview...")
    page.goto('http://127.0.0.1:5000/admin/dashboard', wait_until='domcontentloaded')
    page.wait_for_timeout(1000)
    page.screenshot(path=os.path.join(artifacts_dir, "admin_dashboard_crud_preview.png"), full_page=True)
    print("   Captured admin_dashboard_crud_preview.png")

    browser.close()
    print("ALL ADMIN CRUD SCREENSHOTS CAPTURED SUCCESSFULLY!")
