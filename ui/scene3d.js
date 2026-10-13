// The ambient water behind the interface: caustic light from the surface above,
// faint light shafts, and slow motes drifting at three depths. One WebGL context,
// drawn at reduced resolution and at most 30 frames a second, paused while the
// window is hidden. Skipped under reduced motion or without WebGL; the CSS
// gradient behind it stays as the fallback.
import * as THREE from 'three';
import { CAUSTIC } from './water.js';

const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;


function start() {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, powerPreference: 'low-power', depth: false, stencil: false });
  } catch (e) {
    return; // no WebGL: the CSS background stays
  }
  const SCALE = 0.55; // soft light needs no full resolution
  renderer.setPixelRatio(SCALE);
  renderer.setClearColor(0x000000, 0);
  const canvas = renderer.domElement;
  canvas.className = 'ambient';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.prepend(canvas);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 50);
  camera.position.z = 10;

  // Full-screen light: caustics strongest near the surface (top), shafts slanting down.
  const lightMat = new THREE.ShaderMaterial({
    depthTest: false, depthWrite: false, transparent: true, premultipliedAlpha: true,
    uniforms: { uTime: { value: 0 }, uRes: { value: new THREE.Vector2(1, 1) }, uShift: { value: new THREE.Vector2() }, uScroll: { value: 0 } },
    vertexShader: 'varying vec2 vUv; void main() { vUv = position.xy * 0.5 + 0.5; gl_Position = vec4(position.xy, 0.0, 1.0); }',
    fragmentShader: `
      uniform float uTime; uniform vec2 uRes; uniform vec2 uShift; uniform float uScroll;
      varying vec2 vUv;
      ${CAUSTIC}
      void main() {
        float aspect = uRes.x / uRes.y;
        vec2 p = vec2(vUv.x * aspect, vUv.y);
        // Light falls off with depth below the surface.
        float surface = pow(vUv.y, 2.2);
        vec2 cp = p * 1.15 + uShift * 0.04 + vec2(0.0, uScroll * 0.00025);
        float c = caustic(cp, uTime * 0.32) * 0.75 + caustic(cp * 1.9 + 3.1, uTime * 0.27) * 0.25;
        float caus = c * (0.05 + 0.2 * surface);
        // Slanted light shafts, slowly breathing.
        float x = p.x + (1.0 - vUv.y) * 0.42 + uShift.x * 0.02;
        float shafts = 0.5 + 0.5 * sin(x * 7.0 + uTime * 0.07) * sin(x * 3.1 - uTime * 0.05 + 1.3);
        shafts = pow(shafts, 3.0) * smoothstep(0.0, 1.0, vUv.y) * 0.06;
        vec3 lagoon = vec3(0.224, 0.878, 0.776);
        vec3 deep = vec3(0.122, 0.663, 0.788);
        vec3 col = mix(deep, lagoon, vUv.y) * (caus + shafts);
        float a = clamp(max(col.r, max(col.g, col.b)), 0.0, 1.0);
        gl_FragColor = vec4(col, a);
      }`,
  });
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), lightMat);
  quad.frustumCulled = false;
  quad.renderOrder = -1;
  scene.add(quad);

  // Motes: suspended particles at three depths, parallax with the pointer.
  const COUNT = 70;
  const pos = new Float32Array(COUNT * 3);
  const seed = new Float32Array(COUNT);
  for (let i = 0; i < COUNT; i++) {
    pos[i * 3] = (Math.random() - 0.5) * 16;
    pos[i * 3 + 1] = (Math.random() - 0.5) * 10;
    pos[i * 3 + 2] = [-4, -1, 2][i % 3] + Math.random();
    seed[i] = Math.random();
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('seed', new THREE.BufferAttribute(seed, 1));
  const moteMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: { value: 0 }, uPx: { value: renderer.getPixelRatio() } },
    vertexShader: `
      uniform float uTime; uniform float uPx;
      attribute float seed; varying float vA;
      void main() {
        vec3 p = position;
        // Rise slowly, wrap, sway.
        p.y = mod(p.y + 5.0 + uTime * (0.05 + seed * 0.08), 10.0) - 5.0;
        p.x += sin(uTime * 0.2 + seed * 40.0) * 0.25;
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_PointSize = (3.0 + seed * 5.0) * uPx * (10.0 / -mv.z) * 1.6;
        // Fade near the top/bottom wrap and with depth.
        vA = (0.18 + seed * 0.3) * smoothstep(5.0, 3.5, abs(p.y)) * clamp((p.z + 6.0) / 8.0, 0.3, 1.0);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      varying float vA;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        float a = smoothstep(0.5, 0.0, d) * vA;
        gl_FragColor = vec4(vec3(0.75, 0.97, 0.95) * a, a);
      }`,
  });
  const motes = new THREE.Points(geo, moteMat);
  motes.frustumCulled = false;
  scene.add(motes);

  const shift = new THREE.Vector2();
  const want = new THREE.Vector2();
  addEventListener('pointermove', (e) => {
    want.set(e.clientX / innerWidth - 0.5, 0.5 - e.clientY / innerHeight);
  }, { passive: true });
  let scroll = 0;
  addEventListener('scroll', (e) => {
    if (e.target && e.target.id === 'view') scroll = e.target.scrollTop;
  }, { passive: true, capture: true });

  const resize = () => {
    renderer.setSize(innerWidth, innerHeight, false);
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    lightMat.uniforms.uRes.value.set(innerWidth, innerHeight);
  };
  resize();
  addEventListener('resize', resize);

  let raf = 0;
  let last = 0;
  let clock = 0;
  let prev = performance.now();
  const frame = (now) => {
    raf = requestAnimationFrame(frame);
    if (now - last < 32) return; // ~30 fps is plenty for slow water
    last = now;
    clock += Math.min(0.1, (now - prev) / 1000);
    prev = now;
    shift.lerp(want, 0.06);
    lightMat.uniforms.uTime.value = clock;
    lightMat.uniforms.uShift.value.copy(shift);
    lightMat.uniforms.uScroll.value += (scroll - lightMat.uniforms.uScroll.value) * 0.2;
    moteMat.uniforms.uTime.value = clock;
    motes.position.set(shift.x * 0.6, shift.y * 0.4, 0);
    motes.rotation.y = shift.x * 0.05;
    renderer.render(scene, camera);
  };
  const run = () => {
    if (raf || document.hidden) return;
    prev = performance.now();
    raf = requestAnimationFrame(frame);
  };
  const stop = () => { cancelAnimationFrame(raf); raf = 0; };
  document.addEventListener('visibilitychange', () => (document.hidden ? stop() : run()));
  canvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); stop(); canvas.remove(); });
  run();
  requestAnimationFrame(() => canvas.classList.add('on'));
}

function supported() {
  try {
    const gl = document.createElement('canvas').getContext('webgl2');
    if (gl) gl.getExtension('WEBGL_lose_context')?.loseContext();
    return !!gl;
  } catch (e) {
    return false;
  }
}

// Let the first screen draw before the GPU warms up.
if (!reduced && supported()) {
  const go = () => start();
  if ('requestIdleCallback' in window) requestIdleCallback(go, { timeout: 1200 }); else setTimeout(go, 400);
}
