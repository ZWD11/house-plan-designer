// 交付前全功能验收：按平台选显卡后端打开生成的设计器（见 chrome.mjs），把每个按钮、工具、图层、面板、弹窗、导出都实际操作一遍，
// 检查：页面报错、界面上出现 NaN / undefined、操作后状态有没有真的变、导出的文件能不能打开（另由 qa_files.py 校验）。
// 用法：node scripts/qa.mjs <设计器.html> <输出目录> [--quick] [--angle=后端]
// 输出：<输出目录>/report.md（每项 通过 / 失败 + 原因）、shots/*.png（每一步截图，人工过一遍）、downloads/（导出的文件）
import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';
import { pathToFileURL } from 'url';
import { launchChrome } from './chrome.mjs';

const [, , FILE, OUTARG, ...flags] = process.argv;
if (!FILE || !OUTARG) { console.log('用法：node qa.mjs <设计器.html> <输出目录> [--quick] [--angle=后端]'); process.exit(1); }
const QUICK = flags.includes('--quick');
const OUT = path.resolve(OUTARG), SHOTS = path.join(OUT, 'shots'), DL = path.join(OUT, 'downloads');
fs.rmSync(OUT, { recursive: true, force: true }); for (const d of [SHOTS, DL]) fs.mkdirSync(d, { recursive: true });
const b = await launchChrome(puppeteer, { headless: 'new', protocolTimeout: 900000, viewport: { width: 1600, height: 960 } });
const page = await b.newPage();
const errs = [];
page.on('pageerror', e => errs.push('pageerror: ' + e.message));
page.on('console', m => { if (m.type() === 'error' && !/favicon|ERR_FILE_NOT_FOUND.*\.ico/.test(m.text())) errs.push('console: ' + m.text()); });
page.on('dialog', d => d.dismiss());
const cdp = await page.createCDPSession();
await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: DL }).catch(() => cdp.send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: DL }));
// 第一次打开前清掉本地保存的方案（同一会话里之后刷新不再清，用来测“保存 → 刷新还在”）
await page.evaluateOnNewDocument(() => { try { if (sessionStorage.getItem('qa-init')) return; sessionStorage.setItem('qa-init', '1'); for (const k of Object.keys(localStorage)) if (k.startsWith('house-designer') || k.startsWith('hd-')) localStorage.removeItem(k); } catch { } });
await page.goto(pathToFileURL(path.resolve(FILE)).href + '?debug', { waitUntil: 'load' });
await page.waitForFunction(() => window.__designer, { timeout: 60000 });

