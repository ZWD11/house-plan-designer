// 家具库截图：不同屏幕尺寸下左栏家具页 + 拖宽后 + 大图浏览窗口
// 用法：node dev/libshot.mjs 设计器.html 输出目录
import puppeteer from 'puppeteer-core';
import { pathToFileURL } from 'url';
const [, , FILE, OUT] = process.argv;
const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new', args: ['--use-angle=d3d11', '--enable-gpu'] });
const sleep = ms => new Promise(r => setTimeout(r, ms));
for (const [W, H] of [[1600, 960], [1280, 720]]) {
  const page = await b.newPage(); await page.setViewport({ width: W, height: H });
  await page.evaluateOnNewDocument(() => { for (const k of Object.keys(localStorage)) if (k.startsWith('house-designer') || k.startsWith('hd-')) localStorage.removeItem(k); });
  await page.goto(pathToFileURL(FILE).href + '?debug'); await page.waitForFunction(() => window.__designer, { timeout: 60000 }); await sleep(1500);
  await page.click('#leftPanel .tabs [data-tab="furn"]'); await sleep(500);
  const m = await page.evaluate(() => { const p = document.querySelector('#leftPanel'); return { P: p.clientHeight, top: p.querySelector('.lib-top').offsetHeight, list: p.querySelector('.lib-list').clientHeight, cols: getComputedStyle(p.querySelector('.cat')).gridTemplateColumns.split(' ').length }; });
  console.log(W + 'x' + H, JSON.stringify(m));
  await page.screenshot({ path: `${OUT}/lib_${W}.png`, clip: { x: 0, y: 0, width: 520, height: H } });
  const g = await page.$('.lw-grip'), bb = await g.boundingBox();
  await page.mouse.move(bb.x + 2, bb.y + 300); await page.mouse.down(); await page.mouse.move(bb.x + 180, bb.y + 300, { steps: 5 }); await page.mouse.up(); await sleep(500);
  await page.screenshot({ path: `${OUT}/lib_${W}_wide.png`, clip: { x: 0, y: 0, width: 620, height: H } });
  await page.click('#libExpand'); await sleep(800); await page.screenshot({ path: `${OUT}/lib_${W}_modal.png` });
  await page.close();
}
await b.close();
