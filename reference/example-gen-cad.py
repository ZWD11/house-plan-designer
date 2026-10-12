"""CAD 路线示例：装修公司原始结构图（矢量 PDF）→ HouseSpec。先跑 cadvec.py 得到 cad/draft.json，再用这个脚本补改。
墙体、门窗洞口、管井、柱全部来自 cadvec.py 读 CAD 矢量（cad/draft.json，误差 < 5mm），这里只补：
房间名、门的类型和开向（原图是原始结构图，洞口没画门扇）、家具家电。"""
import json, sys

spec = json.load(open('cad/draft.json', encoding='utf-8'))
spec['name'] = '户型图最终版 · 三室两卫'

def opening(type_, frm):
    for w in spec['walls']:
        for o in w.get('openings', []):
            if o['type'] == type_ and abs(o['from'] - frm) <= 15: return o
    raise KeyError((type_, frm))
def setop(type_, frm, **kw):
    o = opening(type_, frm)
    for k in ('hinge', 'into'): o.pop(k, None)
    o.update(kw)

# 门：原图单线 = 入户门；门洞按房间功能装门
setop('door', 4200, type='door', hinge='from', into=[2200, 4700], entry=True)   # 入户门 1035
setop('hole', 4460, type='door', hinge='to', into=[7400, 4900])                 # 卧室门 870
setop('hole', 1860, type='door', hinge='to', into=[2300, 8600])                 # 次卧门 850
setop('hole', 5590, type='door', hinge='to', into=[5900, 2500])                 # 卫生间门洞 750 → 平开门
setop('door', 8925, type='door', hinge='to', into=[8800, 9300])                 # 主卫新开门洞 750（原图黄框）
setop('hole', 6640, type='sliding')                                             # 主卧套间入口 1195 → 推拉门
setop('window', 5200, sill=1000, head=2300)                                     # 卫生间窗：离地 1000，高 1300

rooms = [(2700, 1500, '厨房'), (4000, 5600, '餐厅'), (4900, 10500, '客厅'), (5600, 2100, '卫生间'), (8300, 3800, '卧室'),
         (8600, 6700, '衣帽间'), (8500, 11500, '主卧'), (9300, 9300, '主卫'), (1500, 11000, '次卧'), (4900, 14600, '阳台')]
spec['rooms'] = [dict(at=[x, y], name=n) for x, y, n in rooms]

F = lambda key, x, y, rot=0, **k: dict(key=key, at=[x, y], rot=rot, **k)
spec['furniture'] = [
 # 开放厨房（北窗下水槽）
 F('counter', 2651, 543, 0, w=2100), F('fridge', 1951, 1250, 270), F('tallOven', 1901, 1950, 270), F('dishwasher', 3500, 543, 0),
 F('gasHeater', 3700, 333, 0),
 # 餐厅 + 玄关
 F('diningTable', 3600, 4600, 0), F('chair', 3200, 4040, 0), F('chair', 4000, 4040, 0), F('chair', 3200, 5160, 180), F('chair', 4000, 5160, 180),
 F('sideboard', 6534, 3850, 90, w=1100), F('shoeCabinet', 1540, 6300, 270), F('entryBench', 1540, 7300, 270, w=700), F('waterDispenser', 6560, 6250, 90),
 F('acFloor', 2500, 3300, 270),
 # 客厅
 F('sofa', 3528, 10800, 270), F('coffeeTable', 4800, 10800, 90), F('rug', 4800, 10800, 90, w=2600, d=2000), F('tvCabinet', 6534, 10800, 90, w=2400),
 F('acFloor', 6500, 13250, 90), F('armchair', 4800, 12600, 180), F('plant', 3400, 13250, 0), F('floorLamp', 3350, 9300, 0),
 # 卫生间（北）
 F('toilet', 5152, 1650, 270), F('vanity', 6134, 1700, 90), F('waterHeater', 5027, 1650, 270), F('bathHeater', 5600, 2100, 0),
 # 卧室（东北）
 F('bed18', 8695, 3450, 90), F('nightstand', 9535, 2290, 90), F('nightstand', 9535, 4610, 90), F('wardrobe', 8600, 5121, 180, w=1400),
 F('acWall', 7104, 3500, 270), F('curtain', 8613, 2111, 0, w=1700),
 # 衣帽间（主卧套间的过厅：北墙一排衣柜，东窗下梳妆台）
 F('cabWardrobe', 8400, 5961, 0, w=2800), F('dresser', 9853, 6900, 90), F('stool', 9450, 6900, 0), F('curtain', 10273, 6745, 90, w=2150),
 # 主卧
 F('bed18', 9303, 11300, 90), F('nightstand', 10143, 10140, 90), F('nightstand', 10143, 12460, 90),
 F('tvCabinet', 7174, 11300, 270, w=1800), F('armchair', 7500, 13000, 0),
 F('acWall', 7104, 12800, 270), F('curtain', 7900, 13540, 180, w=1800),
 # 主卫
 F('vanity', 8586, 8307, 0, w=600), F('toilet', 9221, 8407, 0), F('shower', 9903, 8507, 0), F('waterHeater', 9221, 8282, 0), F('bathHeater', 9300, 9000, 0),
 # 次卧
 F('bed15', 1265, 10800, 270), F('nightstand', 450, 9750, 270), F('nightstand', 450, 11850, 270), F('wardrobe', 900, 8363, 0, w=1300),
 F('acWall', 370, 10800, 270), F('curtain', 1900, 13776, 180, w=2000), F('desk', 2400, 12900, 90, w=1000), F('officeChair', 1950, 12900, 270),
 # 阳台（立管在东南角：洗衣机靠过去）
 F('washer', 6450, 14350, 90), F('laundrySink', 6475, 15050, 90), F('clothesRack', 4500, 14650, 0), F('plant', 3300, 15150, 0),
]
spec['structs'] += [dict(kind='sewer', at=[5102, 1650]), dict(kind='sewer', at=[9221, 8357]), dict(kind='drain', at=[9903, 8507]),
                    dict(kind='drain', at=[8800, 9450]), dict(kind='drain', at=[5800, 15250])]
spec['autoElec'] = True
json.dump(spec, open(sys.argv[1] if len(sys.argv) > 1 else 'spec.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(len(spec['walls']), 'walls')
