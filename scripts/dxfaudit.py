"""布置图 DXF 的精确取数 + 逐项对账（2E 路线用）。坐标系和 dxfinventory 一样：输出 = (x − X0, Y1 − y)，mm，y 朝下。

  python dxfaudit.py blocks 图.dxf --box X0 Y0 X1 Y1 --out 工作目录   # 家具块展开到叶子块（一把椅子 / 一张桌子）→ deep_blocks.json + deep-*.png
  python dxfaudit.py cache  图.dxf --box X0 Y0 X1 Y1 --out 工作目录   # 所有线段（块里的、多段线拆开的、弧线折线化）→ segs.npz
  python dxfaudit.py q      工作目录 X Y R [图层关键字]               # 列出 (X, Y) 半径 R 内的线段：取墙面、柜子外框、门扇的精确坐标
  python dxfaudit.py walls  工作目录      # spec 每面墙的两个墙面 ↔ 原图墙面线（Q_ / P_07 / A-WALL / P_22），±40mm、覆盖 ≥ 50%
  python dxfaudit.py doors  工作目录      # 门图层（含“门”/ DOOR）每个图形 ↔ spec 门洞；不管弧是 ARC、椭圆、凸度还是折线
  python dxfaudit.py dims   图.dxf --box X0 Y0 X1 Y1 --out 工作目录   # 两头都落在原图墙线上的尺寸标注 ↔ 模型墙面 / 洞口边（标注是用户拿来对数的）
  python dxfaudit.py furn   工作目录      # 家具类图层（P_01 活动家具 / P_02 落地到顶 / P_03 洁具电器 / P_09 悬空到顶 / J- / I-FURN）↔ spec 家具外框

工作目录里要有 spec.json（walls / doors / furn）和 segs.npz（先跑 cache）。对账结果写 audit_*.json，终端打印没对上的条目：
  - walls 的 spec_walls_unmatched：模型墙面附近原图没有墙线 → 墙放偏了 / 厚度错了 / 原图根本没墙（外圈玻璃幕墙整段是洞口，属正常）
  - doors 的 MISS：原图画了门、模型这里没门洞（常见：门画在“设备 / 家具”图层、弧是折线拟合的）；EXTRA：模型有门、原图没画（电梯层门、感应门画在别的层，逐个看）
  - furn 的 MISS：原图有图形、没有任何模型家具压着（漏了）；FAKE：模型落地家具框里一根原图线都没有（编的、或放偏了）
图层关键字按天正 / 常见装修公司图层命名，别的图可以改下面几个元组。"""
import argparse, collections, json, math, sys
from pathlib import Path
import numpy as np

WALL_LAYERS = ('P_07', 'Q_01', 'Q_06', 'A-WALL', 'P_22', '中粗')
FURN_LAYERS = ('P_01', 'P_02', 'P_03', 'P_09', 'J-', 'I-FURN')
BLOCK_SKIP = ('天花', '灯具', '地材', '文字', '填充', '标注', '尺寸', '轴', '墙', '门', '窗', '空调', '地漏', 'DIM', 'AXIS')
SKIP_KEYS = ('supplyVent', 'returnVent', 'wifiAP', 'ceilingSpeaker', 'freeExtrude', 'elevator', 'stairRun', 'curtain')


def load_dxf(path):
    import ezdxf
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dxf_prepare import flatten, repair_text
    return ezdxf.readfile(path), flatten, repair_text


