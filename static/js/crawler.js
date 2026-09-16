// SAGHF CRAWLER LIVE CONSOLE & STREAMING CONTROLLER

let crawlerPollInterval = null;
let liveItemsPollInterval = null;
let wasRunning = false;

function escapeHTML(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function sanitizeUrl(url) {
    if (!url || typeof url !== 'string') return '';
    const trimmed = url.trim();
    if (trimmed.startsWith('http://') || trimmed.startsWith('https://') || trimmed.startsWith('/')) {
        return trimmed;
    }
    return '';
}

function setBtnReady(btn) {
    if (!btn) return;
    btn.disabled = false;
    btn.replaceChildren();
    const iconSpan = document.createElement('span');
    iconSpan.textContent = '⚡';
    btn.appendChild(iconSpan);
    btn.appendChild(document.createTextNode(' شروع کراولینگ'));
}

function setBtnLoading(btn) {
    if (!btn) return;
    btn.disabled = true;
    btn.replaceChildren();
    const dot = document.createElement('span');
    dot.className = 'neon-pulse-dot cyan';
    btn.appendChild(dot);
    btn.appendChild(document.createTextNode(' در حال استخراج و تحلیل...'));
}

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
            setBtnLoading(btn);

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
                    setBtnReady(btn);
                }
            } catch (err) {
                showToast('خطا در برقراری ارتباط با سرویس کراولر', 'error');
                setBtnReady(btn);
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
                    const makeEmptyDiv = (msg) => {
                        const d = document.createElement('div');
                        d.style.cssText = 'grid-column: 1 / -1; text-align: center; color: #64748b; padding: 2.5rem;';
                        d.textContent = msg;
                        return d;
                    };
                    if (saleCont) saleCont.replaceChildren(makeEmptyDiv('داده‌های فروش پاک‌سازی شدند.'));
                    if (rentCont) rentCont.replaceChildren(makeEmptyDiv('داده‌های رهن و اجاره پاک‌سازی شدند.'));
                    
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
            setBtnReady(btn);
            showToast('عملیات کراولینگ به پایان رسید. تمامی آگهی‌های جدید به‌صورت زنده به پنل‌ها افزوده شدند.', 'success');
        } else if (!data.is_running && btn && btn.disabled) {
            setBtnReady(btn);
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
        container.replaceChildren();
    }

    const card = document.createElement('div');
    card.id = `prop-card-${p.id}`;
    card.className = 'glass-card live-card-pulse';
    card.style.padding = '1.15rem';
    card.style.border = `1px solid ${isSale ? 'rgba(0, 242, 254, 0.25)' : 'rgba(245, 158, 11, 0.25)'}`;
    card.style.display = 'flex';
    card.style.flexDirection = 'column';
    card.style.justifyContent = 'space-between';
    card.style.transition = 'all 0.3s';

    const topSection = document.createElement('div');

    // 1. Header
    const header = document.createElement('div');
    header.style.display = 'flex';
    header.style.alignItems = 'center';
    header.style.justifyContent = 'space-between';
    header.style.marginBottom = '0.6rem';

    const metaLeft = document.createElement('div');
    metaLeft.style.display = 'flex';
    metaLeft.style.alignItems = 'center';
    metaLeft.style.gap = '0.4rem';

    const sourceBadge = document.createElement('span');
    sourceBadge.className = `badge-neon ${p.source === 'divar' ? 'badge-neon-cyan' : 'badge-neon-emerald'}`;
    sourceBadge.style.fontSize = '0.72rem';
    sourceBadge.textContent = p.source === 'divar' ? 'دیوار' : 'شیپور';

    const distSpan = document.createElement('span');
    distSpan.style.fontSize = '0.75rem';
    distSpan.style.color = '#94a3b8';
    distSpan.textContent = `📍 ${p.district || 'تهران'}`;

    const scoreBadge = document.createElement('span');
    scoreBadge.className = 'badge-neon badge-neon-purple';
    scoreBadge.style.fontSize = '0.7rem';
    scoreBadge.textContent = `امتیاز: ${toPersianDigits(p.score || 85)}`;

    const newBadge = document.createElement('span');
    newBadge.className = 'badge-neon badge-neon-emerald';
    newBadge.style.fontSize = '0.68rem';
    newBadge.style.animation = 'pulse 1.5s infinite';
    newBadge.textContent = 'جدید ⚡';

    metaLeft.appendChild(sourceBadge);
    metaLeft.appendChild(distSpan);
    metaLeft.appendChild(scoreBadge);
    metaLeft.appendChild(newBadge);
    header.appendChild(metaLeft);

    const badgeColor = isSale ? 'badge-neon-cyan' : 'badge-neon-amber';
    if (p.source_url) {
        const topAdLink = document.createElement('a');
        topAdLink.href = sanitizeUrl(p.source_url);
        topAdLink.target = '_blank';
        topAdLink.rel = 'noopener noreferrer';
        topAdLink.className = `badge-neon ${badgeColor}`;
        topAdLink.style.textDecoration = 'none';
        topAdLink.style.fontSize = '0.75rem';
        topAdLink.style.fontWeight = '700';
        topAdLink.textContent = '🔗 لینک آگهی';
        const linkWrap = document.createElement('div');
        linkWrap.appendChild(topAdLink);
        header.appendChild(linkWrap);
    }
    topSection.appendChild(header);

    // 2. Title
    const titleH4 = document.createElement('h4');
    titleH4.style.fontSize = '1rem';
    titleH4.style.fontWeight = '700';
    titleH4.style.margin = '0 0 0.6rem 0';
    titleH4.style.lineHeight = '1.4';

    const titleLink = document.createElement('a');
    titleLink.href = `/properties/${encodeURIComponent(p.id)}`;
    titleLink.style.color = '#f8fafc';
    titleLink.style.textDecoration = 'none';
    titleLink.textContent = p.title || 'بدون عنوان';
    titleH4.appendChild(titleLink);
    topSection.appendChild(titleH4);

    // 3. Specs Bar
    const specsBar = document.createElement('div');
    specsBar.style.display = 'flex';
    specsBar.style.gap = '0.75rem';
    specsBar.style.fontSize = '0.82rem';
    specsBar.style.color = '#cbd5e1';
    specsBar.style.marginBottom = '0.6rem';
    specsBar.style.background = 'rgba(0,0,0,0.25)';
    specsBar.style.padding = '0.4rem 0.65rem';
    specsBar.style.borderRadius = '8px';

    const specArea = document.createElement('span');
    specArea.textContent = `📐 ${toPersianDigits(p.area || 0)} متر`;
    const specRooms = document.createElement('span');
    specRooms.textContent = `🛏️ ${toPersianDigits(p.rooms || 1)} خواب`;
    const specFloor = document.createElement('span');
    specFloor.textContent = `🏢 طبقه ${toPersianDigits(p.floor || 1)}${p.total_floors ? ' از ' + toPersianDigits(p.total_floors) : ''}`;
    const specYear = document.createElement('span');
    specYear.textContent = `🏗️ ساخت ${toPersianDigits(p.build_year || 1401)}`;

    specsBar.appendChild(specArea);
    specsBar.appendChild(specRooms);
    specsBar.appendChild(specFloor);
    specsBar.appendChild(specYear);
    topSection.appendChild(specsBar);

    // 4. Amenities Chips
    const amenWrap = document.createElement('div');
    amenWrap.style.display = 'flex';
    amenWrap.style.gap = '0.35rem';
    amenWrap.style.flexWrap = 'wrap';
    amenWrap.style.marginBottom = '0.65rem';
    amenWrap.style.fontSize = '0.72rem';

    const amElevator = document.createElement('span');
    amElevator.className = `badge-neon ${p.has_elevator ? 'badge-neon-emerald' : 'badge-neon-gray'}`;
    amElevator.textContent = `آسانسور ${p.has_elevator ? '✓' : '✕'}`;

    const amParking = document.createElement('span');
    amParking.className = `badge-neon ${p.has_parking ? 'badge-neon-emerald' : 'badge-neon-gray'}`;
    amParking.textContent = `پارکینگ ${p.has_parking ? '✓' : '✕'}`;

    const amWarehouse = document.createElement('span');
    amWarehouse.className = `badge-neon ${p.has_warehouse ? 'badge-neon-emerald' : 'badge-neon-gray'}`;
    amWarehouse.textContent = `انباری ${p.has_warehouse ? '✓' : '✕'}`;

    amenWrap.appendChild(amElevator);
    amenWrap.appendChild(amParking);
    amenWrap.appendChild(amWarehouse);

    if (p.has_balcony) {
        const amBalcony = document.createElement('span');
        amBalcony.className = 'badge-neon badge-neon-cyan';
        amBalcony.textContent = 'بالکن ✓';
        amenWrap.appendChild(amBalcony);
    }
    topSection.appendChild(amenWrap);

    // 5. Contact Option Box
    const phone = p.owner?.phone_number || '';
    const contactBox = document.createElement('div');
    contactBox.className = 'contact-option-box';
    contactBox.style.marginTop = '0.65rem';
    contactBox.style.marginBottom = '0.65rem';
    contactBox.style.borderRadius = '10px';
    contactBox.style.padding = '0.55rem 0.75rem';
    contactBox.style.boxShadow = '0 4px 15px rgba(0,0,0,0.2)';

    const contactHeader = document.createElement('div');
    contactHeader.style.display = 'flex';
    contactHeader.style.alignItems = 'center';
    contactHeader.style.justifyContent = 'space-between';
    contactHeader.style.marginBottom = '0.4rem';
    contactHeader.style.paddingBottom = '0.35rem';
    contactHeader.style.borderBottom = '1px solid rgba(255,255,255,0.06)';

    const contactLabel = document.createElement('span');
    contactLabel.style.fontSize = '0.76rem';
    contactLabel.style.fontWeight = '700';
    contactLabel.style.color = '#cbd5e1';
    contactLabel.style.display = 'flex';
    contactLabel.style.alignItems = 'center';
    contactLabel.style.gap = '0.35rem';
    contactLabel.textContent = '📞 گزینه تماس مستقیم با آگهی‌دهنده:';

    const statusBadge = document.createElement('span');
    statusBadge.style.fontSize = '0.65rem';
    statusBadge.style.padding = '0.1rem 0.4rem';

    contactHeader.appendChild(contactLabel);
    contactHeader.appendChild(statusBadge);
    contactBox.appendChild(contactHeader);

    const contactActions = document.createElement('div');
    contactActions.style.display = 'flex';
    contactActions.style.alignItems = 'center';
    contactActions.style.justifyContent = 'space-between';
    contactActions.style.gap = '0.5rem';
    contactActions.style.flexWrap = 'wrap';

    if (phone && phone.startsWith('09')) {
        contactBox.style.background = 'rgba(16, 185, 129, 0.1)';
        contactBox.style.border = '1px solid rgba(16, 185, 129, 0.35)';

        statusBadge.className = 'badge-neon badge-neon-emerald';
        statusBadge.textContent = '✓ استخراج شده';

        const phoneLink = document.createElement('a');
        phoneLink.href = `tel:${encodeURIComponent(phone)}`;
        phoneLink.style.textDecoration = 'none';
        phoneLink.style.display = 'inline-flex';
        phoneLink.style.alignItems = 'center';
        phoneLink.style.gap = '0.4rem';
        phoneLink.style.background = 'rgba(16, 185, 129, 0.2)';
        phoneLink.style.border = '1px solid rgba(16, 185, 129, 0.4)';
        phoneLink.style.padding = '0.3rem 0.65rem';
        phoneLink.style.borderRadius = '8px';
        phoneLink.style.color = '#10b981';
        phoneLink.style.fontWeight = '800';
        phoneLink.style.fontSize = '0.95rem';
        phoneLink.style.letterSpacing = '1.5px';
        phoneLink.style.direction = 'ltr';
        phoneLink.textContent = `📲 ${phone}`;
        contactActions.appendChild(phoneLink);

        const btnRow = document.createElement('div');
        btnRow.style.display = 'flex';
        btnRow.style.gap = '0.35rem';
        btnRow.style.alignItems = 'center';

        const callBtn = document.createElement('a');
        callBtn.href = `tel:${encodeURIComponent(phone)}`;
        callBtn.className = 'btn-neon-emerald';
        callBtn.style.padding = '0.28rem 0.65rem';
        callBtn.style.fontSize = '0.74rem';
        callBtn.style.textDecoration = 'none';
        callBtn.style.fontWeight = '700';
        callBtn.textContent = 'تماس فوری';

        const copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'glass-btn';
        copyBtn.style.padding = '0.28rem 0.5rem';
        copyBtn.style.fontSize = '0.74rem';
        copyBtn.style.color = '#10b981';
        copyBtn.title = 'کپی شماره';
        copyBtn.textContent = '📋';
        copyBtn.addEventListener('click', (e) => copyToClipboard(phone, e));

        const messengerBtn = document.createElement('button');
        messengerBtn.type = 'button';
        messengerBtn.className = 'glass-btn';
        messengerBtn.style.padding = '0.28rem 0.55rem';
        messengerBtn.style.fontSize = '0.74rem';
        messengerBtn.style.color = '#38bdf8';
        messengerBtn.title = 'استعلام وضعیت در ۵ پیام‌رسان';
        messengerBtn.textContent = '💬';
        messengerBtn.addEventListener('click', () => {
            if (typeof openMessengerModal === 'function') openMessengerModal(p.id);
        });

        const editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.className = 'glass-btn';
        editBtn.style.padding = '0.28rem 0.5rem';
        editBtn.style.fontSize = '0.74rem';
        editBtn.style.color = '#94a3b8';
        editBtn.title = 'ویرایش شماره';
        editBtn.textContent = '✏️';
        editBtn.addEventListener('click', () => {
            if (typeof promptSavePhone === 'function') {
                promptSavePhone(p.id, phone, p.owner?.full_name || '');
            }
        });

        btnRow.appendChild(callBtn);
        btnRow.appendChild(copyBtn);
        btnRow.appendChild(messengerBtn);
        btnRow.appendChild(editBtn);
        contactActions.appendChild(btnRow);
    } else {
        contactBox.style.background = 'rgba(0, 242, 254, 0.07)';
        contactBox.style.border = '1px solid rgba(0, 242, 254, 0.25)';

        statusBadge.className = 'badge-neon badge-neon-amber';
        statusBadge.textContent = '🔒 نیاز به استخراج';

        const extractBtn = document.createElement('button');
        extractBtn.type = 'button';
        extractBtn.className = 'btn-neon-cyan';
        extractBtn.style.flex = '1';
        extractBtn.style.minWidth = '130px';
        extractBtn.style.justifyContent = 'center';
        extractBtn.style.padding = '0.35rem 0.55rem';
        extractBtn.style.fontSize = '0.75rem';
        extractBtn.style.fontWeight = '700';
        extractBtn.style.cursor = 'pointer';
        extractBtn.title = 'استخراج خودکار شماره واقعی با توکن نشست دیوار';
        extractBtn.textContent = '⚡ استخراج خودکار شماره';
        extractBtn.addEventListener('click', () => {
            if (typeof fetchDivarPhoneDirect === 'function') {
                fetchDivarPhoneDirect(p.id);
            }
        });

        const manualBtn = document.createElement('button');
        manualBtn.type = 'button';
        manualBtn.className = 'glass-btn';
        manualBtn.style.padding = '0.35rem 0.6rem';
        manualBtn.style.fontSize = '0.75rem';
        manualBtn.style.color = '#10b981';
        manualBtn.style.borderColor = 'rgba(16, 185, 129, 0.3)';
        manualBtn.title = 'ثبت دستی شماره تلفن';
        manualBtn.textContent = '✏️ ثبت شماره';
        manualBtn.addEventListener('click', () => {
            if (typeof promptSavePhone === 'function') {
                promptSavePhone(p.id, '', p.owner?.full_name || '');
            }
        });

        contactActions.appendChild(extractBtn);
        contactActions.appendChild(manualBtn);

        if (p.source_url) {
            const divarLink = document.createElement('a');
            divarLink.href = sanitizeUrl(p.source_url);
            divarLink.target = '_blank';
            divarLink.rel = 'noopener noreferrer';
            divarLink.className = 'glass-btn';
            divarLink.style.padding = '0.35rem 0.6rem';
            divarLink.style.fontSize = '0.75rem';
            divarLink.style.color = '#00f2fe';
            divarLink.style.textDecoration = 'none';
            divarLink.style.borderColor = 'rgba(0, 242, 254, 0.3)';
            divarLink.title = 'مشاهده اطلاعات تماس در دیوار';
            divarLink.textContent = '🌐 دیوار';
            contactActions.appendChild(divarLink);
        }
    }
    contactBox.appendChild(contactActions);
    topSection.appendChild(contactBox);

    // 6. Price Display
    const priceBox = document.createElement('div');
    priceBox.style.display = 'flex';
    priceBox.style.justifyContent = 'space-between';
    priceBox.style.alignItems = 'baseline';
    priceBox.style.marginBottom = '0.75rem';

    if (isSale) {
        const lbl = document.createElement('span');
        lbl.style.fontSize = '0.8rem';
        lbl.style.color = '#94a3b8';
        lbl.textContent = 'قیمت فروش:';

        const val = document.createElement('span');
        val.style.fontSize = '1.15rem';
        val.style.fontWeight = '800';
        val.style.color = '#00f2fe';
        val.textContent = formatToman(p.total_price);

        priceBox.appendChild(lbl);
        priceBox.appendChild(val);
    } else {
        const depositCol = document.createElement('div');
        const depLbl = document.createElement('div');
        depLbl.style.fontSize = '0.75rem';
        depLbl.style.color = '#94a3b8';
        depLbl.textContent = 'ودیعه (رهن):';
        const depVal = document.createElement('div');
        depVal.style.fontSize = '1.1rem';
        depVal.style.fontWeight = '800';
        depVal.style.color = '#f59e0b';
        depVal.textContent = formatToman(p.deposit);
        depositCol.appendChild(depLbl);
        depositCol.appendChild(depVal);
        priceBox.appendChild(depositCol);

        if (p.monthly_rent > 0) {
            const rentCol = document.createElement('div');
            rentCol.style.textAlign = 'left';
            const rentLbl = document.createElement('div');
            rentLbl.style.fontSize = '0.75rem';
            rentLbl.style.color = '#94a3b8';
            rentLbl.textContent = 'اجاره ماهانه:';
            const rentVal = document.createElement('div');
            rentVal.style.fontSize = '1rem';
            rentVal.style.fontWeight = '800';
            rentVal.style.color = '#10b981';
            rentVal.textContent = formatToman(p.monthly_rent);
            rentCol.appendChild(rentLbl);
            rentCol.appendChild(rentVal);
            priceBox.appendChild(rentCol);
        }
    }
    topSection.appendChild(priceBox);

    // 7. Images Gallery
    if (Array.isArray(p.images) && p.images.length > 0) {
        const galleryWrap = document.createElement('div');
        galleryWrap.style.marginBottom = '0.75rem';

        const galLbl = document.createElement('div');
        galLbl.style.fontSize = '0.75rem';
        galLbl.style.color = '#94a3b8';
        galLbl.style.marginBottom = '0.35rem';
        galLbl.textContent = `📷 عکس‌های واقعی (${toPersianDigits(p.images.length)} تصویر):`;
        galleryWrap.appendChild(galLbl);

        const thumbsRow = document.createElement('div');
        thumbsRow.style.display = 'flex';
        thumbsRow.style.gap = '0.4rem';
        thumbsRow.style.overflowX = 'auto';
        thumbsRow.style.paddingBottom = '0.25rem';

        p.images.slice(0, 4).forEach(imgUrl => {
            const safeImg = sanitizeUrl(imgUrl);
            if (!safeImg) return;
            const thumbBox = document.createElement('div');
            thumbBox.style.flexShrink = '0';
            thumbBox.style.cursor = 'pointer';
            thumbBox.title = 'مشاهده در گالری تمام‌صفحه';
            thumbBox.onclick = () => {
                if (typeof openPhotoGallery === 'function') {
                    openPhotoGallery(p.id, p.images, p.title, p.file_code);
                }
            };

            const img = document.createElement('img');
            img.src = safeImg;
            img.referrerPolicy = 'no-referrer';
            img.loading = 'lazy';
            img.onerror = function() { this.onerror = null; this.src = '/static/placeholder.png'; };
            img.alt = 'ملک';
            img.style.width = '60px';
            img.style.height = '50px';
            img.style.objectFit = 'cover';
            img.style.borderRadius = '6px';
            img.style.border = '1px solid rgba(255,255,255,0.15)';
            img.style.transition = 'transform 0.2s';
            img.onmouseover = function() { this.style.transform = 'scale(1.08)'; };
            img.onmouseout = function() { this.style.transform = 'scale(1)'; };

            thumbBox.appendChild(img);
            thumbsRow.appendChild(thumbBox);
        });

        galleryWrap.appendChild(thumbsRow);
        topSection.appendChild(galleryWrap);
    }

    // 8. Description Accordion
    const details = document.createElement('details');
    details.style.background = 'rgba(0,0,0,0.2)';
    details.style.borderRadius = '8px';
    details.style.padding = '0.5rem 0.75rem';
    details.style.marginBottom = '0.75rem';
    details.style.fontSize = '0.8rem';
    details.style.color = '#cbd5e1';
    details.style.border = '1px solid rgba(255,255,255,0.05)';

    const summary = document.createElement('summary');
    summary.style.cursor = 'pointer';
    summary.style.fontWeight = '700';
    summary.style.color = '#94a3b8';
    summary.style.outline = 'none';
    summary.textContent = '📄 مشاهده متن کامل آگهی';

    const descBody = document.createElement('div');
    descBody.style.marginTop = '0.5rem';
    descBody.style.lineHeight = '1.6';
    descBody.style.whiteSpace = 'pre-line';
    descBody.style.color = '#e2e8f0';
    descBody.style.fontSize = '0.82rem';
    descBody.style.maxHeight = '160px';
    descBody.style.overflowY = 'auto';
    descBody.style.paddingRight = '0.25rem';
    descBody.textContent = p.description || 'توضیحات تکمیلی در صفحه اصلی آگهی درج شده است.';

    details.appendChild(summary);
    details.appendChild(descBody);
    topSection.appendChild(details);

    card.appendChild(topSection);

    // 9. Action Footer
    const footer = document.createElement('div');
    footer.style.display = 'flex';
    footer.style.gap = '0.5rem';
    footer.style.borderTop = '1px solid rgba(255,255,255,0.08)';
    footer.style.paddingTop = '0.75rem';
    footer.style.marginTop = '0.5rem';

    const dossierLink = document.createElement('a');
    dossierLink.href = `/properties/${encodeURIComponent(p.id)}`;
    dossierLink.className = isSale ? 'btn-neon-cyan' : 'glass-btn';
    dossierLink.style.flex = '1';
    dossierLink.style.justifyContent = 'center';
    dossierLink.style.padding = '0.4rem 0.6rem';
    dossierLink.style.fontSize = '0.82rem';
    if (!isSale) {
        dossierLink.style.borderColor = 'rgba(245, 158, 11, 0.4)';
        dossierLink.style.color = '#f59e0b';
    }
    dossierLink.textContent = '⚡ پرونده ملک';
    footer.appendChild(dossierLink);

    // AGENTS.md rule 2: Clickable direct ad link with exact text "لینک آگهی"
    if (p.source_url) {
        const adLink = document.createElement('a');
        adLink.href = sanitizeUrl(p.source_url);
        adLink.target = '_blank';
        adLink.rel = 'noopener noreferrer';
        adLink.className = 'glass-btn';
        adLink.style.padding = '0.4rem 0.6rem';
        adLink.style.fontSize = '0.82rem';
        adLink.style.color = isSale ? '#00f2fe' : '#f59e0b';
        adLink.style.textDecoration = 'none';
        adLink.textContent = 'لینک آگهی';
        footer.appendChild(adLink);
    }

    const verifyForm = document.createElement('form');
    verifyForm.action = `/properties/${encodeURIComponent(p.id)}/verify`;
    verifyForm.method = 'POST';
    verifyForm.style.display = 'inline';

    const csrfInput = document.createElement('input');
    csrfInput.type = 'hidden';
    csrfInput.name = 'csrf_token';
    csrfInput.value = typeof getCsrfToken === 'function' ? getCsrfToken() : '';
    verifyForm.appendChild(csrfInput);

    const verifyBtn = document.createElement('button');
    verifyBtn.type = 'submit';
    verifyBtn.className = 'btn-neon-emerald';
    verifyBtn.style.padding = '0.4rem 0.6rem';
    verifyBtn.style.fontSize = '0.82rem';
    verifyBtn.title = 'تأیید فایل';
    verifyBtn.textContent = '✓';

    verifyForm.appendChild(verifyBtn);
    footer.appendChild(verifyForm);

    card.appendChild(footer);

    // Prepend to top of container with smooth animation
    container.insertBefore(card, container.firstChild);
    showToast(`⚡ فایل جدید استخراج شد: ${(p.title || '').slice(0, 30)}...`, 'info');
}

