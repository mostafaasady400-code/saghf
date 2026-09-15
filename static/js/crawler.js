// SAGHF CRAWLER LIVE CONSOLE & STREAMING CONTROLLER

let crawlerPollInterval = null;
let liveItemsPollInterval = null;
let wasRunning = false;

function toPersianDigits(num) {
    if (num === null || num === undefined) return '';
    const id = ['۰','۱','۲','۳','۴','۵','۶','۷','۸','۹'];
    return num.toString().replace(/[0-9]/g, function(w){
        return id[+w];
    });
}

function formatToman(price) {
    if (!price || price === 0) return 'توافقی';
    if (price >= 1000000000) {
        const val = (price / 1000000000).toFixed(1).replace('.0', '');
        return `${toPersianDigits(val)} میلیارد تومان`;
    }
    if (price >= 1000000) {
        const val = (price / 1000000).toFixed(0);
        return `${toPersianDigits(val)} میلیون تومان`;
    }
    return `${toPersianDigits(price.toLocaleString())} تومان`;
}

function initCrawler() {
    const startForm = document.getElementById('crawler-start-form');
    if (startForm) {
        startForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = document.getElementById('start-crawl-btn');
            const originalBtnText = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = `<span class="neon-pulse-dot cyan"></span> در حال استخراج و تحلیل...`;

            const sources = Array.from(startForm.querySelectorAll('input[name="sources"]:checked')).map(el => el.value);
            const categories = Array.from(startForm.querySelectorAll('input[name="categories"]:checked')).map(el => el.value);
            const limit = document.getElementById('crawler-limit')?.value || 10;
            const city = document.getElementById('crawler-city')?.value?.trim() || 'tehran';
            const district = document.getElementById('crawler-district')?.value?.trim() || '';

            try {
                const res = await fetch('/crawler/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sources, categories, limit, city, district })
                });
                const data = await res.json();
                if (data.success) {
                    showToast(data.message, 'success');
                    wasRunning = true;
                    startPolling();
                } else {
                    showToast(data.message, 'error');
                    btn.disabled = false;
                    btn.innerHTML = originalBtnText;
                }
            } catch (err) {
                showToast('خطا در برقراری ارتباط با سرویس کراولر', 'error');
                btn.disabled = false;
                btn.innerHTML = originalBtnText;
            }
        });
    }

    // Reset Data Button handler
    const resetBtn = document.getElementById('reset-data-btn');
    if (resetBtn) {
        resetBtn.addEventListener('click', async () => {
            if (!confirm('آیا از پاک‌سازی کامل تمام دیتای کراولر اطمینان دارید؟')) return;
            resetBtn.disabled = true;
            resetBtn.innerText = 'در حال پاک‌سازی...';
            try {
                const res = await fetch('/crawler/reset-data', { method: 'POST' });
                const d = await res.json();
                if (d.success) {
                    showToast(d.message, 'success');
                    // Reset UI containers
                    const saleCont = document.getElementById('sale-cards-container');
                    const rentCont = document.getElementById('rent-cards-container');
                    if (saleCont) saleCont.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; color: #64748b; padding: 2.5rem;">داده‌های فروش پاک‌سازی شدند.</div>';
                    if (rentCont) rentCont.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; color: #64748b; padding: 2.5rem;">داده‌های رهن و اجاره پاک‌سازی شدند.</div>';
                    
                    // Reset counts
                    updateCountBadges(0, 0, 0);
                    window.highestPropertyId = 0;
                } else {
                    showToast(d.message, 'error');
                }
            } catch (err) {
                showToast('خطا در پاک‌سازی داده‌ها', 'error');
            } finally {
                resetBtn.disabled = false;
                resetBtn.innerText = '🧹 پاک‌سازی دیتا';
            }
        });
    }

    // Initial status and live polling check
    pollStatus();
    startPolling();
}

function startPolling() {
    if (crawlerPollInterval) clearInterval(crawlerPollInterval);
    if (liveItemsPollInterval) clearInterval(liveItemsPollInterval);

    crawlerPollInterval = setInterval(pollStatus, 1500);
    liveItemsPollInterval = setInterval(pollLiveItems, 1800);
}

