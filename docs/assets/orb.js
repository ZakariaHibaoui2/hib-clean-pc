// The health orb for the website: the same glass sphere the app uses, filled
// with liquid to a score. The page sets the target score; the liquid rises to
// it, changes colour as it crosses the app's thresholds (40 and 65), tilts
// toward the pointer and sloshes on a spring when the page scrolls.
import * as THREE from 'three';
import { RoomEnvironment } from '../vendor/RoomEnvironment.js';

const LIQUID = 0.93;
const SETS = {
  bad: [new THREE.Color(0xff9d8f), new THREE.Color(0xc93a4c)],
  mid: [new THREE.Color(0xffd98a), new THREE.Color(0xd98a1f)],
  good: [new THREE.Color(0x5ff0d6), new THREE.Color(0x06648c)],
};
const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

const WAVE = `
  uniform float uAmp;
  float wave(vec3 p, float t, vec2 tilt) {
    return uAmp * (0.035 * sin(p.x * 4.2 + t * 1.3) + 0.025 * sin(p.z * 5.1 - t * 1.05)) + dot(tilt, p.xz) * 0.35;
  }`;

function liquidMaterial() {
  return new THREE.ShaderMaterial({
    side: THREE.DoubleSide,
    uniforms: {
      uLevel: { value: -LIQUID }, uTime: { value: 0 }, uTilt: { value: new THREE.Vector2() }, uAmp: { value: 1 },
      uTop: { value: new THREE.Color() }, uBottom: { value: new THREE.Color() },
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
        vec3 color = mix(uBottom * 0.7, uTop * 0.92, pow(depth, 1.7));
        float facing = abs(dot(normalize(vNormal), vView));
        // Thicker liquid toward the edge of the sphere reads darker; a thin bright rim sells the curve.
        color *= mix(0.55, 1.08, pow(facing, 0.75));
        color += pow(1.0 - facing, 4.0) * 0.45 * uTop;
        // Slow caustic shimmer moving through the body.
        float c = sin(vPos.x * 7.0 + uTime * 0.9) * sin(vPos.z * 6.0 - uTime * 0.7) * sin(vPos.y * 8.0 + uTime * 0.5);
        color += uTop * 0.08 * smoothstep(0.25, 0.9, c);
        // A thin bright band just under the surface, like light caught in the meniscus.
        color += uTop * 0.35 * smoothstep(0.06, 0.0, surface - vPos.y);
        if (!gl_FrontFacing) color *= 0.6;
        gl_FragColor = vec4(color, 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
}

function surfaceMaterial() {
  return new THREE.ShaderMaterial({
    transparent: true,
    uniforms: { uTime: { value: 0 }, uTilt: { value: new THREE.Vector2() }, uTop: { value: new THREE.Color() }, uScale: { value: 1 }, uAmp: { value: 1 } },
    vertexShader: `
      uniform float uTime; uniform vec2 uTilt; uniform float uScale;
      varying vec3 vPos;
      ${WAVE}
      void main() {
        vec3 p = position;
        p.y += wave(vec3(p.x * uScale, 0.0, p.z * uScale), uTime, uTilt);
        vPos = p;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
      }`,
    fragmentShader: `
      uniform vec3 uTop; uniform float uTime; varying vec3 vPos;
      void main() {
        float shine = 0.5 + 0.5 * sin(vPos.x * 9.0 + vPos.z * 7.0 + uTime * 0.6);
        vec3 color = mix(uTop * 1.08, vec3(1.0), 0.16 + 0.14 * shine);
        gl_FragColor = vec4(color, 0.92);
        #include <colorspace_fragment>
      }`,
  });
}

export function supported() {
  try {
    const c = document.createElement('canvas');
    return !!(window.WebGLRenderingContext && (c.getContext('webgl2') || c.getContext('webgl')));
  } catch (e) {
    return false;
  }
}

export function mountOrb(el, { start = 0, onLevel = () => {}, onReady = () => {} } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(matchMedia('(pointer: coarse)').matches ? 1.5 : 2, window.devicePixelRatio || 1));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.95;
  const canvas = renderer.domElement;
  canvas.setAttribute('aria-hidden', 'true');
  el.appendChild(canvas);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.6;
  const camera = new THREE.PerspectiveCamera(28, 1, 0.1, 20);
  camera.position.set(0, 0.3, 4.75);
  camera.lookAt(0, 0, 0);

  const key = new THREE.DirectionalLight(0xffffff, 1.5);
  key.position.set(-2, 3, 3);
  scene.add(key);

  const group = new THREE.Group();
  scene.add(group);

  // Dark inner wall so the empty glass reads as deep, clear water instead of milk.
  group.add(new THREE.Mesh(new THREE.SphereGeometry(0.985, 64, 48), new THREE.ShaderMaterial({
    side: THREE.BackSide,
    vertexShader: 'varying vec3 vPos; void main() { vPos = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
    fragmentShader: `varying vec3 vPos;
      void main() {
        vec3 deep = vec3(0.01, 0.045, 0.07);
        vec3 lit = vec3(0.035, 0.12, 0.17);
        gl_FragColor = vec4(mix(deep, lit, smoothstep(-1.0, 1.0, vPos.y) * 0.8), 1.0);
        #include <colorspace_fragment>
      }`,
  })));

  const liquidMat = liquidMaterial();
  group.add(new THREE.Mesh(new THREE.SphereGeometry(LIQUID, 128, 96), liquidMat));

  const surfMat = surfaceMaterial();
  const surface = new THREE.Mesh(new THREE.CircleGeometry(1, 128), surfMat);
  surface.geometry.rotateX(-Math.PI / 2);
  group.add(surface);

  group.add(new THREE.Mesh(
    new THREE.SphereGeometry(1, 128, 96),
    new THREE.MeshPhysicalMaterial({
      color: 0xffffff, metalness: 0, roughness: 0.02, transmission: 1, thickness: 0.18, ior: 1.38,
      clearcoat: 1, clearcoatRoughness: 0.03, envMapIntensity: 1, specularIntensity: 0.85,
    }),
  ));

  const COUNT = 22;
  const bubbles = new THREE.InstancedMesh(
    new THREE.SphereGeometry(0.026, 12, 8),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.55 }),
    COUNT,
  );
  const seeds = Array.from({ length: COUNT }, (_, i) => ({
    a: (i * 2.399) % (Math.PI * 2), r: 0.12 + ((i * 0.37) % 0.65), y: (i * 0.618) % 1, v: 0.045 + (i % 5) * 0.017, s: 0.55 + (i % 3) * 0.35,
  }));
  group.add(bubbles);
  const m = new THREE.Matrix4();

  // State
  let level = start;
  let target = start;
  let rate = 2.2;
  let shown = -1;
  const pos = new THREE.Vector2();   // slosh tilt (spring position)
  const vel = new THREE.Vector2();   // slosh tilt (spring velocity)
  const aim = new THREE.Vector2();   // where the pointer wants the tilt
  const top = new THREE.Color();
  const bottom = new THREE.Color();

  const onMove = (e) => {
    aim.set(
      Math.max(-1, Math.min(1, (e.clientX / innerWidth) * 2 - 1)),
      Math.max(-1, Math.min(1, (e.clientY / innerHeight) * 2 - 1)),
    );
  };
  let lastY = scrollY;
  const onScroll = () => {
    const dy = scrollY - lastY;
    lastY = scrollY;
    vel.y += Math.max(-1.2, Math.min(1.2, dy * 0.012));
  };
  addEventListener('pointermove', onMove, { passive: true });
  addEventListener('scroll', onScroll, { passive: true });

  const resize = () => {
    const w = Math.max(1, el.clientWidth);
    const h = Math.max(1, el.clientHeight);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    // Keep the whole sphere in frame whatever the box shape.
    const fit = 1.16 / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const d = camera.aspect < 1 ? fit / camera.aspect : fit;
    // Look down a little so the water surface shows as an ellipse.
    camera.position.set(0, d * 0.2, d * 0.98);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize);
  ro.observe(el);
  resize();

  let visible = true;
  const io = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; if (visible) kick(); });
  io.observe(el);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) kick(); });

  const yOf = (pct) => -LIQUID + (pct / 100) * LIQUID * 2;
  let last = performance.now();
  let raf = 0;
  let readySent = false;

  function draw(now) {
    const dt = Math.min(0.05, Math.max(0, (now - last) / 1000));
    last = now;
    const t = now / 1000;

    level += (target - level) * (1 - Math.exp(-dt * rate));
    if (Math.abs(target - level) < 0.05) level = target;

    // Underdamped spring (zeta ~0.45): liquid overshoots, then settles.
    const want = new THREE.Vector2(-aim.x * 0.55, -aim.y * 0.35);
    vel.x += ((want.x - pos.x) * 30 - vel.x * 5) * dt;
    vel.y += ((want.y - pos.y) * 30 - vel.y * 5) * dt;
    pos.addScaledVector(vel, dt);
    const sloshMag = Math.min(1, vel.length() * 0.6);

    group.rotation.y = aim.x * 0.35 + Math.sin(t * 0.25) * 0.1;
    group.rotation.x = aim.y * 0.18;

    const s = level;
    const wMid = smooth(36, 44, s);
    const wGood = smooth(60, 66, s);
    top.copy(SETS.bad[0]).lerp(SETS.mid[0], wMid).lerp(SETS.good[0], wGood);
    bottom.copy(SETS.bad[1]).lerp(SETS.mid[1], wMid).lerp(SETS.good[1], wGood);

    const y = yOf(level);
    const amp = 1 + sloshMag * 1.6;
    liquidMat.uniforms.uLevel.value = y;
    liquidMat.uniforms.uTime.value = t;
    liquidMat.uniforms.uTilt.value.copy(pos);
    liquidMat.uniforms.uAmp.value = amp;
    liquidMat.uniforms.uTop.value.copy(top);
    liquidMat.uniforms.uBottom.value.copy(bottom);
    surfMat.uniforms.uTime.value = t;
    surfMat.uniforms.uTilt.value.copy(pos);
    surfMat.uniforms.uAmp.value = amp;
    surfMat.uniforms.uTop.value.copy(top);
    const capR = Math.sqrt(Math.max(0, LIQUID * LIQUID - y * y));
    surface.visible = level > 0.5 && level < 99.5;
    surface.position.y = y;
    surface.scale.set(capR, 1, capR);
    surfMat.uniforms.uScale.value = capR;

    seeds.forEach((b, i) => {
      b.y += b.v * dt;
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
    if (rounded !== shown) { shown = rounded; onLevel(rounded); }
    if (!readySent) { readySent = true; onReady(); }
  }

  // Adaptive quality: on a slow GPU drop to 1x pixels, and if it is still slow,
  // only draw while something is actually changing (filling or sloshing).
  let ema = 16;
  let frames = 0;
  let thin = false;
  let lastDraw = 0;
  function frame(now) {
    raf = 0;
    if (!visible || document.hidden) return;
    const gap = now - last;
    const busy = Math.abs(target - level) > 0.05 || vel.lengthSq() > 1e-4;
    if (!thin || busy || now - lastDraw > 250) {
      const t0 = performance.now();
      draw(now);
      lastDraw = now;
      ema = ema * 0.9 + Math.max(gap, performance.now() - t0) * 0.1;
      frames++;
      if (frames > 40 && ema > 40) {
        if (renderer.getPixelRatio() > 1) { renderer.setPixelRatio(1); resize(); ema = 16; frames = 0; }
        else thin = true;
      }
    }
    raf = requestAnimationFrame(frame);
  }
  function kick() {
    if (!raf) { last = performance.now(); raf = requestAnimationFrame(frame); }
  }
  kick();

  return {
    setTarget(v, speed = 4.5) { target = Math.max(0, Math.min(100, v)); rate = speed; kick(); },
    // Renders one frame and returns it as a PNG data URL (used to make the fallback image).
    capture() { draw(performance.now()); return canvas.toDataURL('image/png'); },
    get level() { return level; },
  };
}
