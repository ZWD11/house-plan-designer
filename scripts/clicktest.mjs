// 2D 点选测试：在平面某点（mm）模拟鼠标点一下，看选中的是什么（场地土层、大造型罩住户型、小房间名字盖住门时用）。
// 用法：node scripts/clicktest.mjs 设计器.html x y [x y …] [--floor i]
// 输出每个点：选中的种类（furn / wall / opening / room / …）、id、名字
import { launch } from './browser.mjs';
import path from 'path';
import { pathToFileURL } from 'url';

const args = process.argv.slice(2);
const fi = args.indexOf('--floor'); const floor = fi >= 0 ? +args.splice(fi, 2)[1] : -1;
const [file, ...nums] = args;
if (!file || nums.length < 2) { console.error('用法：node clicktest.mjs 设计器.html x y [x y …] [--floor i]'); process.exit(1); }
const b = await launch({ gpu: false, viewport: { width: 1600, height: 1000 } });
try {
  const p = await b.newPage();
  await p.evaluateOnNewDocument(() => { try { for (const k of Object.keys(localStorage)) if (k.startsWith('house-designer')) localStorage.removeItem(k); } catch { } });
  await p.goto(pathToFileURL(path.resolve(file)).href + '?debug', { waitUntil: 'load' });
  await p.waitForFunction(() => window.__designer, { timeout: 60000 });
  if (floor >= 0) await p.evaluate(i => window.__designer.goFloor(i), floor);
  await p.evaluate(() => { const D = window.__designer; D.setView?.('2d'); D.setTool?.('select'); });
  for (let k = 0; k + 1 < nums.length; k += 2) {
    const x = +nums[k], y = +nums[k + 1];
    // 拉近到这一点再点（大平面缩到全图时目标只有几个像素）
    const [X, Y] = await p.evaluate((x, y) => { const D = window.__designer, v = D.view; v.s = .12; v.ox = v.W / 2 - x * v.s; v.oy = v.H / 2 - y * v.s; D.emit('view'); D.requestDraw(); const r = document.querySelector('#c2d').getBoundingClientRect(); return [r.x + x * v.s + v.ox, r.y + y * v.s + v.oy]; }, x, y);
    await new Promise(r => setTimeout(r, 200));
    await p.mouse.click(X, Y); await new Promise(r => setTimeout(r, 200));
    const sel = await p.evaluate(() => {
      const a = window.__designer.app, s = a.sel; if (!s || !s.kind) return { kind: null };
      const pl = a.plan, f = s.kind === 'furn' && pl.furniture.find(q => q.id === s.id);
      return { kind: s.kind, id: s.id, name: f ? `${f.name}「${f.key}」` : s.kind === 'room' ? (pl.rooms.find(q => q.id === s.id)?.name || '') : '' };
    });
    console.log(JSON.stringify({ at: [x, y], ...sel }));
  }
} finally { await b.close(); }
