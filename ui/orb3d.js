// The 3D health orb: a glass sphere with liquid filled to a value (0-100),
// a waving surface, rising bubbles, and a gentle tilt toward the pointer.
// app.js uses it through window.HibOrb3D and falls back to a flat orb when
// WebGL isn't available.
import * as THREE from 'three';
import { RoomEnvironment } from './vendor/RoomEnvironment.js';

const PALETTE = {
  good: [0x5ff0d6, 0x06648c],
  mid: [0xffd98a, 0xd98a1f],
  bad: [0xff9d8f, 0xc93a4c],
};
const RADIUS = 1;
const LIQUID = 0.93;
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

function supported() {
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  } catch (e) {
    return false;
  }
}

// Shared by the liquid body and its top surface so their edges meet.
const WAVE = `
  float wave(vec3 p, float t, vec2 tilt) {
    return 0.035 * sin(p.x * 4.2 + t * 1.3) + 0.025 * sin(p.z * 5.1 - t * 1.05) + dot(tilt, p.xz) * 0.35;
  }`;

function liquidMaterial(top, bottom) {
  return new THREE.ShaderMaterial({
    side: THREE.DoubleSide,
    uniforms: {
      uLevel: { value: -LIQUID }, uTime: { value: 0 }, uTilt: { value: new THREE.Vector2() },
      uTop: { value: new THREE.Color(top) }, uBottom: { value: new THREE.Color(bottom) },
    },
    vertexShader: `
      varying vec3 vPos; varying vec3 vNormal; varying vec3 vView;
      void main() {
        vPos = position;
        vec4 world = modelMatrix * vec4(position, 1.0);
        vNormal = normalize(mat3(modelMatrix) * normal);
        vView = normalize(cameraPosition - world.xyz);
        gl_Position = projectionMatrix * viewMatrix * world;
      }`,
    fragmentShader: `
      uniform float uLevel; uniform float uTime; uniform vec2 uTilt; uniform vec3 uTop; uniform vec3 uBottom;
      varying vec3 vPos; varying vec3 vNormal; varying vec3 vView;
      ${WAVE}
      void main() {
        float surface = uLevel + wave(vPos, uTime, uTilt);
        if (vPos.y > surface) discard;
        float depth = smoothstep(-${LIQUID.toFixed(2)}, surface, vPos.y);
        vec3 color = mix(uBottom, uTop, pow(depth, 2.2));
        float rim = pow(1.0 - abs(dot(normalize(vNormal), vView)), 2.2);
        color += rim * 0.22 * uTop;
        if (!gl_FrontFacing) color *= 0.62;
        gl_FragColor = vec4(color, 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
}

function surfaceMaterial(top) {
  return new THREE.ShaderMaterial({
    transparent: true,
    uniforms: { uTime: { value: 0 }, uTilt: { value: new THREE.Vector2() }, uTop: { value: new THREE.Color(top) }, uScale: { value: 1 } },
    vertexShader: `
      uniform float uTime; uniform vec2 uTilt; uniform float uScale;
      varying vec3 vPos; varying float vEdge;
      ${WAVE}
      void main() {
        vec3 p = position;
        vEdge = length(p.xz);
        // The mesh is scaled to the cut circle; the wave needs the real (scaled) coordinates.
        p.y += wave(vec3(p.x * uScale, 0.0, p.z * uScale), uTime, uTilt) / 1.0;
        vPos = p;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
      }`,
    fragmentShader: `
      uniform vec3 uTop; varying vec3 vPos; varying float vEdge;
      void main() {
        float shine = 0.5 + 0.5 * sin(vPos.x * 9.0 + vPos.z * 7.0);
        vec3 color = mix(uTop * 1.08, vec3(1.0), 0.18 + 0.12 * shine);
        gl_FragColor = vec4(color, 0.92);
        #include <colorspace_fragment>
      }`,
  });
}

function mountOrb(el, value, kind, onValue) {
  const size = Math.round(el.getBoundingClientRect().width) || 250;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.setSize(size, size, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.92;
  const canvas = renderer.domElement;
  canvas.setAttribute('aria-hidden', 'true');
  const old = el.querySelector('canvas');
  if (old) old.replaceWith(canvas); else el.prepend(canvas);
  el.classList.add('is3d');
  el.classList.remove('good', 'mid', 'bad');
  el.classList.add(kind);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  scene.environment = pmrem.fromScene(room, 0.04).texture;
  scene.environmentIntensity = 0.55;
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 20);
  camera.position.set(0, 0.28, 3.85);
  camera.lookAt(0, 0, 0);

  const key = new THREE.DirectionalLight(0xffffff, 1.4);
  key.position.set(-2, 3, 3);
  scene.add(key);

  const [top, bottom] = PALETTE[kind] || PALETTE.good;
  const group = new THREE.Group();
  scene.add(group);

  // A dark inner wall behind everything, so the empty part of the glass reads as
  // deep and clear instead of milky, and the liquid stands out against it.
  const wallMat = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    vertexShader: `varying vec3 vPos; void main() { vPos = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `varying vec3 vPos;
      void main() {
        vec3 deep = vec3(0.016, 0.075, 0.11);
        vec3 lit = vec3(0.05, 0.16, 0.22);
        gl_FragColor = vec4(mix(deep, lit, smoothstep(-1.0, 1.0, vPos.y) * 0.8), 1.0);
        #include <colorspace_fragment>
      }`,
  });
  group.add(new THREE.Mesh(new THREE.SphereGeometry(0.985, 64, 48), wallMat));

  const liquidMat = liquidMaterial(top, bottom);
  const liquid = new THREE.Mesh(new THREE.SphereGeometry(LIQUID, 96, 64), liquidMat);
  group.add(liquid);

  const surfMat = surfaceMaterial(top);
  const surface = new THREE.Mesh(new THREE.CircleGeometry(1, 96, 0, Math.PI * 2), surfMat);
  // CircleGeometry lies in x/y; turn it flat so it sits in x/z like a water surface.
  surface.geometry.rotateX(-Math.PI / 2);
  group.add(surface);

  const glass = new THREE.Mesh(
    new THREE.SphereGeometry(RADIUS, 96, 64),
    new THREE.MeshPhysicalMaterial({
      color: 0xffffff, metalness: 0, roughness: 0.02, transmission: 1, thickness: 0.18, ior: 1.38,
      clearcoat: 1, clearcoatRoughness: 0.03, envMapIntensity: 0.9, specularIntensity: 0.8,
    }),
  );
  group.add(glass);

  const bubbleCount = 14;
  const bubbles = new THREE.InstancedMesh(
    new THREE.SphereGeometry(0.028, 12, 8),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.55 }),
    bubbleCount,
  );
  const seeds = Array.from({ length: bubbleCount }, (_, i) => ({
    a: (i * 2.399) % (Math.PI * 2), r: 0.15 + ((i * 0.37) % 0.6), y: Math.random(), v: 0.05 + (i % 5) * 0.018, s: 0.6 + (i % 3) * 0.35,
  }));
  group.add(bubbles);
  const m = new THREE.Matrix4();

  const target = Math.max(0, Math.min(100, value));
  let level = reduced ? target : 0;
  let shown = -1;
  const tilt = new THREE.Vector2();
  const want = new THREE.Vector2();
  const onMove = (e) => {
    const r = el.getBoundingClientRect();
    want.set(
      Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / (r.width * 1.6))),
      Math.max(-1, Math.min(1, (e.clientY - (r.top + r.height / 2)) / (r.height * 1.6))),
    );
  };
  if (!reduced) window.addEventListener('pointermove', onMove);

  let last = performance.now();
  let raf = 0;
  const yOf = (pct) => -LIQUID + (pct / 100) * LIQUID * 2;

  const frame = (now) => {
    if (!el.isConnected) {
      window.removeEventListener('pointermove', onMove);
      renderer.dispose();
      pmrem.dispose();
      return;
    }
    const dt = Math.min(0.05, Math.max(0, (now - last) / 1000));
    last = now;
    level += (target - level) * (1 - Math.exp(-dt * 3.6));
    if (Math.abs(target - level) < 0.15) level = target;
    tilt.lerp(want, 1 - Math.exp(-dt * 4));
    const t = reduced ? 0 : now / 1000;

    group.rotation.y = tilt.x * 0.45 + (reduced ? 0 : Math.sin(t * 0.25) * 0.08);
    group.rotation.x = tilt.y * 0.3;
    const y = yOf(level);
    const slosh = new THREE.Vector2(-tilt.x * 0.5, -tilt.y * 0.4);
    liquidMat.uniforms.uLevel.value = y;
    liquidMat.uniforms.uTime.value = t;
    liquidMat.uniforms.uTilt.value.copy(slosh);
    surfMat.uniforms.uTime.value = t;
    surfMat.uniforms.uTilt.value.copy(slosh);
    const capR = Math.sqrt(Math.max(0, LIQUID * LIQUID - y * y));
    surface.visible = level > 0.5 && level < 99.5;
    surface.position.y = y;
    surface.scale.set(capR, 1, capR);
    surfMat.uniforms.uScale.value = capR;

    seeds.forEach((b, i) => {
      if (!reduced) b.y += b.v * dt;
      if (b.y > 1) b.y = 0;
      const by = -LIQUID + (y + LIQUID) * b.y * 0.95;
      const lim = Math.sqrt(Math.max(0, LIQUID * LIQUID - by * by)) * 0.85;
      const rr = Math.min(b.r, lim);
      m.makeScale(b.s, b.s, b.s);
      m.setPosition(Math.cos(b.a + t * 0.2) * rr, by, Math.sin(b.a + t * 0.2) * rr);
      bubbles.setMatrixAt(i, m);
    });
    bubbles.instanceMatrix.needsUpdate = true;
    bubbles.visible = level > 3;

    renderer.render(scene, camera);
    const rounded = Math.round(level);
    if (rounded !== shown) { shown = rounded; onValue(rounded); }
    if (!reduced || level !== target) raf = requestAnimationFrame(frame);
  };
  raf = requestAnimationFrame(frame);
  return () => cancelAnimationFrame(raf);
}

window.HibOrb3D = { supported, mountOrb };
window.dispatchEvent(new Event('orb3d-ready'));
