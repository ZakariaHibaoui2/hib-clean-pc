// Page behaviour: copy buttons, nav state, screen tabs, the fixes scroll
// and the deferred 3D orb. Everything works without it; this only adds.
document.documentElement.classList.add('js');

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const finePointer = matchMedia('(hover: hover) and (pointer: fine)');

/* ---------- copy buttons ---------- */
$$('[data-copy]').forEach((btn) => {
  let timer = 0;
  btn.addEventListener('click', async () => {
    const code = document.getElementById(btn.dataset.copy);
    const text = code.textContent.trim();
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = 'Copied';
      btn.classList.add('is-done');
    } catch (err) {
      getSelection().selectAllChildren(code);
      btn.textContent = 'Press Ctrl+C';
    }
    clearTimeout(timer);
    timer = setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('is-done'); }, 2200);
  });
});
// Announce copies to screen readers through one polite live region.
const live = Object.assign(document.createElement('p'), { className: 'sr-only' });
live.setAttribute('aria-live', 'polite');
document.body.append(live);
$$('[data-copy]').forEach((btn) => btn.addEventListener('click', () => { setTimeout(() => { live.textContent = btn.textContent === 'Copied' ? 'Install command copied' : ''; }, 50); }));

/* ---------- nav background once scrolled ---------- */
const top = $('#top');
const onNav = () => top.classList.toggle('is-scrolled', scrollY > 24);
addEventListener('scroll', onNav, { passive: true });
onNav();

/* ---------- screen tabs (WAI-ARIA tabs, automatic activation) ---------- */
const tabs = $$('[role="tab"]');
const img = $('#shot-img');
const cap = $('#shot-cap');
const panel = $('#shot');
const shotLink = $('#shot-link');
function select(tab, focus) {
  tabs.forEach((t) => { const on = t === tab; t.setAttribute('aria-selected', String(on)); t.tabIndex = on ? 0 : -1; });
  panel.setAttribute('aria-labelledby', tab.id);
  if (focus) tab.focus();
  if (img.getAttribute('src') === tab.dataset.src) return;
  const swap = () => { img.src = tab.dataset.src; img.alt = tab.dataset.alt; cap.textContent = tab.dataset.cap; shotLink.href = tab.dataset.src; };
  if (reduced.matches) { swap(); return; }
  img.classList.add('is-swapping');
  const pre = new Image();
  pre.src = tab.dataset.src;
  const show = () => { swap(); requestAnimationFrame(() => img.classList.remove('is-swapping')); };
  (pre.decode ? pre.decode() : Promise.resolve()).then(show, show);
}
tabs.forEach((tab, i) => {
  tab.addEventListener('click', () => select(tab, false));
  tab.addEventListener('keydown', (e) => {
    const k = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
    if (k === undefined) return;
    e.preventDefault();
    select(tabs[(k + tabs.length) % tabs.length], true);
  });
});
// Warm the other screenshots once the section is near.
new IntersectionObserver((entries, obs) => {
  if (!entries[0].isIntersecting) return;
  obs.disconnect();
  tabs.forEach((t) => { const p = new Image(); p.src = t.dataset.src; });
}, { rootMargin: '400px' }).observe(panel);

/* ---------- pointer tilt on the screenshot frame ---------- */
const tilt = $('.frame-tilt');
if (tilt) {
  panel.addEventListener('pointermove', (e) => {
    if (reduced.matches || !finePointer.matches) return;
    const r = panel.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5;
    const y = (e.clientY - r.top) / r.height - 0.5;
    tilt.style.setProperty('--ry', `${(x * 7).toFixed(2)}deg`);
    tilt.style.setProperty('--rx', `${(-y * 5).toFixed(2)}deg`);
  });
  panel.addEventListener('pointerleave', () => { tilt.style.setProperty('--ry', '0deg'); tilt.style.setProperty('--rx', '0deg'); });
}

/* ---------- phones, tablets and Macs: send the page to a PC ---------- */
const root = document.documentElement;
const pageUrl = 'https://zakariahibaoui2.github.io/hib-clean-pc/';
const shareUrl = (location.origin + location.pathname === pageUrl || location.protocol === 'file:' ? pageUrl : location.origin + location.pathname) + '#install';
const device = root.dataset.device || '';
if (device) {
  $$('.away-device').forEach((el) => {
    el.textContent = el.closest('.away-hero') ? device.charAt(0).toUpperCase() + device.slice(1) : device;
  });
}
const installSection = $('#install');
const syncInstallLabel = () => installSection.setAttribute('aria-labelledby', root.dataset.os === 'away' ? 'away-title' : 'install-title');
syncInstallLabel();

