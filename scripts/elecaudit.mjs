// 水电点位按家装行业常规逐房间审计：灯、开关、插座、关联关系、安装高度、门边位置
// 用法：node scripts/elecaudit.mjs <设计器.html> [--auto]     --auto = 先“一键布置水电”再审（检查自动布置的质量）
// 输出：每条问题一行 + JSON 汇总（problems 必须为空才算布置到位）
import { launch } from './browser.mjs';
import path from 'path';
const [, , file, ...flags] = process.argv;
if (!file) { console.log('用法：node elecaudit.mjs <设计器.html> [--auto]'); process.exit(1); }
const url = (/^https?:/.test(file) ? file : 'file:///' + path.resolve(file).replace(/\\/g, '/')) + (file.includes('?') ? '&' : '?') + 'debug';
const b = await launch({ gpu: false, headless: 'new', viewport: { width: 1400, height: 900 } });
const p = await b.newPage();
await p.goto(url, { waitUntil: 'load' }); await p.waitForFunction(() => window.__designer, { timeout: 30000 }); await new Promise(r => setTimeout(r, 1200));
const out = await p.evaluate(async auto => {
  const D = window.__designer, A = D.app; localStorage.clear();
  if (auto) { const btn = document.querySelector('#leftPanel .tabs [data-tab="mep"]'); btn && btn.click(); await new Promise(r => setTimeout(r, 300)); window.confirm = () => true; document.querySelector('#autoElec')?.click(); await new Promise(r => setTimeout(r, 600)); document.querySelector('.modal .btn.primary')?.click(); await new Promise(r => setTimeout(r, 800)); }
  const P = A.plan, R = A.rooms, E = P.elec;
  const regAt = q => { const i = Math.floor((q.x - R.x0) / R.c), j = Math.floor((q.y - R.y0) / R.c); if (i < 0 || j < 0 || i >= R.cols || j >= R.rows) return null; const k = R.grid[j * R.cols + i]; return R.regions.find(r => r.idx === k) || null; };
  const near = (e, r) => { if (regAt(e) === r) return true; for (const [dx, dy] of [[150, 0], [-150, 0], [0, 150], [0, -150]]) if (regAt({ x: e.x + dx, y: e.y + dy }) === r) return true; return false; };
  const LIGHT = ['light', 'pendant', 'downlight', 'spot', 'wallLamp', 'strip', 'track', 'linear'], SW = ['switch1', 'switch2', 'switch3', 'dimmer'];
  const SOCK = ['socket', 'socketUSB', 'socketW', 'socket16', 'socketAC', 'socketHood', 'socketFloor', 'socketEV'];
  const problems = [], notes = [], rooms = [];
  const name = r => r.labels.map(l => l.name).join(' + ') || '（未命名）';
  const kind = n => /卫|浴|厕|马桶|淋浴/.test(n) ? 'bath' : /备餐|西厨|水吧/.test(n) ? 'pantry' : /厨/.test(n) && !/过道|走廊|通道/.test(n) ? 'kitchen' : /主卧|次卧|卧室|客卧|老人房|儿童房|保姆房|卧/.test(n) ? 'bed' : /客厅|起居/.test(n) ? 'living' : /餐/.test(n) ? 'dining' : /书房|茶室|工作/.test(n) ? 'study' : /阳台|露台|庭院|花园/.test(n) ? 'balcony' : /玄关|门厅|走廊|过道|过厅/.test(n) ? 'hall' : /衣帽|储藏|储物|杂物/.test(n) ? 'store' : /井|空调位|设备/.test(n) ? 'skip' : 'other';
  const linkedBy = id => E.filter(s => SW.includes(s.kind) && s.links?.includes(id));
  // 门：每个房间的门洞（门边开关位置判断）
  const doors = []; for (const g of A.geo.active) for (const q of g.ops) if (['door', 'double', 'unequal', 'sliding', 'folding', 'pocket', 'hole'].includes(q.o.type)) doors.push({ g, q });
  for (const r of R.regions) {
    if (r.area < 1.5 || !r.labels.length) continue;
    const n = name(r), k = r.labels.map(l => kind(l.name)).find(x => x !== 'other') || 'other'; if (k === 'skip') continue;
    const ins = E.filter(e => regAt(e) === r), lights = ins.filter(e => LIGHT.includes(e.kind)), lid = new Set(lights.map(l => l.id));
    // 控制这个房间灯的开关（卫生间、阳台的开关常装在门外）+ 房间里的开关
    const sws = E.filter(e => SW.includes(e.kind) && (near(e, r) || e.links?.some(id => lid.has(id)))), socks = ins.filter(e => SOCK.includes(e.kind));
    const has = t => ins.some(e => t.includes(e.kind)), cnt = t => ins.filter(e => t.includes(e.kind)).length;
    const fur = P.furniture.filter(f => regAt(f) === r), hasF = re => fur.some(f => re.test(f.type));
    const add = (m) => problems.push(`${n}：${m}`);
    rooms.push({ n, k, area: +r.area.toFixed(1), lights: lights.length, switches: sws.length, sockets: socks.length });
    if (k !== 'store' || r.area >= 3) if (!lights.length) add('没有灯');
    for (const l of lights) if (!linkedBy(l.id).length) add(`${D.CAT ? '' : ''}${l.kind === 'strip' ? '灯带' : '灯'}（${Math.round(l.x)}, ${Math.round(l.y)}）没有开关控制`);
    if (lights.length && !sws.length) add('有灯但房间里 / 门口没有开关');
    // 开关控制的灯应在本房间或相邻房间（不能跨半套房）
    for (const s of sws) for (const id of s.links || []) { const l = E.find(e => e.id === id); if (l && regAt(l) !== regAt(s) && !near(s, regAt(l)) && Math.hypot(l.x - s.x, l.y - s.y) > 8000) add(`开关（${Math.round(s.x)}, ${Math.round(s.y)}）控制的灯离它 ${(Math.hypot(l.x - s.x, l.y - s.y) / 1000).toFixed(1)}m，跨房间太远`); }
    for (const s of sws) if (!(s.links || []).length) add(`开关（${Math.round(s.x)}, ${Math.round(s.y)}）没关联任何灯`);
    // 安装高度（GB 50327 / 家装常规）
    for (const e of ins) {
      if (SW.includes(e.kind) && (e.h < 1100 || e.h > 1450) && !(k === 'bed' && e.h >= 650 && e.h <= 1000)) add(`开关离地 ${e.h}（常规 1300，床头双控 700~900）`);
      if (['socket', 'socketUSB'].includes(e.kind) && e.h > 0 && e.h < 200) add(`插座离地 ${e.h}，低于 200（易受潮、踢到）`);
      if (k === 'bath' && ['socket', 'socketUSB'].includes(e.kind)) add(`卫生间用了非防水插座（${e.kind}），应换防水 / 带防溅盒`);
      if (k === 'bath' && e.kind === 'socket16') notes.push(`${n}：16A 插座（热水器）在卫生间，要加防溅盒、装在 1.8m 以上`);
      if (e.kind === 'socketAC' && (e.h < 1800 || e.h > 2400)) add(`挂机空调插座离地 ${e.h}（常规 2000~2200）`);
    }
    // 门边开关：门锁一侧，离门框 ≤ 600，开关不在门扇扫过的范围里（门开着挡住开关）
    const myDoors = doors.filter(({ g, q }) => { const mid = q.s0 + (q.s1 - q.s0) / 2; for (const sd of [1, -1]) { const pt = { x: g.a.x + g.u.x * mid + g.n.x * sd * (g.ht + 200), y: g.a.y + g.u.y * mid + g.n.y * sd * (g.ht + 200) }; if (regAt(pt) === r) return true; } return false; });
    if (lights.length && myDoors.length && sws.length) {
      for (const { g, q } of myDoors) {
        const ws = sws.filter(s => { const dx = s.x - g.a.x, dy = s.y - g.a.y, al = dx * g.u.x + dy * g.u.y, off = Math.abs(dx * g.n.x + dy * g.n.y); return off < 600 && al > q.s0 - 700 && al < q.s1 + 700; });
        if (!ws.length) {
          const real = myDoors.filter(d => d.q.o.type !== 'hole');
          // 入户门、只有一扇门的房间：门边必须有开关（进门顺手开灯）；有几扇门的房间只要主门有就行
          if (q.o.entry || (real.length === 1 && q.o.type !== 'hole' && ['bed', 'study', 'kitchen', 'hall', 'living', 'dining', 'other'].includes(k))) add(`${q.o.entry ? '入户门' : '门'}旁 700mm 内没有开关（进门顺手开不了灯）`);
          else if (q.o.type !== 'hole' && myDoors.length <= 2) notes.push(`${n}：门（${q.o.type}）旁 700mm 内没有开关`);
          continue;
        }
        if (['door', 'unequal'].includes(q.o.type)) for (const s of ws) {
          const dx = s.x - g.a.x, dy = s.y - g.a.y, al = dx * g.u.x + dy * g.u.y, hingeAt = q.o.hinge ? q.s1 : q.s0, onHinge = Math.abs(al - hingeAt) < Math.abs(al - (q.o.hinge ? q.s0 : q.s1));
          const side = Math.sign(dx * g.n.x + dy * g.n.y), swingSide = q.o.side, onWall = al > g.endA - 20 && al < g.len - g.endB + 20, leafD = (al - hingeAt) * (q.o.hinge ? 1 : -1);
          if (onWall && onHinge && side === swingSide && leafD < q.s1 - q.s0 + 150) add(`开关在门轴一侧、门扇打开时被挡住（应在门把手一侧，离门框 150~200）`);
        }
      }
    }
    // 各功能房间的标配点位
    if (k === 'bed') {
      const bed = fur.find(f => /bed/i.test(f.type) && f.type !== 'bedBench'), dbl = !!bed && bed.w >= 1350;
      if (!E.some(e => e.kind === 'switch2' && regAt(e) === r)) (dbl && r.area >= 8 ? add : (m => notes.push(`${n}：${m}`)))('卧室没有双控（门口 + 床头）');
      if (bed && E.filter(e => SOCK.includes(e.kind) && regAt(e) === r && Math.hypot(e.x - bed.x, e.y - bed.y) < Math.max(bed.w, bed.d) * .9).length < (dbl ? 2 : 1)) add(dbl ? '双人床两侧插座不足 2 个' : '床边没有插座');
      if (!has(['socketAC', 'socket16'])) notes.push(`${n}：没有空调插座（不装空调 / 中央空调可忽略）`);
    }
    if (k === 'living') { if (cnt(['tv']) < 1 && !hasF(/wallTV|tvCabinet|projScreen/)) notes.push(`${n}：没有电视位`); if (cnt(SOCK) < 4) add(`插座只有 ${cnt(SOCK)} 个（客厅常规 ≥ 6：电视墙 4 + 沙发两侧）`); }
    if (k === 'kitchen') {
      if (!has(['socketHood'])) add('没有烟机插座'); if (!has(['smoke'])) add('没有燃气 / 烟雾报警');
      if (cnt(['socket', 'socketW', 'socket16', 'socketUSB']) < 3) add(`台面 + 冰箱插座只有 ${cnt(['socket', 'socketW', 'socket16', 'socketUSB'])} 个（常规 ≥ 4）`);
    }
    if (k === 'pantry' && cnt(SOCK) < 2) add(`备餐间插座只有 ${cnt(SOCK)} 个（台面电器至少 2 个）`);
    if (k === 'bath') { if (!has(['socketW'])) add('没有防水插座（吹风机、智能马桶）'); if (fur.some(f => f.type === 'toilet') && !has(['cold'])) add('马桶没有冷水点'); }
    if (k === 'balcony' && fur.some(f => f.type === 'washer') && !has(['socketW'])) add('洗衣机旁没有防水插座');
  }
  // 全屋
  if (!E.some(e => e.kind === 'panel')) problems.push('全屋：没有强电箱'); if (!E.some(e => e.kind === 'weak')) problems.push('全屋：没有弱电箱');
  const strips = E.filter(e => e.pts?.length); for (const s of strips) if (!linkedBy(s.id).length) problems.push(`灯带 / 轨道（${Math.round(s.x)}, ${Math.round(s.y)}）没有开关控制`);
  const iss = D.runChecks().issues.filter(i => i.level !== 'info').map(i => i.msg);
  return { problems: [...new Set(problems)], notes: [...new Set(notes)], rooms, checkIssues: iss, total: { points: E.length, lights: E.filter(e => LIGHT.includes(e.kind)).length, switches: E.filter(e => SW.includes(e.kind)).length } };
}, flags.includes('--auto'));
for (const m of out.problems) console.log('✗ ' + m);
for (const m of out.notes) console.log('· ' + m);
console.log(JSON.stringify({ total: out.total, problems: out.problems.length, notes: out.notes.length, checkIssues: out.checkIssues, rooms: out.rooms }, null, 1));
await b.close();
