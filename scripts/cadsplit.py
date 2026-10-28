"""
多楼层 / 描边墙 CAD 图纸 → 整栋楼 HouseSpec 初稿（building_draft.json）

适用：
  - 一页（一个文件）上并排放着好几层平面（别墅、自建房、联排：一层、二层……摆在一起）
  - 墙是“两条线描边、中间留白”的画法，且墙线在每个交接处都断开（量房软件、部分天正导出），cadvec 的平行线配对认不全
  - 输入：CAD 导出的矢量 PDF、DWG 用看图软件 / 网页导出的 SVG（真实毫米坐标）、DXF

用法：
  python cadsplit.py 图纸.svg --out 工作目录/split                       # SVG / DXF：坐标就是 mm
  python cadsplit.py 图纸.pdf --out 工作目录/split --ref-width 11720      # PDF：第一张平面墙体外皮总宽（mm）定比例
  python cadsplit.py 图纸.pdf --out ... --scale 162.5                       # 或直接给 mm / pt
  可选：--names 一层,二层,三层   --order rtl / ttb（楼层排列方向，默认从左到右、从上到下）
       --wall-color '#000000'（自动选错时指定墙线颜色）  --px 10（栅格精度 mm）

输出（--out 目录）：
  building_draft.json  整栋楼 HouseSpec 初稿：每层的墙（中线 + 墙厚 + 门窗洞口）、柱、底图对齐参数；
                       各层已经按墙线自动对齐到同一坐标系；`_candidates` 里是楼梯 / 电梯 / 开洞的候选（要人工确认后写进 spec）
  floor<i>.dxf         每一层单独的干净 DXF（mm，原图层 / 颜色），可以再交给 cadvec.py 或别的软件
  floor<i>.png         每一层的底图（已和户型坐标对齐，building_draft.json 的 underlay 指向它）
  check<i>.png         识别结果叠在原图上：红 = 墙、绿 = 门、蓝 = 窗、橙 = 门洞、紫框 = 柱、青框 = 楼梯候选、品红框 = 电梯候选、黄框 = 开洞候选
  report.json          每层识别统计、对齐偏移、候选清单、提示

识别不了的（要人工补）：房间名（文字常被炸成线 / 三角面）、窗台高、门的开向、楼层顺序（默认按图纸排列）、
楼梯上下方向、标注数字（PDF 请自己对一遍尺寸）。生成脚本里读入 building_draft.json 再补改，参考 reference/example-gen-building.py。
"""
import argparse, json, math, os, re, sys
from collections import Counter, defaultdict
import numpy as np
import cv2

sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8')
ap = argparse.ArgumentParser()
ap.add_argument('file')
ap.add_argument('--out', required=True)
ap.add_argument('--page', type=int, default=0)
ap.add_argument('--unit', type=float, help='SVG / DXF：1 个图纸单位 = 多少 mm（默认 1）')
ap.add_argument('--scale', type=float, help='PDF：mm / pt')
ap.add_argument('--ref-dim', type=float, help='PDF：第一张平面最长那道水平尺寸线上标的数字（mm，一般是最外道总尺寸），按它定比例（推荐）')
ap.add_argument('--ref-width', type=float, help='PDF：第一张平面最左到最右墙线（含外凸的柱）的总宽 mm')
ap.add_argument('--names', help='楼层名，逗号分隔（按图纸排列顺序）')
ap.add_argument('--order', choices=['ltr', 'rtl', 'ttb', 'btt'], default='ltr', help='楼层在图上的排列：ltr 从左到右（默认）')
ap.add_argument('--wall-color', help='墙线颜色（#rrggbb），自动选错时指定')
ap.add_argument('--px', type=float, default=10, help='墙体栅格精度 mm / 像素')
ap.add_argument('--max-wall', type=float, default=420, help='墙厚上限 mm（更厚的白色窄条不当墙）')
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
ext = os.path.splitext(a.file)[1].lower()

# ================================================================== 1. 读图元：线段（带颜色 / 图层）、填充、圆、文字
segs, fills, circles, texts = [], [], [], []   # segs: [x0,y0,x1,y1,color,layer]
hexc = lambda c: '#%02x%02x%02x' % tuple(int(round(max(0, min(1, v)) * 255)) for v in c[:3])
def bez(p0, p1, p2, p3, n=8):
    return [((1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t * t * p2[0] + t ** 3 * p3[0],
             (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t * t * p2[1] + t ** 3 * p3[1]) for t in np.linspace(0, 1, n + 1)[1:]]
unit = None
if ext == '.pdf':
    import fitz
    doc = fitz.open(a.file); pg = doc[a.page]
    for d in pg.get_drawings():
        col = hexc(d['color']) if d.get('color') is not None else None
        fil = hexc(d['fill']) if d.get('fill') is not None else None
        polys = []
        for it in d['items']:
            k = it[0]
            if k == 'l': polys.append([(it[1].x, it[1].y), (it[2].x, it[2].y)])
            elif k == 'c': polys.append([(it[1].x, it[1].y)] + bez(*[(p.x, p.y) for p in it[1:5]]))
            elif k == 're': r = it[1]; polys.append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)])
            elif k == 'qu': q = it[1]; polys.append([(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y), (q.ul.x, q.ul.y)])
        if col and d['type'] in ('s', 'fs'):
            for P in polys:
                for p, q in zip(P, P[1:]): segs.append([p[0], p[1], q[0], q[1], col, ''])
        if fil and d['type'] in ('f', 'fs'):
            # 同一路径里的子路径首尾相接拼成多边形
            pts = [p for P in polys for p in P]
            if len(pts) >= 3: fills.append((pts, fil))
    # 小图片 = 实心柱子（部分导出把涂黑的柱画成一像素图片拉伸）
    for im in pg.get_image_info():
        x0, y0, x1, y1 = im['bbox']; fills.append(([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], '#000000:img'))
    for x0, y0, x1, y1, w, *_ in pg.get_text('words'): texts.append(((x0 + x1) / 2, (y0 + y1) / 2, w))
    unit = a.scale
