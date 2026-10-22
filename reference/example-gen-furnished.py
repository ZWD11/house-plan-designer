"""大平层四室.jpg（四室、带保姆房的大平层）户型描述生成脚本。
像素 → 毫米按四周分段尺寸（轴线尺寸）分段线性换算；图上的楼梯间、电梯井、电梯厅是公共部分（楼梯按用户说明画错了，不要），只还原户内。"""
import json, sys
sys.path.insert(0, r'<skill 目录>/scripts')  # 改成本 skill 的 scripts 目录
from axismap import Axis, chain

X = Axis(chain([300, 509, 718, 858, 1135, 1290], [3100, 3100, 2100, 4100, 2300]),
         chain([300, 597, 858, 1303, 1553, 1700], [4400, 3900, 6600, 3700, 2200]))
Y = Axis(chain([343, 539, 721, 1044, 1597], [2900, 2700, 4800, 8200]), [(1138, 11800), (1597, 18600)])
if '--report' in sys.argv: X.report(); Y.report(); sys.exit()

r5 = lambda v: round(v / 5) * 5
P = lambda x, y: [r5(X(x, None)), r5(Y(y, None))]
def ops(A, lst):
    out = []
    for o in lst:
        o = dict(o); f, e = o.pop('f'), o.pop('e')
        if 'into' in o: o['into'] = P(*o['into'])
        out.append(dict(o, **{'from': r5(A(f, None)), 'to': r5(A(e, None))}))
    return out
def H(y, x0, x1, t, bearing=False, o=()):
    w = dict(a=P(x0, y), b=P(x1, y), t=t, bearing=bearing)
    if o: w['openings'] = ops(X, o)
    return w
def V(x, y0, y1, t, bearing=False, o=()):
    w = dict(a=P(x, y0), b=P(x, y1), t=t, bearing=bearing)
    if o: w['openings'] = ops(Y, o)
    return w

