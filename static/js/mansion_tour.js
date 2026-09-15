// ===================================================
// SAGHF 3D LUXURY MANSION SCROLL-PINNED TOUR ENGINE
// High-performance 60fps spatial navigation
// ===================================================

(function () {
    const tourData = [
        {
            id: 'living',
            badge: '🏰 بخش ۱ از ۴: سالن پذیرایی پانوراما',
            title: 'سالن پذیرایی باشکوه با چشم‌انداز ۳۶۰ درجه',
            desc: 'طراحی نئوکلاسیک با پنجره‌های قدی ضد انعکاس، سنگ‌های اسلب بوک‌مچ ایتالیایی و سیستم روشنایی هوشمند داینامیک.',
            specs: ['📐 ۲۵۰ متر مربع', '🪟 نورگیر جنوبی', '✨ ارتفاع سقف ۴.۲ متر', '🛋️ مبلمان ایتالیایی'],
            frameIndex: 0,
            range: [0, 0.25]
        },
        {
            id: 'kitchen',
            badge: '🍳 بخش ۲ از ۴: آشپزخانه مدرن و لانژ',
            title: 'آشپزخانه جزیره‌ای فول فرنیش Miele',
            desc: 'صفحات سنگ کوارتز طبیعی، کابینت‌های آنتی‌فینگر مدرن، لانژ پذیرایی و مطبخ مجزا (Dirty Kitchen).',
            specs: ['🍳 فرنیش برند آلمانی', '☕ کافی‌بار اختصاصی', '🧊 یخچال ساید توکار', '🍷 واین کولر لوکس'],
            frameIndex: 1,
            range: [0.25, 0.50]
        },
        {
            id: 'bedroom',
            badge: '🛏️ بخش ۳ از ۴: سوئیت مستر رویال',
            title: 'اتاق خواب مستر کینگ با بالکن خصوصی',
            desc: 'پوشش چوب گردوی طبیعی، کلوزت روم شیشه‌ای با نورپردازی هوشمند سنسوری، و جکوزی دونفره مشرف به شهر.',
            specs: ['🛏️ سوئیت ۷۵ متری', '👗 واک‌این کلوزت وسیع', '🛁 حمام مستر سنگ اونیکس', '🌅 تراس خصوصی'],
            frameIndex: 2,
            range: [0.50, 0.75]
        },
        {
            id: 'terrace',
            badge: '🏊 بخش ۴ از ۴: روف‌گاردن و استخر اسکای',
            title: 'استخر بی‌نهایت در بام عمارت با دید ابدی',
            desc: 'روف‌گاردن چهارفصل با پوشش گیاهی ژاپنی، فایرپیت اختصاصی، سونای خشک و جکوزی پانوراما زیر آسمان پایتخت.',
            specs: ['🏊 استخر اینفینیتی گرم', '🔥 باربیکیو و فایرپیت', '🌿 سیستم آبیاری هوشمند', '🌃 ویو ۳۶۰ درجه شهر'],
            frameIndex: 3,
            range: [0.75, 1.0]
        }
    ];

    let currentZoneIndex = -1;
    let tourContainer = null;
    let frames = [];
    let progressFill = null;
    let roomBadge = null;
    let tourTitle = null;
    let tourDesc = null;
    let tourSpecs = null;

    function init3DTour() {
        tourContainer = document.getElementById('mansion-3d-tour-container');
        if (!tourContainer) return;

        frames = document.querySelectorAll('.tour-scene-frame');
        progressFill = document.getElementById('tourProgressFill');
        roomBadge = document.getElementById('tourRoomBadge');
        tourTitle = document.getElementById('tourRoomTitle');
        tourDesc = document.getElementById('tourRoomDesc');
        tourSpecs = document.getElementById('tourRoomSpecs');

        // Skip to listings button handler
        const skipBtn = document.getElementById('tourSkipToListings');
        if (skipBtn) {
            skipBtn.addEventListener('click', function (e) {
                e.preventDefault();
                const listingsSection = document.getElementById('properties-catalog-section');
                if (listingsSection) {
                    listingsSection.scrollIntoView({ behavior: 'smooth' });
                } else {
                    const rect = tourContainer.getBoundingClientRect();
                    const targetY = window.scrollY + rect.bottom - 40;
                    window.scrollTo({ top: targetY, behavior: 'smooth' });
                }
            });
        }

        // Zone navigation click triggers
        document.querySelectorAll('.mansion-zone-btn').forEach((btn, idx) => {
            btn.addEventListener('click', () => {
                const targetRatio = (idx * 0.25) + 0.05;
                const containerTop = tourContainer.offsetTop;
                const scrollableDistance = tourContainer.offsetHeight - window.innerHeight;
                const targetScroll = containerTop + (targetRatio * scrollableDistance);
                window.scrollTo({ top: targetScroll, behavior: 'smooth' });
            });
        });

        // Optimized passive scroll listener
        let isTicking = false;
        window.addEventListener('scroll', () => {
            if (!isTicking) {
                window.requestAnimationFrame(() => {
                    updateTourOnScroll();
                    isTicking = false;
                });
                isTicking = true;
            }
        }, { passive: true });

        // Initial trigger
        updateTourOnScroll();
    }

    function updateTourOnScroll() {
        if (!tourContainer) return;

        const rect = tourContainer.getBoundingClientRect();
        const containerHeight = tourContainer.offsetHeight;
        const windowHeight = window.innerHeight;
        const scrollDistance = containerHeight - windowHeight;

        if (scrollDistance <= 0) return;

        // Calculate progress within the pinned container: 0.0 at top, 1.0 when bottom hits viewport
        const scrolled = -rect.top;
        const progress = Math.min(Math.max(scrolled / scrollDistance, 0), 1);

        // Update progress bar fill
        if (progressFill) {
            progressFill.style.width = (progress * 100) + '%';
        }

        // Identify current zone
        let activeZone = tourData[0];
        let activeIndex = 0;
        for (let i = 0; i < tourData.length; i++) {
            if (progress >= tourData[i].range[0] && progress <= tourData[i].range[1]) {
                activeZone = tourData[i];
                activeIndex = i;
                break;
            }
        }
        if (progress >= 0.98) {
            activeZone = tourData[tourData.length - 1];
            activeIndex = tourData.length - 1;
        }

        // 3D camera translation & dolly zoom calculation
        const localZoneProgress = (progress - activeZone.range[0]) / (activeZone.range[1] - activeZone.range[0] || 1);
        const clampedLocal = Math.min(Math.max(localZoneProgress, 0), 1);

        // Smooth spatial 3D transformation
        frames.forEach((frame, idx) => {
            if (idx === activeZone.frameIndex) {
                frame.classList.add('active');
                // 3D perspective camera dolly in and gentle pan
                const scale = 1 + (clampedLocal * 0.07);
                const translateY = (clampedLocal * -20);
                const rotateY = (clampedLocal * 2) - 1;
                frame.style.transform = `scale(${scale}) translateY(${translateY}px) rotateY(${rotateY}deg) translateZ(0)`;
            } else {
                frame.classList.remove('active');
                frame.style.transform = `scale(1.08) translateZ(0)`;
            }
        });

        // Update HUD text if zone changed
        if (activeIndex !== currentZoneIndex) {
            currentZoneIndex = activeIndex;
            updateHUD(activeZone);

            // Update floating spatial navigator buttons if present
            document.querySelectorAll('.mansion-zone-btn').forEach(btn => {
                if (btn.getAttribute('data-zone') === activeZone.id) {
                    btn.classList.add('active');
                } else {
                    btn.classList.remove('active');
                }
            });
            const spatialTitle = document.getElementById('mansion-nav-title');
            if (spatialTitle) {
                spatialTitle.innerHTML = `<span>${activeZone.badge.split(' ')[0]}</span> <span>${activeZone.title.split(' ')[0]} ${activeZone.title.split(' ')[1] || ''}</span>`;
            }
        }
    }

    function updateHUD(zone) {
        if (!roomBadge || !tourTitle || !tourDesc || !tourSpecs) return;

        roomBadge.textContent = zone.badge;
        tourTitle.textContent = zone.title;
        tourDesc.textContent = zone.desc;

        // Render specs chips
        tourSpecs.innerHTML = zone.specs.map(s => `
            <div class="tour-hud-spec-chip">
                <span>${s}</span>
            </div>
        `).join('');

        const header = document.querySelector('.tour-hud-header');
        if (header) {
            header.style.opacity = '1';
            header.style.transform = 'translateY(0)';
        }
    }

    // Auto initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init3DTour);
    } else {
        init3DTour();
    }
})();