elif ext == '.svg':
    s = open(a.file, encoding='utf-8', errors='replace').read()
    if re.search(r'<g[^>]*transform=', s): print('提示：SVG 里有带 transform 的分组，本脚本按未变换坐标读取，如结果错位请先在导出时取消分组', file=sys.stderr)
    num = r'[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?'
    for m in re.finditer(r'<path\b([^>]*)>', s):
        at = m.group(1); d = re.search(r'\bd="([^"]*)"', at)
        if not d: continue
        g = lambda k: (re.search(k + r'="([^"]+)"', at) or [None, None])[1]
        stroke, fill = g('stroke'), g('fill')
        toks = re.findall(r'[MmLlHhVvZzCcQq]|' + num, d.group(1))
        cur = (0.0, 0.0); start = cur; cmd = None; i = 0; P = []; polys = []
        def nums(n):
            global i
            v = [float(t) for t in toks[i:i + n]]; i += n; return v
        while i < len(toks):
            t = toks[i]
            if re.fullmatch(r'[A-Za-z]', t): cmd = t; i += 1
            if cmd in 'Mm':
                x, y = nums(2); cur = (cur[0] + x, cur[1] + y) if cmd == 'm' else (x, y); start = cur
                if len(P) > 1: polys.append(P)
                P = [cur]; cmd = 'l' if cmd == 'm' else 'L'
            elif cmd in 'Ll': x, y = nums(2); cur = (cur[0] + x, cur[1] + y) if cmd == 'l' else (x, y); P.append(cur)
            elif cmd in 'Hh': x, = nums(1); cur = (cur[0] + x if cmd == 'h' else x, cur[1]); P.append(cur)
            elif cmd in 'Vv': y, = nums(1); cur = (cur[0], cur[1] + y if cmd == 'v' else y); P.append(cur)
            elif cmd in 'Cc':
                v = nums(6); pts = [(v[0], v[1]), (v[2], v[3]), (v[4], v[5])]
                if cmd == 'c': pts = [(cur[0] + p[0], cur[1] + p[1]) for p in pts]
                P += bez(cur, *pts); cur = pts[-1]
            elif cmd in 'Qq':
                v = nums(4); pts = [(v[0], v[1]), (v[2], v[3])]
                if cmd == 'q': pts = [(cur[0] + p[0], cur[1] + p[1]) for p in pts]
                c1 = (cur[0] + 2 / 3 * (pts[0][0] - cur[0]), cur[1] + 2 / 3 * (pts[0][1] - cur[1])); c2 = (pts[1][0] + 2 / 3 * (pts[0][0] - pts[1][0]), pts[1][1] + 2 / 3 * (pts[0][1] - pts[1][1]))
                P += bez(cur, c1, c2, pts[1]); cur = pts[1]
            elif cmd in 'Zz':
                P.append(start); cur = start
                if len(P) > 1: polys.append(P)
                P = [cur]; cmd = None
            else: i += 1
        if len(P) > 1: polys.append(P)
        if stroke and stroke != 'none':
            for P in polys:
                for p, q in zip(P, P[1:]): segs.append([p[0], p[1], q[0], q[1], stroke.lower(), ''])
        elif fill and fill != 'none':
            for P in polys: fills.append((P, fill.lower()))
    for m in re.finditer(r'<circle\b([^>]*)>', s):
        at = m.group(1); g = lambda k: float((re.search(r'\b' + k + r'="([-\d.eE+]+)"', at) or [0, 0])[1])
        col = (re.search(r'(?:fill|stroke)="(#[0-9a-fA-F]{6})"', at) or [None, '#000000'])[1]
        circles.append((g('cx'), g('cy'), g('r'), col.lower()))
    unit = a.unit or 1.0
elif ext == '.dxf':
    import ezdxf
    from ezdxf import path as ezpath
    dx = ezdxf.readfile(a.file)
    unit = a.unit or {0: 1, 1: 25.4, 2: 304.8, 4: 1, 5: 10, 6: 1000}.get(dx.header.get('$INSUNITS', 0), 1)
    ACI = {1: '#ff0000', 2: '#ffff00', 3: '#00ff00', 4: '#00ffff', 5: '#0000ff', 6: '#ff00ff', 7: '#000000', 8: '#808080', 9: '#c0c0c0'}
    lay_col = {L.dxf.name: ACI.get(abs(L.dxf.color), '#000000') for L in dx.layers}
    def walk(ents, pl='', depth=0):
        for e in ents:
            t = e.dxftype(); lay = e.dxf.get('layer', '0')
            if lay == '0' and pl: lay = pl
            c = e.dxf.get('color', 256); col = lay_col.get(lay, '#000000') if c in (0, 256) else ACI.get(c, '#000000')
            try:
                if t == 'INSERT':
                    if depth < 6: walk(e.virtual_entities(), lay, depth + 1)
                elif t == 'HATCH' and (e.dxf.get('solid_fill', 0) or (e.dxf.get('pattern_name', '') or '').upper() == 'SOLID'):
                    for p in ezpath.from_hatch(e): fills.append(([(v.x, -v.y) for v in p.flattening(1.0)], col))
                elif t in ('TEXT', 'MTEXT'):
                    p = e.dxf.insert; texts.append((p.x, -p.y, e.plain_text() if t == 'MTEXT' else e.dxf.text))
                elif t in ('LINE', 'LWPOLYLINE', 'POLYLINE', 'ARC', 'CIRCLE', 'SPLINE', 'ELLIPSE'):
                    if t == 'CIRCLE': circles.append((e.dxf.center.x, -e.dxf.center.y, e.dxf.radius, col))
                    pts = [(v.x, -v.y) for v in ezpath.make_path(e).flattening(1.0)]
                    for p, q in zip(pts, pts[1:]): segs.append([p[0], p[1], q[0], q[1], col, lay])
            except Exception as ex: print('跳过', t, ex, file=sys.stderr)
    walk(dx.modelspace())
else:
    sys.exit('支持 .pdf / .svg / .dxf（DWG 先导出成 SVG 或 DXF）')
if not segs: sys.exit('没有读到线条')
S = np.array([[g[0], g[1], g[2], g[3]] for g in segs], dtype=float)
SC = [g[4] for g in segs]; SL = [g[5] for g in segs]

# ================================================================== 2. 按楼层切分：图元按空白间隔聚成几块，每块 = 一张平面
xs = np.r_[S[:, 0], S[:, 2]]; ys = np.r_[S[:, 1], S[:, 3]]
X0, X1, Y0, Y1 = xs.min(), xs.max(), ys.min(), ys.max(); ext_ = max(X1 - X0, Y1 - Y0)
L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1])
keep = L < ext_ * .45                                    # 图框、标题栏的长边不参与切分
cell = ext_ / 400
W_, H_ = int((X1 - X0) / cell) + 3, int((Y1 - Y0) / cell) + 3
occ = np.zeros((H_, W_), np.uint8)
for (x0, y0, x1, y1), k in zip(S, keep):
    if k: cv2.line(occ, (int((x0 - X0) / cell) + 1, int((y0 - Y0) / cell) + 1), (int((x1 - X0) / cell) + 1, int((y1 - Y0) / cell) + 1), 1, 1)
occ = cv2.dilate(occ, np.ones((5, 5), np.uint8))           # 一块平面里标注、文字离墙不远，连成一片
n, lab, st, _ = cv2.connectedComponentsWithStats(occ, 8)
blocks = [(st[i, 0], st[i, 1], st[i, 0] + st[i, 2], st[i, 1] + st[i, 3], st[i, 4]) for i in range(1, n)]
big = max(b[4] for b in blocks)
blocks = [b for b in blocks if b[4] > big * .18]           # 图例、说明、指北针这些小块不要
key = {'ltr': lambda b: (round(b[1] / (big ** .5 * 2)), b[0]), 'rtl': lambda b: (round(b[1] / (big ** .5 * 2)), -b[0]),
       'ttb': lambda b: (round(b[0] / (big ** .5 * 2)), b[1]), 'btt': lambda b: (round(b[0] / (big ** .5 * 2)), -b[1])}[a.order]
blocks.sort(key=key)
clusters = [((b[0] - 1) * cell + X0 - cell, (b[1] - 1) * cell + Y0 - cell, (b[2] - 1) * cell + X0 + cell, (b[3] - 1) * cell + Y0 + cell) for b in blocks]
print(f'找到 {len(clusters)} 张平面', file=sys.stderr)

