"""把一份 HouseSpec 画成“天正 / 设计院风格”的 DXF，用来回归测试 cadvec.py：
WALL 层（承重墙 SOLID 填充、新砌墙 ANSI31 图案、隔墙两条线）、WINDOW 层四线窗、DOOR 层门扇 + 开启弧、
PUB_TEXT 房间名、PUB_DIM 线性标注、AXIS 点划线轴线、FURN 层家具块（应被忽略）。
用法: python make_test_dxf.py spec.json out.dxf [--rot] [--offset X Y]"""
import json, math, sys
import ezdxf

spec = json.load(open(sys.argv[1], encoding='utf-8'))
out = sys.argv[2]
OX, OY = (float(sys.argv[sys.argv.index('--offset') + 1]), float(sys.argv[sys.argv.index('--offset') + 2])) if '--offset' in sys.argv else (50000.0, 80000.0)
doc = ezdxf.new('R2010', setup=True)
doc.header['$INSUNITS'] = 4
for name, col, lt in (('WALL', 7, 'CONTINUOUS'), ('WINDOW', 4, 'CONTINUOUS'), ('DOOR', 3, 'CONTINUOUS'), ('PUB_TEXT', 7, 'CONTINUOUS'),
                      ('PUB_DIM', 3, 'CONTINUOUS'), ('AXIS', 1, 'DASHDOT'), ('FURN', 6, 'CONTINUOUS'), ('WALL-HATCH', 8, 'CONTINUOUS')):
    doc.layers.add(name, color=col, linetype=lt)
msp = doc.modelspace()
P = lambda x, y: (OX + x, OY - y)  # y 朝上

def rect(x0, y0, x1, y1): return [P(x0, y0), P(x1, y0), P(x1, y1), P(x0, y1)]
for w in spec['walls']:
    (ax, ay), (bx, by), t = w['a'], w['b'], w.get('t', 120)
    horiz = ay == by
    lo, hi = (min(ax, bx), max(ax, bx)) if horiz else (min(ay, by), max(ay, by))
    c = ay if horiz else ax
    # 只在和垂直墙相交的端点外延半个墙厚（让填充在转角处连起来）；直线接着的墙不外延，免得盖住旁边的门洞
    def perp_at(px, py):
        for q in spec['walls']:
            (qx0, qy0), (qx1, qy1) = q['a'], q['b']
            qh = qy0 == qy1
            if qh == horiz: continue
            if qh and abs(qy0 - py) < 5 and min(qx0, qx1) - 5 <= px <= max(qx0, qx1) + 5: return True
            if not qh and abs(qx0 - px) < 5 and min(qy0, qy1) - 5 <= py <= max(qy0, qy1) + 5: return True
        return False
    if perp_at(*((lo, c) if horiz else (c, lo))): lo -= t / 2
    if perp_at(*((hi, c) if horiz else (c, hi))): hi += t / 2
    ops = sorted([(min(o['from'], o['to']), max(o['from'], o['to']), o) for o in w.get('openings', [])], key=lambda z: z[0])
    cuts, cur = [], lo
    for f, e, o in ops:
        if f > cur: cuts.append((cur, f))
        cur = max(cur, e)
    if hi > cur: cuts.append((cur, hi))
    bearing, new = w.get('bearing'), w.get('status') == 'new'
    for s0, s1 in cuts:
        box = rect(s0, c - t / 2, s1, c + t / 2) if horiz else rect(c - t / 2, s0, c + t / 2, s1)
        if bearing or new:
            h = msp.add_hatch(color=7 if bearing else 8, dxfattribs={'layer': 'WALL-HATCH' if new else 'WALL'})
            if new: h.set_pattern_fill('ANSI31', scale=20)
            h.paths.add_polyline_path(box, is_closed=True)
        # 墙线
        if horiz:
            msp.add_line(P(s0, c - t / 2), P(s1, c - t / 2), dxfattribs={'layer': 'WALL'}); msp.add_line(P(s0, c + t / 2), P(s1, c + t / 2), dxfattribs={'layer': 'WALL'})
        else:
            msp.add_line(P(c - t / 2, s0), P(c - t / 2, s1), dxfattribs={'layer': 'WALL'}); msp.add_line(P(c + t / 2, s0), P(c + t / 2, s1), dxfattribs={'layer': 'WALL'})
    for f, e, o in ops:
        ty = o['type']
        if 'indow' in ty:
            for k in (-.5, -1 / 6, 1 / 6, .5):
                if horiz: msp.add_line(P(f, c + k * t), P(e, c + k * t), dxfattribs={'layer': 'WINDOW'})
                else: msp.add_line(P(c + k * t, f), P(c + k * t, e), dxfattribs={'layer': 'WINDOW'})
            mid = (f + e) / 2
            code = f"C{round((e - f) / 100):02d}{15:02d}"
            msp.add_text(code, height=150, dxfattribs={'layer': 'PUB_TEXT'}).set_placement(P(mid, c + t + 250) if horiz else P(c + t + 250, mid))
        elif ty in ('door', 'unequal', 'double'):
            hinge_at = f if o.get('hinge', 'from') == 'from' else e
            other = e if hinge_at == f else f
            into = o.get('into')
            side = 1
            if into: side = 1 if ((into[1] - c) if horiz else (into[0] - c)) > 0 else -1
            W = e - f
            hx, hy = (hinge_at, c) if horiz else (c, hinge_at)
            # 门扇：从门轴垂直伸向开启侧；弧：从门扇端点扫到洞口另一端
            leaf_end = (hinge_at, c + side * W) if horiz else (c + side * W, hinge_at)
            msp.add_line(P(hx, hy), P(*leaf_end), dxfattribs={'layer': 'DOOR'})
            cx, cy = P(hx, hy)
            a1 = math.degrees(math.atan2(-(leaf_end[1] - hy), leaf_end[0] - hx))
            a2 = math.degrees(math.atan2(-((c if horiz else other) - hy), (other if horiz else c) - hx))
            s_, e_ = (a1, a2) if (a2 - a1) % 360 <= 180 else (a2, a1)
            msp.add_arc((cx, cy), W, s_, e_, dxfattribs={'layer': 'DOOR'})
            msp.add_text(f"M{round(W / 100):02d}21", height=150, dxfattribs={'layer': 'PUB_TEXT'}).set_placement(P((f + e) / 2, c - side * 300) if horiz else P(c - side * 300, (f + e) / 2))
        elif ty == 'sliding':
            for k, (s0, s1) in ((-.15, (f, (f + e) / 2 + 50)), (.15, ((f + e) / 2 - 50, e))):
                if horiz: msp.add_line(P(s0, c + k * t), P(s1, c + k * t), dxfattribs={'layer': 'DOOR'})
                else: msp.add_line(P(c + k * t, s0), P(c + k * t, s1), dxfattribs={'layer': 'DOOR'})
