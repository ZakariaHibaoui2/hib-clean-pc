'use strict';
/* Hib Clean PC interface. Talks to the host through window.chrome.webview;
   every system action is a bundled PowerShell script (see scripts/). */

// ---------- Bridge ----------
const bridge = (() => {
  const wv = window.chrome && window.chrome.webview;
  const pending = new Map();
  let next = 0;
  if (wv) {
    wv.addEventListener('message', (e) => {
      const m = e.data;
      const p = m && pending.get(m.id);
      if (!p) return;
      pending.delete(m.id);
      if (m.ok) p.resolve(m.data); else p.reject(new Error(m.error || 'failed'));
    });
  }
  return (cmd, args = {}, opts = {}) => new Promise((resolve, reject) => {
    if (!wv) return reject(new Error('no-host'));
    const id = ++next;
    pending.set(id, { resolve, reject });
    wv.postMessage({ id, cmd, args, admin: !!opts.admin });
  });
})();

// ---------- Helpers ----------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

let lang = 'en';
const t = (key, vars) => {
  const dict = I18N[lang] || I18N.en;
  let s = dict[key] ?? I18N.en[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(v);
  return s;
};
const nf = () => new Intl.NumberFormat(lang, { numberingSystem: 'latn', maximumFractionDigits: 1 });
const num = (n) => nf().format(n);
const bytes = (b) => {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0; let v = Number(b) || 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${new Intl.NumberFormat(lang, { numberingSystem: 'latn', maximumFractionDigits: v < 10 && i > 1 ? 1 : 0 }).format(v)} ${t('unit' + units[i])}`;
};
const dateText = (iso, opts = { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) =>
  new Intl.DateTimeFormat(lang, { numberingSystem: 'latn', ...opts }).format(new Date(iso));

let toastTimer;
function toast(text, kind = '') {
  const el = $('#toast');
  el.textContent = text;
  el.className = `toast ${kind}`;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 4200);
}

// Turns a failed call into a sentence. "cancelled" = the user said No to Windows' permission prompt.
function failure(err) {
  const m = String(err && err.message || err);
  if (m === 'cancelled') return t('errCancelled');
  if (m === 'needs-admin') return t('errAdmin');
  if (m === 'no-host') return t('errNoHost');
  return t('errGeneric', { detail: m.slice(0, 160) });
}

async function withBusy(button, label, fn) {
  const before = button.innerHTML;
  button.disabled = true;
  button.classList.add('busy');
  button.innerHTML = `<span class="spin" aria-hidden="true"></span>${esc(label)}`;
  try { return await fn(); } finally {
    button.disabled = false;
    button.classList.remove('busy');
    if (button.isConnected) button.innerHTML = before;
  }
}

// ---------- Data, cached per session ----------
const cache = {};
const loaders = {
  system: () => bridge('system'),
  junk: () => bridge('junk', { mode: 'scan' }),
  startup: () => bridge('startup', { mode: 'list' }),
  tweaks: () => bridge('tweaks', { mode: 'list' }),
  apps: () => bridge('apps', { mode: 'list' }),
  battery: () => bridge('battery', { mode: 'report' }),
  updates: () => bridge('updates', { mode: 'list' }),
  dns: () => bridge('dns', { mode: 'status' }),
  laptop: () => bridge('laptop'),
};
function load(key, force = false) {
  if (force || !cache[key]) cache[key] = loaders[key]();
  return cache[key];
}

// ---------- Health score ----------
// Starts at 100; each problem found takes points off and becomes a suggested fix.
function healthOf(d) {
  const issues = [];
  const add = (weight, key, section, vars) => issues.push({ weight, key, section, vars });
  if (d.system) {
    const free = d.system.drive.free / d.system.drive.total;
    if (free < 0.1) add(20, 'fixDiskLow', 'clean', { free: bytes(d.system.drive.free) });
    else if (free < 0.2) add(10, 'fixDiskLow', 'clean', { free: bytes(d.system.drive.free) });
  }
  if (d.junk) {
    const junk = d.junk.filter((c) => c.readable && c.id !== 'windows-old').reduce((s, c) => s + c.bytes, 0);
    if (junk > 5 * 2 ** 30) add(12, 'fixJunk', 'clean', { size: bytes(junk) });
    else if (junk > 2 ** 30) add(6, 'fixJunk', 'clean', { size: bytes(junk) });
  }
  if (d.startup) {
    const on = d.startup.filter((s) => s.enabled && !/microsoft/i.test(s.publisher || '')).length;
    if (on > 8) add(12, 'fixStartup', 'startup', { n: on });
    else if (on > 4) add(6, 'fixStartup', 'startup', { n: on });
  }
  if (d.tweaks) {
    const showing = d.tweaks.filter((x) => !x.applied).length;
    if (showing >= 6) add(10, 'fixAds', 'windows', { n: showing });
    else if (showing >= 1) add(5, 'fixAds', 'windows', { n: showing });
  }
  if (d.apps) {
    const junkApps = d.apps.filter((a) => a.kind === 'junk').length;
    if (junkApps >= 5) add(6, 'fixBloat', 'windows', { n: junkApps });
    else if (junkApps >= 1) add(3, 'fixBloat', 'windows', { n: junkApps });
  }
  if (d.battery && d.battery.hasBattery && d.battery.health != null) {
    if (d.battery.health < 60) add(12, 'fixBattery', 'battery', { pct: num(d.battery.health) });
    else if (d.battery.health < 80) add(6, 'fixBattery', 'battery', { pct: num(d.battery.health) });
  }
  if (d.updates && d.updates.available) {
    const n = d.updates.apps.length;
    if (n > 5) add(10, 'fixUpdates', 'updates', { n });
    else if (n > 0) add(5, 'fixUpdates', 'updates', { n });
  }
  if (d.dns && !d.dns.blocking) add(5, 'fixDns', 'adblock', {});
  const score = Math.max(0, Math.min(100, 100 - issues.reduce((s, i) => s + i.weight, 0)));
  return { score, issues: issues.sort((a, b) => b.weight - a.weight) };
}

// ---------- Navigation ----------
const ICONS = {
  home: '<path d="M4 11.5 12 5l8 6.5V20a1 1 0 0 1-1 1h-4.5v-5.5h-5V21H5a1 1 0 0 1-1-1z"/>',
  clean: '<path d="M14.5 3.5 20 9l-8.5 8.5-5.5-5.5zM5 13l6 6-2 2H4v-5z"/><path d="M15 15l4 4" />',
  startup: '<path d="M12 3v8"/><path d="M6.4 6.6a8 8 0 1 0 11.2 0"/>',
  windows: '<path d="M4 5.5 11 4.5v7H4zM13 4.2 20 3v8.5h-7zM4 12.5h7v7L4 18.5zM13 12.5h7V21l-7-1z"/>',
  battery: '<rect x="3" y="7" width="16" height="10" rx="2.5"/><path d="M21 10.5v3"/><path d="M6.5 10v4M10 10v4"/>',
  updates: '<path d="M12 4v11"/><path d="M7.5 10.5 12 15l4.5-4.5"/><path d="M5 19.5h14"/>',
  adblock: '<path d="M12 3 19.5 6v5.5c0 4.4-3.1 8.2-7.5 9.5-4.4-1.3-7.5-5.1-7.5-9.5V6z"/><path d="M8.5 12h7"/>',
  laptop: '<rect x="5" y="5" width="14" height="10" rx="1.5"/><path d="M3 18.5h18"/>',
};
const SECTIONS = ['home', 'clean', 'startup', 'windows', 'battery', 'updates', 'adblock', 'laptop'];

function renderNav(active) {
  $('#nav').innerHTML = SECTIONS.map((s) => `
    <a href="#${s}" class="${s === active ? 'on' : ''}" ${s === active ? 'aria-current="page"' : ''}>
      <svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[s]}</svg><span class="label">${esc(t('nav_' + s))}</span><span class="badge" data-badge="${s}" hidden></span>
    </a>`).join('');
  updateBadges();
}

// Small live readings next to the section names, from scans already done.
const JUNK_QUICK = ['user-temp', 'browser', 'crash-dumps', 'thumbnails'];
const junkTotal = (cats) => cats.filter((c) => c.readable && c.id !== 'windows-old').reduce((s, c) => s + c.bytes, 0);
async function updateBadges() {
  const set = (name, text, kind = '') => {
    const el = $(`[data-badge="${name}"]`);
    if (!el) return;
    el.hidden = text == null;
    el.className = `badge ${kind}`;
    el.textContent = text ?? '';
  };
  const settled = async (key) => { try { return cache[key] ? await cache[key] : null; } catch (e) { return null; } };
  const [junk, updates, dns, tweaks] = await Promise.all(['junk', 'updates', 'dns', 'tweaks'].map(settled));
  if (junk) { const b = junkTotal(junk); set('clean', b > 100 * 2 ** 20 ? bytes(b) : null, b > 2 ** 30 ? 'warn' : ''); }
  if (updates && updates.available) set('updates', updates.apps.length ? num(updates.apps.length) : null, 'warn');
  if (tweaks) { const n = tweaks.filter((x) => !x.applied).length; set('windows', n ? num(n) : null, ''); }
  if (dns) set('adblock', '', dns.blocking ? 'dot ok' : 'dot');
}

function route() {
  stopMedia();
  const name = SECTIONS.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'home';
  renderNav(name);
  const view = $('#view');
  view.innerHTML = '';
  view.dataset.section = name;
  view.classList.remove('enter');
  VIEWS[name](view);
  void view.offsetWidth;
  view.classList.add('enter');
  view.focus({ preventScroll: true });
  view.scrollTop = 0;
}

function header(title, lead, actions = '') {
  return `<header class="head"><div><h1>${esc(title)}</h1><p class="lead">${esc(lead)}</p></div><div class="head-actions">${actions}</div></header>`;
}
const loading = (text) => `<div class="loading"><span class="spin" aria-hidden="true"></span>${esc(text)}</div>`;
const skeleton = (text, rows = 4) => `<div class="skeleton" aria-busy="true">${'<i></i>'.repeat(rows)}<p>${esc(text)}</p></div>`;
const errorBox = (err, retryId) => `<div class="error-box"><p>${esc(failure(err))}</p>${retryId ? `<button class="btn ghost" id="${retryId}">${esc(t('tryAgain'))}</button>` : ''}</div>`;

// ---------- Liquid orb ----------
// Water fills the orb to `value` percent, with a slow two-layer wave.
const ORB_COLORS = { good: ['#5cf0d8', '#1fa9c9'], mid: ['#ffd98a', '#e0952a'], bad: ['#ff9d8f', '#d9485a'] };
const orbHtml = (id, unit, extra = '') => `
  <div class="orb ${extra}" ${id ? `id="${id}"` : ''}><canvas aria-hidden="true"></canvas><div class="orb-glass"></div>
    <div class="orb-read"><span class="score">–</span><span class="of">${esc(unit)}</span></div></div>`;

function orb(el, value, kind, onValue) {
  const canvas = $('canvas', el);
  const ctx = canvas.getContext('2d');
  const dpr = Math.max(1, window.devicePixelRatio || 1);
  const size = el.getBoundingClientRect().width || 250;
  canvas.width = Math.round(size * dpr);
  canvas.height = Math.round(size * dpr);
  el.classList.remove('good', 'mid', 'bad');
  el.classList.add(kind);
  const [top, bottom] = ORB_COLORS[kind];
  const bubbles = Array.from({ length: 9 }, (_, i) => ({ x: (i * 0.137 + 0.11) % 1, y: Math.random(), r: 1.2 + (i % 3), v: 0.025 + (i % 4) * 0.012 }));
  let level = reduced ? value : 0;
  let last = performance.now();
  let shown = -1;
  const draw = (now) => {
    if (!el.isConnected) return;
    const dt = Math.min(0.05, Math.max(0, (now - last) / 1000));
    last = now;
    level += (value - level) * (1 - Math.exp(-dt * 3.6));
    if (Math.abs(value - level) < 0.15) level = value;
    const w = canvas.width; const h = canvas.height; const tt = now / 1000;
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.beginPath(); ctx.arc(w / 2, h / 2, w / 2, 0, Math.PI * 2); ctx.clip();
    const bg = ctx.createRadialGradient(w * 0.4, h * 0.3, w * 0.05, w / 2, h / 2, w / 2);
    bg.addColorStop(0, '#12354a'); bg.addColorStop(1, '#061520');
    ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);
    const surface = h * (1 - level / 100);
    const amp = h * 0.018;
    for (const layer of [{ a: 0.45, s: 1.1, o: 1.7 }, { a: 1, s: 0.8, o: 0 }]) {
      ctx.beginPath();
      ctx.moveTo(0, h);
      for (let x = 0; x <= w; x += 4) {
        const y = surface + Math.sin(x / w * Math.PI * 2 * 1.3 + tt * layer.s + layer.o) * amp * (reduced ? 0.5 : 1);
        ctx.lineTo(x, y);
      }
      ctx.lineTo(w, h); ctx.closePath();
      const g = ctx.createLinearGradient(0, surface, 0, h);
      g.addColorStop(0, top); g.addColorStop(1, bottom);
      ctx.globalAlpha = layer.a; ctx.fillStyle = g; ctx.fill();
    }
    ctx.globalAlpha = 0.35; ctx.fillStyle = '#ffffff';
    for (const b of bubbles) {
      if (!reduced) b.y -= b.v * dt;
      if (b.y < 0) b.y = 1;
      const by = surface + (h - surface) * b.y;
      if (by > surface + amp * 2) { ctx.beginPath(); ctx.arc(b.x * w, by, b.r * dpr, 0, Math.PI * 2); ctx.fill(); }
    }
    ctx.restore();
    const rounded = Math.round(level);
    if (rounded !== shown) { shown = rounded; onValue(rounded); }
    if (!reduced) requestAnimationFrame(draw);
  };
  requestAnimationFrame(draw);
}

// ---------- Views ----------
const VIEWS = {};

// Home: the health score, a one-click clean, and the top fixes.
VIEWS.home = (view) => {
  view.innerHTML = `
    ${header(t('homeTitle'), t('homeLead'), `<button class="btn ghost" id="rescan">${esc(t('scanAgain'))}</button>`)}
    <section class="hero-grid">
      <div class="orb-card">
        ${orbHtml('gauge', '/100')}
        <p class="verdict" id="verdict">${esc(t('scanning'))}</p>
      </div>
      <div class="side-stack">
        <div class="quick" id="quick" hidden></div>
        <div class="fixes">
          <h2>${esc(t('topFixes'))}</h2>
          <ol id="fixes" class="fix-list"><li class="ghost-row">${skeleton(t('scanning'), 3)}</li></ol>
        </div>
      </div>
    </section>
    <section class="tiles" id="tiles"></section>`;
  $('#gauge .score').id = 'score';
  $('#rescan').onclick = () => { for (const k of Object.keys(cache)) delete cache[k]; route(); };

  const keys = ['system', 'junk', 'startup', 'tweaks', 'apps', 'battery', 'updates', 'dns'];
  const got = {};
  const done = keys.map((k) => load(k).then((v) => { got[k] = v; tiles(got); updateBadges(); if (k === 'junk') quick(v); }, () => {}));
  Promise.all(done).then(() => {
    if (!$('#gauge')) return;
    const { score, issues } = healthOf(got);
    orb($('#gauge'), score, score >= 65 ? 'good' : score >= 40 ? 'mid' : 'bad', (v) => { const s = $('#score'); if (s) s.textContent = num(v); });
    $('#verdict').textContent = t(score >= 85 ? 'verdictGreat' : score >= 65 ? 'verdictOk' : 'verdictBad');
    const top = issues.slice(0, 4);
    $('#fixes').innerHTML = top.length ? top.map((i) => `
      <li><a class="fix" href="#${i.section}">
        <span class="fix-pts">−${i.weight}</span>
        <span class="fix-text">${esc(t(i.key, i.vars))}</span>
        <span class="fix-go">${esc(t('fixIt'))}</span>
      </a></li>`).join('') : `<li class="all-good">${esc(t('allGood'))}</li>`;
  });
};

// One click cleans the junk that needs no permission: temp files, browser caches, crash dumps, previews.
function quick(cats) {
  const el = $('#quick');
  if (!el) return;
  const ids = cats.filter((c) => JUNK_QUICK.includes(c.id) && c.bytes > 0).map((c) => c.id);
  const size = cats.filter((c) => ids.includes(c.id)).reduce((s, c) => s + c.bytes, 0);
  if (size < 50 * 2 ** 20) { el.hidden = true; return; }
  el.hidden = false;
  el.innerHTML = `<div class="quick-text"><b>${esc(t('quickTitle', { size: bytes(size) }))}</b><span>${esc(t('quickSub'))}</span></div>
    <button class="btn primary" id="quick-go">${esc(t('quickClean'))}</button>`;
  $('#quick-go').onclick = (e) => withBusy(e.currentTarget, t('cleaning'), async () => {
    try {
      const r = await bridge('junk', { mode: 'clean', ids });
      toast(t('quickDone', { size: bytes(r.freed) }), 'ok');
      delete cache.junk; delete cache.system;
      route();
    } catch (err) { toast(failure(err), 'bad'); }
  });
}

function tiles(d) {
  const el = $('#tiles');
  if (!el) return;
  const items = [];
  if (d.system) {
    items.push({ k: t('tileDisk'), v: bytes(d.system.drive.free), s: t('tileDiskOf', { total: bytes(d.system.drive.total) }), href: '#clean' });
    items.push({ k: t('tileMemory'), v: bytes(d.system.memory.total - d.system.memory.free), s: t('tileMemoryOf', { total: bytes(d.system.memory.total) }) });
  }
  if (d.junk) items.push({ k: t('tileJunk'), v: bytes(junkTotal(d.junk)), s: t('tileJunkSub'), href: '#clean' });
  if (d.battery && d.battery.hasBattery) items.push({ k: t('tileBattery'), v: `${num(d.battery.health)}%`, s: t('tileBatterySub'), href: '#battery' });
  if (d.updates && d.updates.available) items.push({ k: t('tileUpdates'), v: num(d.updates.apps.length), s: t('tileUpdatesSub'), href: '#updates' });
  if (d.dns) items.push({ k: t('tileAds'), v: d.dns.blocking ? t('on') : t('off'), s: t('tileAdsSub'), href: '#adblock' });
  el.innerHTML = items.map((i) => `
    <${i.href ? `a href="${i.href}"` : 'div'} class="tile">
      <span class="tile-k">${esc(i.k)}</span><span class="tile-v">${esc(i.v)}</span><span class="tile-s">${esc(i.s)}</span>
    </${i.href ? 'a' : 'div'}>`).join('');
}

// Clean up: junk files by category.
const JUNK_ORDER = ['user-temp', 'browser', 'win-temp', 'update-cache', 'delivery', 'error-reports', 'crash-dumps', 'thumbnails', 'recycle'];
VIEWS.clean = (view) => {
  view.innerHTML = `${header(t('cleanTitle'), t('cleanLead'), `<button class="btn ghost" id="rescan">${esc(t('scanAgain'))}</button>`)}
    <div id="body">${skeleton(t('measuring'), 6)}</div>`;
  $('#rescan').onclick = () => { delete cache.junk; route(); };
  load('junk').then((cats) => {
    const byId = Object.fromEntries(cats.map((c) => [c.id, c]));
    const rows = JUNK_ORDER.map((id) => byId[id]).filter(Boolean);
    const old = byId['windows-old'];
    $('#body').innerHTML = `
      <ul class="rows checks" id="cats">${rows.map((c) => `
        <li><label class="row">
          <input type="checkbox" value="${c.id}" ${c.id !== 'recycle' && (c.bytes > 0 || !c.readable) ? 'checked' : ''} ${c.readable && c.bytes === 0 ? 'disabled' : ''}>
          <span class="row-main"><b>${esc(t('junk_' + c.id))}</b><small>${esc(t('junk_' + c.id + '_d'))}</small></span>
          <span class="row-side">${c.readable ? `<b>${esc(bytes(c.bytes))}</b>` : `<span class="chip">${esc(t('needsPermission'))}</span>`}
            ${c.admin ? `<small>${esc(t('asksPermission'))}</small>` : ''}</span>
        </label></li>`).join('')}
      </ul>
      ${old && old.present ? `<div class="note"><p>${esc(t('windowsOld'))}</p><button class="btn ghost" id="storage">${esc(t('openStorage'))}</button></div>` : ''}
      <div class="bar-actions sticky"><p id="sel"></p><button class="btn primary" id="go">${esc(t('cleanNow'))}</button></div>
      <div id="result"></div>`;
    const selected = () => $$('#cats input:checked').map((i) => byId[i.value]);
    const update = () => {
      const s = selected();
      const size = s.filter((c) => c.readable).reduce((n, c) => n + c.bytes, 0);
      $('#sel').textContent = t('selected', { size: bytes(size) }) + (s.some((c) => !c.readable) ? ` ${t('plusMore')}` : '');
      $('#go').disabled = s.length === 0;
    };
    $('#cats').addEventListener('change', update);
    update();
    if ($('#storage')) $('#storage').onclick = () => bridge('host.open', { url: 'ms-settings:storagesense' });
    $('#go').onclick = (e) => withBusy(e.currentTarget, t('cleaning'), async () => {
      const s = selected();
      const plain = s.filter((c) => !c.admin).map((c) => c.id);
      const admin = s.filter((c) => c.admin).map((c) => c.id);
      let freed = 0; let files = 0; let skipped = 0; let note = '';
      if (plain.length) {
        const r = await bridge('junk', { mode: 'clean', ids: plain }).catch((err) => { note = failure(err); return null; });
        if (r) { freed += r.freed; files += r.files; skipped += r.skipped; }
      }
      if (admin.length) {
        const r = await bridge('junk', { mode: 'clean', ids: admin }, { admin: true }).catch((err) => { note = failure(err); return null; });
        if (r) { freed += r.freed; files += r.files; skipped += r.skipped; }
      }
      delete cache.junk; delete cache.system;
      $('#result').innerHTML = `<div class="result">
        <span class="big" id="freed">0</span>
        <p>${esc(t('freedText', { files: num(files) }))}${skipped ? ` ${esc(t('skippedText', { n: num(skipped) }))}` : ''}</p>
        ${note ? `<p class="warn">${esc(note)}</p>` : ''}</div>`;
      countBytes($('#freed'), freed);
    });
  }, (err) => {
    $('#body').innerHTML = errorBox(err, 'retry');
    $('#retry').onclick = () => { delete cache.junk; route(); };
  });
};

function countBytes(el, total) {
  if (reduced) { el.textContent = bytes(total); return; }
  const start = performance.now();
  const step = (now) => {
    const k = Math.min(1, (now - start) / 1200);
    el.textContent = bytes(total * (1 - (1 - k) ** 3));
    if (k < 1 && el.isConnected) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// Startup apps: one switch each, like Task Manager.
VIEWS.startup = (view) => {
  view.innerHTML = `${header(t('startupTitle'), t('startupLead'))}<div id="body">${skeleton(t('loading'), 5)}</div>`;
  load('startup').then((items) => {
    const sorted = [...items].sort((a, b) => Number(b.enabled) - Number(a.enabled) || a.name.localeCompare(b.name));
    const on = items.filter((i) => i.enabled).length;
    $('#body').innerHTML = items.length ? `
      <p class="summary">${esc(t('startupSummary', { n: num(items.length), on: num(on) }))}</p>
      <ul class="rows">${sorted.map((i, n) => `
        <li class="row">
          <span class="app-icon">${i.icon ? `<img src="${esc(i.icon)}" alt="">` : '<span class="app-dot"></span>'}</span>
          <span class="row-main"><b>${esc(i.name)}</b>
            <small>${esc(i.publisher || t('unknownPublisher'))}${i.exists ? '' : ` · ${esc(t('missingFile'))}`}</small></span>
          <span class="row-side">
            ${i.hint ? `<span class="chip soft">${esc(t('hintStartup', { kind: t('kind_' + i.hint) }))}</span>` : ''}
            <button class="switch" role="switch" aria-checked="${i.enabled}" data-n="${n}" aria-label="${esc(i.name)}"><span></span></button>
          </span>
        </li>`).join('')}</ul>
      <p class="fine">${esc(t('startupFine'))}</p>` : `<p class="empty">${esc(t('startupEmpty'))}</p>`;
    $$('#body .switch').forEach((sw) => sw.addEventListener('click', async () => {
      const item = sorted[Number(sw.dataset.n)];
      const want = sw.getAttribute('aria-checked') !== 'true';
      sw.disabled = true;
      sw.setAttribute('aria-checked', String(want));
      try {
        const r = await bridge('startup', { mode: 'set', id: item.id, enabled: want }, { admin: item.admin });
        item.enabled = r.enabled;
        sw.setAttribute('aria-checked', String(r.enabled));
        toast(t(r.enabled ? 'startupOn' : 'startupOff', { name: item.name }), 'ok');
      } catch (err) {
        sw.setAttribute('aria-checked', String(!want));
        toast(failure(err), 'bad');
      } finally { sw.disabled = false; }
    }));
  }, (err) => { $('#body').innerHTML = errorBox(err); });
};

// Windows clean-up: ads and suggestions, then pre-installed apps.
VIEWS.windows = (view) => {
  view.innerHTML = `${header(t('winTitle'), t('winLead'))}
    <section class="card"><div class="card-head"><h2>${esc(t('winAds'))}</h2><button class="btn primary" id="all" disabled>${esc(t('removeAll'))}</button></div>
      <label class="check-line"><input type="checkbox" id="restore" checked> ${esc(t('restoreFirst'))}</label>
      <div id="tweaks">${skeleton(t('loading'), 5)}</div><div id="explorer"></div></section>
    <section class="card"><div class="card-head"><h2>${esc(t('winApps'))}</h2><button class="btn primary" id="rm" disabled>${esc(t('removeSelected'))}</button></div>
      <p class="fine">${esc(t('winAppsLead'))}</p>
      <div id="apps">${skeleton(t('loading'), 3)}</div></section>`;

  let needsExplorer = false;
  const showExplorer = () => {
    if (!needsExplorer || $('#restart-explorer')) return;
    $('#explorer').innerHTML = `<div class="note"><p>${esc(t('explorerNote'))}</p><button class="btn ghost" id="restart-explorer">${esc(t('restartExplorer'))}</button></div>`;
    $('#restart-explorer').onclick = (e) => withBusy(e.currentTarget, t('working'), async () => {
      await bridge('tweaks', { mode: 'restart-explorer' }).catch((err) => toast(failure(err), 'bad'));
      $('#explorer').innerHTML = '';
      needsExplorer = false;
    });
  };

  // A restore point needs admin rights and Windows' permission prompt.
  async function maybeRestorePoint() {
    if (!$('#restore').checked) return true;
    try {
      const r = await bridge('restore', { mode: 'create' }, { admin: true });
      if (r.created) toast(t('restoreMade'), 'ok');
      else toast(t(r.reason === 'recent' ? 'restoreRecent' : 'restoreOff'), r.reason === 'recent' ? 'ok' : 'bad');
      return r.created || r.reason === 'recent' || confirm(t('restoreOffContinue'));
    } catch (err) { toast(failure(err), 'bad'); return false; }
  }

  const renderTweaks = (list) => {
    const showing = list.filter((x) => !x.applied);
    $('#all').disabled = showing.length === 0;
    $('#tweaks').innerHTML = `<ul class="rows">${list.map((x) => `
      <li class="row">
        <span class="state ${x.applied ? 'done' : ''}" aria-hidden="true"></span>
        <span class="row-main"><b>${esc(t('tw_' + x.id))}</b><small>${esc(t('tw_' + x.id + '_d'))}</small></span>
        <span class="row-side">
          ${x.admin ? `<small>${esc(t('asksPermission'))}</small>` : ''}
          ${x.applied
            ? `<span class="chip ok">${esc(t('removed'))}</span>${x.undo ? `<button class="btn link" data-undo="${x.id}">${esc(t('undo'))}</button>` : ''}`
            : `<button class="btn small" data-apply="${x.id}">${esc(t('remove'))}</button>`}
        </span>
      </li>`).join('')}</ul>`;
  };

  async function run(mode, ids, button) {
    const list = await cache.tweaks;
    const byId = Object.fromEntries(list.map((x) => [x.id, x]));
    const plain = ids.filter((id) => !byId[id].admin);
    const admin = ids.filter((id) => byId[id].admin);
    return withBusy(button, t('working'), async () => {
      if (mode === 'apply' && !(await maybeRestorePoint())) return;
      const results = [];
      if (plain.length) results.push(...await bridge('tweaks', { mode, ids: plain }).catch((err) => { toast(failure(err), 'bad'); return []; }));
      if (admin.length) results.push(...await bridge('tweaks', { mode, ids: admin }, { admin: true }).catch((err) => { toast(failure(err), 'bad'); return []; }));
      const ok = results.filter((r) => r.ok);
      if (ok.some((r) => byId[r.id].restart === 'explorer')) needsExplorer = true;
      if (ok.length) toast(t(mode === 'apply' ? 'tweaksDone' : 'tweaksUndone', { n: num(ok.length) }), 'ok');
      const fresh = await load('tweaks', true);
      renderTweaks(fresh);
      showExplorer();
    });
  }

  load('tweaks').then((list) => {
    renderTweaks(list);
    $('#tweaks').addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.dataset.apply) run('apply', [b.dataset.apply], b);
      if (b.dataset.undo) run('undo', [b.dataset.undo], b);
    });
    $('#all').onclick = async (e) => run('apply', (await cache.tweaks).filter((x) => !x.applied).map((x) => x.id), e.currentTarget);
  }, (err) => { $('#tweaks').innerHTML = errorBox(err); });

  const renderApps = (apps) => {
    if (!apps.length) { $('#apps').innerHTML = `<p class="empty">${esc(t('noBloat'))}</p>`; $('#rm').disabled = true; return; }
    $('#apps').innerHTML = `<ul class="rows checks compact">${apps.map((a) => `
      <li><label class="row">
        <input type="checkbox" value="${esc(a.id)}" ${a.kind === 'junk' ? 'checked' : ''}>
        <span class="row-main"><b>${esc(a.name)}</b></span>
        <span class="row-side"><span class="chip ${a.kind === 'junk' ? '' : 'soft'}">${esc(t(a.kind === 'junk' ? 'kindJunk' : 'kindOptional'))}</span></span>
      </label></li>`).join('')}</ul>`;
    const update = () => {
      const n = $$('#apps input:checked').length;
      $('#rm').disabled = n === 0;
      $('#rm').textContent = n ? t('removeN', { n: num(n) }) : t('removeSelected');
      delete $('#rm').dataset.confirm;
    };
    $('#apps').addEventListener('change', update);
    update();
  };
  load('apps').then(renderApps, (err) => { $('#apps').innerHTML = errorBox(err); });

  // Two clicks: the first turns the button into "Confirm", the second removes.
  $('#rm').onclick = async (e) => {
    const b = e.currentTarget;
    const ids = $$('#apps input:checked').map((i) => i.value);
    if (!ids.length) return;
    if (!b.dataset.confirm) { b.dataset.confirm = '1'; b.textContent = t('confirmRemove', { n: num(ids.length) }); return; }
    delete b.dataset.confirm;
    await withBusy(b, t('removing'), async () => {
      if (!(await maybeRestorePoint())) return;
      const apps = await cache.apps;
      const names = Object.fromEntries(apps.map((a) => [a.id, a.name]));
      const res = await bridge('apps', { mode: 'remove', ids }).catch((err) => { toast(failure(err), 'bad'); return []; });
      const gone = res.filter((r) => r.ok).map((r) => names[r.id] || r.id);
      const failed = res.filter((r) => !r.ok);
      toast(failed.length ? t('appsPartly', { ok: num(gone.length), bad: num(failed.length) }) : t('appsRemoved', { n: num(gone.length) }), failed.length ? 'bad' : 'ok');
      renderApps(await load('apps', true));
      if (gone.length) {
        $('#apps').insertAdjacentHTML('beforeend', `<p class="fine">${esc(t('reinstallHint'))} ${gone.map((n) =>
          `<button class="btn link" data-store="${esc(n)}">${esc(n)}</button>`).join(' ')}</p>`);
        $$('#apps [data-store]').forEach((x) => { x.onclick = () => bridge('host.open', { url: `ms-windows-store://search/?query=${encodeURIComponent(x.dataset.store)}` }); });
      }
    });
  };
};

