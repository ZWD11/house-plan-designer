// 开发用：同一页面连续出几张光线追踪图（第二张起着色器已编译）
import puppeteer from 'puppeteer-core';
import fs from 'fs';
import { launchChrome } from '../chrome.mjs';
const [, , url, shotsJson, out, w = '1280', h = '720', budget = '60'] = process.argv;
const b = await launchChrome(puppeteer, { headless: 'new', protocolTimeout: 1800000, viewport: { width: 1700, height: 1000 } });
const p = await b.newPage(); p.on('console', m => { if (m.text().startsWith('PT')) console.log(m.text()); });
await p.goto(url, { waitUntil: 'load' }); await p.waitForFunction(() => window.__designer && window.shot, { timeout: 30000 }); await new Promise(r => setTimeout(r, 1500));
fs.mkdirSync(out, { recursive: true });
for (const s of JSON.parse(shotsJson)) {
  const u = await p.evaluate(async (s, w, h, budget) => {
    await shot(s.x, s.y, s.yaw, s.pitch ?? -.05, s.t ?? 15);
    const R = await import('/src/view3d/render.ts'); const t0 = performance.now();
    const bl = await R.renderPathTraced(+w, +h, () => true, 512, +budget);
    console.log('PT ' + s.name + ' ' + ((performance.now() - t0) / 1000).toFixed(1) + 's');
    return await new Promise(r => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(bl); });
  }, s, w, h, budget);
  fs.writeFileSync(`${out}/${s.name}.png`, Buffer.from(u.split(',')[1], 'base64'));
}
await b.close();
