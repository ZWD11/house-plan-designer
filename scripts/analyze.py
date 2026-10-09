"""
户型图墙体识别：从彩色户型图（酷家乐/贝壳/房天下这类，墙体为灰色/黑色实心粗线）中
提取水平/竖直墙段与墙上的断口（门窗候选），换算成 mm，输出 HouseSpec 初稿。

用法:
  python analyze.py 户型图.jpg --total-width 12340 [--total-height 11940] [--out 输出目录]
  python analyze.py 户型图.jpg --scale 17.68            # 已知 mm/像素
  python analyze.py 户型图.jpg --dim 262 948 12340      # 像素 x0..x1 对应的 mm 长度（水平方向）

输出（默认在图片旁边的 <图片名>_analysis/ 目录）:
  draft.json     HouseSpec 初稿（墙 + 门窗候选，房间名需要自己补）
  analysis.json  像素级识别结果、比例、外轮廓
  analysis.png   原图叠加识别结果（墙段编号 W*、断口编号 G*、像素标尺），用来核对
  mask.png       墙体掩膜

承重墙判断：先按墙体填充颜色聚类（深色一类 = 承重墙，多数户型图的画法）；
颜色分不开（所有墙同一个颜色）时按厚度猜（≥180mm 算承重），这类会标成“待确认”，
在 analysis.png 上墙号后面带 ?，一定要对照原图图例确认。
尺寸校准：自动找出图上的尺寸线和尺寸界线（短斜杠 / 竖杠），把每条尺寸线上的刻度位置
写进 analysis.json 的 dims_px，并在 analysis.png 上标成 T/B/L/R 编号——配合 axismap.py
按标注尺寸逐段定位墙，比整体按比例换算精确得多。
依赖: pip install numpy pillow opencv-python
"""
import argparse, json, os, sys
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')
import cv2
from PIL import Image, ImageDraw, ImageFont

ap = argparse.ArgumentParser()
ap.add_argument('image')
ap.add_argument('--total-width', type=float, help='外墙外皮总宽 mm（一般是最外圈的总尺寸）')
ap.add_argument('--total-height', type=float, help='外墙外皮总深 mm')
ap.add_argument('--scale', type=float, help='mm/像素')
ap.add_argument('--dim', type=float, nargs=3, metavar=('X0', 'X1', 'MM'), help='水平方向像素 x0..x1 对应 MM')
ap.add_argument('--gray-max', type=int, default=175, help='墙体像素最大亮度（墙偏浅时调高）')
ap.add_argument('--sat-max', type=int, default=22, help='墙体像素最大色差（墙是纯灰/黑）')
ap.add_argument('--out')
ap.add_argument('--crop', type=int, nargs=4, metavar=('X0', 'Y0', 'X1', 'Y1'), help='只在这个像素范围内找墙（排除图例、logo）')
ap.add_argument('--outlined', action='store_true', help='隔墙画成两条细线、中间留白（贝壳等）时打开：把细线围成的墙带也识别出来')
ap.add_argument('--bearing-max', type=int, help='承重墙颜色的最大亮度（0-255）。默认自动按颜色聚类')
a = ap.parse_args()

img = Image.open(a.image).convert('RGB')
rgb = np.array(img).astype(np.int16)
H, W = rgb.shape[:2]
mx, mn = rgb.max(2), rgb.min(2)

