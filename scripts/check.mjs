/**
 * 打开生成的设计器 HTML（无头 Chrome），检查户型并截图，给模型自查用。
 * 用法: node check.mjs 户型.html [输出目录]
 * 输出: report.json（房间面积与开间进深、外围尺寸链、悬空墙端、问题清单）+ plan2d.png（2D）+ overlay.png（叠原图底图，对照墙位）+ view3d.png（3D 鸟瞰）
 * 第一次用先在本目录 npm install。
 */
import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';
import { pathToFileURL } from 'url';

const [, , file, outArg] = process.argv;
if (!file) { console.error('用法: node check.mjs 户型.html [输出目录]'); process.exit(1); }
const out = path.resolve(outArg || path.join(path.dirname(file), path.basename(file, '.html') + '_check'));
fs.mkdirSync(out, { recursive: true });

const candidates = [
  process.env.CHROME_PATH,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
].filter(Boolean);
const executablePath = candidates.find(p => fs.existsSync(p));
if (!executablePath) { console.error('找不到 Chrome/Edge，设置环境变量 CHROME_PATH'); process.exit(1); }

const browser = await puppeteer.launch({
  executablePath, headless: true, defaultViewport: { width: 1600, height: 1000 },
  args: ['--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--hide-scrollbars'],
});
const errors = [];
try {
  const page = await browser.newPage();
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(pathToFileURL(path.resolve(file)).href + '?debug', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__designer, { timeout: 15000 });
  await new Promise(r => setTimeout(r, 800));

  const report = await page.evaluate(() => {
    const D = window.__designer, app = D.app, plan = app.plan, spec = window.__PRESET__?.spec;
    const r1 = v => Math.round(v * 100) / 100;
    const deg = new Map();
    for (const w of plan.walls) if (w.status !== 'removed') for (const k of [w.a, w.b]) deg.set(k, (deg.get(k) || 0) + 1);
    const freeEnds = plan.nodes.filter(n => deg.get(n.id) === 1).map(n => [n.x, n.y]);
    const regions = app.rooms.regions.filter(r => r.area >= 0.6);
    const labeled = new Set(regions.flatMap(r => r.labels.map(l => l.id)));
    const specOps = (spec?.walls || []).reduce((s, w) => s + (w.openings?.length || 0), 0);
    const issues = D.runChecks().issues;
    return {
      name: plan.name,
      walls: plan.walls.length, openings: plan.openings.length,
      openingsDropped: Math.max(0, specOps - plan.openings.length),
      bounds_mm: [app.geo.bounds.x, app.geo.bounds.y, app.geo.bounds.w, app.geo.bounds.h].map(Math.round),
      totalArea_m2: r1(regions.reduce((s, r) => s + r.area, 0)),
      rooms: regions.map(r => ({ name: r.labels.map(l => l.name).join(' + ') || '（未命名）', area_m2: r1(r.area), size_mm: D.roomSize?.(r) || '异形', interior: [Math.round(r.interior.x), Math.round(r.interior.y)] }))
        .sort((a, b) => b.area_m2 - a.area_m2),
      labelsOutsideRooms: plan.rooms.filter(l => !labeled.has(l.id)).map(l => ({ name: l.name, at: [l.x, l.y] })),
      freeWallEnds: freeEnds,
      // 外围三道尺寸（从里到外：门窗分段 / 墙厚+净距 / 总长），逐个和原图标注对数，差 30mm 以上就回去改墙
      exteriorDims: D.exteriorDims?.(),
      issues: issues.map(i => `[${i.level}] ${i.msg}`),
    };
  });
  report.errors = errors;

  const shot = async (sel, name) => { const el = await page.$(sel); await el.screenshot({ path: path.join(out, name) }); };
  await page.evaluate(() => { const D = window.__designer; D.fit2D(); });
  await new Promise(r => setTimeout(r, 300));
  await shot('#pane2d', 'plan2d.png');
  const hasUl = await page.evaluate(() => {
    const D = window.__designer, u = D.app.underlay; if (!u) return false;
    u.visible = true; u.opacity = .55; D.emit('underlay'); return true;
  });
  if (hasUl) {
    await new Promise(r => setTimeout(r, 400));
    await shot('#pane2d', 'overlay.png');
    await page.evaluate(() => { const D = window.__designer; D.app.underlay.visible = false; D.emit('underlay'); });
  }
  await page.evaluate(() => window.__designer.setView('3d'));
  await new Promise(r => setTimeout(r, 3500));
  await shot('#pane3d', 'view3d.png');

  fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 1));
  console.log(JSON.stringify({ out, ...report, screenshots: ['plan2d.png', hasUl && 'overlay.png', 'view3d.png'].filter(Boolean) }, null, 1));
} finally {
  await browser.close();
}