def cmd_blocks(a):
    from ezdxf import bbox, disassemble
    from ezdxf.path import make_path
    from PIL import Image, ImageDraw
    doc, _, repair_text = load_dxf(a.dxf); X0, Y0, X1, Y1 = a.box; out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    tx = lambda x: x - X0; ty = lambda y: Y1 - y

    def ext(e):
        try:
            b = bbox.extents([e], fast=True)
            return (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y) if b.has_data else None
        except Exception: return None
    leaves = []

    def walk(e, layer, depth, path):
        b = ext(e)
        if not b: return
        w, h = b[2] - b[0], b[3] - b[1]
        sub = [v for v in e.virtual_entities() if v.dxftype() == 'INSERT']
        # 子块里有家具大小的（> 150mm）就往下展开；否则这一层就是叶子
        big = [v for v in sub if (lambda bb: bb and max(bb[2] - bb[0], bb[3] - bb[1]) > 150)(ext(v))]
        if big and depth < 8 and max(w, h) > 900:
            for v in big: walk(v, repair_text(v.dxf.layer) if v.dxf.layer != '0' else layer, depth + 1, path + [repair_text(e.dxf.name)])
            return
        ins = e.dxf.insert
        leaves.append(dict(name=repair_text(e.dxf.name), layer=layer, x=round(tx(ins.x), 1), y=round(ty(ins.y), 1), rot=round(e.dxf.rotation % 360, 2),
                           sx=round(e.dxf.xscale, 3), sy=round(e.dxf.yscale, 3), box=[round(tx(b[0]), 1), round(ty(b[3]), 1), round(tx(b[2]), 1), round(ty(b[1]), 1)],
                           size=[round(w), round(h)], cx=round(tx((b[0] + b[2]) / 2), 1), cy=round(ty((b[1] + b[3]) / 2), 1), depth=depth, parent='/'.join(path)))
    for e in doc.modelspace().query('INSERT'):
        layer = repair_text(e.dxf.layer)
        if any(k in layer for k in BLOCK_SKIP): continue
        b = ext(e)
        if b and X0 < (b[0] + b[2]) / 2 < X1 and Y0 < (b[1] + b[3]) / 2 < Y1: walk(e, layer, 0, [])
    (out / 'deep_blocks.json').write_text(json.dumps(leaves, ensure_ascii=False, indent=1), encoding='utf-8')
    by = collections.defaultdict(list)
    for l in leaves: by[l['name']].append(l)
    thumbs = []
    for name, L in sorted(by.items(), key=lambda kv: -len(kv[1])):
        blk = doc.blocks.get([b.name for b in doc.blocks if repair_text(b.name) == name][0])
        pts = []
        for v in disassemble.recursive_decompose(blk):
            try: pts.append([(p.x, p.y) for p in make_path(v).flattening(3)])
            except Exception: pass
        flat = [p for s in pts for p in s]
        if not flat: continue
        x0, y0 = min(p[0] for p in flat), min(p[1] for p in flat); x1, y1 = max(p[0] for p in flat), max(p[1] for p in flat)
        sc = min(200 / max(x1 - x0, 1), 160 / max(y1 - y0, 1))
        im = Image.new('RGB', (260, 240), 'white'); d = ImageDraw.Draw(im)
        for s in pts:
            if len(s) > 1: d.line([((x - x0) * sc + 30, (y1 - y) * sc + 20) for x, y in s], fill='#222', width=1)
        d.text((4, 200), f'{len(L)}x {name[:24]}', fill='blue'); d.text((4, 216), f'{round(x1 - x0)}x{round(y1 - y0)} local, +y up', fill='black')
        thumbs.append(im)
    for s in range(0, len(thumbs), 40):
        sh = Image.new('RGB', (260 * 8, 240 * 5), '#bbb')
        for j, im in enumerate(thumbs[s:s + 40]): sh.paste(im, ((j % 8) * 260, (j // 8) * 240))
        sh.save(out / f'deep-{s // 40}.png')
    print(len(leaves), 'leaf blocks;', [(n, len(L)) for n, L in sorted(by.items(), key=lambda kv: -len(kv[1]))][:30])


def cmd_cache(a):
    from ezdxf.path import make_path
    doc, flatten, _ = load_dxf(a.dxf); X0, Y0, X1, Y1 = a.box; out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    segs, lays = [], []
    for e, layer in flatten(doc.modelspace()):
        if e.dxftype() in ('TEXT', 'MTEXT', 'ATTRIB', 'HATCH', 'DIMENSION', 'INSERT'): continue
        try: pts = [(p.x - X0, Y1 - p.y) for p in make_path(e).flattening(5)]
        except Exception: continue
        if not pts or not any(-500 < x < X1 - X0 + 500 and -500 < y < Y1 - Y0 + 500 for x, y in pts): continue
        for (p, q), (c, d) in zip(pts, pts[1:]):
            if math.hypot(c - p, d - q) > .5: segs.append((p, q, c, d)); lays.append(layer)
    np.savez(out / 'segs.npz', s=np.array(segs), layer=np.array(lays, dtype=object))
    print(len(segs), 'segments cached')


def segs(work):
    d = np.load(Path(work) / 'segs.npz', allow_pickle=True); return d['s'], d['layer']


def spec(work):
    S = json.loads((Path(work) / 'spec.json').read_text(encoding='utf-8'))
    return S['floors'][0] if 'floors' in S else S


def cmd_q(a):
    S, L = segs(a.work); x, y, r = a.x, a.y, a.r
    ax, ay, bx, by = S.T; dx, dy = bx - ax, by - ay
    t = np.clip(((x - ax) * dx + (y - ay) * dy) / np.maximum(dx * dx + dy * dy, 1e-9), 0, 1)
    idx = np.where(np.hypot(ax + t * dx - x, ay + t * dy - y) < r)[0]
    rows = sorted(((L[i], round(ax[i], 1), round(ay[i], 1), round(bx[i], 1), round(by[i], 1), round(math.hypot(dx[i], dy[i]))) for i in idx if a.layer in L[i]), key=lambda v: (v[0], v[1], v[2]))
    for rw in rows[:300]: print(*rw)
    print(len(rows), 'segments')


def cover(lines, lo, hi, pos, tol):
    iv = sorted((max(lo, p), min(hi, q)) for p, q, c, _ in lines if abs(c - pos) < tol and min(hi, q) > max(lo, p))
    tot, cur = 0, None
    for p, q in iv:
        if cur is None or p > cur[1]:
            if cur: tot += cur[1] - cur[0]
            cur = [p, q]
        else: cur[1] = max(cur[1], q)
    return tot + (cur[1] - cur[0] if cur else 0)


def cmd_walls(a):
    SG, LY = segs(a.work); S = spec(a.work); TOL = 40
    keep = np.array([any(k in l for k in WALL_LAYERS) and '填充' not in l for l in LY]); G = SG[keep]; GL = LY[keep]
    H = [(min(p, c), max(p, c), (q + d) / 2, l) for (p, q, c, d), l in zip(G, GL) if abs(q - d) < 2 and abs(c - p) > 150]
    V = [(min(q, d), max(q, d), (p + c) / 2, l) for (p, q, c, d), l in zip(G, GL) if abs(p - c) < 2 and abs(d - q) > 150]
    bad = []
    for i, w in enumerate(S['walls']):
        (ax, ay), (bx, by) = w['a'], w['b']; t = w['t']; h = abs(ay - by) < 1
        if not h and abs(ax - bx) > 1: continue
        lo, hi = (min(ax, bx), max(ax, bx)) if h else (min(ay, by), max(ay, by)); pos = ay if h else ax
        if hi - lo < 300: continue
        span = [(lo + 60, hi - 60)]  # 两头交接处原图线常断开；洞口那段不要求有线
        for o in w.get('openings', []): span = [s for p, q in span for s in ((p, min(q, o['from'])), (max(p, o['to']), q)) if s[1] - s[0] > 50]
        need = sum(q - p for p, q in span) or 1; off = 0
        if w.get('flush'):  # 薄墙贴齐同一直线上厚墙的那一侧
            T = max([q['t'] for q in S['walls'] if q is not w and ((abs(q['a'][1] - q['b'][1]) < 1) == h) and abs((q['a'][1] if h else q['a'][0]) - pos) < 1] + [t])
            off = {'N': -1, 'W': -1, 'S': 1, 'E': 1}[w['flush']] * (T - t) / 2
        res = [sum(cover(H if h else V, p, q, pos + off + sd * t / 2, TOL) for p, q in span) / need for sd in (-1, 1)]
        if min(res) < .5: bad.append({'i': i, 'a': w['a'], 'b': w['b'], 't': t, 'faces_covered': [round(r, 2) for r in res]})
    (Path(a.work) / 'audit_walls.json').write_text(json.dumps(bad, ensure_ascii=False, indent=1), encoding='utf-8')
    print(len(bad), 'spec walls with a face not on any drawing wall line (±40mm)')
    for b in bad: print('WALL', b['a'], b['b'], 't', b['t'], 'faces', b['faces_covered'])


def raster(G, k=.05, X0=-1500, Y0=-500, W=60000, Hh=60000):
    import cv2
    im = np.zeros((int(Hh * k), int(W * k)), np.uint8)
    P = lambda x, y: (int((x - X0) * k), int((y - Y0) * k))
    for p, q, c, d in G: cv2.line(im, P(p, q), P(c, d), 255, 2)
    return im, P, k, X0, Y0


def cmd_doors(a):
    import cv2
    SG, LY = segs(a.work); S = spec(a.work)
    G = SG[np.array([('门' in l or 'DOOR' in l.upper()) and '窗' not in l and '门槛' not in l for l in LY])]  # 门槛石是地面分隔条，不是门
    im, P, k, X0, Y0 = raster(G)
    n, lab, st, _ = cv2.connectedComponentsWithStats(im)
    comps = [[X0 + x / k, Y0 + y / k, X0 + (x + w) / k, Y0 + (y + h) / k] for x, y, w, h, _ in st[1:] if max(w, h) / k > 400]
    ops = []
    for w in S['walls']:
        (ax, ay), (bx, by) = w['a'], w['b']; h = abs(ay - by) < 1; t = w['t'] / 2
        for o in w.get('openings', []):
            if o['type'] in ('glassWall', 'hole') or 'indow' in o['type']: continue
            ops.append({'type': o['type'], 'name': o.get('name', ''), 'w': o['to'] - o['from'],
                        'box': [o['from'], ay - t, o['to'], ay + t] if h else [ax - t, o['from'], ax + t, o['to']]})
    hit = lambda p, q, m=150: min(p[2], q[2]) - max(p[0], q[0]) > -m and min(p[3], q[3]) - max(p[1], q[1]) > -m
    miss = [c for c in comps if not any(hit(c, o['box']) for o in ops)]
    extra = [o for o in ops if not any(hit(c, o['box']) for c in comps)]
    (Path(a.work) / 'audit_doors.json').write_text(json.dumps({'drawing_door_no_opening': miss, 'opening_no_drawing': extra}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(len(comps), 'door shapes;', len(miss), 'without a model opening;', len(extra), 'model openings without a drawn door')
    for c in miss: print('MISS', [round(v) for v in c])
    for o in extra: print('EXTRA', o['type'], [round(v) for v in o['box']], round(o['w']), o['name'])


def corners(f):
    r = math.radians(f.get('rot', 0)); c, s = math.cos(r), math.sin(r); w, d = f.get('w', 500), f.get('d', 500); x, y = f['at']
    return [(x + u * c - v * s, y + u * s + v * c) for u, v in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))]


def cmd_furn(a):
    import cv2
    SG, LY = segs(a.work); S = spec(a.work)
    G = SG[np.array([l.startswith(FURN_LAYERS) and 'DOOR' not in l.upper() for l in LY])]
    im, P, k, X0, Y0 = raster(G)
    cov = np.zeros_like(im)
    for f in S['furniture']:
        if f['key'] not in SKIP_KEYS: cv2.fillPoly(cov, [np.array([P(*p) for p in corners(f)], np.int32)], 255)
    cov = cv2.dilate(cov, np.ones((5, 5), np.uint8))  # 100mm 容差
    n, lab, st, _ = cv2.connectedComponentsWithStats(im)
    miss = []
    for i in range(1, n):
        x, y, w, h, ar = st[i]
        if ar < 15: continue
        inside = float((cov[lab == i] > 0).mean())
        if inside < .6: miss.append({'box': [round(X0 + x / k), round(Y0 + y / k), round(X0 + (x + w) / k), round(Y0 + (y + h) / k)], 'covered': round(inside, 2)})
    fake = []
    for f in S['furniture']:
        if f['key'] in SKIP_KEYS or f.get('ceil') or (f.get('z', 0) > 0 and f['key'] not in ('trainingChair', 'curveTrainingTable', 'officeChair', 'chair')): continue
        poly = np.zeros_like(im); cv2.fillPoly(poly, [np.array([P(*p) for p in corners(f)], np.int32)], 255)
        poly = cv2.erode(poly, np.ones((3, 3), np.uint8)); px = (poly > 0).sum()
        if px and ((poly > 0) & (im > 0)).sum() / px < .02: fake.append({'key': f['key'], 'name': f.get('name', ''), 'at': f['at'], 'w': f.get('w'), 'd': f.get('d')})
    (Path(a.work) / 'audit_furn.json').write_text(json.dumps({'drawing_not_modeled': miss, 'model_without_drawing': fake}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(len(miss), 'drawing shapes not covered by any furniture;', len(fake), 'floor furniture with no drawing lines under it')
    for m in miss: print('MISS', m)
    for f in fake: print('FAKE', f)


def cmd_dims(a):
    doc, _, _ = load_dxf(a.dxf); X0, Y0, X1, Y1 = a.box; work = a.out
    SG, LY = segs(work); S = spec(work)
    G = SG[np.array([l.startswith(('Q_01', 'Q_06', 'A-WALL', 'P_22', 'P_07')) for l in LY])]
    VX = [(p + c) / 2 for p, q, c, d in G if abs(p - c) < 2 and abs(d - q) > 100]; HY = [(q + d) / 2 for p, q, c, d in G if abs(q - d) < 2 and abs(c - p) > 100]
    VX, HY = np.array(VX), np.array(HY)
    MX, MY = [], []
    for w in S['walls']:
        (ax, ay), (bx, by) = w['a'], w['b']; t = w['t'] / 2; ops = [q for o in w.get('openings', []) for q in (o['from'], o['to'])]
        if abs(ay - by) < 1: MY += [ay - t, ay + t]; MX += ops + [min(ax, bx) - t, max(ax, bx) + t]
        elif abs(ax - bx) < 1: MX += [ax - t, ax + t]; MY += ops + [min(ay, by) - t, max(ay, by) + t]
    for s in S.get('structs', []):
        if 'w' in s: x, y = s['at']; MX += [x - s['w'] / 2, x + s['w'] / 2]; MY += [y - s['d'] / 2, y + s['d'] / 2]
    MX, MY = np.array(MX), np.array(MY); rows = []
    for e in doc.modelspace().query('DIMENSION'):
        try: p1, p2, mv = e.dxf.defpoint2, e.dxf.defpoint3, float(e.get_measurement())
        except Exception: continue
        pa, pb = (p1.x - X0, Y1 - p1.y), (p2.x - X0, Y1 - p2.y)
        if not (0 <= pa[0] <= X1 - X0 and 0 <= pa[1] <= Y1 - Y0): continue
        ang = getattr(e.dxf, 'angle', 0) % 180
        for hz, i, W, M in ((abs(ang) < 1, 0, VX, MX), (abs(ang - 90) < 1, 1, HY, MY)):
            if hz and len(W) and np.abs(W - pa[i]).min() < 8 and np.abs(W - pb[i]).min() < 8:
                rows.append({'dir': 'H' if i == 0 else 'V', 'a': [round(v) for v in pa], 'b': [round(v) for v in pb], 'value': round(mv), 'dev': round(float(max(np.abs(M - pa[i]).min(), np.abs(M - pb[i]).min())))})
    r = np.array([q['dev'] for q in rows]) if rows else np.zeros(0)
    (Path(work) / 'audit_dims.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    print(len(rows), 'wall-to-wall dimensions; model ends within 5mm:', int((r <= 5).sum()), ' 25mm:', int((r <= 25).sum()), ' 60mm:', int((r <= 60).sum()), ' >60:', int((r > 60).sum()))
    for q in sorted(rows, key=lambda q: -q['dev'])[:30]:
        if q['dev'] > 25: print('DIM', q)


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sp = ap.add_subparsers(dest='cmd', required=True)
for nm in ('blocks', 'cache', 'dims'):
    p = sp.add_parser(nm); p.add_argument('dxf'); p.add_argument('--box', type=float, nargs=4, required=True); p.add_argument('--out', required=True)
p = sp.add_parser('q'); p.add_argument('work'); p.add_argument('x', type=float); p.add_argument('y', type=float); p.add_argument('r', type=float); p.add_argument('layer', nargs='?', default='')
for nm in ('walls', 'doors', 'furn'): sp.add_parser(nm).add_argument('work')
a = ap.parse_args()
{'blocks': cmd_blocks, 'cache': cmd_cache, 'dims': cmd_dims, 'q': cmd_q, 'walls': cmd_walls, 'doors': cmd_doors, 'furn': cmd_furn}[a.cmd](a)
