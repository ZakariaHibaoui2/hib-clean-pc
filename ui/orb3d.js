// The 3D health orb: a glass sphere with liquid filled to a value (0-100),
// a waving surface lit by caustics, rising bubbles, and a floor beneath it with
// a contact shadow and the pool of light the liquid focuses. It tilts toward the
// pointer. app.js uses it through window.HibOrb3D and falls back to a flat orb
// when WebGL isn't available.
import * as THREE from 'three';
import { RoomEnvironment } from './vendor/RoomEnvironment.js';
import { CAUSTIC } from './water.js';

const PALETTE = {
  good: [0x5ff0d6, 0x06648c],
  mid: [0xffd98a, 0xd98a1f],
  bad: [0xff9d8f, 0xc93a4c],
};
const RADIUS = 1;
const LIQUID = 0.93;
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

// The canvas is bigger than the orb element so the floor fits around it:
// fractions of the orb's size on each side.
const PAD = { x: 0.25, top: 0.1, bottom: 0.3 };

function supported() {
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl2') || c.getContext('webgl');
    if (gl) gl.getExtension('WEBGL_lose_context')?.loseContext();
    return !!gl;
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
      ${CAUSTIC}
      void main() {
        float surface = uLevel + wave(vPos, uTime, uTilt);
        if (vPos.y > surface) discard;
        float depth = smoothstep(-${LIQUID.toFixed(2)}, surface, vPos.y);
        vec3 color = mix(uBottom, uTop, pow(depth, 2.2));
        // Light from the surface plays through the body, fading with depth.
        float c = caustic(vPos.xz * 0.9 + vPos.y * 0.35, uTime * 0.45);
        color += uTop * c * 0.32 * pow(depth, 1.5);
        // The meniscus: a bright band just under the surface.
        color += uTop * smoothstep(0.06, 0.0, surface - vPos.y) * 0.28;
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
        p.y += wave(vec3(p.x * uScale, 0.0, p.z * uScale), uTime, uTilt);
        vPos = vec3(p.x * uScale, p.y, p.z * uScale);
        gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
      }`,
    fragmentShader: `
      uniform vec3 uTop; uniform float uTime; varying vec3 vPos; varying float vEdge;
      ${CAUSTIC}
      void main() {
        float sparkle = caustic(vPos.xz * 1.1 + 0.3, uTime * 0.5);
        vec3 color = mix(uTop * 1.06, vec3(1.0), 0.14 + 0.45 * sparkle);
        // Brighter where the surface meets the glass.
        color += smoothstep(0.82, 1.0, vEdge) * 0.18;
        gl_FragColor = vec4(color, 0.9);
        #include <colorspace_fragment>
      }`,
  });
}

// The floor under the orb: a contact shadow and the caustic pool of light the
// liquid focuses, offset away from the key light (top left).
function floorMaterial(top) {
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, premultipliedAlpha: true,
    uniforms: { uTime: { value: 0 }, uTint: { value: new THREE.Color(top) }, uFill: { value: 0 }, uShift: { value: new THREE.Vector2() } },
    vertexShader: 'varying vec2 vXZ; void main() { vXZ = position.xz; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
    fragmentShader: `
      uniform float uTime; uniform vec3 uTint; uniform float uFill; uniform vec2 uShift;
      varying vec2 vXZ;
      ${CAUSTIC}
      void main() {
        float r2 = dot(vXZ, vXZ);
        // Contact shadow: a tight dark core and a wide soft penumbra.
        float shadow = exp(-r2 * 6.0) * 0.7 + exp(-r2 * 0.9) * 0.32;
        vec2 q = (vXZ - vec2(0.42, 0.34) - uShift) * vec2(0.8, 1.25);
        float pool = exp(-dot(q, q) * 2.6);
        float c = caustic(vXZ * 0.75 + 0.5, uTime * 0.4);
        vec3 light = uTint * pool * (0.2 + 1.1 * c) * uFill;
        // Fade out before the canvas edge so the floor never shows a seam.
        float fade = smoothstep(0.78, 0.3, vXZ.y) * smoothstep(1.8, 1.0, abs(vXZ.x));
        float a = clamp(max(shadow * (1.0 - pool * 0.5), max(light.r, max(light.g, light.b))), 0.0, 1.0) * fade;
        light *= fade;
        gl_FragColor = vec4(light, a);
      }`,
  });
}

// Every live orb, so one leaving the page frees its GPU context right away.
const live = new Set();
function sweep() {
  for (const o of live) if (!o.el.isConnected) o.dispose();
}
function watchView() {
  const view = document.getElementById('view');
  if (view) new MutationObserver(sweep).observe(view, { childList: true, subtree: true });
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', watchView); else watchView();
addEventListener('hashchange', () => setTimeout(sweep, 0));

function mountOrb(el, value, kind, onValue) {
  sweep();
  const size = Math.round(el.getBoundingClientRect().width) || 250;
  const W = Math.round(size * (1 + PAD.x * 2));
  const H = Math.round(size * (1 + PAD.top + PAD.bottom));
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.setSize(W, H, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.92;
  const canvas = renderer.domElement;
  canvas.setAttribute('aria-hidden', 'true');
  canvas.className = 'orb-stage';
  canvas.style.cssText = `left:${-PAD.x * 100}%;top:${-PAD.top * 100}%;width:${(1 + PAD.x * 2) * 100}%;height:${(1 + PAD.top + PAD.bottom) * 100}%`;
  const old = el.querySelector('canvas');
  if (old) old.replaceWith(canvas); else el.prepend(canvas);
  el.classList.add('is3d');
  el.classList.remove('good', 'mid', 'bad');
  el.classList.add(kind);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  const envMap = pmrem.fromScene(room, 0.04).texture;
  scene.environment = envMap;
  scene.environmentIntensity = 0.42;

  // The orb keeps the same size and place as before; the camera's view is widened
  // around it and the canvas shows the part that includes the floor.
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 20);
  const centerFromTop = PAD.top + 0.5;
  const below = H / size - centerFromTop;
  const fullH = 2 * Math.max(centerFromTop, below);
  camera.fov = THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(15)) * fullH));
  camera.aspect = (W / size) / fullH;
  camera.setViewOffset(W, fullH * size, 0, (fullH / 2 - centerFromTop) * size, W, H);
  camera.position.set(0, 0.28, 3.85);
  camera.lookAt(0, 0, 0);
  camera.updateProjectionMatrix();

  const key = new THREE.DirectionalLight(0xffffff, 1.4);
  key.position.set(-2, 3, 3);
  scene.add(key);
  const [top, bottom] = PALETTE[kind] || PALETTE.good;
  const rimLight = new THREE.DirectionalLight(top, 0.9);
  rimLight.position.set(2.5, 1, -2);
  scene.add(rimLight);

  const floorMat = floorMaterial(top);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(4, 4).rotateX(-Math.PI / 2), floorMat);
  floor.position.y = -RADIUS - 0.015;
  floor.renderOrder = -1;
  scene.add(floor);

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

  const glassMat = new THREE.MeshPhysicalMaterial({
    color: 0xffffff, metalness: 0, roughness: 0.02, transmission: 1, thickness: 0.22, ior: 1.42,
    dispersion: 0.35, iridescence: 0.1, iridescenceIOR: 1.3, iridescenceThicknessRange: [180, 420],
    clearcoat: 1, clearcoatRoughness: 0.03, envMapIntensity: 0.95, specularIntensity: 0.85,
  });
  const glass = new THREE.Mesh(new THREE.SphereGeometry(RADIUS, 96, 64), glassMat);
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
  const slosh = new THREE.Vector2();
  const onMove = (e) => {
    const r = el.getBoundingClientRect();
    want.set(
      Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / (r.width * 1.6))),
      Math.max(-1, Math.min(1, (e.clientY - (r.top + r.height / 2)) / (r.height * 1.6))),
    );
  };
  if (!reduced) window.addEventListener('pointermove', onMove, { passive: true });

  let last = performance.now();
  let drawn = 0;
  let raf = 0;
  let disposed = false;
  const yOf = (pct) => -LIQUID + (pct / 100) * LIQUID * 2;

  const entry = { el, dispose };
  live.add(entry);
  function dispose() {
    if (disposed) return;
    disposed = true;
    live.delete(entry);
    cancelAnimationFrame(raf);
    window.removeEventListener('pointermove', onMove);
    document.removeEventListener('visibilitychange', onVisible);
    scene.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) o.material.dispose();
    });
    envMap.dispose();
    pmrem.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
  }

  const frame = (now) => {
    raf = 0;
    if (!el.isConnected) { dispose(); return; }
    const settled = level === target;
    // Full rate while filling, then 30 fps: the slow waves don't need more.
    if (settled && now - drawn < 32) { raf = requestAnimationFrame(frame); return; }
    drawn = now;
    const dt = Math.min(0.05, Math.max(0, (now - last) / 1000));
    last = now;
    level += (target - level) * (1 - Math.exp(-dt * 3.6));
    if (Math.abs(target - level) < 0.15) level = target;
    tilt.lerp(want, 1 - Math.exp(-dt * 4));
    const t = reduced ? 0 : now / 1000;

    group.rotation.y = tilt.x * 0.45 + (reduced ? 0 : Math.sin(t * 0.25) * 0.08);
    group.rotation.x = tilt.y * 0.3;
    const y = yOf(level);
    slosh.set(-tilt.x * 0.5, -tilt.y * 0.4);
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
    floorMat.uniforms.uTime.value = t;
    floorMat.uniforms.uFill.value = Math.min(1, 0.25 + level / 80);
    floorMat.uniforms.uShift.value.set(-tilt.x * 0.25, -tilt.y * 0.2);

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
    if ((!reduced || level !== target) && !document.hidden) raf = requestAnimationFrame(frame);
  };
  // Stop drawing while the window is hidden; pick up again when it returns.
  function onVisible() {
    if (!document.hidden && !raf && !disposed && !reduced) { last = performance.now(); raf = requestAnimationFrame(frame); }
  }
  document.addEventListener('visibilitychange', onVisible);
  raf = requestAnimationFrame(frame);
  return dispose;
}

window.HibOrb3D = { supported, mountOrb };
window.dispatchEvent(new Event('orb3d-ready'));