// Battery: health, overnight drain, what wakes the PC.
VIEWS.battery = (view) => {
  view.innerHTML = `${header(t('batTitle'), t('batLead'))}<div id="body">${skeleton(t('loading'), 3)}</div>`;
  load('battery').then((b) => {
    if (!b.hasBattery) { $('#body').innerHTML = `<p class="empty">${esc(t('noBattery'))}</p>`; return; }
    const h = b.health ?? 0;
    const grade = h >= 80 ? 'good' : h >= 60 ? 'worn' : 'bad';
    const sleeps = b.sleeps || [];
    const worst = sleeps.reduce((w, s) => (!w || s.perHour > w.perHour ? s : w), null);
    $('#body').innerHTML = `
      <section class="hero-grid">
        <div class="orb-card">
          ${orbHtml('bat-orb', '%', 'gauge')}
          <p class="verdict">${esc(t('bat_' + grade))}</p>
        </div>
        <div class="facts">
          <p class="big-line">${esc(t('batHolds', { pct: num(h) }))}</p>
          <dl class="kv">
            <div><dt>${esc(t('batNow'))}</dt><dd>${esc(num(b.percent))}% · ${esc(t(b.plugged ? 'batPlugged' : 'batOnBattery'))}</dd></div>
            <div><dt>${esc(t('batCapacity'))}</dt><dd>${esc(num(b.full / 1000))} / ${esc(num(b.design / 1000))} Wh</dd></div>
            ${b.cycles ? `<div><dt>${esc(t('batCycles'))}</dt><dd>${esc(num(b.cycles))}</dd></div>` : ''}
          </dl>
          <p class="fine">${esc(t('batTip'))}</p>
        </div>
      </section>
      <section class="card">
        <h2>${esc(t('batSleepTitle'))}</h2>
        ${sleeps.length ? `
          <p class="lead-in">${esc(worst && worst.perHour > 1.5 ? t('batSleepHigh', { rate: num(worst.perHour) }) : t('batSleepOk'))}</p>
          <ul class="rows compact">${sleeps.map((s) => `
            <li class="row"><span class="row-main"><b>${esc(dateText(s.start))}</b><small>${esc(t('batSlept', { h: num(s.hours) }))}</small></span>
              <span class="row-side"><b class="${s.perHour > 1.5 ? 'warn' : ''}" dir="ltr">${s.drainPercent > 0 ? '−' : ''}${esc(num(s.drainPercent))}%</b><small>${esc(t('perHour', { n: num(s.perHour) }))}</small></span></li>`).join('')}</ul>`
          : `<p class="empty">${esc(t('batNoSleeps'))}</p>`}
      </section>
      <section class="card">
        <h2>${esc(t('batWakeTitle'))}</h2>
        ${(b.wakes || []).length ? `<ul class="rows compact">${b.wakes.slice(0, 8).map((w) => `
          <li class="row"><span class="row-main"><b>${esc(dateText(w.time))}</b>
            <small>${esc(w.source ? (w.timer ? t('wokeTimer', { what: w.source }) : t('wokeBy', { what: w.source })) : t('wokeUnknown'))}</small></span>
            ${w.sleptMinutes != null ? `<span class="row-side"><small>${esc(t('afterMin', { n: num(w.sleptMinutes) }))}</small></span>` : ''}</li>`).join('')}</ul>`
          : `<p class="empty">${esc(t('batNoWakes'))}</p>`}
        <h3>${esc(t('batArmed'))}</h3>
        ${(b.armed || []).length ? `<ul class="rows compact" id="armed">${b.armed.map((d, i) => `
          <li class="row"><span class="row-main"><b>${esc(d)}</b></span>
            <span class="row-side"><button class="btn small ghost" data-i="${i}">${esc(t('stopWaking'))}</button></span></li>`).join('')}</ul>
          <p class="fine">${esc(t('armedFine'))}</p>`
          : `<p class="empty">${esc(t('noArmed'))}</p>`}
      </section>`;
    orb($('#bat-orb'), Math.round(h), grade === 'good' ? 'good' : grade === 'worn' ? 'mid' : 'bad',
      (v) => { const sc = $('#bat-orb .score'); if (sc) sc.textContent = num(v); });
    $$('#armed [data-i]').forEach((btn) => btn.addEventListener('click', () => withBusy(btn, t('working'), async () => {
      const device = b.armed[Number(btn.dataset.i)];
      try {
        const r = await bridge('battery', { mode: 'wake', device, allow: false }, { admin: true });
        if (!r.allowed) { btn.closest('li').classList.add('done-row'); btn.replaceWith(Object.assign(document.createElement('span'), { className: 'chip ok', textContent: t('wontWake') })); }
        delete cache.battery;
      } catch (err) { toast(failure(err), 'bad'); }
    })));
  }, (err) => { $('#body').innerHTML = errorBox(err); });
};