async function pollStatus() {
    try {
        const res = await fetch('/crawler/status');
        const data = await res.json();
        
        updateCrawlerUI(data);

        const btn = document.getElementById('start-crawl-btn');
        if (wasRunning && !data.is_running) {
            wasRunning = false;
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = `<span>⚡</span> شروع کراولینگ`;
            }
            showToast('عملیات کراولینگ به پایان رسید. تمامی آگهی‌های جدید به‌صورت زنده به پنل‌ها افزوده شدند.', 'success');
        } else if (!data.is_running && btn && btn.disabled) {
            btn.disabled = false;
            btn.innerHTML = `<span>⚡</span> شروع کراولینگ`;
        }
    } catch (err) {
        console.error("Polling error:", err);
    }
}

async function pollLiveItems() {
    const sinceId = window.highestPropertyId || 0;
    try {
        const res = await fetch(`/crawler/live-items?since_id=${sinceId}`);
        const data = await res.json();
        if (data.items && data.items.length > 0) {
            data.items.forEach(item => {
                appendLivePropertyCard(item);
                if (item.id > (window.highestPropertyId || 0)) {
                    window.highestPropertyId = item.id;
                }
            });
            updateCountBadges(data.total_sale, data.total_rent, data.total_all);
        }
    } catch (e) {
        console.error("Live items poll error:", e);
    }
}

function updateCountBadges(saleCount, rentCount, totalAll) {
    const saleTab = document.getElementById('tab-sale-count');
    const rentTab = document.getElementById('tab-rent-count');
    const saleHeader = document.getElementById('panel-sale-count');
    const rentHeader = document.getElementById('panel-rent-count');
    const statDb = document.getElementById('stat-total-db');

    if (saleTab) saleTab.innerText = toPersianDigits(saleCount);
    if (rentTab) rentTab.innerText = toPersianDigits(rentCount);
    if (saleHeader) saleHeader.innerText = `${toPersianDigits(saleCount)} فایل ثبت‌شده`;
    if (rentHeader) rentHeader.innerText = `${toPersianDigits(rentCount)} فایل ثبت‌شده`;
    if (statDb) statDb.innerText = toPersianDigits(totalAll);
}

