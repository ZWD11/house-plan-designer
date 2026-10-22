/**
 * 漫游走查：按一条路线在设计器 3D 漫游里“真的走一遍”，输出每段走完后的位置、脚高、当前楼层，
 * 用来验证楼梯能从起步走到上层、扶手挡得住、门能穿过去、高段梯段底下能走人。
 *
 *   node walktest.mjs 设计器.html 路线.json
 *
 * 路线.json：数组，按顺序执行
 *   {"start": [楼层序号, x, y, 脚高(可省, 默认 0)], "label": "说明"}   传送到某层某点（mm）
 *   {"move": [dx, dy, 步数], "label": "说明"}                        每步挪 (dx, dy) mm，走 n 步（每步 ≤ 60 走得最像真人）
 * 输出每一项之后的 [x, y, 脚高(相对当前层), 当前楼层]。判断：
 *   - 爬楼梯：脚高应逐段升高，走过半层后楼层号 +1、脚高变成负值，到顶 = 0
 *   - 往扶手 / 墙外走：坐标停住不动 = 挡住了
 *   - 进门：坐标穿过墙线 = 门能过
 */
import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';
import { pathToFileURL } from 'url';
import { launchChrome } from './chrome.mjs';

const [html, routeFile] = process.argv.slice(2);
if (!html || !routeFile) { console.error('用法：node walktest.mjs 设计器.html 路线.json'); process.exit(1); }
const route = JSON.parse(fs.readFileSync(routeFile, 'utf8'));
const browser = await launchChrome(puppeteer, { headless: true });
try {
  const page = await browser.newPage();
  page.on('pageerror', e => console.log('页面错误', e.message));
  await page.goto(pathToFileURL(path.resolve(html)).href + '?debug', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__designer, { timeout: 15000 });
  await new Promise(r => setTimeout(r, 800));
  const out = await page.evaluate(async route => {
    const D = window.__designer, S = D.S3, res = [];
    D.setView('3d'); await new Promise(r => setTimeout(r, 1500));
    let entered = false;
    const pos = () => [Math.round(S.fp.x), Math.round(S.fp.y), Math.round(S.fp.z), D.bld?.cur ?? 0];
    for (const it of route) {
      if (it.start) {
        const [fl, x, y, z = 0] = it.start;
        if (D.goFloor && (D.bld?.cur ?? 0) !== fl) { D.goFloor(fl); await new Promise(r => setTimeout(r, 600)); }
        if (!entered) { S.enterFP({ x, y }); await new Promise(r => setTimeout(r, 2500)); entered = true; }
        S.fp.x = x; S.fp.y = y; S.fp.z = z; S.fp.ez = z;
      } else if (it.move) {
        const [dx, dy, n] = it.move;
        for (let i = 0; i < n; i++) S.moveFP(dx, dy);
      }
      res.push({ label: it.label || '', at: pos() });
    }
    return res;
  }, route);
  for (const r of out) console.log(`${r.at.join(', ').padEnd(26)} ${r.label}`);
} finally { await browser.close(); }
