// SAGHF REAL ESTATE CRM - CORE FRONTEND UTILITIES

// CSRF Protection Utilities
function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content') || '';
    const input = document.querySelector('input[name="csrf_token"]');
    if (input) return input.value || '';
    return '';
}

// Global AJAX / Fetch Interceptor to automatically attach X-CSRFToken to POST/PUT/DELETE/PATCH
(function() {
    const originalFetch = window.fetch;
    window.fetch = function(input, init = {}) {
        const method = (init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
        if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
            const token = getCsrfToken();
            if (token) {
                if (init.headers instanceof Headers) {
                    if (!init.headers.has('X-CSRFToken')) {
                        init.headers.set('X-CSRFToken', token);
                    }
                } else if (Array.isArray(init.headers)) {
                    const exists = init.headers.some(([k]) => k.toLowerCase() === 'x-csrftoken');
                    if (!exists) {
                        init.headers.push(['X-CSRFToken', token]);
                    }
                } else {
                    init.headers = {
                        ...(init.headers || {}),
                        'X-CSRFToken': token
                    };
                }
            }
        }
        return originalFetch.call(this, input, init);
    };
})();

function showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    let icon = 'ℹ️';
    if (type === 'success') icon = '✅';
    if (type === 'error') icon = '⚠️';

    const iconSpan = document.createElement('span');
    iconSpan.textContent = icon;
    const msgDiv = document.createElement('div');
    msgDiv.textContent = message;
    toast.appendChild(iconSpan);
    toast.appendChild(msgDiv);
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(-30px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('active');
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('active');
        modal.style.display = 'none';
        document.body.style.overflow = 'auto';
    }
}

// Close modal when clicking outside box
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('glass-modal-overlay')) {
        e.target.classList.remove('active');
        document.body.style.overflow = 'auto';
    }
});

// ===================================================
// FULL-SCREEN LIGHTBOX PHOTO GALLERY & TELEGRAM INTEGRATION
// ===================================================
let _galleryPhotos = [];
let _galleryIndex = 0;
let _galleryPropId = null;
let _galleryFileCode = '';
let _galleryTitle = '';

function openGalleryFromCard(triggerEl) {
    if (!triggerEl) return;
    const card = triggerEl.closest('.compact-property-card') || triggerEl.closest('.property-card');
    if (!card) return;
    const propId = card.getAttribute('data-prop-id');
    const fileCode = card.getAttribute('data-file-code');
    const title = card.getAttribute('data-title');
    let images = [];
    try {
        const raw = card.getAttribute('data-images');
        images = JSON.parse(raw || '[]');
    } catch(e) {
        images = [];
    }
    openPhotoGallery(propId, images, title, fileCode);
}

function openPhotoGallery(propertyId, images, title, code) {
    if (typeof images === 'string') {
        try { images = JSON.parse(images); } catch(e) { images = []; }
    }
    _galleryPhotos = Array.isArray(images) && images.length > 0 ? images : ['/static/placeholder.png'];
    _galleryIndex = 0;
    _galleryPropId = propertyId;
    _galleryFileCode = code || '';
    _galleryTitle = title || 'تصاویر ملک';

    const modal = document.getElementById('saghfPhotoGalleryModal');
    if (!modal) return;

    // Update Header Info
    const codeEl = document.getElementById('galleryModalCode');
    const titleEl = document.getElementById('galleryModalTitle');
    const deepLinkEl = document.getElementById('galleryTgDeepLink');
    const sendBtn = document.getElementById('gallerySendTgBtn');

    if (codeEl) codeEl.textContent = `🔢 کد فایل: ${_galleryFileCode}`;
    if (titleEl) titleEl.textContent = _galleryTitle;
    if (deepLinkEl) deepLinkEl.href = `https://t.me/saghf_bot?start=code_${_galleryFileCode}`;
    
    if (sendBtn) {
        sendBtn.onclick = (e) => sendPropertyPhotosToTelegram(_galleryPropId, _galleryFileCode, e);
    }

    _updateGalleryView();
    _renderGalleryThumbnails();

    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';

    // Attach keyboard listener
    window.addEventListener('keydown', _handleGalleryKeydown);
}

function closePhotoGallery() {
    const modal = document.getElementById('saghfPhotoGalleryModal');
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = 'auto';
    }
    window.removeEventListener('keydown', _handleGalleryKeydown);
}

function navigateGallery(direction) {
    if (!_galleryPhotos || _galleryPhotos.length <= 1) return;
    _galleryIndex += direction;
    if (_galleryIndex < 0) _galleryIndex = _galleryPhotos.length - 1;
    if (_galleryIndex >= _galleryPhotos.length) _galleryIndex = 0;
    _updateGalleryView();
}

function _updateGalleryView() {
    const mainImg = document.getElementById('galleryMainImage');
    const counterEl = document.getElementById('galleryModalCounter');
    
    if (mainImg) {
        mainImg.style.opacity = '0.3';
        mainImg.style.transform = 'scale(0.98)';
        setTimeout(() => {
            mainImg.src = _galleryPhotos[_galleryIndex];
            mainImg.style.opacity = '1';
            mainImg.style.transform = 'scale(1)';
        }, 120);
    }

    if (counterEl) {
        counterEl.textContent = `تصویر ${_galleryIndex + 1} از ${_galleryPhotos.length}`;
    }

    // Highlight active thumbnail
    document.querySelectorAll('.gallery-thumb-item').forEach((item, idx) => {
        if (idx === _galleryIndex) {
            item.classList.add('active');
            item.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
        } else {
            item.classList.remove('active');
        }
    });
}