function appendLivePropertyCard(p) {
    const isSale = p.deal_type === 'sale';
    const containerId = isSale ? 'sale-cards-container' : 'rent-cards-container';
    let container = document.getElementById(containerId);
    if (!container) return;

    // Check if duplicate element already rendered
    if (document.getElementById(`prop-card-${p.id}`)) return;

    // If container currently shows empty placeholder, clear it
    if (container.querySelector('.empty-placeholder')) {
        container.innerHTML = '';
    }

    const card = document.createElement('div');
    card.id = `prop-card-${p.id}`;
    card.className = 'glass-card live-card-pulse';
    card.style.cssText = `padding: 1.15rem; border: 1px solid ${isSale ? 'rgba(0, 242, 254, 0.25)' : 'rgba(245, 158, 11, 0.25)'}; display: flex; flex-direction: column; justify-content: space-between; transition: all 0.3s;`;

    // Contact Option Box
    const phone = p.owner?.phone_number || '';
    let contactBoxHtml = '';
    if (phone && phone.startsWith('09')) {
        contactBoxHtml = `
            <div class="contact-option-box" style="margin-top: 0.65rem; margin-bottom: 0.65rem; background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 10px; padding: 0.55rem 0.75rem; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.4rem; padding-bottom: 0.35rem; border-bottom: 1px solid rgba(255,255,255,0.06);">
                    <span style="font-size: 0.76rem; font-weight: 700; color: #cbd5e1; display: flex; align-items: center; gap: 0.35rem;">
                        <span>📞</span> گزینه تماس مستقیم با آگهی‌دهنده:
                    </span>
                    <span class="badge-neon badge-neon-emerald" style="font-size: 0.65rem; padding: 0.1rem 0.4rem;">
                        ✓ استخراج شده
                    </span>
                </div>
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; flex-wrap: wrap;">
                    <a href="tel:${phone}" style="text-decoration: none; display: inline-flex; align-items: center; gap: 0.4rem; background: rgba(16, 185, 129, 0.2); border: 1px solid rgba(16, 185, 129, 0.4); padding: 0.3rem 0.65rem; border-radius: 8px; color: #10b981; font-weight: 800; font-size: 0.95rem; letter-spacing: 1.5px; direction: ltr;">
                        <span>📲</span>
                        <span>${phone}</span>
                    </a>
                    <div style="display: flex; gap: 0.35rem; align-items: center;">
                        <a href="tel:${phone}" class="btn-neon-emerald" style="padding: 0.28rem 0.65rem; font-size: 0.74rem; text-decoration: none; font-weight: 700;">
                            تماس فوری
                        </a>
                        <button type="button" onclick="navigator.clipboard.writeText('${phone}'); alert('شماره در حافظه کپی شد: ${phone}');" class="glass-btn" style="padding: 0.28rem 0.5rem; font-size: 0.74rem; color: #10b981;" title="کپی شماره">
                            📋
                        </button>
                        <button type="button" onclick="openMessengerModal(${p.id})" class="glass-btn" style="padding: 0.28rem 0.55rem; font-size: 0.74rem; color: #38bdf8;" title="استعلام وضعیت در ۵ پیام‌رسان">
                            💬
                        </button>
                        <button type="button" onclick="promptSavePhone(${p.id}, '${phone}', '${p.owner?.full_name || ''}')" class="glass-btn" style="padding: 0.28rem 0.5rem; font-size: 0.74rem; color: #94a3b8;" title="ویرایش شماره">
                            ✏️
                        </button>
                    </div>
                </div>
            </div>
        `;
    } else {
        contactBoxHtml = `
            <div class="contact-option-box" style="margin-top: 0.65rem; margin-bottom: 0.65rem; background: rgba(0, 242, 254, 0.07); border: 1px solid rgba(0, 242, 254, 0.25); border-radius: 10px; padding: 0.55rem 0.75rem; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.4rem; padding-bottom: 0.35rem; border-bottom: 1px solid rgba(255,255,255,0.06);">
                    <span style="font-size: 0.76rem; font-weight: 700; color: #cbd5e1; display: flex; align-items: center; gap: 0.35rem;">
                        <span>📞</span> گزینه تماس مستقیم با آگهی‌دهنده:
                    </span>
                    <span class="badge-neon badge-neon-amber" style="font-size: 0.65rem; padding: 0.1rem 0.4rem;">
                        🔒 نیاز به استخراج
                    </span>
                </div>
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 0.4rem; flex-wrap: wrap;">
                    <button type="button" onclick="fetchDivarPhoneDirect(${p.id})" class="btn-neon-cyan" style="flex: 1; min-width: 130px; justify-content: center; padding: 0.35rem 0.55rem; font-size: 0.75rem; font-weight: 700; cursor: pointer;" title="استخراج خودکار شماره واقعی با توکن نشست دیوار">
                        <span>⚡</span> استخراج خودکار شماره
                    </button>
                    <button type="button" onclick="promptSavePhone(${p.id}, '', '${p.owner?.full_name || ''}')" class="glass-btn" style="padding: 0.35rem 0.6rem; font-size: 0.75rem; color: #10b981; border-color: rgba(16, 185, 129, 0.3);" title="ثبت دستی شماره تلفن">
                        <span>✏️</span> ثبت شماره
                    </button>
                    ${p.source_url ? `<a href="${p.source_url}" target="_blank" rel="noopener noreferrer" class="glass-btn" style="padding: 0.35rem 0.6rem; font-size: 0.75rem; color: #00f2fe; text-decoration: none; border-color: rgba(0, 242, 254, 0.3);" title="مشاهده اطلاعات تماس در دیوار">🌐 دیوار</a>` : ''}
                </div>
            </div>
        `;
    }

    // Price display
    let priceHtml = '';
    if (isSale) {
        priceHtml = `
            <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.75rem;">
                <span style="font-size: 0.8rem; color: #94a3b8;">قیمت فروش:</span>
                <span style="font-size: 1.15rem; font-weight: 800; color: #00f2fe;">${formatToman(p.total_price)}</span>
            </div>
        `;
    } else {
        priceHtml = `
            <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.75rem;">
                <div>
                    <div style="font-size: 0.75rem; color: #94a3b8;">ودیعه (رهن):</div>
                    <div style="font-size: 1.1rem; font-weight: 800; color: #f59e0b;">${formatToman(p.deposit)}</div>
                </div>
                ${p.monthly_rent > 0 ? `
                <div style="text-align: left;">
                    <div style="font-size: 0.75rem; color: #94a3b8;">اجاره ماهانه:</div>
                    <div style="font-size: 1rem; font-weight: 800; color: #10b981;">${formatToman(p.monthly_rent)}</div>
                </div>` : ''}
            </div>
        `;
    }

    // Images gallery
    let imagesHtml = '';
    if (p.images && p.images.length > 0) {
        const thumbs = p.images.slice(0, 4).map(img => `
            <a href="${img}" target="_blank" rel="noopener noreferrer" style="flex-shrink: 0;">
                <img src="${img}" referrerpolicy="no-referrer" loading="lazy" onerror="this.onerror=null; this.src='/assets/placeholder.png';" alt="ملک" style="width: 60px; height: 50px; object-fit: cover; border-radius: 6px; border: 1px solid rgba(255,255,255,0.15);">
            </a>
        `).join('');
        imagesHtml = `
            <div style="margin-bottom: 0.75rem;">
                <div style="font-size: 0.75rem; color: #94a3b8; margin-bottom: 0.35rem;">📷 عکس‌های واقعی (${toPersianDigits(p.images.length)} تصویر):</div>
                <div style="display: flex; gap: 0.4rem; overflow-x: auto; padding-bottom: 0.25rem;">${thumbs}</div>
            </div>
        `;
    }

    const badgeColor = isSale ? 'badge-neon-cyan' : 'badge-neon-amber';
    const sourceBadge = p.source === 'divar' ? 'badge-neon-cyan' : 'badge-neon-emerald';
    const sourceName = p.source === 'divar' ? 'دیوار' : 'شیپور';

    // Amenities chips
    const amenitiesHtml = `
        <div style="display: flex; gap: 0.35rem; flex-wrap: wrap; margin-bottom: 0.65rem; font-size: 0.72rem;">
            <span class="badge-neon ${p.has_elevator ? 'badge-neon-emerald' : 'badge-neon-gray'}">آسانسور ${p.has_elevator ? '✓' : '✕'}</span>
            <span class="badge-neon ${p.has_parking ? 'badge-neon-emerald' : 'badge-neon-gray'}">پارکینگ ${p.has_parking ? '✓' : '✕'}</span>
            <span class="badge-neon ${p.has_warehouse ? 'badge-neon-emerald' : 'badge-neon-gray'}">انباری ${p.has_warehouse ? '✓' : '✕'}</span>
            ${p.has_balcony ? '<span class="badge-neon badge-neon-cyan">بالکن ✓</span>' : ''}
        </div>
    `;

    card.innerHTML = `
        <div>
            <!-- Header -->
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.6rem;">
                <div style="display: flex; align-items: center; gap: 0.4rem;">
                    <span class="badge-neon ${sourceBadge}" style="font-size: 0.72rem;">${sourceName}</span>
                    <span style="font-size: 0.75rem; color: #94a3b8;">📍 ${p.district || 'تهران'}</span>
                    <span class="badge-neon badge-neon-purple" style="font-size: 0.7rem;">امتیاز: ${toPersianDigits(p.score || 85)}</span>
                    <span class="badge-neon badge-neon-emerald" style="font-size: 0.68rem; animation: pulse 1.5s infinite;">جدید ⚡</span>
                </div>
                <div>
                    ${p.source_url ? `<a href="${p.source_url}" target="_blank" rel="noopener noreferrer" class="badge-neon ${badgeColor}" style="text-decoration: none; font-size: 0.75rem; font-weight: 700;">🔗 لینک آگهی</a>` : ''}
                </div>
            </div>

            <!-- Title -->
            <h4 style="font-size: 1rem; font-weight: 700; margin: 0 0 0.6rem 0; line-height: 1.4;">
                <a href="/properties/${p.id}" style="color: #f8fafc; text-decoration: none;">
                    ${p.title}
                </a>
            </h4>

            <!-- Specs -->
            <div style="display: flex; gap: 0.75rem; font-size: 0.82rem; color: #cbd5e1; margin-bottom: 0.6rem; background: rgba(0,0,0,0.25); padding: 0.4rem 0.65rem; border-radius: 8px;">
                <span>📐 ${toPersianDigits(p.area || 0)} متر</span>
                <span>🛏️ ${toPersianDigits(p.rooms || 1)} خواب</span>
                <span>🏢 طبقه ${toPersianDigits(p.floor || 1)}${p.total_floors ? ' از ' + toPersianDigits(p.total_floors) : ''}</span>
                <span>🏗️ ساخت ${toPersianDigits(p.build_year || 1401)}</span>
            </div>

            <!-- Amenities -->
            ${amenitiesHtml}

            <!-- Dedicated Direct Contact Option Bar -->
            ${contactBoxHtml}

            ${priceHtml}
            ${imagesHtml}

            <!-- Expandable Full Description -->
            <details style="background: rgba(0,0,0,0.2); border-radius: 8px; padding: 0.5rem 0.75rem; margin-bottom: 0.75rem; font-size: 0.8rem; color: #cbd5e1; border: 1px solid rgba(255,255,255,0.05);">
                <summary style="cursor: pointer; font-weight: 700; color: #94a3b8; outline: none;">
                    📄 مشاهده متن کامل آگهی
                </summary>
                <div style="margin-top: 0.5rem; line-height: 1.6; white-space: pre-line; color: #e2e8f0; font-size: 0.82rem; max-height: 160px; overflow-y: auto; padding-right: 0.25rem;">
                    ${p.description || "توضیحات تکمیلی در صفحه اصلی آگهی درج شده است."}
                </div>
            </details>
        </div>

        <!-- Action Footer -->
        <div style="display: flex; gap: 0.5rem; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 0.75rem; margin-top: 0.5rem;">
            <a href="/properties/${p.id}" class="${isSale ? 'btn-neon-cyan' : 'glass-btn'}" style="flex: 1; justify-content: center; padding: 0.4rem 0.6rem; font-size: 0.82rem; ${!isSale ? 'border-color: rgba(245, 158, 11, 0.4); color: #f59e0b;' : ''}">
                ⚡ پرونده ملک
            </a>
            ${p.source_url ? `<a href="${p.source_url}" target="_blank" rel="noopener noreferrer" class="glass-btn" style="padding: 0.4rem 0.6rem; font-size: 0.82rem; color: ${isSale ? '#00f2fe' : '#f59e0b'}; text-decoration: none;">لینک آگهی</a>` : ''}
            <form action="/properties/${p.id}/verify" method="POST" style="display: inline;">
                <button type="submit" class="btn-neon-emerald" style="padding: 0.4rem 0.6rem; font-size: 0.82rem;" title="تأیید فایل">✓</button>
            </form>
        </div>
    `;

    // Prepend to top of container with smooth animation
    container.insertBefore(card, container.firstChild);
    showToast(`⚡ فایل جدید استخراج شد: ${p.title.slice(0, 30)}...`, 'info');
}

