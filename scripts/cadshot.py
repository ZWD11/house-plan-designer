"""
黑底 CAD 截图（模型空间截屏、没有矢量）识别：按线色分图层 + 自动找轴网（轴号圆圈 + 轴线）+ 按轴线尺寸定比例 + 尺寸线刻度。

用法:
  python cadshot.py 户型图cad.jpg --out <工作目录>/shot                                  # 先看分层和轴网
  python cadshot.py 户型图cad.jpg --x-dims 3000 7200 3600 --y-dims 1500 4200 2700 2000 1200 1750 400 --out ...
        # 轴号之间的尺寸（从左到右、从上到下；读图上的轴线尺寸那一道），给了就算 mm/px、原点，输出 Axis

输出:
  layers.png   各颜色图层分开画（青 / 紫 / 绿 / 黄 / 红 / 白 / 蓝），一眼看出哪个颜色是墙
  axes.png     原图 + 识别出的轴线（编号 X0.. / Y0..）+ 尺寸线刻度
  shot.json    colors（各颜色像素数和用途猜测）、axes_px（竖轴 x / 横轴 y 像素）、bubbles（轴号圆圈）、
               mmPerPx（两个方向分别算、误差 %）、origin_px、dims_px（尺寸线刻度，和 analyze.py 同格式）、
               axis_chain（给生成脚本：X = Axis(chain(xs, x_dims))）
  下一步：python analyze.py 图 --wall-color cyan --scale <mmPerPx> --out ...   （墙按青色双线识别）
依赖: pip install numpy pillow opencv-python
"""
import argparse, json, os, sys
import numpy as np
import cv2
from PIL import Image, ImageDraw
from imgio import open_upright
sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8')

ap = argparse.ArgumentParser()
ap.add_argument('image')
ap.add_argument('--out')
ap.add_argument('--x-dims', type=float, nargs='+', help='竖向轴线之间的尺寸 mm（从左到右）')
ap.add_argument('--y-dims', type=float, nargs='+', help='横向轴线之间的尺寸 mm（从上到下）')
ap.add_argument('--axis-color', default='green', help='轴号圆圈 / 尺寸线颜色（默认 green）')
a = ap.parse_args()
out = a.out or os.path.splitext(a.image)[0] + '_shot'
os.makedirs(out, exist_ok=True)

img = open_upright(a.image)
rgb = np.array(img)
H, W = rgb.shape[:2]
if np.median(rgb.max(2)) > 90:
    print('提示：这张图不是黑底，白底图用 analyze.py', file=sys.stderr)

# 1. 按色相分图层（CAD 常用索引色：1 红 2 黄 3 绿 4 青 5 蓝 6 紫 7 白）
hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
h, s, v = hsv[..., 0].astype(int), hsv[..., 1].astype(int), hsv[..., 2].astype(int)
lit = v > 60
col = s > 40   # JPEG 截图细线边缘发灰，饱和度只有 50~80
COLORS = {
    'red': lit & col & ((h < 8) | (h >= 170)),
    'yellow': lit & col & (h >= 20) & (h < 35),
    'green': lit & col & (h >= 35) & (h < 70),
    'cyan': lit & col & (h >= 70) & (h < 100),   # 建筑 CAD 插件的墙线常是偏绿的青（色相 75 左右）
    'blue': lit & col & (h >= 100) & (h < 135),
    'magenta': lit & col & (h >= 135) & (h < 170),
    'white': lit & (s <= 40),
}
GUESS = {'cyan': '墙 / 门窗（建筑 CAD 插件默认）', 'magenta': '洁具 / 家具 / 门窗编号', 'green': '尺寸线 / 轴号', 'yellow': '楼梯 / 填充 / 管线',
         'red': '轴线（点划线）/ 标记', 'white': '文字 / 房间名', 'blue': '设备 / 门窗'}
colors = {k: {'px': int(m.sum()), 'guess': GUESS[k]} for k, m in COLORS.items()}

# layers.png：每个颜色一格
tiles, tw = [], 700
for k, m in COLORS.items():
    t = np.zeros((H, W, 3), np.uint8); t[m] = (255, 255, 255)
    im = Image.fromarray(t).resize((tw, round(H * tw / W)))
    d = ImageDraw.Draw(im); d.rectangle([0, 0, tw, 26], fill=(40, 40, 40)); d.text((8, 6), f'{k}  {colors[k]["px"]} px  {GUESS[k]}', fill=(255, 220, 0))
    tiles.append(im)