# 墙的位置和厚度：按原图两个墙面量出来的（scripts/wallfit.py），不是按刻度猜。
# 外墙涂黑 ≈ 21px ≈ 300；内承重墙 14~15px ≈ 210；描边非承重墙和旁边涂黑的一样厚、墙面对齐（不是 100 的薄隔墙）
EX, E, T = 300, 210, 100
xW, x509, x597, x718, x858, x1140, xNE, x1303, x1553, xE = 305.5, 511, 598.5, 720, 861.5, 1141, 1292.5, 1306, 1558.5, 1703.5
yN0, yN, y985, y1044, yS, yB = 541.5, 725, 984, 1044, 1503, 1595
def fl(w, side): w['flush'] = side; return w
walls = [
 # 北外墙（主卫 / 茶室 / 公卫 / 厨房），主卫西北角是转角窗
 H(yN, xW, x1140, EX, True, [dict(type='window', f=316, e=430), dict(type='window', f=551, e=672),
                             dict(type='highWindow', f=750, e=830), dict(type='window', f=895, e=1110)]),
 # 保姆间凸出的北段（外墙 300），往下接 210 的内墙、东侧墙面对齐
 V(x1140, yN0, yN, EX, True),
 H(yN0, x1140, xNE, 270, True, [dict(type='highWindow', f=1182, e=1272)]),
 # 东外墙：保姆间 + 餐厅东侧（外面是电梯厅）
 V(xNE, yN0, 1139, E, True),
 # 入户：电梯厅进来的入户门
 H(1139, xNE, xE, 220, True, [dict(type='door', f=1362, e=1450, hinge='from', into=(1405, 1060), entry=True)]),
 V(xE, 1139, yB, E, True),
 # 西外墙：主卫转角窗、主卧转角落地窗
 V(xW, yN, yB, EX, True, [dict(type='window', f=724, e=818), dict(type='floorWindow', f=1365, e=1584)]),
 # 南：主卧外墙 + 阳台栏板（四段阳台各自分开，分隔墙和上面的墙一样厚、对齐）
 H(yB, xW, x597, EX, True, [dict(type='floorWindow', f=316, e=492)]),
 H(yB, x597, x858, 120, False, [dict(type='hole', f=612, e=852, sill=1100)]),
 H(yB, x858, x1303, 120, False, [dict(type='hole', f=870, e=1296, sill=1100)]),
 H(yB, x1303, 1562, 120, False, [dict(type='hole', f=1315, e=1554, sill=1100)]),
 H(yB, 1562, xE, 120, False, [dict(type='hole', f=1570, e=1694, sill=1100)]),
 V(x597, yS, yB, E, True), V(x858, yS, yB, E), V(x1303, yS, yB, E), V(1562, yS, yB, E),
 # 卧室与阳台之间
 H(yS, x597, xE, 220, True, [dict(type='window', f=632, e=747), dict(type='door', f=747, e=812, hinge='to', into=(780, 1550)),
                          dict(type='floorWindow', f=895, e=1185), dict(type='door', f=1185, e=1252, hinge='to', into=(1220, 1550)),
                          dict(type='window', f=1345, e=1462), dict(type='door', f=1462, e=1530, hinge='to', into=(1495, 1550)),
                          dict(type='door', f=1597, e=1656, hinge='from', into=(1625, 1550))]),
 # 主卫（西北角）、茶室
 V(x509, yN, y1044, E, True), V(x509, y1044, 1078, E, True),  # 主卫东墙往下多出一截（衣帽间里的墙垛）
 H(y1044, xW, x509, T, False, [dict(type='sliding', f=355, e=428)]),
 H(820, xW, x509, 80, False, [dict(type='door', f=383, e=428, hinge='from', into=(405, 850))]),
 H(890, 428, x509, 80), V(428, 890, y1044, 80, False, [dict(type='door', f=935, e=985, hinge='to', into=(400, 960))]),
 # 茶室南边（门后面）是一整排玻璃隔断，后面就是衣帽间的柜子
 H(y985, x509, x718, 80, False, [dict(type='glassWall', f=520, e=711)]),
 V(x718, yN, 1218, E, True, [dict(type='door', f=907, e=977, hinge='to', into=(660, 930)),
                             dict(type='door', f=1135, e=1200, hinge='to', into=(680, 1160))]),
 # 公卫
 V(x858, yN, 903, E, True),
 H(903, x718, x858, T, False, [dict(type='door', f=730, e=790, hinge='from', into=(760, 870))]),
 # 备餐间
 H(1118, x718, 863.5, E, True),
 V(863.5, y985, 1118, 120), H(y985, x718, 863.5, 80, False, [dict(type='sliding', f=752, e=816)]),
 # 保姆间 + 保姆卫：西墙下段 210 厚，和上面 300 的外墙东侧墙面对齐
 fl(V(x1140, yN, 882, E), 'E'), fl(V(x1140, 882, 903, E), 'E'),
 H(903, x858, x1140, 80, False, [dict(type='sliding', f=909, e=1097)]),
 H(646, x1140, xNE, 120, False, [dict(type='door', f=1228, e=1277, hinge='to', into=(1250, 615))]),
 H(882, x1140, xNE, 120, False, [dict(type='door', f=1222, e=1285, hinge='to', into=(1250, 850))]),
 # 次卧套房（主卧东侧）：东墙上段描边、下段涂黑，一样厚
 V(x597, 1218, yS, E, True),
 H(1218, x597, x858, 150, False, [dict(type='door', f=760, e=827, hinge='to', into=(800, 1255))]),
 V(x858, 1218, 1345, E), V(x858, 1345, yS, E, True),
 H(1366, x597, 752, T),
 V(752, 1218, 1366, 80, False, [dict(type='pocket', f=1258, e=1317, hinge='to')]),
 V(675, 1218, 1366, 60, False, [dict(type='door', f=1280, e=1322, hinge='from', into=(700, 1300))]),
 # 东南卧室 + 卫生间：西墙上段描边、下段涂黑，一样厚
 V(x1303, 1279, 1345, E), V(x1303, 1345, yS, E, True),
 H(1279, x1303, 1410, 150),
 dict(a=P(1410, 1279), b=P(1478, 1244), t=T, bearing=False),
 H(1244, 1478, x1553, T, False, [dict(type='door', f=1480, e=1546, hinge='to', into=(1515, 1290))]),
 V(x1553, 1244, yS, T, False, [dict(type='door', f=1265, e=1325, hinge='from', into=(1600, 1290))]),
 H(1244, x1553, xE, T),
 H(1393, x1553, xE, 60, False, [dict(type='door', f=1585, e=1625, hinge='from', into=(1605, 1430))]),
]
rooms = [(410, 930, '主卫', 'marble'), (400, 770, '主卫浴区', 'marble'), (466, 945, '马桶间', 'marble'), (716, 1290, '次卫', None), (1620, 1450, '淋浴区', None), (790, 1050, '备餐间', 'marble'), (615, 860, '茶室', 'oak'), (790, 860, '公卫', None), (1000, 800, '厨房', None),
         (1215, 760, '保姆房', 'oak'), (1215, 600, '保姆卫', None), (1060, 960, '餐厅', 'marble'), (1080, 1300, '客厅', 'marble'),
         (1500, 1190, '门厅', 'marble'), (450, 1420, '主卧', 'walnut'), (615, 1060, '衣帽间', None), (700, 1450, '次卧', 'oak'),
         (640, 1300, '次卫淋浴', None), (1420, 1400, '客卧', 'oak'), (1630, 1300, '客卫', None),
         (735, 1555, '阳台', None), (1080, 1555, '阳台', None), (1430, 1555, '阳台', None), (1630, 1555, '阳台', None)]
