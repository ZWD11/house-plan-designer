"""
CAD 图纸（矢量 PDF / DXF）精确识别：直接读图元坐标，不靠像素识图，墙体误差 < 5mm。

适用：设计院 / 装修公司 / 量房软件从 CAD 导出的 PDF（打印成 PDF、虚拟打印机都行，只要不是扫描件）、
DXF（AutoCAD / 天正 / 浩辰“另存为 DXF”；DWG 先另存为 DXF，或用 ODA File Converter 转）。
扫描件、截图这类位图仍然用 analyze.py。

用法:
  python cadvec.py 图纸.pdf --total-width 10540 [--page 0] [--out 输出目录]
  python cadvec.py 图纸.pdf --scale 22.242           # 已知 mm/pt（PDF 按 1:100 出图时 = 35.28）
  python cadvec.py 图纸.pdf --ratio 100              # 已知出图比例 1:100（PDF 纸面 1pt = 0.3528mm）
  python cadvec.py 图纸.dxf                           # DXF 自带单位，不用比例

按国标《房屋建筑制图统一标准》GB/T 50001、《建筑制图标准》GB/T 50104 和装修图惯例识别：
  - 实心涂黑的墙 / 柱 = 钢筋混凝土（剪力墙、柱）或原有承重墙            → bearing（厚 ≥ --bearing-min）
  - 灰色实心的墙                                                       → 非承重原墙
  - 砖纹 / 斜线 / 网格填充的墙（PDF 里是一片细短线，DXF 里是图案 HATCH） → 新砌墙 status=new（装修图惯例；--hatch-as existing 改成原墙）
  - 两条粗实线、中间留白的墙带                                          → 轻质隔墙 / 砌体墙（非承重）
  - 墙线上 3~4 条平行细线                                              → 窗（中间有错开两段 = 推拉窗；伸出外墙面 = 飘窗）
  - 墙上断口：有 90°/45° 开启弧线 = 平开门（弧心 = 门轴，弧在哪侧就往哪侧开；两段弧 = 双开 / 子母门）；
    断口里一条沿墙线的单线 = 门扇（多为入户门）；什么都没有 = 门洞；彩色矩形框 = 改造新开洞口
  - 方框里画对角线（⊠ / ╱）= 烟道 / 风道 / 管井；圆里十字（⊕）= 地漏；单个小圆 = 立管
  - 墙外的直线上带 45° 短斜杠（起止符号）= 尺寸线，斜杠位置 = 刻度；有文字层时自动读出标注数字核对比例
  - 单点长画线（虚线）+ 圆圈编号 = 定位轴线；DXF 按图层名识别（WALL / 墙、WINDOW / 窗、DOOR / 门、COLUMN / 柱、AXIS / 轴、DIM / 尺寸、家具洁具层排除）
  - 文字层里的房间名（卧室、客厅……）→ 房间标签；M0921 / C1515 这类门窗编号 → 洞口宽高；“离地 900 / H:1300” → 窗台高、窗高

输出（默认 <图纸名>_cad/）:
  cad.json    比例、墙段（P 编号，按图元精确到 mm）、合并后的墙线（W 编号）、门窗（O 编号，带判断依据）、符号、尺寸线刻度、文字、轴线
  draft.json  HouseSpec 初稿：墙（含 flush、status、bearing）、门窗（门带 hinge / into）、结构（管井、地漏、柱）、房间标签（有文字层时）、底图
  cad.png     核对图：墙段按类型着色 + 编号、门窗框、符号、尺寸刻度，背景是 1m 网格（毫米坐标），直接读坐标
  underlay.png  底图（PDF 按 200dpi 渲染；DXF 把线画出来），draft.json 已写好底图比例和位置
依赖: pip install numpy opencv-python pymupdf ezdxf
"""
import argparse, json, math, os, re, sys
from collections import Counter, defaultdict
import numpy as np
import cv2
sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8')

ap = argparse.ArgumentParser()
ap.add_argument('file')
ap.add_argument('--page', type=int, default=0)
ap.add_argument('--total-width', type=float, help='墙体外轮廓总宽 mm（最外道尺寸）')
ap.add_argument('--total-height', type=float, help='墙体外轮廓总深 mm')
ap.add_argument('--scale', type=float, help='mm / 图纸单位（PDF 是 pt）')
ap.add_argument('--ratio', type=float, help='出图比例 1:N 的 N（PDF 1pt = 0.35278mm 纸面）')
ap.add_argument('--bearing-min', type=float, default=180, help='实心墙厚度 ≥ 这个值算承重（mm）')
ap.add_argument('--hatch-as', choices=['new', 'existing'], default='new', help='填充图案墙：new = 新砌墙（装修图），existing = 原有非承重墙（建筑施工图里的砌体墙）')
ap.add_argument('--max-opening', type=float, default=4200, help='墙线上多宽以内的断口算门窗洞口（mm）')
ap.add_argument('--dpi', type=int, default=200, help='PDF 底图渲染精度')
ap.add_argument('--px', type=float, default=8, help='核对图 cad.png 每像素多少 mm')
ap.add_argument('--no-dims', action='store_true', help='不按尺寸数字校正坐标（只用整体比例）')
ap.add_argument('--out')
a = ap.parse_args()

ROOM_RE = re.compile(r'(主卧|次卧|卧室|老人房|儿童房|客房|保姆房|客厅|起居|餐厅|客餐厅|厨房|主卫|次卫|公卫|卫生间|洗手间|淋浴|阳台|生活阳台|景观阳台|露台|书房|茶室|衣帽间|玄关|门厅|过道|走廊|储藏|储物|杂物|设备平台|空调位|洗衣|多功能|影音|健身|入户花园)')
CODE_RE = re.compile(r'^(FM|TLM|MLC|JLM|M|TC|GC|PC|BYC|LC|C)[A-Z]?(\d{2})(\d{2})')
LAYER = {
    'wall': re.compile(r'wall|墙|^a-wall|qiang|^wa', re.I), 'window': re.compile(r'wind|窗|glaz|chuang', re.I),
    'door': re.compile(r'door|门|^men', re.I), 'column': re.compile(r'colu|柱|zhu', re.I),
    'axis': re.compile(r'axis|轴|dote|grid|^center', re.I), 'dim': re.compile(r'dim|尺寸|标注', re.I),
    'furn': re.compile(r'furn|家具|equip|洁具|sanit|厨具|plumb|elec|电|灯|land|绿化|tile|地面|地砖|ceil|顶', re.I),
}
SKIP_LAYER = re.compile(r'frame|title|tk$|图框|标题|^anno$|north|指北|pub_title', re.I)
def layer_kind(name):
    for k, r in LAYER.items():
        if name and r.search(name): return k
    return ''

# ------------------------------------------------------------------ 1. 读图元（统一成：填充多边形、描边折线、圆弧、文字）
fills, strokes, arcs, texts, dimsx, inserts = [], [], [], [], [], []
src_kind = os.path.splitext(a.file)[1].lower()
unit_mm = None        # 图纸单位 → mm（DXF 已知；PDF 要靠比例）
render_pdf = None

def bez(p0, p1, p2, p3, n=8):
    return [((1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t * t * p2[0] + t ** 3 * p3[0],
             (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t * t * p2[1] + t ** 3 * p3[1]) for t in np.linspace(0, 1, n + 1)[1:]]

if src_kind == '.pdf':
    import fitz
    doc = fitz.open(a.file); pg = doc[a.page]
    if not pg.get_drawings() and pg.get_images(): sys.exit('这一页只有位图（扫描件 / 截图转的 PDF），没有矢量图元：先导出成图片再用 analyze.py')
    _drs = pg.get_drawings()
    # 只描边、但和某个填充形状轮廓完全重合的路径 = 文字笔画（SHX 字体）的描边，不当图形用
    _fill_rects = {tuple(round(v, 1) for v in d['rect']) for d in _drs if d['type'] == 'f'}
    for d in _drs:
        subs, cur = [], []
        def flush():
            global cur
            if len(cur) > 1: subs.append(cur)
            cur = []
        for it in d['items']:
            k = it[0]
            if k == 'l':
                p, q = (it[1].x, it[1].y), (it[2].x, it[2].y)
                if not cur or abs(cur[-1][0] - p[0]) + abs(cur[-1][1] - p[1]) > 1e-3: flush(); cur = [p]
                cur.append(q)
            elif k == 'c':
                ps = [(t.x, t.y) for t in it[1:5]]
                if not cur or abs(cur[-1][0] - ps[0][0]) + abs(cur[-1][1] - ps[0][1]) > 1e-3: flush(); cur = [ps[0]]
                cur += bez(*ps)
            elif k == 're':
                flush(); r = it[1]; subs.append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)])
            elif k == 'qu':
                flush(); q = it[1]; subs.append([(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y), (q.ul.x, q.ul.y)])
        flush()
        fill, col, w = d.get('fill'), d.get('color'), d.get('width') or 0
        dashed = str(d.get('dashes') or '').strip() not in ('', '[] 0', '[] 0.0', 'None')
        if d['type'] in ('f', 'fs') and fill is not None:
            for s in subs:
                if len(s) >= 3: fills.append(dict(poly=s, color=tuple(fill), kind='', layer='', grp=id(d)))
        if d['type'] in ('s', 'fs') and col is not None:
            for s in subs: strokes.append(dict(pts=s, color=tuple(col), width=w, dashed=dashed, layer='', filled=d['type'] == 'fs' or tuple(round(v, 1) for v in d['rect']) in _fill_rects))
    for x0, y0, x1, y1, w, *_ in pg.get_text('words'):
        texts.append(dict(x=(x0 + x1) / 2, y=(y0 + y1) / 2, text=w.strip(), h=y1 - y0))
    render_pdf = pg
elif src_kind == '.dxf':
    import ezdxf
    from ezdxf import path as ezpath
    doc = ezdxf.readfile(a.file)
    unit_mm = {0: 1, 1: 25.4, 2: 304.8, 4: 1, 5: 10, 6: 1000, 14: 100}.get(doc.header.get('$INSUNITS', 0), 1)
    lt_of_layer = {L.dxf.name: (L.dxf.linetype or '') for L in doc.layers}
    ACI = {1: (1, 0, 0), 2: (1, 1, 0), 3: (0, 1, 0), 4: (0, 1, 1), 5: (0, 0, 1), 6: (1, 0, 1), 7: (0, 0, 0), 8: (.5, .5, .5), 9: (.75, .75, .75)}
    col_of_layer = {L.dxf.name: ACI.get(abs(L.dxf.color), (0, 0, 0)) for L in doc.layers}
    def ent_color(e, layer):
        c = e.dxf.get('color', 256)
        return col_of_layer.get(layer, (0, 0, 0)) if c in (0, 256) else ACI.get(c, (0, 0, 0))
    def add_path(p, layer, e, closed=False):
        pts = [(v.x, v.y) for v in p.flattening(1.0)]
        if len(pts) > 1:
            lt = (e.dxf.get('linetype', 'BYLAYER') or 'BYLAYER').upper()
            if lt == 'BYLAYER': lt = lt_of_layer.get(layer, '').upper()
            strokes.append(dict(pts=pts, color=ent_color(e, layer), width=0, dashed=lt not in ('', 'CONTINUOUS', 'BYBLOCK'), layer=layer))
    def walk(ents, parent_layer='', depth=0):
        for e in ents:
            t = e.dxftype(); layer = e.dxf.get('layer', '0')
            if layer == '0' and parent_layer: layer = parent_layer
            if SKIP_LAYER.search(layer or ''): continue  # 图框、标题栏、图名、指北针不是户型的一部分
            try:
                if t == 'INSERT':
                    inserts.append(dict(name=e.dxf.name, x=e.dxf.insert.x, y=e.dxf.insert.y, layer=layer, rot=e.dxf.get('rotation', 0)))
                    if depth < 6: walk(e.virtual_entities(), layer, depth + 1)
                elif t == 'DIMENSION':
                    try: val = e.get_measurement()
                    except Exception: val = None
                    _ov = (e.dxf.get('text', '') or '').strip()
                    if re.fullmatch(r'\d+(\.\d+)?', _ov): val = float(_ov)  # 标注文字被改写过：以文字为准
                    p2, p3 = e.dxf.get('defpoint2'), e.dxf.get('defpoint3')
                    if p2 and p3 and isinstance(val, (int, float)): dimsx.append(dict(p1=(p2.x, p2.y), p2=(p3.x, p3.y), value=float(val), layer=layer))
                elif t == 'HATCH':
                    solid = bool(e.dxf.get('solid_fill', 0)) or (e.dxf.get('pattern_name', '') or '').upper() == 'SOLID'
                    for p in ezpath.from_hatch(e):
                        pts = [(v.x, v.y) for v in p.flattening(1.0)]
                        if len(pts) >= 3: fills.append(dict(poly=pts, color=ent_color(e, layer) if solid else (.5, .5, .5), kind='' if solid else 'hatch', layer=layer, pattern=e.dxf.get('pattern_name', ''), grp=id(e)))
                elif t in ('SOLID', 'TRACE'):
                    v = [e.dxf.vtx0, e.dxf.vtx1, e.dxf.vtx3, e.dxf.vtx2]
                    fills.append(dict(poly=[(p.x, p.y) for p in v], color=ent_color(e, layer), kind='', layer=layer))
                elif t in ('TEXT', 'ATTRIB', 'MTEXT'):
                    s = e.plain_text() if t == 'MTEXT' else e.dxf.text
                    p = e.dxf.insert
                    h = e.dxf.get('char_height' if t == 'MTEXT' else 'height', 300)
                    if t != 'MTEXT':
                        # 文字位置取文字中心：有对齐方式的用对齐点（11），左下角对齐的按估算字宽往右挪半个字宽
                        ha, va = e.dxf.get('halign', 0), e.dxf.get('valign', 0)
                        if (ha or va) and e.dxf.hasattr('align_point'):
                            p = e.dxf.align_point
                        else:
                            n = sum(1.0 if ord(ch) > 255 else .6 for ch in (s or '')) * h * e.dxf.get('width', 1) * .5
                            ang = math.radians(e.dxf.get('rotation', 0))
                            p = ezdxf.math.Vec3(p.x + n * math.cos(ang), p.y + n * math.sin(ang), 0)
                    s = re.sub(r'\\U\+([0-9A-Fa-f]{4})', lambda m: chr(int(m.group(1), 16)), s or '')  # R12 / R2000 用 \U+XXXX 存中文
                    for part in re.split(r'\n|\\P', s):
                        if part.strip(): texts.append(dict(x=p.x, y=p.y, text=part.strip(), h=h, layer=layer))
                elif t in ('ARC', 'CIRCLE'):
                    c = e.dxf.center; r = e.dxf.radius
                    a0, a1 = (e.dxf.start_angle, e.dxf.end_angle) if t == 'ARC' else (0, 360)
                    arcs.append(dict(c=(c.x, c.y), r=r, a0=a0, a1=a1, layer=layer, full=t == 'CIRCLE'))
                    add_path(ezpath.make_path(e), layer, e)
                elif t == 'LINE':
                    s, q = e.dxf.start, e.dxf.end
                    add_path(ezpath.from_vertices([s, q]), layer, e)
                elif t in ('LWPOLYLINE', 'POLYLINE', 'SPLINE', 'ELLIPSE'):
                    p = ezpath.make_path(e); add_path(p, layer, e)
                    if t == 'LWPOLYLINE' and e.closed and (e.dxf.get('const_width', 0) or 0) > 0:
                        fills.append(dict(poly=[(v.x, v.y) for v in p.flattening(1.0)], color=ent_color(e, layer), kind='', layer=layer))
            except Exception as ex:  # 个别畸形图元跳过
                print(f'跳过 {t}: {ex}', file=sys.stderr)
    walk(doc.modelspace())
    # DXF 的 y 轴朝上，翻成朝下（和户型描述一致：y 向南）
    flip = lambda p: (p[0], -p[1])
    for f in fills: f['poly'] = [flip(p) for p in f['poly']]
    for s in strokes: s['pts'] = [flip(p) for p in s['pts']]
    for c in arcs: c['c'] = flip(c['c']); c['a0'], c['a1'] = -c['a1'], -c['a0']
    for t in texts: t['y'] = -t['y']
    for d in dimsx: d['p1'], d['p2'] = flip(d['p1']), flip(d['p2'])
    for i in inserts: i['y'] = -i['y']