# 1. 墙体掩膜：低饱和度的灰/黑像素 → 开运算去掉文字、标注线、地砖斑点 → 只留房子范围内的大块
raw = ((mx - mn < a.sat_max) & (mx < a.gray_max)).astype(np.uint8) * 255
op = cv2.morphologyEx(raw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
n, lab, st, _ = cv2.connectedComponentsWithStats(op, 8)
def wall_like(k):
    x, y, w, h, area = st[k]
    if area < 120 or max(w, h) < 25: return False
    # 文字笔画块：方正、面积小
    return not (max(w, h) / max(1, min(w, h)) < 2 and area < 700)
comps = [k for k in range(1, n) if wall_like(k)]
if a.crop:
    cx0, cy0, cx1, cy1 = a.crop
    comps = [k for k in comps if st[k, 0] >= cx0 and st[k, 1] >= cy0 and st[k, 0] + st[k, 2] <= cx1 and st[k, 1] + st[k, 3] <= cy1]
if not comps:
    sys.exit('没有识别到墙体：试试调高 --gray-max 或 --sat-max')
# 从最大块出发，把离已选范围不远的块逐个并进来（窗洞会把墙体断成很多块）
big = max(comps, key=lambda k: st[k, 4])
U = [st[big, 0], st[big, 1], st[big, 0] + st[big, 2], st[big, 1] + st[big, 3]]
gap = .08 * max(W, H)
chosen, rest = {big}, set(comps) - {big}
grew = True
while grew:
    grew = False
    for k in list(rest):
        x, y, w, h = st[k, :4]
        dx = max(U[0] - (x + w), x - U[2], 0); dy = max(U[1] - (y + h), y - U[3], 0)
        if max(dx, dy) <= gap:
            chosen.add(k); rest.discard(k); grew = True
            U = [min(U[0], x), min(U[1], y), max(U[2], x + w), max(U[3], y + h)]
mask = np.zeros_like(op)
for k in chosen: mask[lab == k] = 255
ys, xs = np.nonzero(mask)
X0, Y0, X1, Y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1

# 2. 比例
if a.scale:
    s, how = a.scale, '--scale'
elif a.dim:
    s, how = a.dim[2] / abs(a.dim[1] - a.dim[0]), '--dim'
elif a.total_width:
    s, how = a.total_width / (X1 - X0), '--total-width / 墙体外轮廓宽'
elif a.total_height:
    s, how = a.total_height / (Y1 - Y0), '--total-height / 墙体外轮廓深'
else:
    sys.exit('需要比例：--total-width（最外圈总尺寸 mm）或 --scale 或 --dim')
check = {}
if a.total_width: check['width_scale'] = a.total_width / (X1 - X0)
if a.total_height: check['height_scale'] = a.total_height / (Y1 - Y0)

# 2b. 描边画法的隔墙：两条平行细线中间留白。闭运算把相距不到一个墙厚的平行细线填成实心带，再只留够长的带
outlined = np.zeros(mask.shape, bool)
if a.outlined:
    thin = ((mx - mn < 40) & (mx < 150)).astype(np.uint8)
    tmax, tmin, Lmin = int(round(280 / s)) + 2, max(2, int(round(70 / s))), max(12, int(round(900 / s)))
    roi = np.zeros(mask.shape, np.uint8); roi[Y0:Y1, X0:X1] = 1
    hb = cv2.morphologyEx(thin, cv2.MORPH_CLOSE, np.ones((tmax, 1), np.uint8))
    hb = cv2.morphologyEx(cv2.morphologyEx(hb, cv2.MORPH_OPEN, np.ones((tmin, 1), np.uint8)), cv2.MORPH_OPEN, np.ones((1, Lmin), np.uint8))
    vb = cv2.morphologyEx(thin, cv2.MORPH_CLOSE, np.ones((1, tmax), np.uint8))
    vb = cv2.morphologyEx(cv2.morphologyEx(vb, cv2.MORPH_OPEN, np.ones((1, tmin), np.uint8)), cv2.MORPH_OPEN, np.ones((Lmin, 1), np.uint8))
    outlined = ((hb | vb) > 0) & (roi > 0) & (mask == 0)
    mask = mask.copy(); mask[outlined] = 255

# 3. 拆成水平/竖直墙段：每个像素比较所在水平连续段和竖直连续段的长度
m = mask > 0
def runs(b):
    out = np.zeros(b.shape, np.int32)
    for i in range(b.shape[0]):
        row = b[i]; j = 0; L = len(row)
        while j < L:
            if row[j]:
                k = j
                while k < L and row[k]: k += 1
                out[i, j:k] = k - j; j = k
            else: j += 1
    return out
hr, vr = runs(m), runs(m.T).T
horiz = (m & (hr >= vr)).astype(np.uint8)
vert = (m & (vr > hr)).astype(np.uint8)

segs = []
for orient, b in (('h', horiz), ('v', vert)):
    n2, lab2, st2, _ = cv2.connectedComponentsWithStats(b, 4)
    for k in range(1, n2):
        x, y, w, h, area = st2[k]
        L, T = (w, h) if orient == 'h' else (h, w)
        if L < 6 or area < 30: continue
        sub = lab2[y:y + h, x:x + w] == k
        # 厚度取中位数（端部和其它墙交接处会偏厚）
        T = float(np.median(sub.sum(0 if orient == 'h' else 1)[sub.sum(0 if orient == 'h' else 1) > 0]))
        if L < T * 1.2: continue
        if orient == 'h':
            cols = np.nonzero(sub.any(0))[0]; prof = sub.sum(1)
            line = y + (np.arange(h) * prof).sum() / prof.sum() + .5
            s0, s1 = x + cols.min(), x + cols.max() + 1
        else:
            rows = np.nonzero(sub.any(1))[0]; prof = sub.sum(0)
            line = x + (np.arange(w) * prof).sum() / prof.sum() + .5
            s0, s1 = y + rows.min(), y + rows.max() + 1
        # 墙芯颜色：去掉边缘 1/4 墙厚后取亮度中位数（边缘有抗锯齿、描边）；描边墙记为白色
        core = cv2.erode(sub.astype(np.uint8), np.ones((max(1, int(T / 4)) * 2 + 1,) * 2, np.uint8)) > 0
        if not core.any(): core = sub
        lum = float(np.median(mx[y:y + h, x:x + w][core]))
        ol = float(outlined[y:y + h, x:x + w][sub].mean()) > .5
        segs.append(dict(orient=orient, line=float(line), s0=float(s0), s1=float(s1), t=T, lum=255.0 if ol else lum, outlined=ol))

# 合并同一条线上相互重叠/相接的碎段
segs.sort(key=lambda q: (q['orient'], q['line'], q['s0']))
merged = []
for q in segs:
    p = merged[-1] if merged else None
    if p and p['orient'] == q['orient'] and abs(p['line'] - q['line']) <= max(2, min(p['t'], q['t']) / 2) and q['s0'] <= p['s1'] + 1:
        L0, L1 = p['s1'] - p['s0'], q['s1'] - q['s0']
        p['lum'] = (p['lum'] * L0 + q['lum'] * L1) / max(1, L0 + L1)
        p['s1'] = max(p['s1'], q['s1']); p['t'] = max(p['t'], q['t']); p['outlined'] = p['outlined'] and q['outlined']
    else: merged.append(dict(q))
segs = merged

# 3b. 承重墙判断：按墙芯亮度做一维两类聚类（按长度加权的 Otsu）；两类差得够开 = 深色那类是承重墙
def otsu(vals, wts):
    order = np.argsort(vals); v, w = np.array(vals)[order], np.array(wts)[order]
    best, thr, W = -1, None, w.sum()
    for i in range(1, len(v)):
        w0, w1 = w[:i].sum(), w[i:].sum()
        if w0 < W * .06 or w1 < W * .06: continue
        m0, m1 = (v[:i] * w[:i]).sum() / w0, (v[i:] * w[i:]).sum() / w1
        sc = w0 * w1 * (m1 - m0) ** 2
        if sc > best: best, thr, sep = sc, float((v[i - 1] + v[i]) / 2), float(m1 - m0)
    return (thr, sep) if thr is not None else (None, 0)
lums, lens = [q['lum'] for q in segs], [q['s1'] - q['s0'] for q in segs]
thr, sep = (float(a.bearing_max), 99) if a.bearing_max is not None else otsu(lums, lens) if len(segs) > 2 else (None, 0)
bearing_by = 'color' if thr is not None and sep >= 35 else 'thickness'
for q in segs:
    tmm = q['t'] * s
    if bearing_by == 'color':
        q['dark'] = bool(q['lum'] <= thr)
        q['sure'] = bool(abs(q['lum'] - thr) > 12 and not (q['dark'] and tmm < 90))
        q['why'] = f"颜色{'深' if q['dark'] else '浅'}（亮度 {q['lum']:.0f}，分界 {thr:.0f}）"
    else:
        q['dark'] = bool(tmm >= 180 and not q['outlined'])
        q['sure'] = False
        q['why'] = f"图上墙体颜色一致，按厚度 {tmm:.0f}mm 猜{'承重' if q['dark'] else '非承重'}"


# 4. 断口：同一条线上两段墙之间的空隙 → 门窗候选
light = (mx - mn < 30) & (mx >= 110) & (mx < 235)  # 窗户在墙带里画成细灰线
gaps = []
for o in ('h', 'v'):
    L = sorted([q for q in segs if q['orient'] == o], key=lambda q: (q['line'], q['s0']))
    for i, p in enumerate(L):
        for q in L[i + 1:]:
            if abs(q['line'] - p['line']) > max(2, min(p['t'], q['t']) * .6): continue
            g0, g1 = p['s1'], q['s0']
            if g1 - g0 < 4 or (g1 - g0) * s > 3200: continue
            # 中间不能有别的同线墙
            if any(r is not p and r is not q and r['orient'] == o and abs(r['line'] - p['line']) < 3 and r['s0'] < g1 and r['s1'] > g0 for r in L): continue
            line, t = (p['line'] + q['line']) / 2, max(p['t'], q['t'])
            if o == 'h': band = light[int(line - t / 2):int(line + t / 2) + 1, int(g0):int(g1)]
            else: band = light[int(g0):int(g1), int(line - t / 2):int(line + t / 2) + 1]
            ratio = float(band.mean()) if band.size else 0
            gaps.append(dict(orient=o, line=line, s0=g0, s1=g1, t=t, a=segs.index(p), b=segs.index(q), lines=ratio, guess='window' if ratio > .12 else 'door'))
            break

# 5. 换算成 mm（原点 = 墙体外轮廓左上角），墙端点吸附到相交墙的中线
R = lambda v: int(round(v / 5.0) * 5)
mmx = lambda px: (px - X0) * s
mmy = lambda py: (py - Y0) * s
def endpoint(q, at_start):
    sp = q['s0'] if at_start else q['s1']
    best = None
    for r in segs:
        if r['orient'] == q['orient']: continue
        # 端点落在 r 的墙带附近、且在 r 的范围内
        if abs(sp - r['line']) <= r['t'] / 2 + q['t'] * .6 + 2 and r['s0'] - 3 <= q['line'] <= r['s1'] + 3:
            d = abs(sp - r['line'])
            if best is None or d < best[0]: best = (d, r['line'])
    if best: return best[1]
    return sp  # 自由端：墙画到哪就到哪（设计器在自由端不再外延半个墙厚）

walls = []
for i, q in enumerate(segs):
    e0, e1 = endpoint(q, True), endpoint(q, False)
    t = R(q['t'] * s)
    if q['orient'] == 'h': A, B = [R(mmx(e0)), R(mmy(q['line']))], [R(mmx(e1)), R(mmy(q['line']))]
    else: A, B = [R(mmx(q['line'])), R(mmy(e0))], [R(mmx(q['line'])), R(mmy(e1))]
    if A == B: continue
    walls.append(dict(id=f'W{i}', a=A, b=B, t=t, bearing=bool(q['dark']), openings=[], _sure=q['sure']))
byid = {w['id']: w for w in walls}
for j, g in enumerate(gaps):
    # 断口用一段墙跨过去：把两侧墙合并成一段，门窗挂在上面
    wa, wb = byid.get(f"W{g['a']}"), byid.get(f"W{g['b']}")
    if not wa or not wb: continue
    k = 0 if g['orient'] == 'h' else 1
    f, t2 = (mmx if k == 0 else mmy)(g['s0']), (mmx if k == 0 else mmy)(g['s1'])
    wb.setdefault('_from', []).append(wa['id'])
    wa['b'] = list(wb['b']); wa['openings'] += [dict(type=g['guess'], **{'from': R(f), 'to': R(t2)}, _gap=f'G{j}')] + wb['openings']
    wa['t'] = max(wa['t'], wb['t']); wa['bearing'] = wa['bearing'] or wb['bearing']; wa['_sure'] = wa['_sure'] and wb['_sure']
    byid[wb['id']] = wa
    walls = [w for w in walls if w is not wb]
    for key in list(byid):
        if byid[key] is wb: byid[key] = wa

# 4b. 尺寸线：墙体外轮廓之外、和外轮廓差不多长的细直线；尺寸界线（短竖杠 / 斜杠）穿过它的位置就是刻度
def find_dims():
    ink = ((mx < 170) & (mx - mn < 60)).astype(np.uint8)
    res = {'top': [], 'bottom': [], 'left': [], 'right': []}
    def scan(img, lo, hi, a0, a1, key, flip, span):
        # img：水平方向就是原图，竖直方向传转置；在 [lo,hi) 行里找长细线
        rows = img[lo:hi, a0:a1].astype(np.int64).sum(1) if hi > lo else np.array([], np.int64)
        for i in np.argsort(-rows)[:12]:
            if rows[i] < span * .3: break
            y = lo + int(i)
            if any(abs(y - d['at']) <= 4 for d in res[key]): continue
            win = img[max(0, y - 7):y - 2, a0:a1].astype(bool), img[y + 3:y + 8, a0:a1].astype(bool)
            hit = win[0].any(0) & win[1].any(0)
            xs = np.nonzero(hit)[0]
            ticks, run = [], []
            for x in xs:
                if run and x - run[-1] > 2: ticks.append(a0 + float(np.mean(run))); run = []
                run.append(x)
            if run: ticks.append(a0 + float(np.mean(run)))
            if len(ticks) >= 2: res[key].append(dict(at=y, ticks=[round(t, 1) for t in ticks]))
        res[key].sort(key=lambda d: d['at'], reverse=flip)
    pad = int(.25 * max(X1 - X0, Y1 - Y0))
    scan(ink, max(0, Y0 - pad), Y0 - 2, max(0, X0 - pad), min(W, X1 + pad), 'top', True, X1 - X0)
    scan(ink, Y1 + 2, min(H, Y1 + pad), max(0, X0 - pad), min(W, X1 + pad), 'bottom', False, X1 - X0)
    scan(ink.T, max(0, X0 - pad), X0 - 2, max(0, Y0 - pad), min(H, Y1 + pad), 'left', True, Y1 - Y0)
    scan(ink.T, X1 + 2, min(W, X1 + pad), max(0, Y0 - pad), min(H, Y1 + pad), 'right', False, Y1 - Y0)
    return res
dims_px = find_dims()

out_dir = a.out or os.path.splitext(a.image)[0] + '_analysis'
os.makedirs(out_dir, exist_ok=True)
draft = {
    'name': '我的户型', 'height': 2800, 'phase': 'renovate',
    'walls': [{k: v for k, v in w.items() if not k.startswith('_')} for w in walls],
    'rooms': [],
    'underlay': {'image': os.path.abspath(a.image), 'mmPerPx': round(s, 4), 'x': round(-X0 * s), 'y': round(-Y0 * s)},
}
for w in draft['walls']:
    if not w['openings']: del w['openings']
json.dump(draft, open(os.path.join(out_dir, 'draft.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
json.dump(dict(image=os.path.abspath(a.image), size=[W, H], mmPerPx=s, scale_from=how, scale_check=check,
               outline_px=[X0, Y0, X1, Y1], outline_mm=[round((X1 - X0) * s), round((Y1 - Y0) * s)],
               bearing_by=bearing_by, bearing_threshold=thr, segments_px=segs, gaps_px=gaps, dims_px=dims_px), open(os.path.join(out_dir, 'analysis.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
Image.fromarray(mask).save(os.path.join(out_dir, 'mask.png'))

# 6. 核对图：原图淡化 + 墙段/断口编号 + 像素标尺
vis = Image.blend(img, Image.new('RGB', img.size, 'white'), .45)
d = ImageDraw.Draw(vis)
try: font = ImageFont.truetype('arial.ttf', 11)
except Exception: font = ImageFont.load_default()
for x in range(0, W, 50):
    d.line([(x, 0), (x, 6 if x % 100 else 12)], fill=(0, 120, 255)); x % 100 == 0 and d.text((x + 2, 12), str(x), fill=(0, 120, 255), font=font)
for y in range(0, H, 50):
    d.line([(0, y), (6 if y % 100 else 12, y)], fill=(0, 120, 255)); y % 100 == 0 and d.text((14, y - 6), str(y), fill=(0, 120, 255), font=font)
d.rectangle([X0, Y0, X1, Y1], outline=(0, 160, 0))
for key, lines in dims_px.items():
    for k, dl in enumerate(lines):
        for j, t in enumerate(dl['ticks']):
            P = (t, dl['at']) if key in ('top', 'bottom') else (dl['at'], t)
            d.ellipse([P[0] - 3, P[1] - 3, P[0] + 3, P[1] + 3], outline=(200, 0, 160), width=2)
            lab = f"{key[0].upper()}{k}.{j}"
            d.text((P[0] + 3, P[1] + (4 if key in ('top', 'bottom') else -12)), lab, fill=(200, 0, 160), font=font)
for i, q in enumerate(segs):
    col = (220, 30, 30) if q['dark'] else (240, 130, 0)
    if q['orient'] == 'h': d.line([(q['s0'], q['line']), (q['s1'], q['line'])], fill=col, width=2); c = ((q['s0'] + q['s1']) / 2, q['line'] - 12)
    else: d.line([(q['line'], q['s0']), (q['line'], q['s1'])], fill=col, width=2); c = (q['line'] + 3, (q['s0'] + q['s1']) / 2)
    d.text(c, f"W{i}{'' if q['sure'] else '?'}", fill=col, font=font)
for j, g in enumerate(gaps):
    col = (0, 90, 255) if g['guess'] == 'window' else (160, 0, 200)
    if g['orient'] == 'h': box = [g['s0'], g['line'] - g['t'] / 2 - 2, g['s1'], g['line'] + g['t'] / 2 + 2]
    else: box = [g['line'] - g['t'] / 2 - 2, g['s0'], g['line'] + g['t'] / 2 + 2, g['s1']]
    d.rectangle(box, outline=col, width=2); d.text((box[2] + 2, box[1]), f"G{j}{'win' if g['guess'] == 'window' else 'door'}", fill=col, font=font)
vis.save(os.path.join(out_dir, 'analysis.png'))

unsure = [w['id'] for w in walls if not w.get('_sure', True)]
print(json.dumps(dict(out=out_dir, mmPerPx=round(s, 3), scale_from=how, scale_check={k: round(v, 3) for k, v in check.items()},
                      outline_mm=[round((X1 - X0) * s), round((Y1 - Y0) * s)], walls=len(draft['walls']), gaps=len(gaps),
                      bearing_by=bearing_by, bearing_unsure=unsure, dim_lines={k: len(v) for k, v in dims_px.items()}), ensure_ascii=False))
