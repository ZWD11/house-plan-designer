// 开发用：打开 URL，执行一段 async 函数体（字符串），返回 dataURL 就存成图片，否则打印
import puppeteer from 'puppeteer-core';
import fs from 'fs';
const [, , url, body, out] = process.argv;
const exe = ['C:/Program Files/Google/Chrome/Application/chrome.exe'].find(p => fs.existsSync(p));
const b = await puppeteer.launch({ executablePath: exe, headless: 'new', protocolTimeout: 1200000, defaultViewport: { width: 1700, height: 1000 }, args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows'] });
const p = await b.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message)); p.on('console', m => { if (m.text().startsWith('PT') || m.type() === 'error') console.log(m.text()); });
await p.goto(url, { waitUntil: 'load' }); await p.waitForFunction(() => window.__designer, { timeout: 30000 }); await new Promise(r => setTimeout(r, 1500));
const v = await p.evaluate(`(async () => { ${body} })()`);
if (typeof v === 'string' && v.startsWith('data:')) { fs.writeFileSync(out, Buffer.from(v.split(',')[1], 'base64')); console.log('saved', out); } else console.log(JSON.stringify(v));
if (errs.length) console.log(errs.slice(0, 5).join('\n')); await b.close();