// App updates through winget.
VIEWS.updates = (view) => {
  view.innerHTML = `${header(t('updTitle'), t('updLead'), `<button class="btn ghost" id="rescan">${esc(t('checkAgain'))}</button>`)}<div id="body">${skeleton(t('checkingUpdates'), 5)}</div>`;
  $('#rescan').onclick = () => { delete cache.updates; route(); };
  load('updates').then((u) => {
    if (!u.available) { $('#body').innerHTML = `<p class="empty">${esc(t('noWinget'))}</p>`; return; }
    if (!u.apps.length) { $('#body').innerHTML = `<div class="result"><span class="big">✓</span><p>${esc(t('upToDate'))}</p></div>`; return; }
    $('#body').innerHTML = `
      <div class="bar-actions top"><p>${esc(t('updCount', { n: num(u.apps.length) }))}</p><button class="btn primary" id="all">${esc(t('updateAll'))}</button></div>
      <ul class="rows" id="list">${u.apps.map((a, i) => `
        <li class="row" data-i="${i}"><span class="state" aria-hidden="true"></span>
          <span class="row-main"><b>${esc(a.name)}</b><small>${esc(a.version)} → ${esc(a.latest)}</small></span>
          <span class="row-side"><button class="btn small" data-i="${i}">${esc(t('update'))}</button></span></li>`).join('')}</ul>
      <p class="fine">${esc(t('updFine'))}</p>`;
    const one = async (i) => {
      const li = $(`#list li[data-i="${i}"]`);
      const btn = $('button', li);
      if (!btn) return true;
      li.classList.add('working');
      btn.disabled = true;
      btn.innerHTML = `<span class="spin" aria-hidden="true"></span>${esc(t('updating'))}`;
      try {
        const r = await bridge('updates', { mode: 'upgrade', id: u.apps[i].id });
        li.classList.remove('working');
        li.classList.add(r.ok ? 'done-row' : 'bad-row');
        btn.replaceWith(Object.assign(document.createElement('span'), { className: `chip ${r.ok ? 'ok' : 'bad'}`, textContent: r.ok ? t('updated') : t('updFailed') }));
        return r.ok;
      } catch (err) {
        li.classList.remove('working');
        btn.disabled = false; btn.textContent = t('update');
        toast(failure(err), 'bad');
        return false;
      }
    };
    $('#list').addEventListener('click', (e) => { const b = e.target.closest('button[data-i]'); if (b) one(Number(b.dataset.i)); });
    $('#all').onclick = (e) => withBusy(e.currentTarget, t('updating'), async () => {
      let ok = 0;
      for (let i = 0; i < u.apps.length; i++) if (await one(i)) ok++;
      delete cache.updates;
      toast(t('updDone', { n: num(ok) }), 'ok');
    });
  }, (err) => { $('#body').innerHTML = errorBox(err); });
};

