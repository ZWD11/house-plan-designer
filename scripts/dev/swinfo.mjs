// 第一个关联了灯的开关：它在哪个房间、它的灯在哪个房间
import puppeteer from 'puppeteer-core';
import { pathToFileURL } from 'url';
const [, , FILE] = process.argv;
const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new', args: ['--use-angle=d3d11', '--enable-gpu'] });
const page = await b.newPage();
await page.goto(pathToFileURL(FILE).href + '?debug'); await page.waitForFunction(() => window.__designer, { timeout: 60000 });
console.log(JSON.stringify(await page.evaluate(() => {
  const D = __designer, P = D.app.plan, R = D.app.rooms.regions;
  const inPoly = (p, poly) => { let c = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) { const a = poly[i], b2 = poly[j]; if ((a.y > p.y) !== (b2.y > p.y) && p.x < (b2.x - a.x) * (p.y - a.y) / (b2.y - a.y) + a.x) c = !c; } return c; };
  const roomOf = p => { const r = R.find(r => (r.polys || [r.poly]).some(q => q && inPoly(p, q))); return r ? (r.labels[0]?.name || '?') : null; };
  const s = P.elec.find(e => /^switch|dimmer/.test(e.kind) && e.links?.some(l => P.elec.some(q => q.id === l)) && R.some(r => r.area > 4 && r.labels.length));
  return { sw: { x: s.x, y: s.y, kind: s.kind, room: roomOf(s) }, lamps: s.links.map(l => { const e = P.elec.find(q => q.id === l); return e && { kind: e.kind, x: e.x, y: e.y, room: roomOf(e) }; }), keys: Object.keys(R[0]) };
}), null, 1));
await b.close();
