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

  // 整栋楼：逐层检查（每层一份报告 + 平面截图 + 叠底图），最后出整栋 / 剖切的 3D
  const nFloors = await page.evaluate(() => window.__designer.bld?.floors.length || 1);
  const reports = [], shots = [];
  const shot = async (sel, name) => { const el = await page.$(sel); await el.screenshot({ path: path.join(out, name) }); shots.push(name); };
  if (nFloors > 1) await page.evaluate(() => { const D = window.__designer; D.bld.view2d = 'one'; });
  for (let fi = 0; fi < nFloors; fi++) {
    if (nFloors > 1) { await page.evaluate(i => window.__designer.goFloor(i), fi); await new Promise(r => setTimeout(r, 400)); }
    const report = await page.evaluate((fi) => {
      const D = window.__designer, app = D.app, plan = app.plan, sp = window.__PRESET__?.spec, spec = sp?.floors ? sp.floors[fi] : sp;
      const r1 = v => Math.round(v * 100) / 100;
      const deg = new Map();
      for (const w of plan.walls) if (w.status !== 'removed') for (const k of [w.a, w.b]) deg.set(k, (deg.get(k) || 0) + 1);
      const freeEnds = plan.nodes.filter(n => deg.get(n.id) === 1).map(n => [n.x, n.y]);
      const regions = app.rooms.regions.filter(r => r.area >= 0.6);
      const labeled = new Set(regions.flatMap(r => r.labels.map(l => l.id)));
      const specOps = (spec?.walls || []).reduce((s, w) => s + (w.openings?.length || 0), 0);
      const issues = D.runChecks().issues;
      // spec 里的墙在方案里找不到（被吸附 / 合并吞掉了，比如两面平行墙只差十几毫米）：取墙中点，看有没有方案墙经过
      const NN = new Map(plan.nodes.map(n => [n.id, n]));
      const segD = (p, a, b) => { const dx = b.x - a.x, dy = b.y - a.y, L = dx * dx + dy * dy || 1, t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / L)); return Math.hypot(p.x - a.x - dx * t, p.y - a.y - dy * t); };
      const wallsDropped = (spec?.walls || []).filter(w => { const m = { x: (w.a[0] + w.b[0]) / 2, y: (w.a[1] + w.b[1]) / 2 }; return !plan.walls.some(pw => pw.status !== 'removed' && segD(m, NN.get(pw.a), NN.get(pw.b)) < 30); }).map(w => [w.a, w.b]);
      return {
        name: plan.name, height: plan.height,
        walls: plan.walls.length, openings: plan.openings.length,
        openingsDropped: Math.max(0, specOps - plan.openings.length),
        wallsDropped,
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
    }, fi);
    reports.push(report);
    const suf = nFloors > 1 ? '_' + fi : '';
    await page.evaluate(() => { const D = window.__designer; D.fit2D(); });
    await new Promise(r => setTimeout(r, 300));
    await shot('#pane2d', `plan2d${suf}.png`);
    const hasUl = await page.evaluate(() => {
      const D = window.__designer, u = D.app.underlay; if (!u) return false;
      u.visible = true; u.opacity = .55; D.emit('underlay'); return true;
    });
    if (hasUl) {
      await new Promise(r => setTimeout(r, 400));
      await shot('#pane2d', `overlay${suf}.png`);
      await page.evaluate(() => { const D = window.__designer; D.app.underlay.visible = false; D.emit('underlay'); });
    }
  }
  if (nFloors > 1) {
    await page.evaluate(() => { const D = window.__designer; D.bld.view2d = 'all'; D.goFloor(0); D.fit2D(); });
    await new Promise(r => setTimeout(r, 400));
    await shot('#pane2d', 'plan2d_all.png');
  }
  await page.evaluate(() => window.__designer.setView('3d'));
  await new Promise(r => setTimeout(r, 3500));
  if (nFloors > 1) {
    await page.evaluate(() => window.__designer.setFloorView('all')); await new Promise(r => setTimeout(r, 2500));
    await shot('#pane3d', 'view3d.png');
    for (let fi = 0; fi < nFloors; fi++) {
      await page.evaluate(i => { const D = window.__designer; D.goFloor(i); D.setFloorView('cut'); }, fi); await new Promise(r => setTimeout(r, 2500));
      await shot('#pane3d', `view3d_cut${fi}.png`);
    }
  } else await shot('#pane3d', 'view3d.png');

  const report = nFloors > 1 ? { floors: reports, errors } : { ...reports[0], errors };
  fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 1));
  const brief = nFloors > 1 ? { out, floors: reports.map(r => ({ name: r.name, area: r.totalArea_m2, rooms: r.rooms.map(x => `${x.name} ${x.area_m2}㎡ ${x.size_mm}`), freeWallEnds: r.freeWallEnds, labelsOutsideRooms: r.labelsOutsideRooms, openingsDropped: r.openingsDropped, wallsDropped: r.wallsDropped, issues: r.issues })), errors, screenshots: shots } : { out, ...report, screenshots: shots };
  console.log(JSON.stringify(brief, null, 1));
} finally {
  await browser.close();
}