// System-wide ad blocking through DNS.
const PROVIDERS = ['adguard', 'quad9', 'cloudflare', 'auto'];
VIEWS.adblock = (view) => {
  view.innerHTML = `${header(t('dnsTitle'), t('dnsLead'))}<div id="body">${skeleton(t('loading'), 2)}</div>`;
  const render = (s) => {
    const current = s.provider;
    $('#body').innerHTML = `
      <div class="status-line ${s.blocking ? 'on' : ''}"><span class="dot" aria-hidden="true"></span>
        <b>${esc(t(s.blocking ? 'dnsProtected' : 'dnsNotProtected'))}</b><span>${esc(t(s.blocking ? 'dnsProtectedSub' : 'dnsNotProtectedSub'))}</span></div>
      <fieldset class="choices"><legend class="sr">${esc(t('dnsChoose'))}</legend>${PROVIDERS.map((p) => `
        <label class="choice ${p === current ? 'current' : ''}">
          <input type="radio" name="dns" value="${p}" ${p === (current && current !== 'auto' && PROVIDERS.includes(current) ? current : 'adguard') ? 'checked' : ''}>
          <span class="choice-body"><b>${esc(t('dns_' + p))}${p === 'adguard' ? ` <span class="chip">${esc(t('recommended'))}</span>` : ''}${p === current ? ` <span class="chip soft">${esc(t('current'))}</span>` : ''}</b>
          <small>${esc(t('dns_' + p + '_d'))}</small></span>
        </label>`).join('')}</fieldset>
      <div class="bar-actions"><p class="fine">${esc(t('dnsFine'))}</p><button class="btn primary" id="apply">${esc(t('apply'))}</button></div>`;
    $('#apply').onclick = (e) => withBusy(e.currentTarget, t('working'), async () => {
      const provider = $('input[name="dns"]:checked').value;
      try {
        const r = await bridge('dns', { mode: 'set', provider }, { admin: true });
        cache.dns = Promise.resolve(r);
        render(r);
        toast(t(r.blocking ? 'dnsNowBlocking' : 'dnsChanged'), 'ok');
      } catch (err) { toast(failure(err), 'bad'); }
    });
  };
  load('dns').then(render, (err) => { $('#body').innerHTML = errorBox(err); });
};

