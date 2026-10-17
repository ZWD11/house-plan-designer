"""独栋别墅（三层 + 车库 + 庭院）HouseSpec 样例：验证别墅识别建模（车库升降门、车棚、庭院围墙、泳池、挑空、电梯、影音室……）。
坐标 mm，原点 = 西北角（车库西墙 / 主楼北墙外皮），x 向东、y 向南。
主楼 x 6800–20800、y 0–11000；车库贴在主楼西侧 x 0–6800、y 3800–11000（二层是车库顶上的露台）；
庭院在主楼南侧 y 11000–19000，三面围墙（1.5m 高），南墙开车道口和人行门。"""
import json, sys

def H(y, x0, x1, t, bearing=False, ops=()):
    return dict(a=[x0, y], b=[x1, y], t=t, bearing=bearing, openings=[dict(o) for o in ops])
def V(x, y0, y1, t, bearing=False, ops=()):
    return dict(a=[x, y0], b=[x, y1], t=t, bearing=bearing, openings=[dict(o) for o in ops])
def O(typ, f, e, **k): return dict(type=typ, **{'from': f, 'to': e}, **k)
def F(key, x, y, rot=0, **k): return dict(key=key, at=[x, y], rot=rot, **k)
def R(x, y, name, **k): return dict(at=[x, y], name=name, **k)

H1, H2, H3, SLAB = 3300, 3000, 3000, 150
def low(w, sill, hh, gates=()):
    """围墙 / 女儿墙：整段开 sill 高以上的洞；gates = [(from, to)] 是不带窗台的通高洞口（车道口、人行门）"""
    horiz = w['a'][1] == w['b'][1]
    s0, s1 = sorted([w['a'][0], w['b'][0]] if horiz else [w['a'][1], w['b'][1]])
    cuts, cur = [], s0 + 1
    for a, b in sorted(gates):
        if a > cur: cuts.append(O('hole', cur, a, sill=sill, head=hh))
        cuts.append(O('hole', a, b, sill=0, head=hh)); cur = b
    if cur < s1 - 1: cuts.append(O('hole', cur, s1 - 1, sill=sill, head=hh))
    w['openings'] = cuts
    return w

STAIR = [15320, 120, 18440, 2600]          # 楼梯井（U 形三跑，上层楼板开洞）
SHAFT = [19400, 2650, 20500, 3950]          # 电梯井道
VOID = [11120, 5000, 15200, 10880]          # 客厅挑空（二层开洞）
def stair(h):   # U 形三跑：右侧起步，背面朝北
    return F('stairU', 16880, 1360, 0, w=3120, d=2480, h=h, opt={'start': 'right', 'run': 1100, 'land': 1000})
def lift(): return F('elevator', 19950, 3300, 0)

