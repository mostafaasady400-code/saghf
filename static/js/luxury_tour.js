// ===================================================
// SAGHF LUXURY REAL ESTATE - ARCHITECTURAL SCROLL TOUR
// Powered by UI/UX Pro Max Design Intelligence
// ===================================================

(function() {
    const zones = [
        { id: 'living', name: 'سالن پذیرایی پانوراما', icon: '🏰', range: [0, 0.26] },
        { id: 'terrace', name: 'تراس و استخر بی‌نهایت', icon: '🏊', range: [0.26, 0.52] },
        { id: 'kitchen', name: 'آشپزخانه مدرن و لانژ', icon: '🍳', range: [0.52, 0.78] },
        { id: 'bedroom', name: 'سوئیت رویال مستر', icon: '🛏️', range: [0.78, 1.0] }
    ];

    let currentZoneId = 'living';
    let isManualOverride = false;
    let overrideTimeout = null;

    function initLuxuryTour() {
        const slides = document.querySelectorAll('.luxury-bg-slide');
        if (!slides || slides.length === 0) return;

        // Zone buttons click handler
        const zoneBtns = document.querySelectorAll('.mansion-zone-btn');
        zoneBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const targetZone = btn.getAttribute('data-zone');
                if (targetZone) {
                    setZone(targetZone, true);
                }
            });
        });

        // Optimized scroll listener with requestAnimationFrame
        let ticking = false;
        window.addEventListener('scroll', () => {
            if (!ticking) {
                window.requestAnimationFrame(() => {
                    handleScroll();
                    ticking = false;
                });
                ticking = true;
            }
        }, { passive: true });

        // Initial setup
        setZone('living', false);
    }

    function handleScroll() {
        if (isManualOverride) return;

        const totalScroll = document.documentElement.scrollHeight - window.innerHeight;
        if (totalScroll <= 0) return;

        const scrollRatio = Math.min(Math.max(window.scrollY / totalScroll, 0), 1);

        // Find active zone based on scroll ratio
        for (const zone of zones) {
            if (scrollRatio >= zone.range[0] && scrollRatio <= zone.range[1]) {
                if (zone.id !== currentZoneId) {
                    setZone(zone.id, false);
                }
                break;
            }
        }

        // Apply subtle parallax translation to active slide (UI/UX Pro Max standard)
        const activeSlide = document.querySelector('.luxury-bg-slide.active');
        if (activeSlide) {
            const parallaxY = (scrollRatio * 35) - 15;
            activeSlide.style.transform = `scale(1) translateY(${-parallaxY}px) translateZ(0)`;
        }
    }

    function setZone(zoneId, isManual) {
        currentZoneId = zoneId;

        // Update slides
        const slides = document.querySelectorAll('.luxury-bg-slide');
        slides.forEach(slide => {
            if (slide.getAttribute('data-zone') === zoneId) {
                slide.classList.add('active');
            } else {
                slide.classList.remove('active');
            }
        });

        // Update navigator buttons
        const zoneBtns = document.querySelectorAll('.mansion-zone-btn');
        zoneBtns.forEach(btn => {
            if (btn.getAttribute('data-zone') === zoneId) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        // Update text pill
        const titleEl = document.getElementById('mansion-nav-title');
        const activeZone = zones.find(z => z.id === zoneId);
        if (titleEl && activeZone) {
            titleEl.replaceChildren();
            const iconSpan = document.createElement('span');
            iconSpan.textContent = activeZone.icon;
            const spaceText = document.createTextNode(' ');
            const nameSpan = document.createElement('span');
            nameSpan.textContent = activeZone.name;
            titleEl.appendChild(iconSpan);
            titleEl.appendChild(spaceText);
            titleEl.appendChild(nameSpan);
        }

        if (isManual) {
            isManualOverride = true;
            if (overrideTimeout) clearTimeout(overrideTimeout);
            // Resume scroll detection after 6 seconds of inactivity
            overrideTimeout = setTimeout(() => {
                isManualOverride = false;
            }, 6000);
        }
    }

    document.addEventListener('DOMContentLoaded', initLuxuryTour);
})();