// ---------- Used laptop check ----------
const checks = { screen: null, keyboard: null, camera: null, mic: null, speakers: null };
let laptopInfo = null;

VIEWS.laptop = (view) => {
  view.innerHTML = `${header(t('lapTitle'), t('lapLead'), `<button class="btn primary" id="pdf">${esc(t('makePdf'))}</button>`)}
    <section class="card" id="hw">${skeleton(t('readingHardware'), 4)}</section>
    <section class="tests" id="tests"></section>`;
  Promise.all([load('laptop'), load('battery').catch(() => null)]).then(([info, bat]) => {
    laptopInfo = { info, bat };
    renderHardware(info, bat);
  }, (err) => { $('#hw').innerHTML = errorBox(err); });
  renderTests();
  $('#pdf').onclick = (e) => withBusy(e.currentTarget, t('makingPdf'), makePdf);
};

function hwRows(info, bat) {
  const ram = info.memory;
  const rows = [
    [t('hwModel'), [info.device.manufacturer, info.device.family && !String(info.device.model).includes(info.device.family) ? info.device.family : '', info.device.model].filter(Boolean).join(' ')],
    [t('hwCpu'), `${info.cpu.name} · ${t('hwCores', { c: num(info.cpu.cores), th: num(info.cpu.threads) })}`],
    [t('hwRam'), `${bytes(ram.installed || ram.total)}${ram.speed ? ` · ${num(ram.speed)} MHz` : ''}${ram.slots ? ` · ${t('hwSlots', { used: num(ram.used), slots: num(ram.slots) })}` : ''}${ram.maxBytes ? ` · ${t('hwRamMax', { max: bytes(ram.maxBytes) })}` : ''}`],
    ...info.gpus.map((g) => [t('hwGpu'), `${g.name}${g.width ? ` · ${g.width}×${g.height}${g.hz ? ` @ ${g.hz} Hz` : ''}` : ''}`]),
    ...info.disks.map((d) => [t('hwDisk'), `${d.name} · ${d.type} ${d.bus} · ${bytes(d.size)} · ${t(d.health === 'Healthy' ? 'healthy' : 'checkIt')}${d.wear != null ? ` · ${t('hwWear', { n: num(d.wear) })}` : ''}${d.powerOnHours != null ? ` · ${t('hwHours', { n: num(d.powerOnHours) })}` : ''}`]),
    [t('hwScreen'), info.display.inches ? `${num(info.display.inches)}″` : '—'],
    [t('hwWindows'), `${info.windows.name} ${info.windows.version} · ${t(info.windows.activated ? 'activated' : 'notActivated')}`],
    [t('hwBios'), `${info.bios.version}${info.bios.date ? ` (${info.bios.date})` : ''}`],
  ];
  if (bat && bat.hasBattery) rows.push([t('hwBattery'), `${t('batHolds', { pct: num(bat.health) })}${bat.cycles ? ` · ${t('batCycles')}: ${num(bat.cycles)}` : ''}`]);
  if (info.device.serial) rows.push([t('hwSerial'), info.device.serial]);
  return rows;
}

