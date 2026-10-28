// 帧率探针：鸟瞰白天 / 鸟瞰夜里（灯全开）/ 进漫游 各量 3 秒帧数，以及进漫游花多久
// 用法：node dev/fps.mjs 设计器.html [房间内一点 x y]
import puppeteer from 'puppeteer-core';
import { pathToFileURL } from 'url';
const [, , FILE, RX = '13600', RY = '27900'] = process.argv;
const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new', defaultViewport: { width: 1400, height: 860 },
  args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows'] });
const page = await b.newPage(); const errs = [];
page.on('pageerror', e => errs.push(e.message)); page.on('console', m => { if (m.type() === 'error') errs.push(m.text().slice(0, 120)); });
await page.evaluateOnNewDocument(() => { for (const k of Object.keys(localStorage)) if (k.startsWith('house-designer')) localStorage.removeItem(k); });
await page.goto(pathToFileURL(FILE).href + '?debug' + (process.env.QS || '')); await page.waitForFunction(() => window.__designer, { timeout: 60000 });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ev = (f, ...a) => page.evaluate(f, ...a);
const fps = () => ev(() => new Promise(res => { let n = 0; const t0 = performance.now(); const f = () => { n++; if (performance.now() - t0 < 3000) requestAnimationFrame(f); else res(Math.round(n / 3 * 10) / 10); }; requestAnimationFrame(f); }));
await ev(() => __designer.setView('3d')); await sleep(800); await page.waitForFunction(() => !__designer.S3.isAnimating(), { timeout: 60000 }); await sleep(1500);
const out = {};
out.birdDay = await fps();
await ev(() => { __designer.S3.lighting.time = 22; __designer.S3.setLighting(); }); await sleep(2000);
out.birdNight = await fps();
const t0 = Date.now(); await ev(r => __designer.S3.enterFP(r), { x: +RX, y: +RY });
await page.waitForFunction(() => __designer.S3.fp.active, { timeout: 120000 }); out.enterMs = Date.now() - t0;
await sleep(1500); out.walkNight = await fps();
await ev(() => { __designer.S3.lighting.time = 14; __designer.S3.setLighting(); }); await sleep(2000);
out.walkDay = await fps();
out.errs = [...new Set(errs)].slice(0, 4);
console.log(JSON.stringify(out));
await b.close();
