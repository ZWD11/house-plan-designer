// 开发用：鸟瞰取景截图（相机位置 / 目标）+ 连续几帧的像素差（看闪烁）
import puppeteer from 'puppeteer-core';
import fs from 'fs';
const [, , url, posesJson, out] = process.argv;
const exe = ['C:/Program Files/Google/Chrome/Application/chrome.exe'].find(p => fs.existsSync(p));
const b = await puppeteer.launch({ executablePath: exe, headless: 'new', protocolTimeout: 600000, defaultViewport: { width: 1700, height: 1000 }, args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist', '--disable-background-timer-throttling', '--disable-renderer-backgrounding'] });
const p = await b.newPage();
await p.goto(url, { waitUntil: 'load' }); await p.waitForFunction(() => window.__designer && window.pump, { timeout: 30000 }); await new Promise(r => setTimeout(r, 1500));
fs.mkdirSync(out, { recursive: true });
for (const s of JSON.parse(posesJson)) {
  const r = await p.evaluate(async s => {
    const d = __designer, S = d.S3; if (d.app.view !== '3d') { d.setView('3d'); await pump(2500); }
    const { camera, controls } = S.three(); controls.target.set(s.tx, s.ty ?? 0, s.tz); camera.position.set(s.x, s.y, s.z); camera.lookAt(controls.target); controls.update();
    if (s.noao !== undefined) { const fx = S.realFxDebug && S.realFxDebug(); if (fx) fx.ao.enabled = !s.noao; }
    await pump(600);
    // 轻微转动相机看闪烁：前后两帧只差 0.02°，像素差大的地方就是在闪
    const c = document.querySelector('#c3d'), grab = () => { S.renderNow(); const t = document.createElement('canvas'); t.width = c.width; t.height = c.height; t.getContext('2d').drawImage(c, 0, 0); return t.getContext('2d').getImageData(0, 0, c.width, c.height).data; };
    const a = grab(); camera.position.x += .002; controls.update(); const bb = grab(); camera.position.x -= .002; controls.update();
    let diff = 0; for (let i = 0; i < a.length; i += 4) if (Math.abs(a[i] - bb[i]) + Math.abs(a[i + 1] - bb[i + 1]) > 60) diff++;
    S.renderNow(); return { diff, url: c.toDataURL('image/jpeg', .92) };
  }, s);
  fs.writeFileSync(`${out}/${s.name}.jpg`, Buffer.from(r.url.split(',')[1], 'base64')); console.log(s.name, 'flickerPixels', r.diff);
}
await b.close();
