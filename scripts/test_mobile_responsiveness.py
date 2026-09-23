import os
import sys
import time

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright

artifacts_dir = r"C:\Users\RINO TEK\.gemini\antigravity-ide\brain\b0700ae5-99ce-4ca6-bebf-bfb35450c9b6"
chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

def run_mobile_test():
    print("Starting mobile responsiveness test at 390x844...")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome_path, headless=True)
        context = browser.new_context(
            viewport={'width': 390, 'height': 844},
            user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
        )
        page = context.new_page()
        page.goto('http://127.0.0.1:5000/properties/', wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(1000)

        # 1. Top Navbar Check
        print("1. Testing top navbar and bottom bar...")
        navbar = page.locator(".floating-3d-navbar")
        hamburger = page.locator("#mobileMenuToggleBtn")
        bottom_bar = page.locator("#mobileBottomBar")

        assert navbar.is_visible(), "Top navbar should be visible"
        assert hamburger.is_visible(), "Hamburger button should be visible on mobile"
        assert bottom_bar.is_visible(), "Bottom bar should be visible on mobile"

        # Check horizontal overflow
        scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
        client_width = page.evaluate("() => document.documentElement.clientWidth")
        print(f"Viewport clientWidth: {client_width}, scrollWidth: {scroll_width}")
        assert scroll_width <= client_width + 1, f"Page has horizontal overflow! {scroll_width} > {client_width}"

        page.screenshot(path=os.path.join(artifacts_dir, "mobile_1_top_navbar.png"))

        # 2. Test Mobile Drawer
        print("2. Testing mobile drawer open/close...")
        hamburger.click()
        page.wait_for_timeout(500)
        drawer = page.locator("#mobileNavDrawer")
        assert "active" in drawer.get_attribute("class"), "Drawer should have 'active' class after click"
        page.screenshot(path=os.path.join(artifacts_dir, "mobile_2_drawer_opened.png"))

        # Close drawer
        close_btn = page.locator(".mobile-drawer-close-btn")
        close_btn.click(force=True, timeout=3000)
        page.wait_for_timeout(500)
        assert "active" not in drawer.get_attribute("class"), "Drawer should close after clicking close button"

        # 3. Test 3D Mansion Tour Height & Scrolling
        print("3. Testing 3D tour mobile height...")
        tour = page.locator("#mansion-3d-tour-container")
        tour_box = tour.bounding_box()
        print(f"Tour container height on mobile: {tour_box['height']}px")
        assert tour_box['height'] < 2500, f"Tour height on mobile should be compact (~1688px), got {tour_box['height']}px"

        page.evaluate("window.scrollTo(0, 450)")
        page.wait_for_timeout(400)
        page.screenshot(path=os.path.join(artifacts_dir, "mobile_3_tour_scrolling.png"))

        # 4. Scroll to AI Station Resting
        print("4. Testing AI station resting state...")
        ai_station = page.locator("#ai-station")
        ai_station.scroll_into_view_if_needed()
        page.wait_for_timeout(600)
        page.screenshot(path=os.path.join(artifacts_dir, "mobile_4_ai_station_resting.png"))

        # 5. Activate In-Page AI Station
        print("5. Testing AI station active state...")
        page.locator("#restingOrbBtn").click()
        page.wait_for_timeout(600)
        active_panel = page.locator("#aiActivePanel")
        assert active_panel.is_visible(), "AI active panel should be visible"

        # Check form does not overflow
        voice_form = page.locator("#chatgptVoiceForm")
        form_box = voice_form.bounding_box()
        print(f"Voice form width: {form_box['width']}px (must be <= {client_width})")
        assert form_box['width'] <= client_width, "Voice form overflows screen width!"
        page.screenshot(path=os.path.join(artifacts_dir, "mobile_5_ai_station_active.png"))

        # 6. Test interaction chip click
        print("6. Testing AI prompt submission...")
        first_chip = page.locator(".station-chip").first
        first_chip.click()
        page.wait_for_timeout(2500)
        page.screenshot(path=os.path.join(artifacts_dir, "mobile_6_ai_station_cards.png"))

        # Close AI panel
        page.locator(".ai-active-close-btn").click()
        page.wait_for_timeout(400)

        # 7. Scroll to Catalog & Filters
        print("7. Testing catalog, deal tabs and property cards...")
        catalog = page.locator("#properties-catalog-section")
        catalog.scroll_into_view_if_needed()
        page.wait_for_timeout(600)

        deal_tabs = page.locator(".deal-tabs-container")
        deal_tabs_box = deal_tabs.bounding_box()
        print(f"Deal tabs width: {deal_tabs_box['width']}px (must be <= {client_width})")
        assert deal_tabs_box['width'] <= client_width, "Deal tabs overflow screen width!"

        page.screenshot(path=os.path.join(artifacts_dir, "mobile_7_catalog_and_cards.png"))

        # Check final scroll width
        scroll_width_final = page.evaluate("() => document.documentElement.scrollWidth")
        print(f"Final scrollWidth: {scroll_width_final}, clientWidth: {client_width}")
        assert scroll_width_final <= client_width + 1, f"Final page has horizontal overflow! {scroll_width_final} > {client_width}"

        browser.close()
        print("ALL MOBILE RESPONSIVENESS TESTS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    run_mobile_test()