else:
    sys.exit('只支持 .pdf（CAD 矢量导出）和 .dxf；DWG 请先另存为 DXF；图片请用 analyze.py')

# 黑底图纸（CAD 模型空间截图、深色背景打印）：一个铺满页面的深色填充 = 背景，亮色才是墙
INVERT = False
if fills:
    _ax = [p[0] for f in fills for p in f['poly']] + [p[0] for s_ in strokes for p in s_['pts']]
    _ay = [p[1] for f in fills for p in f['poly']] + [p[1] for s_ in strokes for p in s_['pts']]
    _area = (max(_ax) - min(_ax)) * (max(_ay) - min(_ay))
    for f in list(fills):
        xs_, ys_ = [p[0] for p in f['poly']], [p[1] for p in f['poly']]
        if (max(xs_) - min(xs_)) * (max(ys_) - min(ys_)) > .6 * _area:
            if .299 * f['color'][0] + .587 * f['color'][1] + .114 * f['color'][2] < .35: INVERT = True
            fills.remove(f)  # 背景板 / 图框底色
has_layers = any(s['layer'] for s in strokes)
wall_layers = has_layers and any(layer_kind(s['layer']) == 'wall' for s in strokes + fills)

# ------------------------------------------------------------------ 2. 线段化：所有描边拆成线段，挑出水平 / 竖直线段
segs = []  # (x0,y0,x1,y1, stroke_idx)
for i, s in enumerate(strokes):
    for p, q in zip(s['pts'], s['pts'][1:]):
        if abs(p[0] - q[0]) + abs(p[1] - q[1]) > 1e-6: segs.append((p[0], p[1], q[0], q[1], i))
def seg_len(g): return math.hypot(g[2] - g[0], g[3] - g[1])
def axis_of(g, tol=.02):
    dx, dy = abs(g[2] - g[0]), abs(g[3] - g[1]); L = math.hypot(dx, dy)
    if L == 0: return None
    return 'h' if dy / L < tol else 'v' if dx / L < tol else None

def luminance(c):
    L = .299 * c[0] + .587 * c[1] + .114 * c[2]
    return 1 - L if INVERT else L

# 主线型：总长最长的 (颜色, 线宽) —— 墙线、门窗线一般都是它
style_len = Counter()
for g in segs:
    s = strokes[g[4]]
    if s['dashed'] or s.get('filled'): continue  # 虚线（轴线）、文字笔画不算
    style_len[(tuple(round(v, 2) for v in s['color']), round(s['width'], 2))] += seg_len(g)
main_style = style_len.most_common(1)[0][0] if style_len else None

# ------------------------------------------------------------------ 3. 实心填充 → 墙段（坐标压缩后按格子拆成水平 / 竖直矩形，精确无误差）
def is_ortho(poly, tol=1e-3):
    for p, q in zip(poly, poly[1:] + poly[:1]):
        dx, dy = abs(p[0] - q[0]), abs(p[1] - q[1])
        if dx > tol * 50 and dy > tol * 50: return False
    return True

def rect_pieces(polys, eps):
    """正交多边形并集 → 水平 / 竖直墙段 [(orient, c, t, s0, s1, cells)]（单位同输入）"""
    if not polys: return []
    _pp = [pl[0] if isinstance(pl, tuple) else pl for pl in polys]
    xs = sorted(set(round(p[0] / eps) * eps for pl in _pp for p in pl)); ys = sorted(set(round(p[1] / eps) * eps for pl in _pp for p in pl))
    xi = {v: i for i, v in enumerate(xs)}; yi = {v: i for i, v in enumerate(ys)}
    nx, ny = len(xs), len(ys)
    if nx < 2 or ny < 2: return []
    canvas = np.zeros((2 * ny, 2 * nx), np.uint8)
    # 同一个路径里的多个闭合圈按奇偶规则填（外圈减内圈 = 带洞的形状），不同路径之间取并集
    by_grp = defaultdict(list)
    for k, pl in enumerate(polys): by_grp[pl[1] if isinstance(pl, tuple) else k].append(pl[0] if isinstance(pl, tuple) else pl)
    for grp, pls in by_grp.items():
        layer = np.zeros_like(canvas)
        for pl in pls:
            pts = np.array([[2 * xi[round(p[0] / eps) * eps], 2 * yi[round(p[1] / eps) * eps]] for p in pl], np.int32)
            one = np.zeros_like(canvas); cv2.fillPoly(one, [pts], 1); layer ^= one
        canvas |= layer
    grid = canvas[1::2, 1::2][:ny - 1, :nx - 1].astype(bool)  # 格子中心
    cw, ch = np.diff(xs), np.diff(ys)
    # 每个格子所在水平连续段 / 竖直连续段的实际长度
    HL = np.zeros(grid.shape); VL = np.zeros(grid.shape)
    for j in range(grid.shape[0]):
        i = 0
        while i < grid.shape[1]:
            if grid[j, i]:
                k = i
                while k < grid.shape[1] and grid[j, k]: k += 1
                HL[j, i:k] = cw[i:k].sum(); i = k
            else: i += 1
    for i in range(grid.shape[1]):
        j = 0
        while j < grid.shape[0]:
            if grid[j, i]:
                k = j
                while k < grid.shape[0] and grid[k, i]: k += 1
                VL[j:k, i] = ch[j:k].sum(); j = k
            else: j += 1
    out = []
    for orient, m in (('h', grid & (HL >= VL)), ('v', grid & (VL > HL))):
        n, lab = cv2.connectedComponents(m.astype(np.uint8), connectivity=4)
        for k in range(1, n):
            jj, ii = np.nonzero(lab == k)
            # 沿墙方向逐列（竖墙逐行）看横截面；横截面一样的相邻列合成一段（L 形、墙垛处会拆开）
            along, cross = (ii, jj) if orient == 'h' else (jj, ii)
            A, C = (xs, ys) if orient == 'h' else (ys, xs)
            prof = {}
            for u in np.unique(along):
                cs = cross[along == u]; prof[int(u)] = (int(cs.min()), int(cs.max()))
            keys = sorted(prof); runs_, cur_ = [], [keys[0]]
            for u in keys[1:]:
                if u == cur_[-1] + 1 and prof[u] == prof[cur_[-1]]: cur_.append(u)
                else: runs_.append(cur_); cur_ = [u]
            runs_.append(cur_)
            for r_ in runs_:
                c0_, c1_ = prof[r_[0]]
                lo, hi = C[c0_], C[c1_ + 1]
                out.append((orient, (lo + hi) / 2, hi - lo, A[r_[0]], A[r_[-1] + 1], len(r_)))
    return out

allpts = [p for f in fills for p in f['poly']] + [p for s in strokes for p in s['pts']]
span = max(max(p[0] for p in allpts) - min(p[0] for p in allpts), max(p[1] for p in allpts) - min(p[1] for p in allpts)) if allpts else 1
EPS = span * 2e-5

def fill_class(f):
    if f['kind'] == 'hatch': return 'hatch'
    lk = layer_kind(f['layer'])
    if lk in ('furn', 'dim', 'axis'): return None
    L = luminance(f['color'])
    if L < .3: return 'solid'
    if L < .85: return 'grey'
    return None  # 白色 / 浅色填充一般是遮挡块（wipeout），不当墙

pieces = []  # dict(orient,c,t,s0,s1,kind)
groups = defaultdict(list)
for f in fills:
    k = fill_class(f)
    if k and is_ortho(f['poly']): groups[k].append((f['poly'], f.get('grp', id(f))))
for k, polys in groups.items():
    for o, c, t, s0, s1, n in rect_pieces(polys, EPS):
        pieces.append(dict(orient=o, c=c, t=t, s0=s0, s1=s1, kind=k))

# 典型墙厚（图纸单位）：实心墙段里按长度加权最常见的厚度
def typical_t(ps):
    cnt = Counter()
    for p in ps:
        if p['s1'] - p['s0'] >= 3 * p['t']: cnt[round(p['t'] / (EPS * 50)) * EPS * 50] += p['s1'] - p['s0']
    return cnt.most_common(1)[0][0] if cnt else None
T = typical_t(pieces)

# ------------------------------------------------------------------ 4. 尺寸线：直线上落着 ≥2 个 45° 短斜杠（或 DXF 的标注图元）
def is_tick_shape(xs_, ys_, poly_area=None):
    w, h = max(xs_) - min(xs_), max(ys_) - min(ys_)
    if w == 0 or h == 0: return False
    if not (.5 < w / h < 2): return False
    return poly_area is None or poly_area < .35 * w * h
ticks = []  # (x, y, size)
for f in fills:
    xs_, ys_ = [p[0] for p in f['poly']], [p[1] for p in f['poly']]
    ar = abs(cv2.contourArea(np.array(f['poly'], np.float32)))
    if is_tick_shape(xs_, ys_, ar): ticks.append(((min(xs_) + max(xs_)) / 2, (min(ys_) + max(ys_)) / 2, max(max(xs_) - min(xs_), max(ys_) - min(ys_))))
for g in segs:
    if axis_of(g, .3) is None and is_tick_shape([g[0], g[2]], [g[1], g[3]]):
        ticks.append(((g[0] + g[2]) / 2, (g[1] + g[3]) / 2, max(abs(g[2] - g[0]), abs(g[3] - g[1]))))
# 起止符号一定落在一条长直线（尺寸线）上；不在线上的小方块是文字、符号
_ax_segs = [g for g in segs if axis_of(g)]
def _on_line(t):
    for g in _ax_segs:
        L = seg_len(g)
        if L < t[2] * 3: continue
        if axis_of(g) == 'h' and abs((g[1] + g[3]) / 2 - t[1]) < t[2] * .25 and min(g[0], g[2]) - t[2] <= t[0] <= max(g[0], g[2]) + t[2]: return True
        if axis_of(g) == 'v' and abs((g[0] + g[2]) / 2 - t[0]) < t[2] * .25 and min(g[1], g[3]) - t[2] <= t[1] <= max(g[1], g[3]) + t[2]: return True
    return False
# 起止符号的大小和墙厚同一个量级（1:100 出图约 2~3mm 纸面 ≈ 墙厚的 0.1~0.8）；文字碎片、填充图案更小，先按大小筛
if T: ticks = [t for t in ticks if .08 * T <= t[2] <= 1.6 * T]  # 1:150 出图时起止符号可到墙厚的 1.5 倍
if len(ticks) < 6000: ticks = [t for t in ticks if _on_line(t)]
tick_size = float(np.median([t[2] for t in ticks])) if ticks else 0
# 一个斜杠常由两三个三角形 / 线段拼成：中心挨得很近的合成一个，取平均位置
_cl = []
for t in sorted(ticks):
    for c_ in _cl:
        if abs(c_[0] / c_[3] - t[0]) < tick_size * .4 and abs(c_[1] / c_[3] - t[1]) < tick_size * .4:
            c_[0] += t[0]; c_[1] += t[1]; c_[2] = max(c_[2], t[2]); c_[3] += 1; break
    else: _cl.append([t[0], t[1], t[2], 1])
ticks = [(c_[0] / c_[3], c_[1] / c_[3], c_[2]) for c_ in _cl]
if os.environ.get('CADDBG'): print('TICKS', len(ticks), 'size', tick_size, file=sys.stderr)
dim_seg = set()
dim_lines = []
if ticks:
    tk = np.array([(t[0], t[1]) for t in ticks])
    for gi, g in enumerate(segs):
        o = axis_of(g)
        if not o or seg_len(g) < tick_size * 3: continue
        if o == 'h':
            y = (g[1] + g[3]) / 2; x0, x1 = sorted((g[0], g[2]))
            on = tk[(np.abs(tk[:, 1] - y) < tick_size * .35) & (tk[:, 0] > x0 - tick_size) & (tk[:, 0] < x1 + tick_size)]
            pos = sorted(on[:, 0])
        else:
            x = (g[0] + g[2]) / 2; y0, y1 = sorted((g[1], g[3]))
            on = tk[(np.abs(tk[:, 0] - x) < tick_size * .35) & (tk[:, 1] > y0 - tick_size) & (tk[:, 1] < y1 + tick_size)]
            pos = sorted(on[:, 1])
        # 尺寸线两头只比最外的起止符号多出一点点；起止符号落在长线中间的（别的尺寸线的端点碰巧在墙线上）不算
        ends = (x0, x1) if o == 'h' else (y0, y1)
        if len(pos) >= 2 and pos[0] - ends[0] < tick_size * 1.6 and ends[1] - pos[-1] < tick_size * 1.6:
            dim_seg.add(gi)
            dim_lines.append(dict(orient=o, at=(g[1] + g[3]) / 2 if o == 'h' else (g[0] + g[2]) / 2, ticks=[float(p) for p in pos]))
