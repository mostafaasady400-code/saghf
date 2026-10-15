// ===================================================
// SAGHF 3D LUXURY MANSION SCROLL-PINNED TOUR ENGINE
// High-performance 60fps spatial navigation & HUD
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
    let progressPercent = null;
    let roomBadge = null;
    let tourTitle = null;
    let tourDesc = null;
    let tourSpecs = null;

    function toPersianNum(num) {
        const persianDigits = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];
        return String(num).replace(/[0-9]/g, function (w) {
            return persianDigits[+w];
        });
    }

    function scrollToZone(idx) {
        if (!tourContainer) return;
        idx = Math.max(0, Math.min(tourData.length - 1, idx));
        const containerTop = tourContainer.getBoundingClientRect().top + window.scrollY;
        const scrollDistance = tourContainer.offsetHeight - window.innerHeight;
        const ratios = [0.02, 0.32, 0.62, 0.88];
        const targetScroll = containerTop + (ratios[idx] * scrollDistance);
        window.scrollTo({ top: targetScroll, behavior: 'smooth' });
    }

    function init3DTour() {
        tourContainer = document.getElementById('mansion-3d-tour-container');
        if (!tourContainer) return;

        frames = document.querySelectorAll('.tour-scene-frame');
        progressFill = document.getElementById('tourProgressFill');
        progressPercent = document.getElementById('tourProgressPercent');
        roomBadge = document.getElementById('tourRoomBadge');
        tourTitle = document.getElementById('tourRoomTitle');
        tourDesc = document.getElementById('tourRoomDesc');
        tourSpecs = document.getElementById('tourRoomSpecs');

        // Zone selection pill buttons
        document.querySelectorAll('.tour-zone-pill-btn').forEach(btn => {
            btn.addEventListener('click', function () {
                const idx = parseInt(this.getAttribute('data-zone-index'), 10);
                if (!isNaN(idx)) {
                    scrollToZone(idx);
                }
            });
        });

        // Previous / Next Room Buttons
        const prevBtn = document.getElementById('tourPrevBtn');
        const nextBtn = document.getElementById('tourNextBtn');

        if (prevBtn) {
            prevBtn.addEventListener('click', function () {
                const targetIdx = currentZoneIndex > 0 ? currentZoneIndex - 1 : 0;
                scrollToZone(targetIdx);
            });
        }

        if (nextBtn) {
            nextBtn.addEventListener('click', function () {
                if (currentZoneIndex < tourData.length - 1) {
                    scrollToZone(currentZoneIndex + 1);
                } else {
                    const catalog = document.getElementById('properties-catalog-section');
                    if (catalog) catalog.scrollIntoView({ behavior: 'smooth' });
                }
            });
        }

        // Keyboard arrow navigation when viewing tour
        window.addEventListener('keydown', function (e) {
            if (!tourContainer) return;
            const rect = tourContainer.getBoundingClientRect();
            const inTour = rect.top <= 50 && rect.bottom >= window.innerHeight - 50;
            if (!inTour) return;

            if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
                if (currentZoneIndex < tourData.length - 1) {
                    scrollToZone(currentZoneIndex + 1);
                }
            } else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
                if (currentZoneIndex > 0) {
                    scrollToZone(currentZoneIndex - 1);
                }
            }
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

        // Calculate progress within the pinned container: 0.0 at top, 1.0 when bottom reaches viewport
        const scrolled = -rect.top;
        const progress = Math.min(Math.max(scrolled / scrollDistance, 0), 1);

        // Update progress bar fill & percentage
        if (progressFill) {
            progressFill.style.width = (progress * 100) + '%';
        }
        if (progressPercent) {
            progressPercent.textContent = toPersianNum(Math.round(progress * 100)) + '٪';
        }

        // Identify current zone
        let activeZone = tourData[0];
        let activeIndex = 0;
        for (let i = 0; i < tourData.length; i++) {
            if (progress >= tourData[i].range[0] && progress < tourData[i].range[1]) {
                activeZone = tourData[i];
                activeIndex = i;
                break;
            }
        }
        if (progress >= 0.95) {
            activeZone = tourData[tourData.length - 1];
            activeIndex = tourData.length - 1;
        }

        // 3D camera translation & dolly zoom calculation
        const localZoneProgress = (progress - activeZone.range[0]) / (activeZone.range[1] - activeZone.range[0] || 1);
        const clampedLocal = Math.min(Math.max(localZoneProgress, 0), 1);

        // Smooth spatial 3D transformation with Antigravity depth
        let activeRotateY = 0;
        let activeRotateX = 0;
        frames.forEach((frame, idx) => {
            if (idx === activeZone.frameIndex) {
                frame.classList.add('active');
                // 3D perspective camera dolly in and gentle pan with smooth cubic ease
                const scale = 1 + (clampedLocal * 0.09);
                const translateY = (clampedLocal * -26);
                activeRotateY = (clampedLocal * 2.8) - 1.4;
                activeRotateX = (clampedLocal * 1.5);
                frame.style.transform = `perspective(1000px) scale(${scale}) translateY(${translateY}px) rotateY(${activeRotateY.toFixed(2)}deg) rotateX(${activeRotateX.toFixed(2)}deg) translateZ(0)`;
            } else {
                frame.classList.remove('active');
                frame.style.transform = `perspective(1000px) scale(1.08) translateZ(-40px)`;
            }
        });

        // Dynamic lighting & shadow transition on scene overlay
        const sceneOverlay = document.querySelector('.tour-scene-overlay');
        if (sceneOverlay) {
            const lightX = 50 + (activeRotateY * 14);
            const lightY = 35 + (activeRotateX * 10);
            sceneOverlay.style.background = `radial-gradient(circle at ${lightX.toFixed(1)}% ${lightY.toFixed(1)}%, rgba(6, 9, 19, 0.12) 0%, rgba(6, 9, 19, 0.62) 65%, rgba(6, 9, 19, 0.96) 100%)`;
        }

        // Promotional Value Messages with Modern Fade Transition
        const phrase1 = document.getElementById('tourPhrase1');
        const phrase2 = document.getElementById('tourPhrase2');
        const phrase3 = document.getElementById('tourPhrase3');
        if (phrase1 && phrase2 && phrase3) {
            let activePhrase = 1;
            if (progress >= 0.66) {
                activePhrase = 3;
            } else if (progress >= 0.33) {
                activePhrase = 2;
            }
            phrase1.classList.toggle('active', activePhrase === 1);
            phrase2.classList.toggle('active', activePhrase === 2);
            phrase3.classList.toggle('active', activePhrase === 3);
        }

        // Update HUD text if zone changed
        if (activeIndex !== currentZoneIndex) {
            currentZoneIndex = activeIndex;
            updateHUD(activeZone);

            // Update zone pill buttons
            document.querySelectorAll('.tour-zone-pill-btn').forEach((btn, idx) => {
                if (idx === activeIndex) {
                    btn.classList.add('active');
                } else {
                    btn.classList.remove('active');
                }
            });
        }
    }

    function updateHUD(zone) {
        if (!roomBadge || !tourTitle || !tourDesc || !tourSpecs) return;

        roomBadge.textContent = zone.badge;
        tourTitle.textContent = zone.title;
        tourDesc.textContent = zone.desc;

        // Render specs chips
        tourSpecs.replaceChildren();
        if (Array.isArray(zone.specs)) {
            zone.specs.forEach(s => {
                const chip = document.createElement('div');
                chip.className = 'tour-hud-spec-chip';
                const span = document.createElement('span');
                span.textContent = s;
                chip.appendChild(span);
                tourSpecs.appendChild(chip);
            });
        }

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
