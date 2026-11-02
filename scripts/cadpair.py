"""
CAD 矢量 PDF 兜底识别：cadvec 报“没认出墙厚”、cadsplit 把一页切成两层 / 墙只认一半时用。
做法（第二次实战 AH26110 别墅手写 walls.py / cols.py 的通用版）：
  1. 按“颜色 + 线宽 + 描边 / 填充”把图元分图层（layers.json 列出每类多少条），默认取黑色描边线当墙线（--wall-color 改）；
  2. 墙 = 同方向平行墙线配对：沿每个方向每 25mm 横切一刀，切到的墙线按间距 ≤ 340mm 成组——
       2 条线 = 实墙（墙厚 = 间距，吸到常用值）、3~4 条线 = 窗 / 玻璃（墙厚范围内有细线）、1 条 = 不是墙；
     连续几刀结果一样就连成一段墙；端点吸到相交墙的中线上；
  3. 柱 = 灰色 / 黑色实心填充的近似矩形块（120~1200mm），去重（同一块常画两遍）；
  4. 一个 PDF 多页 = 多层：默认每页一层（--single 语义，不会把一页切成两层）；各页图框位置一致时共用一个原点（自动检测）。
比例：读不出尺寸数字时必须给一个：--scale mm/pt，或 --total-width（第一页墙线外包宽度对应的 mm，一般是最外道总尺寸）。

用法:
  python cadpair.py 图纸.pdf --total-width 14025 --out <工作目录>/pair
  python cadpair.py 图纸.pdf --scale 29.03 --pages 0,1,2 --names 负一层,一层,二层 --out ...
输出: building_draft.json（整栋楼 HouseSpec 初稿，单页时是普通 HouseSpec）、pair<i>.png（红 = 实墙、蓝 = 玻璃 / 窗、紫 = 柱）、
      layers.json、report.json（比例、原点、每层墙 / 玻璃 / 柱数量）
"""
import argparse, json, math, os, sys
from collections import Counter, defaultdict
sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8')
import fitz
from PIL import Image, ImageDraw

ap = argparse.ArgumentParser()
ap.add_argument('pdf')
ap.add_argument('--out', required=True)
ap.add_argument('--scale', type=float, help='mm / pt')
ap.add_argument('--total-width', type=float, help='第一页墙线外包宽度（mm）')
ap.add_argument('--pages', help='页号，逗号分隔（从 0 起），默认全部')
ap.add_argument('--names', help='每页楼层名，逗号分隔')
ap.add_argument('--wall-color', default='0,0,0', help='墙线颜色 r,g,b（0~1），默认黑色')
ap.add_argument('--col-fill', default='0.5,0.5,0.5;0,0,0', help='柱填充色，分号分隔多个')
ap.add_argument('--tmin', type=float, default=60, help='最小墙厚 mm')
ap.add_argument('--tmax', type=float, default=340, help='最大墙厚 mm')
ap.add_argument('--origin-pt', type=float, nargs=2, help='原点（pt），默认第一页墙线外包左上角')
ap.add_argument('--height', type=int, default=3000)
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)

doc = fitz.open(a.pdf)
pages = [int(p) for p in a.pages.split(',')] if a.pages else list(range(len(doc)))
names = a.names.split(',') if a.names else ([f'{i + 1}层' for i in range(len(pages))] if len(pages) > 1 else ['平面'])
WC = tuple(float(v) for v in a.wall_color.split(','))
CF = [tuple(float(v) for v in c.split(',')) for c in a.col_fill.split(';')]
near = lambda c, ref, tol=.06: c is not None and len(c) >= 3 and all(abs(c[i] - ref[i]) <= tol for i in range(3))

# ---------- 1. 图层统计 + 墙线 / 柱块提取（pt） ----------
layers_all, raw = {}, []
for pi in pages:
    cnt = Counter(); lines, blocks = [], []
    for dr in doc[pi].get_drawings():
        col = tuple(round(v, 2) for v in (dr.get('color') or ())); fill = tuple(round(v, 2) for v in (dr.get('fill') or ()))
        key = f"{dr.get('type')} 线色{col or '-'} 线宽{round(dr.get('width') or 0, 2)} 填充{fill or '-'}"
        cnt[key] += len(dr['items'])
        if dr.get('type') == 's' and near(dr.get('color'), WC):
            for it in dr['items']:
                if it[0] == 'l': lines.append((it[1].x, it[1].y, it[2].x, it[2].y))
                elif it[0] == 're':
                    r = it[1]; lines += [(r.x0, r.y0, r.x1, r.y0), (r.x0, r.y1, r.x1, r.y1), (r.x0, r.y0, r.x0, r.y1), (r.x1, r.y0, r.x1, r.y1)]
                elif it[0] == 'qu':
                    q = it[1]; pts = [q.ul, q.ur, q.lr, q.ll]
                    lines += [(pts[i].x, pts[i].y, pts[(i + 1) % 4].x, pts[(i + 1) % 4].y) for i in range(4)]
        if dr.get('fill') and any(near(dr.get('fill'), c) for c in CF):
            kinds = {it[0] for it in dr['items']}
            if kinds <= {'l', 're', 'qu'} and len(dr['items']) <= 12: blocks.append(tuple(dr['rect']))
    layers_all[names[pages.index(pi)]] = cnt.most_common(30)
    raw.append((lines, blocks))
