@echo off
title Chrome با Debug Port برای سقف
echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║   Chrome با پورت Debugging 9222 برای سقف CRM        ║
echo ║   پس از باز شدن Chrome، در divar.ir وارد شوید       ║
echo ╚══════════════════════════════════════════════════════╝
echo.

set CHROME_EXE="C:\Program Files\Google\Chrome\Application\chrome.exe"
set USER_DATA="%LOCALAPPDATA%\Google\Chrome\SaghfProfile"

echo در حال راه‌اندازی Chrome با Debug Port 9222...
start "" %CHROME_EXE% --remote-debugging-port=9222 --user-data-dir=%USER_DATA% --no-first-run --no-default-browser-check "https://divar.ir"

echo.
echo ✅ Chrome راه‌اندازی شد. حالا:
echo    1. در Chrome به divar.ir بروید و وارد حساب شوید
echo    2. در پنل سقف بروید به: تنظیمات > سشن دیوار > بروزرسانی
echo    3. یا اسکریپت زیر را اجرا کنید: python scratch/cdp_fresh_session.py
echo.
pause
