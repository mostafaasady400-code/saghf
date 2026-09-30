/**
 * SAGHF THREE.JS / WEBGL 3D ORB ENGINE v2.0 (موتور گوی سه‌بعدی وب‌جی‌ال سقف)
 * بازطراحی کامل با مشخصات فوق‌العاده شفاف، شارپ، و حجمی:
 * ۱. گوی کاملاً سه‌بعدی با عمق هندسی، هسته کریستالی ابسیدین و شیدرهای پیشرفته
 * ۲. امواج صوتی نئونی سینوسی متحرک (Dynamic 3D Acoustic Waveforms) روی بدنه گوی
 * ۳. طیف رنگی لوکس: آبی متالیک (#00D2FF) و بنفش نئونی (#9B51E0) بدون تاری کدر
 * ۴. بازتاب اسپکولار بلورین شبیه شیشه کوارتز و ریم لایت قدرتمند
 * ۵. انیمیشن شناوری معلق (Floating) و هماهنگی بلادرنگ با فرکانس صدا
 */

(function() {
    'use strict';

    class Saghf3DOrb {
        constructor(canvasId) {
            this.canvas = typeof canvasId === 'string' ? document.getElementById(canvasId) : canvasId;
            if (!this.canvas) return;

            this.gl = this.canvas.getContext('webgl', { 
                alpha: true, 
                antialias: true, 
                premultipliedAlpha: false,
                powerPreference: 'high-performance'
            });

            if (!this.gl) {
                console.warn("WebGL not supported, falling back to Canvas 2D");
                this.init2DFallback();
                return;
            }

            this.state = 'standby'; // 'standby' | 'listening' | 'speaking' | 'processing'
            this.audioLevel = 0.0;
            this.audioFreqs = new Float32Array(16);
            this.time = 0.0;
            this.rotationAngle = 0.0;
            this.targetSpeed = 1.0;
            this.currentSpeed = 1.0;
            this.animFrameId = null;

            this.initShaders();
            this.initGeometry();
            this.setupEvents();
            this.resize();
            this.startLoop();
        }

        initShaders() {
            const gl = this.gl;

            // Vertex Shader: جابه‌جایی دینامیک رئوس بر پایه امواج آکوستیک، هارمونیک‌های صوتی و ریپل‌های سه‌بعدی
            const vsSource = `
                precision mediump float;

                attribute vec3 aPosition;
                attribute vec3 aNormal;

                uniform mat4 uProjection;
                uniform mat4 uModelView;
                uniform float uTime;
                uniform float uAudioLevel;
                uniform float uState; // 0=standby, 1=listening, 2=speaking, 3=processing
                uniform float uFreqData[16];

                varying vec3 vNormal;
                varying vec3 vPosition;
                varying vec3 vWorldNormal;
                varying float vDisplacement;
                varying float vWaveIntensity;

                float hash(vec3 p) {
                    p = fract(p * 0.3183099 + 0.1);
                    p *= 17.0;
                    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
                }

                float noise(vec3 x) {
                    vec3 p = floor(x);
                    vec3 f = fract(x);
                    f = f * f * (3.0 - 2.0 * f);
                    return mix(
                        mix(mix(hash(p + vec3(0,0,0)), hash(p + vec3(1,0,0)), f.x),
                            mix(hash(p + vec3(0,1,0)), hash(p + vec3(1,1,0)), f.x), f.y),
                        mix(mix(hash(p + vec3(0,0,1)), hash(p + vec3(1,0,1)), f.x),
                            mix(hash(p + vec3(0,1,1)), hash(p + vec3(1,1,1)), f.x), f.y), f.z
                    );
                }

                void main() {
                    vNormal = normalize(aNormal);
                    vec3 pos = aPosition;

                    float disp = 0.0;
                    float wave = 0.0;

                    // امواج هارمونیک پایدار در حالت استندبای
                    float harmonic1 = sin(pos.y * 4.0 + uTime * 2.2) * 0.04;
                    float harmonic2 = cos(pos.x * 3.5 - uTime * 1.8 + pos.z * 2.0) * 0.03;
                    float organic = noise(pos * 2.2 + uTime * 0.5) * 0.035;

                    disp = harmonic1 + harmonic2 + organic;

                    // واکنش به صدای کاربر در حالت‌های شنود و گفتار
                    if (uState > 0.5 && uState < 2.5) {
                        float freqBoost = (uFreqData[0] + uFreqData[2] + uFreqData[4] + uFreqData[7]) * 0.25;
                        float reactiveAmp = (uAudioLevel * 0.45) + (freqBoost * 0.35);

                        // امواج آکوستیک شدید و ریپل‌های صوتی مواج
                        wave = sin(pos.y * 12.0 + uTime * 6.0) * reactiveAmp * 0.55;
                        wave += cos(pos.x * 10.0 - uTime * 5.0) * reactiveAmp * 0.35;
                        disp += wave + noise(pos * 4.5 + uTime * 2.5) * (0.06 + reactiveAmp * 0.35);
                    } else if (uState > 2.5) {
                        // گرداب پردازش کوانتومی
                        float angle = uTime * 6.0;
                        disp = sin(pos.y * 7.0 + angle) * cos(pos.z * 7.0 + angle) * 0.14;
                        disp += sin(atan(pos.z, pos.x) * 5.0 + uTime * 9.0) * 0.08;
                    }

                    vDisplacement = disp;
                    vWaveIntensity = wave;

                    pos += aNormal * disp;
                    vPosition = pos;

                    gl_Position = uProjection * uModelView * vec4(pos, 1.0);
                }
            `;

            // Fragment Shader: ساختار فوق‌لوکس مشکی آبسیدین با خطوط پردازشی بردهای طلایی و پالس‌های نوری متحرک
            const fsSource = `
                precision mediump float;

                varying vec3 vNormal;
                varying vec3 vPosition;
                varying float vDisplacement;
                varying float vWaveIntensity;

                uniform float uTime;
                uniform float uState;
                uniform float uAudioLevel;

                void main() {
                    // هسته مشکی آبسیدین عمیق و متالیک (#0A0A0C تا #121212)
                    vec3 coreObsidian = vec3(0.04, 0.04, 0.048);

                    // پالت اختصاصی متالیک طلایی و کهربایی سقف
                    vec3 metallicGold = vec3(0.831, 0.686, 0.216);  // #D4AF37 طلایی سلطنتی سقف
                    vec3 radiantGold  = vec3(1.0, 0.843, 0.0);      // #FFD700 طلایی درخشان
                    vec3 lightAmber   = vec3(1.0, 0.92, 0.65);       // #FFDF73 هایلایت طلایی
                    vec3 deepBronze   = vec3(0.55, 0.40, 0.12);      // #8C661F برنز عمیق متالیک
                    vec3 deepBlack    = vec3(0.012, 0.012, 0.015);

                    vec3 viewDir = normalize(-vPosition);
                    vec3 normal = normalize(vNormal);

                    // ۱. افکت فرنل لبه‌های بیرونی با تناژ طلایی گرم (Warm Golden Fresnel Bloom)
                    float nDotV = max(dot(viewDir, normal), 0.0);
                    float fresnel = 1.0 - nDotV;
                    float rimSharp = pow(fresnel, 2.6);
                    float rimBroad = pow(fresnel, 1.3);

                    // ضریب شتاب زمان بر اساس وضعیت سامانه (پایش و جستجوی فایل = سرعت ۳×)
                    float speedMult = (uState > 2.5) ? 3.4 : ((uState > 0.5) ? (2.2 + uAudioLevel * 2.5) : 1.0);

                    // ۲. خطوط مدار الکتریکی سایبرنتیک و مسیرهای جریان داده (Electronic Circuit Board Traces)
                    vec3 cp = vPosition * 4.4;
                    vec3 fp = fract(cp);

                    float trackX = smoothstep(0.06, 0.0, abs(fp.y - 0.5));
                    float trackY = smoothstep(0.06, 0.0, abs(fp.x - 0.5));
                    float trackZ = smoothstep(0.06, 0.0, abs(fp.z - 0.5));
                    float diagTrace = smoothstep(0.05, 0.0, abs((fp.x + fp.y) - 1.0));

                    // پدهای لحیم و اتصالات چیپست (Micro-Vias & Solder Nodes)
                    float viaDist = length(fp - 0.5);
                    float vias = smoothstep(0.18, 0.12, viaDist) * smoothstep(0.04, 0.08, viaDist);

                    float circuitNetwork = max(trackX, max(trackY, trackZ)) * 0.75 + diagTrace * 0.6 + vias * 1.3;

                    // ۳. پالس‌های نوری متحرک در طول مدارهای روی گوی بر اساس زمان (uTime)
                    float flowAxis = (vPosition.x * 2.8 + vPosition.y * 3.6 + vPosition.z * 2.2);
                    float pulse = pow(sin(flowAxis * 3.5 - uTime * speedMult * 2.8) * 0.5 + 0.5, 7.0);
                    float microPulse = pow(sin(flowAxis * 7.0 + uTime * speedMult * 4.0) * 0.5 + 0.5, 12.0);

                    // ۴. بازتاب اسپکولار بلورین دوقلو (Dual Glossy Metallic Gold Highlights)
                    vec3 lightDir1 = normalize(vec3(0.5, 0.8, 1.0));
                    vec3 halfDir1 = normalize(lightDir1 + viewDir);
                    float spec1 = pow(max(dot(normal, halfDir1), 0.0), 75.0);

                    vec3 lightDir2 = normalize(vec3(-0.6, -0.4, 0.7));
                    vec3 halfDir2 = normalize(lightDir2 + viewDir);
                    float spec2 = pow(max(dot(normal, halfDir2), 0.0), 36.0);

                    // ۵. ترکیب لایه‌های رنگی: هسته ابسیدین + خطوط مدار طلایی + پالس‌های درخشان + ریم‌لایت
                    vec3 finalColor = coreObsidian;

                    // اعمال رنگ طلایی روی خطوط پردازشی با پالس‌های درخشان
                    vec3 circuitColor = mix(deepBronze, metallicGold, 0.6);
                    circuitColor = mix(circuitColor, radiantGold, pulse * 0.85 + microPulse * 0.5);
                    finalColor += circuitColor * circuitNetwork * (0.45 + pulse * 1.6 + microPulse * 1.2);

                    // هاله نورانی دور گوی (Warm Gold Fresnel / Rim Glow)
                    vec3 rimColor = mix(metallicGold, radiantGold, rimSharp);
                    finalColor += rimColor * (rimSharp * 2.4 + rimBroad * 0.5);

                    // تقویت درخشش هنگام مکالمه صوتی و پردازش
                    if (uState > 0.5 && uState < 2.5) {
                        finalColor += radiantGold * (uAudioLevel * 0.9);
                        finalColor += lightAmber * (abs(vWaveIntensity) * 3.5);
                    } else if (uState > 2.5) {
                        finalColor += radiantGold * 1.4;
                    }

                    // هایلایت‌های شفاف کریستالی طلایی
                    finalColor += lightAmber * (spec1 * 1.4 + spec2 * 0.4);

                    // آلفای متراکم و شارپ با عمق سه‌بعدی
                    float alpha = clamp(0.94 + rimSharp * 0.06, 0.90, 1.0);

                    gl_FragColor = vec4(finalColor, alpha);
                }
            `;

            this.program = this.createProgram(vsSource, fsSource);
            gl.useProgram(this.program);

            this.uProjection = gl.getUniformLocation(this.program, "uProjection");
            this.uModelView = gl.getUniformLocation(this.program, "uModelView");
            this.uTime = gl.getUniformLocation(this.program, "uTime");
            this.uAudioLevel = gl.getUniformLocation(this.program, "uAudioLevel");
            this.uState = gl.getUniformLocation(this.program, "uState");
            this.uFreqData = gl.getUniformLocation(this.program, "uFreqData");

            this.aPosition = gl.getAttribLocation(this.program, "aPosition");
            this.aNormal = gl.getAttribLocation(this.program, "aNormal");
        }

        createProgram(vsSrc, fsSrc) {
            const gl = this.gl;
            const vs = gl.createShader(gl.VERTEX_SHADER);
            gl.shaderSource(vs, vsSrc);
            gl.compileShader(vs);
            if (!gl.getShaderParameter(vs, gl.COMPILE_STATUS)) {
                console.error("VS error:", gl.getShaderInfoLog(vs));
            }

            const fs = gl.createShader(gl.FRAGMENT_SHADER);
            gl.shaderSource(fs, fsSrc);
            gl.compileShader(fs);
            if (!gl.getShaderParameter(fs, gl.COMPILE_STATUS)) {
                console.error("FS error:", gl.getShaderInfoLog(fs));
            }

            const prog = gl.createProgram();
            gl.attachShader(prog, vs);
            gl.attachShader(prog, fs);
            gl.linkProgram(prog);
            if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
                console.error("Program link error:", gl.getProgramInfoLog(prog));
            }
            return prog;
        }

        initGeometry() {
            const gl = this.gl;
            const latitudeBands = 48;
            const longitudeBands = 48;
            const radius = 1.18;

            const positions = [];
            const normals = [];
            const indices = [];

            for (let lat = 0; lat <= latitudeBands; lat++) {
                const theta = (lat * Math.PI) / latitudeBands;
                const sinTheta = Math.sin(theta);
                const cosTheta = Math.cos(theta);

                for (let lon = 0; lon <= longitudeBands; lon++) {
                    const phi = (lon * 2 * Math.PI) / longitudeBands;
                    const sinPhi = Math.sin(phi);
                    const cosPhi = Math.cos(phi);

                    const x = cosPhi * sinTheta;
                    const y = cosTheta;
                    const z = sinPhi * sinTheta;

                    positions.push(radius * x, radius * y, radius * z);
                    normals.push(x, y, z);
                }
            }

            for (let lat = 0; lat < latitudeBands; lat++) {
                for (let lon = 0; lon < longitudeBands; lon++) {
                    const first = lat * (longitudeBands + 1) + lon;
                    const second = first + longitudeBands + 1;
                    indices.push(first, second, first + 1);
                    indices.push(second, second + 1, first + 1);
                }
            }

            this.indexCount = indices.length;

            this.posBuffer = gl.createBuffer();
            gl.bindBuffer(gl.ARRAY_BUFFER, this.posBuffer);
            gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(positions), gl.STATIC_DRAW);

            this.normBuffer = gl.createBuffer();
            gl.bindBuffer(gl.ARRAY_BUFFER, this.normBuffer);
            gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(normals), gl.STATIC_DRAW);

            this.indexBuffer = gl.createBuffer();
            gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
            gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(indices), gl.STATIC_DRAW);

            gl.enable(gl.BLEND);
            gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
            gl.enable(gl.DEPTH_TEST);
            gl.depthFunc(gl.LEQUAL);
        }

        setupEvents() {
            window.addEventListener('resize', () => this.resize());
        }

        resize() {
            if (!this.canvas || !this.gl) return;
            const dpr = Math.min(window.devicePixelRatio || 1, 2);
            const displayWidth = Math.round((this.canvas.clientWidth || 280) * dpr);
            const displayHeight = Math.round((this.canvas.clientHeight || 280) * dpr);

            if (displayWidth > 0 && displayHeight > 0 && 
                (this.canvas.width !== displayWidth || this.canvas.height !== displayHeight)) {
                this.canvas.width = displayWidth;
                this.canvas.height = displayHeight;
                this.gl.viewport(0, 0, this.canvas.width, this.canvas.height);
            }
        }

        setState(newState) {
            this.state = newState;
            if (newState === 'processing') {
                this.targetSpeed = 4.5;
            } else if (newState === 'listening' || newState === 'speaking') {
                this.targetSpeed = 2.2;
            } else {
                this.targetSpeed = 1.0;
            }
            // اطمینان از تنظیم سایز بعد از هر تغییر وضعیت
            setTimeout(() => this.resize(), 50);
        }

        setAudioData(level, freqs) {
            this.audioLevel = Math.max(0, Math.min(1.5, level));
            if (freqs && freqs.length) {
                for (let i = 0; i < 16; i++) {
                    this.audioFreqs[i] = freqs[i] || 0.0;
                }
            }
        }

        render() {
            const gl = this.gl;
            if (!gl) return;

            // اگر کانواس عرض صفر داشت (مثلاً در تب یا کانتینر مخفی بود)، چک مجدد سایز
            if (this.canvas.width === 0 || this.canvas.height === 0 || this.canvas.clientWidth > 0 && Math.abs(this.canvas.width - this.canvas.clientWidth) > 5) {
                this.resize();
            }

            this.time += 0.016;
            this.currentSpeed += (this.targetSpeed - this.currentSpeed) * 0.08;
            this.rotationAngle += 0.015 * this.currentSpeed;

            gl.clearColor(0, 0, 0, 0);
            gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

            gl.useProgram(this.program);

            const aspect = (this.canvas.width || 1) / (this.canvas.height || 1);
            const proj = this.createPerspectiveMatrix(45, aspect, 0.1, 100.0);
            const modelView = this.createModelViewMatrix(this.rotationAngle);

            gl.uniformMatrix4fv(this.uProjection, false, proj);
            gl.uniformMatrix4fv(this.uModelView, false, modelView);
            gl.uniform1f(this.uTime, this.time);
            gl.uniform1f(this.uAudioLevel, this.audioLevel);

            let stateNum = 0.0;
            if (this.state === 'listening') stateNum = 1.0;
            else if (this.state === 'speaking') stateNum = 2.0;
            else if (this.state === 'processing') stateNum = 3.0;
            gl.uniform1f(this.uState, stateNum);

            gl.uniform1fv(this.uFreqData, this.audioFreqs);

            gl.bindBuffer(gl.ARRAY_BUFFER, this.posBuffer);
            gl.enableVertexAttribArray(this.aPosition);
            gl.vertexAttribPointer(this.aPosition, 3, gl.FLOAT, false, 0, 0);

            gl.bindBuffer(gl.ARRAY_BUFFER, this.normBuffer);
            gl.enableVertexAttribArray(this.aNormal);
            gl.vertexAttribPointer(this.aNormal, 3, gl.FLOAT, false, 0, 0);

            gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
            gl.drawElements(gl.TRIANGLES, this.indexCount, gl.UNSIGNED_SHORT, 0);
        }

        createPerspectiveMatrix(fovDeg, aspect, near, far) {
            const fovRad = (fovDeg * Math.PI) / 180;
            const f = 1.0 / Math.tan(fovRad / 2);
            return new Float32Array([
                f / aspect, 0, 0, 0,
                0, f, 0, 0,
                0, 0, (far + near) / (near - far), -1,
                0, 0, (2 * far * near) / (near - far), 0
            ]);
        }

        createModelViewMatrix(rot) {
            const cosY = Math.cos(rot);
            const sinY = Math.sin(rot);
            const cosX = Math.cos(0.28);
            const sinX = Math.sin(0.28);

            return new Float32Array([
                cosY, sinX * sinY, -cosX * sinY, 0,
                0, cosX, sinX, 0,
                sinY, -sinX * cosY, cosX * cosY, 0,
                0, 0, -3.3, 1
            ]);
        }

        startLoop() {
            const loop = () => {
                this.render();
                this.animFrameId = requestAnimationFrame(loop);
            };
            this.animFrameId = requestAnimationFrame(loop);
        }

        init2DFallback() {
            const ctx = this.canvas.getContext('2d');
            let t = 0;
            const loop2D = () => {
                t += 0.03;
                const w = this.canvas.width || 280;
                const h = this.canvas.height || 280;
                ctx.clearRect(0, 0, w, h);

                const grad = ctx.createRadialGradient(w/2, h/2, 10, w/2, h/2, w*0.48);
                grad.addColorStop(0, '#0A0A0C');
                grad.addColorStop(0.55, '#D4AF37');
                grad.addColorStop(1, '#FFDF73');

                ctx.beginPath();
                ctx.arc(w/2, h/2, w*0.4 + Math.sin(t)*5, 0, Math.PI*2);
                ctx.fillStyle = grad;
                ctx.fill();

                // رسم خطوط موج صوتی فالبک طلایی
                ctx.strokeStyle = 'rgba(255, 223, 115, 0.85)';
                ctx.lineWidth = 2.5;
                ctx.beginPath();
                for (let x = 0; x < w; x += 5) {
                    const y = h/2 + Math.sin(x * 0.05 + t * 4) * 22;
                    if (x === 0) ctx.moveTo(x, y);
                    else ctx.lineTo(x, y);
                }
                ctx.stroke();

                requestAnimationFrame(loop2D);
            };
            loop2D();
        }

        destroy() {
            if (this.animFrameId) {
                cancelAnimationFrame(this.animFrameId);
            }
        }
    }

    window.Saghf3DOrb = Saghf3DOrb;

    // initSaghf3DOrb: راه‌اندازی یک canvas به صورت singleton
    window.initSaghf3DOrb = function(canvasId) {
        canvasId = canvasId || 'saghf3DOrbCanvas';
        const key = '__saghfOrb_' + canvasId;
        if (!window[key]) {
            const canvasEl = typeof canvasId === 'string' ? document.getElementById(canvasId) : canvasId;
            if (canvasEl) {
                window[key] = new Saghf3DOrb(canvasEl);
            }
        }
        return window[key];
    };

    // initWebGlOrbs: راه‌اندازی هر دو canvas (standby + active) - مدیریت شده توسط ai_orb.js
    window.initWebGlOrbs = function() {
        const instances = {};
        const standbyCanvas = document.getElementById('saghf3DOrbCanvas');
        if (standbyCanvas && !window.__saghfOrb_standby) {
            window.__saghfOrb_standby = new Saghf3DOrb(standbyCanvas);
        }
        instances.standby = window.__saghfOrb_standby || null;

        const activeCanvas = document.getElementById('saghf3DOrbCanvasActive');
        if (activeCanvas && !window.__saghfOrb_active) {
            window.__saghfOrb_active = new Saghf3DOrb(activeCanvas);
        }
        instances.active = window.__saghfOrb_active || null;

        return instances;
    };

    // بدون راه‌اندازی خودکار - مدیریت توسط ai_orb.js
})();