function renderHardware(info, bat) {
  $('#hw').innerHTML = `<div class="card-head"><h2>${esc(t('hwTitle'))}</h2>
      ${info.admin || info.disks.every((d) => d.wear != null) ? '' : `<button class="btn ghost small" id="deep">${esc(t('hwDeep'))}</button>`}</div>
    <dl class="kv wide">${hwRows(info, bat).map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>`;
  if ($('#deep')) $('#deep').onclick = (e) => withBusy(e.currentTarget, t('working'), async () => {
    try {
      const deep = await bridge('laptop', {}, { admin: true });
      cache.laptop = Promise.resolve(deep);
      laptopInfo.info = deep;
      renderHardware(deep, bat);
    } catch (err) { toast(failure(err), 'bad'); }
  });
}

const TESTS = ['screen', 'keyboard', 'camera', 'mic', 'speakers'];
function renderTests() {
  $('#tests').innerHTML = TESTS.map((k) => `
    <div class="test-card ${checks[k] === true ? 'pass' : checks[k] === false ? 'fail' : ''}" id="test-${k}">
      <h3>${esc(t('test_' + k))}</h3><p>${esc(t('test_' + k + '_d'))}</p>
      <div class="test-area" id="area-${k}"></div>
      <div class="test-actions">
        <button class="btn ghost small" data-start="${k}">${esc(t('startTest'))}</button>
        <span class="verdict-btns">
          <button class="btn small ok-btn" data-pass="${k}" aria-pressed="${checks[k] === true}">${esc(t('works'))}</button>
          <button class="btn small bad-btn" data-fail="${k}" aria-pressed="${checks[k] === false}">${esc(t('problem'))}</button>
        </span>
      </div>
    </div>`).join('');
  $('#tests').onclick = (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.start) START[b.dataset.start]();
    if (b.dataset.pass) mark(b.dataset.pass, true);
    if (b.dataset.fail) mark(b.dataset.fail, false);
  };
}