function updateCrawlerUI(data) {
    // 1. Status Indicator
    const statusPill = document.getElementById('crawler-status-pill');
    if (statusPill) {
        statusPill.replaceChildren();
        const dot = document.createElement('span');
        if (data.is_running) {
            dot.className = 'neon-pulse-dot emerald';
            statusPill.className = 'badge-neon badge-neon-emerald';
            statusPill.appendChild(dot);
            statusPill.appendChild(document.createTextNode(' در حال استخراج و اعتبارسنجی زنده'));
        } else {
            dot.className = 'neon-pulse-dot cyan';
            statusPill.className = 'badge-neon badge-neon-cyan';
            statusPill.appendChild(dot);
            statusPill.appendChild(document.createTextNode(' موتور آماده به کار'));
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
        terminal.replaceChildren();
        data.recent_logs.forEach(log => {
            let color = '#a7f3d0';
            if (log.level === 'error') color = '#f87171';
            if (log.level === 'success') color = '#34d399';

            const line = document.createElement('div');
            line.className = 'terminal-line';
            line.style.color = color;

            const timeSpan = document.createElement('span');
            timeSpan.className = 'terminal-time';
            timeSpan.textContent = `[${log.time || ''}] `;

            const msgText = document.createTextNode(log.message || '');

            line.appendChild(timeSpan);
            line.appendChild(msgText);
            terminal.appendChild(line);
        });
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