rooms = [dict(at=P(x, y), name=n, **({'mat': m} if m else {})) for x, y, n, m in rooms]

def F(key, x, y, rot=0, **k): return dict(key=key, at=P(x, y), rot=rot, **k)
import math
def bend_sofa(ctrl, key='bendSofa', **k):
    """异形组合沙发：ctrl = [(像素 x, 像素 y, 座深 mm), …]（座深中线，从没有靠背的那一头起，靠背在走向左手边）。
    按设计器同样的平滑 + 圆角收口算外包框，at = 外包框中心，path 写成相对中心的 mm。"""
    C = [((X(x, None)), (Y(y, None)), d) for x, y, d in ctrl]
    pts, dep = [], []
    for i in range(len(C) - 1):
        p0, p1, p2, p3 = C[max(0, i - 1)], C[i], C[i + 1], C[min(len(C) - 1, i + 2)]
        n = max(2, math.ceil(math.hypot(p2[0] - p1[0], p2[1] - p1[1]) / 40))
        for j in range(n):
            t = j / n; cr = lambda a, b, c, d: .5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t * t + (-a + 3 * b - 3 * c + d) * t ** 3)
            pts.append((cr(p0[0], p1[0], p2[0], p3[0]), cr(p0[1], p1[1], p2[1], p3[1]))); dep.append(p1[2] + (p2[2] - p1[2]) * t)
    pts.append(C[-1][:2]); dep.append(C[-1][2])
    out = []
    for i, (x, y) in enumerate(pts):
        a, b = pts[max(0, i - 1)], pts[min(len(pts) - 1, i + 1)]; L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
        nx, ny = (b[1] - a[1]) / L, -(b[0] - a[0]) / L
        out += [(x + nx * dep[i] / 2, y + ny * dep[i] / 2), (x - nx * dep[i] / 2, y - ny * dep[i] / 2)]
        if i in (0, len(pts) - 1):  # 两头圆角往外鼓
            sg = -1 if i == 0 else 1; r = min(160, dep[i] * .22); out.append((x - ny * sg * r, y + nx * sg * r))
    xs, ys = [q[0] for q in out], [q[1] for q in out]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    path = '|'.join(f'{round(x - cx)},{round(y - cy)},{d}' for x, y, d in C)
    return dict(key=key, at=[r5(cx), r5(cy)], rot=0, w=round(max(xs) - min(xs)), d=round(max(ys) - min(ys)), opt=dict(path=path, **k.pop('opt', {})), **k)

def drape(p0, p1, at, rot):
    """落地窗帘：p0 ~ p1 是要盖住的范围（窗洞两端各外放 ~150，像素；水平墙填 x、竖直墙填 y），at 是窗帘中线的另一个坐标"""
    A = X if rot in (0, 180) else Y
    a, b = A(p0, None), A(p1, None); c = (a + b) / 2
    return dict(key='curtain', at=[r5(c), r5(Y(at, None))] if rot in (0, 180) else [r5(X(at, None)), r5(c)], rot=rot, w=round(abs(b - a) / 10) * 10)

