// 开发用：打开 dev 页面，按 JSON 里的机位逐张漫游截图（直接取 3D 画布）
// node shot3d.mjs URL '[{"x":..,"y":..,"yaw":..,"pitch":..,"t":15,"name":"a"}]' 输出目录 [gpu]
// 带 gpu 参数时按平台选硬件后端，不带则 SwiftShader。CHROME_ANGLE / --angle= 可覆盖。
import puppeteer from 'puppeteer-core';
import fs from 'fs';
import { launchChrome } from '../chrome.mjs';
const [, , url, shotsJson, out, gpu] = process.argv;
const b = await launchChrome(puppeteer, { headless: 'new', viewport: { width: 1700, height: 1000 }, angle: gpu ? undefined : 'swiftshader' });
const p = await b.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message)); p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
await p.goto(url, { waitUntil: 'load' }); await p.waitForFunction(() => window.__designer && window.shot, { timeout: 30000 });
await new Promise(r => setTimeout(r, 1500));
fs.mkdirSync(out, { recursive: true });
for (const s of JSON.parse(shotsJson)) {
  const r = await p.evaluate(async s => { const st = await shot(s.x, s.y, s.yaw, s.pitch ?? -0.05, s.t ?? 15); if (s.night !== undefined) { /* reserved */ } await pump(300); window.__designer.S3.renderNow(); return { st, ms: perf(), url: document.querySelector('#c3d').toDataURL('image/jpeg', .9) }; }, s);
  fs.writeFileSync(`${out}/${s.name}.jpg`, Buffer.from(r.url.split(',')[1], 'base64'));
  console.log(s.name, r.st, r.ms + 'ms');
}
console.log(errs.slice(0, 5).join('\n')); await b.close();