# 同一条尺寸线可能被拆成多段：按位置合并刻度
merged_dims = []
for d in sorted(dim_lines, key=lambda d: (d['orient'], d['at'])):
    m = merged_dims[-1] if merged_dims else None
    if m and m['orient'] == d['orient'] and abs(m['at'] - d['at']) < tick_size * .3:
        m['ticks'] = sorted(set(round(t, 3) for t in m['ticks'] + d['ticks']))
    else: merged_dims.append(dict(d))
for d in merged_dims:  # 相邻太近的刻度去重（取平均）
    out = []
    for t in sorted(d['ticks']):
        if out and t - out[-1][-1] <= tick_size * .4: out[-1].append(t)
        else: out.append([t])
    d['ticks'] = [float(np.mean(g)) for g in out]
# 每个刻度的尺寸界线：过刻度、垂直于尺寸线的那根线，它的另一头就是被量的构件（墙面）所在的位置
_perp = {'h': [g for g in segs if axis_of(g) == 'v'], 'v': [g for g in segs if axis_of(g) == 'h']}
for d in merged_dims:
    feet = []
    for t in d['ticks']:
        best = None
        for g in _perp[d['orient']]:
            pos = (g[0] + g[2]) / 2 if d['orient'] == 'h' else (g[1] + g[3]) / 2
            if abs(pos - t) > tick_size * .3: continue
            e0, e1 = (g[1], g[3]) if d['orient'] == 'h' else (g[0], g[2])
            if min(abs(e0 - d['at']), abs(e1 - d['at'])) > tick_size * 2 and not (min(e0, e1) <= d['at'] <= max(e0, e1)): continue
            far = e0 if abs(e0 - d['at']) > abs(e1 - d['at']) else e1
            if best is None or abs(far - d['at']) > abs(best - d['at']): best = far
        feet.append(best if best is not None else d['at'])
    d['feet'] = feet
# 一条“尺寸线”上若有文字层数字，配对读出比例
def scale_from_dim_text():
    if not texts: return None
    ests = []
    for d in merged_dims:
        for t0, t1 in zip(d['ticks'], d['ticks'][1:]):
            mid = (t0 + t1) / 2
            for tx in texts:
                if not re.fullmatch(r'\d{2,6}', tx['text']): continue
                along, perp = (tx['x'], tx['y']) if d['orient'] == 'h' else (tx['y'], tx['x'])
                if abs(along - mid) < (t1 - t0) / 2 and abs(perp - d['at']) < max(tx['h'] * 2.5, tick_size * 3):
                    ests.append(float(tx['text']) / (t1 - t0))
    for d in dimsx:
        L = math.dist(d['p1'], d['p2'])
        if L > 0 and d['value']: ests.append(d['value'] / L)
    if len(ests) >= 3:
        med = float(np.median(ests)); good = [e for e in ests if abs(e / med - 1) < .02]
        if len(good) >= max(3, len(ests) * .5): return float(np.mean(good)), len(good), len(ests)
    return None

# ------------------------------------------------------------------ 5. 描边墙带：两条平行线之间 = 墙；中间有 ≥1 条平行线 = 窗；中间是细短线 = 填充图案墙
if T is None:
    # 没有实心墙：用墙图层（或主线型）的平行线间距估墙厚
    cand = [g for gi, g in enumerate(segs) if gi not in dim_seg and axis_of(g) and (not wall_layers or layer_kind(strokes[g[4]]['layer']) == 'wall')]
    spans = Counter()
    hs = sorted([g for g in cand if axis_of(g) == 'h'], key=lambda g: g[1])
    for i, g in enumerate(hs[:3000]):
        for q in hs[i + 1:i + 40]:
            dy = abs(q[1] - g[1])
            if dy <= 0: continue
            ov = min(max(g[0], g[2]), max(q[0], q[2])) - max(min(g[0], g[2]), min(q[0], q[2]))
            if ov > dy * 4: spans[round(dy / (EPS * 50)) * EPS * 50] += ov
    T = spans.most_common(1)[0][0] if spans else span / 60
if not T or T <= 0:
    sys.exit('没认出墙厚：这张图可能是一页里并排好几层平面、或墙是描边画法且在交接处全部断开（量房软件导出的常见画法）。'
             '改用 cadsplit.py（按楼层切开、描边墙识别、输出整栋楼初稿）：python cadsplit.py 图纸 --out 目录 [--ref-dim 最外道总尺寸]')

def hatch_like(g):
    s = strokes[g[4]]
    lk = layer_kind(s['layer'])
    if lk in ('furn', 'dim', 'axis', 'window', 'door'): return False
    st = (tuple(round(v, 2) for v in s['color']), round(s['width'], 2))
    return seg_len(g) < T * 1.3 and (st != main_style or (s['layer'] and re.search(r'hatch|填充|pattern', s['layer'], re.I)))

# 尺寸界线：端点落在尺寸刻度上的线（不是墙线）
if ticks:
    tk2 = np.array([(t[0], t[1]) for t in ticks])
    for gi, g in enumerate(segs):
        if gi in dim_seg: continue
        for px_, py_ in ((g[0], g[1]), (g[2], g[3])):
            if (np.hypot(tk2[:, 0] - px_, tk2[:, 1] - py_) < tick_size * .5).any(): dim_seg.add(gi); break
# 房子范围：实心墙的包围盒外扩 2 个墙厚；之外的东西（尺寸、文字、图例、图框）不参与找墙
solid_ps = [p for p in pieces if p['kind'] in ('solid', 'grey') and p['s1'] - p['s0'] > 2 * p['t']]
if len(solid_ps) >= 4:
    _b = [(p['s0'], p['c'] - p['t'] / 2, p['s1'], p['c'] + p['t'] / 2) if p['orient'] == 'h' else (p['c'] - p['t'] / 2, p['s0'], p['c'] + p['t'] / 2, p['s1']) for p in solid_ps]
    REG = (min(q[0] for q in _b) - 2 * T, min(q[1] for q in _b) - 2 * T, max(q[2] for q in _b) + 2 * T, max(q[3] for q in _b) + 2 * T)
else:
    REG = None
def in_reg(g):
    return REG is None or (REG[0] <= min(g[0], g[2]) and max(g[0], g[2]) <= REG[2] and REG[1] <= min(g[1], g[3]) and max(g[1], g[3]) <= REG[3])
pieces = [p for p in pieces if REG is None or in_reg((p['s0'], p['c'], p['s1'], p['c']) if p['orient'] == 'h' else (p['c'], p['s0'], p['c'], p['s1']))]
hatch_segs = [g for gi, g in enumerate(segs) if gi not in dim_seg and hatch_like(g) and in_reg(g)]
if os.environ.get('CADDBG'): print('MAIN', main_style, 'T', T, 'hatch', len(hatch_segs), 'REG', REG, file=sys.stderr)
line_segs = []
for gi, g in enumerate(segs):
    if gi in dim_seg or strokes[g[4]]['dashed'] or not in_reg(g): continue
    o = axis_of(g)
    if not o or seg_len(g) < T * .4: continue
    lk = layer_kind(strokes[g[4]]['layer'])
    if lk in ('furn', 'dim', 'axis'): continue
    if wall_layers and lk not in ('wall', 'window', 'column', ''): continue
    st = (tuple(round(v, 2) for v in strokes[g[4]]['color']), round(strokes[g[4]]['width'], 2))
    if not has_layers and st != main_style and g in hatch_segs: continue
    if o == 'h': line_segs.append(dict(o='h', c=(g[1] + g[3]) / 2, s0=min(g[0], g[2]), s1=max(g[0], g[2]), lk=lk))
    else: line_segs.append(dict(o='v', c=(g[0] + g[2]) / 2, s0=min(g[1], g[3]), s1=max(g[1], g[3]), lk=lk))
# 同线相接的线段先合并
line_segs.sort(key=lambda q: (q['o'], round(q['c'] / (T * .02)), q['s0']))
ml = []
for q in line_segs:
    p = ml[-1] if ml else None
    if p and p['o'] == q['o'] and abs(p['c'] - q['c']) < T * .02 and q['s0'] <= p['s1'] + T * .02 and p['lk'] == q['lk']: p['s1'] = max(p['s1'], q['s1'])
    else: ml.append(dict(q))
line_segs = ml

def covered(o, c0, c1, s0, s1, kinds=('solid', 'grey', 'hatch')):
    """带区域被已有墙段覆盖的比例"""
    tot = 0
    for p in pieces:
        if p['orient'] != o or p['kind'] not in kinds: continue
        ov_c = min(c1, p['c'] + p['t'] / 2) - max(c0, p['c'] - p['t'] / 2)
        ov_s = min(s1, p['s1']) - max(s0, p['s0'])
        if ov_c > 0 and ov_s > 0: tot += ov_c * ov_s
    return tot / max(1e-9, (c1 - c0) * (s1 - s0))

def hatch_density(o, c0, c1, s0, s1):
    n = 0
    for g in hatch_segs:
        mx_, my_ = (g[0] + g[2]) / 2, (g[1] + g[3]) / 2
        along, perp = (mx_, my_) if o == 'h' else (my_, mx_)
        if s0 <= along <= s1 and c0 <= perp <= c1: n += 1
    return n / max(1e-9, (s1 - s0) / T)

def jamb(o, c0, c1, e, keep):
    # 洞口边上横跨墙厚的短线（洞口边线）：把按网格切出来的边界吸到它上面
    if abs(e - keep) < 1e-9: return e
    best = None
    for g in segs:
        if o == 'h' and abs(g[0] - g[2]) < 1e-3 and min(g[1], g[3]) <= c0 + (c1 - c0) * .2 and max(g[1], g[3]) >= c1 - (c1 - c0) * .2: pos = g[0]
        elif o == 'v' and abs(g[1] - g[3]) < 1e-3 and min(g[0], g[2]) <= c0 + (c1 - c0) * .2 and max(g[0], g[2]) >= c1 - (c1 - c0) * .2: pos = g[1]
        else: continue
        if abs(pos - e) < T * .5 and (best is None or abs(pos - e) < abs(best - e)): best = pos
    return best if best is not None else e

def make_band(o, L, p, q, dc, s0, s1):
    c0, c1 = p['c'], q['c']
    segs_free, cur0 = [], s0
    def _ab(z):  # 墙段在本方向上的 (沿线区间, 横向区间)
        if z['orient'] == o: return (z['s0'], z['s1']), (z['c'] - z['t'] / 2, z['c'] + z['t'] / 2)
        return (z['c'] - z['t'] / 2, z['c'] + z['t'] / 2), (z['s0'], z['s1'])
    cov = sorted((max(s0, al[0]), min(s1, al[1])) for z in pieces if z['kind'] in ('solid', 'grey', 'hatch')
                 for al, cr in [_ab(z)] if min(c1, cr[1]) - max(c0, cr[0]) > (c1 - c0) * .5 and min(s1, al[1]) > max(s0, al[0]))
    for z0, z1 in cov:
        if z0 > cur0: segs_free.append((cur0, z0))
        cur0 = max(cur0, z1)
    if s1 > cur0: segs_free.append((cur0, s1))
    for s0, s1 in [z for z in segs_free if z[1] - z[0] >= T * .8]:
        band_part(o, L, p, q, dc, c0, c1, s0, s1)

def band_part(o, L, p, q, dc, c0, c1, s0, s1):
    # 墙面线一直画过去、只有窗的那一段中间多了玻璃线：按玻璃线的范围切成 墙 / 窗 / 墙
    ins = sorted((max(s0, r['s0']), min(s1, r['s1'])) for r in L if c0 + T * .05 < r['c'] < c1 - T * .05 and min(r['s1'], s1) - max(r['s0'], s0) > T * .8)
    if ins and hatch_density(o, c0, c1, s0, s1) <= 1.5:
        mg = []
        for a0_, a1_ in ins:
            if mg and a0_ <= mg[-1][1] + T * .2: mg[-1][1] = max(mg[-1][1], a1_)
            else: mg.append([a0_, a1_])
        cov = sum(b_ - a_ for a_, b_ in mg)
        if cov < .85 * (s1 - s0):
            cur_ = s0
            for a_, b_ in mg:
                if a_ - cur_ >= T * .8: _band_core(o, L, p, q, dc, c0, c1, cur_, a_, force='outline')
                _band_core(o, L, p, q, dc, c0, c1, a_, b_)
                cur_ = b_
            if s1 - cur_ >= T * .8: _band_core(o, L, p, q, dc, c0, c1, cur_, s1, force='outline')
            return
    _band_core(o, L, p, q, dc, c0, c1, s0, s1)

