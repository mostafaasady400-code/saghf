/**
 * ═══════════════════════════════════════════════════════════════════════════
 *  SAGHF LUXURY AI ORB v3.0 — Three.js + Custom GLSL Shaders
 *  موتور گوی سه‌بعدی فوق‌لوکس دستیار هوش مصنوعی سقف
 * ═══════════════════════════════════════════════════════════════════════════
 *  Visual Identity:
 *    • Core: Deep Obsidian Black (#0A0A0C)
 *    • Accent: Liquid Gold (#D4AF37 → #FFDF73)
 *    • Material: Glassmorphism + Metallic Gold Rim + Inner Glow
 *
 *  States: 'idle' | 'listening' | 'thinking' | 'speaking'
 *
 *  Features:
 *    ✦ Simplex 3D Noise vertex displacement (organic jelly motion)
 *    ✦ 1200 anti-gravity gold dust particles with orbital physics
 *    ✦ Mouse parallax tilt (3-axis smooth lerp)
 *    ✦ Audio-reactive: vertex amplitude + particle speed + inner glow
 *    ✦ CSS-based bloom (drop-shadow + filter) — no post-processing needed
 *    ✦ 60fps optimized with DPR clamping
 * ═══════════════════════════════════════════════════════════════════════════
 */

(function () {
    'use strict';

    // ─── Simplex 3D Noise (compact, GPU-quality) ────────────────────────
    // Based on Stefan Gustavson's GLSL implementation
    const SIMPLEX_NOISE_GLSL = `
        vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
        vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
        vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
        vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

        float snoise(vec3 v) {
            const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
            const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);

            vec3 i  = floor(v + dot(v, C.yyy));
            vec3 x0 = v - i + dot(i, C.xxx);

            vec3 g = step(x0.yzx, x0.xyz);
            vec3 l = 1.0 - g;
            vec3 i1 = min(g.xyz, l.zxy);
            vec3 i2 = max(g.xyz, l.zxy);

            vec3 x1 = x0 - i1 + C.xxx;
            vec3 x2 = x0 - i2 + C.yyy;
            vec3 x3 = x0 - D.yyy;

            i = mod289(i);
            vec4 p = permute(permute(permute(
                i.z + vec4(0.0, i1.z, i2.z, 1.0))
              + i.y + vec4(0.0, i1.y, i2.y, 1.0))
              + i.x + vec4(0.0, i1.x, i2.x, 1.0));

            float n_ = 0.142857142857;
            vec3 ns = n_ * D.wyz - D.xzx;

            vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
            vec4 x_ = floor(j * ns.z);
            vec4 y_ = floor(j - 7.0 * x_);

            vec4 x = x_ * ns.x + ns.yyyy;
            vec4 y = y_ * ns.x + ns.yyyy;
            vec4 h = 1.0 - abs(x) - abs(y);

            vec4 b0 = vec4(x.xy, y.xy);
            vec4 b1 = vec4(x.zw, y.zw);

            vec4 s0 = floor(b0) * 2.0 + 1.0;
            vec4 s1 = floor(b1) * 2.0 + 1.0;
            vec4 sh = -step(h, vec4(0.0));

            vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
            vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;

            vec3 p0 = vec3(a0.xy, h.x);
            vec3 p1 = vec3(a0.zw, h.y);
            vec3 p2 = vec3(a1.xy, h.z);
            vec3 p3 = vec3(a1.zw, h.w);

            vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));
            p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;

            vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
            m = m * m;
            return 42.0 * dot(m * m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
        }
    `;

    // ─── Vertex Shader ──────────────────────────────────────────────────
    const VERTEX_SHADER = `
        ${SIMPLEX_NOISE_GLSL}

        uniform float uTime;
        uniform float uAudioLevel;
        uniform float uState;  // 0=idle, 1=listening, 2=thinking, 3=speaking
        uniform vec2  uMouseTilt;

        varying vec3  vNormal;
        varying vec3  vPosition;
        varying vec3  vWorldPosition;
        varying float vDisplacement;
        varying float vFresnel;

        void main() {
            vec3 pos = position;
            vec3 norm = normal;
            float disp = 0.0;

            // ── ۱. Simplex Noise ارگانیک (۳ لایه octave) ──
            float n1 = snoise(pos * 1.8 + uTime * 0.35) * 0.55;
            float n2 = snoise(pos * 3.5 + uTime * 0.6)  * 0.30;
            float n3 = snoise(pos * 7.0 + uTime * 0.9)  * 0.15;
            float organicNoise = n1 + n2 + n3;

            // ── ۲. رفتار بر اساس حالت ──
            if (uState < 0.5) {
                // IDLE: تنفس نرم + نویز ملایم
                float breathe = sin(uTime * 1.6) * 0.025 + 0.01;
                disp = organicNoise * 0.06 + breathe;

            } else if (uState < 1.5) {
                // LISTENING: واکنش شدید به صدا
                float audioBoost = uAudioLevel * 0.35;
                float sharpWave = sin(pos.y * 12.0 + uTime * 5.5) * audioBoost;
                sharpWave += cos(pos.x * 9.0 - uTime * 4.2) * audioBoost * 0.6;
                disp = organicNoise * (0.08 + audioBoost) + sharpWave;

            } else if (uState < 2.5) {
                // THINKING: گرداب مارپیچی + نور متمرکز
                float vortexAngle = atan(pos.z, pos.x) * 3.0 + uTime * 4.5;
                float vortex = sin(vortexAngle + pos.y * 5.0) * 0.09;
                float concentrate = smoothstep(1.2, 0.0, length(pos.xy)) * 0.04;
                disp = organicNoise * 0.07 + vortex + concentrate;

            } else {
                // SPEAKING: پالس‌های هارمونیک نرم
                float pulse1 = sin(pos.y * 4.0 + uTime * 3.8) * 0.07;
                float pulse2 = sin(pos.x * 3.0 - uTime * 2.5 + pos.z * 2.0) * 0.05;
                float harmonic = (pulse1 + pulse2) * (0.7 + uAudioLevel * 0.5);
                disp = organicNoise * 0.06 + harmonic;
            }

            vDisplacement = disp;
            pos += norm * disp;

            // ── ۳. Mouse Parallax Tilt ──
            float tiltX = uMouseTilt.x * 0.15;
            float tiltY = uMouseTilt.y * 0.15;
            mat3 tiltMat = mat3(
                cos(tiltY),  0.0, sin(tiltY),
                0.0,         1.0, 0.0,
                -sin(tiltY), 0.0, cos(tiltY)
            ) * mat3(
                1.0, 0.0,        0.0,
                0.0, cos(tiltX), -sin(tiltX),
                0.0, sin(tiltX), cos(tiltX)
            );
            pos = tiltMat * pos;
            norm = tiltMat * norm;

            vNormal = normalize(normalMatrix * norm);
            vPosition = pos;
            vWorldPosition = (modelMatrix * vec4(pos, 1.0)).xyz;

            // ── ۴. Fresnel محاسبه ──
            vec3 viewDir = normalize(cameraPosition - vWorldPosition);
            vFresnel = 1.0 - max(dot(viewDir, vNormal), 0.0);

            gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
        }
    `;

    // ─── Fragment Shader (Cybernetic Gold & Obsidian Core) ───────────────
    const FRAGMENT_SHADER = `
        uniform float uTime;
        uniform float uState;
        uniform float uAudioLevel;
        uniform float uInnerGlowIntensity;

        varying vec3  vNormal;
        varying vec3  vPosition;
        varying vec3  vWorldPosition;
        varying float vDisplacement;
        varying float vFresnel;

        void main() {
            // ── پالت رنگی فوق‌لوکس مشکی آبسیدین و طلایی متالیک ──
            vec3 obsidianCore = vec3(0.04, 0.04, 0.048);    // #0A0A0C آبسیدین کیهانی عمیق
            vec3 metallicGold = vec3(0.831, 0.686, 0.216);  // #D4AF37 طلایی سلطنتی سقف
            vec3 radiantGold  = vec3(1.0, 0.843, 0.0);      // #FFD700 طلایی درخشان
            vec3 lightAmber   = vec3(1.0, 0.92, 0.65);       // #FFDF73 هایلایت طلایی
            vec3 deepBronze   = vec3(0.55, 0.40, 0.12);      // #8C661F برنز عمیق متالیک
            vec3 deepBlack    = vec3(0.012, 0.012, 0.015);

            vec3 normal = normalize(vNormal);

            // ۱. هسته آبسیدین عمیق با بافت ظریف متالیک
            float centerDist = length(vPosition) / 1.62;
            vec3 baseColor = mix(deepBlack, obsidianCore, smoothstep(0.0, 0.85, centerDist));

            // سرعت گردش جریان بر اساس وضعیت سیستم (پایش زنده و پردازش هوشمند = شتاب ۳ برابری)
            float speedMult = (uState > 1.5) ? 3.2 : ((uState > 0.5) ? (2.0 + uAudioLevel * 2.5) : 1.0);

            // ۲. خطوط مدار الکتریکی سایبرنتیک (Cybernetic Circuit Traces & Micro-Bus Channels)
            vec3 cp = vPosition * 4.2;
            vec3 fp = fract(cp);
            
            // شیارهای اتصالات الکترونیکی عمودی و افقی برد
            float trackX = smoothstep(0.06, 0.0, abs(fp.y - 0.5));
            float trackY = smoothstep(0.06, 0.0, abs(fp.x - 0.5));
            float trackZ = smoothstep(0.06, 0.0, abs(fp.z - 0.5));
            float diagTrace = smoothstep(0.05, 0.0, abs((fp.x + fp.y) - 1.0));
            
            // پدهای اتصال چیپست (Micro-Vias & Solder Nodes)
            float viaDist = length(fp - 0.5);
            float vias = smoothstep(0.18, 0.12, viaDist) * smoothstep(0.04, 0.08, viaDist);
            
            float circuitNetwork = max(trackX, max(trackY, trackZ)) * 0.75 + diagTrace * 0.6 + vias * 1.3;

            // ۳. پالس‌های نوری متحرک در طول مدارهای طلایی بر مبنای زمان (uTime)
            float flowAxis = (vPosition.x * 2.8 + vPosition.y * 3.6 + vPosition.z * 2.2);
            float pulse = pow(sin(flowAxis * 3.5 - uTime * speedMult * 2.8) * 0.5 + 0.5, 7.0);
            float microPulse = pow(sin(flowAxis * 7.0 + uTime * speedMult * 4.0) * 0.5 + 0.5, 12.0);

            // اعمال رنگ طلایی روی خطوط پردازشی با پالس‌های درخشان
            vec3 circuitColor = mix(deepBronze, metallicGold, 0.6);
            circuitColor = mix(circuitColor, radiantGold, pulse * 0.85 + microPulse * 0.5);
            baseColor += circuitColor * circuitNetwork * (0.45 + pulse * 1.6 + microPulse * 1.2);

            // ۴. Inner Glow طلایی گرم از مرکز هسته
            float innerGlow = smoothstep(0.92, 0.0, centerDist) * uInnerGlowIntensity;
            vec3 warmGlow = mix(deepBronze, metallicGold, sin(uTime * 1.5 * speedMult + centerDist * 3.0) * 0.5 + 0.5);
            baseColor += warmGlow * innerGlow * 0.9;

            // ۵. Fresnel Rim Light لوکس طلایی گرم (Warm Golden Bloom)
            float rimSharp = pow(vFresnel, 2.6);
            float rimBroad = pow(vFresnel, 1.3);
            vec3 rimColor = mix(metallicGold, radiantGold, smoothstep(-0.5, 0.8, vNormal.y));
            baseColor += rimColor * rimSharp * 2.4;
            baseColor += deepBronze * rimBroad * 0.5;

            // ۶. هایلایت‌های کریستالی صیقلی اسپکولار فلزی
            vec3 viewDir = normalize(cameraPosition - vWorldPosition);
            vec3 lightDir1 = normalize(vec3(0.5, 0.8, 1.0));
            vec3 halfDir1 = normalize(lightDir1 + viewDir);
            float spec1 = pow(max(dot(normal, halfDir1), 0.0), 80.0);

            vec3 lightDir2 = normalize(vec3(-0.6, -0.4, 0.8));
            vec3 halfDir2 = normalize(lightDir2 + viewDir);
            float spec2 = pow(max(dot(normal, halfDir2), 0.0), 40.0);

            baseColor += lightAmber * (spec1 * 1.4 + spec2 * 0.4);

            // ۷. واکنش دینامیک به حالت‌های شنود، گفتار و تحلیل داده
            if (uState > 0.5 && uState < 1.5) {
                // Listening: امواج طلایی پالس‌زن متناسب با دامنه صدا
                baseColor += radiantGold * (uAudioLevel * 0.85);
                baseColor += lightAmber * abs(vDisplacement) * (uAudioLevel * 3.2);
            } else if (uState > 1.5 && uState < 2.5) {
                // Thinking / Analyzing: تمرکز پرتوهای نوری طلایی در هسته
                float thinkPulse = sin(uTime * 7.0) * 0.5 + 0.5;
                baseColor += radiantGold * thinkPulse * innerGlow * 1.8;
            } else if (uState > 2.5) {
                // Speaking: گردش پرتوهای نورانی هارمونیک
                float speechPulse = sin(uTime * 5.5) * 0.5 + 0.5;
                baseColor += mix(metallicGold, lightAmber, speechPulse) * speechPulse * 0.45;
            }

            // ۸. آلفای متراکم و شارپ با عمق سه‌بعدی
            float alpha = clamp(0.94 + rimSharp * 0.06, 0.90, 1.0);
            gl_FragColor = vec4(baseColor, alpha);
        }
    `;

    // ═════════════════════════════════════════════════════════════════════
    //  MAIN CLASS
    // ═════════════════════════════════════════════════════════════════════

    class SaghfLuxuryOrb {
        constructor(canvasEl) {
            this.canvas = typeof canvasEl === 'string'
                ? document.getElementById(canvasEl)
                : canvasEl;
            if (!this.canvas) return;

            // State
            this.state = 'idle';
            this.audioLevel = 0.0;
            this.audioFreqs = new Float32Array(16);
            this.targetState = 0.0;
            this.currentState = 0.0;
            this.targetGlow = 0.4;
            this.currentGlow = 0.4;
            this.mouseX = 0.0;
            this.mouseY = 0.0;
            this.targetMouseX = 0.0;
            this.targetMouseY = 0.0;
            this.animFrameId = null;
            this.isDestroyed = false;

            try {
                this.initRenderer();
                this.initScene();
                this.initOrb();
                this.initParticles();
                this.initEvents();
                this.resize();
                this.startLoop();
            } catch (e) {
                console.warn('[SaghfLuxuryOrb] Init failed, falling back:', e);
                this.initFallback2D();
            }
        }

        // ─── Renderer ───────────────────────────────────────────────────
        initRenderer() {
            const w = this.canvas.clientWidth || 340;
            const h = this.canvas.clientHeight || 340;

            this.renderer = new THREE.WebGLRenderer({
                canvas: this.canvas,
                antialias: true,
                alpha: true,
                powerPreference: 'high-performance'
            });
            this.renderer.setSize(w, h);
            this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
            this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
            this.renderer.toneMappingExposure = 1.35;
        }

        // ─── Scene + Camera + Lights ────────────────────────────────────
        initScene() {
            this.scene = new THREE.Scene();
            this.camera = new THREE.PerspectiveCamera(
                42,
                (this.canvas.clientWidth || 340) / (this.canvas.clientHeight || 340),
                0.1,
                100
            );
            this.camera.position.z = 5.5;

            // Ambient
            this.scene.add(new THREE.AmbientLight(0x100c04, 1.4));

            // Key Light: طلایی متالیک درخشان (#FFD700)
            this.keyLight = new THREE.PointLight(0xFFD700, 3.8, 22);
            this.keyLight.position.set(3.5, 3.2, 4.5);
            this.scene.add(this.keyLight);

            // Fill Light: طلایی سلطنتی سقف (#D4AF37)
            this.fillLight = new THREE.PointLight(0xD4AF37, 2.8, 18);
            this.fillLight.position.set(-3.5, -2.8, 3.5);
            this.scene.add(this.fillLight);

            // Rim Light: امبر طلایی روشن (#FFDF73)
            this.rimLight = new THREE.PointLight(0xFFDF73, 3.2, 22);
            this.rimLight.position.set(0, 0, -5);
            this.scene.add(this.rimLight);

            this.clock = new THREE.Clock();
        }

        // ─── Orb Geometry + Shader Material ─────────────────────────────
        initOrb() {
            this.orbGroup = new THREE.Group();
            this.scene.add(this.orbGroup);

            // ۱. کره اصلی با ShaderMaterial سفارشی
            const orbGeo = new THREE.IcosahedronGeometry(1.52, 6);

            this.orbUniforms = {
                uTime:              { value: 0.0 },
                uState:             { value: 0.0 },
                uAudioLevel:        { value: 0.0 },
                uMouseTilt:         { value: new THREE.Vector2(0, 0) },
                uInnerGlowIntensity:{ value: 0.4 }
            };

            const orbMat = new THREE.ShaderMaterial({
                vertexShader: VERTEX_SHADER,
                fragmentShader: FRAGMENT_SHADER,
                uniforms: this.orbUniforms,
                transparent: true,
                side: THREE.FrontSide,
                depthWrite: true
            });

            this.orbMesh = new THREE.Mesh(orbGeo, orbMat);
            this.orbGroup.add(this.orbMesh);

            // ۲. پوسته وایرفریم شیشه‌ای سایبرنتیک با درخشش طلایی (Cybernetic Gold Wireframe Shell)
            const shellGeo = new THREE.IcosahedronGeometry(1.68, 4);
            const shellMat = new THREE.MeshPhysicalMaterial({
                color: 0x0A0A0C,
                emissive: 0xD4AF37,
                emissiveIntensity: 0.28,
                roughness: 0.18,
                metalness: 0.95,
                clearcoat: 1.0,
                clearcoatRoughness: 0.05,
                transparent: true,
                opacity: 0.25,
                wireframe: true,
                blending: THREE.AdditiveBlending
            });
            this.shellMesh = new THREE.Mesh(shellGeo, shellMat);
            this.orbGroup.add(this.shellMesh);

            // ۳. شبکه ذرات هولوگرام داده‌های طلایی سقف (Gold Hologram Point-Cloud Lattice)
            const PTS = 1600;
            const ptPos = new Float32Array(PTS * 3);
            const ptCols = new Float32Array(PTS * 3);
            const cGold1 = new THREE.Color(0xFFD700);
            const cGold2 = new THREE.Color(0xD4AF37);
            const cGold3 = new THREE.Color(0xFFDF73);

            for (let i = 0; i < PTS; i++) {
                const phi = Math.acos(-1 + (2 * i) / PTS);
                const theta = Math.sqrt(PTS * Math.PI) * phi;
                const r = 1.58;
                ptPos[i * 3]     = r * Math.sin(phi) * Math.cos(theta);
                ptPos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
                ptPos[i * 3 + 2] = r * Math.cos(phi);

                const cChoice = Math.random();
                const col = cChoice < 0.52 ? cGold1 : (cChoice < 0.82 ? cGold2 : cGold3);
                ptCols[i * 3]     = col.r;
                ptCols[i * 3 + 1] = col.g;
                ptCols[i * 3 + 2] = col.b;
            }
            const ptGeo = new THREE.BufferGeometry();
            ptGeo.setAttribute('position', new THREE.BufferAttribute(ptPos, 3));
            ptGeo.setAttribute('color', new THREE.BufferAttribute(ptCols, 3));
            const ptMat = new THREE.PointsMaterial({
                size: 0.038,
                vertexColors: true,
                transparent: true,
                opacity: 0.88,
                blending: THREE.AdditiveBlending,
                sizeAttenuation: true,
                depthWrite: false
            });
            this.hologramGlobe = new THREE.Points(ptGeo, ptMat);
            this.orbGroup.add(this.hologramGlobe);

            // ۴. حلقه‌های مداری سه‌گانه ژیروسکوپ طلایی (Orbital Gold Planetary Rings)
            this.ring1 = this._createRing(2.18, 0.016, 0xFFD700, 0.85);
            this.ring1.rotation.x = Math.PI * 0.35;
            this.ring1.rotation.y = Math.PI * 0.14;
            this.orbGroup.add(this.ring1);

            this.ring2 = this._createRing(2.36, 0.014, 0xD4AF37, 0.75);
            this.ring2.rotation.x = -Math.PI * 0.26;
            this.ring2.rotation.z = Math.PI * 0.24;
            this.orbGroup.add(this.ring2);

            this.ring3 = this._createRing(2.55, 0.012, 0xAA7C11, 0.60);
            this.ring3.rotation.x = Math.PI * 0.58;
            this.ring3.rotation.z = -Math.PI * 0.32;
            this.orbGroup.add(this.ring3);
        }

        _createRing(radius, tube, color, opacity) {
            const geo = new THREE.TorusGeometry(radius, tube, 16, 128);
            const mat = new THREE.MeshBasicMaterial({
                color: color,
                transparent: true,
                opacity: opacity,
                blending: THREE.AdditiveBlending
            });
            return new THREE.Mesh(geo, mat);
        }

        // ─── Ambient Hologram Data Particles ────────────────────────────
        initParticles() {
            const COUNT = 1200;
            const positions = new Float32Array(COUNT * 3);
            const colors    = new Float32Array(COUNT * 3);
            const sizes     = new Float32Array(COUNT);
            this.particleData = new Float32Array(COUNT * 4); // angle, radius, speed, yOffset

            const colorA = new THREE.Color(0xFFD700); // Radiant Gold
            const colorB = new THREE.Color(0xD4AF37); // Metallic Gold
            const colorC = new THREE.Color(0xFFDF73); // Light Amber

            for (let i = 0; i < COUNT; i++) {
                const theta = Math.random() * Math.PI * 2;
                const phi   = Math.acos(2 * Math.random() - 1);
                const r     = 1.9 + Math.random() * 1.6;

                const sinPhi = Math.sin(phi);
                positions[i * 3]     = r * sinPhi * Math.cos(theta);
                positions[i * 3 + 1] = r * sinPhi * Math.sin(theta);
                positions[i * 3 + 2] = r * Math.cos(phi);

                const colorChoice = Math.random();
                const c = colorChoice < 0.50 ? colorA : (colorChoice < 0.82 ? colorB : colorC);
                colors[i * 3]     = c.r;
                colors[i * 3 + 1] = c.g;
                colors[i * 3 + 2] = c.b;

                sizes[i] = 1.4 + Math.random() * 2.2;

                this.particleData[i * 4]     = theta;
                this.particleData[i * 4 + 1] = r;
                this.particleData[i * 4 + 2] = 0.003 + Math.random() * 0.008;
                this.particleData[i * 4 + 3] = Math.random() * Math.PI * 2;
            }

            const geo = new THREE.BufferGeometry();
            geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
            geo.setAttribute('color',    new THREE.BufferAttribute(colors, 3));
            geo.setAttribute('size',     new THREE.BufferAttribute(sizes, 1));

            const mat = new THREE.PointsMaterial({
                size: 0.045,
                vertexColors: true,
                transparent: true,
                opacity: 0.65,
                blending: THREE.AdditiveBlending,
                sizeAttenuation: true,
                depthWrite: false
            });

            this.particles = new THREE.Points(geo, mat);
            this.orbGroup.add(this.particles);
        }

        // ─── Events ─────────────────────────────────────────────────────
        initEvents() {
            // Resize
            this._onResize = () => this.resize();
            window.addEventListener('resize', this._onResize);

            // Mouse Parallax
            this._onMouseMove = (e) => {
                const rect = this.canvas.getBoundingClientRect();
                const cx = rect.left + rect.width / 2;
                const cy = rect.top + rect.height / 2;
                this.targetMouseX = ((e.clientX - cx) / (rect.width / 2)) * 0.4;
                this.targetMouseY = ((e.clientY - cy) / (rect.height / 2)) * 0.3;
            };

            this._onMouseLeave = () => {
                this.targetMouseX = 0;
                this.targetMouseY = 0;
            };

            document.addEventListener('mousemove', this._onMouseMove);
            this.canvas.addEventListener('mouseleave', this._onMouseLeave);
        }

        // ─── State Management ───────────────────────────────────────────
        setState(newState) {
            const stateMap = { idle: 0, standby: 0, listening: 1, thinking: 2, processing: 2, speaking: 3 };
            this.state = newState;
            this.targetState = stateMap[newState] || 0;

            // Inner glow intensity per state
            const glowMap = { idle: 0.4, standby: 0.4, listening: 0.85, thinking: 1.2, processing: 1.2, speaking: 0.7 };
            this.targetGlow = glowMap[newState] || 0.4;
        }

        setAudioData(level, freqs) {
            this.audioLevel = Math.max(0, Math.min(1.5, level));
            if (freqs && freqs.length) {
                for (let i = 0; i < 16; i++) {
                    this.audioFreqs[i] = freqs[i] || 0.0;
                }
            }
        }

        // ─── Resize ─────────────────────────────────────────────────────
        resize() {
            if (!this.canvas || !this.renderer) return;
            const w = this.canvas.clientWidth || 340;
            const h = this.canvas.clientHeight || 340;
            if (w === 0 || h === 0) return;

            this.camera.aspect = w / h;
            this.camera.updateProjectionMatrix();
            this.renderer.setSize(w, h);
        }

        // ─── Animation Loop ─────────────────────────────────────────────
        startLoop() {
            const animate = () => {
                if (this.isDestroyed) return;
                this.animFrameId = requestAnimationFrame(animate);
                this.update();
            };
            this.animFrameId = requestAnimationFrame(animate);
        }

        update() {
            const time = this.clock.getElapsedTime();
            const dt = this.clock.getDelta();

            // Smooth state transitions
            this.currentState += (this.targetState - this.currentState) * 0.06;
            this.currentGlow  += (this.targetGlow  - this.currentGlow)  * 0.05;
            this.mouseX += (this.targetMouseX - this.mouseX) * 0.04;
            this.mouseY += (this.targetMouseY - this.mouseY) * 0.04;

            // ── Update Uniforms ──
            this.orbUniforms.uTime.value = time;
            this.orbUniforms.uState.value = this.currentState;
            this.orbUniforms.uAudioLevel.value = this.audioLevel;
            this.orbUniforms.uMouseTilt.value.set(this.mouseY, this.mouseX);
            this.orbUniforms.uInnerGlowIntensity.value = this.currentGlow;

            // ── Shell rotation ──
            const shellSpeed = this.currentState > 1.5 ? 0.025 : 0.008;
            this.shellMesh.rotation.y += shellSpeed;
            this.shellMesh.rotation.x = Math.sin(time * 0.6) * 0.05;

            // ── Ring & Hologram Globe rotation ──
            const ringBaseSpeed = this.currentState > 1.5 ? 0.035 : 0.012;
            const audioRingBoost = this.audioLevel * 0.03;
            if (this.ring1) this.ring1.rotation.z += ringBaseSpeed + audioRingBoost;
            if (this.ring2) this.ring2.rotation.y -= (ringBaseSpeed * 0.85) + audioRingBoost;
            if (this.ring3) {
                this.ring3.rotation.x += (ringBaseSpeed * 0.65) + audioRingBoost;
                this.ring3.rotation.z -= (ringBaseSpeed * 0.35);
            }
            if (this.hologramGlobe) {
                this.hologramGlobe.rotation.y += 0.004 + (this.audioLevel * 0.01);
                this.hologramGlobe.rotation.x = Math.sin(time * 0.4) * 0.05;
            }

            // ── Orb group subtle rotation ──
            this.orbGroup.rotation.y += 0.004;
            this.orbGroup.rotation.x = Math.sin(time * 0.5) * 0.03;

            // ── Light animation ──
            const lightPulse = Math.sin(time * 2.2) * 0.5 + 0.5;
            this.keyLight.intensity  = 2.8 + lightPulse * 0.8 + this.audioLevel * 2.0;
            this.fillLight.intensity = 1.8 + lightPulse * 0.5 + this.audioLevel * 1.0;
            this.rimLight.intensity  = 2.2 + Math.sin(time * 1.8) * 0.5;

            // ── Update Particles (Anti-Gravity Physics) ──
            this.updateParticles(time);

            // ── Render ──
            this.renderer.render(this.scene, this.camera);
        }

        updateParticles(time) {
            const posAttr = this.particles.geometry.attributes.position;
            const count = posAttr.count;
            const arr = posAttr.array;
            const d = this.particleData;

            const audioSpeedBoost = 1.0 + this.audioLevel * 2.5;
            const isActive = this.currentState > 0.5;

            for (let i = 0; i < count; i++) {
                const i4 = i * 4;
                const i3 = i * 3;

                // Orbit angle
                d[i4] += d[i4 + 2] * audioSpeedBoost;
                const angle  = d[i4];
                const radius = d[i4 + 1];
                const yPhase = d[i4 + 3];

                // Y oscillation (anti-gravity float)
                const yOsc = Math.sin(time * 0.8 + yPhase) * 0.4;
                const yNoise = Math.sin(time * 1.5 + i * 0.1) * 0.15;

                // Active state: particles expand slightly
                const rMult = isActive ? 1.0 + this.audioLevel * 0.3 : 1.0;

                arr[i3]     = Math.cos(angle) * radius * rMult;
                arr[i3 + 1] = yOsc + yNoise + Math.sin(angle * 0.5) * 0.3;
                arr[i3 + 2] = Math.sin(angle) * radius * rMult;
            }

            posAttr.needsUpdate = true;

            // Particle opacity flicker
            this.particles.material.opacity = 0.55 + Math.sin(time * 3.0) * 0.1 + this.audioLevel * 0.2;
            this.particles.rotation.y += 0.002;
        }

        // ─── 2D Fallback ────────────────────────────────────────────────
        initFallback2D() {
            const ctx = this.canvas.getContext('2d');
            if (!ctx) return;
            let t = 0;
            const w = this.canvas.width || 340;
            const h = this.canvas.height || 340;
            const cx = w / 2, cy = h / 2;

            const loop = () => {
                if (this.isDestroyed) return;
                t += 0.02;
                ctx.clearRect(0, 0, w, h);

                // Core glow
                const grad = ctx.createRadialGradient(cx, cy, 5, cx, cy, w * 0.42);
                grad.addColorStop(0, 'rgba(212, 175, 55, 0.4)');
                grad.addColorStop(0.4, 'rgba(10, 10, 12, 0.95)');
                grad.addColorStop(1, 'transparent');
                ctx.beginPath();
                ctx.arc(cx, cy, w * 0.38 + Math.sin(t) * 4, 0, Math.PI * 2);
                ctx.fillStyle = grad;
                ctx.fill();

                // Gold ring
                ctx.strokeStyle = 'rgba(212, 175, 55, 0.5)';
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.arc(cx, cy, w * 0.44, 0, Math.PI * 2);
                ctx.stroke();

                requestAnimationFrame(loop);
            };
            loop();
        }

        // ─── Destroy ────────────────────────────────────────────────────
        destroy() {
            this.isDestroyed = true;
            if (this.animFrameId) cancelAnimationFrame(this.animFrameId);

            window.removeEventListener('resize', this._onResize);
            document.removeEventListener('mousemove', this._onMouseMove);
            if (this.canvas) this.canvas.removeEventListener('mouseleave', this._onMouseLeave);

            if (this.renderer) {
                this.renderer.dispose();
                this.renderer.forceContextLoss();
            }
        }
    }

    // ═════════════════════════════════════════════════════════════════════
    //  GLOBAL EXPORTS
    // ═════════════════════════════════════════════════════════════════════

    window.SaghfLuxuryOrb = SaghfLuxuryOrb;

    // Backward-compatible aliases
    window.Saghf3DOrb = SaghfLuxuryOrb;

    // initWebGlOrbs: راه‌اندازی هر دو canvas
    window.initWebGlOrbs = function () {
        const instances = {};
        const standbyCanvas = document.getElementById('saghf3DOrbCanvas');
        if (standbyCanvas && !window.__saghfOrb_standby) {
            window.__saghfOrb_standby = new SaghfLuxuryOrb(standbyCanvas);
        }
        instances.standby = window.__saghfOrb_standby || null;

        const activeCanvas = document.getElementById('saghf3DOrbCanvasActive');
        if (activeCanvas && !window.__saghfOrb_active) {
            window.__saghfOrb_active = new SaghfLuxuryOrb(activeCanvas);
        }
        instances.active = window.__saghfOrb_active || null;

        return instances;
    };

    // بدون auto-init — مدیریت توسط ai_orb.js
})();