# ---------------------------------------------------------------- 一层
w1 = [
    # 主楼外墙
    H(0, 6800, 20800, 240, True, [O('window', 7600, 9600), O('window', 12000, 14200), O('window', 19000, 20200, sill=1200)]),
    V(20800, 0, 11000, 240, True, [O('window', 3200, 5000), O('window', 7400, 9800)]),
    H(11000, 6800, 20800, 240, True, [O('unequal', 7400, 8600, entry=True, into=[8000, 9500]), O('sliding', 10200, 14400), O('window', 16500, 19500)]),
    V(6800, 0, 11000, 240, True, [O('door', 4700, 5500, hinge='from', into=[8000, 5100])]),   # 车库 → 设备间
    # 车库
    H(3800, 0, 6800, 240, True), V(0, 3800, 11000, 240, True, [O('window', 5600, 7400, sill=1500)]),
    H(11000, 0, 6800, 240, True, [O('garage', 800, 5800)]),
    # 主楼内墙
    V(11000, 0, 4200, 120, False, [O('sliding', 1200, 3200)]),                 # 厨房 / 餐厅
    H(4200, 6800, 11000, 120, False),                                          # 厨房南墙
    V(9400, 4200, 11000, 120, False, [O('hole', 7600, 10200)]),                # 玄关 → 客厅 垭口
    H(4200, 11000, 14000, 120, False),                                         # 电视背景墙（东头留 1.2m 通餐厅）
    H(7000, 6800, 9400, 120, False, [O('door', 8200, 9000, hinge='to', into=[8600, 6200])]),  # 设备间门（从玄关进）
    V(15200, 0, 11000, 240, True, [O('hole', 2700, 4100), O('hole', 4400, 5800)]),           # 餐厅 / 客厅 → 过厅
    V(18500, 0, 2600, 120, False),                                             # 楼梯 / 公卫
    H(2600, 18500, 20800, 120, False, [O('door', 19100, 19900, hinge='to', into=[19500, 1500])]),
    H(6000, 15200, 20800, 120, False, [O('door', 15500, 16400, hinge='from', into=[16000, 7500])]),  # 老人房门
    V(18300, 6000, 8400, 120, False, [O('door', 6200, 7000, hinge='from', into=[19500, 6800])]),   # 老人房卫生间
    H(8400, 18300, 20800, 120, False),
    # 庭院围墙（1.5m）：西、南、东三面，南墙开车道口和人行门
    low(V(0, 11000, 19000, 200), 1500, H1),
    low(H(19000, 0, 20800, 200), 1500, H1, [(800, 5800), (7500, 8500)]),
    low(V(20800, 11000, 19000, 200), 1500, H1),
]
f1furn = [
    # 车库：两个车位、壁挂充电桩、储物架、工具台、自行车
    F('suv', 2050, 7600, 180), F('car', 4700, 7600, 180), F('evCharger', 3400, 3995, 0),
    F('garageShelf', 370, 5300, 270, w=2400), F('workbench', 6355, 6800, 90, w=1400), F('bicycle', 6250, 8800, 0),
    # 厨房、餐厅
    F('lCounter', 7900, 1300, 0, w=2000, d=1800), F('fridgeDouble', 10350, 600, 0), F('kitchenIsland', 8900, 3000, 0, w=1800),
    F('longTable', 13100, 2300, 0), *[F('chair', 12300 + k * 800, 1500, 0) for k in range(3)], *[F('chair', 12300 + k * 800, 3100, 180) for k in range(3)],
    F('sideboard', 13100, 320, 0, w=2000, h=900),
    # 客厅（挑空）
    F('lSofa', 12300, 9100, 180, w=3200), F('coffeeTable', 12300, 7300, 0), F('tvCabinet', 12300, 4460, 0, w=2400), F('rug', 12300, 7300, 0, w=3000, d=2400),
    F('armchair', 10300, 6800, 90), F('grandPiano', 14200, 6300, 0), F('acFloor', 10000, 4550, 0), F('bigPlant', 14700, 10400),
    # 玄关、设备间
    F('shoeCabinet', 7095, 8800, 270, w=1600),
    F('boiler', 7095, 6000, 270), F('waterSoftener', 7145, 6600, 270), F('manifold', 9280, 5300, 90), F('washer', 8000, 4520, 0), F('dryer', 8650, 4520, 0),
    # 楼梯、电梯、过厅
    stair(H1 + SLAB), lift(), F('consoleTable', 17000, 5770, 180),
    # 公卫
    F('toilet', 20330, 1550, 90), F('vanity', 18810, 1100, 270, w=900), F('shower', 20180, 620, 0, w=1000, d=900),
    # 老人房 + 卫生间
    F('bed15', 16700, 9855, 180), F('nightstand', 15620, 10670, 180), F('nightstand', 17780, 10670, 180), F('wardrobe', 15620, 7800, 270, w=1700), F('acWall', 18300, 10850, 180),
    F('toilet', 20330, 7000, 90), F('vanity', 19000, 8090, 180, w=900), F('shower', 20180, 7900, 0, w=1000, d=900),
    # 庭院：车棚车位、草坪、凉亭、泳池、躺椅、遮阳伞、秋千、烧烤台、景墙、草坪灯、乔木、灌木、大门
    F('carport2', 3300, 15900, 0, w=5400), F('car', 3300, 16000, 0, color='#c9ccd1'),
    F('stepStones', 8000, 15000, 0, d=7600), F('lawn', 11000, 15000, 0, w=4400, d=6400), F('gazebo', 11000, 16300, 0, w=3000, d=3000),
    F('pool', 16800, 16600, 90, w=3400, d=7000), F('sunLounger', 16200, 13600, 0), F('sunLounger', 17200, 13600, 0), F('parasol', 19400, 12700, 0),
    F('swing', 14600, 13000, 0), F('bbq', 15450, 11445, 0), F('waterFeature', 11000, 18500, 180, w=2000),
    *[F('lawnLamp', 7500, y) for y in (12300, 14800, 17300)], F('tree', 12600, 12400, 0, w=2000, d=2000),
    F('shrub', 9600, 11600), F('gate', 3300, 19000, 0, w=4800), F('gate', 8000, 19000, 0, w=1000),
]
f1 = dict(name='一层', height=H1, walls=w1, autoElec=True,
          rooms=[R(3400, 9500, '车库', mat='epoxy'), R(8800, 1800, '厨房', mat='tile'), R(13000, 1200, '餐厅', mat='marble'),
                 R(12300, 7000, '客厅', mat='marble'), R(8000, 9800, '玄关', mat='marble'), R(8000, 5800, '设备间', mat='cement'),
                 R(16850, 2000, '楼梯', mat='marble'), R(19700, 1200, '公卫', mat='bath'), R(17800, 4300, '过厅', mat='marble'),
                 R(16700, 8800, '老人房', mat='oak'), R(19600, 7400, '卫生间', mat='bath'), R(10000, 13000, '庭院', mat='paving')],
          structs=[dict(kind='sewer', at=[20375, 1550]), dict(kind='sewer', at=[20375, 7000]), dict(kind='drain', at=[20180, 620]), dict(kind='drain', at=[20180, 7900]),
                   dict(kind='drain', at=[3400, 10500])],
          furniture=f1furn)