def _band_core(o, L, p, q, dc, c0, c1, s0, s1, force=None):
    inner = [] if force else [r for r in L if c0 + T * .05 < r['c'] < c1 - T * .05 and min(r['s1'], s1) - max(r['s0'], s0) > (s1 - s0) * .5]
    hd = hatch_density(o, c0, c1, s0, s1)
    if hd > 1.5:
        # 填充墙的边线常常一直画过门洞：按“哪里有填充短线”把墙带切开
        nb = max(1, int((s1 - s0) / (T * .25)))
        filled = np.zeros(nb, bool)
        for g in hatch_segs:
            mx_, my_ = (g[0] + g[2]) / 2, (g[1] + g[3]) / 2
            al_, pp_ = (mx_, my_) if o == 'h' else (my_, mx_)
            if s0 <= al_ <= s1 and c0 <= pp_ <= c1: filled[min(nb - 1, int((al_ - s0) / (s1 - s0) * nb))] = True
        k0 = None
        for k in range(nb + 1):
            on = k < nb and filled[k]
            if not on and k < nb and k0 is not None and filled[k:min(nb, k + 6)].any(): on = True  # 图案线稀疏：空不到 1.5 个墙厚不算断
            if on and k0 is None: k0 = k
            if not on and k0 is not None:
                b0, b1 = s0 + (s1 - s0) * k0 / nb, s0 + (s1 - s0) * k / nb
                b0, b1 = jamb(o, c0, c1, b0, s0), jamb(o, c0, c1, b1, s1)
                if b1 - b0 >= T * .5: bands.append(dict(orient=o, c=(c0 + c1) / 2, t=dc, s0=b0, s1=b1, kind='hatch', inner=0, slide=False))
                k0 = None
        return
    win_layer = p['lk'] == 'window' or q['lk'] == 'window' or any(r['lk'] == 'window' for r in inner)
    if hd > 1.5: kind = 'hatch'
    elif inner or win_layer: kind = 'glazing'
    else: kind = 'outline'
    # 推拉窗：中间两条错开、各占一半左右
    slide = kind == 'glazing' and len(inner) >= 2 and all((r['s1'] - r['s0']) < (s1 - s0) * .8 for r in inner)
    if kind == 'outline':
        # 描边墙：两条边线首尾基本对齐、厚度在常见墙厚范围内（排除柜子、洁具、尺寸线和墙面线凑成的假墙）
        if dc > T * 1.15 or (not force and (abs(p['s0'] - q['s0']) > T * .6 or abs(p['s1'] - q['s1']) > T * .6)): return
    bands.append(dict(orient=o, c=(c0 + c1) / 2, t=dc, s0=s0, s1=s1, kind=kind, inner=len(inner), slide=slide,
                      src=[(round(r['c'], 1), round(r['s0'], 1), round(r['s1'], 1), r['lk']) for r in [p, q] + inner]))


bands = []
for o in ('h', 'v'):
    L = sorted([q for q in line_segs if q['o'] == o], key=lambda q: q['c'])
    for i, p in enumerate(L):
        cands = []
        for q in L[i + 1:]:
            dc = q['c'] - p['c']
            if dc > T * 1.75: break
            if dc < T * .3: continue
            s0, s1 = max(p['s0'], q['s0']), min(p['s1'], q['s1'])
            if s1 - s0 < T * 1.0: continue
            cands.append((q, dc, s0, s1))
        if not cands: continue
        # 一条长墙面线可能和不同的线在不同区段配对（同一面墙上的两个窗）：按区段分组，每组取重叠最长、其中最远的一条
        cands.sort(key=lambda c_: -(c_[3] - c_[2]))
        picks = []
        for seed in cands:
            if any(min(seed[3], pk[3]) - max(seed[2], pk[2]) > .5 * (seed[3] - seed[2]) for pk in picks): continue
            grp = [c_ for c_ in cands if min(c_[3], seed[3]) - max(c_[2], seed[2]) >= .8 * max(c_[3] - c_[2], seed[3] - seed[2])]
            picks.append(max(grp, key=lambda c_: c_[1]))
        for q, dc, s0, s1 in picks:
            make_band(o, L, p, q, dc, s0, s1)
# 窗带、描边墙带两端都要接到墙（或别的窗带）上，否则是家具、洁具、柜子的轮廓
def _box(z):
    return (z['s0'], z['c'] - z['t'] / 2, z['s1'], z['c'] + z['t'] / 2) if z['orient'] == 'h' else (z['c'] - z['t'] / 2, z['s0'], z['c'] + z['t'] / 2, z['s1'])
def _end_touch(b, end, others, tol):
    e = b['s0'] if end == 0 else b['s1']
    pt_box = (e - tol, b['c'] - b['t'] / 2 - tol, e + tol, b['c'] + b['t'] / 2 + tol) if b['orient'] == 'h' else (b['c'] - b['t'] / 2 - tol, e - tol, b['c'] + b['t'] / 2 + tol, e + tol)
    for q in others:
        if q is b: continue
        B = _box(q)
        if pt_box[0] <= B[2] and B[0] <= pt_box[2] and pt_box[1] <= B[3] and B[1] <= pt_box[3]: return True
    return False
bands = [b for b in bands if b['kind'] != 'glazing' or (b['s1'] - b['s0'] >= T * 1.6 and b['t'] <= T * 1.3)]  # 窗：不短于 ~400、不厚于墙
def _across_door(b, others):
    # 门洞边的短墙垛：同一条线上隔着一个门洞宽的距离，有一段已确认的同厚墙带
    for q in others:
        if q is b or q['orient'] != b['orient'] or abs(q['c'] - b['c']) > T * .1 or abs(q['t'] - b['t']) > T * .1: continue
        gap = max(q['s0'] - b['s1'], b['s0'] - q['s1'])
        if T * 1.5 <= gap <= a.max_opening / max(S_pre, 1e-9): return True
    return False
S_pre = (a.scale or (a.ratio * 25.4 / 72 if a.ratio else None) or (unit_mm or 0) or 240 / T)
# 逐步接受：先认接到实墙 / 填充墙上的，再认接到已认墙带上的（一圈描边隔墙围成的小卫生间也能一路认出来）
_pool_all = pieces + bands
acc = [b for b in bands if b['kind'] == 'hatch']
pend = [b for b in bands if b['kind'] != 'hatch']
for _ in range(5):
    hard = pieces + acc
    new_ = [b for b in pend if
            (b['kind'] == 'glazing' and (_end_touch(b, 0, _pool_all, T * .25) or _end_touch(b, 1, _pool_all, T * .25)))
            or (b['kind'] == 'outline' and ((_end_touch(b, 0, hard, T * .25) and _end_touch(b, 1, hard, T * .25))
                or (b['s1'] - b['s0'] >= 3 * T and (_end_touch(b, 0, hard, T * .25) or _end_touch(b, 1, hard, T * .25)))
                or ((_end_touch(b, 0, hard, T * .25) or _end_touch(b, 1, hard, T * .25)) and _across_door(b, acc))))]
    if not new_: break
    acc += new_; pend = [b for b in pend if b not in new_]
bands = acc
# 窗必须开在墙线上：和某段实墙（或已确认的窗）同一条线、首尾相接
def _collinear_touch(b, others):
    for q in others:
        if q is b or q['orient'] != b['orient']: continue
        if abs(q['c'] - b['c']) > max(q['t'], b['t']) / 2 + T * .1: continue
        if b['s0'] - T * 1.2 <= q['s1'] and q['s0'] <= b['s1'] + T * 1.2: return True  # 中间可能隔着一面丁字墙
    return False
def _exterior(b):
    # 窗带某一侧再没有任何平行墙（射线打出去是空的）= 外墙上的窗
    mid = (b['s0'] + b['s1']) / 2
    for d in (1, -1):
        if not any(z is not b and z['orient'] == b['orient'] and (z['c'] - b['c']) * d > b['t'] / 2 and z['s0'] <= mid <= z['s1'] for z in pieces + bands): return True
    return False
ok = [b for b in bands if b['kind'] in ('hatch', 'outline') or _collinear_touch(b, pieces)]
for _ in range(3):
    ok += [b for b in bands if b not in ok and (_collinear_touch(b, [z for z in ok if z['kind'] != 'outline'])
           or (b['kind'] == 'glazing' and _exterior(b) and _end_touch(b, 0, ok, T * .25) and _end_touch(b, 1, ok, T * .25)))]
bands = ok
# 同一处只留最宽的带（4 线窗会配出好几对）
bands.sort(key=lambda b: -b['t'])
kept = []
for b in bands:
    if any(k['orient'] == b['orient'] and abs(k['c'] - b['c']) < (k['t'] + b['t']) / 2 and min(k['s1'], b['s1']) - max(k['s0'], b['s0']) > .3 * (b['s1'] - b['s0']) for k in kept): continue
    kept.append(b)
bands = kept
if os.environ.get('CADDBG'):
    for b in bands: print('BAND', b['orient'], round(b['c'], 1), round(b['t'], 1), round(b['s0'], 1), round(b['s1'], 1), b['kind'], b.get('src'), file=sys.stderr)

# ------------------------------------------------------------------ 6. 比例
how = None
if unit_mm: s_mm, how = unit_mm, f'DXF 单位（1 单位 = {unit_mm} mm）'
elif a.scale: s_mm, how = a.scale, '--scale'
elif a.ratio: s_mm, how = a.ratio * 25.4 / 72, f'--ratio 1:{a.ratio:g}'
allw = pieces + [b for b in bands if b['kind'] != 'outline'] + [b for b in bands if b['kind'] == 'outline' and b['s1'] - b['s0'] > T * 3]
def bbox(ps):
    xs_, ys_ = [], []
    for p in ps:
        if p['orient'] == 'h': xs_ += [p['s0'], p['s1']]; ys_ += [p['c'] - p['t'] / 2, p['c'] + p['t'] / 2]
        else: ys_ += [p['s0'], p['s1']]; xs_ += [p['c'] - p['t'] / 2, p['c'] + p['t'] / 2]
    return min(xs_), min(ys_), max(xs_), max(ys_)
if not allw: sys.exit('没有找到墙：这张图的墙可能是单线画的，或者被炸成了很短的碎线，改用 analyze.py 识别渲染出的图片')
BX0, BY0, BX1, BY1 = bbox(allw)
check = {}
if not how:
    if a.total_width: s_mm, how = a.total_width / (BX1 - BX0), '--total-width / 墙体外轮廓宽'
    elif a.total_height: s_mm, how = a.total_height / (BY1 - BY0), '--total-height / 墙体外轮廓深'
    else:
        r = scale_from_dim_text()
        if r: s_mm, how = r[0], f'尺寸文字自动核对（{r[1]}/{r[2]} 段一致）'
        else:
            s_mm = 240 / T; how = '没有比例信息：按“最常见墙厚 = 240mm”猜的，务必用 --total-width 或 --scale 指定'
if a.total_width: check['width'] = round(a.total_width / (BX1 - BX0), 4)
if a.total_height: check['height'] = round(a.total_height / (BY1 - BY0), 4)
auto = scale_from_dim_text()
if auto: check['dim_text'] = round(auto[0], 4)

# ---- 6b. 读尺寸数字（文字层 / 字形破译 / DXF 标注），按标注数字建立 图纸坐标 → mm 的分段映射
#      有标注的地方，墙面、洞口边、墙厚都严格等于标注；标注之间按比例插值
dimvals = {}  # (尺寸线序号, 段序号) → dict(value, measured, ok, text, src)
dec = None
def dims_from_textlayer(S0):
    out = {}
    for ci, d in enumerate(merged_dims):
        for k, (t0, t1) in enumerate(zip(d['ticks'], d['ticks'][1:])):
            mid = (t0 + t1) / 2; best = None
            for tx in texts:
                if not re.fullmatch(r'\d{2,6}', tx['text']): continue
                along, perp = (tx['x'], tx['y']) if d['orient'] == 'h' else (tx['y'], tx['x'])
                if abs(perp - d['at']) < max(tx['h'] * 2.5, tick_size * 3):
                    e = abs(along - mid)
                    if e < max((t1 - t0) / 2, tick_size) and (best is None or e < best[0]): best = (e, tx['text'])
            if best:
                v = int(best[1]); L = (t1 - t0) * S0
                out[(ci, k)] = dict(value=v, measured=L, ok=abs(v - L) <= max(12, .008 * L), text=best[1], src='文字层')
    return out