function mark(k, ok) {
  checks[k] = ok;
  const card = $(`#test-${k}`);
  card.classList.toggle('pass', ok);
  card.classList.toggle('fail', !ok);
  $(`[data-pass="${k}"]`).setAttribute('aria-pressed', String(ok));
  $(`[data-fail="${k}"]`).setAttribute('aria-pressed', String(!ok));
  if (k === 'camera' || k === 'mic') stopMedia();
}

let media = null; let audioCtx = null; let meterRaf = 0;
function stopMedia() {
  if (media) { media.getTracks().forEach((tr) => tr.stop()); media = null; }
  cancelAnimationFrame(meterRaf);
}

const START = {
  async screen() {
    const colors = ['#000', '#fff', '#f00', '#0f0', '#00f', '#808080'];
    const el = $('#screen-test');
    let i = 0;
    await bridge('host.fullscreen', { on: true }).catch(() => {});
    el.hidden = false;
    el.style.background = colors[0];
    $('#screen-test-hint').textContent = t('screenHint');
    const finish = async () => {
      el.hidden = true;
      el.onclick = null;
      removeEventListener('keydown', key, true);
      await bridge('host.fullscreen', { on: false }).catch(() => {});
    };
    const nextColor = () => {
      i++;
      if (i >= colors.length) { finish(); return; }
      el.style.background = colors[i];
      $('#screen-test-hint').textContent = '';
    };
    const key = (e) => { e.preventDefault(); if (e.key === 'Escape') finish(); else nextColor(); };
    el.onclick = nextColor;
    addEventListener('keydown', key, true);
  },

  keyboard() {
    const area = $('#area-keyboard');
    const rows = [
      ['Escape', 'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12', 'Delete'],
      ['Backquote', 'Digit1', 'Digit2', 'Digit3', 'Digit4', 'Digit5', 'Digit6', 'Digit7', 'Digit8', 'Digit9', 'Digit0', 'Minus', 'Equal', 'Backspace'],
      ['Tab', 'KeyQ', 'KeyW', 'KeyE', 'KeyR', 'KeyT', 'KeyY', 'KeyU', 'KeyI', 'KeyO', 'KeyP', 'BracketLeft', 'BracketRight', 'Backslash'],
      ['CapsLock', 'KeyA', 'KeyS', 'KeyD', 'KeyF', 'KeyG', 'KeyH', 'KeyJ', 'KeyK', 'KeyL', 'Semicolon', 'Quote', 'Enter'],
      ['ShiftLeft', 'IntlBackslash', 'KeyZ', 'KeyX', 'KeyC', 'KeyV', 'KeyB', 'KeyN', 'KeyM', 'Comma', 'Period', 'Slash', 'ShiftRight'],
      ['ControlLeft', 'MetaLeft', 'AltLeft', 'Space', 'AltRight', 'ControlRight', 'ArrowLeft', 'ArrowUp', 'ArrowDown', 'ArrowRight'],
    ];
    const NAMES = {
      Escape: 'Esc', Delete: 'Del', Backquote: '`', Minus: '-', Equal: '=', Backspace: '⌫', Tab: 'Tab', BracketLeft: '[',
      BracketRight: ']', Backslash: '\\', CapsLock: 'Caps', Semicolon: ';', Quote: "'", Enter: 'Enter', ShiftLeft: 'Shift',
      IntlBackslash: '<', Comma: ',', Period: '.', Slash: '/', ShiftRight: 'Shift', ControlLeft: 'Ctrl', MetaLeft: 'Win',
      AltLeft: 'Alt', Space: ' ', AltRight: 'Alt', ControlRight: 'Ctrl', ArrowLeft: '←', ArrowUp: '↑', ArrowDown: '↓', ArrowRight: '→',
    };
    const label = (c) => NAMES[c] ?? c.replace(/^Key|^Digit/, '');
    area.innerHTML = `<p class="fine">${esc(t('keyHint'))}</p><div class="kbd" tabindex="0" id="kbd">${rows.map((r) => `<div class="kbd-row">${r.map((c) =>
      `<span class="key" data-code="${c}" data-w="${['Space'].includes(c) ? 6 : ['Backspace', 'Tab', 'CapsLock', 'Enter', 'ShiftLeft', 'ShiftRight'].includes(c) ? 2 : 1}">${esc(label(c))}</span>`).join('')}</div>`).join('')}</div>
      <p class="fine" id="kbd-count"></p>`;
    const total = $$('.key', area).length;
    const seen = new Set();
    const kbd = $('#kbd');
    kbd.focus();
    kbd.onkeydown = (e) => {
      e.preventDefault();
      const k = $(`.key[data-code="${e.code}"]`, area);
      if (k) {
        k.classList.add('hit');
        if (e.key && e.key.length === 1 && e.key !== ' ') k.textContent = e.key.toUpperCase();
        seen.add(e.code);
      }
      $('#kbd-count').textContent = t('keysPressed', { n: num(seen.size), total: num(total) });
    };
  },

  async camera() {
    const area = $('#area-camera');
    stopMedia();
    try {
      media = await navigator.mediaDevices.getUserMedia({ video: true });
      area.innerHTML = '<video autoplay playsinline muted class="cam"></video>';
      $('video', area).srcObject = media;
    } catch (err) { area.innerHTML = `<p class="warn">${esc(t('noCamera'))}</p>`; }
  },

  async mic() {
    const area = $('#area-mic');
    stopMedia();
    try {
      media = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioCtx = audioCtx || new AudioContext();
      const src = audioCtx.createMediaStreamSource(media);
      const an = audioCtx.createAnalyser();
      an.fftSize = 512;
      src.connect(an);
      area.innerHTML = `<p class="fine">${esc(t('micHint'))}</p><div class="meter"><span id="lvl"></span></div>`;
      const buf = new Uint8Array(an.fftSize);
      const tick = () => {
        an.getByteTimeDomainData(buf);
        let peak = 0;
        for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
        const el = $('#lvl');
        if (!el) return;
        el.style.width = `${Math.min(100, peak / 1.28)}%`;
        meterRaf = requestAnimationFrame(tick);
      };
      tick();
    } catch (err) { area.innerHTML = `<p class="warn">${esc(t('noMic'))}</p>`; }
  },

  speakers() {
    const area = $('#area-speakers');
    area.innerHTML = `<div class="spk"><button class="btn ghost small" data-pan="-1">${esc(t('left'))}</button><button class="btn ghost small" data-pan="1">${esc(t('right'))}</button></div>`;
    area.onclick = (e) => {
      const b = e.target.closest('[data-pan]');
      if (!b) return;
      audioCtx = audioCtx || new AudioContext();
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      const pan = audioCtx.createStereoPanner();
      osc.frequency.value = 523.25;
      pan.pan.value = Number(b.dataset.pan);
      gain.gain.setValueAtTime(0.0001, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.3, audioCtx.currentTime + 0.05);
      gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.9);
      osc.connect(gain).connect(pan).connect(audioCtx.destination);
      osc.start(); osc.stop(audioCtx.currentTime + 0.95);
    };
  },
};