cols = 4; th = tiles[0].size[1]
sheet = Image.new('RGB', (cols * tw, ((len(tiles) + cols - 1) // cols) * th), (20, 20, 20))
for i, t in enumerate(tiles): sheet.paste(t, ((i % cols) * tw, (i // cols) * th))
sheet.save(os.path.join(out, 'layers.png'))

# 2. 轴号圆圈：轴线颜色里的圆（Hough），只留排成一行 / 一列的那些
am = COLORS.get(a.axis_color, COLORS['green']).astype(np.uint8) * 255
r0 = max(8, round(min(W, H) * .008)); r1 = max(r0 + 4, round(min(W, H) * .03))
cs = cv2.HoughCircles(cv2.GaussianBlur(cv2.dilate(am, np.ones((3, 3), np.uint8)), (5, 5), 1.5), cv2.HOUGH_GRADIENT, dp=1.2, minDist=r0 * 3, param1=80, param2=24, minRadius=r0, maxRadius=r1)
circ = []
if cs is not None:
    for x, y, r in cs[0]:
        # 真圆：圆周上大部分点是线色
        ang = np.linspace(0, 2 * np.pi, 72, endpoint=False)
        hit = np.zeros(72, bool)
        for dr in range(-4, 5):
            xx = np.clip((x + (r + dr) * np.cos(ang)).round().astype(int), 0, W - 1); yy = np.clip((y + (r + dr) * np.sin(ang)).round().astype(int), 0, H - 1)
            hit |= am[yy, xx] > 0
        ring = hit
        if ring.mean() > .7: circ.append((float(x), float(y), float(r)))

def rows_of(pts, key, tol):
    """按 key 坐标聚类，返回成员 ≥ 2 的组"""
    pts = sorted(pts, key=key); groups = []
    for p in pts:
        if groups and abs(key(p) - np.mean([key(q) for q in groups[-1]])) < tol: groups[-1].append(p)
        else: groups.append([p])
    return [g for g in groups if len(g) >= 2]

rmed = float(np.median([c[2] for c in circ])) if circ else r0
circ = [c for c in circ if abs(c[2] - rmed) < rmed * .25]
# 竖向轴线的轴号排成一行（同 y，在图上方或下方）；横向轴线的轴号排成一列（同 x，在左侧或右侧）
hrow = max(rows_of(circ, lambda c: c[1], rmed), key=len, default=[])
vcol = max(rows_of(circ, lambda c: c[0], rmed), key=len, default=[])

def line_through(xy, vertical):
    """轴号圆心沿轴线方向往图里找线：在 ±3px 内统计线色像素，找最亮的那一列 / 行"""
    best, bc = xy, -1
    for d in range(-4, 5):
        c = int(round(xy + d))
        if not (0 <= c < (W if vertical else H)): continue
        cnt = int((COLORS['green'] | COLORS['red'] | COLORS['cyan'] | COLORS['white'])[:, c].sum() if vertical else (COLORS['green'] | COLORS['red'] | COLORS['cyan'] | COLORS['white'])[c, :].sum())
        if cnt > bc: best, bc = c, cnt
    return best

xs = sorted(line_through(c[0], True) for c in hrow)
ys = sorted(line_through(c[1], False) for c in vcol)
res = {'image': os.path.abspath(a.image), 'size': [W, H], 'colors': colors,
       'bubbles': {'x_axes': [[round(c[0], 1), round(c[1], 1), round(c[2], 1)] for c in sorted(hrow)], 'y_axes': [[round(c[0], 1), round(c[1], 1), round(c[2], 1)] for c in sorted(vcol, key=lambda c: c[1])]},
       'axes_px': {'x': xs, 'y': ys}}

# 3. 比例：轴线像素间距 vs 轴线尺寸
def fit(px, dims, name):
    if not dims: return None
    if len(dims) != len(px) - 1:
        print(f'{name}：找到 {len(px)} 条轴线（{px}），应给 {len(px) - 1} 段尺寸，现在给了 {len(dims)} 段——对照 axes.png 补齐或删掉', file=sys.stderr)
        return None
    acc = np.concatenate([[0], np.cumsum(dims)])
    k, b = np.polyfit(np.array(px, float), acc, 1)
    resid = acc - (k * np.array(px) + b)
    segs = [round(d / (px[i + 1] - px[i]), 4) for i, d in enumerate(dims)]
    return {'mmPerPx': round(float(k), 4), 'origin_px': round(float(-b / k), 2), 'seg_mmPerPx': segs, 'max_resid_mm': round(float(np.abs(resid).max()), 1),
            'chain': [[p, float(m)] for p, m in zip(px, acc)]}

fx, fy = fit(xs, a.x_dims, '竖向轴线'), fit(ys, a.y_dims, '横向轴线')
if fx: res['x_fit'] = fx
if fy: res['y_fit'] = fy
if fx and fy:
    res['mmPerPx'] = round((fx['mmPerPx'] + fy['mmPerPx']) / 2, 4)
    res['scale_diff_pct'] = round(abs(fx['mmPerPx'] - fy['mmPerPx']) / res['mmPerPx'] * 100, 2)
    res['origin_px'] = [fx['origin_px'], fy['origin_px']]
    res['axis_chain'] = {'x': fx['chain'], 'y': fy['chain'],
                         'usage': 'from axismap import Axis; X = Axis(shot["axis_chain"]["x"]); Y = Axis(shot["axis_chain"]["y"])  # 原点 = 第一根轴线'}
elif fx or fy:
    f = fx or fy; res['mmPerPx'] = f['mmPerPx']

# 4. 尺寸线刻度：轴线颜色里的长水平 / 竖直线，刻度 = 跨过这条线的短斜杠 / 尺寸界线
g = COLORS['green']
def dim_lines(mask, horizontal, minlen):
    prof = mask.sum(1 if horizontal else 0)
    cand = [i for i in range(len(prof)) if prof[i] > minlen]
    groups = []
    for i in cand:
        if groups and i - groups[-1][-1] <= 2: groups[-1].append(i)
        else: groups.append([i])
    out = []
    for gi in groups:
        c = int(round(np.mean(gi)))
        line = mask[c, :] if horizontal else mask[:, c]
        idx = np.nonzero(line)[0]
        if not len(idx): continue
        lo, hi = int(idx.min()), int(idx.max())
        rr = max(4, round(rmed * .35))
        ticks = []
        for t in range(lo, hi + 1):
            band = mask[max(0, c - rr):c + rr + 1, t] if horizontal else mask[t, max(0, c - rr):c + rr + 1]
            if band.sum() >= rr * 1.4: ticks.append(t)
        tk = []
        for t in ticks:
            if tk and t - tk[-1][-1] <= 3: tk[-1].append(t)
            else: tk.append([t])
        pos = [round(float(np.mean(q)), 1) for q in tk]
        if len(pos) >= 2: out.append({'at': c, 'from': lo, 'to': hi, 'ticks': pos})
    return out
minlen = .12 * max(W, H)
res['dims_px'] = {'horizontal': dim_lines(g, True, minlen), 'vertical': dim_lines(g, False, minlen)}

# axes.png
vis = Image.fromarray((rgb * .55).astype(np.uint8)); d = ImageDraw.Draw(vis)
for i, x in enumerate(xs): d.line([x, 0, x, H], fill=(255, 80, 80), width=2); d.text((x + 4, 6), f'X{i} {x}', fill=(255, 120, 120))
for i, y in enumerate(ys): d.line([0, y, W, y], fill=(255, 80, 80), width=2); d.text((6, y + 4), f'Y{i} {y}', fill=(255, 120, 120))
for c in hrow + vcol: d.ellipse([c[0] - c[2], c[1] - c[2], c[0] + c[2], c[1] + c[2]], outline=(255, 255, 0), width=3)
for dl in res['dims_px']['horizontal']:
    for t in dl['ticks']: d.ellipse([t - 5, dl['at'] - 5, t + 5, dl['at'] + 5], outline=(200, 120, 255), width=2)
for dl in res['dims_px']['vertical']:
    for t in dl['ticks']: d.ellipse([dl['at'] - 5, t - 5, dl['at'] + 5, t + 5], outline=(200, 120, 255), width=2)
vis.save(os.path.join(out, 'axes.png'))
json.dump(res, open(os.path.join(out, 'shot.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
brief = {k: res[k] for k in ('size', 'axes_px', 'mmPerPx', 'scale_diff_pct', 'origin_px') if k in res}
brief['colors'] = {k: v['px'] for k, v in colors.items()}
brief['dim_lines'] = [len(res['dims_px']['horizontal']), len(res['dims_px']['vertical'])]
for k in ('x_fit', 'y_fit'):
    if k in res: brief[k] = {q: res[k][q] for q in ('mmPerPx', 'max_resid_mm', 'seg_mmPerPx')}
brief['out'] = out
print(json.dumps(brief, ensure_ascii=False, indent=1))
