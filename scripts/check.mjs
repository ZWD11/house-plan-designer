/**
 * 打开生成的设计器 HTML（无头 Chrome），检查户型并截图，给模型自查用。
 * 用法: node check.mjs 户型.html [输出目录]
 * 输出: report.json（房间面积与开间进深、外围尺寸链、悬空墙端、问题清单）+ plan2d.png（2D）+ overlay.png（叠原图底图，对照墙位）+ view3d.png（3D 鸟瞰）
 * 第一次用先在本目录 npm install。
 */
import { launch } from './browser.mjs';
import fs from 'fs';
import path from 'path';
import { pathToFileURL } from 'url';

const [, , file, outArg] = process.argv;
if (!file) { console.error('用法: node check.mjs 户型.html [输出目录]'); process.exit(1); }
const out = path.resolve(outArg || path.join(path.dirname(file), path.basename(file, '.html') + '_check'));
fs.mkdirSync(out, { recursive: true });

const browser = await launch({ gpu: false, headless: true, protocolTimeout: 180000, viewport: { width: 1600, height: 1000 } });
const errors = [];
try {
  const page = await browser.newPage();
  page.setDefaultTimeout(180000);
  console.log('browser ready');
  page.setDefaultNavigationTimeout(180000);
  page.on('pageerror', e => { errors.push(e.message); console.log('pageerror', e.message); });
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(pathToFileURL(path.resolve(file)).href + '?debug', { waitUntil: 'load' });
  console.log('page loaded');
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
      // 方案里有、但没画到任何墙上的门窗（墙被吸附成斜的 / 太短，洞口放不下时会悄悄不画）
      const drawn = new Set([...app.geo.active].flatMap(g => g.ops.map(q => q.o.id)));
      const openingsHidden = plan.openings.filter(o => !drawn.has(o.id)).map(o => ({ type: o.type, wall: o.wall, name: o.name || '' }));
      // spec 里横平竖直的墙，在方案里被端点吸附成了斜墙（两条墙线差十几毫米时常见）：放到同一条线上
      const wallsSkewed = plan.walls.filter(w => { const a = NN.get(w.a), b = NN.get(w.b), dx = Math.abs(b.x - a.x), dy = Math.abs(b.y - a.y); return w.status !== 'removed' && Math.min(dx, dy) > 1 && Math.min(dx, dy) < 60 && Math.max(dx, dy) > 300; })
        .map(w => [[NN.get(w.a).x, NN.get(w.a).y], [NN.get(w.b).x, NN.get(w.b).y]]);
      return {
        name: plan.name, height: plan.height,
        walls: plan.walls.length, openings: plan.openings.length,
        openingsDropped: Math.max(0, specOps - plan.openings.length) + openingsHidden.length,
        openingsHidden, wallsSkewed,
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
        issuesDetail: issues.map(i => ({ level: i.level, msg: i.msg, ...(i.data || {}) })),
        ...dimCheck(spec),
      };
      /** 尺寸链对账：spec.dims 每道尺寸链的每个刻度，在模型里找最近的墙中线 / 墙面 / 门窗洞口边 / 墙端，差 > tol（默认 30）报出来；
       *  spec.expectDims 按外围三道尺寸（exteriorDims）逐段比对。图纸自己前后矛盾的刻度单独列 dimConflicts。 */
      function dimCheck(spec) {
        const out = { dimChains: [], dimIssues: [], dimConflicts: [] };
        if (!spec) return out;
        const G = [...app.geo.active];
        const isH = g => Math.abs(g.u.y) < .01, isV = g => Math.abs(g.u.x) < .01;
        const P = (g, s) => ({ x: g.a.x + g.u.x * s, y: g.a.y + g.u.y * s });
        // 沿 ax 方向量的刻度（ax = 'x'：水平尺寸链，量 x 坐标），扫描线 c（另一坐标）
        const feats = (ax, c) => {
          const f = [], oth = ax === 'x' ? 'y' : 'x', perp = ax === 'x' ? isV : isH, para = ax === 'x' ? isH : isV;
          for (const g of G) {
            const lo = Math.min(g.a[oth], g.b[oth]) - g.ht - 1, hi = Math.max(g.a[oth], g.b[oth]) + g.ht + 1;
            if (perp(g) && c >= lo && c <= hi) { const m = g.a[ax]; f.push([m, '墙中线'], [m - g.ht, '墙面'], [m + g.ht, '墙面']); }
            if (para(g) && Math.abs(g.a[oth] - c) <= g.ht + 1) {
              f.push([P(g, -g.extA)[ax], '墙端'], [P(g, g.len + g.extB)[ax], '墙端']);
              for (const q of g.ops) f.push([P(g, q.s0)[ax], q.o.type + '边'], [P(g, q.s1)[ax], q.o.type + '边']);
            }
          }
          return f;
        };
        const ticksOf = d => { const t = [d.from || 0]; for (const v of d.segs) t.push(t[t.length - 1] + v); return t; };
        for (const d of spec.dims || []) {
          const m = /^\s*([xy])\s*=\s*(-?[\d.]+)/.exec(d.line || ''); if (!m) { out.dimIssues.push(`尺寸链 ${d.name || ''}：line 要写成 'y=11640'（水平尺寸链，量 x）或 'x=13800'`); continue; }
          const ax = m[1] === 'y' ? 'x' : 'y', scans = d.at || [+m[2]], tol = d.tol ?? 30;
          // ref：这道链量的是什么。center = 轴线 / 墙中线（轴线尺寸一定写，不然墙面会顶替中线，墙挪了 100 多也查不出）；
          // face = 墙面、洞口边、墙端（门窗分段、净距）；不写 = 都算
          const REF = { center: k => k === '墙中线', face: k => k !== '墙中线' };
          const F = scans.flatMap(c => feats(ax, c)).filter(q => !REF[d.ref] || REF[d.ref](q[1]));
          const ticks = ticksOf(d).map((tk, i) => {
            if (!F.length) return { i, mm: tk, near: null, diff: null };
            const [v, k] = F.reduce((b, q) => Math.abs(q[0] - tk) < Math.abs(b[0] - tk) ? q : b);
            return { i, mm: tk, near: Math.round(v * 2) / 2, kind: k, diff: Math.round(v - tk) };
          });
          const bad = ticks.filter(t => t.diff === null || Math.abs(t.diff) > tol);
          out.dimChains.push({ name: d.name || d.line, line: d.line, ticks, bad: bad.length });
          for (const t of bad) out.dimIssues.push(`尺寸链「${d.name || d.line}」第 ${t.i} 个刻度 ${ax}=${t.mm}：` + (t.diff === null ? '扫描线上没有墙' : `模型最近的是 ${t.kind} ${t.near}，差 ${t.diff}mm`) +
            (t.i > 0 ? `（这一段标注 ${d.segs[t.i - 1]}）` : ''));
        }
        // 图纸自相矛盾：同一条线上两道尺寸链量到差 1~60mm 的两个刻度（如 C1518 窗宽 1500 vs 尺寸链 1600）
        const L = spec.dims || [];
        for (let i = 0; i < L.length; i++) for (let j = i + 1; j < L.length; j++) {
          if ((L[i].line || '')[0] !== (L[j].line || '')[0]) continue;
          const A = ticksOf(L[i]), B = ticksOf(L[j]);
          for (const p of A) for (const q of B) if (Math.abs(p - q) >= 1 && Math.abs(p - q) <= 60)
            out.dimConflicts.push(`「${L[i].name || L[i].line}」刻度 ${p} 和「${L[j].name || L[j].line}」刻度 ${q} 差 ${Math.abs(p - q)}mm：图纸前后不一致，交付时说明按哪个为准`);
        }
        // 外围三道：expectDims = { left: [240, 3260, ...], top: [...] }，和 exteriorDims 的 axis（墙厚 + 净距）/ openings（门窗分段）比
        const ext = spec.expectDims ? D.exteriorDims?.() : null;
        for (const [side, want] of Object.entries(spec.expectDims || {})) {
          const got = ext?.[side]; if (!got) { out.dimIssues.push(`expectDims.${side}：设计器没算出这一侧的外围尺寸`); continue; }
          const cand = [['墙厚 + 净距', got.axis], ['门窗分段', got.openings]];
          const score = arr => arr.length === want.length ? want.reduce((s, v, i) => s + Math.abs(v - arr[i]), 0) : Infinity;
          const [nm, arr] = cand.reduce((b, c) => score(c[1]) < score(b[1]) ? c : b);
          if (score(arr) === Infinity) { out.dimIssues.push(`expectDims.${side}：图上 ${want.length} 段 [${want.join(', ')}]，设计器墙厚 + 净距 ${got.axis.length} 段 [${got.axis.join(', ')}]、门窗分段 ${got.openings.length} 段——段数对不上，多半漏墙或多墙`); continue; }
          want.forEach((v, i) => { if (Math.abs(v - arr[i]) >= 30) out.dimIssues.push(`expectDims.${side} 第 ${i + 1} 段（${nm}）：图上 ${v}，设计器 ${arr[i]}，差 ${arr[i] - v}mm`); });
        }
        return out;
      }
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
  const brief = nFloors > 1 ? { out, floors: reports.map(r => ({ name: r.name, area: r.totalArea_m2, rooms: r.rooms.map(x => `${x.name} ${x.area_m2}㎡ ${x.size_mm}`), freeWallEnds: r.freeWallEnds, labelsOutsideRooms: r.labelsOutsideRooms, openingsDropped: r.openingsDropped, openingsHidden: r.openingsHidden, wallsSkewed: r.wallsSkewed, wallsDropped: r.wallsDropped, issues: r.issues, dimIssues: r.dimIssues, dimConflicts: r.dimConflicts })), errors, screenshots: shots } : { out, ...report, issuesDetail: undefined, dimChains: undefined, screenshots: shots };
  console.log(JSON.stringify(brief, null, 1));
} finally {
  await browser.close();
}