function updateCrawlerUI(data) {
    // 1. Status Indicator
    const statusPill = document.getElementById('crawler-status-pill');
    if (statusPill) {
        if (data.is_running) {
            statusPill.innerHTML = `<span class="neon-pulse-dot emerald"></span> در حال استخراج و اعتبارسنجی زنده`;
            statusPill.className = 'badge-neon badge-neon-emerald';
        } else {
            statusPill.innerHTML = `<span class="neon-pulse-dot cyan"></span> موتور آماده به کار`;
            statusPill.className = 'badge-neon badge-neon-cyan';
        }
    }

    // 2. Stats
    if (data.stats) {
        const totalCrawled = document.getElementById('stat-total-crawled');
        const newSaved = document.getElementById('stat-new-saved');
        const skipped = document.getElementById('stat-skipped');
        const totalDb = document.getElementById('stat-total-db');

        if (totalCrawled) totalCrawled.innerText = toPersianDigits(data.stats.total_crawled || 0);
        if (newSaved) newSaved.innerText = toPersianDigits(data.stats.new_saved || 0);
        if (skipped) skipped.innerText = toPersianDigits(data.stats.duplicates_skipped || 0);
        if (totalDb) totalDb.innerText = toPersianDigits(data.stats.total_in_db || 0);
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

// Global copy phone utility
window.copyToClipboard = function(text, event) {
    if (event) event.stopPropagation();
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
        showToast(`شماره تماس ${text} کپی شد`, 'info');
    }).catch(() => {
        showToast('خطا در کپی شماره', 'error');
    });
};

document.addEventListener('DOMContentLoaded', initCrawler);
