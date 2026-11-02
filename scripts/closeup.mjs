// 3D 近景截图：用户指出某件东西不对（三角柜、楼梯转角、玻璃隔断）时，站到旁边拍一张漫游画面看，不用从鸟瞰图里裁。
// 用法：node scripts/closeup.mjs 设计器.html x y 方向 输出.png [--floor 1] [--pitch -0.15] [--time 15] [--gpu]
//   x y：站的位置（mm，户型坐标）；方向：北 / 南 / 东 / 西 / 东北…，或弧度（0 = 朝图上方，顺时针为正）
//   正式 HTML 加 ?debug 打开时暴露 window.shot(x, y, yaw, pitch, t)，这里就是调它
import { launch } from './browser.mjs';
import fs from 'fs';
import path from 'path';
import { pathToFileURL } from 'url';

const args = process.argv.slice(2);
const flag = (k, d) => { const i = args.indexOf(k); if (i < 0) return d; const v = args[i + 1]; args.splice(i, 2); return v; };
const gpu = args.includes('--gpu'); if (gpu) args.splice(args.indexOf('--gpu'), 1);
const floor = +flag('--floor', -1), pitch = +flag('--pitch', -0.12), time = +flag('--time', 15);
const [file, X, Y, dir, out] = args;
if (!out) { console.error('用法：node closeup.mjs 设计器.html x y 方向(北/东/南/西/弧度) 输出.png [--floor i] [--pitch -0.12] [--time 15] [--gpu]'); process.exit(1); }
const DIRS = { 北: 0, 东北: Math.PI / 4, 东: Math.PI / 2, 东南: Math.PI * 3 / 4, 南: Math.PI, 西南: -Math.PI * 3 / 4, 西: -Math.PI / 2, 西北: -Math.PI / 4, N: 0, E: Math.PI / 2, S: Math.PI, W: -Math.PI / 2 };
const yaw = dir in DIRS ? DIRS[dir] : +dir;

const b = await launch({ gpu, viewport: { width: 1400, height: 900 } });
try {
  const p = await b.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(e.message));
  await p.evaluateOnNewDocument(() => { try { for (const k of Object.keys(localStorage)) if (k.startsWith('house-designer')) localStorage.removeItem(k); } catch { } });
  await p.goto(pathToFileURL(path.resolve(file)).href + '?debug', { waitUntil: 'load' });
  await p.waitForFunction(() => window.__designer && window.shot, { timeout: 60000 });
  if (floor >= 0) await p.evaluate(i => window.__designer.goFloor(i), floor);
  // 设计器漫游的 yaw：0 朝东（+x）、往南（+y）转为正；这里对外约定 0 = 北、顺时针为正，换算 = yaw − 90°
  const st = await p.evaluate(async (x, y, yaw, pitch, t) => window.shot(x, y, yaw, pitch, t), +X, +Y, yaw - Math.PI / 2, pitch, time);
  const url = await p.evaluate(() => { window.__designer.S3.renderNow(); return document.querySelector('#c3d').toDataURL('image/png'); });
  fs.mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
  fs.writeFileSync(out, Buffer.from(url.split(',')[1], 'base64'));
  console.log(JSON.stringify({ out: path.resolve(out), state: st, errors: errs.slice(0, 3) }));
} finally { await b.close(); }