async function makePdf() {
  if (!laptopInfo) { toast(t('waitHardware'), 'bad'); return; }
  const { info, bat } = laptopInfo;
  const verdict = (k) => (checks[k] === true ? `<b class="ok">${esc(t('works'))}</b>` : checks[k] === false ? `<b class="bad">${esc(t('problem'))}</b>` : `<span class="muted">${esc(t('notTested'))}</span>`);
  $('#report').innerHTML = `
    <header><div class="r-brand">${document.querySelector('.brand .mark').outerHTML.replace(/id="hc(\w+)"/g, 'id="hcR$1"').replace(/url\(#hc(\w+)\)/g, 'url(#hcR$1)')}Hib Clean PC</div>
      <div><h1>${esc(t('reportTitle'))}</h1><p>${esc(dateText(new Date().toISOString(), { dateStyle: 'long', timeStyle: 'short' }))}</p></div></header>
    <h2>${esc(t('hwTitle'))}</h2>
    <table>${hwRows(info, bat).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join('')}</table>
    <h2>${esc(t('reportTests'))}</h2>
    <table>${TESTS.map((k) => `<tr><th>${esc(t('test_' + k))}</th><td>${verdict(k)}</td></tr>`).join('')}</table>
    <p class="r-foot">${esc(t('reportFoot'))}</p>`;
  document.body.classList.add('printing');
  try {
    const name = `${t('reportFile')} - ${info.device.model}`.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '').trim();
    const r = await bridge('host.pdf', { name });
    toast(t('pdfSaved'), 'ok');
    const head = $('.head-actions');
    if (head && !$('#reveal')) {
      head.insertAdjacentHTML('afterbegin', `<button class="btn ghost" id="reveal">${esc(t('showPdf'))}</button>`);
      $('#reveal').onclick = () => bridge('host.reveal', { path: r.path });
    }
  } catch (err) { toast(failure(err), 'bad'); }
  finally { document.body.classList.remove('printing'); }
}

// ---------- Start ----------
function setLang(l) {
  lang = I18N[l] ? l : 'en';
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
  $('#lang').value = lang;
  $$('[data-t]').forEach((el) => { el.textContent = t(el.dataset.t); });
  try { localStorage.setItem('lang', lang); } catch (e) { /* storage blocked */ }
}

async function start() {
  let saved = null;
  try { saved = localStorage.getItem('lang'); } catch (e) { /* storage blocked */ }
  let info = { version: '', lang: navigator.language.slice(0, 2) };
  try { info = await bridge('host.info'); } catch (e) { /* preview without the host */ }
  setLang(saved || info.lang);
  $('#version').textContent = info.version ? `v${info.version}` : '';
  $('#lang').onchange = (e) => { setLang(e.target.value); route(); };
  addEventListener('hashchange', route);
  addEventListener('beforeunload', stopMedia);
  route();
}
start();