# ================================================================== 3. 墙线颜色：成对平行（间距像墙厚）的直线总长最多的那种颜色
def axis_segs(idx):
    out = []
    for i in idx:
        x0, y0, x1, y1 = S[i]
        if abs(y1 - y0) < 1e-6 * ext_ and abs(x1 - x0) > 0: out.append(('h', y0, min(x0, x1), max(x0, x1), i))
        elif abs(x1 - x0) < 1e-6 * ext_ and abs(y1 - y0) > 0: out.append(('v', x0, min(y0, y1), max(y0, y1), i))
    return out
def pair_score(ax, lo, hi):
    sc = 0.0
    for o in 'hv':
        A = sorted([q for q in ax if q[0] == o], key=lambda q: q[1])
        for j, p in enumerate(A):
            for q in A[j + 1:j + 60]:
                d = q[1] - p[1]
                if d > hi: break
                if d >= lo:
                    ov = min(p[3], q[3]) - max(p[2], q[2])
                    if ov > 0: sc += ov
    return sc

def wall_color_rel(idx, B):
    """比例未知时选墙线颜色：按平面宽度的相对尺寸栅格化，每种颜色单独画，数围出来的“墙厚宽度窄条”总长"""
    bw, bh = B[2] - B[0], B[3] - B[1]; px = bw / 1400; gw, gh = int(bw / px) + 4, int(bh / px) + 4
    cs = Counter(SC[i] for i in idx); best, bs = None, -1
    for c, _ in cs.most_common(6):
        cv_ = np.zeros((gh, gw), np.uint8)
        for i in idx:
            if SC[i] == c: x0, y0, x1, y1 = S[i]; cv2.line(cv_, (int((x0 - B[0]) / px) + 2, int((y0 - B[1]) / px) + 2), (int((x1 - B[0]) / px) + 2, int((y1 - B[1]) / px) + 2), 255, 1)
        fr = (cv_ == 0).astype(np.uint8); n_, lb, st_, _ = cv2.connectedComponentsWithStats(fr, 4); ds = cv2.distanceTransform(fr, cv2.DIST_L2, 3)
        tot = 0.0
        for k in range(1, n_):
            x, y, w, h, ar = st_[k]
            if x == 0 or y == 0 or x + w >= gw or y + h >= gh or ar < 9: continue
            hm = float(ds[y:y + h, x:x + w][lb[y:y + h, x:x + w] == k].max())
            if 1.5 <= hm * 2 <= 1400 / 25: tot += ar / max(hm * 2, 1)
        if tot > bs: best, bs = c, tot
    return best
def in_box(i, B):
    x0, y0, x1, y1 = S[i]; return B[0] <= min(x0, x1) and max(x0, x1) <= B[2] and B[1] <= min(y0, y1) and max(y0, y1) <= B[3]
fl_idx = [[i for i in range(len(S)) if in_box(i, B)] for B in clusters]
# 比例（mm / 单位）
if unit is None:
    if a.ref_dim:
        # 第一张平面：墙线颜色以外最长的那条水平线 = 最外道尺寸线
        B0 = clusters[0]; bw = B0[2] - B0[0]
        ax0 = axis_segs(fl_idx[0]); cols0 = Counter(SC[q[4]] for q in ax0)
        wc0 = a.wall_color.lower() if a.wall_color else wall_color_rel(fl_idx[0], B0)
        hd = [q for q in ax0 if q[0] == 'h' and SC[q[4]] != wc0]
        Lmax = max(q[3] - q[2] for q in hd)
        unit = a.ref_dim / Lmax; how = f'--ref-dim {a.ref_dim}（最长水平尺寸线 {Lmax:.2f} 单位）'
    elif a.ref_width:
        # 第一张平面：只看长线（≥ 平面高度的 30%），墙线颜色 = 成对平行（间距在平面宽度的 1/400 ~ 1/25 之间）总长最多的颜色
        B0 = clusters[0]; bw, bh = B0[2] - B0[0], B0[3] - B0[1]
        ax0 = [q for q in axis_segs(fl_idx[0]) if q[3] - q[2] > .3 * (bh if q[0] == 'v' else bw)]
        cols0 = Counter(SC[q[4]] for q in ax0)
        best = a.wall_color.lower() if a.wall_color else wall_color_rel(fl_idx[0], B0)
        vv = [q for q in axis_segs(fl_idx[0]) if SC[q[4]] == best and q[0] == 'v']
        unit = a.ref_width / (max(q[1] for q in vv) - min(q[1] for q in vv))
        how = f'--ref-width {a.ref_width}'
    else:
        unit = None; how = '没有比例：按最常见墙厚 = 220mm 估算（请用 --scale 或 --ref-width 指定）'
else: how = 'SVG/DXF 坐标' if ext != '.pdf' else f'--scale {unit}'
if unit is None:
    ax0 = axis_segs(fl_idx[0]); sp = Counter()
    for o in 'hv':
        A = sorted([q for q in ax0 if q[0] == o], key=lambda q: q[1])
        for j, p in enumerate(A):
            for q in A[j + 1:j + 30]:
                d = q[1] - p[1]
                if d <= 0: continue
                ov = min(p[3], q[3]) - max(p[2], q[2])
                if ov > d * 4: sp[round(d, 2)] += ov
    unit = 220 / sp.most_common(1)[0][0]
print('比例', round(unit, 4), 'mm/单位 ·', how, file=sys.stderr)

# ================================================================== 4. 每层：栅格化墙线 → 窄白条 = 墙；按缺口里的线判断门窗；方块 = 柱
PX = a.px
STD_T = [100, 120, 150, 180, 200, 220, 240, 250, 300, 370]
def snap_t(t):
    b = min(STD_T, key=lambda v: abs(v - t)); return b if abs(b - t) <= 18 else round(t / 10) * 10