if merged_dims and not a.no_dims:
    if texts and auto:
        dimvals = dims_from_textlayer(auto[0])
    if not dimvals:
        import importlib.util
        _sp = importlib.util.spec_from_file_location('dimtext', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dimtext.py'))
        dimtext = importlib.util.module_from_spec(_sp); _sp.loader.exec_module(dimtext)
        guesses = ([s_mm] if how and '猜' not in how else []) + [v / T for v in (240, 200, 180, 250, 300, 120, 100, 370)] + [n * 25.4 / 72 for n in (50, 100, 150, 200)]
        try:
            dec = dimtext.decode(fills, strokes, merged_dims, ticks, tick_size, T, guesses)
        except Exception as ex:
            print('尺寸数字识别失败：', ex, file=sys.stderr); dec = None
        if dec:
            dimvals = {k: dict(v, src='字形识别') for k, v in dec['values'].items()}
            if os.environ.get('CADDBG'): os.makedirs(a.out or '.', exist_ok=True); dimtext.montage(dec, os.path.join(a.out or '.', 'glyphs.png'))
    nd = sum(v['ok'] for v in dimvals.values())
    if nd >= 4:
        ratios = [v['value'] / (merged_dims[ci]['ticks'][k + 1] - merged_dims[ci]['ticks'][k]) for (ci, k), v in dimvals.items() if v['ok'] and v['value'] >= 300]
        check['dims_read'] = round(float(np.median(ratios)), 4)
        if not how or '猜' in how or (not a.total_width and not a.total_height and not a.scale and not a.ratio):
            s_mm, how = float(np.median(ratios)), f'尺寸数字（{nd}/{len(dimvals)} 段读出且和图形一致）'

S = s_mm
# 每个方向：所有读出的标注段 → 刻度节点之间的距离约束，最小二乘解出每个刻度的 mm 坐标（几条尺寸线互相印证、不一致处平均）
maxseg = {o: max([len(d['ticks']) - 1 for d in merged_dims if d['orient'] == o] or [1]) for o in ('h', 'v')}
def build_axis(orient, B0):
    nodes, node_at = [], []
    def node(r, at=None):
        for i, v in enumerate(nodes):
            if abs(v - r) < max(T * .03, 1e-6):  # 只合并真正同一点的刻度（相距 15mm 的两个墙面是两个点）
                if at is not None: node_at[i].append(at)
                return i
        nodes.append(r); node_at.append([] if at is None else [at]); return len(nodes) - 1
    eqs = []
    for (ci, k), v in dimvals.items():
        d = merged_dims[ci]
        if d['orient'] != orient or not v['ok']: continue
        # 外墙外侧的三道尺寸是主尺寸，室内的细部尺寸和它矛盾时让着它
        outside = (d['at'] < (BY0 if orient == 'h' else BX0)) or (d['at'] > (BY1 if orient == 'h' else BX1))
        # 权重：外侧尺寸里分段越细越优先（最里一道门窗细部尺寸 > 轴线尺寸 > 总尺寸），室内尺寸最低
        nseg = len(d['ticks']) - 1
        wt_ = max(.02, (nseg / maxseg[orient]) ** 2) if outside else .02
        eqs.append((node(d['ticks'][k], d['feet'][k]), node(d['ticks'][k + 1], d['feet'][k + 1]), float(v['value']), (ci, k), wt_))
    for dd in dimsx:  # DXF 标注：有改写文字就用文字，否则就是图形本身的长度
        (x1, y1), (x2, y2) = dd['p1'], dd['p2']
        if orient == 'h' and abs(x2 - x1) > abs(y2 - y1) * 5 and abs(x2 - x1) > 0:
            eqs.append((node(min(x1, x2)), node(max(x1, x2)), dd['value'], None, 1.0))
        if orient == 'v' and abs(y2 - y1) > abs(x2 - x1) * 5 and abs(y2 - y1) > 0:
            eqs.append((node(min(y1, y2)), node(max(y1, y2)), dd['value'], None, 1.0))
    if len(eqs) < 2: return None
    for _ in range(4):
        n = len(nodes); A, bv = [], []
        for i_, j_, v, _k, wt in eqs:
            row = np.zeros(n); row[j_] = wt; row[i_] = -wt; A.append(row); bv.append(v * wt)
        w = 1e-3
        for i in range(n):
            row = np.zeros(n); row[i] = w; A.append(row); bv.append(w * S * (nodes[i] - B0))
        sol = np.linalg.lstsq(np.array(A), np.array(bv), rcond=None)[0]
        # 加权最小二乘已经按优先级消化了图纸里的小矛盾；这里只剔除明显读错的数字（差 25mm / 2% 以上）
        res = [(abs(sol[j_] - sol[i_] - v), e) for e in eqs for i_, j_, v, _k, wt in [e]]
        out_ = [q for q in res if q[0] > max(25, .02 * q[1][2])]
        if not out_: break
        worst = max(out_, key=lambda q: q[0] / q[1][2])[1]
        eqs.remove(worst)
        if worst[3] is not None: dimvals[worst[3]]['ok'] = False; dimvals[worst[3]]['conflict'] = True
    nw = np.zeros(len(nodes))
    for i_, j_, v, k_, wt in eqs: nw[i_] = max(nw[i_], wt); nw[j_] = max(nw[j_], wt)
    order = np.argsort(nodes); rx = np.array(nodes)[order]; mx = sol[order]; ats = [node_at[i] for i in order]; nws = nw[order]
    if os.environ.get('CADDBG'):
        print('AXIS', orient, 'nodes', len(nodes), 'eqs', len(eqs), file=sys.stderr)
        for i_, j_, v, k_, wt in eqs: print('  EQ', round(nodes[i_], 2), round(nodes[j_], 2), v, round(sol[j_] - sol[i_], 1), k_, file=sys.stderr)
    # 相邻刻度的局部比例要合理（防止读错的数字把坐标拧反）
    keep = [0]
    for i in range(1, len(rx)):
        gap_ = rx[i] - rx[keep[-1]]
        sl = (mx[i] - mx[keep[-1]]) / max(gap_, 1e-9)
        # 挨得很近的两个刻度（左右两侧尺寸各标各的墙面，差十几毫米）算斜率没意义，只要求不倒序
        if (gap_ < T * .15 and mx[i] >= mx[keep[-1]] - 1) or .85 * S <= sl <= 1.15 * S: keep.append(i)
    rx, mx = rx[keep], mx[keep]; ats = [ats[i] for i in keep]; nws = nws[keep]
    if os.environ.get('CADDBG'): print('  KEEP', len(keep), 'of', len(order), file=sys.stderr)
    used = len(eqs)
    for i_, j_, v, k_, wt in eqs:  # 图纸自己前后矛盾的标注：照实列出来
        got = sol[j_] - sol[i_]
        if k_ is not None and abs(got - v) > 1.5: dimvals[k_]['conflict'] = round(float(got), 1)
    snap_tol = T * .07  # 墙面 / 洞口边离尺寸刻度 ~15mm 以内：就是标注量的那个面，直接取标注值（图上线和刻度常差几毫米）
    def f(v, near=None):
        # 吸附时优先用离这个构件最近的那条尺寸线上的刻度（左右两侧的尺寸线可能在差不多的高度上各标各的墙）
        cand = np.nonzero(np.abs(rx - v) <= snap_tol)[0]
        if len(cand):
            # 几个刻度都够得着时：先看哪个刻度的尺寸界线伸到了这个构件（near = 构件在另一方向上的范围），再信优先级高的尺寸线，最后看远近
            def reach(j):
                if near is None or not ats[j]: return 0
                lo_, hi_ = near if isinstance(near, tuple) else (near, near)
                return min(max(lo_ - f_, f_ - hi_, 0) for f_ in ats[j])
            tol_r = T * 1.5
            best_r = min(reach(j) for j in cand)
            cand = [j for j in cand if reach(j) <= best_r + tol_r]
            top = nws[cand].max(); cand = [j for j in cand if nws[j] >= .8 * top]
            i = int(min(cand, key=lambda j: abs(rx[j] - v)))
            if os.environ.get('CADDBG2') and abs(v - float(os.environ['CADDBG2'])) < 6: print('SNAP', orient, round(v, 2), near, [(round(rx[j], 2), round(mx[j], 1), round(nws[j], 2), [round(a_, 1) for a_ in ats[j]]) for j in np.nonzero(np.abs(rx - v) <= snap_tol)[0]], '->', round(rx[i], 2), round(mx[i], 1), file=sys.stderr)
            return float(mx[i])
        if v <= rx[0]: return float(mx[0] + (v - rx[0]) * S)
        if v >= rx[-1]: return float(mx[-1] + (v - rx[-1]) * S)
        return float(np.interp(v, rx, mx))
    return f, len(rx), used
AX = build_axis('h', BX0) if (dimvals or dimsx) else None
AY = build_axis('v', BY0) if (dimvals or dimsx) else None
if AX: fx = AX[0]; X0m = fx(BX0); X = lambda v, near=None: fx(v, near) - X0m
else: X = lambda v, near=None: (v - BX0) * S
if AY: fy = AY[0]; Y0m = fy(BY0); Y = lambda v, near=None: fy(v, near) - Y0m
else: Y = lambda v, near=None: (v - BY0) * S
MM = lambda v: v * S
def R5(v):  # 坐标精确到 0.5mm（奇数墙厚的中线在半毫米上，墙面才是整数），标注是多少就是多少
    r = round(v * 2) / 2
    return int(r) if r == int(r) else r
def span_mm(o, c, t, near=None):  # 墙厚：两侧墙面分别换算再相减（墙面在标注刻度上时 = 标注值）
    F = Y if o == 'h' else X
    return abs(F(c + t / 2, near) - F(c - t / 2, near))

# ------------------------------------------------------------------ 7. 墙段 → mm，过滤文字笔画、家具
P = []
for p in pieces + bands:
    _mid = (p['s0'], p['s1'])
    t = span_mm(p['orient'], p['c'], p['t'], _mid); Lm = MM(p['s1'] - p['s0'])
    if t < 40 or (t > 800 and p['kind'] not in ('solid', 'grey')): continue
    if p['kind'] in ('outline',) and Lm < max(300, 1.2 * t): continue
    if p['kind'] == 'hatch' and t > 300: continue  # 填充的小方框：管井、立管包封，不是墙
    if p['kind'] in ('solid', 'grey') and t < .3 * MM(T) and Lm < 4 * MM(T): continue  # 文字笔画、符号里的细条
    _F = Y if p['orient'] == 'h' else X
    _G = X if p['orient'] == 'h' else Y
    d = dict(orient=p['orient'], c=(_F(p['c'] + p['t'] / 2, _mid) + _F(p['c'] - p['t'] / 2, _mid)) / 2, t=t, s0=_G(p['s0'], p['c']),
             s1=_G(p['s1'], p['c']), kind=p['kind'])
    if p.get('slide'): d['slide'] = True
    P.append(d)
# 方墩 / 大块实心：柱、结构块（长宽比 < 1.6 且不是交接处的小方块）
blocks = []
def touches(p, q, tol=30):
    def box(z):
        return (z['s0'], z['c'] - z['t'] / 2, z['s1'], z['c'] + z['t'] / 2) if z['orient'] == 'h' else (z['c'] - z['t'] / 2, z['s0'], z['c'] + z['t'] / 2, z['s1'])
    A, B = box(p), box(q)
    return A[0] - tol <= B[2] and B[0] - tol <= A[2] and A[1] - tol <= B[3] and B[1] - tol <= A[3]
def as_orient(p, o):
    if p['orient'] == o: return dict(p)
    cx, cy = ((p['s0'] + p['s1']) / 2, p['c']) if p['orient'] == 'h' else (p['c'], (p['s0'] + p['s1']) / 2)
    w_, d_ = (p['s1'] - p['s0'], p['t']) if p['orient'] == 'h' else (p['t'], p['s1'] - p['s0'])
    L_ = w_ if o == 'h' else d_
    return dict(p, orient=o, c=cy if o == 'h' else cx, t=d_ if o == 'h' else w_, s0=(cx if o == 'h' else cy) - L_ / 2, s1=(cx if o == 'h' else cy) + L_ / 2)
for p in list(P):
    L = p['s1'] - p['s0']
    if p['kind'] in ('solid', 'grey', 'hatch') and L < 1.6 * p['t']:
        P.remove(p)
        big = min(L, p['t']) > 260
        if not big:
            # 墙垛 / 门边短墙：同一条线上隔一个洞口有墙段（中线或一侧墙面对齐），就按那个方向并进去
            best = None
            for o in ('h', 'v'):
                z = as_orient(p, o)
                for q in P:
                    if q['orient'] != o or q['kind'] not in ('solid', 'grey', 'hatch'): continue
                    face = min(abs((q['c'] - q['t'] / 2) - (z['c'] - z['t'] / 2)), abs((q['c'] + q['t'] / 2) - (z['c'] + z['t'] / 2)), abs(q['c'] - z['c']))
                    if face > 15 or abs(z['t'] - q['t']) > .35 * q['t']: continue
                    gap = max(q['s0'] - z['s1'], z['s0'] - q['s1'])
                    if -5 <= gap <= a.max_opening and (best is None or gap < best[0]): best = (gap, z)
            if os.environ.get('CADDBG'): print('SQUAT', [round(v) for v in (p['c'], p['t'], p['s0'], p['s1'])], p['orient'], 'best', best and (round(best[0]), best[1]['orient']), file=sys.stderr)
            if best:
                best[1]['stub'] = True; P.append(best[1]); continue
            # 两头都顶着垂直墙的短墙（转角连接段）：照常保留
            def _end_hit(z, e):
                for q in P:
                    if q['orient'] == z['orient']: continue
                    if abs(e - q['c']) <= q['t'] / 2 + 30 and q['s0'] - 30 <= z['c'] <= q['s1'] + 30: return True
                return False
            for o in (p['orient'], 'v' if p['orient'] == 'h' else 'h'):
                z = as_orient(p, o)
                if _end_hit(z, z['s0']) and _end_hit(z, z['s1']): P.append(z); break
                # 墙垛 / 翼墙：一头顶着垂直墙、另一头悬空伸出去
                if (_end_hit(z, z['s0']) or _end_hit(z, z['s1'])) and z['s1'] - z['s0'] >= MM(T) * 1.2 and z['t'] <= 400: P.append(z); break
            else:
                if p['kind'] != 'hatch' and not any(touches(p, q) for q in P): blocks.append(dict(x=(p['s0'] + p['s1']) / 2 if p['orient'] == 'h' else p['c'], y=p['c'] if p['orient'] == 'h' else (p['s0'] + p['s1']) / 2, w=L if p['orient'] == 'h' else p['t'], d=p['t'] if p['orient'] == 'h' else L))
            continue
        if p['kind'] != 'hatch' and (big or not any(touches(p, q) for q in P)):
            cx, cy = ((p['s0'] + p['s1']) / 2, p['c']) if p['orient'] == 'h' else (p['c'], (p['s0'] + p['s1']) / 2)
            w_, d_ = (L, p['t']) if p['orient'] == 'h' else (p['t'], L)
            blocks.append(dict(x=cx, y=cy, w=w_, d=d_))
    elif p['kind'] in ('solid', 'grey') and p['t'] > 450 and L < 3 * p['t']:
        P.remove(p)
        cx, cy = ((p['s0'] + p['s1']) / 2, p['c']) if p['orient'] == 'h' else (p['c'], (p['s0'] + p['s1']) / 2)
        blocks.append(dict(x=cx, y=cy, w=L if p['orient'] == 'h' else p['t'], d=p['t'] if p['orient'] == 'h' else L))
P.sort(key=lambda p: (p['orient'], p['c'], p['s0']))
for i, p in enumerate(P): p['id'] = f'P{i}'

# ------------------------------------------------------------------ 8. 合并成墙线：同方向、中线相近（或面齐平）、首尾相接 / 中间是门窗断口
def same_line(p, q):
    if p['orient'] != q['orient']: return None
    if abs(p['c'] - q['c']) < 3 or (abs(p['c'] - q['c']) < 12 and abs(p['t'] - q['t']) < 6): return 'center'
    # 薄墙接厚墙、一侧面齐平
    for side in (-1, 1):
        if abs((p['c'] + side * p['t'] / 2) - (q['c'] + side * q['t'] / 2)) < 5 and abs(p['c'] - q['c']) < max(p['t'], q['t']) / 2: return side
    return None
lines = []  # dict(orient, c, pieces)
for p in sorted(P, key=lambda p: -p['t']):
    for L in lines:
        if any(same_line(p, q) for q in L['pieces']):
            L['pieces'].append(p); break
    else: lines.append(dict(orient=p['orient'], c=p['c'], pieces=[p]))
segs_mm = [(X(g[0]), Y(g[1]), X(g[2]), Y(g[3]), g[4]) for gi, g in enumerate(segs)
           if gi not in dim_seg and not strokes[g[4]]['dashed'] and layer_kind(strokes[g[4]]['layer']) not in ('axis', 'dim', 'furn')]
def strokes_in(x0, y0, x1, y1):
    return [g for g in segs_mm if min(g[0], g[2]) >= x0 and max(g[0], g[2]) <= x1 and min(g[1], g[3]) >= y0 and max(g[1], g[3]) <= y1]
perp_cache = {}
def perp_cross(o, c, t, g0, g1):
    """断口里有垂直方向的墙穿过 → 是丁字 / 十字交接，不是门窗"""
    for q in P:
        if q['orient'] == o: continue
        if g0 - 5 <= q['c'] - q['t'] / 2 and q['c'] + q['t'] / 2 <= g1 + 5 and q['s0'] <= c + t / 2 + 5 and q['s1'] >= c - t / 2 - 5: return q
    return None

# 圆弧：DXF 直接有；PDF 把弧拆成了折线，按“点到圆心等距”拟合
def fit_arc(pts):
    A = np.array(pts, float)
    if len(A) < 5: return None
    M = np.c_[2 * A, np.ones(len(A))]; bvec = (A ** 2).sum(1)
    try: sol, *_ = np.linalg.lstsq(M, bvec, rcond=None)
    except Exception: return None
    cx, cy = sol[0], sol[1]; r = math.sqrt(max(0, sol[2] + cx * cx + cy * cy))
    if r == 0: return None
    err = np.abs(np.hypot(A[:, 0] - cx, A[:, 1] - cy) - r).max()
    if err > r * .04: return None
    ang = np.degrees(np.arctan2(A[:, 1] - cy, A[:, 0] - cx))
    sweep = np.degrees(np.abs(np.diff(np.unwrap(np.radians(ang)))).sum())
    return (cx, cy, r, float(sweep), float(np.mean(A[:, 0])), float(np.mean(A[:, 1])))
arcs_mm = []
for c in arcs:
    if layer_kind(c.get('layer', '')) in ('furn', 'dim', 'axis'): continue  # 家具、水电符号里的圆不是管井 / 地漏
    a0, a1 = math.radians(c['a0']), math.radians(c['a1'])
    if a1 < a0: a1 += 2 * math.pi
    mid = (a0 + a1) / 2
    arcs_mm.append(dict(cx=X(c['c'][0]), cy=Y(c['c'][1]), r=MM(c['r']), sweep=math.degrees(a1 - a0),
                        mx=X(c['c'][0] + c['r'] * math.cos(mid)), my=Y(c['c'][1] + c['r'] * math.sin(mid)), full=c.get('full', False)))
if src_kind == '.pdf':
    for s in strokes:
        if len(s['pts']) >= 6 and not s.get('filled'):  # 带填充的小闭合形多是文字笔画（SHX 字体炸成的轮廓）
            f = fit_arc([(X(p[0]), Y(p[1])) for p in s['pts']])
            if f and f[3] > 25: arcs_mm.append(dict(cx=f[0], cy=f[1], r=f[2], sweep=f[3], mx=f[4], my=f[5], full=f[3] > 330))

walls, openings = [], []
for L in lines:
    o = L['orient']; ps = sorted(L['pieces'], key=lambda p: p['s0'])
    # 复合墙：同一段上并排两层（如砖砌内衬 + 混凝土墙），合成一面墙，厚度取两层总厚
    comp = []
    for p in ps:
        m = next((q for q in comp if p['kind'] != 'glazing' and q['kind'] != 'glazing'
                  and min(q['s1'], p['s1']) - max(q['s0'], p['s0']) > .5 * min(q['s1'] - q['s0'], p['s1'] - p['s0'])), None)
        if m:
            lo = min(m['c'] - m['t'] / 2, p['c'] - p['t'] / 2); hi = max(m['c'] + m['t'] / 2, p['c'] + p['t'] / 2)
            st = (m.get('solid_t', m['t'] if m['kind'] == 'solid' else 0)) + (p['t'] if p['kind'] == 'solid' else 0)
            m.update(c=(lo + hi) / 2, t=hi - lo, s0=min(m['s0'], p['s0']), s1=max(m['s1'], p['s1']), solid_t=st,
                     kind='solid' if st > 0 else m['kind'])
        else: comp.append(dict(p))
    ps = comp
    main = max(ps, key=lambda p: (p['kind'] != 'glazing', p['t'], p['s1'] - p['s0']))
    c = main['c']
    for p in ps:
        rel = same_line(p, main) if p is not main else 'center'
        p['flush'] = None if rel in ('center', None) else rel
    # 串成连续段，段间断口判断门窗
    def notch(g0, g1, t):
        # 外墙凹口：断口两端各有一面垂直墙朝同一侧伸出、那一侧还有一面平行墙把它们连起来，而另一侧是室外
        for d in (1, -1):
            def leaving(e):
                for q in P:
                    if q['orient'] == o or abs(q['c'] - e) > q['t'] / 2 + 80: continue
                    near, far = (q['s0'], q['s1']) if d > 0 else (q['s1'], q['s0'])
                    if abs(near - c) <= t + 80 and (far - c) * d >= 250: return True
                return False
            if not (leaving(g0) and leaving(g1)): continue
            if not any(q['orient'] == o and 200 <= (q['c'] - c) * d <= 2600 and min(g1, q['s1']) - max(g0, q['s0']) >= .7 * (g1 - g0) for q in P): continue
            mid = (g0 + g1) / 2
            outside = not any(q['orient'] == o and (q['c'] - c) * -d > t and q['s0'] <= mid <= q['s1'] for q in P)
            if outside: return True
        return False
    runs, cur = [], [ps[0]]
    for q in ps[1:]:
        prev_end = max(z['s1'] for z in cur)
        gap = q['s0'] - prev_end
        if gap <= 150: cur.append(q); continue  # 不到 150 的缝不是洞口（窗框接缝、文字压线）
        if gap <= a.max_opening and notch(prev_end, q['s0'], main['t']):
            runs.append(cur); cur = [q]; continue
        if gap <= a.max_opening and not perp_cross(o, c, main['t'], prev_end, q['s0']):
            cur.append(dict(gap=True, s0=prev_end, s1=q['s0'])); cur.append(q); continue
        pc = perp_cross(o, c, main['t'], prev_end, q['s0'])
        if pc and gap <= a.max_opening + 400:
            # 断口中间有一面垂直墙穿过：墙两侧剩下的空当才是洞口
            for g0_, g1_ in ((prev_end, pc['c'] - pc['t'] / 2), (pc['c'] + pc['t'] / 2, q['s0'])):
                if g1_ - g0_ >= 300: cur.append(dict(gap=True, s0=g0_, s1=g1_))
            cur.append(q); continue
        runs.append(cur); cur = [q]
    runs.append(cur)
    for run in runs:
        items = [z for z in run if not z.get('gap')]
        # 每一段连续的墙单独定中线（同一条直线上隔得很远的两面墙互不影响）
        rm = max(items, key=lambda p: (p['kind'] != 'glazing', p['t'], p['s1'] - p['s0']))
        for p in items:
            rel = same_line(p, rm) if p is not rm else 'center'
            p['flush'] = None if rel in ('center', None) else rel
        walls.append(dict(orient=o, c=rm['c'], s0=min(z['s0'] for z in items), s1=max(z['s1'] for z in items), items=run, t_main=rm['t']))

# 门窗：玻璃带 → 窗；断口 → 看里面的图元
def classify_gap(w, g0, g1):
    o, c, t = w['orient'], w['c'], w['t_main']
    width = g1 - g0
    box = (g0 + 15, c - t / 2 - 15, g1 - 15, c + t / 2 + 15) if o == 'h' else (c - t / 2 - 15, g0 + 15, c + t / 2 + 15, g1 - 15)
    along_lines, inner_lines = [], []
    for g in segs_mm:
        if o == 'h' and abs(g[1] - g[3]) < 3: pos, a0_, a1_ = g[1], min(g[0], g[2]), max(g[0], g[2])
        elif o == 'v' and abs(g[0] - g[2]) < 3: pos, a0_, a1_ = g[0], min(g[1], g[3]), max(g[1], g[3])
        else: continue
        if abs(pos - c) > t / 2 + 15 or min(a1_, g1) - max(a0_, g0) < width * .6: continue
        along_lines.append(g)
        if abs(pos - c) < t / 2 - 12: inner_lines.append(g)
    why = []
    # 弧线：圆心在断口某一端（墙中线附近），半径约等于洞宽（单扇）或一半（双扇）
    found = []
    for ar in arcs_mm:
        if ar['full'] or ar['sweep'] < 25 or ar['sweep'] > 200: continue
        for end, e in (('from', g0), ('to', g1)):
            hx, hy = (e, c) if o == 'h' else (c, e)
            if math.hypot(ar['cx'] - hx, ar['cy'] - hy) < t / 2 + 60 and .3 * width < ar['r'] < 1.25 * width:
                side = (ar['my'] - c) if o == 'h' else (ar['mx'] - c)
                found.append((end, ar['r'], side, ar))
    leaf_open = []
    for g in strokes_in(*(g0 - 30, c - width * 1.3, g1 + 30, c + width * 1.3) if o == 'h' else (c - width * 1.3, g0 - 30, c + width * 1.3, g1 + 30)):
        Lg = math.hypot(g[2] - g[0], g[3] - g[1])
        perp = abs(g[0] - g[2]) < 3 if o == 'h' else abs(g[1] - g[3]) < 3
        if perp and .55 * width < Lg < 1.1 * width:
            for end, e in (('from', g0), ('to', g1)):
                for px, py in ((g[0], g[1]), (g[2], g[3])):
                    if (abs(px - e) < 60 and abs(py - c) < t / 2 + 60) if o == 'h' else (abs(py - e) < 60 and abs(px - c) < t / 2 + 60):
                        far = (g[3] + g[1] - 2 * c) if o == 'h' else (g[2] + g[0] - 2 * c)
                        leaf_open.append((end, Lg, far))
    if found:
        ends = {f[0] for f in found}
        if len(ends) == 2:
            rs = sorted(f[1] for f in found)
            typ = 'unequal' if rs[-1] / max(1, rs[0]) > 1.3 else 'double'
            hinge = max(found, key=lambda f: f[1])[0]
        else: typ, hinge = 'door', found[0][0]
        side = sum(f[2] for f in found)
        why.append(f'开启弧线 ×{len(found)}，半径 {"/".join(str(R5(f[1])) for f in found)}')
        return dict(type=typ, hinge=hinge, side=1 if side > 0 else -1, why='；'.join(why))
    if leaf_open:
        end, Lg, far = max(leaf_open, key=lambda q: q[1])
        return dict(type='door', hinge=end, side=1 if far > 0 else -1, why=f'门扇线（垂直墙、长 {R5(Lg)}）')
    door_lines = [g for g in inner_lines if layer_kind(strokes[g[4]]['layer']) == 'door']
    def _span(g): return (min(g[0], g[2]), max(g[0], g[2])) if o == 'h' else (min(g[1], g[3]), max(g[1], g[3]))
    def _pos(g): return g[1] if o == 'h' else g[0]
    # 推拉门：两扇门扇线错开（各占洞宽一半多一点、前后错开一点）
    halves = []
    for g in segs_mm:  # 推拉门扇各只占洞宽一半多一点，不在 inner_lines（要求覆盖 60%）里
        if not ((o == 'h' and abs(g[1] - g[3]) < 3) or (o == 'v' and abs(g[0] - g[2]) < 3)): continue
        if abs(_pos(g) - c) < t / 2 - 12 and .35 * width < _span(g)[1] - _span(g)[0] < .8 * width and min(_span(g)[1], g1) - max(_span(g)[0], g0) > .3 * width: halves.append(g)
    if len(halves) >= 2 and abs(_pos(halves[0]) - _pos(halves[1])) > 8 and (not has_layers or sum(layer_kind(strokes[g[4]]['layer']) == 'door' for g in halves) >= 2):
        a_, b_ = sorted(halves[:2], key=lambda g: _span(g)[0])
        if _span(a_)[0] < g0 + width * .2 and _span(b_)[1] > g1 - width * .2:
            return dict(type='sliding', why='两条错开的门扇线 = 推拉门')
    if door_lines: return dict(type='door', why='门图层的线（门扇关闭画法）', side=0)
    for s_ in ([] if has_layers else strokes):  # 有图层的 DXF 本来就是彩色的，不按颜色判断
        if not s_['color'] or max(s_['color']) - min(s_['color']) < .3: continue
        xs_ = [X(p_[0]) for p_ in s_['pts']]; ys_ = [Y(p_[1]) for p_ in s_['pts']]
        if min(xs_) >= box[0] - 40 and max(xs_) <= box[2] + 40 and min(ys_) >= box[1] - 40 and max(ys_) <= box[3] + 40:
            al = (min(xs_), max(xs_)) if o == 'h' else (min(ys_), max(ys_))
            r_ = dict(type='door', why='洞口画了彩色框（装修图里多表示新开 / 改造的门洞），按门处理，开向待定', side=0, marked=True)
            if al[1] - al[0] > 300: r_['span'] = (max(g0, al[0]), min(g1, al[1]))
            return r_
    if inner_lines and len(along_lines) >= 2: return dict(type='window', why=f'断口里 {len(along_lines)} 条平行线（墙面线以内有 {len(inner_lines)} 条）')
    if len(inner_lines) >= 2: return dict(type='window', why=f'断口里 {len(inner_lines)} 条平行线')
    if len(inner_lines) == 1: return dict(type='door', why='断口里一条沿墙中线的单线（门扇关闭画法，多见于入户门）', side=0)
    colored = [] if has_layers else [s for s in strokes if s['color'] and max(s['color']) - min(s['color']) > .3]
    for s in colored:
        xs_ = [X(p[0]) for p in s['pts']]; ys_ = [Y(p[1]) for p in s['pts']]
        if min(xs_) >= box[0] - 40 and max(xs_) <= box[2] + 40 and min(ys_) >= box[1] - 40 and max(ys_) <= box[3] + 40:
            return dict(type='door', why='断口里有彩色框（多为改造新开洞口），按门处理，开向待定', side=0, marked=True)
    return dict(type='hole', why='断口里没有门窗图元 = 门洞（原始结构图里的门洞，装修时一般要装门）')

O_list = []
for wi, w in enumerate(walls):
    w['id'] = f'W{wi}'
    o, c = w['orient'], w['c']
    for z in w['items']:
        if z.get('gap') and not z.get('cross'):
            g = classify_gap(w, z['s0'], z['s1']); sp_ = g.pop('span', (z['s0'], z['s1']))
            g.update(wall=w['id'], s0=sp_[0], s1=sp_[1], width=sp_[1] - sp_[0])
            O_list.append(g)
        elif not z.get('gap') and z['kind'] == 'glazing':
            typ = 'slideWindow' if z.get('slide') else 'window'
            O_list.append(dict(type=typ, wall=w['id'], s0=z['s0'], s1=z['s1'], width=z['s1'] - z['s0'], why=f'墙带里 {z.get("inner", 0) + 2}+ 条平行线 = 窗'))
# 飘窗：窗外侧还有一圈凸出的平行线（外墙面以外 300~800 有平行线覆盖窗宽）
for op in O_list:
    if not op['type'].endswith('indow'): continue
    w = next(q for q in walls if q['id'] == op['wall'])
    o, c, t = w['orient'], w['c'], w['t_main']
    for side in (-1, 1):
        lo, hi = (c + side * (t / 2 + 250), c + side * (t / 2 + 900))
        hits = [g for g in segs_mm if (abs(g[1] - g[3]) < 3 and o == 'h' and min(lo, hi) < g[1] < max(lo, hi) and min(g[0], g[2]) < op['s0'] + 50 and max(g[0], g[2]) > op['s1'] - 50)
                or (abs(g[0] - g[2]) < 3 and o == 'v' and min(lo, hi) < g[0] < max(lo, hi) and min(g[1], g[3]) < op['s0'] + 50 and max(g[1], g[3]) > op['s1'] - 50)]
        if len(hits) >= 2: op['bay_side'] = side; op['why'] += '；窗外凸出一圈平行线，可能是飘窗（看原图确认）'
# 门窗编号 / 窗台高文字
for op in O_list:
    w = next(q for q in walls if q['id'] == op['wall'])
    cx, cy = ((op['s0'] + op['s1']) / 2, w['c']) if w['orient'] == 'h' else (w['c'], (op['s0'] + op['s1']) / 2)
    near = sorted(texts, key=lambda tx: math.hypot(X(tx['x']) - cx, Y(tx['y']) - cy))
    for tx in near[:4]:
        if math.hypot(X(tx['x']) - cx, Y(tx['y']) - cy) > 1500: break
        m = CODE_RE.match(tx['text'].upper())
        if m:
            op['code'] = tx['text']; op['code_w'] = int(m.group(2)) * 100; op['code_h'] = int(m.group(3)) * 100
            if m.group(1).startswith(('M', 'FM', 'TLM', 'JLM')) and op['type'] in ('hole', 'window'): op['type'] = 'sliding' if m.group(1) == 'TLM' else 'door'
        m = re.search(r'离地\s*(\d+)', tx['text']);  op.update(sill=int(m.group(1))) if m else None
        m = re.search(r'H\s*[:：=]?\s*(\d+)', tx['text']); op.update(win_h=int(m.group(1))) if m and op['type'].endswith('indow') else None
for i, op in enumerate(O_list): op['id'] = f'O{i}'

# ------------------------------------------------------------------ 9. 墙线端点吸附到相交墙中线 → HouseSpec
def wall_t(w):
    ts = [z['t'] for z in w['items'] if not z.get('gap') and z['kind'] != 'glazing']
    return max(ts) if ts else max(z['t'] for z in w['items'] if not z.get('gap'))
for w in walls: w['t'] = wall_t(w)
def snap_end(w, sp):
    best = None
    for q in walls:
        if q['orient'] == w['orient']: continue
        if abs(sp - q['c']) <= max(q['t'], w['t']) / 2 + 40 and q['s0'] - w['t'] / 2 - 40 <= w['c'] <= q['s1'] + w['t'] / 2 + 40:
            d = abs(sp - q['c'])
            if best is None or d < best[0]: best = (d, q['c'], q)
    if best and not (min(best[2].get('e0', best[2]['s0']), best[2].get('e1', best[2]['s1'])) - 1 <= w['c'] <= max(best[2].get('e0', best[2]['s0']), best[2].get('e1', best[2]['s1'])) + 1):
        best[2].setdefault('_grow', []).append(w['c'])  # 接上的这面墙还没画到这里：稍后把它延长过来
    return best[1] if best else sp
# 自由端顶着实心结构块（柱、结构墩）：穿过去到块的另一侧，再找墙接上
for w in walls:
    for end in ('s0', 's1'):
        e = w[end]
        for b in blocks:
            bx0, by0, bx1, by1 = b['x'] - b['w'] / 2, b['y'] - b['d'] / 2, b['x'] + b['w'] / 2, b['y'] + b['d'] / 2
            lo, hi, c0_, c1_ = (bx0, bx1, by0, by1) if w['orient'] == 'h' else (by0, by1, bx0, bx1)
            if not (c0_ - 5 <= w['c'] <= c1_ + 5): continue
            if end == 's1' and abs(e - lo) < 40: w[end] = hi; b['through'] = w['id']
            if end == 's0' and abs(e - hi) < 40: w[end] = lo; b['through'] = w['id']
for w in walls:
    w['e0'], w['e1'] = snap_end(w, w['s0']), snap_end(w, w['s1'])
# 错位墙：一面墙的自由端旁边紧贴着一面平行墙（墙线错开半个墙厚以上）→ 加一小段横墙把它们接上
connectors = []
for w in walls:
    for k, sp, dirn in (('e0', w['s0'], -1), ('e1', w['s1'], 1)):
        if w[k] != sp: continue
        for q in walls:
            if q is w or q['orient'] != w['orient']: continue
            off = q['c'] - w['c']
            if not (abs(abs(off) - (q['t'] + w['t']) / 2) < 40 or abs(off) < (q['t'] + w['t']) / 2) or abs(off) < 20: continue
            if not (min(q['e0'], q['e1']) - 5 <= sp <= max(q['e0'], q['e1']) + 5): continue
            e2 = sp - dirn * w['t'] / 2
            w[k] = e2
            connectors.append(dict(orient='h' if w['orient'] == 'v' else 'v', c=e2, a=w['c'], b=q['c'], t=w['t']))
            break
# 墙端是自由端、正前方不远处有垂直墙：中间是靠墙角的门洞（门边没有墙垛的画法）。近的先处理，处理完别的墙可能已经接上了
cand_fe = []
for w in walls:
    for k, sp, dirn in (('e0', w['s0'], -1), ('e1', w['s1'], 1)):
        if w[k] != sp: continue
        for q in walls:
            if q['orient'] == w['orient'] or not (q['s0'] - w['t'] / 2 - 80 <= w['c'] <= q['s1'] + w['t'] / 2 + 80): continue
            g = (q['c'] - sp) * dirn - q['t'] / 2
            if 300 <= g <= min(a.max_opening, 2400): cand_fe.append((g, w, k, sp, dirn, q))
cand_fe.sort(key=lambda z: z[0])
done_fe = set()
for g, w, k, sp, dirn, q in cand_fe:
    if (id(w), k) in done_fe or w[k] != sp: continue
    if snap_end(w, sp) != sp: w[k] = snap_end(w, sp); done_fe.add((id(w), k)); continue
    if not (q['s0'] - w['t'] / 2 - 80 <= w['c'] <= q['s1'] + w['t'] / 2 + 80): continue
    done_fe.add((id(w), k))
    if True:
            g0_, g1_ = (sp, q['c'] - q['t'] / 2) if dirn > 0 else (q['c'] + q['t'] / 2, sp)
            # 中间不能被别的同向墙段占着
            if any(z is not w and z['orient'] == w['orient'] and abs(z['c'] - w['c']) < w['t'] and min(z['s1'], g1_) - max(z['s0'], g0_) > 50 for z in walls): continue
            info_ = classify_gap(w, g0_, g1_); sp_ = info_.pop('span', (g0_, g1_)); info_.update(wall=w['id'], s0=sp_[0], s1=sp_[1], width=sp_[1] - sp_[0])
            info_['id'] = f'O{len(O_list)}'; O_list.append(info_)
            w['items'].append(dict(gap=True, s0=g0_, s1=g1_))
            w[k] = q['c']; w.setdefault('ext', []).append(k)
            if dirn > 0: w['s1'] = q['c']
            else: w['s0'] = q['c']
# 被接上的墙没画到交点（墙垛、翼墙从另一面墙的外侧伸出来）：把它延长到交点
for q in walls:
    for v_ in q.pop('_grow', []):
        if v_ < min(q['e0'], q['e1']): q['e0'] = v_; q['s0'] = min(q['s0'], v_); q.setdefault('ext', []).append('e0')
        elif v_ > max(q['e0'], q['e1']): q['e1'] = v_; q['s1'] = max(q['s1'], v_); q.setdefault('ext', []).append('e1')
# 转角差一点没接上（中间是没填充的短墙头、窗框）：两面墙都延长到交点
for w in walls:
    for k, sp in (('e0', w['s0']), ('e1', w['s1'])):
        if w[k] != sp: continue
        best = None
        for q in walls:
            if q['orient'] == w['orient'] or abs(sp - q['c']) > 650: continue
            for qk in ('e0', 'e1'):
                if abs(q[qk] - w['c']) <= 650 and not (min(q['e0'], q['e1']) - 5 <= w['c'] <= max(q['e0'], q['e1']) + 5):
                    d = abs(sp - q['c']) + abs(q[qk] - w['c'])
                    if best is None or d < best[0]: best = (d, q, qk)
        if best:
            _, q, qk = best; w[k] = q['c']; q[qk] = w['c']
            if k == 'e0': w['s0'] = min(w['s0'], q['c'])
            else: w['s1'] = max(w['s1'], q['c'])
for w in walls:
    w['free'] = [k for k, e, s in (('a', w['e0'], w['s0']), ('b', w['e1'], w['s1'])) if e == s and ('e0' if k == 'a' else 'e1') not in w.get('ext', []) and not any(abs(cn['c'] - e) < 1 and abs(cn['a'] - w['c']) < 1 for cn in connectors)]

FL = {('h', -1): 'N', ('h', 1): 'S', ('v', -1): 'W', ('v', 1): 'E'}
spec_walls = []
for w in walls:
    o, c = w['orient'], w['c']
    # 按厚度 / 类型切段（门窗跟着前一段走）
    chunks, cur = [], None
    items = sorted(w['items'], key=lambda z: z['s0'])
    for k, z in enumerate(items):
        if z.get('gap') or z['kind'] == 'glazing':
            if cur: cur['ops'].append(z)
            else: chunks.append(dict(t=None, kind=None, flush=None, s0=z['s0'], s1=z['s1'], ops=[z])); cur = chunks[-1]
            continue
        key = (round(z['t'] / 20), z['kind'] if z['kind'] != 'outline' else 'grey', z['flush'])
        st_ = z.get('solid_t', z['t'] if z['kind'] == 'solid' else 0)
        if cur and cur['t'] is None:  # 开头是门窗：并到第一段实墙
            cur.update(t=z['t'], kind=z['kind'], flush=z['flush'], key=key, solid_t=st_); cur['s1'] = z['s1']; continue
        if cur and cur.get('key') == key: cur['s1'] = z['s1']; continue
        chunks.append(dict(t=z['t'], kind=z['kind'], flush=z['flush'], key=key, s0=z['s0'], s1=z['s1'], ops=[], solid_t=st_)); cur = chunks[-1]
    for ch in chunks:
        if ch['t'] is None:  # 整面都是窗（转角窗、阳台玻璃）
            g = [z for z in ch['ops'] if not z.get('gap')]
            ch['t'] = max([z['t'] for z in g] or [w['t']]); ch['kind'] = 'glazing'
        for z in ch['ops']: ch['s1'] = max(ch['s1'], z['s1'])
    for k, ch in enumerate(chunks):
        a0 = w['e0'] if k == 0 else chunks[k - 1]['s1'] if chunks[k - 1]['s1'] <= ch['s0'] + 1 else ch['s0']
        a1 = w['e1'] if k == len(chunks) - 1 else ch['s1']
        if k > 0: a0 = chunks[k - 1]['_end']
        ch['_end'] = a1
        t = R5(ch['t'])
        kind = ch['kind']
        bearing = kind == 'solid' and ch.get('solid_t', t) >= a.bearing_min
        status = 'new' if kind == 'hatch' and a.hatch_as == 'new' else 'existing'
        A, B = ([R5(a0), R5(c)], [R5(a1), R5(c)]) if o == 'h' else ([R5(c), R5(a0)], [R5(c), R5(a1)])
        if abs(a1 - a0) < 50: continue
        sw = dict(a=A, b=B, t=t, bearing=bearing)
        if status != 'existing': sw['status'] = status
        if ch['flush']: sw['flush'] = FL[(o, ch['flush'])]
        sw['_src'] = w['id']; sw['_kind'] = kind
        ops = []
        for op in O_list:
            if op['wall'] != w['id'] or not (op['s0'] >= a0 - 5 and op['s1'] <= a1 + 5): continue
            d = {'type': op['type'], 'from': R5(op['s0']), 'to': R5(op['s1']), '_id': op['id']}
            if op['type'] in ('door', 'double', 'unequal'):
                if op.get('hinge'): d['hinge'] = op['hinge']
                if op.get('side'):
                    off = 600 * op['side']
                    mid = (op['s0'] + op['s1']) / 2
                    d['into'] = [R5(mid), R5(c + off)] if o == 'h' else [R5(c + off), R5(mid)]
            if op.get('sill') is not None: d['sill'] = op['sill']
            if op.get('win_h') and op.get('sill') is not None: d['head'] = op['sill'] + op['win_h']
            ops.append(d)
        if ops: sw['openings'] = ops
        spec_walls.append(sw)

for cn in connectors:
    A, B = ([R5(cn['a']), R5(cn['c'])], [R5(cn['b']), R5(cn['c'])]) if cn['orient'] == 'h' else ([R5(cn['c']), R5(cn['a'])], [R5(cn['c']), R5(cn['b'])])
    spec_walls.append(dict(a=A, b=B, t=R5(cn['t']), bearing=R5(cn['t']) >= a.bearing_min, _src='connector', _kind='connector'))
# 符号：方框 + 对角线 = 管井 / 烟道；圆 + 十字 = 地漏；小圆 = 立管
structs = []
for b in blocks: structs.append(dict(kind='column', at=[R5(b['x']), R5(b['y'])], w=R5(b['w']), d=R5(b['d']), _why='实心方块'))
def boxes():
    out = []
    for s in strokes:
        if layer_kind(s['layer']) in ('furn', 'dim', 'axis'): continue
        pts = [(X(p[0]), Y(p[1])) for p in s['pts']]
        if len(pts) == 5 and abs(pts[0][0] - pts[-1][0]) + abs(pts[0][1] - pts[-1][1]) < 2:
            xs_, ys_ = [p[0] for p in pts], [p[1] for p in pts]
            if is_ortho(pts[:-1], 1e-2): out.append((min(xs_), min(ys_), max(xs_), max(ys_)))
    return out
diags = [g for g in segs_mm if abs(g[2] - g[0]) > 20 and abs(g[3] - g[1]) > 20 and .4 < abs(g[2] - g[0]) / abs(g[3] - g[1]) < 2.5]
def has_diag(x0, y0, x1, y1):
    n = 0
    for g in diags:
        if min(g[0], g[2]) >= x0 - 15 and max(g[0], g[2]) <= x1 + 15 and min(g[1], g[3]) >= y0 - 15 and max(g[1], g[3]) <= y1 + 15 and math.hypot(g[2] - g[0], g[3] - g[1]) > .6 * math.hypot(x1 - x0, y1 - y0): n += 1
    return n
cands = boxes()
# 没有闭合矩形时：由对角线的包围盒反推（两条交叉对角线）
for i, g in enumerate(diags):
    for h in diags[i + 1:]:
        if abs(min(g[0], g[2]) - min(h[0], h[2])) < 15 and abs(max(g[0], g[2]) - max(h[0], h[2])) < 15 and abs(min(g[1], g[3]) - min(h[1], h[3])) < 15 and abs(max(g[1], g[3]) - max(h[1], h[3])) < 15:
            cands.append((min(g[0], g[2]), min(g[1], g[3]), max(g[0], g[2]), max(g[1], g[3])))
seen = []
# 外框套内框（包封管井）时用外框
cands = sorted(set(cands), key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))
for x0, y0, x1, y1 in cands:
    w_, d_ = x1 - x0, y1 - y0
    if not (100 <= w_ <= 1200 and 100 <= d_ <= 1200): continue
    inner = [b for b in cands if b != (x0, y0, x1, y1) and b[0] >= x0 - 5 and b[1] >= y0 - 5 and b[2] <= x1 + 5 and b[3] <= y1 + 5 and (b[2] - b[0]) > .4 * w_]
    if not has_diag(x0, y0, x1, y1) and not any(has_diag(*b) for b in inner): continue
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if any(abs(cx - q[0]) < 60 and abs(cy - q[1]) < 60 for q in seen): continue
    seen.append((cx, cy))
    structs.append(dict(kind='shaft', at=[R5(cx), R5(cy)], w=R5(w_), d=R5(d_), _why='方框内有对角线（烟道 / 风道 / 管井，厨房里的一般是烟道 flue）'))
