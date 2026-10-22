// 开发用：生产版 HTML 上点“渲染出图（光线追踪）”，编译完 40 秒后点“提前结束并保存”，抓下载的文件
import puppeteer from 'puppeteer-core';
import fs from 'fs';
import { launchChrome } from '../chrome.mjs';
const [, , file, out] = process.argv;
const b = await launchChrome(puppeteer, { headless: 'new', protocolTimeout: 1800000, viewport: { width: 1700, height: 1000 } });
const p = await b.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
fs.mkdirSync(out, { recursive: true });
const cdp = await p.createCDPSession(); await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: out.split('/').join(String.fromCharCode(92)) });
await p.goto('file:///' + file + '?debug', { waitUntil: 'load' }); await p.waitForFunction(() => window.__designer, { timeout: 30000 }); await new Promise(r => setTimeout(r, 1500));
const t0 = Date.now();
await p.evaluate(async () => {
  const d = __designer, S = d.S3; d.setView('3d'); await new Promise(r => setTimeout(r, 2500));
  for (let k = 0; k < 40 && !S.fp.active; k++) { if (!S.isAnimating()) S.enterFP({ x: 11648, y: 13000 }); await new Promise(r => setTimeout(r, 250)); }
  S.fp.yaw = 1.9; S.fp.pitch = -.2; await new Promise(r => setTimeout(r, 800));
  document.querySelector('#rendMode').value = 'pt'; document.querySelector('#resIn').value = '1920x1080';
  document.querySelector('#renderBtn').click();
});
let txt = '', compiledAt = 0;
for (let i = 0; i < 600; i++) {
  await new Promise(r => setTimeout(r, 1000));
  txt = await p.evaluate(() => { const b = document.querySelector('#ptProg'); return (b.classList.contains('on') ? 'ON ' : 'OFF ') + b.querySelector('span').textContent; });
  if (i % 20 === 0) console.log(Math.round((Date.now() - t0) / 1000) + 's', txt);
  if (!compiledAt && txt.includes('已采样')) compiledAt = Date.now();
  if (compiledAt && Date.now() - compiledAt > 40000) { await p.evaluate(() => document.querySelector('#ptProg button').click()); console.log('clicked stop at', Math.round((Date.now() - t0) / 1000) + 's', txt); compiledAt = Infinity; }
  if (txt.startsWith('OFF') && i > 5) break;
}
await new Promise(r => setTimeout(r, 3000));
console.log('done', Math.round((Date.now() - t0) / 1000) + 's', 'files:', fs.readdirSync(out).join(','), 'toast:', await p.evaluate(() => document.querySelector('#toast')?.textContent), 'errors:', errs.join(' | '));
await b.close();
