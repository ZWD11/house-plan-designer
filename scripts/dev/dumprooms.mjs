// 导出设计器里每个房间的矩形拆分和墙的几何（含面齐平偏移），用来逐条核对面积
import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';
import { pathToFileURL } from 'url';
const [, , file, out] = process.argv;
const exe = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(p => fs.existsSync(p));
const browser = await puppeteer.launch({ executablePath: exe, headless: true, args: ['--enable-unsafe-swiftshader', '--use-angle=swiftshader'] });
const page = await browser.newPage();
await page.goto(pathToFileURL(path.resolve(file)).href + '?debug', { waitUntil: 'load' });
await page.waitForFunction(() => window.__designer, { timeout: 15000 });
await new Promise(r => setTimeout(r, 800));
const data = await page.evaluate(() => {
  const app = window.__designer.app;
  const rooms = app.rooms.regions.filter(r => r.area >= .6).map(r => ({ name: r.labels.map(l => l.name).join('+'), area: r.area, bb: r.bb, rects: r.rects }));
  const geo = app.geo || window.__designer.geo;
  const walls = (geo?.active || []).map(g => ({ a: g.a, b: g.b, ht: g.ht, off: g.off, t: g.w.t, align: g.w.align }));
  return { rooms, walls, keys: Object.keys(app) };
});
fs.writeFileSync(out, JSON.stringify(data, null, 1));
await browser.close();
console.log('ok', data.rooms.length, data.walls.length, data.keys.join(','));
