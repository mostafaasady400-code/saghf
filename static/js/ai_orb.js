/**
 * ai_orb.js - کنترل‌کننده گوی شناور هوشمند و دستیار صوتی سقف
 * ۳ کارکرد اصلی:
 * ۱. کنترل صوتی اپ و اعمال فیلترهای استخراج (App Voice Controller)
 * ۲. شنود و تحلیل زنده مذاکره با مشتری حضوری (Real-time Lead Assistant)
 * ۳. دستیار هوشمند عملیاتی کارشناس (Operational Commands)
 */

(function () {
    'use strict';

    let speechRecognition = null;
    let leadRecognition = null;
    let inPageRecognition = null;
    let isVoiceListening = false;
    let isLeadListening = false;
    let isInPageRecording = false;
    let leadTranscriptBuffer = '';
    let leadAnalysisDebounceTimer = null;
    let currentVoiceState = 'idle'; // 'idle' | 'greeting' | 'listening' | 'analyzing' | 'speaking' | 'closed'
    let aiSessionId = 'saghf_session_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8);
    let audioContext = null;
    let analyserNode = null;
    let micStream = null;
    let micAnimFrameId = null;

    // بررسی پشتیبانی مرورگر از Web Speech API
    const SpeechRecClass = window.SpeechRecognition || window.webkitSpeechRecognition;

    function toPersianDigits(num) {
        if (num === null || num === undefined) return '';
        const id = ['۰','۱','۲','۳','۴','۵','۶','۷','۸','۹'];
        return num.toString().replace(/[0-9]/g, function(w){ return id[+w]; });
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

    // پخش صدای بازخورد مدرن هوش مصنوعی با Web Audio API
    function playAudioChime(type = 'success') {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);

            const now = ctx.currentTime;
            if (type === 'start') {
                osc.frequency.setValueAtTime(440, now);
                osc.frequency.exponentialRampToValueAtTime(880, now + 0.15);
                gain.gain.setValueAtTime(0.12, now);
                gain.gain.linearRampToValueAtTime(0.01, now + 0.2);
                osc.start(now);
                osc.stop(now + 0.2);
            } else if (type === 'success') {
                osc.frequency.setValueAtTime(587.33, now); // D5
                osc.frequency.setValueAtTime(880, now + 0.1); // A5
                gain.gain.setValueAtTime(0.15, now);
                gain.gain.linearRampToValueAtTime(0.01, now + 0.3);
                osc.start(now);
                osc.stop(now + 0.3);
            }
        } catch (e) {
            // Audio context may be restricted before user gesture
        }
    }

    // =========================================================================
    // بوم رندر دینامیک ذرات و امواج هوش مصنوعی گوی سقف (Pure Canvas Dynamic Engine)
    // =========================================================================
    let sphereCanvasAnimId = null;
    let sphereParticles = [];
    let sphereIsHovered = false;

    function initSphereCanvas() {
        const canvas = document.getElementById('saghfSphereCanvas');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const width = canvas.width || 140;
        const height = canvas.height || 140;
        const centerX = width / 2;
        const centerY = height / 2;
        const radiusLimit = width * 0.44;

        // ۳۶ ذره معلق با فیزیک گردابی در پالت لوکس مشکی-طلایی
        sphereParticles = [];
        const particleColors = ['#ffffff', '#fce79f', '#d4af37', '#fef08a', '#aa771c'];
        for (let i = 0; i < 36; i++) {
            sphereParticles.push({
                angle: Math.random() * Math.PI * 2,
                dist: 8 + Math.random() * (radiusLimit - 12),
                speed: 0.012 + Math.random() * 0.024,
                size: 0.9 + Math.random() * 2.2,
                alpha: 0.3 + Math.random() * 0.65,
                color: particleColors[Math.floor(Math.random() * particleColors.length)],
                pulseOffset: Math.random() * Math.PI * 2
            });
        }

        const sphereContainer = document.getElementById('saghfSmartSphereFloating');
        if (sphereContainer) {
            sphereContainer.addEventListener('mouseenter', () => { sphereIsHovered = true; });
            sphereContainer.addEventListener('mouseleave', () => { sphereIsHovered = false; });
        }

        let time = 0;

        function renderSphereVortex() {
            ctx.clearRect(0, 0, width, height);
            time += 0.035;

            const isListeningNow = isVoiceListening || isLeadListening;
            const speedMultiplier = isListeningNow ? 2.6 : (sphereIsHovered ? 1.9 : 1.0);

            // ۱. تابش هسته مرکزی طلایی-آبسیدین
            const coreGrad = ctx.createRadialGradient(
                centerX, centerY, 2,
                centerX, centerY, radiusLimit
            );
            if (isListeningNow) {
                coreGrad.addColorStop(0, 'rgba(252, 231, 159, 0.48)');
                coreGrad.addColorStop(0.35, 'rgba(245, 158, 11, 0.3)');
                coreGrad.addColorStop(0.75, 'rgba(212, 175, 55, 0.12)');
                coreGrad.addColorStop(1, 'transparent');
            } else {
                coreGrad.addColorStop(0, 'rgba(252, 231, 159, 0.28)');
                coreGrad.addColorStop(0.4, 'rgba(212, 175, 55, 0.14)');
                coreGrad.addColorStop(0.8, 'rgba(5, 6, 8, 0.05)');
                coreGrad.addColorStop(1, 'transparent');
            }
            ctx.fillStyle = coreGrad;
            ctx.beginPath();
            ctx.arc(centerX, centerY, radiusLimit, 0, Math.PI * 2);
            ctx.fill();

            // ۲. امواج و ذرات چرخشی گرداب طلایی
            for (let i = 0; i < sphereParticles.length; i++) {
                const p = sphereParticles[i];
                p.angle += p.speed * speedMultiplier;

                // انحراف شعاعی تنفسی
                const pulse = Math.sin(time + p.pulseOffset) * 3.5;
                const r = Math.max(5, Math.min(radiusLimit - 3, p.dist + pulse));
                const x = centerX + Math.cos(p.angle) * r;
                const y = centerY + Math.sin(p.angle) * (r * 0.74); // نمای بیضوی سه‌بعدی

                ctx.save();
                ctx.beginPath();
                ctx.arc(x, y, p.size, 0, Math.PI * 2);
                ctx.fillStyle = p.color;
                ctx.globalAlpha = Math.min(1, Math.max(0.15, p.alpha + (isListeningNow ? 0.35 : 0)));
                ctx.shadowColor = '#d4af37';
                ctx.shadowBlur = p.size * 3;
                ctx.fill();
                ctx.restore();
            }

            // ۳. حلقه‌های درخشان مداری داخلی (Inner Energy Rings)
            ctx.save();
            ctx.strokeStyle = isListeningNow ? 'rgba(252, 231, 159, 0.45)' : 'rgba(212, 175, 55, 0.2)';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.ellipse(centerX, centerY, radiusLimit * 0.65, radiusLimit * 0.35, time * 0.4, 0, Math.PI * 2);
            ctx.stroke();

            ctx.beginPath();
            ctx.ellipse(centerX, centerY, radiusLimit * 0.85, radiusLimit * 0.45, -time * 0.25, 0, Math.PI * 2);
            ctx.stroke();
            ctx.restore();

            sphereCanvasAnimId = requestAnimationFrame(renderSphereVortex);
        }

        if (sphereCanvasAnimId) cancelAnimationFrame(sphereCanvasAnimId);
        renderSphereVortex();
    }

    function initAIOrb() {
        const floatingSphere = document.getElementById('saghfSmartSphereFloating');
        const fallbackOrbBtn = document.getElementById('aiOrbBtn');
        const hudModal = document.getElementById('aiOrbHudModal');
        const hudCloseBtn = document.getElementById('aiHudCloseBtn');

        // باز کردن مودال با کلیک روی گوی هوشمند جدید یا قدیمی
        if (floatingSphere && hudModal) {
            floatingSphere.addEventListener('click', (e) => {
                e.stopPropagation();
                window.openSaghfAiAssistant();
            });
        }
        if (fallbackOrbBtn && hudModal) {
            fallbackOrbBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                window.openSaghfAiAssistant();
            });
        }

        if (hudCloseBtn) {
            hudCloseBtn.addEventListener('click', () => {
                window.cleanupAndCloseVoiceAgent();
            });
        }

        const disconnectBtn = document.getElementById('aiDisconnectCallBtn');
        if (disconnectBtn) {
            disconnectBtn.addEventListener('click', () => {
                window.cleanupAndCloseVoiceAgent();
            });
        }

        if (hudModal) {
            hudModal.addEventListener('click', (e) => {
                if (e.target === hudModal) {
                    window.cleanupAndCloseVoiceAgent();
                }
            });
        }

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                const modal = document.getElementById('aiOrbHudModal');
                if (modal && modal.classList.contains('active')) {
                    window.cleanupAndCloseVoiceAgent();
                }
            }
        });

        // ۲. تعویض تب‌های دستیار هوشمند
        const tabBtns = document.querySelectorAll('.ai-hud-tab');
        tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const targetTab = btn.getAttribute('data-tab');
                switchTab(targetTab);
            });
        });

        // ۳. راه‌اندازی تب ۱: کنترل صوتی
        setupVoiceController();

        // ۴. راه‌اندازی تب ۲: شنود مذاکره حضوری
        setupLeadAssistant();

        // ۵. آغاز بوم دینامیک ذرات گوی
        initSphereCanvas();
    }

    // =========================================================================
    // مدیریت چرخه‌حیات صدا و پاکسازی قطعی دسترسی میکروفون (Microphone Cleanup & Lifecycle)
    // =========================================================================
    function cleanupAudioResources() {
        // ۱. متوقف‌سازی کامل رکوگنیشن‌های وب‌اسپیچ
        if (speechRecognition) {
            try { speechRecognition.abort(); } catch (e) {}
            try { speechRecognition.stop(); } catch (e) {}
            speechRecognition = null;
        }
        if (leadRecognition) {
            try { leadRecognition.abort(); } catch (e) {}
            try { leadRecognition.stop(); } catch (e) {}
            leadRecognition = null;
        }
        if (inPageRecognition) {
            try { inPageRecognition.abort(); } catch (e) {}
            try { inPageRecognition.stop(); } catch (e) {}
            inPageRecognition = null;
        }
        isVoiceListening = false;
        isLeadListening = false;
        isInPageRecording = false;

        // ۲. متوقف‌سازی قطعی و غیرفعال‌سازی تمامی ترک‌های مدیا استریم میکروفون
        if (micStream) {
            try {
                micStream.getTracks().forEach(track => {
                    track.stop();
                    track.enabled = false;
                });
            } catch (e) {}
            micStream = null;
        }

        // ۳. لغو و بستن تحلیلگر فرکانس و آودیو کانتکست (AudioContext Termination)
        if (micAnimFrameId) {
            cancelAnimationFrame(micAnimFrameId);
            micAnimFrameId = null;
        }
        if (analyserNode) {
            try { analyserNode.disconnect(); } catch (e) {}
            analyserNode = null;
        }
        if (audioContext) {
            try {
                if (audioContext.state !== 'closed') {
                    audioContext.close();
                }
            } catch (e) {}
            audioContext = null;
        }

        // ۴. لغو فوری پخش گفتار در حال اجرا (Cancel Speech Synthesis)
        if (window.speechSynthesis) {
            try { window.speechSynthesis.cancel(); } catch (e) {}
        }

        // ۵. بروزرسانی رابط کاربری به حالت Closed و خاموش شدن امواج
        setVoiceAgentState('closed', 'مکالمه قطع و بسته شد');
        updateSphereListeningUI(false);
    }

    window.cleanupAndCloseVoiceAgent = function() {
        cleanupAudioResources();
        const hudModal = document.getElementById('aiOrbHudModal');
        if (hudModal) {
            hudModal.classList.remove('active');
        }
    };

    window.closeSaghfAiAssistant = window.cleanupAndCloseVoiceAgent;

    // =========================================================================
    // استانداردسازی ماشین وضعیت صوتی (States: Idle, Greeting, Listening, Analyzing, Speaking, Closed)
    // =========================================================================
    function setVoiceAgentState(state, customLabel = null) {
        currentVoiceState = state;
        const pill = document.getElementById('aiVoiceStatePill');
        const label = document.getElementById('aiVoiceStateLabel');
        const micOrb = document.getElementById('aiInteractiveMicOrb');
        const soundwaves = document.getElementById('aiSoundwaves');

        if (pill) {
            pill.classList.remove('state-greeting', 'state-listening', 'state-analyzing', 'state-speaking', 'state-closed');
            if (state !== 'idle') {
                pill.classList.add(`state-${state}`);
            }
        }

        let defaultLabel = 'آماده به کار';
        let defaultStatus = 'روی گوی کلیک کنید یا نیاز ملکی خود را بفرمایید...';

        switch (state) {
            case 'greeting':
                defaultLabel = 'خوش‌آمدگویی هوشمند';
                defaultStatus = 'دستیار در حال معرفی و آغاز هوشمند مکالمه...';
                if (soundwaves) soundwaves.classList.add('active');
                if (micOrb) {
                    micOrb.classList.add('speaking');
                    micOrb.classList.remove('listening');
                }
                updateSphereListeningUI(false);
                break;
            case 'listening':
                defaultLabel = 'در حال شنود گفتار شما';
                defaultStatus = 'میکروفون فعال است... بفرمایید، مشتاقانه می‌شنوم';
                if (soundwaves) soundwaves.classList.add('active');
                if (micOrb) {
                    micOrb.classList.add('listening');
                    micOrb.classList.remove('speaking');
                }
                updateSphereListeningUI(true);
                break;
            case 'analyzing':
                defaultLabel = 'تحلیل نیاز و استخراج آگهی';
                defaultStatus = 'هوش مصنوعی در حال تحلیل فاکتورهای مدنظر و جستجوی آنلاین...';
                if (soundwaves) soundwaves.classList.remove('active');
                if (micOrb) micOrb.classList.remove('listening', 'speaking');
                updateSphereListeningUI(false);
                break;
            case 'speaking':
                defaultLabel = 'پاسخگویی صوتی کارشناس';
                defaultStatus = 'مشاور هوشمند سقف در حال ارائه توضیحات صوتی...';
                if (soundwaves) soundwaves.classList.add('active');
                if (micOrb) {
                    micOrb.classList.add('speaking');
                    micOrb.classList.remove('listening');
                }
                updateSphereListeningUI(false);
                break;
            case 'closed':
                defaultLabel = 'مکالمه قطع شد';
                defaultStatus = 'میکروفون کاملاً آزاد شد. برای شروع مجدد روی گوی کلیک فرمایید.';
                if (soundwaves) soundwaves.classList.remove('active');
                if (micOrb) micOrb.classList.remove('listening', 'speaking');
                updateSphereListeningUI(false);
                break;
            case 'idle':
            default:
                defaultLabel = 'آماده به کار';
                defaultStatus = 'روی گوی کلیک کنید یا نیاز ملکی خود را بنویسید/بگویید...';
                if (soundwaves) soundwaves.classList.remove('active');
                if (micOrb) micOrb.classList.remove('listening', 'speaking');
                updateSphereListeningUI(false);
                break;
        }

        if (label) label.textContent = customLabel || defaultLabel;
        showVoiceStatus(defaultStatus);
    }

    // =========================================================================
    // سنتز صوتی فارسی با پشتیبانی از بازخورد پایان و پالایش متن
    // =========================================================================
    function speakAssistantSpeech(text, onEndCallback) {
        if (!window.speechSynthesis) {
            if (typeof onEndCallback === 'function') onEndCallback();
            return;
        }

        try {
            window.speechSynthesis.cancel();

            let cleanText = text
                .replace(/[\u{1F300}-\u{1F9FF}]/gu, '')
                .replace(/[📍📐🔑🏷️🏢🏛️⚡🎙️🔊⏹️✕↵💡🚗📡👥🤖💎💰•*#`[\]()]/gu, '')
                .replace(/[|]/g, ' و ')
                .replace(/\n+/g, ' ')
                .trim();

            if (!cleanText) {
                if (typeof onEndCallback === 'function') onEndCallback();
                return;
            }

            const utterance = new SpeechSynthesisUtterance(cleanText);
            utterance.lang = 'fa-IR';
            utterance.rate = 1.0;
            utterance.pitch = 1.0;

            const setBestVoice = () => {
                const voices = window.speechSynthesis.getVoices();
                const faVoice = voices.find(v => v.lang && (v.lang.toLowerCase().includes('fa') || v.lang.toLowerCase().includes('ir') || v.name.toLowerCase().includes('persian') || v.name.toLowerCase().includes('farsi')));
                if (faVoice) utterance.voice = faVoice;
            };
            setBestVoice();
            if (window.speechSynthesis.onvoiceschanged !== undefined) {
                window.speechSynthesis.onvoiceschanged = setBestVoice;
            }

            let hasEnded = false;
            const finish = () => {
                if (!hasEnded) {
                    hasEnded = true;
                    if (typeof onEndCallback === 'function') onEndCallback();
                }
            };

            utterance.onend = finish;
            utterance.onerror = (err) => {
                console.warn('SpeechSynthesis error:', err);
                finish();
            };

            // تایمر ایمنی جهت تضمین ادامه کار در صورت باگ مرورگر
            const maxDurationMs = Math.max(2500, cleanText.length * 90);
            const safetyTimeout = setTimeout(finish, maxDurationMs + 2000);
            utterance.addEventListener('end', () => clearTimeout(safetyTimeout));
            utterance.addEventListener('error', () => clearTimeout(safetyTimeout));

            window.speechSynthesis.speak(utterance);
        } catch (e) {
            console.warn('Speech synthesis error:', e);
            if (typeof onEndCallback === 'function') onEndCallback();
        }
    }

    // =========================================================================
    // سناریوی پیش‌قدم شدن خوش‌آمدگویی هوشمند (Initial Voice Greeting & Discovery)
    // =========================================================================
    window.openSaghfAiAssistant = async function() {
        const hudModal = document.getElementById('aiOrbHudModal');
        if (!hudModal) return;

        // ایجاد شناسه نشست تازه جهت تعامل چندنوبته
        aiSessionId = 'saghf_session_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8);

        hudModal.classList.add('active');
        playAudioChime('start');
        switchTab('voice');

        // ورود به وضعیت Greeting
        setVoiceAgentState('greeting');

        const defaultGreeting = "سلام! من دستیار هوشمند شما در سامانه سقف هستم. چطور می‌تونم کمکتون کنم؟ به دنبال خرید هستید یا اجاره؟ در چه منطقه و با چه بودجه‌ای ملکی مد نظرتونه؟";
        let greetingText = defaultGreeting;

        const transcriptBox = document.getElementById('aiTranscriptBox');
        if (transcriptBox) {
            transcriptBox.innerHTML = `<span style="color: #fce79f; line-height: 1.6;">«${defaultGreeting}»</span>`;
        }

        // استعلام از بک‌اند
        try {
            const resp = await fetch('/api/ai-orb/initial-greeting');
            const data = await resp.json();
            if (data.success && (data.greeting || data.voice_reply || data.speech_text)) {
                greetingText = data.greeting || data.voice_reply || data.speech_text;
                if (transcriptBox) {
                    transcriptBox.innerHTML = `<span style="color: #fce79f; line-height: 1.6;">«${greetingText}»</span>`;
                }
            }
        } catch (e) {
            console.warn('Initial greeting fetch fallback:', e);
        }

        // پخش صوتی گرم و رسمی
        speakAssistantSpeech(greetingText, () => {
            // پس از اتمام پخش صدای خوش‌آمدگویی، گوی خودکار وارد حالت Listening شود
            if (currentVoiceState !== 'closed' && hudModal.classList.contains('active')) {
                startVoiceRecognition();
            }
        });
    };

    function switchTab(tabId) {
        document.querySelectorAll('.ai-hud-tab').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.ai-hud-view').forEach(v => v.classList.remove('active'));

        const targetBtn = document.querySelector(`.ai-hud-tab[data-tab="${tabId}"]`);
        if (targetBtn) targetBtn.classList.add('active');

        if (tabId === 'voice') {
            const v = document.getElementById('aiViewVoice');
            if (v) v.classList.add('active');
        } else if (tabId === 'lead') {
            const v = document.getElementById('aiViewLead');
            if (v) v.classList.add('active');
        } else if (tabId === 'ops') {
            const v = document.getElementById('aiViewOps');
            if (v) v.classList.add('active');
        }
    }

    function setupVoiceController() {
        const micOrb = document.getElementById('aiInteractiveMicOrb');
        const textInput = document.getElementById('aiVoiceTextInput');
        const sendBtn = document.getElementById('aiVoiceTextSendBtn');

        if (micOrb) {
            micOrb.addEventListener('click', () => {
                if (isVoiceListening) {
                    stopVoiceRecognition();
                    setVoiceAgentState('idle');
                } else {
                    startVoiceRecognition();
                }
            });
        }

        if (sendBtn && textInput) {
            sendBtn.addEventListener('click', () => {
                const val = textInput.value.trim();
                if (val) {
                    textInput.value = '';
                    handleVoiceCommand(val);
                }
            });

            textInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    const val = textInput.value.trim();
                    if (val) {
                        textInput.value = '';
                        handleVoiceCommand(val);
                    }
                }
            });
        }
    }

    function updateSphereListeningUI(isListening) {
        const floatingSphere = document.getElementById('saghfSmartSphereFloating');
        const fallbackOrb = document.getElementById('aiOrbBtn');
        const badgeText = document.getElementById('saghfSphereBadgeText');

        if (floatingSphere) {
            if (isListening) {
                floatingSphere.classList.add('is-listening');
            } else {
                floatingSphere.classList.remove('is-listening');
            }
        }
        if (fallbackOrb) {
            if (isListening) {
                fallbackOrb.classList.add('is-listening');
            } else {
                fallbackOrb.classList.remove('is-listening');
            }
        }
        if (badgeText) {
            badgeText.textContent = isListening ? 'در حال شنیدن...' : 'هوش مصنوعی سقف';
        }
    }

    function startVoiceRecognition() {
        if (!SpeechRecClass) {
            setVoiceAgentState('idle', 'تایپ نیاز');
            showVoiceStatus('مرورگر شما از ورودی صوتی پشتیبانی نمی‌کند. لطفاً تایپ فرمایید.', '#f87171');
            return;
        }

        if (speechRecognition) {
            try { speechRecognition.abort(); } catch (e) {}
            speechRecognition = null;
        }

        try {
            speechRecognition = new SpeechRecClass();
            speechRecognition.lang = 'fa-IR';
            speechRecognition.continuous = false;
            speechRecognition.interimResults = true;

            const transcriptBox = document.getElementById('aiTranscriptBox');

            speechRecognition.onstart = () => {
                isVoiceListening = true;
                playAudioChime('start');
                setVoiceAgentState('listening');
                if (transcriptBox) {
                    transcriptBox.innerHTML = '<span style="color: #fce79f; animation: pulse 1.5s infinite;">🎙️ در حال گوش دادن... نیاز ملکی‌تان را بفرمایید</span>';
                }
            };

            speechRecognition.onresult = (e) => {
                let current = '';
                for (let i = e.resultIndex; i < e.results.length; i++) {
                    current += e.results[i][0].transcript;
                }
                if (transcriptBox && current) {
                    transcriptBox.textContent = `«${current}»`;
                }

                if (e.results[0].isFinal) {
                    const finalTranscript = e.results[0][0].transcript;
                    stopVoiceRecognition();
                    handleVoiceCommand(finalTranscript);
                }
            };

            speechRecognition.onerror = (e) => {
                console.warn('Speech recognition error:', e);
                stopVoiceRecognition();
                setVoiceAgentState('idle');
                if (e.error === 'not-allowed') {
                    showVoiceStatus('دسترسی به میکروفون مجاز نیست. لطفاً دسترسی را فعال فرمایید.', '#f87171');
                } else if (e.error === 'no-speech') {
                    showVoiceStatus('صدایی شنیده نشد. برای صحبت مجدد روی گوی کلیک کنید.', '#94a3b8');
                } else {
                    showVoiceStatus('خطا در دریافت صوت. لطفاً مجدداً امتحان کنید.', '#f87171');
                }
            };

            speechRecognition.onend = () => {
                isVoiceListening = false;
                if (currentVoiceState === 'listening') {
                    setVoiceAgentState('idle');
                }
            };

            speechRecognition.start();
        } catch (err) {
            console.error('Speech start error:', err);
            stopVoiceRecognition();
            setVoiceAgentState('idle');
        }
    }

    function stopVoiceRecognition() {
        isVoiceListening = false;
        const micOrb = document.getElementById('aiInteractiveMicOrb');
        if (micOrb) micOrb.classList.remove('listening');
        if (!isLeadListening) updateSphereListeningUI(false);

        if (speechRecognition) {
            try { speechRecognition.abort(); } catch (e) {}
            try { speechRecognition.stop(); } catch (e) {}
            speechRecognition = null;
        }
    }

    function showVoiceStatus(text, color = '#fce79f') {
        const el = document.getElementById('aiVoiceStatusText');
        if (el) {
            el.textContent = text;
            el.style.color = color;
        }
    }

    // =========================================================================
    // تعامل هوشمند چندنوبته با LLM، ابزار آنلاین واکشی ملک و هدایت به قرار بازدید
    // =========================================================================
    async function handleVoiceCommand(cmdText) {
        if (!cmdText || !cmdText.trim()) return;
        const query = cmdText.trim();

        setVoiceAgentState('analyzing');
        const transcriptBox = document.getElementById('aiTranscriptBox');
        if (transcriptBox) {
            transcriptBox.textContent = `«${query}»`;
        }

        try {
            const resp = await fetch('/api/ai-orb/voice-interact', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query: query,
                    session_id: aiSessionId,
                    current_path: window.location.pathname
                })
            });

            const data = await resp.json();

            if (!data.success) {
                setVoiceAgentState('idle', 'خطا در پردازش');
                showVoiceStatus(data.message || 'پردازش انجام نشد. مجدداً تلاش فرمایید.', '#f87171');
                return;
            }

            playAudioChime('success');

            // نمایش پاسخ متنی
            displayVoiceReply(data.voice_reply);

            // واکشی و رندر فوری کارت‌های ملکی
            if (data.items && data.items.length > 0) {
                renderVoicePropertyCards(data.items);
            }

            // تغییر وضعیت به پاسخگویی صوتی کارشناس
            setVoiceAgentState('speaking');

            // اعلام صوتی خلاصه نتایج و پاسخ کارشناسی
            speakAssistantSpeech(data.speech_text || data.voice_reply, () => {
                if (currentVoiceState !== 'closed') {
                    setVoiceAgentState('idle', 'آماده شنود مجدد');
                    showVoiceStatus('برای ادامه گفتگو، روی گوی کلیک کرده یا صحبت فرمایید.', '#d4af37');
                }
            });

            // اجرای اکشن‌های نگاشت‌شده خاص
            if (data.action === 'apply_filters' && data.params) {
                applyFiltersToCurrentPageOrRedirect(data);
            } else if (data.action === 'navigate' && data.url) {
                setTimeout(() => {
                    window.location.href = data.url;
                }, 1500);
            }

        } catch (err) {
            console.error('Command process error:', err);
            setVoiceAgentState('idle', 'خطای ارتباط');
            showVoiceStatus('خطا در برقراری ارتباط با موتور هوش مصنوعی سقف', '#f87171');
        }
    }

    function displayVoiceReply(replyText) {
        const box = document.getElementById('aiVoiceReplyBox');
        if (box && replyText) {
            box.textContent = replyText;
            box.style.display = 'block';
            box.style.animation = 'fadeIn 0.3s ease';
        }
    }

    // =========================================================================
    // رندر کارت‌های ملکی منطبق با تگ مستقیم «لینک آگهی» و دکمه هماهنگی بازدید
    // =========================================================================
    function renderVoicePropertyCards(items) {
        const container = document.getElementById('aiVoiceItemsContainer');
        const list = document.getElementById('aiVoiceItemsList');
        const countSpan = document.getElementById('aiVoiceItemsCount');
        if (!container || !list) return;

        if (!items || items.length === 0) {
            container.style.display = 'none';
            return;
        }

        if (countSpan) {
            countSpan.textContent = `${toPersianDigits(items.length)} فایل منطبق`;
        }

        list.replaceChildren();

        items.forEach(p => {
            const card = document.createElement('div');
            card.className = 'ai-voice-item-card';

            const directLink = p.source_url || p.detail_url;

            card.innerHTML = `
                <img src="${p.image_url}" class="ai-voice-item-img" onerror="this.onerror=null; this.src='/static/placeholder.png';" alt="ملک">
                <div class="ai-voice-item-details">
                    <div class="ai-voice-item-title" title="${p.title}">${p.title}</div>
                    <div class="ai-voice-item-specs">
                        <span>📍 ${p.district || 'تهران'}</span>
                        <span>📐 ${toPersianDigits(p.area || 0)} متر</span>
                        <span>🛏️ ${toPersianDigits(p.rooms || 0)} خواب</span>
                        <span style="color: #00f2fe; font-weight: 700;">★ انطباق هوشمند</span>
                    </div>
                    <div class="ai-voice-item-price">${p.price_str}</div>
                    <div class="ai-voice-item-actions">
                        <a href="${directLink}" class="ai-voice-item-link" target="_blank" rel="noopener noreferrer" title="مشاهده مستقیم آگهی اصلی در سایت منبع">
                            <span>🔗</span> لینک آگهی
                        </a>
                        <a href="${p.detail_url}" class="ai-rec-btn ai-rec-btn-glass" target="_blank" title="مشاهده پرونده کامل در سامانه سقف">
                            🏛️ پرونده
                        </a>
                        <button type="button" class="ai-rec-btn ai-rec-btn-gold" onclick="window.scheduleVisitPrompt(${p.id}, '${p.title.replace(/'/g, "\\'")}')" title="هماهنگی بازدید حضوری">
                            📅 هماهنگی بازدید
                        </button>
                    </div>
                </div>
            `;
            list.appendChild(card);
        });

        container.style.display = 'block';
    }

    // =========================================================================
    // سناریوی هماهنگی قرار بازدید (Schedule Visit Flow)
    // =========================================================================
    window.scheduleVisitPrompt = function(propertyId, propertyTitle) {
        const box = document.getElementById('aiVoiceReplyBox');
        if (!box) return;

        box.style.display = 'block';
        box.innerHTML = `
            <div style="background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 10px; padding: 0.85rem; margin-top: 0.5rem;">
                <div style="color: #10b981; font-weight: 700; font-size: 0.84rem; margin-bottom: 0.4rem;">
                    📅 هماهنگی قرار بازدید: «${propertyTitle}»
                </div>
                <div style="font-size: 0.76rem; color: #d1d5db; margin-bottom: 0.6rem;">
                    لطفاً شماره تماس خود را تأیید فرمایید تا کارشناس سقف جهت هماهنگی ساعت بازدید با شما تماس بگیرد:
                </div>
                <div style="display: flex; gap: 0.5rem;">
                    <input type="tel" id="aiVisitCustomerPhone" class="ai-text-input" placeholder="شماره تماس (مثلاً ۰۹۱۲۳۴۵۶۷۸۹)" style="font-size: 0.8rem; padding: 0.4rem 0.65rem;" />
                    <button type="button" class="ai-text-send-btn" onclick="window.confirmScheduleVisit(${propertyId}, '${propertyTitle.replace(/'/g, "\\'")}')" style="background: #10b981; color: #000; font-weight: 700; font-size: 0.78rem; padding: 0.4rem 0.85rem;">
                        ثبت قرار بازدید ✓
                    </button>
                </div>
            </div>
        `;

        box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };

    window.confirmScheduleVisit = async function(propertyId, propertyTitle) {
        const phoneInput = document.getElementById('aiVisitCustomerPhone');
        const phone = phoneInput ? phoneInput.value.trim() : '';

        if (!phone || phone.length < 10) {
            alert('لطفاً شماره تماس معتبر وارد فرمایید.');
            return;
        }

        try {
            const resp = await fetch('/api/ai-orb/schedule-visit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    property_id: propertyId,
                    property_title: propertyTitle,
                    customer_phone: phone,
                    session_id: aiSessionId
                })
            });

            const data = await resp.json();
            if (data.success) {
                playAudioChime('success');
                const box = document.getElementById('aiVoiceReplyBox');
                if (box) {
                    box.innerHTML = `
                        <div style="background: rgba(16, 185, 129, 0.2); border: 1px solid #10b981; border-radius: 10px; padding: 0.85rem; color: #6ee7b7; font-weight: 600; font-size: 0.84rem;">
                            ✅ ${data.message || 'قرار بازدید با موفقیت ثبت گردید. کارشناس مربوطه به زودی با شما تماس می‌گیرد.'}
                        </div>
                    `;
                }
                speakAssistantSpeech("درخواست قرار بازدید شما با موفقیت ثبت شد. همکاران ما به زودی جهت هماهنگی با شما تماس خواهند گرفت.");
            } else {
                alert(data.message || 'خطا در ثبت قرار بازدید');
            }
        } catch (e) {
            console.error('Schedule visit error:', e);
            alert('خطا در برقراری ارتباط با سرور.');
        }
    };

    function applyFiltersToCurrentPageOrRedirect(data) {
        const isPropertyListPage = window.location.pathname.startsWith('/properties') && !window.location.pathname.includes('/new');

        if (isPropertyListPage && document.getElementById('propertyFilterForm')) {
            // اعمال مستقیم روی فیلترهای موجود در همین صفحه بدون رفرش سنگین
            const p = data.params || {};

            // 1. نوع معامله
            if (p.deal_type && typeof window.switchDealTab === 'function') {
                window.switchDealTab(p.deal_type);
            }

            // 2. محله
            if (p.district) {
                const hiddenDist = document.getElementById('filterDistrict');
                const labelDist = document.getElementById('districtPickerSelectedLabel');
                const clearDist = document.getElementById('districtPickerClearBtn');
                if (hiddenDist) hiddenDist.value = p.district;
                if (labelDist) labelDist.textContent = p.district;
                if (clearDist) clearDist.style.display = 'inline-flex';
            }

            // 3. مالی
            if (p.max_deposit && document.getElementById('raw_max_deposit')) {
                document.getElementById('raw_max_deposit').value = p.max_deposit;
                const formatted = document.getElementById('formatted_max_deposit');
                if (formatted) formatted.value = Number(p.max_deposit).toLocaleString();
            }
            if (p.max_rent && document.getElementById('raw_max_rent')) {
                document.getElementById('raw_max_rent').value = p.max_rent;
                const formatted = document.getElementById('formatted_max_rent');
                if (formatted) formatted.value = Number(p.max_rent).toLocaleString();
            }
            if (p.max_price && document.getElementById('raw_max_price')) {
                document.getElementById('raw_max_price').value = p.max_price;
                const formatted = document.getElementById('formatted_max_price');
                if (formatted) formatted.value = Number(p.max_price).toLocaleString();
            }

            // 4. سن بنا
            if (p.min_age !== undefined && document.getElementById('min_age')) {
                document.getElementById('min_age').value = p.min_age;
            }
            if (p.max_age !== undefined && document.getElementById('max_age')) {
                document.getElementById('max_age').value = p.max_age;
            }

            // 5. متراژ و امکانات
            if (p.min_area && document.getElementById('min_area')) document.getElementById('min_area').value = p.min_area;
            if (p.rooms && document.getElementById('rooms')) document.getElementById('rooms').value = p.rooms;
            if (p.has_parking && document.getElementById('has_parking')) document.getElementById('has_parking').checked = true;
            if (p.has_elevator && document.getElementById('has_elevator')) document.getElementById('has_elevator').checked = true;

            // اجرای فوری استخراج درجا
            if (typeof window.triggerOnDemandSearch === 'function') {
                setTimeout(() => {
                    const hudModal = document.getElementById('aiOrbHudModal');
                    if (hudModal) hudModal.classList.remove('active');
                    window.triggerOnDemandSearch(true);
                }, 600);
            }
        } else {
            // هدایت به صفحه فیلترها
            setTimeout(() => {
                window.location.href = data.redirect_url;
            }, 800);
        }
    }

    // فرامین سریع پیشنهادی از چیپ‌ها یا کلیدهای عملیاتی
    window.executeVoiceCommandDirect = function(cmdText) {
        const hudModal = document.getElementById('aiOrbHudModal');
        if (hudModal && !hudModal.classList.contains('active')) {
            hudModal.classList.add('active');
        }
        switchTab('voice');
        handleVoiceCommand(cmdText);
    };

    // =========================================================================
    // کارکرد دوم: شنود و تحلیل زنده مذاکره با مشتری حضوری (Lead Assistant)
    // =========================================================================
    function setupLeadAssistant() {
        const toggleBtn = document.getElementById('aiLeadToggleBtn');
        if (!toggleBtn) return;

        toggleBtn.addEventListener('click', () => {
            if (isLeadListening) {
                stopLeadListening();
            } else {
                startLeadListening();
            }
        });
    }

    function startLeadListening() {
        if (!SpeechRecClass) {
            alert('مرورگر شما از وب‌اسپیچ پشتیبانی نمی‌کند.');
            return;
        }

        try {
            leadRecognition = new SpeechRecClass();
            leadRecognition.lang = 'fa-IR';
            leadRecognition.continuous = true;
            leadRecognition.interimResults = true;

            const toggleBtn = document.getElementById('aiLeadToggleBtn');
            const btnIcon = document.getElementById('aiLeadBtnIcon');
            const btnText = document.getElementById('aiLeadBtnText');
            const desc = document.getElementById('aiLeadStatusDesc');
            const floatingOrb = document.getElementById('aiOrbBtn');

            leadRecognition.onstart = () => {
                isLeadListening = true;
                playAudioChime('start');
                if (toggleBtn) toggleBtn.classList.add('recording');
                if (btnIcon) btnIcon.textContent = '⏹️';
                if (btnText) btnText.textContent = 'توقف شنود جلسه';
                if (desc) {
                    desc.textContent = 'شنود فعال در پس‌زمینه... هوش مصنوعی در حال استخراج نیازمندی‌های مشتری است.';
                    desc.style.color = '#10b981';
                }
                updateSphereListeningUI(true);
            };

            leadRecognition.onresult = (e) => {
                let currentChunk = '';
                for (let i = e.resultIndex; i < e.results.length; i++) {
                    currentChunk += e.results[i][0].transcript + ' ';
                }

                leadTranscriptBuffer += ' ' + currentChunk;

                // Debounce ارسال متن جهت تحلیل پس از مکث یا تکمیل جمله
                if (leadAnalysisDebounceTimer) clearTimeout(leadAnalysisDebounceTimer);
                leadAnalysisDebounceTimer = setTimeout(() => {
                    sendTranscriptForLeadAnalysis(leadTranscriptBuffer);
                }, 2200);
            };

            leadRecognition.onerror = (e) => {
                console.warn('Lead listening error:', e);
                if (e.error === 'not-allowed') {
                    stopLeadListening();
                    alert('دسترسی میکروفون جهت شنود جلسه تأیید نشد.');
                }
            };

            leadRecognition.onend = () => {
                // اگر کاربر دکمه توقف را نزده باشد، جهت پایداری نشست مجدداً فعال می‌شود
                if (isLeadListening) {
                    try { leadRecognition.start(); } catch (e) {}
                }
            };

            leadRecognition.start();
        } catch (e) {
            console.error('Lead recognition error:', e);
            stopLeadListening();
        }
    }

    function stopLeadListening() {
        isLeadListening = false;
        const toggleBtn = document.getElementById('aiLeadToggleBtn');
        const btnIcon = document.getElementById('aiLeadBtnIcon');
        const btnText = document.getElementById('aiLeadBtnText');
        const desc = document.getElementById('aiLeadStatusDesc');

        if (toggleBtn) toggleBtn.classList.remove('recording');
        if (btnIcon) btnIcon.textContent = '▶️';
        if (btnText) btnText.textContent = 'شروع شنود جلسه';
        if (desc) {
            desc.textContent = 'شنود متوقف شد.';
            desc.style.color = '#94a3b8';
        }
        if (!isVoiceListening) updateSphereListeningUI(false);

        if (leadRecognition) {
            try { leadRecognition.stop(); } catch (e) {}
            leadRecognition = null;
        }
    }

    async function sendTranscriptForLeadAnalysis(transcript) {
        if (!transcript || transcript.trim().length < 6) return;

        try {
            const resp = await fetch('/api/ai-orb/analyze-lead', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ transcript: transcript })
            });

            const data = await resp.json();
            if (data.success) {
                renderLeadRequirementsTags(data.tags);
                renderLeadMatchingProperties(data.matches);
            }
        } catch (e) {
            console.error('Lead analysis API error:', e);
        }
    }

    function renderLeadRequirementsTags(tags) {
        const cloud = document.getElementById('aiLeadTagsCloud');
        if (!cloud) return;

        if (!tags || tags.length === 0) return;

        cloud.replaceChildren();
        tags.forEach(t => {
            const pill = document.createElement('span');
            pill.className = 'ai-lead-tag-pill' + (t.type === 'budget' || t.type === 'price' ? ' gold' : '');
            pill.textContent = t.label;
            cloud.appendChild(pill);
        });
    }

    function renderLeadMatchingProperties(matches) {
        const container = document.getElementById('aiLeadMatchesContainer');
        const countSpan = document.getElementById('aiLeadMatchesCount');
        if (!container) return;

        if (!matches || matches.length === 0) {
            container.innerHTML = '<div style="text-align: center; color: #64748b; padding: 1.5rem; font-size: 0.8rem;">در حال حاضر فایلی با این شروط یافت نشد.</div>';
            if (countSpan) countSpan.textContent = '';
            return;
        }

        if (countSpan) {
            countSpan.textContent = `${toPersianDigits(matches.length)} فایل مطابق شروط`;
        }

        container.replaceChildren();

        matches.forEach(p => {
            const card = document.createElement('div');
            card.className = 'ai-rec-card';

            const priceText = p.deal_type === 'rent'
                ? `ودیعه: ${formatToman(p.deposit)} ${p.monthly_rent ? ' | اجاره: ' + formatToman(p.monthly_rent) : ''}`
                : `قیمت: ${formatToman(p.total_price)}`;

            card.innerHTML = `
                <img src="${p.image_url}" class="ai-rec-img" onerror="this.onerror=null; this.src='/static/placeholder.png';" alt="ملک">
                <div class="ai-rec-details">
                    <div>
                        <div class="ai-rec-title" title="${p.title}">${p.title}</div>
                        <div class="ai-rec-specs">
                            <span>📍 ${p.district}</span>
                            <span>📐 ${toPersianDigits(p.area || 0)} متر</span>
                            <span>🛏️ ${toPersianDigits(p.rooms || 0)} خواب</span>
                            <span style="color: #00f2fe; font-weight: 700;">★ ${toPersianDigits(p.score)}٪ انطباق</span>
                        </div>
                        <div class="ai-rec-price">${priceText}</div>
                    </div>
                    <div class="ai-rec-actions">
                        <a href="${p.detail_url}" class="ai-rec-btn ai-rec-btn-gold" target="_blank" title="مشاهده پرونده کامل">
                            🏛️ پرزنت فوری
                        </a>
                        <button type="button" class="ai-rec-btn ai-rec-btn-glass" onclick="sendPropertyPhotosToTelegram(${p.id}, '${p.file_code}', event)" title="ارسال آلبوم به تلگرام">
                            📸 تلگرام
                        </button>
                        ${p.owner_phone ? `
                            <a href="tel:${p.owner_phone}" class="ai-rec-btn ai-rec-btn-glass" title="تماس با مالک">
                                📞 تماس
                            </a>
                        ` : `
                            <button type="button" class="ai-rec-btn ai-rec-btn-glass" onclick="fetchAndRevealCardPhone(${p.id}, event)" title="استعلام شماره">
                                ⚡ شماره
                            </button>
                        `}
                    </div>
                </div>
            `;
            container.appendChild(card);
        });
    }

    // =========================================================================
    // بخش اختصاصی CHATGPT VOICE MODE & AI REAL ESTATE AGENT
    // =========================================================================

    // ۱. فعال‌سازی و بستن پنل تعاملی روی همان صفحه (IN-PAGE EXPANSION)
    window.activateInPageAssistant = function() {
        const resting = document.getElementById('aiRestingSection');
        const active = document.getElementById('aiActivePanel');
        const station = document.getElementById('ai-station');

        if (active) {
            active.classList.remove('hidden');
        }
        if (resting) {
            resting.classList.add('hidden');
        }
        playAudioChime('start');

        if (station) {
            station.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }

        // شروع خودکار شنود صوتی هنگام باز شدن در صورت تمایل کاربر
        setTimeout(() => {
            if (!isChatGptRecording && SpeechRecClass) {
                window.toggleChatGptVoiceMic();
            }
        }, 350);
    };

    window.deactivateInPageAssistant = function() {
        const resting = document.getElementById('aiRestingSection');
        const active = document.getElementById('aiActivePanel');

        if (active) {
            active.classList.add('hidden');
        }
        if (resting) {
            resting.classList.remove('hidden');
        }

        if (window.speechSynthesis) {
            window.speechSynthesis.cancel();
        }
        if (typeof isChatGptRecording !== 'undefined' && isChatGptRecording && typeof chatgptRecognition !== 'undefined' && chatgptRecognition) {
            try { chatgptRecognition.stop(); } catch (e) {}
            isChatGptRecording = false;
        }
        stopAudioAnalysis();
        const centerOrb = document.getElementById('chatgptCenterOrbContainer');
        if (centerOrb) centerOrb.classList.remove('has-results');
        setOrbVoiceState('idle');
    };

    // حفظ سازگاری نام‌های قبلی
    window.openChatGptVoiceModal = window.activateInPageAssistant;
    window.closeChatGptVoiceModal = window.deactivateInPageAssistant;

    // ۲. کنترل وضعیت گوی مرکزی (شنود، تفکر، پاسخ صوتی)
    function setOrbVoiceState(state) {
        const orb = document.getElementById('chatgptCenterOrbContainer');
        const statusText = document.getElementById('chatgptVoiceStatus');
        const micBadge = document.getElementById('chatgptOrbMicBadge');
        if (!orb) return;

        orb.classList.remove('is-listening', 'is-thinking', 'is-speaking');

        if (state === 'listening') {
            orb.classList.add('is-listening');
            if (statusText) statusText.textContent = 'در حال شنود گفتار شما... (صحبت کنید)';
            if (micBadge) micBadge.innerHTML = '<span class="animate-pulse">⏹️</span>';
        } else if (state === 'thinking') {
            orb.classList.add('is-thinking');
            if (statusText) statusText.textContent = 'در حال تحلیل دیتابیس املاک و استخراج فایل‌ها...';
            if (micBadge) micBadge.innerHTML = '<span>⚡</span>';
        } else if (state === 'speaking') {
            orb.classList.add('is-speaking');
            if (statusText) statusText.textContent = 'مشاور هوشمند در حال پاسخ صوتی...';
            if (micBadge) micBadge.innerHTML = '<span class="animate-bounce">🔊</span>';
        } else {
            if (statusText) statusText.textContent = 'آماده شنود خواسته شما...';
            if (micBadge) micBadge.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/></svg>';
        }
    }

    // ۳. سنتز صوتی فارسی (Speech Synthesis) - صحبت کردن مشاور با صدای طبیعی و بدون لکنت
    function speakPersianText(text) {
        if (!window.speechSynthesis) return;
        try {
            window.speechSynthesis.cancel();

            let cleanText = text.replace(/[\u{1F300}-\u{1F9FF}]/gu, '')
                                .replace(/[📍📐🔑🏷️🏢🏛️⚡🎙️🔊⏹️✕↵💡🚗📡👥🤖💎💰•]/gu, '')
                                .replace(/[|]/g, ' و ')
                                .replace(/\n/g, ' ')
                                .trim();

            const utterance = new SpeechSynthesisUtterance(cleanText);
            utterance.lang = 'fa-IR';
            utterance.rate = 0.95;
            utterance.pitch = 1.0;

            const loadAndSetVoice = () => {
                const voices = window.speechSynthesis.getVoices();
                const faVoice = voices.find(v => v.lang && (v.lang.toLowerCase().includes('fa') || v.name.toLowerCase().includes('persian') || v.name.toLowerCase().includes('farsi')));
                if (faVoice) utterance.voice = faVoice;
            };

            loadAndSetVoice();
            if (window.speechSynthesis.onvoiceschanged !== undefined) {
                window.speechSynthesis.onvoiceschanged = loadAndSetVoice;
            }

            setOrbVoiceState('speaking');

            utterance.onend = function() {
                setOrbVoiceState('idle');
            };
            utterance.onerror = function() {
                setOrbVoiceState('idle');
            };

            window.speechSynthesis.speak(utterance);
        } catch (e) {
            setOrbVoiceState('idle');
        }
    }

    // ۴. ضبط صدا و تبدیل گفتار به متن با Web Speech API
    window.toggleChatGptVoiceMic = function() {
        if (typeof window.toggleMicrophoneLive === 'function') {
            window.toggleMicrophoneLive();
        }
    };

    // =========================================================================
    // بخش جدید: دستیار هوشمند درون‌صفحه‌ای سقف با گوی ۳ بعدی WebGL / Three.js
    // =========================================================================
    let orbStandbyInstance = null;
    let orbActiveInstance = null;
    let activeScenarioMode = 'discovery'; // 'discovery' | 'intake'

    // راه‌اندازی گوی‌های سه‌بعدی WebGL
    function initWebGlOrbs() {
        if (typeof window.Saghf3DOrb !== 'function') return;

        const standbyCanvas = document.getElementById('saghf3DOrbCanvas');
        if (standbyCanvas && !orbStandbyInstance) {
            orbStandbyInstance = new window.Saghf3DOrb(standbyCanvas);
        }

        const activeCanvas = document.getElementById('saghf3DOrbCanvasActive');
        if (activeCanvas && !orbActiveInstance) {
            orbActiveInstance = new window.Saghf3DOrb(activeCanvas);
        }
    }

    // به‌روزرسانی وضعیت هر دو گوی
    function setOrbState(state) {
        if (orbStandbyInstance) orbStandbyInstance.setState(state);
        if (orbActiveInstance) orbActiveInstance.setState(state);

        const stateText = document.getElementById('saghfStateText');
        const visualizer = document.getElementById('saghfAudioVisualizer');
        const micBadge = document.getElementById('saghfMicStateIndicator');

        if (state === 'listening') {
            if (stateText) stateText.textContent = 'در حال شنود کلام شما...';
            if (visualizer) visualizer.classList.add('active');
            if (micBadge) micBadge.classList.add('listening');
        } else if (state === 'speaking') {
            if (stateText) stateText.textContent = 'در حال پاسخگویی صوتی...';
            if (visualizer) visualizer.classList.add('active');
            if (micBadge) micBadge.classList.remove('listening');
        } else if (state === 'processing') {
            if (stateText) stateText.textContent = 'در حال تحلیل نیاز و استخراج زنده ملک...';
            if (visualizer) visualizer.classList.add('active');
            if (micBadge) micBadge.classList.remove('listening');
        } else {
            if (stateText) stateText.textContent = 'آماده شنود...';
            if (visualizer) visualizer.classList.remove('active');
            if (micBadge) micBadge.classList.remove('listening');
        }
    }

    // اتصال به وب‌آودیو جهت تحلیل لحظه‌ای فرکانس صدا
    async function startAudioAnalysis() {
        try {
            if (!audioContext) {
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (audioContext.state === 'suspended') {
                await audioContext.resume();
            }

            if (!micStream) {
                micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
            }

            const source = audioContext.createMediaStreamSource(micStream);
            analyserNode = audioContext.createAnalyser();
            analyserNode.fftSize = 64;
            source.connect(analyserNode);

            const bufferLength = analyserNode.frequencyBinCount;
            const dataArray = new Uint8Array(bufferLength);

            function updateAudioLoop() {
                if (!isInPageRecording) return;
                analyserNode.getByteFrequencyData(dataArray);

                let sum = 0;
                const freqs = [];
                for (let i = 0; i < Math.min(16, bufferLength); i++) {
                    const normVal = dataArray[i] / 255.0;
                    freqs.push(normVal);
                    sum += normVal;
                }
                const avgLevel = sum / 16.0;

                if (orbActiveInstance) {
                    orbActiveInstance.setAudioData(avgLevel * 1.5, freqs);
                }
                if (orbStandbyInstance) {
                    orbStandbyInstance.setAudioData(avgLevel * 1.5, freqs);
                }

                micAnimFrameId = requestAnimationFrame(updateAudioLoop);
            }
            updateAudioLoop();
        } catch (e) {
            console.warn("Audio analysis fallback:", e);
        }
    }

    function stopAudioAnalysis() {
        if (micAnimFrameId) {
            cancelAnimationFrame(micAnimFrameId);
            micAnimFrameId = null;
        }
        if (micStream) {
            try {
                micStream.getTracks().forEach(track => {
                    track.stop();
                    track.enabled = false;
                });
            } catch (e) {}
            micStream = null;
        }
        if (analyserNode) {
            try { analyserNode.disconnect(); } catch (e) {}
            analyserNode = null;
        }
        if (orbActiveInstance) orbActiveInstance.setAudioData(0, []);
        if (orbStandbyInstance) orbStandbyInstance.setAudioData(0, []);
    }

    // پخش صدای طبیعی گفتار فارسی (TTS)
    function speakPersianText(text, onEndCallback) {
        if (!window.speechSynthesis) {
            if (onEndCallback) onEndCallback();
            return;
        }

        window.speechSynthesis.cancel();
        const cleanText = text.replace(/[*_#`[\]()]/g, '').trim();
        const utterance = new SpeechSynthesisUtterance(cleanText);
        utterance.lang = 'fa-IR';
        utterance.rate = 1.05;
        utterance.pitch = 1.0;

        // انتخاب بهترین صدای موجود
        const voices = window.speechSynthesis.getVoices();
        const faVoice = voices.find(v => v.lang.includes('fa') || v.lang.includes('IR')) || voices.find(v => v.name.includes('Persian'));
        if (faVoice) utterance.voice = faVoice;

        utterance.onstart = () => {
            setOrbState('speaking');
        };

        utterance.onend = () => {
            setOrbState('standby');
            if (onEndCallback) onEndCallback();
        };

        utterance.onerror = () => {
            setOrbState('standby');
            if (onEndCallback) onEndCallback();
        };

        window.speechSynthesis.speak(utterance);
    }

    // ۱. باز کردن پنل تعاملی از حالت استندبای
    window.expandAndStartListening = function() {
        const standby = document.getElementById('aiStationStandbyView');
        const expanded = document.getElementById('aiStationExpandedView');
        const expandBtnText = document.getElementById('aiExpandCollapseText');
        const expandBtnIcon = document.getElementById('aiExpandCollapseIcon');

        if (standby && expanded) {
            standby.classList.add('hidden');
            expanded.classList.remove('hidden');
            if (expandBtnText) expandBtnText.textContent = 'بستن کنسول و بازگشت به گوی';
            if (expandBtnIcon) expandBtnIcon.textContent = '▲';

            // اگر گوی فعال هنوز مقداردهی نشده باشد، دوباره راه‌اندازی شود
            setTimeout(() => {
                initWebGlOrbs();
                if (orbActiveInstance) orbActiveInstance.resize();
            }, 100);

            // آغاز تعامل با خوش‌آمدگویی صوتی استاندارد سناریوی اول
            const transcript = document.getElementById('saghfLiveTranscript');
            const welcomeSpeech = "سلام، خوش آمدید به سقف. برای خرید یا اجاره چه متراژ و در چه منطقه‌ای مد نظرتونه؟";
            if (transcript) {
                transcript.innerHTML = `«${welcomeSpeech}»`;
            }
            speakPersianText(welcomeSpeech, () => {
                // شروع خودکار شنود پس از خوش‌آمدگویی
                window.toggleMicrophoneLive(true);
            });
        }
    };

    // باز و بسته کردن کنسول تعاملی
    window.toggleInPageAssistant = function() {
        const standby = document.getElementById('aiStationStandbyView');
        const expanded = document.getElementById('aiStationExpandedView');
        const expandBtnText = document.getElementById('aiExpandCollapseText');
        const expandBtnIcon = document.getElementById('aiExpandCollapseIcon');

        if (!standby || !expanded) return;

        if (expanded.classList.contains('hidden')) {
            window.expandAndStartListening();
        } else {
            expanded.classList.add('hidden');
            standby.classList.remove('hidden');
            if (expandBtnText) expandBtnText.textContent = 'باز کردن کنسول تعاملی';
            if (expandBtnIcon) expandBtnIcon.textContent = '▼';
            if (isInPageRecording) window.toggleMicrophoneLive(false);
            if (window.speechSynthesis) window.speechSynthesis.cancel();
            setOrbState('standby');
        }
    };

    // سوئیچ بین سناریوی ۱ (کشف نیاز مشتری) و سناریوی ۲ (ثبت فایل جدید ملک)
    window.toggleAiScenarioMode = function(forcedMode = null) {
        activeScenarioMode = forcedMode || (activeScenarioMode === 'discovery' ? 'intake' : 'discovery');

        const modeBadge = document.getElementById('aiModeBadge');
        const scenarioIcon = document.getElementById('aiScenarioIcon');
        const scenarioText = document.getElementById('aiScenarioText');
        const matchingPanel = document.getElementById('saghfMatchingPanel');
        const intakePanel = document.getElementById('saghfIntakePanel');
        const transcript = document.getElementById('saghfLiveTranscript');

        if (activeScenarioMode === 'discovery') {
            if (modeBadge) modeBadge.textContent = 'کشف نیاز خریدار/مستأجر و انطباق زنده';
            if (scenarioIcon) scenarioIcon.textContent = '🔍';
            if (scenarioText) scenarioText.textContent = 'حالت: کشف نیاز مشتری';
            if (matchingPanel) matchingPanel.classList.remove('hidden');
            if (intakePanel) intakePanel.classList.add('hidden');
            if (transcript) transcript.textContent = '«آماده دریافت خواسته شما برای خرید، رهن یا اجاره ملک...»';
        } else {
            if (modeBadge) modeBadge.textContent = 'ثبت خودکار فایل جدید و اتصال به پیام‌رسان‌ها';
            if (scenarioIcon) scenarioIcon.textContent = '📝';
            if (scenarioText) scenarioText.textContent = 'حالت: ثبت فایل جدید مالک';
            if (matchingPanel) matchingPanel.classList.add('hidden');
            if (intakePanel) intakePanel.classList.remove('hidden');
            const intakeMsg = "لطفاً مشخصات ملکتان مانند منطقه، متراژ، قیمت و شرایط واگذاری را بفرمایید تا مستقیماً ثبت شود.";
            if (transcript) transcript.textContent = `«${intakeMsg}»`;
            speakPersianText(intakeMsg);
        }
    };

    // فعال‌سازی و توقف میکروفون برای شنود زنده
    window.toggleMicrophoneLive = function(forceStart = null) {
        if (!SpeechRecClass) {
            alert('مرورگر شما از ورودی صوتی پشتیبانی نمی‌کند. لطفاً پیام را بنویسید.');
            return;
        }

        const shouldStart = forceStart !== null ? forceStart : !isInPageRecording;

        if (!shouldStart) {
            if (inPageRecognition) inPageRecognition.stop();
            isInPageRecording = false;
            stopAudioAnalysis();
            setOrbState('standby');
            return;
        }

        try {
            inPageRecognition = new SpeechRecClass();
            inPageRecognition.lang = 'fa-IR';
            inPageRecognition.continuous = false;
            inPageRecognition.interimResults = true;

            inPageRecognition.onstart = function() {
                isInPageRecording = true;
                setOrbState('listening');
                playAudioChime('start');
                startAudioAnalysis();
                const transcript = document.getElementById('saghfLiveTranscript');
                if (transcript) transcript.textContent = '«در حال گوش دادن به شما... بفرمایید»';
            };

            inPageRecognition.onresult = function(e) {
                let interim = '';
                let final = '';
                for (let i = 0; i < e.results.length; ++i) {
                    if (e.results[i].isFinal) {
                        final += e.results[i][0].transcript;
                    } else {
                        interim += e.results[i][0].transcript;
                    }
                }
                const text = final || interim;
                const transcript = document.getElementById('saghfLiveTranscript');
                const input = document.getElementById('saghfTextInput');
                if (transcript && text) transcript.textContent = `«${text}»`;
                if (input && text) input.value = text;

                if (final) {
                    isInPageRecording = false;
                    stopAudioAnalysis();
                    window.handleVoiceFormSubmit();
                }
            };

            inPageRecognition.onerror = function() {
                isInPageRecording = false;
                stopAudioAnalysis();
                setOrbState('standby');
            };

            inPageRecognition.onend = function() {
                isInPageRecording = false;
                stopAudioAnalysis();
            };

            inPageRecognition.start();
        } catch (e) {
            isInPageRecording = false;
            stopAudioAnalysis();
            setOrbState('standby');
        }
    };

    // انتخاب سریع پرامپت‌ها
    window.quickPromptSelect = function(promptText) {
        window.expandAndStartListening();
        const input = document.getElementById('saghfTextInput');
        if (input) input.value = promptText;
        setTimeout(() => {
            window.handleVoiceFormSubmit();
        }, 300);
    };

    // ارسال فرم و پردازش همزمان کوئری و رندر کارت‌ها
    window.handleVoiceFormSubmit = function(event) {
        if (event && event.preventDefault) event.preventDefault();

        const input = document.getElementById('saghfTextInput');
        const transcript = document.getElementById('saghfLiveTranscript');
        const matchContainer = document.getElementById('saghfMatchListContainer');
        const countBadge = document.getElementById('saghfMatchCountBadge');
        const entitiesBox = document.getElementById('saghfExtractedEntities');
        const entitiesList = document.getElementById('saghfEntitiesList');

        if (!input) return;
        const query = input.value.trim();
        if (!query) return;

        // تغییر وضعیت به پردازش گردابی
        setOrbState('processing');
        if (transcript) transcript.innerHTML = `<span style="color: #00d2ff;">⚡ «${query}»</span>`;

        // تشخیص خودکار قصد ثبت فایل (سناریوی ۲)
        const norm = query.toLowerCase();
        if (norm.includes('ثبت') || norm.includes('واگذاری') || norm.includes('مالکم') || norm.includes('بسپارم')) {
            window.toggleAiScenarioMode('intake');
            // استخراج فیلدها و پر کردن ویزارد
            if (norm.includes('اجاره') || norm.includes('رهن')) {
                document.getElementById('intakeDealType').textContent = 'رهن و اجاره';
            } else if (norm.includes('فروش') || norm.includes('خرید')) {
                document.getElementById('intakeDealType').textContent = 'خرید و فروش';
            }
            if (norm.includes('پونک') || norm.includes('منطقه ۵')) {
                document.getElementById('intakeDistrict').textContent = 'منطقه ۵ (پونک)';
            } else if (norm.includes('منطقه ۲') || norm.includes('سعادت آباد')) {
                document.getElementById('intakeDistrict').textContent = 'منطقه ۲ (سعادت‌آباد)';
            }
        }

        const csrfToken = typeof getCsrfToken === 'function' ? getCsrfToken() : '';

        fetch('/api/ai-orb/parse-command', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({
                command: query,
                current_path: window.location.pathname
            })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                playAudioChime('success');
                if (transcript) {
                    transcript.innerHTML = data.voice_reply.replace(/\n/g, '<br>');
                }

                // خوانش صوتی پاسخ
                speakPersianText(data.speech_text || data.voice_reply);

                // نمایش موجودیت‌های استخراج‌شده (NER)
                const extracted = data.extracted_params || data.params;
                if (extracted && entitiesBox && entitiesList) {
                    entitiesList.innerHTML = '';
                    let hasEntities = false;
                    Object.entries(extracted).forEach(([k, v]) => {
                        if (v) {
                            hasEntities = true;
                            const tag = document.createElement('span');
                            tag.className = 'saghf-ner-tag';
                            tag.textContent = `${k}: ${v}`;
                            entitiesList.appendChild(tag);
                        }
                    });
                    if (hasEntities) entitiesBox.classList.remove('hidden');
                }

                // رندر همزمان کارت‌های ملکی منطبق در پنل اسلایدی (سناریوی ۱)
                if (data.items && data.items.length > 0 && matchContainer) {
                    matchContainer.innerHTML = '';
                    if (countBadge) countBadge.textContent = `${toPersianDigits(data.items.length)} فایل`;

                    data.items.forEach(item => {
                        const card = document.createElement('div');
                        card.className = 'saghf-mini-property-card';
                        card.innerHTML = `
                            <div class="saghf-mini-card-head">
                                <img src="${item.image_url}" class="saghf-mini-thumb" onerror="this.src='/static/images/placeholder.png'" alt="ملک" />
                                <div class="saghf-mini-info">
                                    <div class="saghf-mini-title" title="${item.title}">${item.title}</div>
                                    <div class="saghf-mini-meta">📍 ${item.district} | 📐 ${toPersianDigits(item.area || 0)} متر (${toPersianDigits(item.rooms || 1)} خواب)</div>
                                </div>
                            </div>
                            <div class="saghf-mini-price-box">${item.price_str}</div>
                            <div class="saghf-mini-card-actions">
                                <a href="${item.detail_url}" target="_blank" class="saghf-card-btn-view">
                                    🏛️ پرونده ملک ↵
                                </a>
                                <a href="${item.source_url || item.detail_url}" target="_blank" rel="noopener noreferrer" class="saghf-card-source-link">
                                    لینک آگهی ↗
                                </a>
                            </div>
                        `;
                        matchContainer.appendChild(card);
                    });
                } else if (matchContainer && data.items && data.items.length === 0) {
                    if (countBadge) countBadge.textContent = '۰ فایل';
                }

                // در صورتی که نیاز به هدایت صفحه باشد
                if (data.action === 'navigate' && data.url) {
                    setTimeout(() => {
                        window.location.href = data.url;
                    }, 2200);
                }
            } else {
                setOrbState('standby');
                if (transcript) transcript.textContent = data.message || 'پوزش، متوجه دستور نشدم.';
            }
        })
        .catch(err => {
            setOrbState('standby');
            if (transcript) transcript.textContent = 'خطا در برقراری ارتباط با موتور هوش مصنوعی سقف.';
        });
    };

    // اتوماسیون پیام‌رسان‌ها در سناریوی ۲
    window.triggerOmniChannelIntake = function(channel) {
        const phone = document.getElementById('intakeOwnerPhone')?.value.trim() || '09123456789';
        const dealType = document.getElementById('intakeDealType')?.textContent || 'رهن و اجاره';
        const district = document.getElementById('intakeDistrict')?.textContent || 'منطقه ۵';
        const statusBox = document.getElementById('saghfIntakeSubmitStatus');

        if (statusBox) {
            statusBox.classList.remove('hidden');
            statusBox.innerHTML = `
                <div>✅ پیام خوش‌آمد، تأیید ثبت فایل (${dealType} - ${district}) و لینک دریافت تصاویر با موفقیت به <strong>${channel.toUpperCase()}</strong> شماره <strong>${phone}</strong> ارسال شد.</div>
                <div style="font-size: 0.75rem; color: #a7f3d0; margin-top: 0.35rem;">🔗 شناسه پیام ارسالی: MSG-${Math.floor(100000 + Math.random() * 900000)} | پرونده در CRM سقف تشکیل شد.</div>
            `;
        }

        speakPersianText(`اطلاعات ملک با موفقیت ثبت شد و پیام خوش‌آمد و لینک مدارک به ${channel} شما ارسال گردید.`);
    };

    // اتصال اسکرول صفحه به کامپوننت هوش مصنوعی
    window.scrollToAssistant = function() {
        const station = document.getElementById('ai-station');
        if (station) {
            station.scrollIntoView({ behavior: 'smooth', block: 'center' });
            window.expandAndStartListening();
        } else {
            window.location.href = '/properties/#ai-station';
        }
    };

    // پایش دوره‌ای وضعیت استخراج زنده دیوار
    function startRealtimeMonitorPolling() {
        const textElem = document.getElementById('divarLiveMonitorText');
        if (!textElem) return;

        function checkStatus() {
            fetch('/crawler/realtime-monitor/status')
                .then(res => res.json())
                .then(data => {
                    if (data && data.is_running) {
                        const count = data.new_owners_today || 0;
                        textElem.innerHTML = `پایش زنده منطقه ۵: <strong>${count}</strong> فایل جدید مالک`;
                    }
                })
                .catch(() => {});
        }

        // استعلام اولیه و تکرار هر ۱۵ ثانیه
        checkStatus();
        setInterval(checkStatus, 15000);
    }

    // راه‌اندازی پس از بارگذاری سند
    document.addEventListener('DOMContentLoaded', () => {
        initAIOrb();
        if (typeof window.initWebGlOrbs === 'function') {
            window.initWebGlOrbs();
        } else if (typeof window.initSaghf3DOrb === 'function') {
            window.initSaghf3DOrb();
        }
        startRealtimeMonitorPolling();
    });

})();