for r in spec.get('rooms', []):
    msp.add_text(r['name'], height=300, dxfattribs={'layer': 'PUB_TEXT'}).set_placement(P(*r['at']))
# 家具块（应被忽略）
blk = doc.blocks.new('BED1800')
blk.add_lwpolyline([(0, 0), (1800, 0), (1800, 2000), (0, 2000)], close=True)
blk.add_line((0, 1800), (1800, 1800))
for f in spec.get('furniture', []):
    if f['key'].startswith('bed'): msp.add_blockref('BED1800', P(f['at'][0] - 900, f['at'][1] + 1000), dxfattribs={'layer': 'FURN'})
# 轴线 + 总尺寸标注
xs = sorted({w['a'][0] for w in spec['walls'] if w['a'][0] == w['b'][0] and w.get('bearing')})
ys = sorted({w['a'][1] for w in spec['walls'] if w['a'][1] == w['b'][1] and w.get('bearing')})
X0, X1, Y0, Y1 = min(xs), max(xs), min(ys), max(ys)
for x in xs[:12]: msp.add_line(P(x, Y0 - 1500), P(x, Y1 + 1500), dxfattribs={'layer': 'AXIS'})
for y in ys[:12]: msp.add_line(P(X0 - 1500, y), P(X1 + 1500, y), dxfattribs={'layer': 'AXIS'})
for a_, b_ in zip(xs, xs[1:]):
    msp.add_linear_dim(base=P(a_, Y1 + 1200), p1=P(a_, Y1), p2=P(b_, Y1), dimstyle='EZDXF', dxfattribs={'layer': 'PUB_DIM'}).render()
doc.saveas(out)
print('ok', out)