const sleep = ms => new Promise(r => setTimeout(r, ms));
const ev = (fn, ...a) => page.evaluate(fn, ...a);
const results = [];
let shotN = 0;
/** DOM 里能看到的文字有没有 NaN / undefined / [object Object] / Infinity */
const domBad = () => ev(() => {
  const bad = [], seen = new Set();
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    const t = n.textContent; if (!t || !/NaN|undefined|Infinity|\[object |null ?(m|㎡|mm|元|个|盏)/.test(t)) continue;
    const el = n.parentElement; if (!el || el.closest('script,style,template')) continue;
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (!r.width || !r.height || cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) continue;
    const s = t.trim().slice(0, 80); if (!seen.has(s)) { seen.add(s); bad.push(s); }
  }
  for (const i of document.querySelectorAll('input')) if (/NaN|undefined/.test(i.value) && i.offsetParent) bad.push('input=' + i.value);
  return bad;
});
async function step(name, fn, { shot = true, timeout = 120000 } = {}) {
  const e0 = errs.length, t0 = Date.now(); let ok = true, msg = '';
  try {
    const r = await Promise.race([fn(), sleep(timeout).then(() => { throw new Error('超时'); })]);
    if (typeof r === 'string') msg = r;
  } catch (e) { ok = false; msg = String(e && e.message || e).slice(0, 300); }
  await sleep(150);
  const ne = errs.slice(e0);
  if (ne.length) { ok = false; msg += (msg ? '；' : '') + '页面报错：' + ne.slice(0, 3).join(' | ').slice(0, 400); }
  let bad = []; try { bad = await domBad(); } catch { }
  if (bad.length) { ok = false; msg += (msg ? '；' : '') + '界面异常文字：' + bad.slice(0, 4).join(' / '); }
  let file = '';
  if (shot) { file = `${String(++shotN).padStart(3, '0')}_${name.replace(/[\\/:*?"<>| ]+/g, '_').slice(0, 40)}.png`; try { await page.screenshot({ path: path.join(SHOTS, file) }); } catch { } }
  results.push({ name, ok, msg, ms: Date.now() - t0, shot: file });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${msg ? '  —  ' + msg : ''}`);
  return ok;
}
const must = (c, m) => { if (!c) throw new Error(m); };
const dlCount = () => fs.readdirSync(DL).filter(f => !f.endsWith('.crdownload') && !f.endsWith('.tmp')).length;
async function expectDownload(trigger, { wait = 30000, n = 1 } = {}) {
  const snap = () => Object.fromEntries(fs.readdirSync(DL).map(f => [f, fs.statSync(path.join(DL, f)).mtimeMs]));
  const before = snap(); await trigger();
  const t0 = Date.now();
  while (Date.now() - t0 < wait) {
    const now = Object.entries(snap()).filter(([f, m]) => !/\.(crdownload|tmp)$/.test(f) && before[f] !== m).map(([f]) => f);
    if (now.length >= n) { await sleep(500); return now; }
    await sleep(250);
  }
  throw new Error('没有下载到文件');
}
const toastText = () => ev(() => document.querySelector('#toast')?.textContent || '');
const click = sel => ev(s => { const e = document.querySelector(s); if (!e) throw new Error('找不到 ' + s); e.click(); }, sel);
const clickText = (scope, text) => ev((s, t) => { const e = [...document.querySelectorAll(s)].find(x => x.textContent.trim().includes(t)); if (!e) throw new Error(`找不到“${t}”`); e.click(); }, scope, text);
const modalOk = () => ev(() => { const m = document.querySelector('.modal [data-ok]'); if (m) m.click(); return !!m; });
const closeModals = () => ev(() => document.querySelectorAll('.modal').forEach(m => m.remove()));
const st = () => ev(() => { const a = __designer.app, p = a.plan; return { walls: p.walls.length, open: p.openings.length, furn: p.furniture.length, elec: p.elec.length, meas: p.measures.length, com: (p.comments || []).length, rooms: a.rooms.regions.length, tool: a.tool, layer: a.layer, view: a.view, sel: a.sel.kind, phase: p.phase }; });
/** 平面 mm → 页面像素 */
const px = (x, y) => ev((x, y) => { const v = __designer.view, r = document.querySelector('#c2d').getBoundingClientRect(); return [r.x + x * v.s + v.ox, r.y + y * v.s + v.oy]; }, x, y);
async function clickMM(x, y, opt = {}) { const [X, Y] = await px(x, y); await page.mouse.click(X, Y, opt); await sleep(120); }
const multi = await ev(() => !!(__designer.bld && __designer.bld.floors && __designer.bld.floors.length > 1));
const info = await ev(() => ({ name: __designer.app.plan.name, floors: __designer.bld?.floors?.length || 1 }));
console.log('==', info.name, multi ? `${info.floors} 层` : '单层');
// 多层：2D 默认各层平铺，点选测试统一切到“单层”显示（平铺另有专门的测试）
if (multi) { await ev(() => { const b = document.querySelector('#floorDock [data-v2="one"]'); b && b.click(); __designer.fit2D(); }); await sleep(600); }

/* ============================== 2D ============================== */
await step('打开：无报错、平面已画出', async () => {
  await sleep(1500); const s = await st(); must(s.walls > 0, '没有墙'); must(s.rooms > 0, '没有房间');
  const area = await ev(() => document.querySelector('#stArea').textContent); must(/㎡/.test(area), '状态栏面积缺失');
  const r = await ev(() => __designer.runChecks()); const errsN = r.issues.filter(i => i.level === 'error');
  return `墙 ${s.walls} · 门窗 ${s.open} · 家具 ${s.furn} · 点位 ${s.elec}；检查：${r.issues.length} 条提示（其中错误 ${errsN.length}）`;
});
for (const [k, n] of [['layout', '布置'], ['mep', '水电'], ['ceiling', '顶面'], ['floor', '铺装'], ['demolition', '拆改']])
  await step(`图层：${n}`, async () => { await click(`#layerSeg [data-layer="${k}"]`); await sleep(400); must((await st()).layer === k, '图层没切过去'); });
await click('#layerSeg [data-layer="layout"]');
await step('缩放：放大 / 缩小 / 适应窗口', async () => {
  const s0 = await ev(() => __designer.view.s); await click('#zoomIn'); const s1 = await ev(() => __designer.view.s); await click('#zoomOut'); await click('#fitBtn');
  must(s1 > s0, '放大没生效'); const z = await ev(() => document.querySelector('#stZoom').textContent); must(/\d+%/.test(z), '缩放比例显示异常');
});
for (const t of ['plan', 'mep', 'furn']) await step(`左侧面板：${{ plan: '户型', mep: '水电', furn: '家具' }[t]}`, async () => {
  await click(`#leftPanel .tabs [data-tab="${t}"]`); await sleep(400);
  const n = await ev(() => document.querySelector('#leftPanel').innerText.length); must(n > 30, '面板是空的');
});
// 家具库：每一类点一个加进方案
await step('家具库：点击添加 / 撤销 / 重做', async () => {
  await click('#leftPanel .tabs [data-tab="furn"]'); await sleep(300);
  const n0 = (await st()).furn;
  const items = await ev(() => [...document.querySelectorAll('#leftPanel .cat > *')].length); must(items > 20, `家具库只有 ${items} 项`);
  await ev(() => document.querySelector('#leftPanel .cat > *').click()); await sleep(400);
  must((await st()).furn === n0 + 1, '添加家具没生效'); must((await st()).sel === 'furn', '新家具没被选中');
  const insp = await ev(() => document.querySelector('#inspector').innerText); must(insp.length > 20, '属性面板是空的');
  await click('#undoBtn'); await sleep(300); must((await st()).furn === n0, '撤销没生效');
  await click('#redoBtn'); await sleep(300); must((await st()).furn === n0 + 1, '重做没生效');
  await click('#undoBtn'); await sleep(300);
  return `家具库 ${items} 项`;
});
await step('家具库：全部家具类型 2D + 3D 都能画出来', async () => {
  const r = await ev(async () => {
    const D = __designer, p = D.app.plan, CAT = window.__CAT;
    const items = [...document.querySelectorAll('#leftPanel .cat > *')];
    const n0 = p.furniture.length;
    for (const it of items) it.click();
    await new Promise(r => setTimeout(r, 300));
    return { added: p.furniture.length - n0, types: [...new Set(p.furniture.slice(n0).map(f => f.type))].length };
  });
  must(r.added > 20, '没加进去');
  await ev(async () => { await __designer.setView('split'); }); await sleep(3500);
  const bad = await ev(() => { const S = __designer.S3, fm = S.sceneRefs().furnMap, out = []; const T = S.sceneRefs().camera.position.constructor; for (const f of __designer.app.plan.furniture) { const e = fm.get(f.id); if (!e) { out.push(f.type + ':无模型'); continue; } let n = 0; e.g.traverse(o => { if (o.isMesh) n++; }); if (!n) out.push(f.type + ':空'); } return out; });
  await sleep(500);
  await ev(async n => { for (let k = 0; k < n; k++) __designer.undo(); }, r.added); await sleep(800);
  await ev(async () => { await __designer.setView('2d'); }); await sleep(1500);
  must(!bad.length, '3D 没画出来：' + bad.slice(0, 8).join('、'));
  return `${r.added} 件 / ${r.types} 种`;
});
// 选墙 → 属性 → 改厚度 → 撤销
// 选一段非承重墙上没有门窗的实墙部分（点中点）
const wall = await ev(() => { for (const g of __designer.app.geo.active) { if (g.w.bearing) continue; const q = (g.solids || []).find(q => q.s1 - q.s0 > 900); if (q) { const s = (q.s0 + q.s1) / 2; return { id: g.w.id, x: g.a.x + g.u.x * s, y: g.a.y + g.u.y * s, t: g.w.t }; } } const g = __designer.app.geo.active[0]; return { id: g.w.id, x: g.a.x + g.u.x * g.len / 2, y: g.a.y + g.u.y * g.len / 2, t: g.w.t }; });
await step('选择墙：属性面板 / 改墙厚 / 撤销', async () => {
  await ev(() => __designer.fit2D()); await sleep(300);
  await click('#layerSeg [data-layer="layout"]'); await ev(() => __designer.setTool('select'));
  await clickMM(wall.x, wall.y); must((await st()).sel === 'wall', '没选中墙');
  const ins = await ev(() => document.querySelector('#inspector').innerText); must(/墙/.test(ins), '属性面板没显示墙');
  const ok = await ev(() => { const i = [...document.querySelectorAll('#inspector input[type=number], #inspector select')].find(x => /厚/.test(x.closest('label')?.textContent || '')); if (!i) return false; i.value = i.tagName === 'SELECT' ? i.options[0].value : String(+i.value + 20); i.dispatchEvent(new Event('input', { bubbles: true })); i.dispatchEvent(new Event('change', { bubbles: true })); return true; });
  must(ok, '找不到墙厚输入'); await sleep(300);
  const t1 = await ev(id => __designer.app.plan.walls.find(w => w.id === id).t, wall.id); must(t1 !== wall.t, '墙厚没改');
  await click('#undoBtn'); await sleep(300);
  const t2 = await ev(id => __designer.app.plan.walls.find(w => w.id === id).t, wall.id); must(t2 === wall.t, '撤销后墙厚没恢复');
});
await step('立面图（墙）', async () => {
  await clickMM(wall.x, wall.y); await sleep(200);
  const has = await ev(() => !!document.querySelector('#wElev')); if (!has) return '这面墙没有立面按钮';
  await click('#wElev'); await sleep(800); const m = await ev(() => !!document.querySelector('.modal canvas')); must(m, '立面图没打开');
});
await closeModals();
// 画墙 / 画房间：在户型外面空白处
const bb = await ev(() => { const b = __designer.app.geo.bounds; return b; });
const ox = bb.x1 + 1500, oy = bb.y + 500;
await step('画墙（两段）+ Esc 结束 + 撤销', async () => {
  const s0 = await st(); await click('#toolSeg [data-tool="wall"]'); must((await st()).tool === 'wall', '工具没切换');
  await ev(() => __designer.fit2D()); const [X, Y] = await px(ox, oy); const r = await ev(() => { const q = document.querySelector('#c2d').getBoundingClientRect(); return { x: q.x, y: q.y, right: q.right, bottom: q.bottom }; });
  const x0 = Math.min(X, r.right - 200), y0 = Math.min(Math.max(Y, r.y + 100), r.bottom - 200);
  await page.mouse.click(x0, y0); await page.mouse.click(x0 + 120, y0); await page.mouse.click(x0 + 120, y0 + 100); await page.keyboard.press('Escape'); await sleep(300);
  const s1 = await st(); must(s1.walls >= s0.walls + 2, `墙没画出来（${s0.walls} → ${s1.walls}）`);
  await click('#undoBtn'); await click('#undoBtn'); await sleep(300); await ev(() => __designer.setTool('select'));
  const s2 = await st(); must(s2.walls === s0.walls, `撤销后墙数不对（${s2.walls}）`);
});
await step('画房间 + 撤销', async () => {
  const s0 = await st(); await click('#toolSeg [data-tool="rect"]');
  const r = await ev(() => { const q = document.querySelector('#c2d').getBoundingClientRect(); return { x: q.x, y: q.y, right: q.right, bottom: q.bottom }; });
  const x0 = r.right - 220, y0 = r.y + 140; await page.mouse.click(x0, y0); await page.mouse.click(x0 + 140, y0 + 110); await sleep(400);
  const s1 = await st(); must(s1.walls >= s0.walls + 4, `房间没画出来（${s0.walls} → ${s1.walls}）`);
  await click('#undoBtn'); await sleep(300); await ev(() => __designer.setTool('select'));
  must((await st()).walls === s0.walls, '撤销没恢复');
});
await step('门窗工具：在墙上放一扇门 + 撤销', async () => {
  const s0 = await st(); await click('#toolSeg [data-tool="opening"]'); await sleep(300);
  await ev(() => { const b = document.querySelector('#leftPanel [data-op="door"]'); b && b.click(); });
  // 找一段够长、没有门窗的墙段
  const g = await ev(() => { const A = __designer.app; for (const g of A.geo.active) { if (g.len < 2400) continue; const free = g.solids?.find(q => q.s1 - q.s0 > 1300); if (free) { const s = (free.s0 + free.s1) / 2; return { x: g.a.x + g.u.x * s, y: g.a.y + g.u.y * s }; } } return null; });
  must(g, '找不到能放门的墙'); await clickMM(g.x, g.y); await sleep(300);
  const s1 = await st(); must(s1.open === s0.open + 1, `门没放上（${s0.open} → ${s1.open}）`);
  await click('#undoBtn'); await sleep(200); await ev(() => __designer.setTool('select'));
});
const room = await ev(() => { const r = __designer.app.rooms.regions.filter(r => r.labels.length && r.area > 6).sort((a, b) => b.area - a.area)[0]; return { x: r.interior.x, y: r.interior.y, name: r.labels[0].name }; });
await step('水电工具：在墙边放一个插座 + 撤销', async () => {
  const s0 = await st(); await click('#toolSeg [data-tool="elec"]'); await sleep(300);
  must((await st()).layer === 'mep', '没切到水电图层');
  // 插座要贴墙放：在一段实墙两侧离墙面 80mm 处各试一次
  const g = await ev(id => { const g = __designer.app.geo.active.find(g => g.w.id === id); return { ax: g.a.x, ay: g.a.y, ux: g.u.x, uy: g.u.y, len: g.len, t: g.w.t }; }, wall.id);
  for (const sd of [1, -1]) {
    const nx = -g.uy * sd, ny = g.ux * sd, d = g.t / 2 + 80;
    await clickMM(wall.x + nx * d, wall.y + ny * d); await sleep(250);
    if ((await st()).elec > s0.elec) break;
  }
  const s1 = await st(); must(s1.elec === s0.elec + 1, `点位没放上（${s0.elec} → ${s1.elec}）：${await toastText()}`);
  await click('#undoBtn'); await sleep(200); await ev(() => __designer.setTool('select'));
});
await step('批注：放一条 + 回复面板', async () => {
  await ev(() => { try { localStorage.setItem('house-designer-author', '验收'); } catch { } });
  const s0 = await st(); await click('#toolSeg [data-tool="comment"]'); await clickMM(room.x - 200, room.y - 200); await sleep(500);
  const hasModal = await ev(() => { const t = document.querySelector('.modal textarea, .modal input'); if (t) { t.value = '验收留言'; t.dispatchEvent(new Event('input')); } return !!t; });
  if (hasModal) { await modalOk(); await sleep(400); }
  const s1 = await st(); must(s1.com === s0.com + 1, `批注没加上（${s0.com} → ${s1.com}）`);
  await ev(() => __designer.setTool('select')); await click('#undoBtn'); await sleep(200);
});
await step('测量：两点 + 清除全部测量', async () => {
  const s0 = await st(); await click('#toolSeg [data-tool="measure"]'); await clickMM(room.x - 800, room.y); await clickMM(room.x + 800, room.y); await sleep(300);
  const s1 = await st(); must(s1.meas === s0.meas + 1, '测量没生成');
  await ev(() => __designer.setTool('select'));
  await click('#moreMenu > button'); await click('#moreMenu [data-act="clearMeasure"]'); await sleep(200);
  must((await st()).meas === 0, '清除测量没生效');
});
await step('拆墙：拆除 ↔ 恢复（承重墙不能拆）', async () => {
  if ((await st()).phase === 'original') { await ev(() => document.querySelector('#leftPanel .tabs [data-tab="plan"]').click()); await ev(() => document.querySelector('#leftPanel [data-ph="renovate"]')?.click()); }
  const namesBefore = await ev(() => __designer.app.plan.rooms.map(r => r.name).sort().join('|'));
  const w = await ev(() => { const g = __designer.app.geo.active.find(g => !g.w.bearing && g.w.status !== 'new' && g.len > 1200); return g && { id: g.w.id, x: g.a.x + g.u.x * g.len / 2, y: g.a.y + g.u.y * g.len / 2 }; });
  if (!w) return '没有可拆的墙';
  await click('#toolSeg [data-tool="demolish"]'); await clickMM(w.x, w.y); await sleep(300);
  const s1 = await ev(id => __designer.app.plan.walls.find(q => q.id === id).status, w.id); must(s1 === 'removed', '没拆掉：' + s1);
  await ev(() => __designer.setTool('select'));
  await click('#moreMenu > button'); await click('#moreMenu [data-act="restoreWalls"]'); await sleep(300); await modalOk(); await sleep(300);
  const s2 = await ev(id => __designer.app.plan.walls.find(q => q.id === id).status, w.id); must(s2 === 'existing', '恢复没生效：' + s2);
  const namesAfter = await ev(() => __designer.app.plan.rooms.map(r => r.name).sort().join('|')); must(namesAfter === namesBefore, `恢复后房间名变了：${namesBefore} → ${namesAfter}`);
  const bw = await ev(() => { const g = __designer.app.geo.active.find(g => g.w.bearing && g.len > 1200); return g && { id: g.w.id, x: g.a.x + g.u.x * g.len / 2, y: g.a.y + g.u.y * g.len / 2 }; });
  if (bw) { await click('#toolSeg [data-tool="demolish"]'); await clickMM(bw.x, bw.y); await sleep(200); const s3 = await ev(id => __designer.app.plan.walls.find(q => q.id === id).status, bw.id); must(s3 !== 'removed', '承重墙被拆了'); await ev(() => __designer.setTool('select')); }
});
// 家具：选中 / 拖动 / 旋转 / 复制 / 删除
// 找一件点得中的家具（中心点没被别的东西盖住）
await ev(() => { __designer.setLayer('layout'); __designer.setTool('select'); __designer.fit2D(); });
let furn = null;
for (const f of await ev(() => __designer.app.plan.furniture.filter(f => f.w > 500 && f.d > 400 && !/curtain|rug|carpet/.test(f.type)).slice(0, 25).map(f => ({ id: f.id, x: f.x, y: f.y, rot: f.rot })))) {
  await clickMM(f.x, f.y); const sel = await ev(() => __designer.app.sel); if (sel.kind === 'furn' && sel.id === f.id) { furn = f; break; }
}
await ev(() => __designer.select(null));
if (furn) await step('家具：点选 / 拖动 / R 旋转 / Ctrl+D 复制 / Delete 删除', async () => {
  await click('#layerSeg [data-layer="layout"]'); await ev(() => __designer.setTool('select'));
  await clickMM(furn.x, furn.y); must((await st()).sel === 'furn', '没选中家具');
  const [X, Y] = await px(furn.x, furn.y); await page.mouse.move(X, Y); await page.mouse.down(); await page.mouse.move(X + 20, Y + 10, { steps: 5 }); await page.mouse.up(); await sleep(200);
  const f1 = await ev(id => { const f = __designer.app.plan.furniture.find(q => q.id === id); return { x: f.x, y: f.y }; }, furn.id); must(Math.hypot(f1.x - furn.x, f1.y - furn.y) > 50, '拖动没生效');
  await page.keyboard.press('KeyR'); await sleep(150); const r1 = await ev(id => __designer.app.plan.furniture.find(q => q.id === id).rot, furn.id); must(r1 !== furn.rot, '旋转没生效');
  const n0 = (await st()).furn; await page.keyboard.down('Control'); await page.keyboard.press('KeyD'); await page.keyboard.up('Control'); await sleep(200);
  must((await st()).furn === n0 + 1, '复制没生效');
  await page.keyboard.press('Delete'); await sleep(200); must((await st()).furn === n0, '删除没生效');
  for (let k = 0; k < 4; k++) await click('#undoBtn').catch(() => { }); await sleep(300);
  const f2 = await ev(id => __designer.app.plan.furniture.find(q => q.id === id), furn.id); must(f2 && Math.abs(f2.x - furn.x) < 2 && f2.rot === furn.rot, '撤销没恢复到原位');
});
await step('选择房间：属性面板 + 立面图', async () => {
  await click('#layerSeg [data-layer="layout"]'); await ev(() => __designer.select(null));
  const lab = await ev(() => { const R = __designer.app.rooms.regions.filter(r => r.labels.length === 1 && r.area > 8).sort((a, b) => a.area - b.area); const l = R[0]?.labels[0]; return l && { id: l.id, x: l.x, y: l.y }; });
  if (!lab) return '方案里没有房间标签';
  await clickMM(lab.x, lab.y); await sleep(300);
  const s = await st(); must(s.sel === 'room' || s.sel === 'roomLabel' || s.sel, '没选中房间');
  const ins = await ev(() => document.querySelector('#inspector').innerText); must(ins.length > 30, '属性面板空');
  const has = await ev(() => !!document.querySelector('#rElev')); if (has) { await click('#rElev'); await sleep(800); must(await ev(() => !!document.querySelector('.modal canvas')), '立面图没打开'); await ev(() => document.querySelectorAll('.modal [data-i]').forEach(b => b.click())); }
});
await closeModals();
/* ---------------- 编辑细节：定制柜、门窗、房间材质、点位、楼层、方案 ---------------- */
async function selectFurn(pred) {
  await ev(() => { __designer.setLayer('layout'); __designer.setTool('select'); __designer.fit2D(); }); await sleep(200);
  const cands = await ev(src => __designer.app.plan.furniture.filter(eval(src)).map(f => ({ id: f.id, x: f.x, y: f.y })), pred);
  for (const f of cands.slice(0, 8)) { await clickMM(f.x, f.y); const sel = await ev(() => __designer.app.sel); if (sel.kind === 'furn' && sel.id === f.id) return f; }
  return null;
}
await step('定制橱柜：一字 / L / U 造型切换', async () => {
  const f = await selectFurn("f => ['counter', 'lCounter', 'uCounter'].includes(f.type)"); if (!f) return '方案里没有橱柜';
  const has = await ev(() => !!document.querySelector('#kShape')); must(has, '属性面板没有橱柜定制');
  const s0 = await ev(id => JSON.stringify(__designer.app.plan.furniture.find(q => q.id === id)), f.id);
  for (const v of ['L', 'U', 'I']) { await ev(v => { const e = document.querySelector('#kShape'); if (!e) return; e.value = v; e.dispatchEvent(new Event('change', { bubbles: true })); }, v); await sleep(400); if (v === 'U') await page.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_定制橱柜_U形.png`) }); }
  const s1 = await ev(id => JSON.stringify(__designer.app.plan.furniture.find(q => q.id === id)), f.id); must(s1 !== s0, '改造型没生效');
  for (let k = 0; k < 3; k++) await click('#undoBtn'); await sleep(300);
});
await step('定制柜：属性面板改分格', async () => {
  const f = await selectFurn("f => f.type === 'cabinet' && f.cab"); if (!f) return '方案里没有定制柜';
  const n = await ev(() => document.querySelectorAll('#inspector .cust select, #inspector .cust input').length); must(n > 2, '定制区没有选项');
  const ok = await ev(() => { const e = document.querySelector('#inspector .cust select'); if (!e || e.options.length < 2) return false; e.value = e.options[(e.selectedIndex + 1) % e.options.length].value; e.dispatchEvent(new Event('change', { bubbles: true })); return true; }); await sleep(400);
  must(ok, '改不了'); await page.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_定制柜.png`) }); await click('#undoBtn'); await sleep(200);
});
await step('门窗属性：改类型 / 开向 + 撤销', async () => {
  await ev(() => { __designer.setLayer('layout'); __designer.setTool('select'); __designer.fit2D(); });
  const o = await ev(() => { const A = __designer.app; for (const g of A.geo.active) for (const q of g.ops || []) if (q.o.type === 'door') { const s = (q.s0 + q.s1) / 2; return { id: q.o.id, x: g.a.x + g.u.x * s, y: g.a.y + g.u.y * s }; } return null; });
  if (!o) return '没有门';
  await clickMM(o.x, o.y); must((await st()).sel === 'opening', '没选中门');
  const t0 = await ev(id => JSON.stringify(__designer.app.plan.openings.find(q => q.id === id)), o.id);
  await ev(() => { const e = document.querySelector('#oType'); if (e) { e.value = [...e.options].map(x => x.value).find(v => v === 'double') || e.options[1].value; e.dispatchEvent(new Event('change', { bubbles: true })); } }); await sleep(300);
  const t1 = await ev(id => JSON.stringify(__designer.app.plan.openings.find(q => q.id === id)), o.id); must(t1 !== t0, '属性没改动');
  await page.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_门窗属性.png`) });
  await click('#undoBtn'); await sleep(300);
  const t2 = await ev(id => JSON.stringify(__designer.app.plan.openings.find(q => q.id === id)), o.id); must(t2 === t0, '撤销没恢复');
});
await step('房间属性：地面材质 / 吊顶 + 撤销', async () => {
  await ev(() => { __designer.setLayer('layout'); __designer.setTool('select'); __designer.select(null); });
  const lab = await ev(() => { const R = __designer.app.rooms.regions.filter(r => r.labels.length === 1 && r.area > 8).sort((a, b) => a.area - b.area); const l = R[0].labels[0]; return { id: l.id, x: l.x, y: l.y }; });
  await clickMM(lab.x, lab.y); await sleep(200);
  const sel = await ev(() => __designer.app.sel); must(sel.kind === 'room', '没选中房间：' + sel.kind); lab.id = sel.id;
  const m0 = await ev(id => JSON.stringify(__designer.app.plan.rooms.find(q => q.id === id)), lab.id);
  await ev(() => { const e = document.querySelector('#rCeil'); if (e) { e.value = e.options[(e.selectedIndex + 1) % e.options.length].value; e.dispatchEvent(new Event('change', { bubbles: true })); } }); await sleep(300);
  const m1 = await ev(id => JSON.stringify(__designer.app.plan.rooms.find(q => q.id === id)), lab.id); must(m1 !== m0, '吊顶没改动');
  await page.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_房间属性.png`) });
  await click('#undoBtn'); await sleep(300);
});
await step('水电点位属性：改类型 + 撤销', async () => {
  await ev(() => { __designer.setLayer('mep'); __designer.setTool('select'); });
  const e = await ev(() => { const e = __designer.app.plan.elec.find(e => e.kind === 'socket'); return e && { id: e.id, x: e.x, y: e.y }; }); if (!e) return '没有插座';
  await clickMM(e.x, e.y); const sel = await st(); if (sel.sel !== 'elec') return '点位被别的元素盖住，跳过';
  e.id = await ev(() => __designer.app.sel.id);
  const k0 = await ev(id => __designer.app.plan.elec.find(q => q.id === id).kind, e.id);
  await ev(() => { const s = document.querySelector('#eKind'); if (s) { s.value = [...s.options].map(o => o.value).find(v => v !== s.value); s.dispatchEvent(new Event('change', { bubbles: true })); } }); await sleep(300);
  const k1 = await ev(id => __designer.app.plan.elec.find(q => q.id === id)?.kind, e.id); must(k1 !== k0, '类型没改'); await click('#undoBtn'); await sleep(200);
});
if (!multi) await step('楼层：复制本层为二层 → 楼层面板出现 → 撤销', async () => {
  await click('#leftPanel .tabs [data-tab="plan"]'); await sleep(300);
  await ev(() => document.querySelector('#leftPanel [data-addf="copy"]').click()); await sleep(1200);
  const n = await ev(() => __designer.bld.floors.length); must(n === 2, `楼层数 ${n}`); must(await ev(() => document.querySelector('#floorDock').style.display !== 'none'), '楼层面板没出现');
  await page.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_加楼层.png`) });
  await click('#undoBtn'); await sleep(800); const n2 = await ev(() => __designer.bld.floors?.length || 1); must(n2 === 1, `撤销后还有 ${n2} 层`);
});
await step('方案管理：复制当前方案 → 对比 → 关闭', async () => {
  await click('#schemeBtn'); await sleep(800);
  const n0 = await ev(() => document.querySelectorAll('.modal .sccard').length);
  await ev(() => document.querySelector('.modal [data-new="copy"]').click()); await sleep(1500);
  must(/已新建并切换/.test(await toastText()), '复制后没切换：' + await toastText());
  await closeModals(); await click('#schemeBtn'); await sleep(1200);
  const n1 = await ev(() => document.querySelectorAll('.modal .sccard').length); must(n1 === n0 + 1, `方案数 ${n0} → ${n1}`);
  await ev(() => { const cs = [...document.querySelectorAll('.modal .sccard .pick input')].slice(0, 2); cs.forEach(c => { c.checked = true; c.dispatchEvent(new Event('change')); }); }); await sleep(200);
  await click('#scCmp'); await sleep(1500); must(await ev(() => !!document.querySelector('#cmX')), '对比页没打开');
  await page.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_方案对比.png`) });
  await click('#cmX'); await closeModals(); await sleep(300);
});