function _renderGalleryThumbnails() {
    const strip = document.getElementById('galleryThumbStrip');
    if (!strip) return;
    strip.replaceChildren();

    if (_galleryPhotos.length <= 1) {
        strip.style.display = 'none';
        return;
    }
    strip.style.display = 'flex';

    _galleryPhotos.forEach((imgUrl, idx) => {
        const thumb = document.createElement('div');
        thumb.className = `gallery-thumb-item ${idx === _galleryIndex ? 'active' : ''}`;
        thumb.onclick = () => {
            _galleryIndex = idx;
            _updateGalleryView();
        };

        const img = document.createElement('img');
        img.src = imgUrl;
        img.referrerPolicy = 'no-referrer';
        img.loading = 'lazy';
        img.onerror = function() { this.src = '/static/placeholder.png'; };

        thumb.appendChild(img);
        strip.appendChild(thumb);
    });
}

function _handleGalleryKeydown(e) {
    if (e.key === 'Escape') {
        closePhotoGallery();
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        navigateGallery(-1);
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        navigateGallery(1);
    }
}

// Interactive Fast Send Photos to Telegram
async function sendPropertyPhotosToTelegram(propertyId, fileCode, event) {
    if (event && event.stopPropagation) event.stopPropagation();

    const triggerBtn = event ? event.currentTarget : document.getElementById(`btn-tg-${propertyId}`);
    const originalText = triggerBtn ? triggerBtn.innerHTML : '';
    
    if (triggerBtn) {
        triggerBtn.disabled = true;
        triggerBtn.innerHTML = '<span>⏳</span> در حال ارسال...';
    }

    try {
        const response = await fetch('/api/telegram/send-property-photos', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                property_id: propertyId,
                file_code: fileCode
            })
        });

        const result = await response.json();

        if (result.success) {
            showToast(result.message || `آلبوم تصاویر فایل کد ${fileCode} با موفقیت به تلگرام ارسال شد.`, 'success');
            if (!result.channel_configured && result.deep_link) {
                // Open directly in Telegram for instant presentation
                window.open(result.deep_link, '_blank');
            }
            if (triggerBtn) {
                triggerBtn.innerHTML = '<span>✅</span> ارسال شد!';
            }
        } else {
            showToast(result.message || 'خطا در ارسال تصاویر به تلگرام', 'error');
            if (triggerBtn) triggerBtn.innerHTML = originalText;
        }
    } catch (err) {
        console.error('Error sending photos to Telegram:', err);
        showToast('خطا در ارتباط با سرور تلگرام', 'error');
        if (triggerBtn) triggerBtn.innerHTML = originalText;
    } finally {
        if (triggerBtn) {
            setTimeout(() => {
                triggerBtn.disabled = false;
                triggerBtn.innerHTML = originalText;
            }, 3000);
        }
    }
}

// -------------------------------------------------------------
// Interactive Contact Reveal Functions on Property Cards
// -------------------------------------------------------------
function revealCardPhone(propId, phone, event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const btn = document.getElementById(`btn-reveal-${propId}`);
    const box = document.getElementById(`revealed-phone-${propId}`);
    if (btn && box) {
        btn.style.display = 'none';
        box.style.display = 'flex';
    }
}

function copyCardPhone(phone, btnEl, event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    if (!phone) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(phone).then(() => {
            if (btnEl) {
                const orig = btnEl.textContent;
                btnEl.textContent = '✓';
                btnEl.style.color = '#34d399';
                setTimeout(() => {
                    btnEl.textContent = orig;
                    btnEl.style.color = '';
                }, 1500);
            }
        }).catch(err => {
            console.error('Clipboard write error:', err);
        });
    }
}

async function fetchAndRevealCardPhone(propId, event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const btn = document.getElementById(`btn-reveal-${propId}`);
    const box = document.getElementById(`revealed-phone-${propId}`);
    if (!btn || !box) return;

    const origText = btn.innerHTML;
    btn.innerHTML = '<span>⏳</span> <span>در حال استعلام...</span>';
    btn.disabled = true;

    try {
        const resp = await fetch(`/properties/${propId}/fetch-divar-phone`, { method: 'POST' });
        const res = await resp.json();
        const phone = res.phone || res.phone_number;
        if (res.success && phone) {
            btn.style.display = 'none';
            box.replaceChildren();

            const callLink = document.createElement('a');
            callLink.href = `tel:${phone}`;
            callLink.className = 'phone-call-anchor';
            callLink.title = 'تماس تلفنی مستقیم';

            const phoneIcon = document.createElement('span');
            phoneIcon.className = 'phone-icon';
            phoneIcon.textContent = '📞';

            const phoneDigits = document.createElement('span');
            phoneDigits.className = 'phone-num-text';
            phoneDigits.dir = 'ltr';
            phoneDigits.textContent = phone;

            callLink.appendChild(phoneIcon);
            callLink.appendChild(phoneDigits);

            const copyBtn = document.createElement('button');
            copyBtn.type = 'button';
            copyBtn.className = 'btn-copy-revealed-phone';
            copyBtn.title = 'کپی شماره';
            copyBtn.textContent = '📋 کپی';
            copyBtn.onclick = (e) => copyCardPhone(phone, copyBtn, e);

            box.appendChild(callLink);
            box.appendChild(copyBtn);
            box.style.display = 'flex';
        } else if (res.is_auth_needed) {
            btn.innerHTML = '<span>🔑</span> <span>نیاز به نشست دیوار</span>';
            btn.disabled = false;
            if (typeof openModal === 'function') {
                openModal('divarSessionModal');
            }
        } else {
            btn.innerHTML = '<span>🔒</span> <span>محفوظ در پرونده</span>';
            btn.style.opacity = '0.85';
            btn.onclick = (e) => openInAppAdModal(propId, e);
        }
    } catch (err) {
        console.error('Error fetching phone for card:', err);
        btn.innerHTML = origText;
        btn.disabled = false;
    }
}
