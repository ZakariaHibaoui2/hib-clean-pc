// Unit tests for the health score: takes healthOf() out of ui/app.js and checks
// its exact result for known situations. Prints "PASS name" / "FAIL name" lines.
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('../ui/app.js', import.meta.url), 'utf8');
const start = src.indexOf('function healthOf(d) {');
const end = start + src.slice(start).search(/\r?\n\}\r?\n/) + 3; // app.js may have Windows line endings
const healthOf = new Function('bytes', 'num', `${src.slice(start, end)}; return healthOf;`)((b) => `${b}B`, (n) => String(n));

const GB = 2 ** 30;
const base = () => ({
  system: { drive: { total: 1000 * GB, free: 500 * GB }, memory: { total: 16 * GB, free: 8 * GB } },
  junk: [{ id: 'user-temp', readable: true, bytes: 0 }],
  startup: [],
  tweaks: Array.from({ length: 12 }, (_, i) => ({ id: `t${i}`, applied: true })),
  apps: [],
  battery: { hasBattery: true, health: 95 },
  updates: { available: true, apps: [] },
  dns: { blocking: true },
});
let failed = 0;
const expect = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ` (got ${JSON.stringify(got)}, want ${JSON.stringify(want)})`}`);
};

// A PC with nothing to fix scores 100 with no suggestions.
let r = healthOf(base());
expect('perfect PC scores 100', r.score, 100);
expect('perfect PC has no fixes', r.issues.length, 0);

// Every problem at its worst: 100 - (20+12+12+10+6+12+10+5) = 13.
const worst = base();
worst.system.drive.free = 50 * GB;
worst.junk = [{ id: 'user-temp', readable: true, bytes: 6 * GB }];
worst.startup = Array.from({ length: 10 }, () => ({ enabled: true, publisher: 'Someone' }));
worst.tweaks = worst.tweaks.map((x) => ({ ...x, applied: false }));
worst.apps = Array.from({ length: 6 }, () => ({ kind: 'junk' }));
worst.battery.health = 50;
worst.updates.apps = Array.from({ length: 9 }, () => ({}));
worst.dns.blocking = false;
r = healthOf(worst);
expect('worst case scores 13', r.score, 13);
expect('worst case lists 8 fixes, biggest first', r.issues.map((i) => i.weight), [20, 12, 12, 12, 10, 10, 6, 5]);

// The milder level of each problem: 100 - (10+6+6+5+3+6+5+5) = 54.
const mid = base();
mid.system.drive.free = 150 * GB;
mid.junk = [{ id: 'user-temp', readable: true, bytes: 2 * GB }];
mid.startup = Array.from({ length: 5 }, () => ({ enabled: true, publisher: 'Someone' }));
mid.tweaks[0].applied = false;
mid.apps = [{ kind: 'junk' }];
mid.battery.health = 75;
mid.updates.apps = [{}, {}];
mid.dns.blocking = false;
r = healthOf(mid);
expect('milder problems score 54', r.score, 54);

// Edge cases.
const ms = base();
ms.startup = Array.from({ length: 12 }, () => ({ enabled: true, publisher: 'Microsoft Corporation' }));
expect('Microsoft startup apps are not counted', healthOf(ms).score, 100);
const off = base();
off.startup = Array.from({ length: 12 }, () => ({ enabled: false, publisher: 'Someone' }));
expect('turned-off startup apps are not counted', healthOf(off).score, 100);
const noBat = base();
noBat.battery = { hasBattery: false };
expect('a PC without a battery is not marked down', healthOf(noBat).score, 100);
const unreadable = base();
unreadable.junk = [{ id: 'win-temp', readable: false, bytes: 9 * GB }, { id: 'windows-old', readable: true, bytes: 9 * GB }];
expect('junk that needs permission or Windows.old is not counted', healthOf(unreadable).score, 100);
const optional = base();
optional.apps = Array.from({ length: 8 }, () => ({ kind: 'optional' }));
expect('optional apps are not counted as junk', healthOf(optional).score, 100);
const nowinget = base();
nowinget.updates = { available: false, apps: [] };
expect('no winget is not marked down', healthOf(nowinget).score, 100);
const missing = {};
expect('missing scans give 100, not an error', healthOf(missing).score, 100);
const edge = base();
edge.system.drive.free = 100 * GB;
edge.junk = [{ id: 'user-temp', readable: true, bytes: GB }];
expect('exactly 10% free costs 10 points; exactly 1 GB of junk costs none', healthOf(edge).score, 90);

process.exit(failed ? 1 : 0);
