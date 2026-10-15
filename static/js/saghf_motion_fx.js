/**
 * SAGHF ANTIGRAVITY 3D MOTION & LUXURY VISUAL SUITE
 * مجهز به:
 * ۱. موتور ذرات کوانتومی پس‌زمینه (Cosmic Stardust & Connection Laser Filaments)
 * ۲. هاله نور محیطی نشانگر ماوس (Ambient Torchlight Glare)
 * ۳. فیزیک سه‌بعدی ژیروسکوپی با بازتاب هولوگرافیک (Card 3D Physics & Specular Sheen)
 * ۴. دکمه‌های تعاملی مغناطیسی (Magnetic Buttons)
 * ۵. انیمیشن صعودی اعداد (Animated Smooth Number Counters)
 * ۶. نمایش ۳ بعدی المان‌ها در اسکرول (3D Staggered Scroll Reveal)
 */

(function() {
    'use strict';

    // =========================================================================
    // ۱. موتور ذرات کوانتومی پس‌زمینه (Cosmic Quantum Canvas)
    // =========================================================================
    function initQuantumParticles() {
        if (window.innerWidth <= 768) return; // بهینه‌سازی برای موبایل

        let canvas = document.getElementById('saghf-ambient-particles');
        if (!canvas) {
            canvas = document.createElement('canvas');
            canvas.id = 'saghf-ambient-particles';
            document.body.prepend(canvas);
        }

        const ctx = canvas.getContext('2d');
        let width = canvas.width = window.innerWidth;
        let height = canvas.height = window.innerHeight;

        const particleCount = 45;
        const particles = [];
        const mouse = { x: -1000, y: -1000, radius: 160 };

        // پالت رنگ‌های لوکس سقف: فیروزه‌ای نئونی، طلایی متالیک، بنفش نئونی
        const colors = [
            'rgba(0, 242, 254, ',   // نئون فیروزه‌ای
            'rgba(212, 175, 55, ',   // طلایی لوکس
            'rgba(192, 132, 252, '   // نئون بنفش
        ];

        class Particle {
            constructor() {
                this.x = Math.random() * width;
                this.y = Math.random() * height;
                this.vx = (Math.random() - 0.5) * 0.45;
                this.vy = (Math.random() - 0.5) * 0.45;
                this.radius = Math.random() * 2 + 0.8;
                this.colorBase = colors[Math.floor(Math.random() * colors.length)];
                this.alpha = Math.random() * 0.6 + 0.2;
                this.pulseSpeed = Math.random() * 0.02 + 0.008;
            }

            update() {
                this.x += this.vx;
                this.y += this.vy;

                // بازگشت در لبه‌های پنجره
                if (this.x < 0) this.x = width;
                if (this.x > width) this.x = 0;
                if (this.y < 0) this.y = height;
                if (this.y > height) this.y = 0;

                // پالس درخشندگی
                this.alpha += Math.sin(Date.now() * this.pulseSpeed) * 0.008;
                this.alpha = Math.max(0.15, Math.min(0.75, this.alpha));

                // تعامل ماوس: گرانش ملایم به سمت ماوس
                const dx = mouse.x - this.x;
                const dy = mouse.y - this.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < mouse.radius) {
                    const force = (mouse.radius - dist) / mouse.radius;
                    const angle = Math.atan2(dy, dx);
                    this.x -= Math.cos(angle) * force * 1.5;
                    this.y -= Math.sin(angle) * force * 1.5;
                }
            }

            draw() {
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
                ctx.fillStyle = this.colorBase + this.alpha + ')';
                ctx.shadowBlur = 10;
                ctx.shadowColor = this.colorBase + '0.8)';
                ctx.fill();
                ctx.shadowBlur = 0;
            }
        }

        for (let i = 0; i < particleCount; i++) {
            particles.push(new Particle());
        }

        // حلقه رسم زنده
        let animId;
        function render() {
            ctx.clearRect(0, 0, width, height);

            // اتصالات لیزری ظریف بین ذرات نزدیک
            for (let i = 0; i < particles.length; i++) {
                for (let j = i + 1; j < particles.length; j++) {
                    const dx = particles[i].x - particles[j].x;
                    const dy = particles[i].y - particles[j].y;
                    const dist = Math.sqrt(dx * dx + dy * dy);

                    if (dist < 110) {
                        const opacity = (1 - dist / 110) * 0.18;
                        ctx.beginPath();
                        ctx.moveTo(particles[i].x, particles[i].y);
                        ctx.lineTo(particles[j].x, particles[j].y);
                        ctx.strokeStyle = `rgba(0, 242, 254, ${opacity})`;
                        ctx.lineWidth = 0.75;
                        ctx.stroke();
                    }
                }
            }

            particles.forEach(p => {
                p.update();
                p.draw();
            });

            animId = requestAnimationFrame(render);
        }

        render();

        window.addEventListener('resize', () => {
            width = canvas.width = window.innerWidth;
            height = canvas.height = window.innerHeight;
        });

        window.addEventListener('mousemove', (e) => {
            mouse.x = e.clientX;
            mouse.y = e.clientY;
        });

        // بهینه‌سازی عدم مصرف پردازنده هنگام تغییر تب
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                cancelAnimationFrame(animId);
            } else {
                render();
            }
        });
    }

    // =========================================================================
    // ۲. حذف کامل هاله نور ماوس طبق دستور صوتی کاربر
    // =========================================================================
    function initCursorGlow() {
        // حذف هرگونه المان هاله نور قبلی ماوس
        const existingGlow = document.getElementById('ambient-cursor-glow');
        if (existingGlow) {
            existingGlow.remove();
        }
    }

    // =========================================================================
    // ۳. فیزیک ملایم و ارگونومیک کارت‌ها (حذف تلاطم ۳ بعدی شدید و تکان‌های غیرطبیعی)
    // =========================================================================
    function init3DCardTilt() {
        // موشن‌های شدید ژیروسکوپی ۳ بعدی طبق درخواست کاربر با ترنزیشن‌های نرم و پایدار CSS جایگزین شدند
        // تا کلیک روی تصاویر و آگهی‌ها به آسانی و بدون تکان خوردن کارت انجام شود.
        const selector = '.antigravity-card-3d, .property-card, .divar-style-card, .kpi-card, .luxury-dept-card, .glass-panel';
        document.querySelectorAll(selector).forEach(card => {
            if (card.__tiltReady) return;
            card.__tiltReady = true;
            // پاکسازی هرگونه ترنسفورم تلاطم قبلی
            card.style.transform = '';
        });
    }

    // =========================================================================
    // ۴. دکمه‌های پایدار (حذف حرکت چپ و راست مغناطیسی طبق دستور صوتی کاربر)
    // =========================================================================
    function initMagneticButtons() {
        // دکمه‌ها نباید زیر دست کاربر به چپ و راست منحرف شوند؛ حفظ پایداری کامل
        const magneticSelector = '.magnetic-btn, .btn-primary, .btn-neon-cyan, .btn-neon-emerald, .nav-ai-assistant-btn, .glass-btn';
        document.querySelectorAll(magneticSelector).forEach(btn => {
            btn.style.transform = '';
        });
    }

    // =========================================================================
    // ۵. شمارنده انیمیشنی اعداد (Animated Number Counters)
    // =========================================================================
    function initAnimatedCounters() {
        const counters = document.querySelectorAll('.animate-counter, .stagger-counter');
        if (!counters.length) return;

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting && !entry.target.__counted) {
                    entry.target.__counted = true;
                    const targetNum = parseInt(entry.target.getAttribute('data-target') || entry.target.innerText.replace(/[^\d]/g, ''), 10);
                    if (isNaN(targetNum)) return;

                    let start = 0;
                    const duration = 1200;
                    const startTime = performance.now();

                    function updateCount(currentTime) {
                        const elapsed = currentTime - startTime;
                        const progress = Math.min(elapsed / duration, 1);
                        // Easing out cubic
                        const easeOut = 1 - Math.pow(1 - progress, 3);
                        const current = Math.floor(easeOut * targetNum);

                        // تبدیل به ارقام فارسی
                        entry.target.innerText = current.toLocaleString('fa-IR');

                        if (progress < 1) {
                            requestAnimationFrame(updateCount);
                        } else {
                            entry.target.innerText = targetNum.toLocaleString('fa-IR');
                        }
                    }
                    requestAnimationFrame(updateCount);
                }
            });
        }, { threshold: 0.2 });

        counters.forEach(c => observer.observe(c));
    }

    // =========================================================================
    // ۶. نمایش ۳ بعدی المان‌ها در اسکرول (Scroll Reveal 3D)
    // =========================================================================
    function initScrollReveal() {
        const revealElements = document.querySelectorAll('.stagger-reveal, .stagger-in');
        if (!revealElements.length) return;

        const observer = new IntersectionObserver((entries) => {
            entries.forEach((entry, index) => {
                if (entry.isIntersecting) {
                    setTimeout(() => {
                        entry.target.classList.add('revealed');
                    }, index * 80);
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.1 });

        revealElements.forEach(el => observer.observe(el));
    }

    // =========================================================================
    // راه‌اندازی سراسری سیستم موشن
    // =========================================================================
    function initMotionSuite() {
        initQuantumParticles();
        initCursorGlow();
        init3DCardTilt();
        initMagneticButtons();
        initAnimatedCounters();
        initScrollReveal();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initMotionSuite);
    } else {
        initMotionSuite();
    }
})();
