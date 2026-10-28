"""DXF 家具布置图清点：块（家具 / 洁具 / 设备）、文字、门弧线、毫米底图。

装修公司 / 设计院的“家具布置图”DXF 常见情况：一张图里有好几张平面（原始结构 + 布置）、块套块、天正图层、
中文图层名和文字是 GBK 被当 latin1 读成乱码。这个脚本只读不改，给写生成脚本提供证据：

  python dxfinventory.py 图.dxf --box X0 Y0 X1 Y1 --out <工作目录>/inv     # box = CAD 坐标（y 朝上），框住要还原的那一张

输出：
  blocks.json   每个家具块：名字、图层、外框（输出坐标 mm，y 朝下，原点 = box 左上角）、旋转、猜的家具库 key、尺寸
  blocks-*.png  每个块的缩略图 + 编号（逐个核对是什么家具、朝哪边）
  texts.json    全部文字（已修 GBK 乱码）及位置：房间名、设备标注（A/S、A/R、无线AP……）
  doors.json    门弧线（圆心、半径、起止角）：门轴位置 + 开向
  underlay.png  10mm / 像素的线稿底图（不含天花、灯具、地材、标注图层），spec 的 underlay 直接用：{"image": ..., "mmPerPx": 10, "x": 0, "y": 0}
  summary.json  各类计数、按图层统计、猜测的家具 key 汇总
"""
import argparse, collections, json, math, re
from pathlib import Path
import ezdxf
from ezdxf import bbox, disassemble
from ezdxf.path import make_path
from PIL import Image, ImageDraw

def repair(v):
    try:
        r = v.encode('latin1').decode('gbk')
        return r if any('一' <= c <= '鿿' for c in r) else v
    except (UnicodeError, AttributeError):
        return v

def flatten(ents, parent='0', depth=0):
    for e in ents:
        layer = repair(e.dxf.layer)
        if layer == '0': layer = parent
        if e.dxftype() == 'INSERT' and depth < 12:
            yield from flatten(e.virtual_entities(), layer, depth + 1)
            for a in e.attribs: yield a, layer
        else:
            yield e, layer

# 块名 / 图层关键字 → 家具库 key（只是猜测，生成脚本里逐个核对）
GUESS = [
    (r'双人床|大床|bed.?1[58]|double.?bed', 'bed18'), (r'单人床|single.?bed|儿童床', 'bed12'), (r'上下床|高低床|bunk', 'bunkBed'), (r'床头柜|nightstand', 'nightstand'),
    (r'转角沙发|l.?sofa|l形沙发', 'lSofa'), (r'三人沙发|多人沙发|sofa', 'sofa'), (r'单人沙发|休闲椅|armchair|lounge', 'armchair'),
    (r'茶几|coffee', 'coffeeTable'), (r'电视柜|tv.?cab', 'tvCabinet'), (r'圆桌|round.?table', 'roundTable'), (r'会议桌|conference', 'conferenceTable'),
    (r'餐桌|dining', 'diningTable'), (r'培训桌|课桌|training', 'trainingTable'), (r'书桌|办公桌|desk|工位', 'desk'), (r'班台|大班', 'bossDesk'),
    (r'办公椅|转椅|office.?chair|chair.?office', 'officeChair'), (r'餐椅|椅|chair', 'chair'),
    (r'衣柜|wardrobe', 'wardrobe'), (r'书柜|书架|bookcase|shelf', 'bookshelf'), (r'鞋柜', 'shoeCabinet'), (r'柜|cabinet', 'cabBase'),
    (r'坐便|马桶|座便|toilet|wc', 'toilet'), (r'蹲便|蹲坑', 'squatToilet'), (r'小便|urinal', 'urinal'), (r'拖布|污水池|mop', 'serviceSink'),
    (r'台盆|洗手盆|洗脸盆|面盆|basin|lavatory|sink', 'vanity'), (r'浴缸|bath.?tub', 'bathtub'), (r'淋浴|shower', 'shower'),
    (r'冰箱|fridge|refrig', 'fridge'), (r'洗衣机|washer|washing', 'washer'), (r'灶|炉|cooker|hob', 'counter'),
    (r'钢琴|piano', 'piano'), (r'植物|绿植|盆栽|plant|tree', 'plant'), (r'地毯|rug|carpet', 'rug'), (r'打印|复印|printer', 'printer'),
    (r'地漏|floor.?drain', 'drain'), (r'风口|送风|回风|空调设备|diffuser', 'supplyVent'), (r'讲台|lectern', 'lectern'), (r'台球|billiard', 'billiards'), (r'麻将', 'mahjong'), (r'车位|汽车|car', 'car'), (r'柜机|立式空调', 'acFloor'), (r'挂机|空调', 'acWall'),
]
def guess(name, layer):
    t = (name + ' ' + layer).lower()
    for pat, k in GUESS:
        if re.search(pat, t, re.I): return k
    return ''

