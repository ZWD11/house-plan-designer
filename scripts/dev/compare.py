"""回归测试：比较两份 HouseSpec 的墙和洞口。
用法: python compare.py 真值spec.json 识别出的draft.json [dx dy]（不给平移就按两者墙体包围盒左上角对齐）
配合 make_test_dxf.py：把一份确认无误的 spec 画成 DXF（或再打印成 PDF），用 cadvec.py 识别回来，和原 spec 比。"""
import json, sys
sys.stdout.reconfigure(encoding='utf-8')
A = json.load(open(sys.argv[1], encoding='utf-8')); B = json.load(open(sys.argv[2], encoding='utf-8'))
dx = float(sys.argv[3]) if len(sys.argv) > 3 else None; dy = float(sys.argv[4]) if len(sys.argv) > 4 else None
def ops(S, dx=0, dy=0):
    out = []
    for w in S['walls']:
        h = w['a'][1] == w['b'][1]
        c = (w['a'][1] + dy) if h else (w['a'][0] + dx)
        for o in w.get('openings', []):
            f, e = sorted((o['from'], o['to']))
            sh = dx if h else dy
            out.append((o['type'], 'h' if h else 'v', c, f + sh, e + sh, o.get('hinge'), o.get('into')))
    return out
def bb(S):
    xs = [p[0] for w in S['walls'] for p in (w['a'], w['b'])]; ys = [p[1] for w in S['walls'] for p in (w['a'], w['b'])]
    return min(xs), min(ys)
if dx is None:
    (ax, ay), (bx, by) = bb(A), bb(B); dx, dy = ax - bx, ay - by
oa, ob = ops(A), ops(B, dx, dy)
print(f'平移 {dx:.0f},{dy:.0f}；真值 {len(oa)} 个洞口，识别 {len(ob)} 个')
TYPE = lambda t: 'window' if 'indow' in t or t == 'bay' else 'door' if t in ('door', 'unequal', 'double', 'pocket', 'folding') else t
bad = 0
for t, o, c, f, e, hg, into in oa:
    m = [q for q in ob if q[1] == o and abs(q[2] - c) < 80 and abs(q[3] - f) < 80 and abs(q[4] - e) < 80]
    if not m: print('  漏', t, o, round(c), round(f), round(e)); bad += 1; continue
    q = m[0]
    flag = '' if TYPE(q[0]) == TYPE(t) else '  ← 类型不同'
    if flag or abs(q[3] - f) > 20 or abs(q[4] - e) > 20: bad += 1
    print(f'  {t:11s} → {q[0]:11s} 端点误差 {q[3] - f:+5.0f} {q[4] - e:+5.0f}{flag}' + (f'  hinge {hg}→{q[5]}' if t == 'door' and hg != q[5] and q[5] else ''))
for q in ob:
    if not any(q[1] == o and abs(q[2] - c) < 80 and abs(q[3] - f) < 80 and abs(q[4] - e) < 80 for t, o, c, f, e, *_ in oa): print('  多', q[:5]); bad += 1
# 墙：比较中线覆盖
def segs(S, dx=0, dy=0):
    r = []
    for w in S['walls']:
        (x0, y0), (x1, y1) = w['a'], w['b']
        r.append(('h' if y0 == y1 else 'v', (y0 + dy) if y0 == y1 else (x0 + dx), min(x0, x1) + dx if y0 == y1 else min(y0, y1) + dy, max(x0, x1) + dx if y0 == y1 else max(y0, y1) + dy, w.get('t'), bool(w.get('bearing')), w.get('status', 'existing')))
    return r
sa, sb = segs(A), segs(B, dx, dy)
def cover(s, others):
    L = s[3] - s[2]; got = 0
    for q in others:
        if q[0] == s[0] and abs(q[1] - s[1]) < 30: got += max(0, min(q[3], s[3]) - max(q[2], s[2]))
    return got / max(1, L)
miss = [s for s in sa if cover(s, sb) < .9 and s[3] - s[2] > 200]
extra = [s for s in sb if cover(s, sa) < .9 and s[3] - s[2] > 200]
for s in miss: print('  墙漏', s)
for s in extra: print('  墙多', s)
tdiff = [(s, q) for s in sa for q in sb if q[0] == s[0] and abs(q[1] - s[1]) < 30 and min(q[3], s[3]) - max(q[2], s[2]) > 200 and (abs((q[4] or 0) - (s[4] or 0)) > 15 or q[5] != s[5] or q[6] != s[6])]
for s, q in tdiff[:12]: print('  属性不同', s[:2], 't', s[4], '→', q[4], 'bearing', s[5], '→', q[5], 'status', s[6], '→', q[6])
print('结果:', '通过' if not (bad or miss or extra) else f'{bad} 处洞口问题，{len(miss)} 墙漏，{len(extra)} 墙多，{len(tdiff)} 处属性不同')
