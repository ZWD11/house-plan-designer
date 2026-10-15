"""
整栋楼生成脚本模板：读入 cadsplit.py 的 building_draft.json，人工补齐后写出 spec.json，再用 build.py 打包。

  python cadsplit.py 图纸.svg --out work/split                 # 1. 切分 + 识别（PDF 加 --ref-dim 最外道总尺寸）
  python example-gen-building.py work/split/building_draft.json work/spec.json   # 2. 本脚本：补房间、门、楼梯、电梯、家具
  python build.py work/spec.json -o 输出.html                    # 3. 打包
  node check.mjs 输出.html work/check                             # 4. 逐层自查（report.json 的 floors[]、plan2d_<i>.png、view3d_cut<i>.png）

要点（实际项目照着改下面 FLOORS 里的内容）：
- 坐标：cadsplit 已经把各层对齐到同一坐标系（mm，x 向右、y 向下），先看 work/split/check<i>.png 确认墙、门窗、柱。
- 楼层顺序：默认按图纸排列。用楼梯核对：下层上行梯段的终点要落在上层楼梯起步处，不对就调 FLOORS 的顺序。
- 层高：看图上的层高 / 标高标注（▽ 数字）；楼板厚写在 spec 的 slab。
- 门：cadsplit 只认出“这里有门洞”（door / hole），开向、门轴、门的类型（单开 / 推拉 / 子母 / 入户门）在这里补。
- 楼梯：_candidates.stairs 是踏步组（rect、treads 踏步数、run 走向），U 形三跑楼梯写 stairU，直跑写 stairRun（h = 层高 + 楼板厚）。
  上层楼板在楼梯上方开洞（voids）；电梯井写 voids + "shaft": true，每层同一位置放 elevator。
- 房间名：图上的字常被炸成线 / 三角面，读不出来，按功能补 rooms。
"""
import json, sys
sys.stdout.reconfigure(encoding='utf-8')

src, dst = sys.argv[1], sys.argv[2]
d = json.load(open(src, encoding='utf-8'))
floors = d['floors']

def F(key, x, y, rot=0, **k): return dict(key=key, at=[x, y], rot=rot, **k)
def room(x, y, name, **k): return dict(at=[x, y], name=name, **k)

def find_opening(fl, x, y, tol=400):
    """找离 (x, y) 最近的洞口（门窗都行），返回 (墙, 洞口)；用来改门的类型、开向"""
    best = None
    for w in fl['walls']:
        horiz = w['a'][1] == w['b'][1]
        for op in w.get('openings', []):
            cx, cy = ((op['from'] + op['to']) / 2, w['a'][1]) if horiz else (w['a'][0], (op['from'] + op['to']) / 2)
            dd = abs(cx - x) + abs(cy - y)
            if dd < tol and (best is None or dd < best[0]): best = (dd, w, op)
    return (best[1], best[2]) if best else (None, None)

def set_door(fl, x, y, into, typ='door', hinge='from', **extra):
    """把 (x, y) 附近的洞口改成门：into = 门开进去那个房间里的一点"""
    w, op = find_opening(fl, x, y)
    if not op: print('没找到洞口', fl['name'], x, y); return
    op.update(type=typ, into=list(into), hinge=hinge, **extra)

def stair_u_from_candidates(fl, h, start='right'):
    """把 _candidates 里的踏步组合成一部 U 形楼梯（外包框 = 所有踏步组的外包）"""
    st = fl['_candidates'].get('stairs', [])
    if not st: return None
    x0 = min(s['rect'][0] for s in st); y0 = min(s['rect'][1] for s in st); x1 = max(s['rect'][2] for s in st); y1 = max(s['rect'][3] for s in st)
    return F('stairU', (x0 + x1) / 2, (y0 + y1) / 2, 0, w=x1 - x0, d=y1 - y0, h=h, opt={'start': start})

# ---------------------------------------------------------------- 每层补什么（示例：按自己的图改）
FLOORS = [
    # (楼层名, 层高, 房间标签, 门（位置、开进去的点、类型）, 家具)
    ('一层', 3600, [room(2000, 3000, '客厅'), room(9000, 3000, '餐厨'), room(10900, 5400, '卫生间')],
     [((11830, 900), (10900, 900), 'unequal', {'entry': True})], []),
    ('二层', 3300, [room(2000, 2000, '卧室')], [], []),
]
slab = d.get('slab', 120)
for i, (name, h, rooms, doors, furn) in enumerate(FLOORS):
    if i >= len(floors): break
    fl = floors[i]
    fl['name'] = name; fl['height'] = h
    fl['rooms'] = rooms
    for (pt, into, typ, extra) in doors: set_door(fl, *pt, into, typ, **extra)
    # 楼梯：最上一层不画上行楼梯就把 i + 1 < len(floors) 的条件留着
    s = stair_u_from_candidates(fl, h + slab) if i + 1 < len(floors) else None
    fl['furniture'] = ([s] if s else []) + furn
    # 上层楼板在楼梯上方开洞（楼梯井）
    if i > 0 and floors[i - 1].get('_candidates', {}).get('stair_zone'):
        z = floors[i - 1]['_candidates']['stair_zone']
        fl.setdefault('voids', []).append({'rect': z, 'name': '楼梯井'})

# 电梯（任何一层的候选里有，或者已知位置）：每层同一位置放 elevator，井道写 voids（"shaft": true）
lift = next((e for fl in floors for e in fl.get('_candidates', {}).get('elevator', [])), None)
if lift:
    x0, y0, x1, y1 = lift['rect']
    for g in floors:
        g.setdefault('furniture', []).append(F('elevator', (x0 + x1) / 2, (y0 + y1) / 2, 0, w=x1 - x0, d=y1 - y0))
        g.setdefault('voids', []).append({'rect': [x0, y0, x1, y1], 'shaft': True, 'name': '电梯井'})
for fl in floors: fl.pop('_candidates', None)
d.pop('_notes', None)
d['name'] = d.get('name') or '整栋楼'
json.dump(d, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('写出', dst, '·', len(floors), '层')
