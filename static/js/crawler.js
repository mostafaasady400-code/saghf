// SAGHF CRAWLER LIVE CONSOLE & STREAMING CONTROLLER

let crawlerPollInterval = null;

function initCrawler() {
    const startForm = document.getElementById('crawler-start-form');
    if (startForm) {
        startForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = document.getElementById('start-crawl-btn');
            const originalBtnText = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = `<span class="neon-pulse-dot cyan"></span> در حال اجرا...`;

            const sources = Array.from(startForm.querySelectorAll('input[name="sources"]:checked')).map(el => el.value);
            const categories = Array.from(startForm.querySelectorAll('input[name="categories"]:checked')).map(el => el.value);
            const limit = document.getElementById('crawler-limit')?.value || 8;

            try {
                const res = await fetch('/crawler/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sources, categories, limit })
                });
                const data = await res.json();
                if (data.success) {
                    showToast(data.message, 'success');
                    startPollingStatus();
                } else {
                    showToast(data.message, 'error');
                    btn.disabled = false;
                    btn.innerHTML = originalBtnText;
                }
            } catch (err) {
                showToast('خطا در ارتباط با سرور کراولر', 'error');
                btn.disabled = false;
                btn.innerHTML = originalBtnText;
            }
        });
    }

    // Initial status check
    pollStatus();
}

function startPollingStatus() {
    if (crawlerPollInterval) clearInterval(crawlerPollInterval);
    crawlerPollInterval = setInterval(pollStatus, 2000);
}

async function pollStatus() {
    try {
        const res = await fetch('/crawler/status');
        const data = await res.json();
        
        updateCrawlerUI(data);

        const btn = document.getElementById('start-crawl-btn');
        if (!data.is_running && btn && btn.disabled) {
            btn.disabled = false;
            btn.innerHTML = `<span>⚡</span> شروع کراولینگ دیوار و شیپور`;
            showToast('فرآیند کراولینگ به پایان رسید. فایل‌های جدید ثبت شدند.', 'info');
        }
    } catch (err) {
        console.error("Polling error:", err);
    }
}

function updateCrawlerUI(data) {
    // 1. Status Indicator
    const statusPill = document.getElementById('crawler-status-pill');
    if (statusPill) {
        if (data.is_running) {
            statusPill.innerHTML = `<span class="neon-pulse-dot emerald"></span> در حال استخراج زنده`;
            statusPill.className = 'badge-neon badge-neon-emerald';
        } else {
            statusPill.innerHTML = `<span class="neon-pulse-dot cyan"></span> آماده به کار`;
            statusPill.className = 'badge-neon badge-neon-cyan';
        }
    }

    // 2. Stats
    if (data.stats) {
        const totalCrawled = document.getElementById('stat-total-crawled');
        const newSaved = document.getElementById('stat-new-saved');
        const skipped = document.getElementById('stat-skipped');
        const totalDb = document.getElementById('stat-total-db');

        if (totalCrawled) totalCrawled.innerText = data.stats.total_crawled || 0;
        if (newSaved) newSaved.innerText = data.stats.new_saved || 0;
        if (skipped) skipped.innerText = data.stats.duplicates_skipped || 0;
        if (totalDb) totalDb.innerText = data.stats.total_in_db || 0;
    }

    // 3. Live Terminal Logs
    const terminal = document.getElementById('crawler-terminal');
    if (terminal && data.recent_logs) {
        terminal.innerHTML = data.recent_logs.map(log => {
            let color = '#a7f3d0';
            if (log.level === 'error') color = '#f87171';
            if (log.level === 'success') color = '#34d399';
            return `<div class="terminal-line" style="color: ${color};">
                <span class="terminal-time">[${log.time}]</span> ${log.message}
            </div>`;
        }).join('');
        terminal.scrollTop = terminal.scrollHeight;
    }
}

document.addEventListener('DOMContentLoaded', initCrawler);
