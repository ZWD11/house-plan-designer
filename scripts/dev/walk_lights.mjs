// 漫游开关灯实测（真显卡无头浏览器）：夜里 / 白天进一个房间，面朝最近的开关，
// 截图：关灯 → 按空格（操作准星对着的开关）→ 点位标记；输出开关、灯状态、标记数量和页面报错。
// 用法：node dev/walk_lights.mjs 设计器.html 输出目录 [房间内一点 x y] [时刻 22]
import puppeteer from 'puppeteer-core';
import { pathToFileURL } from 'url';
const [, , FILE, OUT, RX = '13600', RY = '27900', HOUR = '22'] = process.argv;
const room = { x: +RX, y: +RY };
const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new', defaultViewport: { width: 1400, height: 860 },
  args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows'] });
const page = await b.newPage(); const errs = [];
page.on('pageerror', e => errs.push(e.message)); page.on('console', m => { if (m.type() === 'error') errs.push(m.text().slice(0, 160)); });
await page.evaluateOnNewDocument(() => { for (const k of Object.keys(localStorage)) if (k.startsWith('house-designer')) localStorage.removeItem(k); });
await page.goto(pathToFileURL(FILE).href + '?debug'); await page.waitForFunction(() => window.__designer, { timeout: 60000 });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ev = (f, ...a) => page.evaluate(f, ...a);
await ev(() => __designer.setView('3d')); await sleep(800); await page.waitForFunction(() => !__designer.S3.isAnimating(), { timeout: 30000 }); await sleep(1500);
const sw = await ev((room, hour) => {
  const D = __designer, S3 = D.S3, P = D.app.plan;
  S3.lighting.time = hour; S3.setLighting();
  const s = P.elec.filter(e => /^switch|dimmer/.test(e.kind) && e.links && e.links.length).map(s => ({ s, d: Math.hypot(s.x - room.x, s.y - room.y) })).sort((a, b) => a.d - b.d)[0].s;
  S3.enterFP(room); return { id: s.id, x: s.x, y: s.y, kind: s.kind, links: s.links.length };
}, room, +HOUR);
const t0 = Date.now();
await page.waitForFunction(() => __designer.S3.fp.active, { timeout: 90000 }).catch(() => { });
const t1 = Date.now();
const dbg = await ev(() => ({ fp: __designer.S3.fp.active, anim: __designer.S3.isAnimating(), cp: __designer.S3.isColorPlan(), view: __designer.app.view }));
if (!dbg.fp) { console.log('没进漫游', JSON.stringify(dbg), errs.slice(0, 3)); await b.close(); process.exit(1); }
await ev(sw => { const S3 = __designer.S3; S3.setAllLamps(false); S3.fp.yaw = Math.atan2(sw.y - S3.fp.y, sw.x - S3.fp.x); S3.fp.pitch = Math.atan2(1.35 - 1.6, Math.hypot(sw.x - S3.fp.x, sw.y - S3.fp.y) / 1000); }, sw);
await sleep(2500);
const st = () => ev(id => { const D = __designer, s = D.app.plan.elec.find(e => e.id === id); return { fp: D.S3.fp.active, pos: [Math.round(D.S3.fp.x), Math.round(D.S3.fp.y)], lamps: s.links.map(l => D.S3.lampLevel.get(l) || 0), hud: [...document.querySelectorAll('.pt')].map(b => b.className.replace(/^pt /, '')), aim: !!document.querySelector('.pt.aim') }; }, sw.id);
const s0 = await st(); await page.screenshot({ path: OUT + '/1_off.png' });
const pre = await ev(() => ({ active: document.activeElement?.tagName + '#' + document.activeElement?.id + '.' + document.activeElement?.className, modal: !!document.querySelector('.modal'), view: __designer.app.view, fp: __designer.S3.fp.active }));
const probe = await ev(() => { const log = []; const h = e => log.push('win:' + e.code + ':' + e.defaultPrevented); window.addEventListener('keydown', h, true); window.addEventListener('keydown', e => log.push('bubble-end:' + e.defaultPrevented)); window.__klog = log; return 1; });
const aim = await ev(() => { const c = __designer.hudApi.atCrosshair(); return c && { key: c.key, kind: c.e?.kind, links: c.e?.links, fname: c.f?.name }; });
await page.keyboard.press('Space'); await sleep(300);
const klog = await ev(() => window.__klog);
const toastTxt = await ev(() => document.querySelector('#toast')?.textContent); await sleep(2200);
const s1 = await st(); await page.screenshot({ path: OUT + '/2_on.png' });
await page.keyboard.press('KeyT'); await sleep(600); await page.screenshot({ path: OUT + '/3_hud_off.png' }); const s2 = await st(); await page.keyboard.press('KeyT');
console.log(JSON.stringify({ aim, klog, pre, toastTxt, enterMs: t1 - t0, sw, before: s0, afterSpace: s1, hudOff: s2.hud.length, errs: [...new Set(errs)].slice(0, 6) }, null, 1));
await b.close();
