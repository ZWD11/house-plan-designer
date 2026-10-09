"""户型图4.jpg（五室三卫，标注净面积 162.94㎡）的户型描述生成脚本 —— 按图上标注尺寸精确定位（v2）。
做法：analyze.py 找出四周尺寸线的刻度像素（dims_px），按图上标注的毫米数用 axismap.Axis 建立 像素→毫米 的分段映射，
墙厚取刻度间实测（黑色实心 ≈ 250 = 承重，灰色 ≈ 120~150 = 非承重），墙按“墙面”落在标注尺寸上。"""
import json, sys
sys.path.insert(0, r'<skill 目录>/scripts')  # 改成本 skill 的 scripts 目录
from axismap import Axis, chain

# ---- 水平方向：底部分段尺寸线（外墙外皮起算）+ 顶部分段尺寸线，两条在东墙 V932 处对齐
wb = (17812 - (5575 + 4390 + 3100 + 2237 + 1000)) / 6           # 底部 6 道墙，刻度间都是 11px，均分
bot = chain([205.5, 216.5, 463.5, 474.5, 668.5, 679.5, 816.5, 827.5, 926.5, 937.5, 982.5, 993.5],
            [wb, 5575, wb, 4390, wb, 3100, wb, 2237, wb, 1000, wb])
top0 = chain([436.5, 447.5, 569.5, 576.5, 658.5, 669.5, 751.5, 761.5, 926.5, 937.5],
             [240, 2750, 150, 1860, 250, 1850, 250, 3738, 244])
off = dict(bot)[926.5] - dict(top0)[926.5]
top = [(p, m + off) for p, m in top0 if 440 < p < 920]  # 东墙两侧以底部为准
X = Axis(bot, top)
# ---- 竖直方向：右侧尺寸线（凸出卧室顶面起算）+ 左侧尺寸线，两条在北外墙 H107 处对齐
wr = (15460 - (410 + 6880 + 4720 + 2200)) / 5
right = chain([72.5, 83.5, 101.5, 112.5, 417.5, 428.5, 636.5, 647.5, 745.5, 756.5], [wr, 410, wr, 6880, wr, 4720, wr, 2200, wr])
gl = (14795 - (6175 + 500 + 1850 + 2100 + 3050)) / 50.2           # 左侧几道缝按像素宽分摊
left0 = chain([101.5, 112.5, 386.3, 391.5, 413.5, 417.5, 499.5, 510.5, 603.5, 610.5, 744.5, 756.5],
              [11 * gl, 6175, 5.2 * gl, 500, 4 * gl, 1850, 11 * gl, 2100, 7 * gl, 3050, 12 * gl])
offy = dict(right)[101.5]
left = [(p, m + offy) for p, m in left0 if 115 < p < 740]
Y = Axis(right, left)
if __name__ == '__main__' and '--report' in sys.argv: X.report(); Y.report(); sys.exit()

# 墙的位置可以写中线像素，也可以写成 (墙面1, 墙面2) 两个刻度像素：后者中线和墙厚都直接取标注，最准
F2 = lambda A, v: (A(v[0], None) + A(v[1], None)) / 2 if isinstance(v, tuple) else A(v, None)
TK = lambda A, v, t: round(abs(A(v[1], None) - A(v[0], None)) / 5) * 5 if isinstance(v, tuple) else t
r5 = lambda v: round(v / 5) * 5
P = lambda x, y: [r5(F2(X, x)), r5(F2(Y, y))]
def H(y, x0, x1, t, bearing=False, ops=()):
    return dict(a=P(x0, y), b=P(x1, y), t=TK(Y, y, t), bearing=bearing, openings=[dict(o, **{'from': X(o.pop('f'), 5), 'to': X(o.pop('e'), 5)}) for o in map(dict, ops)])
def V(x, y0, y1, t, bearing=False, ops=()):
    return dict(a=P(x, y0), b=P(x, y1), t=TK(X, x, t), bearing=bearing, openings=[dict(o, **{'from': Y(o.pop('f'), 5), 'to': Y(o.pop('e'), 5)}) for o in map(dict, ops)])