json.dump(layers_all, open(os.path.join(a.out, 'layers.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

# ---------- 2. 比例与原点 ----------
def bbox(ls):
    xs = [v for l in ls for v in (l[0], l[2])]; ys = [v for l in ls for v in (l[1], l[3])]
    return min(xs), min(ys), max(xs), max(ys)
if not raw[0][0]: sys.exit('第一页没有找到墙线颜色的描边线：看 layers.json，用 --wall-color 指定墙线颜色')
B0 = bbox(raw[0][0])
if a.scale: S, how = a.scale, '--scale'
elif a.total_width: S, how = a.total_width / (B0[2] - B0[0]), '--total-width / 第一页墙线外包宽'
else: sys.exit('需要比例：--scale mm/pt 或 --total-width 总尺寸 mm（尺寸数字是炸开的线条时读不出来，问用户要一个总尺寸）')
# 各页图框（页面上所有图元的外包）位置一致 → 共用原点；不一致时每页用自己墙线外包的左上角
frames = [doc[pi].rect for pi in pages]
same_frame = all(abs(f.x0 - frames[0].x0) < .5 and abs(f.x1 - frames[0].x1) < .5 for f in frames)
OX, OY = a.origin_pt if a.origin_pt else (B0[0], B0[1])

# ---------- 3. 平行线配墙 ----------
STD = [60, 80, 90, 100, 120, 150, 180, 200, 220, 240, 250, 280, 300, 330]
def snap_t(t): s = min(STD, key=lambda v: abs(v - t)); return s if abs(s - t) <= 12 else round(t / 5) * 5
STEP = 25

def walls_of(lines_mm, horizontal):
    """lines_mm: [(c, lo, hi)] 横线 (y, x0, x1) / 竖线 (x, y0, y1)。返回 [(kind, c_lo, c_hi, lo, hi, n)]"""
    if not lines_mm: return []
    lo_all = min(l[1] for l in lines_mm); hi_all = max(l[2] for l in lines_mm)
    # 按沿线方向分桶，加速横切
    buckets = defaultdict(list); BK = 500
    for l in lines_mm:
        for k in range(int(l[1] // BK), int(l[2] // BK) + 1): buckets[k].append(l)
    runs = []   # 当前正在延伸的段：key (kind, c_lo, c_hi) → [lo, hi]
    open_ = {}; out = []
    p = lo_all + STEP / 2
    while p < hi_all:
        cs = sorted({round(l[0], 1) for l in buckets[int(p // BK)] if l[1] <= p <= l[2]})
        # 相距 < 15mm 的算同一条线（双描边、线宽）
        merged = []
        for c in cs:
            if merged and c - merged[-1][-1] < 15: merged[-1].append(c)
            else: merged.append([c])
        cs = [sum(m) / len(m) for m in merged]
        groups, cur = [], []
        for c in cs:
            if cur and (c - cur[-1] > a.tmax or c - cur[0] > a.tmax): groups.append(cur); cur = []
            cur.append(c)
        if cur: groups.append(cur)
        seen = set()
        for g in groups:
            if len(g) < 2 or g[-1] - g[0] < a.tmin: continue
            kind = 'wall' if len(g) == 2 else 'glass'
            key = (kind, round(g[0] / 10), round(g[-1] / 10)); seen.add(key)
            if key in open_ and p - open_[key][1] <= STEP * 1.5: open_[key][1] = p
            else:
                if key in open_: out.append((key, *open_[key]))
                open_[key] = [p - STEP / 2, p, g[0], g[-1], len(g)]
        for key in [k for k in open_ if k not in seen and p - open_[k][1] > STEP * 1.5]: out.append((key, *open_.pop(key)))
        p += STEP
    out += [(k, *v) for k, v in open_.items()]
    res = []
    for (kind, _, _), s0, s1, c0, c1, n in out:
        s1 += STEP / 2
        if s1 - s0 < 150: continue
        res.append((kind, c0, c1, s0, s1, n))
    return res

def to_mm(x, y): return ((x - OX) * S, (y - OY) * S)

floors, report = [], {'scale_mm_per_pt': round(S, 4), 'scale_from': how, 'origin_pt': [round(OX, 2), round(OY, 2)], 'shared_origin': same_frame or bool(a.origin_pt), 'floors': []}
for fi, (pi, (lines, blocks)) in enumerate(zip(pages, raw)):
    H_, V_ = [], []
    for x0, y0, x1, y1 in lines:
        (X0, Y0), (X1, Y1) = to_mm(x0, y0), to_mm(x1, y1)
        L = math.hypot(X1 - X0, Y1 - Y0)
        if L < 100: continue
        if abs(Y1 - Y0) < L * .01: H_.append(((Y0 + Y1) / 2, min(X0, X1), max(X0, X1)))
        elif abs(X1 - X0) < L * .01: V_.append(((X0 + X1) / 2, min(Y0, Y1), max(Y0, Y1)))
    bands = [('h', b) for b in walls_of(H_, True)] + [('v', b) for b in walls_of(V_, False)]
    walls = []
    for o, (kind, c0, c1, s0, s1, n) in bands:
        c = round((c0 + c1) / 2 * 2) / 2; t = snap_t(c1 - c0)
        w = {'a': [round(s0), c] if o == 'h' else [c, round(s0)], 'b': [round(s1), c] if o == 'h' else [c, round(s1)], 't': t, 'bearing': False, '_lines': n}
        if kind == 'glass': w['openings'] = [{'type': 'glassWall', 'from': round(s0), 'to': round(s1), '_why': f'墙厚内 {n} 条线（窗 / 玻璃）'}]
        walls.append(w)
    # 端点吸到垂直墙中线：墙端离某面垂直墙中线 ≤ 对方半厚 + 本墙半厚 + 30，且在对方范围内
    for w in walls:
        hor = w['a'][1] == w['b'][1]
        for end in ('a', 'b'):
            p = w[end]
            best = None
            for q in walls:
                if q is w or (q['a'][1] == q['b'][1]) == hor: continue
                qc = q['a'][0] if hor else q['a'][1]
                qlo, qhi = sorted((q['a'][1], q['b'][1]) if hor else (q['a'][0], q['b'][0]))
                pc = p[1] if hor else p[0]
                d = abs((p[0] if hor else p[1]) - qc)
                if qlo - 30 <= pc <= qhi + 30 and d <= q['t'] / 2 + w['t'] / 2 + 30 and (best is None or d < best[0]): best = (d, qc)
            if best:
                if hor: p[0] = best[1]
                else: p[1] = best[1]
    for w in walls:
        if w.get('openings'):
            # 洞口用世界坐标（水平墙 x、竖直墙 y），端点吸附后跟着墙端走
            k = 0 if w['a'][1] == w['b'][1] else 1
            w['openings'][0]['from'], w['openings'][0]['to'] = sorted((w['a'][k], w['b'][k]))
    # 柱
    cols = []
    for r in blocks:
        (x0, y0), (x1, y1) = to_mm(r[0], r[1]), to_mm(r[2], r[3])
        w_, d_ = x1 - x0, y1 - y0
        if 120 <= w_ <= 1200 and 120 <= d_ <= 1200 and max(w_, d_) / min(w_, d_) <= 4:
            c = [round((x0 + x1) / 2), round((y0 + y1) / 2)]
            if not any(abs(c[0] - q['at'][0]) < 30 and abs(c[1] - q['at'][1]) < 30 for q in cols):
                cols.append({'kind': 'column', 'at': c, 'w': round(w_), 'd': round(d_)})
    fl = {'name': names[fi], 'height': a.height, 'walls': walls, 'structs': cols, 'rooms': []}
    floors.append(fl)
    report['floors'].append({'name': names[fi], 'page': pi, 'walls': sum(1 for w in walls if not w.get('openings')), 'glass': sum(1 for w in walls if w.get('openings')), 'columns': len(cols), 'wall_lines': len(lines)})

    # 预览图：页面渲染 + 识别结果
    zoom = 2
    pix = doc[pi].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples).convert('L').convert('RGB')
    im = Image.blend(im, Image.new('RGB', im.size, (255, 255, 255)), .5); d = ImageDraw.Draw(im)
    P = lambda x, y: ((x / S + OX) * zoom, (y / S + OY) * zoom)
    for i, w in enumerate(walls):
        colr = (40, 90, 255) if w.get('openings') else (230, 30, 30)
        wpx = max(2, round(w['t'] / S * zoom))
        d.line([*P(*w['a']), *P(*w['b'])], fill=colr, width=wpx)
        m = P((w['a'][0] + w['b'][0]) / 2, (w['a'][1] + w['b'][1]) / 2); d.text((m[0] + 3, m[1] + 2), f'W{i} {w["t"]}', fill=(0, 0, 0))
    for c in cols:
        x0, y0 = P(c['at'][0] - c['w'] / 2, c['at'][1] - c['d'] / 2); x1, y1 = P(c['at'][0] + c['w'] / 2, c['at'][1] + c['d'] / 2)
        d.rectangle([x0, y0, x1, y1], outline=(170, 0, 200), width=3)
    im.save(os.path.join(a.out, f'pair{fi}.png'))

if len(floors) > 1: draft = {'name': os.path.splitext(os.path.basename(a.pdf))[0], 'slab': 150, 'floors': floors}
else: draft = {'name': os.path.splitext(os.path.basename(a.pdf))[0], **floors[0]}
json.dump(draft, open(os.path.join(a.out, 'building_draft.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
json.dump(report, open(os.path.join(a.out, 'report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
report['note'] = '承重：图上只有柱是实心填充、墙全是两线描边 = 框架结构，墙一律 bearing:false（地下室外墙按挡土承重墙手改）。玻璃 / 窗（蓝）和柱（紫）看 pair*.png 逐处确认，再用 wallaudit.py 全楼对账'
print(json.dumps(report, ensure_ascii=False, indent=1))