for ar in arcs_mm:
    if not ar['full'] or not (30 <= ar['r'] <= 200): continue
    cx, cy, r = ar['cx'], ar['cy'], ar['r']
    if any(abs(cx - q[0]) < 40 and abs(cy - q[1]) < 40 for q in seen): continue
    cross = [g for g in segs_mm if math.hypot((g[0] + g[2]) / 2 - cx, (g[1] + g[3]) / 2 - cy) < r * .3 and 1.4 * r < math.hypot(g[2] - g[0], g[3] - g[1]) < 2.6 * r]
    seen.append((cx, cy))
    if len(cross) >= 2: structs.append(dict(kind='drain', at=[R5(cx), R5(cy)], _why=f'圆内十字 ⊕（地漏），半径 {R5(r)}'))
    elif r <= 90: structs.append(dict(kind='sewer', at=[R5(cx), R5(cy)], _why=f'小圆（排水立管 / 下水口，按位置确认），半径 {R5(r)}'))

rooms = []
for tx in texts:
    m = ROOM_RE.search(tx['text'])
    if m: rooms.append(dict(at=[R5(X(tx['x'])), R5(Y(tx['y']))], name=tx['text'] if len(tx['text']) <= 8 else m.group(1)))

# 轴线：虚线长直线
axes = []
for g in segs_mm:
    s = strokes[g[4]]
    if (s['dashed'] or layer_kind(s['layer']) == 'axis') and math.hypot(g[2] - g[0], g[3] - g[1]) > 2000:
        o = 'h' if abs(g[1] - g[3]) < 3 else 'v' if abs(g[0] - g[2]) < 3 else None
        if o: axes.append(dict(orient=o, at=R5(g[1] if o == 'h' else g[0])))