# ---------------------------------------------------------------- 二层
w2 = [
    H(0, 6800, 20800, 240, True, [O('window', 7600, 9600, sill=1500), O('window', 12000, 14200), O('window', 19000, 20200, sill=1200)]),
    V(20800, 0, 11000, 240, True, [O('window', 6400, 8400), O('window', 9000, 10400)]),
    H(11000, 6800, 20800, 240, True, [O('window', 7600, 10200), O('floorWindow', 11600, 14800), O('window', 15800, 17600), O('window', 18600, 20200)]),
    V(6800, 0, 11000, 240, True, [O('sliding', 6000, 8400)]),                 # 主卧 → 车库顶露台
    # 车库顶露台女儿墙
    low(H(3800, 0, 6800, 150), 1100, H2), low(V(0, 3800, 11000, 150), 1100, H2), low(H(11000, 0, 6800, 150), 1100, H2),
    # 主卧套房：主卫、衣帽间、主卧
    H(3000, 6800, 10200, 120, False, [O('door', 7200, 7900, hinge='from', into=[7600, 2200])]),
    V(10200, 0, 4800, 120, False, [O('door', 3400, 4200, hinge='to', into=[10700, 3800])]),   # 衣帽间 → 家庭厅（套房门）
    H(4800, 6800, 11120, 120, False, [O('hole', 7400, 8400)]),                # 主卧 → 衣帽间
    V(11120, 4800, 11000, 120, False),                                         # 主卧 / 挑空
    low(H(5000, 11120, 15200, 120), 1100, H2),                                 # 挑空栏板
    # 楼梯 / 公卫 / 过厅 / 次卧
    V(15200, 0, 5000, 240, True, [O('hole', 2800, 4600)]), V(15200, 5000, 11000, 240, True),
    V(18500, 0, 2600, 120, False), H(2600, 18500, 20800, 120, False, [O('door', 19100, 19900, hinge='to', into=[19500, 1500])]),
    H(5000, 15200, 20800, 120, False, [O('door', 16300, 17100, hinge='from', into=[16700, 6000]), O('door', 18300, 19100, hinge='from', into=[18700, 6000])]),
    V(18000, 5000, 11000, 120, False),
]
f2furn = [
    stair(H2 + SLAB), lift(),
    # 主卧套房
    F('bed18', 8800, 9830, 180), F('nightstand', 7520, 10670, 180), F('nightstand', 10080, 10670, 180), F('bedBench', 8800, 8350, 0, w=1600),
    F('tvCabinet', 9500, 5060, 0, w=1400), F('lounge', 10685, 6400, 90), F('acWall', 10930, 8000, 90), F('curtain', 8900, 10800, 180, w=2800),
    F('cabWardrobe', 8400, 3360, 0, w=2800),
    F('bathtub', 7950, 520, 0), F('shower', 9650, 650, 0, w=1000, d=1000), F('vanity', 9865, 2100, 90, w=1200), F('toilet', 7270, 1600, 270),
    # 家庭厅（回廊）
    F('sofa', 12900, 600, 0), F('coffeeTable', 12900, 1900, 0), F('bookshelf', 14905, 1500, 90, w=2000), F('acWall', 11300, 380, 0),
    F('chandelier', 13150, 7900, 0),      # 挑空大吊灯：挂在二层顶面，垂进客厅
    # 公卫
    F('toilet', 20330, 1550, 90), F('vanity', 18810, 1100, 270, w=900), F('shower', 20180, 620, 0, w=1000, d=900),
    # 次卧 ×2
    F('bed15', 16600, 9855, 180), F('nightstand', 15600, 10670, 180), F('desk', 15620, 7000, 270, w=1100), F('officeChair', 16150, 7000, 90), F('acWall', 16600, 10850, 180),
    F('bed12', 19400, 9880, 180), F('nightstand', 20350, 10670, 180), F('wardrobe', 19900, 5360, 0, w=1400), F('acWall', 19400, 10850, 180),
    # 车库顶露台
    F('outdoorSet', 3400, 6200), F('lounge', 1200, 9300, 90), F('lounge', 1200, 10200, 90), F('bigPlant', 600, 4400), F('plantShelf', 3400, 10600, 180),
]
f2 = dict(name='二层', height=H2, walls=w2, autoElec=True,
          rooms=[R(8800, 7400, '主卧', mat='oak'), R(8500, 3900, '衣帽间', mat='oak'), R(8500, 1500, '主卫', mat='bath'), R(12900, 2700, '家庭厅', mat='oak'),
                 R(13150, 7900, '挑空'), R(16850, 2000, '楼梯', mat='marble'), R(19700, 1200, '公卫', mat='bath'), R(17800, 4000, '过厅', mat='oak'),
                 R(16600, 8000, '次卧', mat='oak'), R(19400, 8000, '儿童房', mat='oak'), R(3400, 7400, '露台', mat='deck')],
          structs=[dict(kind='sewer', at=[20375, 1550]), dict(kind='sewer', at=[7225, 1600]), dict(kind='drain', at=[9650, 650]), dict(kind='drain', at=[20180, 620]), dict(kind='drain', at=[3400, 10600])],
          voids=[dict(rect=STAIR, name='楼梯井'), dict(rect=VOID, name='客厅挑空'), dict(rect=SHAFT, name='电梯井', shaft=True)],
          furniture=f2furn)

