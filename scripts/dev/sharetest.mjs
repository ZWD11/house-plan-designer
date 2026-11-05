// 保存 / 分享文件往返测试：自由造型、吊顶、灯带、“我的造型”、自己导入的底图 → 刷新还在 → 导出分享文件 → 换一个干净的浏览器打开，全部都在
// 用法：node scripts/dev/sharetest.mjs <设计器.html> <输出目录>
import { launch, setDownloadDir } from '../browser.mjs';
import fs from 'fs';
import path from 'path';
const [, , file, outDir] = process.argv;
const OUT = path.resolve(outDir || 'sharetest'); fs.rmSync(OUT, { recursive: true, force: true }); fs.mkdirSync(OUT, { recursive: true });
const url = 'file:///' + path.resolve(file).replace(/\\/g, '/') + '?debug';
const wait = ms => new Promise(r => setTimeout(r, ms));
const b = await launch({ gpu: true, headless: 'new', viewport: { width: 1500, height: 950 } });
const res = {};
const ready = async p => { await p.waitForFunction(() => window.__designer, { timeout: 30000 }); await wait(1500); };
// ---------- 1. 改方案 ----------
const p = await b.newPage();
await p.goto(url); await ready(p);
await p.evaluate(async () => {
  const D = __designer, A = D.app, wait = ms => new Promise(r => setTimeout(r, ms));
  const R = A.rooms.regions.filter(q => q.labels.length && q.area > 8).sort((a, b) => b.area - a.area)[0], c = R.interior;
  R.labels.forEach(l => (l.ceil = { type: 'tray', drop: 280, edgeW: 400, drop2: 150, edgeW2: 300, cove: true, curtain: 200, cornice: true }));
  A.plan.elec.push({ id: 'tstStrip', kind: 'strip', x: Math.round(c.x), y: Math.round(c.y), h: 1450, rot: 0, pts: [{ x: c.x - 800, y: c.y }, { x: c.x + 800, y: c.y }], cct: 2700 });
  A.plan.furniture.push(D.makeFurn('ceilZoneCove', Math.round(c.x), Math.round(c.y + 1500), 0));
  A.plan.furniture.push(D.makeFurn('landLawn', Math.round(c.x + 3000), Math.round(c.y), 0));
  D.commit();
  // 工作台：模板电视柜 → 完成放进方案；再做一个花盆存进“我的造型”
  document.querySelector('#toolSeg [data-tool="free"]').click(); await wait(500);
  __fm.addTemplate('tvCabinet'); document.querySelector('.fm-wrap [data-a="done"]').click(); await wait(800);
  document.querySelector('#toolSeg [data-tool="free"]').click(); await wait(500);
  __fm.addTemplate('planter'); document.querySelector('.fm-wrap [data-a="lib"]').click(); await wait(300); __fm.close(); await wait(300);
  document.querySelector('#saveBtn').click(); await wait(1500);
});
// 自己导入的底图：走真正的“导入户型图”（户型面板的文件框）
const png = path.join(OUT, 'ul.png'); fs.writeFileSync(png, Buffer.from((await p.evaluate(() => { const c = document.createElement('canvas'); c.width = 64; c.height = 48; const x = c.getContext('2d'); x.fillStyle = '#c33'; x.fillRect(0, 0, 64, 48); return c.toDataURL('image/png'); })).split(',')[1], 'base64'));
await p.evaluate(() => document.querySelector('#leftPanel .tabs [data-tab="plan"]').click()); await wait(300);
const fi = await p.$('#ulFile'); await fi.uploadFile(png); await wait(2500);
res.ulDebug = await p.evaluate(() => { const u = __designer.app.underlay; return u ? [u.imgW, u.imgH, u.src.slice(0, 30)] : null; });
const snap = () => p.evaluate(() => { const A = __designer.app, P = A.plan, fm = P.furniture.find(f => f.opt?.shape === 'model'); return {
  model: !!fm && String(fm.opt.model).length > 100, modelName: fm?.name, ceil: P.rooms.find(l => l.ceil?.type === 'tray') ? 'tray' : null,
  coveStrips: P.elec.filter(e => e.auto?.startsWith('cove:')).length, strip: !!P.elec.find(e => e.id === 'tstStrip' && e.cct === 2700), zone: P.furniture.some(f => f.key === 'ceilZoneCove'), lawn: P.furniture.some(f => f.key === 'landLawn'),
  fmLib: JSON.parse(localStorage.getItem('hd-free-models') || '[]').length, underlay: !!A.underlay && A.underlay.imgW === 64 && A.underlay.imgH === 48 }; });
res.edited = await snap();
// ---------- 2. 刷新：自动保存的都还在 ----------
await p.reload(); await ready(p); res.afterReload = await snap();
// ---------- 3. 导出分享文件 ----------
await setDownloadDir(b, p, OUT);
await p.evaluate(() => { document.querySelector('[data-exp="share"]').click(); });
let shareFile = null; for (let k = 0; k < 40 && !shareFile; k++) { await wait(500); shareFile = fs.readdirSync(OUT).find(f => f.endsWith('-分享.html')); }
res.shareFile = shareFile; res.shareKB = shareFile ? Math.round(fs.statSync(path.join(OUT, shareFile)).size / 1024) : 0;
// ---------- 4. 换一个干净的浏览器（空的本机存储）打开分享文件 ----------
if (shareFile) {
  const ctxB = await b.createBrowserContext(), q = await ctxB.newPage(); const errs = []; q.on('pageerror', e => errs.push(e.message));
  await q.goto('file:///' + path.join(OUT, shareFile).replace(/\\/g, '/') + '?debug'); await ready(q); await wait(1000);
  res.inShare = await q.evaluate(async () => {
    const D = __designer, A = D.app, P = A.plan, fm = P.furniture.find(f => f.opt?.shape === 'model');
    D.setView('3d'); const S = D.S3; for (let k = 0; k < 40; k++) { S.frame(performance.now()); await new Promise(r => setTimeout(r, 40)); }
    let meshes = 0; const e = fm && S.sceneRefs().furnMap.get(fm.id); e?.g.traverse(o => { if (o.isMesh) meshes++; });
    return { model: !!fm, modelMeshes3D: meshes, ceil: P.rooms.some(l => l.ceil?.type === 'tray'), coveStrips: P.elec.filter(e => e.auto?.startsWith('cove:')).length, strip: !!P.elec.find(e => e.id === 'tstStrip'),
      zone: P.furniture.some(f => f.key === 'ceilZoneCove'), lawn: P.furniture.some(f => f.key === 'landLawn'), fmLib: JSON.parse(localStorage.getItem('hd-free-models') || '[]').length,
      libHasMine: !!document.querySelector('#leftPanel') && Object.keys(D.CAT).some(k => k.startsWith('fm_')), underlay: !!A.underlay && A.underlay.imgW === 64, banner: getComputedStyle(document.getElementById('shareBanner')).display !== 'none' };
  });
  await q.screenshot({ path: path.join(OUT, 'share-opened.png') });
  res.inShareErrors = errs;
  // 分享文件里再存一次、刷新，还在
  await q.evaluate(() => document.querySelector('#saveBtn').click()); await wait(1200); await q.reload(); await ready(q);
  res.shareAfterReload = await q.evaluate(() => { const P = __designer.app.plan; return { model: P.furniture.some(f => f.opt?.shape === 'model'), strip: !!P.elec.find(e => e.id === 'tstStrip') }; });
}
console.log(JSON.stringify(res, null, 1));
await b.close();