axes = [dict(t) for t in {(d['orient'], d['at']): d for d in axes}.values()]

dims_out = []
for ci, d in enumerate(merged_dims):
    at = (Y if d['orient'] == 'h' else X)(d['at']); tk = [(X if d['orient'] == 'h' else Y)(t, d['feet'][k]) for k, t in enumerate(d['ticks'])]
    if len(tk) < 2: continue
    labels = []
    for k in range(len(tk) - 1):
        v = dimvals.get((ci, k))
        labels.append(None if not v else (v['value'] if v['ok'] else f"?{v['text']}"))
    dims_out.append(dict(id=f'D{ci}', orient=d['orient'], at=round(at), ticks=[round(t, 1) for t in tk],
                         segs=[round(b - a_, 1) for a_, b in zip(tk, tk[1:])], labels=labels))

# ------------------------------------------------------------------ 10. 输出
out_dir = a.out or os.path.splitext(a.file)[0] + '_cad'
os.makedirs(out_dir, exist_ok=True)
ul = None
if render_pdf is not None:
    pix = render_pdf.get_pixmap(dpi=a.dpi); upath = os.path.join(out_dir, 'underlay.png'); pix.save(upath)
    k = 72 / a.dpi
    ul = dict(image=os.path.abspath(upath), mmPerPx=round(k * S, 4), x=round(-BX0 * S), y=round(-BY0 * S))
