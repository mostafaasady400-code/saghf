from playwright.sync_api import sync_playwright

chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=chrome_path, headless=True)
    page = browser.new_page()
    page.goto('http://127.0.0.1:5000/properties/', wait_until='networkidle')
    
    # Direct JS call
    res = page.evaluate("""() => {
        openModal('divarSessionModal');
        return document.getElementById('divarSessionModal').style.display;
    }""")
    print('Direct JS call result:', res)
    
    browser.close()