furniture = [
 # 主卫：独立浴缸、双盆浴室柜、毛巾高柜；玻璃隔断后的马桶间，马桶背后是嵌入式淋浴包管台
 F('freeTub', 379, 768, 0, w=1800, d=800), F('doubleVanity', 336, 945, 270, w=2800, d=560),
 F('cabTall', 488, 857, 90, w=960, d=500), F('toilet', 466, 983, 180), F('showerSet', 466, 1024, 180, w=1050, d=450, h=1000), F('waterHeater', 466, 1024, 180, z=1900),
 F('bathHeater', 400, 930), F('bathHeater', 466, 950),
 # 茶室：椭圆小桌 + 两把圆椅，西墙展示柜
 F('ovalTable', 628, 826, 90, w=1600, d=700), F('chair', 590, 826, 270, w=560, d=600), F('chair', 666, 826, 90, w=560, d=600),
 F('displayCabinet', 529, 822, 270, w=2000, d=320), F('acWall', 526.9, 776, 270), drape(541, 682, 740.5, 0), F('wallArt', 710.9, 822, 90, w=1200, d=40),
 # 主卧套房：U 形衣帽柜、圆角长台、两门高柜、西墙长衣柜
 F('cabWardrobe', 540, 1044, 270, w=1600, d=560), F('cabWardrobe', 617, 1009, 0, w=1500, d=560), F('cabWardrobe', 690, 1044, 90, w=1600, d=560),
 F('island', 495, 1116, 0, w=1930, d=480), F('island', 691.5, 1114, 0, w=640, d=470), F('cabTall', 492, 1070, 90, w=740, d=400), F('cabWardrobe', 336, 1172, 270, w=3650, d=560),
 # 主卧：床前长衣柜、梳妆台 + 圆凳、2.0 米床、两侧床头柜（带台灯）、床尾窄地毯、贵妃椅 + 圆边几、落地灯
 F('cabWardrobe', 513, 1235, 0, w=2350, d=650), F('dresser', 517, 1286, 0, w=1400, d=480), F('stool', 518, 1315, 0, w=520, d=520),
 F('bed20', 505, 1447, 90, w=2050, d=2100), F('nightstand', 561, 1359, 90, w=420, d=420), F('nightstand', 561, 1533, 90, w=420, d=420),
 F('rug', 476, 1446, 90, w=2950, d=970), F('chaise', 354, 1500, 90, w=1500, d=800), F('sideTable', 401, 1525, 0, w=500, d=500),
 F('floorLamp', 338, 1563, 0, w=320, d=320), drape(316, 502, 1579.5, 180), drape(1355, 1584.5, 321, 270), F('acWall', 582.6, 1447, 90), F('wallPanel', 586.3, 1446.5, 90, w=3160, d=150, opt={'style': 'slat'}),
 # 公卫：淋浴区（一字玻璃）、东墙嵌入式淋浴包管台、马桶、圆台盆
 F('shower', 772, 767, 0, w=1300, d=950, opt={'shape': 'line'}), F('showerSet', 841, 771, 90, w=1000, d=320),
 F('toilet', 829, 834, 90), F('pedestalSink', 836, 872, 90, w=450, d=430), F('bathHeater', 790, 830),
 # 厨房：U 形橱柜（西段双盆水槽、东段灶台），两端高柜（西：电器高柜，东：冰箱），南侧玻璃推拉门
 dict(key='uCounter', at=P(1002.8, 797.6), rot=0, w=3980, d=1850,
      kit={'shape': 'U', 'depth': 600, 'wallLegs': [1, 2], 'sink': {'leg': 1, 'at': 1245, 'w': 800, 'bowls': 2}, 'hob': {'leg': 2, 'at': 1250, 'w': 750, 'burners': 2}}),
 F('tallOven', 888.8, 880, 270, w=600, d=600), F('gasHeater', 1123.5, 741.2, 0, z=1500), F('fridge', 1116.8, 880, 90, w=600, d=600),
 # 保姆房 / 保姆卫
 F('cabWardrobe', 1185, 665, 0, w=980, d=420), F('bed12', 1188, 746, 0, w=900, d=1960), F('washer', 1170, 861, 180, w=540, d=480),
 F('cabTall', 1207, 846, 270, w=890, d=340),
 F('wallToilet', 1204, 579, 270, w=450, d=640), F('showerSet', 1158, 588, 270, w=1040, d=340), F('pedestalSink', 1274, 570, 90, w=420, d=380),
 F('waterHeater', 1268, 612, 90),
 # 备餐间（推拉门）：西墙薄高柜、东侧冰箱 + 矮柜、南侧单盆水槽台；外侧长凳
 F('cabTall', 738, 1030, 270, w=1300, d=340), F('fridge', 837.9, 1013, 90, w=650, d=640), F('cabTall', 837.9, 1057, 90, w=640, d=640, h=900),
 F('counter', 793.3, 1094.4, 180, w=1960, d=490, kit={'hob': False, 'sink': {'leg': 0, 'at': 1130, 'w': 460}}),
 F('diningBench', 881, 1055, 90, w=1300, d=360),
 # 餐厅：椭圆长餐桌 6 人位、北侧带折叠门的矮柜
 F('ovalTable', 1068, 1062, 0, w=3100, d=1200),
 *[F('chair', x, 1002, 0, w=580) for x in (1018, 1069, 1121)], *[F('chair', x, 1122, 180, w=580) for x in (1018, 1069, 1121)],
 F('sideboard', 1180, 897, 0, w=890, d=390, h=900),
 # 门厅：入户台盆 + 两侧柜，东侧鞋柜；客厅北侧长凳
 F('cabShoe', 1263, 987, 90, w=600, d=590), F('vanity', 1263, 1061, 90, w=1600, d=590), F('cabShoe', 1263, 1131, 90, w=480, d=590),
 F('shoeCabinet', 1682.9, 1194, 90, w=1370, d=400), F('diningBench', 1081, 1183, 0, w=1000, d=480),
 # 客厅：异形组合沙发（西侧贵妃位 → 折角 → 斜向长座）、椭圆茶几、单椅（面向茶几）、西墙低柜、圆角大地毯
 F('wallPanel', 870.6, 1357.5, 270, w=4140, d=60, opt={'style': 'slat'}), F('cabBase', 884, 1353, 270, w=3000, d=330, h=450), F('rug', 1078, 1357, 0, w=4750, d=4050),
 bend_sofa([(973.3, 1445, 880), (968.3, 1403.3, 1250), (968.3, 1363.3, 1250), (987.3, 1328.3, 1000), (1033.3, 1288.3, 880), (1081.7, 1250, 880)], opt={'open': 420}),
 F('ovalCoffee', 1089, 1377, 310, w=1500, d=900), F('armchair', 1157, 1455, 167, w=700, d=700),
 F('acFloor', 1282, 1480, 90), drape(885, 1262, 1490.2, 180),
 # 次卧套房：1.5 米床；次卫 = 马桶间（推拉门）+ 台盆 + 玻璃门后的淋浴区（包管台 + 拖把池）
 F('bed15', 677, 1444, 270, w=1550, d=2080), F('acWall', 614.4, 1444, 270), drape(606, 822, 1490.2, 180),
 F('showerSet', 640, 1238, 0, w=1020, d=360), F('laundrySink', 637, 1356, 180, w=750, d=420),
 F('toilet', 714, 1244, 0), F('waterHeater', 714, 1238.2, 0, w=700), F('vanity', 713.2, 1341, 180, w=1060, d=600), F('bathHeater', 710, 1290),
 # 东南客卧 + 客卫（门开在卧室里）：衣柜、1.5 米床、圆床头柜、穿衣镜；台盆、马桶、玻璃门后的淋浴区
 F('cabWardrobe', 1395, 1302, 0, w=2370, d=650), F('bed15', 1395, 1407, 270, w=1560, d=2080), F('nightstand', 1341, 1478, 270, w=480, d=480),
 F('mirror', 1548, 1407, 90, w=1250, d=50), F('wallPanel', 1318.2, 1391, 270, w=1900, d=150, opt={'style': 'soft'}), F('acWall', 1321.9, 1407, 270), drape(1335, 1540, 1490.2, 180),
 F('vanity', 1676.2, 1290, 90, w=1000, d=600), F('toilet', 1675, 1361, 90), F('showerSet', 1683.9, 1428, 90, w=1050, d=370),
 F('bathHeater', 1630, 1330), F('waterHeater', 1681.2, 1361, 90),
]
structs = [dict(kind='drain', at=P(x, y)) for x, y in [
    (495, 745), (323, 885),            # 主卫：浴缸旁、台盆区
    (816, 746), (848, 811),            # 公卫：淋浴区、马桶旁
    (1188, 612), (1173, 875),          # 保姆卫、保姆房洗衣机
    (614, 1328), (685, 1352),          # 次卫：淋浴区、马桶间
    (1663, 1452), (1688, 1383),        # 客卫：淋浴区、马桶旁
    (840, 1585), (1290, 1585), (1545, 1585), (1690, 1585)]]   # 四段阳台
import math
for f in furniture:
    if f['key'] in ('toilet', 'wallToilet'):  # 下水口：马桶中心往背面 45（坑距 305）
        a = math.radians(f['rot']); structs.append(dict(kind='sewer', at=[r5(f['at'][0] + 45 * math.sin(a)), r5(f['at'][1] - 45 * math.cos(a))]))
ox, oy = X(0, None), Y(0, None)
elec = [dict(kind='socketFloor', at=P(342, 1572), rot=0)]  # 主卧角窗下的落地灯：两面都是落地窗，用地插
spec = dict(name='大平层 · 四室三厅五卫（带保姆房）', height=2900, walls=walls, rooms=rooms, furniture=furniture, structs=structs, elec=elec,
            autoElec=True, underlay=dict(image='../大平层四室.jpg', mmPerPx=round(X.scale, 4), x=round(ox), y=round(oy)))
json.dump(spec, open(sys.argv[1] if len(sys.argv) > 1 else 'spec.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('ok', len(walls), 'walls', len(furniture), 'furniture')