# 核对图（也作为 DXF 的底图）
pxmm = a.px
mx0 = min(min(X(p[0]) for p in allpts), 0) - 600; my0 = min(min(Y(p[1]) for p in allpts), 0) - 600
mx1 = max(X(p[0]) for p in allpts) + 600; my1 = max(Y(p[1]) for p in allpts) + 600
Wd, Hd = int((mx1 - mx0) / pxmm), int((my1 - my0) / pxmm)
if Wd * Hd > 6e7: pxmm *= math.sqrt(Wd * Hd / 6e7); Wd, Hd = int((mx1 - mx0) / pxmm), int((my1 - my0) / pxmm)
U = lambda x, y: (int(round((x - mx0) / pxmm)), int(round((y - my0) / pxmm)))
base = np.full((Hd, Wd, 3), 255, np.uint8)
for g in segs_mm: cv2.line(base, U(g[0], g[1]), U(g[2], g[3]), (60, 60, 60), 1, cv2.LINE_AA)
for f in fills:
    pts = np.array([U(X(p[0]), Y(p[1])) for p in f['poly']], np.int32)
    L = luminance(f['color']); v = int(255 * min(1, L)); cv2.fillPoly(base, [pts], (v, v, v) if f['kind'] != 'hatch' else (150, 150, 150))
if render_pdf is None:
    upath = os.path.join(out_dir, 'underlay.png'); cv2.imencode('.png', base)[1].tofile(upath)
    ul = dict(image=os.path.abspath(upath), mmPerPx=round(pxmm, 4), x=round(mx0), y=round(my0))
vis = cv2.addWeighted(base, .45, np.full_like(base, 255), .55, 0)
for gx in range(int(mx0 // 1000) * 1000, int(mx1) + 1, 500):
    x, _ = U(gx, 0); cv2.line(vis, (x, 0), (x, Hd), (255, 220, 190) if gx % 1000 else (240, 180, 120), 1)
    if gx % 1000 == 0: cv2.putText(vis, str(gx), (x + 2, 14), cv2.FONT_HERSHEY_SIMPLEX, .4, (200, 120, 40), 1)
for gy in range(int(my0 // 1000) * 1000, int(my1) + 1, 500):
    _, y = U(0, gy); cv2.line(vis, (0, y), (Wd, y), (255, 220, 190) if gy % 1000 else (240, 180, 120), 1)
    if gy % 1000 == 0: cv2.putText(vis, str(gy), (2, y - 2), cv2.FONT_HERSHEY_SIMPLEX, .4, (200, 120, 40), 1)
KC = {'solid': (40, 40, 220), 'grey': (0, 140, 255), 'hatch': (180, 60, 180), 'outline': (0, 170, 0), 'glazing': (230, 160, 0)}
for p in P:
    x0, y0, x1, y1 = (p['s0'], p['c'] - p['t'] / 2, p['s1'], p['c'] + p['t'] / 2) if p['orient'] == 'h' else (p['c'] - p['t'] / 2, p['s0'], p['c'] + p['t'] / 2, p['s1'])
    cv2.rectangle(vis, U(x0, y0), U(x1, y1), KC[p['kind']], 2)
for w in walls:
    A, B = ((w['e0'], w['c']), (w['e1'], w['c'])) if w['orient'] == 'h' else ((w['c'], w['e0']), (w['c'], w['e1']))
    cv2.line(vis, U(*A), U(*B), (0, 0, 160), 1)
    mid = U((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)
    cv2.putText(vis, w['id'], (mid[0] + 3, mid[1] - 3), cv2.FONT_HERSHEY_SIMPLEX, .45, (0, 0, 160), 1)
OC = {'window': (230, 120, 0), 'slideWindow': (230, 120, 0), 'hole': (0, 160, 160), 'door': (200, 0, 200), 'double': (200, 0, 200), 'unequal': (200, 0, 200), 'sliding': (200, 0, 200)}
for op in O_list:
    w = next(q for q in walls if q['id'] == op['wall'])
    x0, y0, x1, y1 = (op['s0'], w['c'] - w['t'] / 2 - 40, op['s1'], w['c'] + w['t'] / 2 + 40) if w['orient'] == 'h' else (w['c'] - w['t'] / 2 - 40, op['s0'], w['c'] + w['t'] / 2 + 40, op['s1'])
    cv2.rectangle(vis, U(x0, y0), U(x1, y1), OC.get(op['type'], (0, 0, 0)), 2)
    cv2.putText(vis, f"{op['id']} {op['type']}", (U(x1, y1)[0] + 2, U(x1, y0)[1] + 10), cv2.FONT_HERSHEY_SIMPLEX, .42, OC.get(op['type'], (0, 0, 0)), 1)
for s in structs:
    cv2.circle(vis, U(*s['at']), 9, (0, 120, 0), 2); cv2.putText(vis, s['kind'], (U(*s['at'])[0] + 10, U(*s['at'])[1]), cv2.FONT_HERSHEY_SIMPLEX, .42, (0, 120, 0), 1)
for d in dims_out:
    for t in d['ticks']:
        q = U(t, d['at']) if d['orient'] == 'h' else U(d['at'], t)
        cv2.circle(vis, q, 3, (160, 0, 160), 1)
    for k, lab in enumerate(d['labels']):  # 读出来的标注数字：绿 = 读出且和图形一致，红 = 没读出 / 不一致
        m = (d['ticks'][k] + d['ticks'][k + 1]) / 2
        q = U(m, d['at']) if d['orient'] == 'h' else U(d['at'], m)
        txt = '?' if lab is None else str(lab)
        col = (0, 140, 0) if isinstance(lab, (int, float)) else (0, 0, 220)
        cv2.putText(vis, txt, (q[0] - 12, q[1] + 14), cv2.FONT_HERSHEY_SIMPLEX, .38, col, 1)
cv2.imencode('.png', vis)[1].tofile(os.path.join(out_dir, 'cad.png'))

clean = lambda d: {k: v for k, v in d.items() if not k.startswith('_')}
draft = dict(name=os.path.splitext(os.path.basename(a.file))[0], height=2800, phase='renovate',
             walls=[dict(clean(w), **({'openings': [clean(o) for o in w['openings']]} if w.get('openings') else {})) for w in spec_walls],
             rooms=rooms, structs=[clean(s) for s in structs], autoElec=True, underlay=ul)
json.dump(draft, open(os.path.join(out_dir, 'draft.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
R1 = lambda v: round(v, 1)
info = dict(file=os.path.abspath(a.file), mmPerUnit=round(S, 5), scale_from=how, scale_check=check, typical_wall_t=round(MM(T)),
            outline_mm=[round(MM(BX1 - BX0)), round(MM(BY1 - BY0))],
            pieces=[dict(id=p['id'], orient=p['orient'], c=R1(p['c']), t=R1(p['t']), s0=R1(p['s0']), s1=R1(p['s1']), kind=p['kind'], flush=p.get('flush')) for p in P],
            walls=[dict(id=w['id'], orient=w['orient'], c=R1(w['c']), t=R1(w['t']), a=R1(w['e0']), b=R1(w['e1']), free=w['free'],
                        pieces=[z['id'] for z in w['items'] if not z.get('gap')]) for w in walls],
            openings=[{k: (R1(v) if isinstance(v, float) else v) for k, v in op.items()} for op in O_list],
            spec_walls=[dict(src=w['_src'], kind=w['_kind'], a=w['a'], b=w['b'], t=w['t']) for w in spec_walls],
            structs=structs, dims=dims_out, axes=axes, texts=[dict(text=t['text'], at=[R5(X(t['x'])), R5(Y(t['y']))]) for t in texts],
            inserts=[dict(name=i['name'], at=[R5(X(i['x'])), R5(Y(i['y']))], layer=i['layer']) for i in inserts][:300],
            dxf_dims=[dict(value=d['value'], a=[R5(X(d['p1'][0])), R5(Y(d['p1'][1]))], b=[R5(X(d['p2'][0])), R5(Y(d['p2'][1]))]) for d in dimsx][:400])
json.dump(info, open(os.path.join(out_dir, 'cad.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
kinds = Counter(p['kind'] for p in P)
print(json.dumps(dict(out=out_dir, mmPerUnit=round(S, 4), scale_from=how, scale_check=check, outline_mm=info['outline_mm'], typical_wall_t=info['typical_wall_t'],
                      pieces=dict(kinds), walls=len(spec_walls), openings=dict(Counter(o['type'] for o in O_list)), structs=dict(Counter(s['kind'] for s in structs)),
                      dims=len(dims_out), dim_labels=f"{sum(v['ok'] for v in dimvals.values())}/{len(dimvals)}",
                      dim_conflicts=[f"D{ci}#{k + 1} 标 {v['value']} 实际 {v['conflict']}" for (ci, k), v in dimvals.items() if isinstance(v.get('conflict'), float)],
                      texts=len(texts), rooms=len(rooms), free_ends=sum(len(w['free']) for w in walls)), ensure_ascii=False))