# 标注了两侧墙面的墙
xW, x573, x665, x756, xE = (436.5, 447.5), (569.5, 576.5), (658.5, 669.5), (751.5, 761.5), (926.5, 937.5)
x674, x822, x469, x211, x988 = (668.5, 679.5), (816.5, 827.5), (463.5, 474.5), (205.5, 216.5), (982.5, 993.5)
y78, y107, y423, y642, y751 = (72.5, 83.5), (101.5, 112.5), (417.5, 428.5), (636.5, 647.5), (745.5, 756.5)
y389, y505, y608 = (386.3, 391.5), (499.5, 510.5), (603.5, 610.5)
E, G, T = 250, 150, 120   # 黑色承重墙 / 灰色 7px 隔墙 / 灰色 5~6px 隔墙
walls = [
 # 北面：儿童房、卫生间外墙（西段黑色承重，东段灰色），凸出的小卧室，主卧北墙
 H(y107, xW, 508, E, True),
 H(y107, 508, 669.5, G, False, [dict(type='window', f=603, e=643, sill=1400)]),
 V(x665, y78, y107, E, True),
 H(y78, x665, x756, E, True, [dict(type='window', f=676, e=742)]),
 V(x756, y78, y107, E, True),
 H(y107, 745.5, xE, E, True, [dict(type='window', f=771, e=911)]),
 # 东外墙（主卧 + 客厅），主卧南墙，阳台
 V(xE, y107, y642, E, True, [dict(type='window', f=116, e=262), dict(type='window', f=291, e=402), dict(type='sliding', f=447, e=633)]),
 H(y423, 745.5, x988, E, True),
 V(x988, y423, y642, E, True, [dict(type='floorWindow', f=431, e=633)]),
 H(y642, xW, x988, E, True, [dict(type='door', f=605, e=657, hinge='to', entry=True, into=P(630, 610)), dict(type='sliding', f=681, e=816)]),
 # 西外墙：上段黑色承重（儿童房），下段灰色（客餐厅一侧）
 V(xW, y107, y389, E, True, [dict(type='window', f=137, e=243), dict(type='window', f=260, e=353)]),
 V(xW, y389, y642, E, False, [dict(type='window', f=429, e=487), dict(type='door', f=527, e=562, hinge='from', into=P(420, 545)), dict(type='door', f=583, e=617, hinge='from', into=P(420, 600))]),
 # 厨房
 V(x674, y642, y751, E, True), H(y751, x674, x822, E, True), V(x822, y642, y751, E, False, [dict(type='window', f=653, e=726)]),
 # 客卧与西侧两卫
 V(x469, y642, y751, E, True), H(y751, x211, x469, E, True),
 V(x211, y505, y751, E, True, [dict(type='window', f=513, e=591, sill=1400), dict(type='window', f=628, e=734)]),
 H(y505, x211, xW, E, True, [dict(type='window', f=218, e=305, sill=1400), dict(type='window', f=344, e=434, sill=1400)]),
 V(333.5, y505, y608, G, False, [dict(type='door', f=515, e=551, hinge='from', into=P(300, 530))]),
 H(y608, x211, 390, G), V(390, 576.5, y608, G), H(576.5, 390, xW, G),
 # 北侧内墙：儿童房 / 卫生间 / 小卧室 / 走廊
 V(x573, y107, 253, G), H(253, x573, 659, T),
 V(669.5, y107, 198.5, T),
 H(198.5, 659, 745.5, G),
 V(745.5, y107, y423, T, False, [dict(type='hole', f=119, e=181), dict(type='door', f=213, e=247, hinge='to', into=P(780, 230))]),
 V(659, 198.5, 418, T, False, [dict(type='door', f=212, e=247, hinge='from', into=P(620, 230)), dict(type='door', f=323, e=357, hinge='to', into=P(630, 340))]),
 H(y389, xW, 659, T),
]
for w in walls:
    if not w['openings']: del w['openings']
rooms = [(520, 200, '儿童房'), (622, 167, '卫生间'), (708, 140, '卧室'), (703, 307, '走廊'), (830, 260, '主卧'), (720, 520, '客餐厅'),
         (748, 690, '厨房'), (960, 530, '阳台'), (273, 551, '公卫'), (360, 530, '卫生间'), (335, 680, '客卧')]