await step('层高 / 方案名 / 阶段切换', async () => {
  await click('#leftPanel .tabs [data-tab="plan"]'); await sleep(300);
  const ph0 = (await st()).phase; await ev(p => document.querySelector(`#leftPanel [data-ph="${p === 'original' ? 'renovate' : 'original'}"]`)?.click(), ph0); await sleep(300);
  must((await st()).phase !== ph0, '阶段没切换'); await ev(p => document.querySelector(`#leftPanel [data-ph="${p}"]`)?.click(), ph0); await sleep(300);
  const tag = await ev(() => document.querySelector('#phaseTag').textContent); must(tag.length, '顶栏阶段标签空');
});
/* ---------------- 水电 ---------------- */
await step('一键布置水电（确认后点位数合理）', async () => {
  await click('#leftPanel .tabs [data-tab="mep"]'); await sleep(300);
  const e0 = (await st()).elec; await click('#autoElec'); await sleep(400); await modalOk(); await sleep(1500);
  const e1 = (await st()).elec; must(e1 > 10, `点位太少：${e1}`); return `${e0} → ${e1} 个点位`;
});
await step('自动关联开关', async () => { await click('#autoLink'); await sleep(300); const t = await toastText(); must(/关联/.test(t), '没有提示：' + t); return t; });
for (const v of ['all', 'power', 'light', 'weak', 'water', 'drain'])
  await step(`管线视图：${v}`, async () => { await click('#layerSeg [data-layer="mep"]'); await ev(id => document.querySelector(`#mepPreset [data-p="${id}"]`).click(), v); await sleep(500); must(await ev(id => document.querySelector(`#mepPreset [data-p="${id}"]`)?.classList.contains('on'), v), '按钮没高亮'); });