# ---------------------------------------------------------------- 三层
w3 = [
    H(0, 6800, 20800, 240, True, [O('window', 7600, 9600, sill=1200), O('window', 19000, 20200, sill=1200)]),
    V(20800, 0, 5000, 240, True, [O('window', 3200, 4600)]),
    low(V(20800, 5000, 11000, 150), 1100, H3), low(H(11000, 15200, 20800, 150), 1100, H3),   # 东南露台女儿墙
    H(11000, 6800, 15200, 240, True, [O('window', 11800, 14400)]),
    V(6800, 0, 11000, 240, True, [O('window', 1400, 3200)]),
    H(4800, 6800, 11000, 120, False, [O('door', 10000, 10800, hinge='to', into=[10400, 5600])]),   # 茶室 / 影音室
    V(11000, 0, 11000, 120, False, [O('double', 1600, 3000, into=[10000, 2300]), O('door', 6000, 6800, hinge='from', into=[11700, 6400])]),
    H(5000, 11000, 15200, 120, False, [O('hole', 12400, 14000)]),             # 休闲厅 / 台球室
    V(15200, 0, 11000, 240, True, [O('hole', 2800, 4600), O('sliding', 7000, 9000)]),   # 休闲厅 → 过厅；台球室 → 露台
    V(18500, 0, 2600, 120, False), H(2600, 18500, 20800, 120, False, [O('door', 19100, 19900, hinge='to', into=[19500, 1500])]),
    H(5000, 15200, 20800, 240, True, [O('sliding', 16200, 18200)]),          # 过厅 → 露台
]
f3furn = [
    lift(),
    # 茶室
    F('teaTable', 8900, 2000, 0), F('mahjong', 8900, 3900, 0, w=900, d=900), F('displayCabinet', 7120, 2400, 90, w=2000), F('acWall', 10300, 380, 0),
    # 影音室
    F('projScreen', 8900, 10850, 180, w=3000), F('speaker', 7300, 10500, 180), F('speaker', 10500, 10500, 180),
    F('theaterSofa', 8900, 6600, 0, w=3000), F('theaterSofa', 8900, 8700, 0, w=3000), F('acWall', 7050, 7500, 270),
    # 休闲厅（吧台、酒柜）
    F('barCounter', 13100, 1900, 0, w=2600), F('wineCabinet', 13100, 330, 0, w=2000), F('sofa', 13100, 4100, 180, w=1800),
    # 台球室 + 桑拿
    F('billiards', 13100, 7900, 90), F('sauna', 14400, 10150, 0, w=1500, d=1500), F('acWall', 12600, 10850, 180),
    # 公卫
    F('toilet', 20330, 1550, 90), F('vanity', 18810, 1100, 270, w=900), F('shower', 20180, 620, 0, w=1000, d=900),
    # 露台
    F('outdoorSet', 18000, 8000), F('sunLounger', 20000, 7500, 0), F('bigPlant', 15700, 10400), F('plantShelf', 18000, 10600, 180),
]
f3 = dict(name='三层', height=H3, walls=w3, autoElec=True,
          rooms=[R(8900, 2800, '茶室', mat='walnut'), R(8900, 9500, '影音室', mat='walnut'), R(13100, 3300, '休闲厅', mat='oak'),
                 R(13100, 9800, '台球室', mat='oak'), R(16850, 2000, '楼梯', mat='marble'), R(19700, 1200, '公卫', mat='bath'),
                 R(17000, 4300, '健身区', mat='oak'), R(18000, 9000, '露台', mat='deck')],
          structs=[dict(kind='sewer', at=[20375, 1550]), dict(kind='drain', at=[20180, 620]), dict(kind='drain', at=[20000, 10600])],
          voids=[dict(rect=STAIR, name='楼梯井'), dict(rect=SHAFT, name='电梯井', shaft=True)],
          furniture=f3furn)

for fl in (f1, f2, f3):
    for w in fl['walls']:
        if not w['openings']: del w['openings']
spec = dict(name='独栋别墅 · 三层', slab=SLAB, floors=[f1, f2, f3])
json.dump(spec, open(sys.argv[1] if len(sys.argv) > 1 else 'spec.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('ok')
