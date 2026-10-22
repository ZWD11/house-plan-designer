// 开发用：打开 URL（dev server），执行一段表达式，把返回的字节数组 / 字符串写到文件
import puppeteer from 'puppeteer-core';
import fs from 'fs';
const [, , url, expr, out] = process.argv;
const exe = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(p => fs.existsSync(p));
const b = await puppeteer.launch({ executablePath: exe, headless: true, defaultViewport: { width: 1600, height: 1000 }, args: ['--enable-unsafe-swiftshader', '--use-angle=swiftshader'] });
const p = await b.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
await p.goto(url, { waitUntil: 'load' }); await p.waitForFunction(() => window.__designer, { timeout: 20000 }); await new Promise(r => setTimeout(r, 1000));
const v = await p.evaluate(expr);
fs.writeFileSync(out, Array.isArray(v) ? Buffer.from(v) : typeof v === 'string' && v.startsWith('data:') ? Buffer.from(v.split(',')[1], 'base64') : String(v));
console.log('ok', errs.join('\n')); await b.close();
