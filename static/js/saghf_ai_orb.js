/**
 * ==========================================================================
 * SAGHF 3D LUXURY AI ORB (Three.js WebGL Engine)
 * Strictly: Deep Black Obsidian Core + Metallic Blue (#00D2FF) & Neon Purple (#9B51E0)
 * NO GOLD in the sphere.
 * States: 'standby' | 'listening' | 'processing' | 'speaking'
 * ==========================================================================
 */

class SaghfAiOrb {
    constructor(canvasId = 'ai-orb-canvas') {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) return;

        this.state = 'standby'; // 'standby' | 'listening' | 'processing' | 'speaking'
        this.audioLevel = 0;
        this.syntheticAudioPhase = 0;
        this.analyser = null;
        this.dataArray = null;
        this.isListeningMic = false;

        this.initThree();
        this.createSceneObjects();
        this.setupEvents();
        this.animate = this.animate.bind(this);
        requestAnimationFrame(this.animate);
    }

    initThree() {
        const width = this.canvas.clientWidth || 280;
        const height = this.canvas.clientHeight || 280;

        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
        this.camera.position.z = 6.2;

        this.renderer = new THREE.WebGLRenderer({
            canvas: this.canvas,
            antialias: true,
            alpha: true,
            powerPreference: 'high-performance'
        });
        this.renderer.setSize(width, height);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
        this.renderer.toneMappingExposure = 1.25;

        // Dynamic Dual-Color Lighting (Metallic Blue & Neon Purple only)
        this.ambientLight = new THREE.AmbientLight(0x04040a, 1.2);
        this.scene.add(this.ambientLight);

        // Metallic Blue Key Light (#00D2FF)
        this.blueLight = new THREE.PointLight(0x00d2ff, 3.2, 20);
        this.blueLight.position.set(4, 3, 5);
        this.scene.add(this.blueLight);

        // Neon Purple Rim Light (#9B51E0)
        this.purpleLight = new THREE.PointLight(0x9b51e0, 3.5, 20);
        this.purpleLight.position.set(-4, -3, 4);
        this.scene.add(this.purpleLight);

        this.clock = new THREE.Clock();
    }

    createSceneObjects() {
        this.orbGroup = new THREE.Group();
        this.scene.add(this.orbGroup);

        // 1. Central Core: Deep Obsidian Black Sphere (No Gold)
        const coreGeo = new THREE.IcosahedronGeometry(1.65, 5);
        const coreMat = new THREE.MeshPhysicalMaterial({
            color: 0x050508, // Deep obsidian black
            emissive: 0x020205,
            roughness: 0.12,
            metalness: 0.95,
            clearcoat: 1.0,
            clearcoatRoughness: 0.08,
            reflectivity: 0.9
        });
        this.coreMesh = new THREE.Mesh(coreGeo, coreMat);
        this.orbGroup.add(this.coreMesh);

        // 2. Outer Waveform Dynamic Displacement Energy Shell
        // Vertices deform in real-time with sound and fluid waves
        const energyGeo = new THREE.IcosahedronGeometry(1.85, 4);
        this.originalVertices = [];
        const posAttr = energyGeo.attributes.position;
        for (let i = 0; i < posAttr.count; i++) {
            this.originalVertices.push(new THREE.Vector3(
                posAttr.getX(i),
                posAttr.getY(i),
                posAttr.getZ(i)
            ));
        }

        // Metallic Blue & Neon Purple wireframe shader material
        this.energyMat = new THREE.MeshStandardMaterial({
            color: 0x00d2ff,
            emissive: 0x9b51e0,
            emissiveIntensity: 0.85,
            wireframe: true,
            transparent: true,
            opacity: 0.75,
            blending: THREE.AdditiveBlending
        });
        this.energyMesh = new THREE.Mesh(energyGeo, this.energyMat);
        this.orbGroup.add(this.energyMesh);

        // 3. Dual Orbiting Plasma Rings (Counter-Rotating Vortex)
        // Ring 1: Metallic Blue (#00D2FF)
        const ring1Geo = new THREE.TorusGeometry(2.35, 0.022, 16, 120);
        const ring1Mat = new THREE.MeshBasicMaterial({
            color: 0x00d2ff,
            transparent: true,
            opacity: 0.85,
            blending: THREE.AdditiveBlending
        });
        this.ring1 = new THREE.Mesh(ring1Geo, ring1Mat);
        this.ring1.rotation.x = Math.PI * 0.35;
        this.ring1.rotation.y = Math.PI * 0.15;
        this.orbGroup.add(this.ring1);

        // Ring 2: Neon Purple (#9B51E0)
        const ring2Geo = new THREE.TorusGeometry(2.52, 0.02, 16, 120);
        const ring2Mat = new THREE.MeshBasicMaterial({
            color: 0x9b51e0,
            transparent: true,
            opacity: 0.8,
            blending: THREE.AdditiveBlending
        });
        this.ring2 = new THREE.Mesh(ring2Geo, ring2Mat);
        this.ring2.rotation.x = -Math.PI * 0.3;
        this.ring2.rotation.z = Math.PI * 0.25;
        this.orbGroup.add(this.ring2);

        // 4. Volumetric Floating Particle Cloud (Purple & Cyan Mist)
        const particleCount = 750;
        const particleGeo = new THREE.BufferGeometry();
        const particlePositions = new Float32Array(particleCount * 3);
        const particleColors = new Float32Array(particleCount * 3);

        const cBlue = new THREE.Color(0x00d2ff);
        const cPurple = new THREE.Color(0x9b51e0);

        for (let i = 0; i < particleCount; i++) {
            // Spherical distribution around orb
            const u = Math.random();
            const v = Math.random();
            const theta = u * 2.0 * Math.PI;
            const phi = Math.acos(2.0 * v - 1.0);
            const r = 2.0 + Math.random() * 1.3;

            const sinPhi = Math.sin(phi);
            const x = r * sinPhi * Math.cos(theta);
            const y = r * sinPhi * Math.sin(theta);
            const z = r * Math.cos(phi);

            particlePositions[i * 3] = x;
            particlePositions[i * 3 + 1] = y;
            particlePositions[i * 3 + 2] = z;

            // Color: Alternate between Blue and Purple
            const mixedColor = Math.random() > 0.45 ? cBlue : cPurple;
            particleColors[i * 3] = mixedColor.r;
            particleColors[i * 3 + 1] = mixedColor.g;
            particleColors[i * 3 + 2] = mixedColor.b;
        }

        particleGeo.setAttribute('position', new THREE.BufferAttribute(particlePositions, 3));
        particleGeo.setAttribute('color', new THREE.BufferAttribute(particleColors, 3));

        const particleMat = new THREE.PointsMaterial({
            size: 0.055,
            vertexColors: true,
            transparent: true,
            opacity: 0.7,
            blending: THREE.AdditiveBlending
        });

        this.particles = new THREE.Points(particleGeo, particleMat);
        this.orbGroup.add(this.particles);
    }

    setupEvents() {
        window.addEventListener('resize', () => {
            if (!this.canvas) return;
            const width = this.canvas.clientWidth || 280;
            const height = this.canvas.clientHeight || 280;
            this.camera.aspect = width / height;
            this.camera.updateProjectionMatrix();
            this.renderer.setSize(width, height);
        });

        // Click on orb triggers listening toggle
        if (this.canvas) {
            this.canvas.addEventListener('click', () => {
                if (window.saghfAiWidget) {
                    window.saghfAiWidget.handleOrbClick();
                }
            });
        }
    }

    setState(newState) {
        if (!['standby', 'listening', 'processing', 'speaking'].includes(newState)) return;
        this.state = newState;
        console.log(`[SaghfAiOrb] State switched to: ${newState}`);

        // Update UI status pill if present
        const pill = document.getElementById('aiOrbStatusPill');
        const pillText = document.getElementById('aiOrbStatusText');
        if (pill && pillText) {
            pill.className = `ai-orb-status-pill status-${newState}`;
            if (newState === 'standby') {
                pillText.textContent = 'حالت آماده‌باش هوشمند';
            } else if (newState === 'listening') {
                pillText.textContent = 'در حال شنیدن صدای شما...';
            } else if (newState === 'processing') {
                pillText.textContent = 'در حال پردازش و استخراج املاک...';
            } else if (newState === 'speaking') {
                pillText.textContent = 'پاسخ هوش مصنوعی سقف';
            }
        }
    }

    setAudioAnalyser(analyserNode) {
        this.analyser = analyserNode;
        this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);
        this.isListeningMic = true;
    }

    animate() {
        requestAnimationFrame(this.animate);

        const time = this.clock.getElapsedTime();
        let speed = 0.012;
        let displacementFactor = 0.06;

        // 1. Calculate Real or Simulated Audio Reactive Amplitude
        if (this.isListeningMic && this.analyser) {
            this.analyser.getByteFrequencyData(this.dataArray);
            let sum = 0;
            for (let i = 0; i < 32; i++) {
                sum += this.dataArray[i];
            }
            const avg = sum / 32;
            this.audioLevel = avg / 255; // 0.0 to 1.0
        } else if (this.state === 'listening' || this.state === 'speaking') {
            // Synthetic organic speech frequency when mic stream is not active
            this.syntheticAudioPhase += 0.08;
            this.audioLevel = 0.35 + Math.sin(this.syntheticAudioPhase * 2.5) * 0.25 + Math.sin(this.syntheticAudioPhase * 5.1) * 0.15;
        } else {
            this.audioLevel = 0.05 + Math.sin(time * 1.8) * 0.03;
        }

        // 2. State-Specific Dynamics
        if (this.state === 'standby') {
            // Fluid gentle wave undulations
            speed = 0.009;
            displacementFactor = 0.05;
            this.energyMat.emissiveIntensity = 0.7 + Math.sin(time * 2) * 0.15;
            this.ring1.rotation.z += 0.008;
            this.ring2.rotation.y -= 0.007;
            this.particles.rotation.y += 0.003;
        } else if (this.state === 'listening') {
            // Dynamic audio reactivity: vertex spikes and synchronized pulse
            speed = 0.018;
            displacementFactor = 0.14 + (this.audioLevel * 0.28);
            this.energyMat.emissiveIntensity = 1.1 + (this.audioLevel * 0.9);
            this.ring1.rotation.z += 0.02 + (this.audioLevel * 0.05);
            this.ring2.rotation.y -= 0.02 + (this.audioLevel * 0.05);
            this.particles.rotation.y += 0.008;
            this.blueLight.intensity = 3.5 + (this.audioLevel * 3.0);
            this.purpleLight.intensity = 4.0 + (this.audioLevel * 3.5);
        } else if (this.state === 'processing') {
            // Rapid vortex acceleration! Swirling lights between purple and blue
            speed = 0.065;
            displacementFactor = 0.08 + Math.sin(time * 12) * 0.04;
            this.energyMat.emissiveIntensity = 1.4 + Math.sin(time * 10) * 0.4;
            this.ring1.rotation.z += 0.09;
            this.ring2.rotation.y -= 0.09;
            this.particles.rotation.y += 0.035;
            this.blueLight.intensity = 4.5 + Math.sin(time * 8) * 2.0;
            this.purpleLight.intensity = 4.5 + Math.cos(time * 8) * 2.0;
        } else if (this.state === 'speaking') {
            // Cadence undulations
            speed = 0.022;
            displacementFactor = 0.11 + Math.sin(time * 6) * 0.06;
            this.energyMat.emissiveIntensity = 1.0 + Math.sin(time * 5) * 0.3;
            this.ring1.rotation.z += 0.015;
            this.ring2.rotation.y -= 0.015;
            this.particles.rotation.y += 0.006;
        }

        // 3. Apply Group Rotation
        this.orbGroup.rotation.y += speed;
        this.orbGroup.rotation.x = Math.sin(time * 0.8) * 0.08;

        // 4. Vertex Waveform Displacement on Outer Shell
        const posAttr = this.energyMesh.geometry.attributes.position;
        const count = posAttr.count;

        for (let i = 0; i < count; i++) {
            const vOrig = this.originalVertices[i];
            // Multi-frequency spherical waves
            const noise = Math.sin(vOrig.x * 2.5 + time * 3.0) *
                          Math.cos(vOrig.y * 2.5 + time * 2.5) *
                          Math.sin(vOrig.z * 2.5 + time * 2.0);

            const scale = 1.0 + (noise * displacementFactor);
            posAttr.setXYZ(
                i,
                vOrig.x * scale,
                vOrig.y * scale,
                vOrig.z * scale
            );
        }
        posAttr.needsUpdate = true;

        // 5. Update Waveform Visualizer Bars in UI
        this.updateWaveformBars(this.audioLevel);

        this.renderer.render(this.scene, this.camera);
    }

    updateWaveformBars(level) {
        const bars = document.querySelectorAll('.ai-wave-bar');
        if (!bars || bars.length === 0) return;

        bars.forEach((bar, index) => {
            const phase = (index / bars.length) * Math.PI * 2;
            const h = 4 + Math.max(0, Math.sin(this.clock.getElapsedTime() * 8 + phase)) * (level * 22);
            bar.style.height = `${Math.min(26, h).toFixed(1)}px`;
        });
    }
}

// Global Hook
window.SaghfAiOrb = SaghfAiOrb;
