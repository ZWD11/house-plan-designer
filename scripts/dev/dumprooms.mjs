// 导出设计器里每个房间的矩形拆分和墙的几何（含面齐平偏移），用来逐条核对面积
import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';
import { pathToFileURL } from 'url';
import { launchChrome } from '../chrome.mjs';
const [, , file, out] = process.argv;
const browser = await launchChrome(puppeteer, { headless: true });
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
