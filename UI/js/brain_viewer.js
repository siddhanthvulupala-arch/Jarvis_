import * as THREE from 'three';
import { OrbitControls } from '../vendor/controls/OrbitControls.js';
import { GLTFLoader } from '../vendor/loaders/GLTFLoader.js';

/**
 * JARVIS 3D Brain Viewer Core Application
 */
class JarvisBrainViewer {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    if (!this.container) throw new Error(`Container #${containerId} not found`);

    this.width = this.container.clientWidth;
    this.height = this.container.clientHeight;

    // State & Themes
    this.currentTheme = 'cyan';
    this.autoRotate = true;
    this.isInteracting = false;
    this.interactionTimeout = null;
    this.isTweeningCamera = false;

    this.themes = {
      cyan: {
        baseColor: new THREE.Color(0x05162b),
        rimColor: new THREE.Color(0x00f7ff),
        pulseColor: new THREE.Color(0x7df9ff),
        accentColor: new THREE.Color(0x00d2ff),
        ambientColor: new THREE.Color(0x0a223f),
        particleColor: 0x00d2ff,
        floorColor: 0x00d2ff
      },
      amber: {
        baseColor: new THREE.Color(0x241202),
        rimColor: new THREE.Color(0xffaa00),
        pulseColor: new THREE.Color(0xffe066),
        accentColor: new THREE.Color(0xff8800),
        ambientColor: new THREE.Color(0x351904),
        particleColor: 0xffaa00,
        floorColor: 0xffaa00
      },
      violet: {
        baseColor: new THREE.Color(0x16082b),
        rimColor: new THREE.Color(0xc084fc),
        pulseColor: new THREE.Color(0xf3e8ff),
        accentColor: new THREE.Color(0xa855f7),
        ambientColor: new THREE.Color(0x220c3d),
        particleColor: 0xa855f7,
        floorColor: 0xc084fc
      },
      emerald: {
        baseColor: new THREE.Color(0x021f17),
        rimColor: new THREE.Color(0x34d399),
        pulseColor: new THREE.Color(0xa7f3d0),
        accentColor: new THREE.Color(0x10b981),
        ambientColor: new THREE.Color(0x053325),
        particleColor: 0x10b981,
        floorColor: 0x34d399
      }
    };

    // Camera view presets (Comfortably framed 3/4 beauty angle default)
    this.defaultCameraPos = new THREE.Vector3(3.2, 1.8, 4.6);
    this.defaultTarget = new THREE.Vector3(0, 0, 0);

    this.presets = {
      iso: { pos: new THREE.Vector3(3.2, 1.8, 4.6), target: new THREE.Vector3(0, 0, 0) },
      front: { pos: new THREE.Vector3(0, 0.4, 5.6), target: new THREE.Vector3(0, 0, 0) },
      top: { pos: new THREE.Vector3(0, 5.8, 0.01), target: new THREE.Vector3(0, 0, 0) },
      back: { pos: new THREE.Vector3(0, 0.4, -5.6), target: new THREE.Vector3(0, 0, 0) },
      left: { pos: new THREE.Vector3(-5.6, 0.4, 0), target: new THREE.Vector3(0, 0, 0) },
      right: { pos: new THREE.Vector3(5.6, 0.4, 0), target: new THREE.Vector3(0, 0, 0) }
    };

    // Impulse Wave State
    this.impulseWave = {
      center: new THREE.Vector3(0, 0, 0),
      radius: 0.0,
      intensity: 0.0,
      speed: 3.8,
      active: false
    };

    // Hover Tracking
    this.hoverPoint = new THREE.Vector3(999, 999, 999);
    this.hoverIntensity = 0.0;

    // Hierarchy
    this.brainGroup = new THREE.Group();     // Outer group for turntable Y rotation
    this.modelInner = new THREE.Group();     // Inner group for anatomical orientation
    this.brainGroup.add(this.modelInner);

    this.brainMeshes = [];
    this.clock = new THREE.Clock();
    this.raycaster = new THREE.Raycaster();
    this.mouse = new THREE.Vector2(-999, -999);

    // Audio synthesizer for sci-fi impulse ping
    this.audioCtx = null;