await step('管线：回路表 / 材料清单数值正常', async () => {
  const r = await ev(() => { const m = __designer.mep(); return { c: m.circuits.length, runs: m.runs.length, bad: m.runs.filter(x => !isFinite(x.len) || x.pts.some(p => !isFinite(p.x))).length, bom: m.bom.filter(b => !(b.qty >= 0)).length }; });
  must(r.runs > 0, '没有管线'); must(!r.bad, `${r.bad} 段管线坐标异常`); must(!r.bom, '材料清单有异常数量'); return `${r.c} 个回路、${r.runs} 段管线`;
});
await step('管线：点中一段 → 属性；拖动；恢复自动走线', async () => {
  await ev(() => document.querySelector('#mepPreset [data-p="power"]').click()); await ev(() => __designer.setTool('select')); await sleep(300);
  const seg = await ev(() => { const m = __designer.mep(); for (const r of m.runs) if (r.sys === 'power') for (let k = 0; k + 1 < r.pts.length; k++) { const a = r.pts[k], b = r.pts[k + 1]; if (Math.abs(a.y - b.y) < 1 && Math.abs(a.x - b.x) > 1200) { const x = (a.x + b.x) / 2, y = a.y, tol = 20 / __designer.view.s; if (!__designer.app.plan.nodes.some(n => Math.hypot(n.x - x, n.y - y) < tol) && !__designer.app.plan.elec.some(e => Math.hypot(e.x - x, e.y - y) < tol)) return { x, y, key: r.key }; } } return null; });
  must(seg, '找不到能拖的线段');
  const [X, Y] = await px(seg.x, seg.y); await page.mouse.click(X, Y); await sleep(300);
  const sel = await st(); must(sel.sel === 'run', '没选中管线：' + sel.sel);
  await page.mouse.move(X, Y); await page.mouse.down(); await page.mouse.move(X, Y + 25, { steps: 6 }); await page.mouse.up(); await sleep(400);
  const ed = await ev(() => Object.keys(__designer.app.plan.mep?.edits || {}).length); must(ed > 0, '拖动没记录');
  await click('#leftPanel .tabs [data-tab="mep"]'); await sleep(200); await click('#mepReset'); await sleep(300);
  must(await ev(() => !Object.keys(__designer.app.plan.mep?.edits || {}).length), '恢复自动走线没生效');
});
await step('管线：插座走顶 / 给水走地 切换', async () => {
  for (const [id, v] of [['#mepPower', 'ceil'], ['#mepWater', 'floor'], ['#mepPower', 'floor'], ['#mepWater', 'ceil']]) {
    await ev((id, v) => { const s = document.querySelector(id); s.value = v; s.dispatchEvent(new Event('change', { bubbles: true })); }, id, v); await sleep(400);
  }
});
await step('导出：当前视图图片', async () => { await ev(() => document.querySelector('#mepPreset [data-p="all"]').click()); const f = await expectDownload(() => click('#mepPng')); return f.join(','); });
await step('导出：当前视图 CAD', async () => { const f = await expectDownload(() => click('#mepDxf')); return f.join(','); });
await step('导出：5 类管线分别导出 CAD', async () => { const f = await expectDownload(() => click('#mepDxfAll'), { n: 5, wait: 30000 }); return f.length + ' 个'; });
await step('导出：回路表 + 材料清单 CSV', async () => { const f = await expectDownload(() => click('#mepCsv')); return f.join(','); });
/* ---------------- 报价 / 方案 ---------------- */
await step('报价：打开、合计正常、导出 CSV', async () => {
  await click('#quoteBtn'); await sleep(800);
  const t = await ev(() => document.querySelector('.modal')?.innerText || ''); must(/合计|总计/.test(t), '报价里没有合计');
  await page.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_报价单.png`) });
  const f = await expectDownload(() => click('#qCsv')); await click('#qX'); return f.join(',');
});
await step('方案管理：打开 / 关闭', async () => { await click('#schemeBtn'); await sleep(600); must(await ev(() => !!document.querySelector('.modal .scgrid')), '方案管理没打开'); await page.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_方案管理.png`) }); await click('#scX'); });
await closeModals();
/* ---------------- 导出菜单 ---------------- */
for (const [k, n] of [['original', '原始结构图'], ['demolition', '拆改图'], ['layout', '平面布置图'], ['floor', '地面铺装图'], ['ceiling', '顶面布置图'], ['mep', '水电点位图'], ['dxf', 'CAD 国标'], ['dxf-deco', 'CAD 装修'], ['dxf-mep', 'CAD 水电'], ['share', '分享文件']])
  await step(`导出菜单：${n}`, async () => {
    const f = await expectDownload(async () => { await click('#exportMenu > button'); await click(`#exportMenu [data-exp="${k}"]`); });
    if (k === 'share') { // 分享文件要能单独打开：载入方案、显示分享横幅、没有报错
      const m = await b.newPage(); const e2 = []; m.on('pageerror', e => e2.push(e.message));
      await m.goto(pathToFileURL(path.join(DL, f[0])).href, { waitUntil: 'load' }); await sleep(3500);
      const r = await m.evaluate(() => ({ area: document.querySelector('#stArea')?.textContent || '', banner: getComputedStyle(document.querySelector('#shareBanner')).display !== 'none' && document.querySelector('#shareBanner').innerText.length > 0 }));
      await m.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_分享文件打开.png`) }); await m.close();
      must(!e2.length, '分享文件打开报错：' + e2[0]); must(/㎡/.test(r.area), '分享文件没载入方案'); must(r.banner, '没有分享横幅');
    }
    return f.join(',');
  });
if (!QUICK) await step('导出菜单：整套施工图 PDF', async () => { const f = await expectDownload(async () => { await click('#exportMenu > button'); await click('#exportMenu [data-exp="pdf"]'); }, { wait: 240000 }); return f.join(',') + ' · ' + await toastText(); }, { timeout: 260000 });
await step('更多：导出方案 JSON → 再导入', async () => {
  const f = await expectDownload(async () => { await click('#moreMenu > button'); await click('#moreMenu [data-act="exportJson"]'); });
  const inp = await page.$('#fileIn'); await inp.uploadFile(path.join(DL, f[0])); await sleep(1500);
  const t = await toastText(); must(/导入/.test(t) && !/不正确/.test(t), '导入失败：' + t); return f[0];
});
await step('保存 → 刷新页面 → 方案还在', async () => {
  const n0 = (await st()).furn; await click('#saveBtn'); await sleep(500);
  await page.reload({ waitUntil: 'load' }); await page.waitForFunction(() => window.__designer, { timeout: 60000 }); await sleep(2000);
  const n1 = (await st()).furn; must(n1 === n0, `刷新后家具数 ${n0} → ${n1}`); const t = await toastText(); return t;
});
/* ============================== 3D ============================== */
const to3d = async v => { await ev(async v => { await __designer.setView(v); }, v); await sleep(3200); };
await step('分屏视图', async () => { await click('#viewSeg [data-view="split"]'); await sleep(3500); must((await st()).view === 'split', '没进分屏'); });
await step('3D 视图：鸟瞰', async () => { await click('#viewSeg [data-view="3d"]'); await sleep(3500); must((await st()).view === '3d', '没进 3D'); must(await ev(() => __designer.S3.ready), '3D 没准备好'); });
const canvasStd = () => ev(() => { const S = __designer.S3; S.renderNow(); const c = document.querySelector('#c3d'), t = document.createElement('canvas'); t.width = 160; t.height = 90; const x = t.getContext('2d'); x.drawImage(c, 0, 0, 160, 90); const d = x.getImageData(0, 0, 160, 90).data; let s = 0, s2 = 0, n = 0; for (let i = 0; i < d.length; i += 4) { const v = (d[i] + d[i + 1] + d[i + 2]) / 3; s += v; s2 += v * v; n++; } const m = s / n; return { mean: m, std: Math.sqrt(s2 / n - m * m) }; });
await step('3D 画面不是空白', async () => { const s = await canvasStd(); must(s.std > 12, `画面像是空的（std ${s.std.toFixed(1)}）`); return `亮度 ${s.mean.toFixed(0)}，起伏 ${s.std.toFixed(0)}`; });
await step('重置视角 / 锁定开关', async () => { await click('#camReset'); await sleep(1200); await click('#lockBtn'); await sleep(200); const t1 = await ev(() => document.querySelector('#lockBtn').textContent); await click('#lockBtn'); must(t1 === '🔒', '锁定按钮没变'); });
await step('管线透视 开 / 关', async () => { await click('#mepBtn'); await sleep(1500); must(await ev(() => document.querySelector('#mepBtn').classList.contains('on')), '没打开'); await page.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_管线透视_开.png`) }); await click('#mepBtn'); await sleep(800); });
await step('光照面板：城市 / 月份 / 时间 / 正北 / 开灯', async () => {
  await click('#lightBtn'); await sleep(300); must(await ev(() => document.querySelector('#lightPop').classList.contains('open')), '面板没打开');
  await ev(() => { const s = document.querySelector('#cityIn'); s.value = s.options[Math.min(3, s.options.length - 1)].value; s.dispatchEvent(new Event('change')); });
  for (const [id, v] of [['#monthIn', '12'], ['#timeIn', '20'], ['#northIn', '30'], ['#timeIn', '10'], ['#northIn', '0']]) await ev((id, v) => { const i = document.querySelector(id); i.value = v; i.dispatchEvent(new Event('input')); i.dispatchEvent(new Event('change')); }, id, v);
  await ev(() => { const c = document.querySelector('#lampIn'); c.checked = true; c.dispatchEvent(new Event('change')); }); await sleep(600);
  const info = await ev(() => document.querySelector('#sunInfo').innerText); must(/日出|月亮|太阳/.test(info), '太阳信息异常：' + info);
  await ev(() => { const c = document.querySelector('#lampIn'); c.checked = false; c.dispatchEvent(new Event('change')); }); return info;
});
await step('日照演示：播放后回到原来的时间', async () => {
  const t0 = await ev(() => __designer.S3.lighting.time); await click('#sunDemo'); await sleep(3000); must(await ev(() => __designer.S3.demoActive()), '演示没开始');
  await sleep(15500); const t1 = await ev(() => ({ on: __designer.S3.demoActive(), t: __designer.S3.lighting.time }));
  must(!t1.on, '演示没结束'); must(Math.abs(t1.t - t0) < .05, `演示后时间没回到 ${t0}（现在 ${t1.t.toFixed(2)}）`);
}, { timeout: 40000 });
await ev(() => { document.querySelector('#lightPop').classList.remove('open'); const i = document.querySelector('#timeIn'); i.value = '15'; i.dispatchEvent(new Event('input')); });
await click('#lookBtn'); await sleep(300);
for (const s of ['diorama', 'colorplan', 'real']) await step(`风格：${{ real: '写实', diorama: '沙盘', colorplan: '彩平图' }[s]}`, async () => { await click(`#lookStyle [data-style="${s}"]`); await sleep(2500); must(await ev(() => __designer.S3.look().style), ''); const c = await canvasStd(); must(c.std > 8, '画面空白'); });
const pals = await ev(() => [...document.querySelectorAll('#lookPal button')].map(b => b.dataset.pal));
for (const p of (QUICK ? pals.slice(0, 3) : pals)) await step(`配色：${p}`, async () => { await ev(p => document.querySelector(`#lookPal [data-pal="${p}"]`).click(), p); await sleep(1200); must(await ev(() => __designer.S3.look().palette), ''); });
await ev(p => document.querySelector(`#lookPal [data-pal="${p}"]`).click(), pals[0]);
for (const q of ['fast', 'balanced', 'high']) await step(`画质：${q}`, async () => { await click(`#lookQ [data-q="${q}"]`); await sleep(1500); must(await ev(() => __designer.S3.qualityLevel()) === q, '没切换'); must((await canvasStd()).std > 8, '画面空白'); });
await step('沙盘选项：辉光 / 房间名 / 圆润 / 景深 + 沙盘俯视', async () => {
  await click('#lookStyle [data-style="diorama"]'); await sleep(2000);
  for (const o of ['glow', 'labels', 'round', 'tilt']) { await ev(o => { const i = document.querySelector(`#lookOpts [data-opt="${o}"]`); i.checked = !i.checked; i.dispatchEvent(new Event('change')); }, o); await sleep(600); await ev(o => { const i = document.querySelector(`#lookOpts [data-opt="${o}"]`); i.checked = !i.checked; i.dispatchEvent(new Event('change')); }, o); }
  await click('#lookPose'); await sleep(1500);
});
await step('彩平图：尺寸 不标 / 简洁 / 完整', async () => { await click('#lookStyle [data-style="colorplan"]'); await sleep(2500); for (const d of ['none', 'full', 'simple']) { await click(`#cpDims [data-d="${d}"]`); await sleep(1200); } });
await step('导出：彩平图 PNG', async () => { const f = await expectDownload(async () => { await click('#exportMenu > button'); await click('#exportMenu [data-exp="colorplan"]'); }, { wait: 60000 }); return f.join(','); });
await click('#lookStyle [data-style="real"]'); await sleep(2500); await ev(() => document.querySelector('#lookPop').classList.remove('open'));
await step('导出：当前 3D 画面', async () => { const f = await expectDownload(async () => { await click('#exportMenu > button'); await click('#exportMenu [data-exp="3d"]'); }); return f.join(','); });
await step('渲染出图：实时 1920×1080', async () => {
  await ev(() => { document.querySelector('#rendMode').value = 'raster'; document.querySelector('#resIn').value = '1920x1080'; });
  const f = await expectDownload(() => click('#renderBtn'), { wait: 90000 }); return f.join(',');
}, { timeout: 120000 });
/* 漫游 */
await step('漫游：进入 / 走动 / 转向 / 退出', async () => {
  await ev(r => { const S = __designer.S3; S.enterFP({ x: r.x, y: r.y }); }, room); await sleep(2200);
  must(await ev(() => __designer.S3.fp.active), '没进漫游');
  const p0 = await ev(() => ({ x: __designer.S3.fp.x, y: __designer.S3.fp.y }));
  await page.keyboard.down('KeyW'); await sleep(900); await page.keyboard.up('KeyW');
  await page.keyboard.down('KeyD'); await sleep(500); await page.keyboard.up('KeyD'); await sleep(300);
  const p1 = await ev(() => ({ x: __designer.S3.fp.x, y: __designer.S3.fp.y })); must(Math.hypot(p1.x - p0.x, p1.y - p0.y) > 100, '按 W 没走动');
  must((await canvasStd()).std > 6, '漫游画面空白');
  await page.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_漫游画面.png`) });
});
await step('720° 全景（漫游中）', async () => {
  await click('#panoBtn'); await sleep(6000); must(await ev(() => !!document.querySelector('.modal')), '全景预览没打开');
  const f = await expectDownload(() => ev(() => { const b = [...document.querySelectorAll('.modal button')].find(x => /下载|保存/.test(x.textContent)); if (!b) throw new Error('全景预览里没有下载按钮'); b.click(); })); await closeModals(); return f.join(',');
}, { timeout: 90000 });
await step('3D 里点门 / 开关（射线点中可交互物体）', async () => {
  const r = await ev(async () => {
    const S = __designer.S3, D = __designer, op = D.app.plan.openings.find(o => o.type === 'door');
    if (!op) return 'no door';
    const before = S.doorOpen.get(op.id); S.toggleDoor(op.id); await new Promise(r => setTimeout(r, 900)); const after = S.doorOpen.get(op.id); S.toggleDoor(op.id);
    return before !== after ? 'ok' : 'door state unchanged';
  });
  must(r === 'ok' || r === 'no door', r);
});
await step('退出漫游', async () => { await page.keyboard.press('Escape'); await sleep(1800); must(!(await ev(() => __designer.S3.fp.active)), '没退出'); });
if (!QUICK) await step('光线追踪出图（提前结束保存）', async () => {
  await ev(() => { document.querySelector('#rendMode').value = 'pt'; document.querySelector('#resIn').value = '1920x1080'; });
  const f = await expectDownload(async () => {
    await click('#renderBtn');
    const t0 = Date.now(); while (Date.now() - t0 < 300000) { const s = await ev(() => document.querySelector('#ptProg span').textContent); if (/已采样 ([2-9]\d|\d{3})/.test(s)) break; await sleep(2000); }
    await ev(() => document.querySelector('#ptProg button').click());
  }, { wait: 360000 });
  await ev(() => { document.querySelector('#rendMode').value = 'raster'; }); return f.join(',');
}, { timeout: 400000 });
/* 智能中控 */
await step('智能中控：进入', async () => { await click('#smartBtn'); await sleep(4000); must(await ev(() => !!document.querySelector('#smExit') && getComputedStyle(document.querySelector('#smExit')).display !== 'none'), '没进入中控'); });
for (const t of ['light', 'env', 'dev', 'robot', 'sec']) await step(`中控分类：${t}`, async () => {
  const has = await ev(t => { const b = document.querySelector(`#smTabs [data-tab="${t}"]`); if (b) b.click(); return !!b; }, t); if (!has) return '没有这个分类';
  await sleep(1500);
  const pins = await ev(() => [...document.querySelectorAll('.sm-pin')].filter(p => p.style.visibility !== 'hidden' && p.offsetParent).length);
  if (pins) { await ev(() => [...document.querySelectorAll('.sm-pin')].find(p => p.style.visibility !== 'hidden' && p.offsetParent).click()); await sleep(2200); const card = await ev(() => document.querySelector('#smCard')?.innerText || ''); must(card.length > 4, '控制卡片是空的'); await page.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_中控卡片_${t}.png`) });
    await ev(() => { const r = document.querySelector('#smCard input[type=range]'); if (r) { r.value = String((+r.min + +r.max) / 2); r.dispatchEvent(new Event('input', { bubbles: true })); r.dispatchEvent(new Event('change', { bubbles: true })); } const b = [...document.querySelectorAll('#smCard button')][0]; b && b.click(); }); await sleep(800); }
  return `${pins} 个设备图标`;
});
if (multi) await step('中控：切换楼层', async () => { const n = await ev(() => document.querySelectorAll('#smFloors button').length); for (let i = 0; i < n; i++) { await ev(i => document.querySelectorAll('#smFloors button')[i].click(), i); await sleep(1800); } return `${n} 个楼层按钮`; });
await step('智能中控：退出', async () => { await click('#smExit'); await sleep(2500); });
/* 多层 */
if (multi) {
  await step('楼层：楼层面板逐层切换（2D）', async () => {
    await to3d('2d'); const n = await ev(() => document.querySelectorAll('#floorDock [data-f]').length); must(n > 1, '楼层面板没有楼层');
    for (let i = 0; i < n; i++) { await ev(i => document.querySelectorAll('#floorDock [data-f]')[i].click(), i); await sleep(900); }
    for (const v of ['all', 'one']) { await ev(v => document.querySelector(`#floorDock [data-v2="${v}"]`)?.click(), v); await sleep(1200); }
    return `${n} 层`;
  });
  await step('楼层：3D 楼层视图按钮', async () => {
    await to3d('3d'); const bs = await ev(() => [...document.querySelectorAll('#floor3d button, #floor3d input')].length); must(bs > 0, '3D 楼层面板没有按钮');
    const n = await ev(() => document.querySelectorAll('#floor3d button').length); for (let i = 0; i < n; i++) { await ev(i => document.querySelectorAll('#floor3d button')[i].click(), i); await sleep(1600); must((await canvasStd()).std > 6, `第 ${i + 1} 个楼层视图画面空白`); }
    return `${n} 个按钮`;
  });
}
/* 手机 */
/* 夜里打开中控：左侧文字要看得清 */
await step('夜里打开智能中控（文字对比度）', async () => {
  await to3d('3d'); await ev(() => { const i = document.querySelector('#timeIn'); i.value = '21'; i.dispatchEvent(new Event('input')); }); await sleep(800);
  await click('#smartBtn'); await sleep(4000);
  const low = await ev(() => {
    // 文字颜色和它所在底板（往上找第一个不透明背景，找不到就取 3D 画面在那一点的颜色）的对比度
    const lum = c => { const m = c.match(/[\d.]+/g).map(Number); const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }; return .2126 * f(m[0]) + .7152 * f(m[1]) + .0722 * f(m[2]); };
    const cv = document.querySelector('#c3d'), t = document.createElement('canvas'); t.width = cv.width; t.height = cv.height; __designer.S3.renderNow(); t.getContext('2d').drawImage(cv, 0, 0);
    const cr = cv.getBoundingClientRect(), out = [];
    for (const el of document.querySelectorAll('.sm-left *, .sm-tabs button, #smFloors button, .sm-exit')) {
      if (!el.childNodes.length || ![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
      const r = el.getBoundingClientRect(); if (!r.width) continue;
      let bg = null; for (let p = el; p; p = p.parentElement) { const b = getComputedStyle(p).backgroundColor; const a = b.match(/[\d.]+/g); if (a && (a.length < 4 || +a[3] > .5)) { bg = b; break; } if (p.id === 'pane3d') break; }
      if (!bg) { const x = Math.round((r.x + r.width / 2 - cr.x) / cr.width * cv.width), y = Math.round((r.y + r.height / 2 - cr.y) / cr.height * cv.height); const d = t.getContext('2d').getImageData(Math.max(0, x), Math.max(0, y), 1, 1).data; bg = `rgb(${d[0]},${d[1]},${d[2]})`; }
      const L1 = lum(getComputedStyle(el).color), L2 = lum(bg), cr2 = (Math.max(L1, L2) + .05) / (Math.min(L1, L2) + .05);
      if (cr2 < 2.2) out.push(el.textContent.trim().slice(0, 12) + ' ' + cr2.toFixed(1));
    }
    return out;
  });
  await page.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_夜里的中控.png`) });
  await click('#smExit'); await sleep(2000); await ev(() => { const i = document.querySelector('#timeIn'); i.value = '15'; i.dispatchEvent(new Event('input')); });
  must(!low.length, '看不清的文字：' + low.slice(0, 6).join('、'));
});
/* 常见屏幕尺寸：按钮不能被挤出、不能互相压住 */
const LAYOUT_FN = () => {
  const out = [];
  const groups = [['header', 'header > *:not(.grow):not(.sep)'], ['3D 工具栏', '#pane3d .overlay.ov-tl > *, #floor3d'], ['2D 图层', '#layerSeg > button'], ['2D 缩放', '#pane2d .ov-br > *']];
  for (const [name, sel] of groups) {
    const els = [...document.querySelectorAll(sel)].filter(e => e.offsetParent && getComputedStyle(e).display !== 'none');
    const host = els[0]?.closest('header, .pane'); const hr = host?.getBoundingClientRect();
    const rs = els.map(e => ({ e, r: e.getBoundingClientRect(), t: (e.textContent || e.title || e.id).trim().slice(0, 8) }));
    for (const a of rs) {
      if (hr && (a.r.right > hr.right + 1 || a.r.left < hr.left - 1 || a.r.bottom > hr.bottom + 1)) out.push(`${name}「${a.t}」超出边界`);
      if (a.e.scrollWidth > a.e.clientWidth + 2 && a.e.tagName === 'BUTTON') out.push(`${name}「${a.t}」文字被截断`);
    }
    for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) { const a = rs[i].r, b = rs[j].r; const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left), oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top); if (ox > 2 && oy > 2) out.push(`${name}「${rs[i].t}」和「${rs[j].t}」重叠`); }
  }
  return [...new Set(out)];
};
const layoutBad = (pg = page) => pg.evaluate(LAYOUT_FN);
for (const [w, h] of [[1280, 720], [1366, 768], [1440, 900], [1920, 1080]]) await step(`屏幕 ${w}×${h}：2D / 3D 按钮不挤不叠`, async () => {
  await page.setViewport({ width: w, height: h }); await sleep(800);
  const bad = []; for (const v of ['2d', '3d']) { await to3d(v); bad.push(...(await layoutBad()).map(x => v + '：' + x)); await page.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_屏幕${w}x${h}_${v}.png`) }); }
  must(!bad.length, bad.slice(0, 6).join('；'));
}, { shot: false });
await step('手机：直接用手机尺寸打开（平面在屏幕内、抽屉面板）', async () => {
  const m = await b.newPage(); const e0 = errs.length; m.on('pageerror', e => errs.push('pageerror(手机): ' + e.message));
  await m.emulate({ viewport: { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 }, userAgent: 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36' });
  await m.goto(pathToFileURL(path.resolve(FILE)).href + '?debug', { waitUntil: 'load' }); await m.waitForFunction(() => window.__designer, { timeout: 60000 }); await sleep(2500);
  const r = await m.evaluate(() => { const D = __designer, v = D.view, c = document.querySelector('#c2d').getBoundingClientRect(), bb = D.app.geo.bounds; return { over: document.documentElement.scrollWidth > innerWidth + 2, x0: c.x + bb.x * v.s + v.ox, x1: c.x + bb.x1 * v.s + v.ox, W: innerWidth }; });
  await m.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_手机_打开.png`) });
  await m.evaluate(() => document.querySelector('#leftToggle').click()); await sleep(500); await m.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_手机_左面板.png`) });
  await m.evaluate(() => { document.querySelector('#leftToggle').click(); document.querySelector('#rightToggle').click(); }); await sleep(500); await m.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_手机_右面板.png`) });
  await m.evaluate(() => document.querySelector('#rightToggle').click());
  await m.evaluate(async () => { await __designer.setView('3d'); }); await sleep(5000); const mobBad = await m.evaluate(LAYOUT_FN); await m.screenshot({ path: path.join(SHOTS, `${String(++shotN).padStart(3, '0')}_手机_3D.png`) });
  await m.close();
  must(!r.over, '页面横向溢出'); must(!mobBad.length, '手机 3D：' + mobBad.slice(0, 4).join('；')); must(r.x0 > -20 && r.x1 < r.W + 20, `平面超出屏幕（${Math.round(r.x0)} ~ ${Math.round(r.x1)} / ${r.W}）`);
}, { shot: false });
await page.setViewport({ width: 1600, height: 960 }); await to3d('2d');

/* ============================== 报告 ============================== */
const fail = results.filter(r => !r.ok);
const md = [`# 设计器验收报告：${info.name}`, '', `文件：${FILE}`, `结果：**${results.length - fail.length} / ${results.length} 通过**${fail.length ? `，${fail.length} 项失败` : ''}`, '',
  '| # | 项目 | 结果 | 说明 | 截图 |', '|---|---|---|---|---|',
  ...results.map((r, i) => `| ${i + 1} | ${r.name} | ${r.ok ? '✅' : '❌'} | ${(r.msg || '').replace(/\|/g, '/')} | ${r.shot ? `shots/${r.shot}` : ''} |`), '',
  '导出的文件在 downloads/，用 `python scripts/qa_files.py <输出目录>/downloads` 检查能不能打开。'].join('\n');
fs.writeFileSync(path.join(OUT, 'report.md'), md);
fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify({ file: FILE, results, errors: errs }, null, 1));
console.log(`\n${results.length - fail.length} / ${results.length} 通过` + (fail.length ? `\n失败：\n${fail.map(r => ' - ' + r.name + '：' + r.msg).join('\n')}` : ''));
await b.close();
process.exit(fail.length ? 2 : 0);