if (navigator.share) {
  $$('[data-share]').forEach((btn) => {
    btn.hidden = false;
    btn.addEventListener('click', async () => {
      try {
        await navigator.share({ title: 'Hib Clean PC', text: 'Install Hib Clean PC on my Windows PC', url: shareUrl });
      } catch (err) { /* closed the share sheet */ }
    });
  });
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (err) { /* fall through */ }
  const t = Object.assign(document.createElement('textarea'), { value: text, readOnly: true });
  t.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
  document.body.append(t);
  t.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
  t.remove();
  return ok;
}
$$('[data-copy-link]').forEach((btn) => {
  const label = $('span', btn);
  let timer = 0;
  btn.addEventListener('click', async () => {
    const ok = await copyText(shareUrl);
    label.textContent = ok ? 'Link copied. Paste it on your PC' : shareUrl;
    live.textContent = ok ? 'Link copied' : '';
    btn.classList.toggle('is-done', ok);
    clearTimeout(timer);
    timer = setTimeout(() => { label.textContent = 'Copy link for your PC'; btn.classList.remove('is-done'); }, 3200);
  });
});
$$('[data-mailto]').forEach((a) => {
  a.href = 'mailto:?subject=' + encodeURIComponent('Hib Clean PC for my PC') + '&body=' + encodeURIComponent('Install Hib Clean PC on my Windows PC: ' + shareUrl);
});
$$('[data-show-windows]').forEach((btn) => btn.addEventListener('click', () => {
  root.dataset.os = 'windows';
  syncInstallLabel();
  const h = $('#install-title');
  h.setAttribute('tabindex', '-1');
  h.focus({ preventScroll: true });
  installSection.scrollIntoView({ behavior: reduced.matches ? 'auto' : 'smooth', block: 'start' });
}));

/* QR codes for the page, drawn on this device when they come near the screen. */
const qrBoxes = $$('[data-qr]');
if (qrBoxes.length && 'IntersectionObserver' in window) {
  const qrIO = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      qrIO.unobserve(entry.target);
      import('./qr.js').then(({ qrSvg }) => {
        entry.target.innerHTML = qrSvg(shareUrl, { label: 'QR code for ' + shareUrl.replace('https://', '') });
      }).catch(() => { entry.target.closest('figure').hidden = true; });
    });
  }, { rootMargin: '300px' });
  qrBoxes.forEach((b) => qrIO.observe(b));
}

/* ---------- the fixes: scroll progress drives the score ---------- */
const orbEl = $('#orb');
const START = Number(orbEl.dataset.start) || 69;
const steps = $$('.step');
const scoreEl = $('#score');
const verdictEl = $('#verdict');
const kindOf = (s) => (s >= 65 ? 'good' : s >= 40 ? 'mid' : 'bad');
const verdictOf = (s) => (s >= 85 ? 'Great shape' : s >= 65 ? 'Good, with a few things to fix' : 'Needs some care');
let orb = null;

function scrollScore() {
  const vh = innerHeight;
  let score = START;
  // On tall screens the first fix is already in view at the top of the page;
  // hold the score at its start until the visitor actually scrolls.
  const gate = Math.min(1, scrollY / (vh * 0.25));
  steps.forEach((step) => {
    const r = step.getBoundingClientRect();
    const p = gate * Math.min(1, Math.max(0, (vh * 0.62 - r.top) / (r.height * 0.55)));
    step.classList.toggle('is-on', p > 0.45);
    score += Number(step.dataset.delta) * p;
  });
  return score;
}
let ticking = false;
function onStepsScroll() {
  if (ticking) return;
  ticking = true;
  requestAnimationFrame(() => {
    ticking = false;
    const s = scrollScore();
    if (orb && orb.ready) orb.api.setTarget(s);
  });
}
addEventListener('scroll', onStepsScroll, { passive: true });
addEventListener('resize', onStepsScroll, { passive: true });
scrollScore();

function showLevel(v) {
  scoreEl.textContent = v;
  verdictEl.textContent = verdictOf(v);
  orbEl.dataset.kind = kindOf(v);
}

/* ---------- the 3D orb, loaded after the page is ready ---------- */
const capture = new URLSearchParams(location.search).has('capture');
function fallback() {
  document.documentElement.classList.remove('gl');
  $('.orb-still', orbEl).src = 'assets/orb.webp';
  showLevel(START);
}
async function startOrb() {
  if (!document.documentElement.classList.contains('gl')) return; // the still image stays
  try {
    const { mountOrb } = await import('./orb.js');
    orb = { ready: false, api: null };
    const intro = capture ? START : 0;
    orb.api = mountOrb(orbEl, {
      start: intro,
      onLevel: showLevel,
      onReady: () => {
        orbEl.classList.add('is-live');
        orbEl.parentElement.classList.add('is-live');
        orb.ready = true;
        // Fill from empty to the score, slowly enough to watch the colour change.
        orb.api.setTarget(scrollScore(), capture ? 50 : 1.15);
      },
    });
    if (capture) window.__orb = orb.api;
  } catch (err) {
    // Fall back to the filled still image; the page is complete without the 3D orb.
    fallback();
    console.warn('3D orb unavailable', err);
  }
}
const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 200));
if (document.readyState === 'complete') idle(startOrb, { timeout: 1200 });
else addEventListener('load', () => idle(startOrb, { timeout: 1200 }), { once: true });
