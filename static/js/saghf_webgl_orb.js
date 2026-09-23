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

            // Fragment Shader: ایجاد ساختار کاملاً شفاف، شارپ، با هسته ابسیدین درخشان و امواج صوتی نئونی واضح
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
                    // هسته مشکی ابسیدین عمیق با ته‌رنگ کبالت لوکس
                    vec3 coreObsidian = vec3(0.04, 0.05, 0.09);

                    // پالت اختصاصی نئونی: آبی متالیک کریستالی (#00D2FF) و بنفش نئونی (#9B51E0)
                    vec3 metallicCyan = vec3(0.0, 0.85, 1.0);   // #00D2FF
                    vec3 neonViolet   = vec3(0.62, 0.28, 0.92);  // #9B51E0
                    vec3 electricBlue = vec3(0.12, 0.38, 0.98);

                    vec3 viewDir = normalize(-vPosition);
                    vec3 normal = normalize(vNormal);

                    // ۱. افکت فرنل لبه‌های بیرونی (Rim Glow شارپ و خیره‌کننده)
                    float nDotV = max(dot(viewDir, normal), 0.0);
                    float fresnel = 1.0 - nDotV;
                    float rimSharp = pow(fresnel, 2.4);
                    float rimBroad = pow(fresnel, 1.2);

                    // ۲. امواج صوتی سینوسی سه‌بعدی متحرک (Acoustic Sinusoidal Sound Waves)
                    float waveSpeed = uTime * 3.5;
                    float waveRibbon1 = pow(abs(sin(vPosition.y * 14.0 - waveSpeed + vDisplacement * 8.0)), 12.0);
                    float waveRibbon2 = pow(abs(cos(vPosition.z * 10.0 + waveSpeed * 0.8 + vPosition.x * 6.0)), 10.0);
                    float waveRibbon3 = pow(abs(sin((vPosition.x + vPosition.y) * 16.0 - waveSpeed * 1.2)), 16.0) * (0.4 + uAudioLevel * 0.8);
                    float totalSoundWave = waveRibbon1 * 1.1 + waveRibbon2 * 0.8 + waveRibbon3 * 1.2;

                    // ۳. گردش و گرداب پلاسما میان آبی متالیک و بنفش نئونی
                    float cycleSpeed = (uState > 2.5) ? 8.0 : 2.2;
                    float plasmaCycle = sin(uTime * cycleSpeed + vPosition.y * 3.2 + atan(vPosition.z, vPosition.x) * 2.0) * 0.5 + 0.5;
                    vec3 plasmaColor = mix(metallicCyan, neonViolet, plasmaCycle);

                    // ۴. بازتاب اسپکولار بلورین دوقلو (Dual Glossy Highlights شبیه شیشه کوارتز صیقلی)
                    vec3 lightDir1 = normalize(vec3(0.5, 0.8, 1.0));
                    vec3 halfDir1 = normalize(lightDir1 + viewDir);
                    float spec1 = pow(max(dot(normal, halfDir1), 0.0), 64.0);

                    vec3 lightDir2 = normalize(vec3(-0.6, -0.4, 0.7));
                    vec3 halfDir2 = normalize(lightDir2 + viewDir);
                    float spec2 = pow(max(dot(normal, halfDir2), 0.0), 32.0);

                    // ۵. ترکیب لایه‌های رنگی: هسته ابسیدین + نور پلاسما + نوارهای موج صوتی نئونی + ریم‌لایت
                    vec3 finalColor = coreObsidian;

                    // نورپردازی پایه پلاسما درون گوی
                    finalColor += mix(electricBlue, plasmaColor, 0.7) * (0.35 + 0.45 * plasmaCycle);

                    // پرتوهای امواج صوتی شارپ نئونی (آبی متالیک و بنفش)
                    finalColor += metallicCyan * totalSoundWave * 1.5;
                    finalColor += neonViolet * (waveRibbon2 * 1.1);

                    // تقویت درخشش هنگام مکالمه صوتی
                    if (uState > 0.5 && uState < 2.5) {
                        finalColor += plasmaColor * (uAudioLevel * 1.3);
                        finalColor += metallicCyan * (abs(vWaveIntensity) * 4.0);
                    } else if (uState > 2.5) {
                        finalColor += plasmaColor * 1.6;
                    }

                    // ریم لایت لبه‌ها (Rim Lighting)
                    finalColor += plasmaColor * (rimSharp * 1.8 + rimBroad * 0.4);

                    // هایلایت‌های شفاف کریستالی
                    finalColor += vec3(0.95, 1.0, 1.0) * (spec1 * 1.2 + spec2 * 0.35);

                    // آلفای قدرتمند و متراکم (برای اینکه در مرکز گوی مات و سیاه نشود و کاملاً حجم سه‌بعدی داشته باشد)
                    float alpha = clamp(0.92 + rimSharp * 0.08, 0.9, 1.0);

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
                grad.addColorStop(0, '#070A14');
                grad.addColorStop(0.55, '#00D2FF');
                grad.addColorStop(1, '#9B51E0');

                ctx.beginPath();
                ctx.arc(w/2, h/2, w*0.4 + Math.sin(t)*5, 0, Math.PI*2);
                ctx.fillStyle = grad;
                ctx.fill();

                // رسم خطوط موج صوتی فالبک
                ctx.strokeStyle = 'rgba(255, 255, 255, 0.7)';
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

    window.initSaghf3DOrb = function(canvasId = 'saghf3DOrbCanvas') {
        if (!window.__saghfOrbInstance) {
            const canvasEl = typeof canvasId === 'string' ? document.getElementById(canvasId) : canvasId;
            if (canvasEl) {
                window.__saghfOrbInstance = new Saghf3DOrb(canvasEl);
            }
        }
        return window.__saghfOrbInstance;
    };

    window.initWebGlOrbs = window.initSaghf3DOrb;

    // راه‌اندازی خودکار مستقل
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.initSaghf3DOrb();
        });
    } else {
        window.initSaghf3DOrb();
    }
})();
