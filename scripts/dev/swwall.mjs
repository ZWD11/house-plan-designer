import puppeteer from 'puppeteer-core';
import { pathToFileURL } from 'url';
const [, , FILE, X, Y] = process.argv;
const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new', args: ['--use-angle=d3d11', '--enable-gpu'] });
const page = await b.newPage();
await page.goto(pathToFileURL(FILE).href + '?debug'); await page.waitForFunction(() => window.__designer, { timeout: 60000 });
console.log(JSON.stringify(await page.evaluate((X, Y) => {
  const D = __designer, P = D.app.plan;
  const es = P.elec.filter(e => Math.hypot(e.x - X, e.y - Y) < 400).map(e => ({ id: e.id, kind: e.kind, x: e.x, y: e.y, rot: e.rot, h: e.h, links: e.links }));
  const ws = [...D.app.geo.active].filter(g => { const a = g.a, bb = g.b; const L = Math.hypot(bb.x - a.x, bb.y - a.y), ux = (bb.x - a.x) / L, uy = (bb.y - a.y) / L, t = (X - a.x) * ux + (Y - a.y) * uy, o = -(X - a.x) * uy + (Y - a.y) * ux; return t > -300 && t < L + 300 && Math.abs(o) < 400; })
    .map(g => ({ a: g.a, b: g.b, t: g.w.t, ops: g.ops.map(q => ({ type: q.o.type, s0: q.s0, s1: q.s1, hinge: q.o.hinge })) }));
  return { es, ws };
}, +X, +Y), null, 1));
await b.close();
