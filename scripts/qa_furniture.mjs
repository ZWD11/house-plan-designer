// 家具库逐件验收：在一个大空房间里把家具库所有家具排成网格（每件下面写名字），分块拍 3D 和 2D，人工逐件看模型对不对
// 用法：node scripts/qa_furniture.mjs <设计器.html> <输出目录>
import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';
import { pathToFileURL } from 'url';
import { launchChrome } from './chrome.mjs';

const [, , FILE, OUTARG] = process.argv;
const OUT = path.resolve(OUTARG); fs.rmSync(OUT, { recursive: true, force: true }); fs.mkdirSync(OUT, { recursive: true });
const b = await launchChrome(puppeteer, { headless: 'new', protocolTimeout: 900000, viewport: { width: 1600, height: 1000 } });
const page = await b.newPage(); const errs = [];
page.on('pageerror', e => errs.push(e.message)); page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
await page.evaluateOnNewDocument(() => { try { for (const k of Object.keys(localStorage)) if (k.startsWith('house-designer') || k.startsWith('hd-')) localStorage.removeItem(k); } catch { } });
await page.goto(pathToFileURL(path.resolve(FILE)).href + '?debug', { waitUntil: 'load' }); await page.waitForFunction(() => window.__designer, { timeout: 60000 });
const sleep = ms => new Promise(r => setTimeout(r, ms));
await sleep(1500);
// 家具库全部加进来，记下名字
await page.evaluate(() => document.querySelector('#leftPanel .tabs [data-tab="furn"]').click()); await sleep(400);
const COLS = 12, CELL = 2800;
const n = await page.evaluate(async () => { for (const it of document.querySelectorAll('#leftPanel .cat > *')) it.click(); await new Promise(r => setTimeout(r, 300)); return document.querySelectorAll('#leftPanel .cat > *').length; });
const info = await page.evaluate((COLS, CELL) => {
  const D = __designer, p = structuredClone(D.app.plan), items = p.furniture.slice(-document.querySelectorAll('#leftPanel .cat > *').length);
  const rows = Math.ceil(items.length / COLS), W = COLS * CELL + 1200, H = rows * CELL + 1200;
  const w0 = p.walls[0], id = () => Math.random().toString(36).slice(2, 10);
  const N = [[0, 0], [W, 0], [W, H], [0, H]].map(([x, y]) => ({ id: id(), x, y }));
  p.nodes = N; p.walls = N.map((q, i) => ({ ...w0, id: id(), a: q.id, b: N[(i + 1) % 4].id, t: 240, status: 'existing', bearing: false }));
  p.openings = []; p.elec = []; p.structs = []; p.beams = []; p.voids = []; p.measures = []; p.comments = [];
  p.rooms = [{ id: id(), x: 300, y: 300, name: '家具库', mat: 'oak' }];
  p.furniture = items.map((f, i) => ({ ...f, x: 600 + (i % COLS + .5) * CELL, y: 600 + (Math.floor(i / COLS) + .5) * CELL, rot: 0 }));
  delete p.mep; p.name = '家具库验收'; D.replacePlan(p);
  return { rows, W, H, list: p.furniture.map((f, i) => ({ i, type: f.type, name: f.name, w: f.w, d: f.d, h: f.h })) };
}, COLS, CELL);
fs.writeFileSync(path.join(OUT, 'list.json'), JSON.stringify(info.list, null, 1));
await page.evaluate(() => { const D = __designer; D.fit2D(); D.requestDraw(); }); await sleep(800);
await page.screenshot({ path: path.join(OUT, '2d_all.png') });
await page.evaluate(async () => { await __designer.setView('3d'); }); await sleep(2000);
await page.waitForFunction(() => !__designer.S3.isAnimating() && !__designer.app.transitioning, { timeout: 30000 }); await sleep(500);
await page.evaluate(() => { const s = document.querySelector('#pane3d'); s.querySelectorAll('.overlay').forEach(o => (o.style.display = 'none')); });
// 3D：每次拍 3 行 × 4 列，斜 45° 俯视
let k = 0;
for (let r0 = 0; r0 < info.rows; r0 += 2) for (let c0 = 0; c0 < COLS; c0 += 4) {
  const cx = (600 + (c0 + 2) * CELL) / 1000, cz = (600 + (r0 + 1) * CELL) / 1000;
  await page.evaluate((cx, cz) => { const S = __designer.S3, V = S.sceneRefs().camera.position.constructor; S.setPose({ target: new V(cx, .5, cz), r: 9.5, p: .78, t: 0 }); }, cx, cz);
  await sleep(900); await page.screenshot({ path: path.join(OUT, `3d_${String(k++).padStart(2, '0')}_行${r0 + 1}-${r0 + 2}_列${c0 + 1}-${c0 + 4}.png`) });
}
// 名字表：哪一格是什么
const lines = info.list.map(f => `第 ${Math.floor(f.i / COLS) + 1} 行第 ${f.i % COLS + 1} 列：${f.name}（${f.type}，${f.w}×${f.d}×${f.h}）`);
fs.writeFileSync(path.join(OUT, 'list.txt'), lines.join('\n'));
const bad = await page.evaluate(() => { const fm = __designer.S3.sceneRefs().furnMap, out = []; for (const f of __designer.app.plan.furniture) { const e = fm.get(f.id); let m = 0; e?.g.traverse(o => { if (o.isMesh) m++; }); if (!m) out.push(f.name); } return out; });
console.log(`${n} 件家具，${info.rows} 行；没有 3D 模型的：${bad.join('、') || '无'}；页面报错：${errs.length ? errs.slice(0, 3).join(' | ') : '无'}`);
await b.close();
