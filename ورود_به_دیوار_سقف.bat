@echo off
chcp 65001 >nul
title اتصال امن سامانه سقف به دیوار
echo ========================================================
echo     در حال راه‌اندازی مرورگر گوگل کروم جهت تایید دیوار
echo ========================================================
echo.
echo لطفاً پس از باز شدن پنجره، شماره موبایل خود را وارد کرده و کد پیامکی را بزنید.
echo پس از ورود موفق، پنجره را نبندید؛ سیستم سقف به صورت خودکار اطلاعات نشست را ضبط خواهد کرد.
echo.
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\SaghfChromeProfile --start-maximized "https://divar.ir/my-divar/my-posts"