F = lambda key, x, y, rot=0, **k: dict(key=key, at=[x, y], rot=rot, **k)
furniture = [
 # 儿童房（西墙两扇窗）
 F('bed12', 6500, 1910, 0), F('nightstand', 7350, 1120, 0), F('wardrobe', 6400, 6790, 180, w=1800),
 F('desk', 7940, 3000, 90), F('officeChair', 7450, 3000, 270), F('bookshelf', 8030, 5200, 90),
 F('acWall', 7300, 1040, 0), F('rug', 6900, 4400, 0, w=1800, d=1400), F('curtain', 5520, 2660, 270, w=2600), F('curtain', 5520, 5290, 270, w=2300),
 # 北卫
 F('toilet', 9000, 1260, 0), F('shower', 9930, 1360, 0), F('vanity', 8610, 3000, 270), F('waterHeater', 9000, 1135, 0), F('bathHeater', 9300, 2400, 0),
 # 小卧室（北侧凸出）
 F('bed12', 11340, 1280, 0), F('curtain', 11340, 360, 0, w=1500),
 # 主卧 + 开放衣帽间
 F('bed18', 14300, 1960, 0), F('nightstand', 13150, 1120, 0), F('nightstand', 15450, 1120, 0), F('bedBench', 14300, 3260, 0),
 F('cabSlide', 12620, 5900, 270, w=3000), F('island', 14400, 5900, 90), F('cabWardrobe', 14400, 7490, 180, w=2600),
 F('armchair', 15650, 3900, 90), F('floorLamp', 15800, 4600, 0),
 F('acWall', 15650, 1040, 0), F('curtain', 14340, 990, 0, w=3400), F('curtain', 16190, 2630, 90, w=3400), F('curtain', 16190, 6190, 90, w=2700),
 # 客厅（南墙沙发、北墙电视）
 F('sofa', 15000, 12260, 180), F('coffeeTable', 15000, 10700, 0), F('rug', 15000, 10900, 0, w=2600, d=2000), F('tvCabinet', 15000, 8240, 0, w=2400),
 F('acFloor', 13300, 8230, 0), F('armchair', 13300, 10700, 270), F('plant', 13300, 12300, 0), F('curtain', 16190, 10550, 90, w=4100),
 # 餐厅 + 玄关
 F('diningTable', 7900, 8900, 0), F('chair', 7500, 8340, 0), F('chair', 8300, 8340, 0), F('chair', 7500, 9460, 180), F('chair', 8300, 9460, 180),
 F('sideboard', 6250, 7410, 0, w=1600), F('waterDispenser', 7400, 7370, 0), F('shoeCabinet', 8200, 12560, 180, w=1400), F('plant', 11200, 12300, 0),
 # 厨房
 F('counter', 12250, 14890, 180, w=2400), F('fridge', 11050, 13500, 270), F('gasHeater', 10790, 14600, 270),
 # 阳台
 F('washer', 17075, 12430, 180), F('dryer', 17075, 8350, 0), F('clothesRack', 17075, 10400, 90),
 # 公卫（西）
 F('bathtub', 1300, 11650, 180), F('toilet', 800, 10210, 0), F('vanity', 1550, 10110, 0),
 # 卫生间（中）
 F('toilet', 3300, 11600, 270), F('vanity', 4000, 10110, 0), F('waterHeater', 3170, 11600, 270), F('bathHeater', 3800, 10900, 0),
 # 客卧
 F('bed18', 2600, 14140, 180), F('nightstand', 1450, 14980, 180), F('nightstand', 3750, 14980, 180), F('wardrobe', 1800, 12450, 0, w=2400),
 F('acWall', 5730, 13900, 90), F('curtain', 335, 13730, 270, w=2600),
]
structs = [dict(kind='sewer', at=[9000, 1210]), dict(kind='drain', at=[9930, 1360]), dict(kind='sewer', at=[800, 10160]), dict(kind='drain', at=[1700, 11700]),
           dict(kind='sewer', at=[3250, 11600]), dict(kind='drain', at=[3600, 11000]), dict(kind='drain', at=[17300, 12000]), dict(kind='drain', at=[11300, 14600])]
spec = dict(name='户型图4 · 五室三卫 162.94㎡', height=2800, phase='renovate', north=30, autoElec=True, walls=walls,
            rooms=[dict(at=P(x, y), name=n) for x, y, n in rooms], structs=structs, furniture=furniture,
            underlay=dict(image='../户型图4.jpg', mmPerPx=round((X.scale + Y.scale) / 2, 4), x=round(X(0, None)), y=round(Y(0, None))))
json.dump(spec, open(sys.argv[1] if len(sys.argv) > 1 else 'spec.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(len(walls))