floors = []
for fi, B in enumerate(clusters):
    idx = fl_idx[fi]
    mm = lambda v: v * unit
    ax = axis_segs(idx)
    # 墙线颜色
    cols = Counter(SC[q[4]] for q in ax)
    # 局部坐标（mm）：以这一块的左上角为原点
    bx0, by0 = B[0], B[1]
    def to_mm(x, y): return ((x - bx0) * unit, (y - by0) * unit)
    Wmm, Hmm = (B[2] - B[0]) * unit, (B[3] - B[1]) * unit
    gw, gh = int(Wmm / PX) + 4, int(Hmm / PX) + 4
    P = lambda x, y: (int(round(to_mm(x, y)[0] / PX)) + 2, int(round(to_mm(x, y)[1] / PX)) + 2)
    def strip_len(c):
        # 只画这种颜色的线，数一数围出来的“墙厚宽度的窄条”总长：尺寸线、轴线围不出闭合窄条
        cv_ = np.zeros((gh, gw), np.uint8)
        for i in idx:
            if SC[i] == c: x0, y0, x1, y1 = S[i]; cv2.line(cv_, P(x0, y0), P(x1, y1), 255, 1)
        fr = (cv_ == 0).astype(np.uint8); n_, lb, st_, _ = cv2.connectedComponentsWithStats(fr, 4); ds = cv2.distanceTransform(fr, cv2.DIST_L2, 3)
        tot = 0.0
        for k in range(1, n_):
            x, y, w, h, ar = st_[k]
            if x == 0 or y == 0 or x + w >= gw or y + h >= gh or ar < 9: continue
            hm = float(ds[y:y + h, x:x + w][lb[y:y + h, x:x + w] == k].max()) * PX
            if 60 <= hm * 2 <= a.max_wall + PX * 2: tot += ar * PX / max(hm * 2, PX)
        return tot
    if a.wall_color: wc = a.wall_color.lower()
    else:
        top = sorted(cols, key=lambda c: -pair_score([q for q in ax if SC[q[4]] == c], 80 / unit, a.max_wall / unit))[:4]
        wc = max(top, key=strip_len)
    # 所有颜色的线都画上（窗、门框的线常是别的颜色，不画的话墙带会从窗口“漏”到室外）；
    # 每个像素记住是哪种颜色画的，之后看窄条长边的颜色：墙线颜色占多数 = 墙，否则是窗 / 门 / 楼梯踏步
    canvas = np.zeros((gh, gw), np.uint8); colimg = np.zeros((gh, gw), np.int16)
    cidx = {c: k + 1 for k, c in enumerate(sorted(set(SC[i] for i in idx)))}; WCI = cidx.get(wc, -1)
    for i in sorted(idx, key=lambda i: SC[i] == wc):           # 墙线最后画，重叠处算墙线
        x0, y0, x1, y1 = S[i]; cv2.line(canvas, P(x0, y0), P(x1, y1), 255, 1); cv2.line(colimg, P(x0, y0), P(x1, y1), cidx[SC[i]], 1)
    # 涂黑的柱子 / 实心墙（墙线颜色或深色的填充）也画上
    solid_fills = []
    for poly, col in fills:
        xs_, ys_ = [p[0] for p in poly], [p[1] for p in poly]
        if not (B[0] <= min(xs_) and max(xs_) <= B[2] and B[1] <= min(ys_) and max(ys_) <= B[3]): continue
        w_, h_ = (max(xs_) - min(xs_)) * unit, (max(ys_) - min(ys_)) * unit
        dark = col.startswith('#000000') or col == wc
        if dark and 80 < min(w_, h_) and max(w_, h_) < 1500 and min(w_, h_) / max(w_, h_) > .35 and (col.endswith(':img') or len(poly) <= 6):
            solid_fills.append((min(xs_), min(ys_), max(xs_), max(ys_)))
            cv2.rectangle(canvas, P(min(xs_), min(ys_)), P(max(xs_), max(ys_)), 255, -1)
    # 空白连通块：窄长的 = 墙体内部（墙两侧描边之间）；宽的 = 房间 / 室外
    free = (canvas == 0).astype(np.uint8)
    n, lab, stt, _ = cv2.connectedComponentsWithStats(free, 4)
    dist = cv2.distanceTransform(free, cv2.DIST_L2, 3)
    strips, rooms = [], []
    exterior = {int(k) for k in np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]]) if k}
    def is_ext(xmm, ymm):
        gx, gy = int(round(xmm / PX)) + 2, int(round(ymm / PX)) + 2
        return 0 <= gx < gw and 0 <= gy < gh and int(lab[gy, gx]) in exterior
    for k in range(1, n):
        x, y, w, h, area = stt[k]
        if x == 0 or y == 0 or x + w >= gw or y + h >= gh: continue   # 碰到画布边 = 室外
        m = lab[y:y + h, x:x + w] == k
        half = float(dist[y:y + h, x:x + w][m].max()) * PX
        if area < 9: continue
        if half * 2 <= a.max_wall + PX * 2: strips.append((k, x, y, w, h, m))
        else: rooms.append((k, x, y, w, h, area * PX * PX / 1e6))
    # 窄条拆成矩形（按行合并、按列合并，取块数少的）
    def rects_of(m, x, y):
        def by_rows(M):
            out, open_ = [], {}
            for r in range(M.shape[0]):
                runs, c = [], 0
                row = M[r]
                while c < len(row):
                    if row[c]:
                        c0 = c
                        while c < len(row) and row[c]: c += 1
                        runs.append((c0, c))
                    else: c += 1
                nxt = {}
                for ru in runs:
                    if ru in open_: nxt[ru] = open_[ru]
                    else: nxt[ru] = r
                for ru, r0 in open_.items():
                    if ru not in nxt: out.append((ru[0], r0, ru[1], r))
                open_ = nxt
            for ru, r0 in open_.items(): out.append((ru[0], r0, ru[1], M.shape[0]))
            return out
        R1 = by_rows(m); R2 = [(r0, c0, r1, c1) for (c0, r0, c1, r1) in by_rows(m.T)]
        R = R1 if len(R1) <= len(R2) else R2
        return [((c0 + x - 2) * PX, (r0 + y - 2) * PX, (c1 + x - 2) * PX, (r1 + y - 2) * PX, (c0 + x, r0 + y, c1 + x, r1 + y)) for (c0, r0, c1, r1) in R]
    pieces = []   # 墙段矩形（mm，局部坐标），描边线占一个像素：两侧各补半个像素
    for k, x, y, w, h, m in strips:
        for (x0, y0, x1, y1, (gx0, gy0, gx1, gy1)) in rects_of(m, x, y):
            x0 -= PX / 2; y0 -= PX / 2; x1 += PX / 2; y1 += PX / 2
            ww, hh = x1 - x0, y1 - y0
            if max(ww, hh) < 60: continue
            o = 'h' if ww >= hh else 'v'
            t = hh if o == 'h' else ww
            if t > a.max_wall + PX or t < 60: continue        # 太薄的是文字笔画、两条线之间的缝
            # 长边上的线是什么颜色
            if o == 'h': edge = np.r_[colimg[max(gy0 - 1, 0), gx0:gx1], colimg[min(gy1, gh - 1), gx0:gx1]]
            else: edge = np.r_[colimg[gy0:gy1, max(gx0 - 1, 0)], colimg[gy0:gy1, min(gx1, gw - 1)]]
            wf = float((edge == WCI).mean()) if len(edge) else 0
            pieces.append(dict(o=o, c=(y0 + y1) / 2 if o == 'h' else (x0 + x1) / 2, s0=x0 if o == 'h' else y0, s1=x1 if o == 'h' else y1, t=t, sq=min(ww, hh) / max(ww, hh) > .8, wall=wf >= .5))
    # 柱：涂黑的块、或墙线围成的近方形大块（比墙厚）
    columns = []
    wallp = [p for p in pieces if p['wall']]
    def near_wall(c, tol=60):
        for p in wallp:
            r = (p['s0'], p['c'] - p['t'] / 2, p['s1'], p['c'] + p['t'] / 2) if p['o'] == 'h' else (p['c'] - p['t'] / 2, p['s0'], p['c'] + p['t'] / 2, p['s1'])
            if c[0] - tol <= r[2] and r[0] <= c[2] + tol and c[1] - tol <= r[3] and r[1] <= c[3] + tol: return True
        return False
    for (x0, y0, x1, y1) in solid_fills:
        p0, p1 = to_mm(x0, y0), to_mm(x1, y1); c = (p0[0], p0[1], p1[0], p1[1])
        if min(c[2] - c[0], c[3] - c[1]) >= 200 and near_wall(c): columns.append(c)
    for k, x, y, w, h, area in rooms:
        if area < 1.0 and min(w, h) * PX > a.max_wall and min(w, h) / max(w, h) > .5 and area * 1e6 / (w * h * PX * PX) > .9 and max(w, h) * PX < 1100:
            c = ((x - 2) * PX - PX / 2, (y - 2) * PX - PX / 2, (x + w - 2) * PX + PX / 2, (y + h - 2) * PX + PX / 2)
            if near_wall(c) and not any(abs(c[0] - q[0]) < 50 and abs(c[1] - q[1]) < 50 for q in columns): columns.append(c)
    for q in pieces:
        # 方块、或比墙厚得多的短块（贴在墙上的柱子框）= 柱
        if q['wall'] and q['t'] >= 300 and q['s1'] - q['s0'] >= 300 and (q['sq'] or q['s1'] - q['s0'] <= 900):
            q['sq'] = True
            c = (q['s0'], q['c'] - q['t'] / 2, q['s1'], q['c'] + q['t'] / 2) if q['o'] == 'h' else (q['c'] - q['t'] / 2, q['s0'], q['c'] + q['t'] / 2, q['s1'])
            if not any(abs(c[0] - k[0]) < 50 and abs(c[1] - k[1]) < 50 for k in columns): columns.append(c)
    # ---- 墙段合并成墙线：同方向、中线相近、首尾相接（中间被门窗打断的也连起来，缺口记成洞口）
    other = [i for i in idx if SC[i] != wc]
    oax = axis_segs(other)
    aax = axis_segs(idx)   # 所有颜色（判断缺口里画了几条平行线：窗的玻璃线有时和墙线同色）
    def mm_ax(q):
        o, c, s0, s1, i = q
        if o == 'h': (A0, Cc), (A1, _) = to_mm(s0, c), to_mm(s1, c); return (o, Cc, A0, A1, i)
        (Cc, A0), (_, A1) = to_mm(c, s0), to_mm(c, s1); return (o, Cc, A0, A1, i)
    oax = [mm_ax(q) for q in oax]; aax = [mm_ax(q) for q in aax]
    arcs_mm = []
    for i in other:
        x0, y0, x1, y1 = S[i]
        if abs(x1 - x0) > 1e-9 and abs(y1 - y0) > 1e-9: p0, p1 = to_mm(x0, y0), to_mm(x1, y1); arcs_mm.append((p0, p1, SC[i]))
    def gap_lines(o, c, t, g0, g1):
        # 缺口里画了门窗线（墙线以外的颜色）才算门窗；墙线自己的延续线不算
        return len({round(cc / 15) for (oo, cc, a0, a1, i) in oax if oo == o and abs(cc - c) <= t / 2 + 25 and min(a1, g1) - max(a0, g0) > (g1 - g0) * .5})
    lines = []
    for p in sorted([p for p in pieces if not p['sq'] and p['wall']], key=lambda p: (p['o'], round(p['c'] / 40), p['s0'])):
        L_ = lines[-1] if lines else None
        gp = p['s0'] - L_['s1'] if L_ else 0
        if L_ and L_['o'] == p['o'] and abs(L_['c'] - p['c']) <= 35 and abs(L_['t'] - p['t']) <= 45 and (gp <= 1500 or (gp <= 6000 and gap_lines(p['o'], p['c'], p['t'], L_['s1'], p['s0']) >= 2)):
            if p['s0'] - L_['s1'] > PX * 1.5: L_['gaps'].append((L_['s1'], p['s0']))
            L_['s1'] = max(L_['s1'], p['s1']); L_['segs'].append(p); L_['c'] = (L_['c'] * (len(L_['segs']) - 1) + p['c']) / len(L_['segs']); L_['t'] = max(L_['t'], p['t'])
        else: lines.append(dict(o=p['o'], c=p['c'], s0=p['s0'], s1=p['s1'], t=p['t'], gaps=[], segs=[p]))
    # 方块（转角、门垛）贴着墙线端头的：墙线延伸进去
    sqs = [p for p in pieces if p['sq'] and p['wall']]
    # ---- 缺口分类：缺口里沿墙方向的平行线 ≥ 3 条 = 窗；2 条（两侧墙面）或横跨的门框线 = 门；空的 = 门洞
    def classify(L_, g0, g1):
        o, c, t = L_['o'], L_['c'], L_['t']
        par = set(); cross = 0
        for (oo, cc, a0, a1, i) in aax:
            if oo == o and abs(cc - c) <= t / 2 + 25 and min(a1, g1) - max(a0, g0) > (g1 - g0) * .5: par.add(round(cc / 15))
            if oo != o and abs(cc - g0) < 40 or (oo != o and abs(cc - g1) < 40):
                if oo != o and min(a1, c + t / 2) - max(a0, c - t / 2) > t * .6: cross += 1
        # 墙内部（离两侧墙面 30mm 以上）的平行线 = 玻璃线 → 窗；只有两侧墙面线 / 门框线 → 门（量房图常把门洞画成一块）；空的 → 门洞
        glassn = len({round(cc / 15) for (oo, cc, a0, a1, i) in aax if oo == o and abs(cc - c) < t / 2 - 30 and min(a1, g1) - max(a0, g0) > (g1 - g0) * .5})
        if glassn >= 1: return 'window', glassn
        if len(par) >= 2 or cross >= 1: return 'door', len(par)
        return 'hole', 0
    # 墙线端头和前方的柱 / 方块之间画了门窗线：墙线延伸到柱边，中间记成洞口
    blocks = [((q['s0'], q['c'] - q['t'] / 2, q['s1'], q['c'] + q['t'] / 2) if q['o'] == 'h' else (q['c'] - q['t'] / 2, q['s0'], q['c'] + q['t'] / 2, q['s1'])) for q in sqs] + list(columns)
    def rect_of(q): return (q['s0'], q['c'] - q['t'] / 2, q['s1'], q['c'] + q['t'] / 2) if q['o'] == 'h' else (q['c'] - q['t'] / 2, q['s0'], q['c'] + q['t'] / 2, q['s1'])
    for L_ in lines:
        o, c, t = L_['o'], L_['c'], L_['t']
        perp = [rect_of(q) for q in lines if q['o'] != o]   # 垂直的墙也可以是门窗另一头的“墙垛”
        for end in (0, 1):
            e = L_['s0'] if end == 0 else L_['s1']; best = None
            for b in blocks + perp:
                if o == 'h' and b[1] - 20 <= c <= b[3] + 20:
                    face = b[2] if end == 0 else b[0]; g = (e - face) if end == 0 else (face - e)
                elif o == 'v' and b[0] - 20 <= c <= b[2] + 20:
                    face = b[3] if end == 0 else b[1]; g = (e - face) if end == 0 else (face - e)
                else: continue
                if 250 < g <= 6000 and (best is None or g < best[0]): best = (g, face)
            if best and gap_lines(o, c, t, *(sorted([e, best[1]]))) >= 2:
                if end == 0: L_['gaps'].append((best[1], L_['s0'])); L_['s0'] = best[1]
                else: L_['gaps'].append((L_['s1'], best[1])); L_['s1'] = best[1]
    # 玻璃墙 / 玻璃栏杆：长边不是墙线颜色、但很长的窄条（≥ 1.2m，楼梯踏步一般短于这个），且不在已有墙线的门窗缺口里
    def in_gap(p):
        for L_ in lines:
            if L_['o'] == p['o'] and abs(L_['c'] - p['c']) <= L_['t'] / 2 + 30:
                for g0, g1 in L_['gaps']:
                    if p['s0'] >= g0 - 30 and p['s1'] <= g1 + 30: return True
        return False
    glass = sorted([p for p in pieces if not p['wall'] and not p['sq'] and p['s1'] - p['s0'] >= 800 and 50 <= p['t'] <= 300 and not in_gap(p)], key=lambda p: (p['o'], p['c']))
    bands = []
    for p in glass:   # 中间有一条玻璃线的，两半并成一条
        b = bands[-1] if bands else None
        if b and b['o'] == p['o'] and abs((b['c'] + b['t'] / 2) - (p['c'] - p['t'] / 2)) <= PX * 1.5 and min(b['s1'], p['s1']) - max(b['s0'], p['s0']) > .8 * (p['s1'] - p['s0']):
            lo, hi = b['c'] - b['t'] / 2, p['c'] + p['t'] / 2; b['c'], b['t'] = (lo + hi) / 2, hi - lo; b['s0'], b['s1'] = min(b['s0'], p['s0']), max(b['s1'], p['s1'])
        else: bands.append(dict(p))
    for b in bands:
        if b['t'] < 80: continue
        # 只要外围的：窄条某一侧紧挨室外（楼梯踏步、梁线围出来的条在室内，不算）
        mid = (b['s0'] + b['s1']) / 2; off = b['t'] / 2 + PX * 2.5
        sides = [(mid, b['c'] - off), (mid, b['c'] + off)] if b['o'] == 'h' else [(b['c'] - off, mid), (b['c'] + off, mid)]
        if not any(is_ext(*q) for q in sides): continue
        lines.append(dict(o=b['o'], c=b['c'], s0=b['s0'], s1=b['s1'], t=b['t'], gaps=[(b['s0'] + 1, b['s1'] - 1)], segs=[b], glass=True))
    # ---- 输出 HouseSpec 墙
    walls_out, ops_n = [], Counter()
    for L_ in lines:
        t = snap_t(L_['t']); o, c = L_['o'], round(L_['c'] * 2) / 2
        s0, s1 = L_['s0'], L_['s1']
        # 端头接着方块（转角块、柱）：延伸到方块中心
        for end in (0, 1):
            e = s0 if end == 0 else s1
            for q in sqs + [dict(o='x', c=0, s0=0, s1=0, box=cb) for cb in columns]:
                if 'box' in q: bx0_, by0_, bx1_, by1_ = q['box']
                else:
                    bx0_, by0_, bx1_, by1_ = (q['s0'], q['c'] - q['t'] / 2, q['s1'], q['c'] + q['t'] / 2) if q['o'] == 'h' else (q['c'] - q['t'] / 2, q['s0'], q['c'] + q['t'] / 2, q['s1'])
                if o == 'h' and by0_ - 20 <= c <= by1_ + 20 and abs((bx0_ if end else bx1_) - e) < 40:
                    e = (bx0_ + bx1_) / 2
                if o == 'v' and bx0_ - 20 <= c <= bx1_ + 20 and abs((by0_ if end else by1_) - e) < 40:
                    e = (by0_ + by1_) / 2
            if end == 0: s0 = e
            else: s1 = e
        ops = []
        gs = []
        for g0, g1 in sorted(L_['gaps']):   # 重叠的缺口并起来
            if gs and g0 <= gs[-1][1] + 20: gs[-1] = (gs[-1][0], max(gs[-1][1], g1))
            else: gs.append((g0, g1))
        for g0, g1 in gs:
            if g1 - g0 < 300: continue
            gr = (g0, c - t / 2, g1, c + t / 2) if o == 'h' else (c - t / 2, g0, c + t / 2, g1)
            if any(min(gr[2], cb[2]) - max(gr[0], cb[0]) > (g1 - g0) * .5 * (o == 'h') + 10 * (o == 'v') and min(gr[3], cb[3]) - max(gr[1], cb[1]) > (g1 - g0) * .5 * (o == 'v') + 10 * (o == 'h') for cb in blocks): continue
            typ, nl = ('floorWindow', 0) if L_.get('glass') else classify(L_, g0, g1); ops_n[typ] += 1
            ops.append({'type': typ, 'from': round(g0), 'to': round(g1), '_lines': nl})
        if t < 60 or s1 - s0 < max(150, t * .8): continue   # 文字笔画、线头之间的碎条
        A = (round(s0), c) if o == 'h' else (c, round(s0)); Bp = (round(s1), c) if o == 'h' else (c, round(s1))
        walls_out.append({'a': list(A), 'b': list(Bp), 't': t, 'bearing': t >= 180, **({'openings': ops} if ops else {})})
    # 端点吸附：墙端离垂直墙中线 ≤ 半墙厚 + 40 → 延伸 / 缩到那条中线上（T 形、L 形交接）
    for w in walls_out:
        o = 'h' if w['a'][1] == w['b'][1] else 'v'
        for k in ('a', 'b'):
            p = w[k]
            for q in walls_out:
                if q is w: continue
                qo = 'h' if q['a'][1] == q['b'][1] else 'v'
                if qo == o: continue
                if o == 'h' and qo == 'v':
                    lo, hi = sorted([q['a'][1], q['b'][1]])
                    if lo - 40 <= p[1] <= hi + 40 and abs(p[0] - q['a'][0]) <= q['t'] / 2 + w['t'] / 2 + 80: p[0] = q['a'][0]
                if o == 'v' and qo == 'h':
                    lo, hi = sorted([q['a'][0], q['b'][0]])
                    if lo - 40 <= p[0] <= hi + 40 and abs(p[1] - q['a'][1]) <= q['t'] / 2 + w['t'] / 2 + 80: p[1] = q['a'][1]
    structs = [{'kind': 'column', 'at': [round((c[0] + c[2]) / 2), round((c[1] + c[3]) / 2)], 'w': round(c[2] - c[0]), 'd': round(c[3] - c[1])} for c in columns]
    # ---- 候选：楼梯（等间距平行短线 ≥ 4 条）、开洞（成片的 45° 斜线）、电梯（楼梯旁三面墙围成的 0.8~1.4m 小间）
    cand = {'stairs': [], 'voids': [], 'elevator': []}
    for o in 'hv':
        A = sorted([q for q in oax if q[0] == o and 500 < q[3] - q[2] < 2200], key=lambda q: (SC[q[4]], q[1]))
        groups = []
        for q in A:
            G = groups[-1] if groups else None
            if G and SC[G[-1][4]] == SC[q[4]] and 150 < q[1] - G[-1][1] < 360 and abs(q[2] - G[-1][2]) < 300 and abs(q[3] - G[-1][3]) < 300: G.append(q)
            elif G and abs(q[1] - G[-1][1]) < 5: continue
            else: groups.append([q])
        for G in groups:
            if len(G) < 4: continue
            sp_ = np.diff([q[1] for q in G])
            if sp_.std() > 40: continue
            c0, c1 = G[0][1], G[-1][1]; a0, a1 = min(q[2] for q in G), max(q[3] for q in G)
            box = [round(a0), round(c0), round(a1), round(c1)] if o == 'h' else [round(c0), round(a0), round(c1), round(a1)]
            cand['stairs'].append({'rect': box, 'treads': len(G), 'tread': round(float(sp_.mean())), 'run': 'ns' if o == 'h' else 'ew', 'color': SC[G[0][4]]})
    diag = defaultdict(list)
    for p0, p1, col in arcs_mm:
        dx_, dy_ = p1[0] - p0[0], p1[1] - p0[1]
        if abs(abs(dx_) - abs(dy_)) < .08 * max(abs(dx_), abs(dy_)) and math.hypot(dx_, dy_) > 300: diag[col].append((p0, p1))
    for col, D in diag.items():
        if len(D) < 8: continue
        pts = np.array([p for d in D for p in d])
        # 斜线按位置粗分成团
        grid = defaultdict(list)
        for d in D: grid[(int(d[0][0] // 2500), int(d[0][1] // 2500))].append(d)
        seen = set()
        for kk in grid:
            if kk in seen: continue
            stack, comp = [kk], []
            while stack:
                u = stack.pop()
                if u in seen or u not in grid: continue
                seen.add(u); comp += grid[u]
                stack += [(u[0] + i, u[1] + j) for i in (-1, 0, 1) for j in (-1, 0, 1)]
            if len(comp) >= 8:
                P_ = np.array([p for d in comp for p in d])
                cand['voids'].append({'rect': [round(P_[:, 0].min()), round(P_[:, 1].min()), round(P_[:, 0].max()), round(P_[:, 1].max())], 'lines': len(comp), 'note': '成片斜线：可能是挑空（楼板开洞）、下沉区、或上层卫生间降板压下来的局部低顶——看区域里的 ▽ 标高（+ 为净高、- 为下沉）和上一层同位置是不是卫生间再定'})
    if cand['stairs']:
        sx0 = min(s_['rect'][0] for s_ in cand['stairs']) - 400; sy0 = min(s_['rect'][1] for s_ in cand['stairs']) - 400
        sx1 = max(s_['rect'][2] for s_ in cand['stairs']) + 400; sy1 = max(s_['rect'][3] for s_ in cand['stairs']) + 400
        cand['stair_zone'] = [round(sx0), round(sy0), round(sx1), round(sy1)]
        inz = lambda w: sx0 <= min(w['a'][0], w['b'][0]) and max(w['a'][0], w['b'][0]) <= sx1 and sy0 <= min(w['a'][1], w['b'][1]) and max(w['a'][1], w['b'][1]) <= sy1
        zw = [w for w in walls_out if inz(w) and w['t'] <= 200]
        V_ = [w for w in zw if w['a'][0] == w['b'][0]]; H_ = [w for w in zw if w['a'][1] == w['b'][1]]
        for i_, p in enumerate(V_):
            for q in V_[i_ + 1:]:
                gap = abs(q['a'][0] - p['a'][0]) - (p['t'] + q['t']) / 2
                if not 750 <= gap <= 1450: continue
                plo, phi = sorted([p['a'][1], p['b'][1]]); qlo, qhi = sorted([q['a'][1], q['b'][1]])
                lo, hi = max(plo, qlo), min(phi, qhi)
                if hi - lo < 800: continue
                xl, xr = sorted([p['a'][0], q['a'][0]])
                for h_ in H_:
                    hlo, hhi = sorted([h_['a'][0], h_['b'][0]])
                    if hlo <= xl + 40 and hhi >= xr - 40 and (abs(h_['a'][1] - lo) < 60 or abs(h_['a'][1] - hi) < 60):
                        top = h_['a'][1]
                        y_in0, y_in1 = (top + h_['t'] / 2, hi) if abs(top - lo) < 60 else (lo, top - h_['t'] / 2)
                        cand['elevator'].append({'rect': [round(xl + p['t'] / 2), round(y_in0), round(xr - q['t'] / 2), round(y_in1)], 'inner_w': round(gap), 'note': '楼梯旁三面墙的小间：很可能是家用电梯井（看其它层同一位置）'})
    # ---- 底图 + 核对图
    UPX = 8.0
    uw, uh = int(Wmm / UPX) + 1, int(Hmm / UPX) + 1
    under = np.full((uh, uw, 3), 255, np.uint8)
    def hex2bgr(c):
        c = c.split(':')[0].lstrip('#'); r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        if r + g + b > 600: r, g, b = int(r * .65), int(g * .65), int(b * .45)  # 很浅的颜色（黄字）压暗一点，白底上看得见
        return (b, g, r)
    Q = lambda x, y: (int(round(to_mm(x, y)[0] / UPX)), int(round(to_mm(x, y)[1] / UPX)))
    for poly, col in fills:
        xs_ = [p[0] for p in poly]; ys_ = [p[1] for p in poly]
        if col.endswith(':img') and max(max(xs_) - min(xs_), max(ys_) - min(ys_)) * unit > 1500: continue   # 大图片（半透明遮罩等）不画
        if B[0] <= min(xs_) and max(xs_) <= B[2] and B[1] <= min(ys_) and max(ys_) <= B[3]:
            cv2.fillPoly(under, [np.array([Q(*p) for p in poly], np.int32)], hex2bgr(col))
    for i in idx:
        x0, y0, x1, y1 = S[i]; cv2.line(under, Q(x0, y0), Q(x1, y1), hex2bgr(SC[i]), 1, cv2.LINE_AA)
    for cx, cy, r, col in circles:
        if B[0] <= cx <= B[2] and B[1] <= cy <= B[3]: cv2.circle(under, Q(cx, cy), max(1, int(r * unit / UPX)), hex2bgr(col), -1)
    chk = under.copy()
    M_ = lambda x, y: (int(round(x / UPX)), int(round(y / UPX)))
    for w in walls_out:
        o = 'h' if w['a'][1] == w['b'][1] else 'v'; t = w['t']
        x0, y0 = w['a']; x1, y1 = w['b']
        r0 = (min(x0, x1), y0 - t / 2, max(x0, x1), y0 + t / 2) if o == 'h' else (x0 - t / 2, min(y0, y1), x0 + t / 2, max(y0, y1))
        cv2.rectangle(chk, M_(r0[0], r0[1]), M_(r0[2], r0[3]), (40, 40, 220), 2)
        for op in w.get('openings', []):
            colr = {'window': (220, 120, 30), 'floorWindow': (255, 170, 60), 'door': (40, 170, 40), 'hole': (0, 140, 255)}[op['type']]
            rr = (op['from'], y0 - t / 2 - 40, op['to'], y0 + t / 2 + 40) if o == 'h' else (x0 - t / 2 - 40, op['from'], x0 + t / 2 + 40, op['to'])
            cv2.rectangle(chk, M_(rr[0], rr[1]), M_(rr[2], rr[3]), colr, 3)
    for c in columns: cv2.rectangle(chk, M_(c[0], c[1]), M_(c[2], c[3]), (200, 60, 160), 3)
    for s_ in cand['stairs']: r = s_['rect']; cv2.rectangle(chk, M_(r[0], r[1]), M_(r[2], r[3]), (200, 200, 0), 2)
    for e in cand['elevator']: r = e['rect']; cv2.rectangle(chk, M_(r[0], r[1]), M_(r[2], r[3]), (200, 0, 200), 3)
    for v in cand['voids']: r = v['rect']; cv2.rectangle(chk, M_(r[0], r[1]), M_(r[2], r[3]), (0, 200, 230), 3)
    floors.append(dict(box=B, wall_color=wc, walls=walls_out, structs=structs, cand=cand, under=under, chk=chk, ops=dict(ops_n),
                       rooms=len([r for r in rooms if r[5] > 1.5]), idx=idx, to_origin=(bx0, by0)))
    print(f'  第 {fi + 1} 张：墙线颜色 {wc}，墙 {len(walls_out)}，洞口 {dict(ops_n)}，柱 {len(structs)}，楼梯候选 {len(cand["stairs"])}，电梯候选 {len(cand["elevator"])}，开洞候选 {len(cand["voids"])}', file=sys.stderr)

# ================================================================== 5. 各层对齐：找让竖直 / 水平墙线重合最多的平移（以第一层为基准）
def wall_lines_axis(F, o):
    out = []
    for w in F['walls']:
        if (o == 'v') == (w['a'][0] == w['b'][0]):
            c = w['a'][0] if o == 'v' else w['a'][1]
            lo, hi = sorted([w['a'][1], w['b'][1]] if o == 'v' else [w['a'][0], w['b'][0]])
            out.append((c, hi - lo))
    return out
def best_shift(ref, cur):
    if not ref or not cur: return 0.0
    cand_ = Counter()
    for c0, l0 in ref:
        for c1, l1 in cur: cand_[round((c0 - c1) / 20) * 20] += min(l0, l1)
    top = [d for d, _ in cand_.most_common(12)]
    def score(d): return sum(min(l0, l1) for c0, l0 in ref for c1, l1 in cur if abs(c0 - (c1 + d)) < 30)
    d = max(top, key=score)
    # 精调：重合线的平均差
    diffs = [c0 - c1 for c0, l0 in ref for c1, l1 in cur if abs(c0 - (c1 + d)) < 30]
    return float(np.median(diffs)) if diffs else float(d)
shifts = [(0.0, 0.0)]
for F in floors[1:]:
    shifts.append((best_shift(wall_lines_axis(floors[0], 'v'), wall_lines_axis(F, 'v')), best_shift(wall_lines_axis(floors[0], 'h'), wall_lines_axis(F, 'h'))))
# 统一原点：所有楼层墙体外包框的左上角
allx = [p[0] + shifts[i][0] for i, F in enumerate(floors) for w in F['walls'] for p in (w['a'], w['b'])]
ally = [p[1] + shifts[i][1] for i, F in enumerate(floors) for w in F['walls'] for p in (w['a'], w['b'])]
OX, OY = min(allx), min(ally)
names = a.names.split(',') if a.names else ['一层', '二层', '三层', '四层', '五层', '六层', '七层', '八层', '九层', '十层'][:len(floors)]
while len(names) < len(floors): names.append(f'{len(names) + 1}层')

def shift_pt(p, dx, dy): return [round((p[0] + dx) * 2) / 2, round((p[1] + dy) * 2) / 2]
spec_floors, report = [], {'file': os.path.abspath(a.file), 'scale_mm_per_unit': unit, 'scale_from': how, 'floors': []}
try:
    import ezdxf
except ImportError:
    ezdxf = None
for i, F in enumerate(floors):
    dx, dy = shifts[i][0] - OX, shifts[i][1] - OY
    walls = []
    for w in F['walls']:
        o = 'h' if w['a'][1] == w['b'][1] else 'v'
        w2 = dict(w, a=shift_pt(w['a'], dx, dy), b=shift_pt(w['b'], dx, dy))
        if 'openings' in w:
            sh = dx if o == 'h' else dy
            w2['openings'] = [{'type': op['type'], 'from': round(op['from'] + sh), 'to': round(op['to'] + sh)} for op in w['openings']]
        walls.append(w2)
    structs = [dict(s_, at=shift_pt(s_['at'], dx, dy)) for s_ in F['structs']]
    def sr(r): return [round(r[0] + dx), round(r[1] + dy), round(r[2] + dx), round(r[3] + dy)]
    cand = {'stairs': [dict(s_, rect=sr(s_['rect'])) for s_ in F['cand']['stairs']],
            'elevator': [dict(e, rect=sr(e['rect'])) for e in F['cand']['elevator']],
            'voids': [dict(v, rect=sr(v['rect'])) for v in F['cand']['voids']]}
    if 'stair_zone' in F['cand']: cand['stair_zone'] = sr(F['cand']['stair_zone'])
    # imwrite silently fails on Windows paths containing Chinese characters.
    for filename, pixels in [(f'floor{i}.png', F['under']), (f'check{i}.png', F['chk'])]:
        ok, encoded = cv2.imencode('.png', pixels)
        if not ok: raise RuntimeError(f'PNG encoding failed: {filename}')
        encoded.tofile(os.path.join(a.out, filename))
    # 每层的干净 DXF（mm，对齐后的坐标；y 朝上）
    if ezdxf:
        dd = ezdxf.new('R2010'); dd.header['$INSUNITS'] = 4; ms = dd.modelspace(); bx0, by0 = F['to_origin']
        for j in F['idx']:
            x0, y0, x1, y1 = S[j]; lay = SL[j] or ('C' + SC[j].lstrip('#').split(':')[0])
            if lay not in dd.layers: dd.layers.add(lay)
            p0 = ((x0 - bx0) * unit + dx, -((y0 - by0) * unit + dy)); p1 = ((x1 - bx0) * unit + dx, -((y1 - by0) * unit + dy))
            ms.add_line(p0, p1, dxfattribs={'layer': lay, 'true_color': int(SC[j].lstrip('#').split(':')[0], 16)})
        dd.saveas(os.path.join(a.out, f'floor{i}.dxf'))
    spec_floors.append({'name': names[i], 'height': 3000, 'walls': walls, 'structs': structs, 'rooms': [], 'furniture': [], 'voids': [], 'autoElec': True,
                        'underlay': {'image': f'floor{i}.png', 'mmPerPx': 8.0, 'x': round(dx), 'y': round(dy)}, '_candidates': cand})
    report['floors'].append({'name': names[i], 'wall_color': F['wall_color'], 'walls': len(walls), 'openings': F['ops'], 'columns': len(structs),
                             'rooms_seen': F['rooms'], 'shift_to_first_floor_mm': [round(shifts[i][0]), round(shifts[i][1])], 'candidates': {k: len(v) for k, v in cand.items() if isinstance(v, list)}})
draft = {'name': os.path.splitext(os.path.basename(a.file))[0], 'slab': 120, 'base': 0, 'floors': spec_floors,
         '_notes': ['楼层顺序默认按图纸排列（--order），请按楼梯能否接上核对：下层上行梯段的终点应落在上层楼梯起步处',
                    '层高默认 3000：按图上的层高 / 标高标注改；门的开向、窗台高、房间名、家具都要补',
                    '_candidates 里的楼梯 / 电梯 / 开洞是候选：楼梯写成家具 stairU / stairRun，电梯写 elevator，开洞写 voids（电梯井加 "shaft": true）；确认后删掉 _candidates']}
json.dump(draft, open(os.path.join(a.out, 'building_draft.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
json.dump(report, open(os.path.join(a.out, 'report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(report, ensure_ascii=False, indent=1))