    this.initScene();
    this.initLights();
    this.initBackgroundElements();
    this.initControls();
    this.initEvents();
    this.loadBrainModel();
    this.animate();
  }

  initScene() {
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x02050e);
    this.scene.fog = new THREE.FogExp2(0x02050e, 0.055);

    this.camera = new THREE.PerspectiveCamera(40, this.width / this.height, 0.1, 100);
    this.camera.position.copy(this.defaultCameraPos);

    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
      preserveDrawingBuffer: true
    });
    this.renderer.setSize(this.width, this.height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;

    this.container.appendChild(this.renderer.domElement);
    this.scene.add(this.brainGroup);
  }

  initLights() {
    this.ambientLight = new THREE.AmbientLight(this.themes[this.currentTheme].ambientColor, 1.5);
    this.scene.add(this.ambientLight);

    // Main Key Light
    this.keyLight = new THREE.DirectionalLight(0x7dd3fc, 2.6);
    this.keyLight.position.set(5, 7, 6);
    this.scene.add(this.keyLight);

    // Fill Light
    this.fillLight = new THREE.DirectionalLight(0x0284c7, 1.7);
    this.fillLight.position.set(-6, -3, -4);
    this.scene.add(this.fillLight);

    // Top Rim Light
    this.rimLight = new THREE.DirectionalLight(0x00f7ff, 2.4);
    this.rimLight.position.set(0, 8, -5);
    this.scene.add(this.rimLight);

    // Bottom Base Light (illuminates brain stem & underside)
    this.baseLight = new THREE.DirectionalLight(0x0369a1, 1.4);
    this.baseLight.position.set(0, -6, 2);
    this.scene.add(this.baseLight);
  }

  initBackgroundElements() {
    // 1. Subtle Holographic Floor Grid
    const floorRadius = 5.5;
    const gridHelper = new THREE.PolarGridHelper(floorRadius, 16, 8, 32, 0x00d2ff, 0x003355);
    gridHelper.position.y = -2.1;
    gridHelper.material.opacity = 0.22;
    gridHelper.material.transparent = true;
    gridHelper.material.depthWrite = false;
    this.floorGrid = gridHelper;
    this.scene.add(gridHelper);

    // 2. Ambient Floating Holographic Particles
    const particleCount = 180;
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    const scales = new Float32Array(particleCount);

    for (let i = 0; i < particleCount; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 12;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 8;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 12;
      scales[i] = Math.random() * 0.04 + 0.01;
    }

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('scale', new THREE.BufferAttribute(scales, 1));

    const particleMaterial = new THREE.PointsMaterial({
      color: this.themes[this.currentTheme].particleColor,
      size: 0.045,
      transparent: true,
      opacity: 0.45,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });

    this.particles = new THREE.Points(geometry, particleMaterial);
    this.scene.add(this.particles);
  }

  initControls() {
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;
    this.controls.rotateSpeed = 0.75;
    this.controls.zoomSpeed = 0.9;
    this.controls.panSpeed = 0.75;
    this.controls.minDistance = 1.8;
    this.controls.maxDistance = 12.0;
    this.controls.target.copy(this.defaultTarget);

    // Listen to user drag to pause auto-rotate
    this.controls.addEventListener('start', () => {
      this.isInteracting = true;
      if (this.interactionTimeout) clearTimeout(this.interactionTimeout);
    });

    this.controls.addEventListener('end', () => {
      if (this.interactionTimeout) clearTimeout(this.interactionTimeout);
      this.interactionTimeout = setTimeout(() => {
        this.isInteracting = false;
      }, 2500);
    });
  }

  createBrainMaterial() {
    const theme = this.themes[this.currentTheme];

    const uniforms = {
      uTime: { value: 0 },
      uBaseColor: { value: theme.baseColor.clone() },
      uRimColor: { value: theme.rimColor.clone() },
      uPulseColor: { value: theme.pulseColor.clone() },
      uAccentColor: { value: theme.accentColor.clone() },
      uWaveCenter: { value: new THREE.Vector3(0, 0, 0) },
      uWaveRadius: { value: 0.0 },
      uWaveIntensity: { value: 0.0 },
      uHoverCenter: { value: new THREE.Vector3(999, 999, 999) },
      uHoverIntensity: { value: 0.0 }
    };

    const material = new THREE.MeshStandardMaterial({
      color: theme.baseColor,
      roughness: 0.32,
      metalness: 0.20,
      transparent: true,
      opacity: 0.96,
      side: THREE.FrontSide
    });

    material.onBeforeCompile = (shader) => {
      shader.uniforms.uTime = uniforms.uTime;
      shader.uniforms.uBaseColor = uniforms.uBaseColor;
      shader.uniforms.uRimColor = uniforms.uRimColor;
      shader.uniforms.uPulseColor = uniforms.uPulseColor;
      shader.uniforms.uAccentColor = uniforms.uAccentColor;
      shader.uniforms.uWaveCenter = uniforms.uWaveCenter;
      shader.uniforms.uWaveRadius = uniforms.uWaveRadius;
      shader.uniforms.uWaveIntensity = uniforms.uWaveIntensity;
      shader.uniforms.uHoverCenter = uniforms.uHoverCenter;
      shader.uniforms.uHoverIntensity = uniforms.uHoverIntensity;

      // Custom Vertex Shader extension to track world coordinates
      shader.vertexShader = `
        varying vec3 vBrainWorldPosition;
        varying vec3 vBrainNormal;
        varying vec3 vBrainViewDir;
        ${shader.vertexShader}
      `;

      shader.vertexShader = shader.vertexShader.replace(
        '#include <begin_vertex>',
        `
        #include <begin_vertex>
        vec4 brainWorldPos = modelMatrix * vec4(transformed, 1.0);
        vBrainWorldPosition = brainWorldPos.xyz;
        vBrainNormal = normalize(mat3(modelMatrix) * normal);
        vBrainViewDir = normalize(cameraPosition - brainWorldPos.xyz);
        `
      );

      // Custom Fragment Shader extension for Fresnel rim + Impulse wave + Sulci depth
      shader.fragmentShader = `
        uniform float uTime;
        uniform vec3 uBaseColor;
        uniform vec3 uRimColor;
        uniform vec3 uPulseColor;
        uniform vec3 uAccentColor;
        uniform vec3 uWaveCenter;
        uniform float uWaveRadius;
        uniform float uWaveIntensity;
        uniform vec3 uHoverCenter;
        uniform float uHoverIntensity;

        varying vec3 vBrainWorldPosition;
        varying vec3 vBrainNormal;
        varying vec3 vBrainViewDir;
        ${shader.fragmentShader}
      `;

      shader.fragmentShader = shader.fragmentShader.replace(
        '#include <dithering_fragment>',
        `
        #include <dithering_fragment>

        // 1. Fresnel Edge Glow (keeps brain silhouette and cortical folds crisp)
        float fresnel = pow(1.0 - max(dot(normalize(vBrainNormal), normalize(vBrainViewDir)), 0.0), 2.7);
        vec3 rimGlow = uRimColor * fresnel * 1.6;

        // 2. Subtle Holographic Scanline
        float scanline = sin(vBrainWorldPosition.y * 32.0 - uTime * 2.2) * 0.5 + 0.5;
        scanline = pow(scanline, 4.0) * 0.12;

        // 3. Interactive Impulse Wave (expands outward from click point)
        float distToWaveCenter = length(vBrainWorldPosition - uWaveCenter);
        float waveDelta = abs(distToWaveCenter - uWaveRadius);
        float waveShape = exp(-waveDelta * waveDelta * 32.0);
        vec3 impulseGlow = uPulseColor * waveShape * uWaveIntensity * 3.0;

        // 4. Hover spot glow
        float distToHover = length(vBrainWorldPosition - uHoverCenter);
        float hoverShape = exp(-distToHover * distToHover * 8.0);
        vec3 hoverGlow = uAccentColor * hoverShape * uHoverIntensity * 0.9;

        // Combine all lighting passes
        gl_FragColor.rgb += rimGlow + (uAccentColor * scanline) + impulseGlow + hoverGlow;
        `
      );

      material.userData.shader = shader;
    };

    material.userData.uniforms = uniforms;
    return material;
  }

  loadBrainModel() {
    const loader = new GLTFLoader();
    const modelUrl = './models/brain-atlas.glb';

    loader.load(
      modelUrl,
      (gltf) => {
        // Collect required anatomical parts: unified cortex + cerebellum + brain stem
        const targetMeshNames = [
          'unified-cortex',
          'cerebellum',
          'brain-stem',
          'corpus-callosum'
        ];

        const rawMeshes = [];
        gltf.scene.traverse((child) => {
          if (child.isMesh) {
            if (targetMeshNames.includes(child.name)) {
              rawMeshes.push(child);
            }
          }
        });

        if (rawMeshes.length === 0) {
          gltf.scene.traverse((child) => {
            if (child.isMesh && !child.name.startsWith('hit-proxy')) {
              rawMeshes.push(child);
            }
          });
        }

        // Shared JARVIS holographic material
        this.activeBrainMaterial = this.createBrainMaterial();

        rawMeshes.forEach((mesh) => {
          mesh.material = this.activeBrainMaterial;
          mesh.castShadow = false;
          mesh.receiveShadow = false;
          mesh.geometry.computeVertexNormals();
          this.brainMeshes.push(mesh);
          this.modelInner.add(mesh);
        });

        // Compute Bounding Box of the anatomical assembly
        const bbox = new THREE.Box3().setFromObject(this.modelInner);
        const center = new THREE.Vector3();
        bbox.getCenter(center);
        const size = new THREE.Vector3();
        bbox.getSize(size);

        // Center anatomical assembly to (0, 0, 0)
        this.brainMeshes.forEach((mesh) => {
          mesh.position.sub(center);
        });

        // Anatomical Reorientation:
        // FreeSurfer RAS coordinates:
        // X = Left-Right, Y = Posterior-Anterior, Z = Inferior-Superior
        // In Three.js: Up is +Y, Front is +Z
        // 1. Rotate rx = -Math.PI / 2 maps Superior (+Z) to Up (+Y), and Anterior (+Y) to Back (-Z).
        // 2. Rotate rz = Math.PI in local frame maps Anterior (+Y) to Front (+Z).
        this.modelInner.rotation.x = -Math.PI / 2;
        this.modelInner.rotation.z = Math.PI;

        // Scale to a comfortable diameter in Three.js units (~3.25 units)
        const maxDim = Math.max(size.x, size.y, size.z);
        const targetScale = 3.25 / maxDim;
        this.modelInner.scale.setScalar(targetScale);

        // Update telemetry display
        let totalVerts = 0;
        let totalFaces = 0;
        this.brainMeshes.forEach((m) => {
          if (m.geometry.attributes.position) {
            totalVerts += m.geometry.attributes.position.count;
          }
          if (m.geometry.index) {
            totalFaces += m.geometry.index.count / 3;
          }
        });

        const statsElem = document.getElementById('poly-stats');
        if (statsElem) {
          statsElem.innerText = `VERTS: ${totalVerts.toLocaleString()} | FACES: ${Math.round(totalFaces).toLocaleString()}`;
        }

        // Hide loader overlay
        const loaderElem = document.getElementById('loader-overlay');
        if (loaderElem) {
          loaderElem.style.opacity = '0';
          setTimeout(() => {
            loaderElem.style.display = 'none';
          }, 500);
        }

        console.log(`[JARVIS Brain] Successfully loaded ${this.brainMeshes.length} anatomical structures.`);

        // Dispatch rendered snapshot for verification
        setTimeout(() => {
          this.renderer.render(this.scene, this.camera);
          try {
            const dataUrl = this.renderer.domElement.toDataURL('image/png');
            fetch('/api/screenshot', { method: 'POST', body: dataUrl }).catch(() => {});
          } catch(e) {}
        }, 700);
      },
      (progress) => {
        const percent = Math.round((progress.loaded / (progress.total || 10692408)) * 100);
        const loadText = document.getElementById('loader-percent');
        if (loadText) loadText.innerText = `${percent}%`;
      },
      (error) => {
        console.error('[JARVIS Brain] Failed to load model:', error);
        const loadText = document.getElementById('loader-status');
        if (loadText) loadText.innerText = 'LOAD ERROR: ' + error.message;
      }
    );
  }

  initEvents() {
    window.addEventListener('resize', () => this.onWindowResize());

    const dom = this.renderer.domElement;
    dom.addEventListener('pointermove', (e) => this.onPointerMove(e));
    dom.addEventListener('pointerdown', (e) => this.onPointerDown(e));
    dom.addEventListener('dblclick', () => this.resetCamera());

    // Bind UI Buttons
    const resetBtn = document.getElementById('btn-reset-view');
    if (resetBtn) resetBtn.addEventListener('click', () => this.resetCamera());

    const autoRotateBtn = document.getElementById('btn-auto-rotate');
    if (autoRotateBtn) {
      autoRotateBtn.addEventListener('click', () => {
        this.autoRotate = !this.autoRotate;
        autoRotateBtn.classList.toggle('active', this.autoRotate);
        autoRotateBtn.innerText = this.autoRotate ? 'AUTO-ROTATE: ON' : 'AUTO-ROTATE: OFF';
      });
    }

    // View preset buttons
    document.querySelectorAll('.preset-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const presetKey = e.target.getAttribute('data-preset');
        if (presetKey && this.presets[presetKey]) {
          document.querySelectorAll('.preset-btn').forEach((b) => b.classList.remove('active'));
          e.target.classList.add('active');
          this.setCameraPreset(this.presets[presetKey]);
        }
      });
    });

    // Theme selector buttons
    document.querySelectorAll('.theme-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const theme = e.target.getAttribute('data-theme');
        if (theme && this.themes[theme]) {
          document.querySelectorAll('.theme-btn').forEach((b) => b.classList.remove('active'));
          e.target.classList.add('active');
          this.setTheme(theme);
        }
      });
    });
  }

  onWindowResize() {
    this.width = this.container.clientWidth;
    this.height = this.container.clientHeight;
    this.camera.aspect = this.width / this.height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(this.width, this.height);
  }

  onPointerMove(event) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

    // Raycast for hover feedback
    if (this.brainMeshes.length > 0) {
      this.raycaster.setFromCamera(this.mouse, this.camera);
      const intersects = this.raycaster.intersectObjects(this.brainMeshes, false);

      if (intersects.length > 0) {
        this.renderer.domElement.style.cursor = 'pointer';
        const hit = intersects[0];
        this.hoverPoint.copy(hit.point);
        this.hoverIntensity = 1.0;

        if (this.activeBrainMaterial && this.activeBrainMaterial.userData.uniforms) {
          const u = this.activeBrainMaterial.userData.uniforms;
          u.uHoverCenter.value.copy(hit.point);
          u.uHoverIntensity.value = 1.0;
        }
      } else {
        this.renderer.domElement.style.cursor = 'default';
        this.hoverIntensity = 0.0;
        if (this.activeBrainMaterial && this.activeBrainMaterial.userData.uniforms) {
          this.activeBrainMaterial.userData.uniforms.uHoverIntensity.value = 0.0;
        }
      }
    }
  }

  onPointerDown(event) {
    if (event.button !== 0) return; // Only primary left-click triggers impulse

    const rect = this.renderer.domElement.getBoundingClientRect();
    const clickMouse = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1
    );

    this.raycaster.setFromCamera(clickMouse, this.camera);
    const intersects = this.raycaster.intersectObjects(this.brainMeshes, false);

    if (intersects.length > 0) {
      const hit = intersects[0];
      this.triggerImpulse(hit.point, event.clientX, event.clientY);
    }
  }

  triggerImpulse(worldPoint, screenX, screenY) {
    // Start expanding ripple wave from the clicked point
    this.impulseWave.center.copy(worldPoint);
    this.impulseWave.radius = 0.0;
    this.impulseWave.intensity = 1.0;
    this.impulseWave.active = true;

    // Show temporary impulse toast near click
    const indicator = document.getElementById('impulse-indicator');
    if (indicator) {
      indicator.style.left = `${screenX}px`;
      indicator.style.top = `${screenY}px`;
      indicator.style.opacity = '1';
      indicator.style.transform = 'translate(-50%, -180%)';
      setTimeout(() => {
        indicator.style.opacity = '0';
      }, 700);
    }

    // Play subtle audio-synthetic futuristic beep
    this.playImpulseSound();

    console.log(`[JARVIS Brain] Neural impulse triggered at: [${worldPoint.x.toFixed(2)}, ${worldPoint.y.toFixed(2)}, ${worldPoint.z.toFixed(2)}]`);
  }

  playImpulseSound() {
    try {
      if (!this.audioCtx) {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (AudioContext) this.audioCtx = new AudioContext();
      }
      if (this.audioCtx && this.audioCtx.state === 'suspended') {
        this.audioCtx.resume();
      }
      if (!this.audioCtx) return;

      const osc = this.audioCtx.createOscillator();
      const gain = this.audioCtx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, this.audioCtx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(1760, this.audioCtx.currentTime + 0.08);

      gain.gain.setValueAtTime(0.04, this.audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, this.audioCtx.currentTime + 0.12);

      osc.connect(gain);
      gain.connect(this.audioCtx.destination);

      osc.start();
      osc.stop(this.audioCtx.currentTime + 0.12);
    } catch {
      // Audio autoplay policy catch
    }
  }

  resetCamera() {
    this.setCameraPreset({
      pos: this.defaultCameraPos,
      target: this.defaultTarget
    });
  }

  setCameraPreset(preset) {
    if (this.isTweeningCamera) return;
    this.isTweeningCamera = true;

    const startPos = this.camera.position.clone();
    const startTarget = this.controls.target.clone();
    const targetPos = preset.pos.clone();
    const targetTarget = preset.target.clone();

    const startTime = performance.now();
    const duration = 650; // ms

    const animateTween = (now) => {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1.0);
      const ease = 1 - Math.pow(1 - progress, 3); // Smooth cubic ease out

      this.camera.position.lerpVectors(startPos, targetPos, ease);
      this.controls.target.lerpVectors(startTarget, targetTarget, ease);
      this.controls.update();

      if (progress < 1.0) {
        requestAnimationFrame(animateTween);
      } else {
        this.camera.position.copy(targetPos);
        this.controls.target.copy(targetTarget);
        this.controls.update();
        this.isTweeningCamera = false;
      }
    };

    requestAnimationFrame(animateTween);
  }

  setTheme(themeName) {
    if (!this.themes[themeName]) return;
    this.currentTheme = themeName;
    const theme = this.themes[themeName];

    // Update Ambient Light
    this.ambientLight.color.copy(theme.ambientColor);

    // Update Particles
    if (this.particles && this.particles.material) {
      this.particles.material.color.setHex(theme.particleColor);
    }

    // Update Floor Grid
    if (this.floorGrid && this.floorGrid.material) {
      this.floorGrid.material.color.setHex(theme.floorColor);
    }

    // Update Brain Material Uniforms
    if (this.activeBrainMaterial && this.activeBrainMaterial.userData.uniforms) {
      const u = this.activeBrainMaterial.userData.uniforms;
      u.uBaseColor.value.copy(theme.baseColor);
      u.uRimColor.value.copy(theme.rimColor);
      u.uPulseColor.value.copy(theme.pulseColor);
      u.uAccentColor.value.copy(theme.accentColor);
    }

    // Update CSS Accent
    document.documentElement.style.setProperty('--jarvis-cyan', '#' + theme.accentColor.getHexString());
    document.documentElement.style.setProperty('--jarvis-cyan-bright', '#' + theme.rimColor.getHexString());
  }

  animate() {
    requestAnimationFrame(() => this.animate());

    const delta = this.clock.getDelta();
    const time = this.clock.getElapsedTime();

    // OrbitControls update
    this.controls.update();

    // Smooth turntable rotation around world vertical Y axis
    if (this.autoRotate && !this.isInteracting && !this.isTweeningCamera) {
      this.brainGroup.rotation.y += 0.004;
    }

    // Gentle particle drift
    if (this.particles) {
      this.particles.rotation.y = time * 0.02;
    }

    // Update impulse wave
    if (this.impulseWave.active) {
      this.impulseWave.radius += this.impulseWave.speed * delta;
      this.impulseWave.intensity -= delta * 0.95;

      if (this.impulseWave.intensity <= 0.0 || this.impulseWave.radius > 6.0) {
        this.impulseWave.active = false;
        this.impulseWave.intensity = 0.0;
      }
    }

    // Update shader uniforms
    if (this.activeBrainMaterial && this.activeBrainMaterial.userData.uniforms) {
      const u = this.activeBrainMaterial.userData.uniforms;
      u.uTime.value = time;
      u.uWaveCenter.value.copy(this.impulseWave.center);
      u.uWaveRadius.value = this.impulseWave.radius;
      u.uWaveIntensity.value = this.impulseWave.intensity;
    }

    // Render Scene
    this.renderer.render(this.scene, this.camera);
  }
}

// Auto-instantiate when DOM is ready
window.addEventListener('DOMContentLoaded', () => {
  window.viewer = new JarvisBrainViewer('canvas-container');
});