SKIP_LAYER = ('天花', '灯', '地材', '标注', '尺寸', '文字', 'AXIS', '轴', 'DIM', 'TEXT', '填充', 'HATCH', 'PUB_')

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dxf'); ap.add_argument('--box', nargs=4, type=float, required=True, metavar=('X0', 'Y0', 'X1', 'Y1'))
    ap.add_argument('--out', required=True); ap.add_argument('--mmpx', type=float, default=10)
    a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    x0, y0, x1, y1 = a.box; ox, oy = x0, y1  # 输出坐标：x - x0，y1 - y（y 朝下，原点在框的左上角）
    T = lambda x, y: (x - ox, oy - y)
    inside = lambda x, y: x0 <= x <= x1 and y0 <= y <= y1
    doc = ezdxf.readfile(a.dxf)
    blocks, thumbs, layer_n = [], [], collections.Counter()
    for e in doc.modelspace().query('INSERT'):
        layer = repair(e.dxf.layer); name = repair(e.dxf.name)
        try:
            b = bbox.extents([e], fast=True)
            if not b.has_data: continue
            p, q = b.extmin, b.extmax
            if not inside((p.x + q.x) / 2, (p.y + q.y) / 2): continue
            w, d = q.x - p.x, q.y - p.y
            if w < 80 or d < 40 or w > 15000 or d > 15000: continue
            if any(k in layer for k in ('墙', 'WALL', '门', 'DOOR', '窗', 'WINDOW', '轴', '尺寸', 'DIM')): continue
            # 天花、灯具、地材、文字图层的块不是家具（地漏、空调设备留着）
            if any(k in layer for k in ('天花', '灯具', '地材', '文字', '填充')) and not any(k in layer for k in ('地漏', '空调')): continue
        except Exception:
            continue
        (bx0, by0), (bx1, by1) = T(p.x, q.y), T(q.x, p.y)
        k = guess(name, layer)
        row = dict(i=len(blocks), name=name, layer=layer, box=[round(bx0, 1), round(by0, 1), round(bx1, 1), round(by1, 1)], at=[round((bx0 + bx1) / 2, 1), round((by0 + by1) / 2, 1)],
                   size=[round(w), round(d)], rot=round(e.dxf.rotation, 2), mirror=bool(e.dxf.xscale * e.dxf.yscale < 0), guess=k)
        blocks.append(row); layer_n[layer] += 1
        im = Image.new('RGB', (240, 220), 'white'); dr = ImageDraw.Draw(im); sc = min(205 / w, 150 / d)
        drawn = 0; door_arc = False
        for v in disassemble.recursive_decompose([e]):
            try:
                if v.dxftype() == 'ARC' and abs(v.dxf.radius - max(w, d)) < max(w, d) * .2: door_arc = True
                pts = [((pp.x - p.x) * sc + 15, (q.y - pp.y) * sc + 15) for pp in make_path(v).flattening(max(1, w / 400))]
                if len(pts) > 1: dr.line(pts, fill='#252525', width=1); drawn += 1
            except Exception:
                pass
        if not drawn: blocks.pop(); layer_n[layer] -= 1; continue  # 文字块、空块
        if door_arc and 500 < max(w, d) < 1900: row['guess'] = k = 'door（门块，写进墙的 openings，不是家具）'
        dr.text((6, 176), f"{row['i']} {round(w)}x{round(d)} r{round(e.dxf.rotation)}{' M' if row['mirror'] else ''}", fill='black')
        dr.text((6, 192), (k or '?')[:12] + ' ' + name[:22], fill='#1d4ed8')
        thumbs.append(im)
    (out / 'blocks.json').write_text(json.dumps(blocks, ensure_ascii=False, indent=1), encoding='utf-8')
    for s in range(0, len(thumbs), 48):
        sheet = Image.new('RGB', (240 * 8, 220 * 6), '#bbbbbb')
        for j, im in enumerate(thumbs[s:s + 48]): sheet.paste(im, ((j % 8) * 240, (j // 8) * 220))
        sheet.save(out / f'blocks-{s // 48}.png')
    texts, doors = [], []
    W, H = int((x1 - x0) / a.mmpx) + 1, int((y1 - y0) / a.mmpx) + 1
    under = Image.new('RGB', (W, H), 'white'); ud = ImageDraw.Draw(under)
    for e, layer in flatten(doc.modelspace()):
        t = e.dxftype()
        if t in ('TEXT', 'MTEXT', 'ATTRIB'):
            try:
                p = e.dxf.insert
                if inside(p.x, p.y):
                    s = repair(e.plain_text() if t == 'MTEXT' else e.dxf.text).strip()
                    if s: texts.append({'text': s, 'at': [round(v, 1) for v in T(p.x, p.y)], 'layer': layer, 'h': round(e.dxf.get('height', 0) or e.dxf.get('char_height', 0) or 0)})
            except Exception:
                pass
            continue
        if t == 'ARC' and 500 < e.dxf.radius < 1900 and inside(e.dxf.center.x, e.dxf.center.y) and ('门' in layer or 'DOOR' in layer.upper() or layer == '0'):
            sweep = (e.dxf.end_angle - e.dxf.start_angle) % 360
            if 60 < sweep < 120:
                c = T(e.dxf.center.x, e.dxf.center.y)
                # 角度换到输出坐标（y 朝下）：θ → −θ
                doors.append({'hinge': [round(c[0], 1), round(c[1], 1)], 'r': round(e.dxf.radius), 'a0': round(-e.dxf.end_angle % 360, 1), 'a1': round(-e.dxf.start_angle % 360, 1), 'layer': layer})
        if t not in ('LINE', 'POLYLINE', 'LWPOLYLINE', 'ARC', 'CIRCLE', 'ELLIPSE', 'SPLINE', 'SOLID'): continue
        if any(k in layer.upper() for k in SKIP_LAYER) or any(k in layer for k in SKIP_LAYER): continue
        try:
            pts = [T(pp.x, pp.y) for pp in make_path(e).flattening(5)]
        except Exception:
            continue
        if len(pts) < 2 or not any(inside(x + ox, oy - y) for x, y in pts): continue
        ud.line([(x / a.mmpx, y / a.mmpx) for x, y in pts], fill='#6b6b6b', width=1)
    under.save(out / 'underlay.png')
    (out / 'texts.json').write_text(json.dumps(texts, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'doors.json').write_text(json.dumps(doors, ensure_ascii=False, indent=1), encoding='utf-8')
    summ = {'blocks': len(blocks), 'guessed': dict(collections.Counter(b['guess'] or '?' for b in blocks)), 'block_layers': dict(layer_n.most_common(20)),
            'texts': len(texts), 'door_arcs': len(doors), 'underlay': {'image': 'underlay.png', 'mmPerPx': a.mmpx, 'x': 0, 'y': 0, 'px': [W, H]},
            'origin_cad': [ox, oy], 'note': '输出坐标 = (x − box.x0, box.y1 − y)，单位按 DXF（一般 mm）；spec 里坐标照用，底图 x/y 写 0'}
    (out / 'summary.json').write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summ, ensure_ascii=True))

if __name__ == '__main__':
    main()
