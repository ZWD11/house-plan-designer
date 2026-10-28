// 风格款家具 + 自由模型验收：一行一个风格（默认款 + 9 种风格），一列一类风格家具；最后两行是全部自由模型。分块拍 3D，人工逐件看
// 用法：node scripts/qa_styles.mjs <设计器.html> <输出目录>
import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';
import { pathToFileURL } from 'url';

const [, , FILE, OUTARG] = process.argv;
const OUT = path.resolve(OUTARG); fs.rmSync(OUT, { recursive: true, force: true }); fs.mkdirSync(OUT, { recursive: true });
const exe = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome'].find(p => fs.existsSync(p));
const b = await puppeteer.launch({ executablePath: exe, headless: 'new', protocolTimeout: 900000, defaultViewport: { width: 1600, height: 1000 }, args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist', '--disable-background-timer-throttling', '--disable-renderer-backgrounding'] });
const page = await b.newPage(); const errs = [];
page.on('pageerror', e => errs.push(e.message)); page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
await page.evaluateOnNewDocument(() => { try { for (const k of Object.keys(localStorage)) if (k.startsWith('house-designer') || k.startsWith('hd-')) localStorage.removeItem(k); } catch { } });
const url = /^https?:/.test(FILE) ? FILE : pathToFileURL(path.resolve(FILE)).href;
await page.goto(url + (url.includes('?') ? '&' : '?') + 'debug', { waitUntil: 'load' }); await page.waitForFunction(() => window.__designer, { timeout: 60000 });
const sleep = ms => new Promise(r => setTimeout(r, ms));
await sleep(1500);
const KEYS = ['sofa', 'armchair', 'bed18', 'chair', 'diningTable', 'coffeeTable', 'desk', 'wardrobe2', 'tvCabinet', 'nightstand'];
const CELL = 3000;
const info = await page.evaluate((KEYS, CELL) => {
  const D = __designer, p = structuredClone(D.app.plan), id = () => Math.random().toString(36).slice(2, 10);
  const styles = ['', ...Object.keys(D.STYLES)], frees = Object.values(D.CAT).filter(c => c.type === 'free').map(c => c.key);
  const items = [];
  styles.forEach((st, r) => KEYS.forEach((k, c) => { const f = D.makeFurn(k, 600 + (c + .5) * CELL, 600 + (r + .5) * CELL, 0); if (st) D.applyStyle(f, st); items.push({ f, label: `${st ? D.STYLES[st].name : '默认款'} · ${f.name}` }); }));
  frees.forEach((k, i) => { const f = D.makeFurn(k, 600 + (i % KEYS.length + .5) * CELL, 600 + (styles.length + Math.floor(i / KEYS.length) + .5) * CELL, 0); if (f.z && f.z > 2000) f.z = 1200; items.push({ f, label: f.name }); });
  const rows = styles.length + Math.ceil(frees.length / KEYS.length), W = KEYS.length * CELL + 1200, H = rows * CELL + 1200;
  const w0 = p.walls[0], N = [[0, 0], [W, 0], [W, H], [0, H]].map(([x, y]) => ({ id: id(), x, y }));
  p.nodes = N; p.walls = N.map((q, i) => ({ ...w0, id: id(), a: q.id, b: N[(i + 1) % 4].id, t: 240, status: 'existing', bearing: false }));
  p.openings = []; p.elec = []; p.structs = []; p.beams = []; p.voids = []; p.measures = []; p.comments = [];
  p.rooms = [{ id: id(), x: 300, y: 300, name: '风格验收', mat: 'oak' }]; p.height = 3200;
  p.furniture = items.map(i => i.f); delete p.mep; p.name = '风格验收'; D.replacePlan(p);
  return { rows, cols: KEYS.length, list: items.map((it, i) => `${i}: ${it.label}`) };
}, KEYS, CELL);
fs.writeFileSync(path.join(OUT, 'list.txt'), info.list.join('\n'));
await page.evaluate(async () => { await __designer.setView('3d'); }); await sleep(2500);
await page.waitForFunction(() => !__designer.S3.isAnimating() && !__designer.app.transitioning, { timeout: 30000 }); await sleep(500);
await page.evaluate(() => { const s = document.querySelector('#pane3d'); s.querySelectorAll('.overlay').forEach(o => (o.style.display = 'none')); });
let k = 0;
for (let r0 = 0; r0 < info.rows; r0++) for (let c0 = 0; c0 < info.cols; c0 += 5) {
  const cx = (600 + (c0 + 2.5) * CELL) / 1000, cz = (600 + (r0 + .5) * CELL) / 1000;
  await page.evaluate((cx, cz) => { const S = __designer.S3, V = S.sceneRefs().camera.position.constructor; S.setPose({ target: new V(cx, .5, cz), r: 10.5, p: .55, t: 0 }); }, cx, cz);
  await sleep(1000); await page.screenshot({ path: path.join(OUT, `3d_${String(k++).padStart(2, '0')}_行${r0 + 1}_列${c0 + 1}-${c0 + 5}.png`) });
}
console.log(`${info.list.length} 件，页面报错：${errs.length ? errs.slice(0, 3).join(' | ') : '无'}`);
await b.close();
