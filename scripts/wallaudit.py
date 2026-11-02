"""
全楼墙体对账：沿 spec 里每段墙每 150mm 横切原图一刀，数墙厚范围内有几条线，和建模（实墙 / 门窗 / 洞口）比对，
只报不一致的地方，并给每处裁一张放大图（原图 + 建模的墙带叠在一起）人工一眼确认。

判定（图上 → 应该建成）：
  2 条线             实墙（或门：门洞两侧的门框线也是 2 条）
  3~4 条及以上细线    窗 / 玻璃 / 推拉门 / 栏板洞口
  没有线              门洞、开敞（挑空、坡道口），或者多建了墙
  灰色 / 黑色填充      柱 / 承重实心墙
假报处理：墙边紧贴的衣柜、床头板、浴室柜的线会被数成“玻璃”——先用 spec 里家具的外框把这些区域遮掉再数（--no-mask 关闭）。

用法:
  python wallaudit.py spec.json --out <工作目录>/audit                      # 用每层 underlay 底图（spec 里写的 image / mmPerPx / x / y）
  python wallaudit.py spec.json --pdf 图纸.pdf --scale 29.03 --origin-pt 172.3 103.2 --out ...   # 矢量 PDF：每页一层，高分辨率渲染再数
  可选：--floor 2（只查一层）  --step 150  --min-len 300（不一致段短于这个不报）
输出: audit.json（每处：楼层、墙号、墙的位置、区间、图上 / 建模）、audit.txt、sheet_<楼层>.png（每处一张放大图拼成一页）
自测：把二层中庭的玻璃墙写成实墙 → 必须报“图上=glass 建模=wall”。
"""
import argparse, json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from imgio import open_upright
sys.stdout.reconfigure(encoding='utf-8')

ap = argparse.ArgumentParser()
ap.add_argument('spec'); ap.add_argument('--out', required=True)
ap.add_argument('--pdf'); ap.add_argument('--scale', type=float, help='PDF：mm / pt'); ap.add_argument('--origin-pt', type=float, nargs=2, default=(0, 0))
ap.add_argument('--pages', help='PDF：每层对应的页号，逗号分隔，默认 0,1,2…'); ap.add_argument('--dpi', type=int, default=216)
ap.add_argument('--floor', type=int); ap.add_argument('--step', type=float, default=150); ap.add_argument('--min-len', type=float, default=300)
ap.add_argument('--dark', type=int, default=110, help='线条像素最大亮度'); ap.add_argument('--no-mask', action='store_true')
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
spec = json.load(open(a.spec, encoding='utf-8'))
floors = spec['floors'] if 'floors' in spec else [spec]
base = os.path.dirname(os.path.abspath(a.spec))
here = os.path.dirname(os.path.abspath(__file__))
try: SIZES = json.load(open(os.path.join(here, '..', 'reference', 'catalog-sizes.json'), encoding='utf-8'))
except Exception: SIZES = {}
try: FONT = ImageFont.truetype('msyh.ttc', 16)
except Exception:
    try: FONT = ImageFont.truetype('NotoSansCJK-Regular.ttc', 16)
    except Exception: FONT = ImageFont.load_default()
# 不压在墙上的东西（吸顶、地面、软装）不用遮
NOMASK = {'rug', 'roundRug', 'ceilingLight', 'downlight', 'chandelier', 'pendant', 'curtain', 'sheer', 'lawn', 'paving', 'stepStone'}

def page_image(fi):
    """返回 (灰度数组, mm→像素函数)"""
    if a.pdf:
        import fitz
        if not a.scale: sys.exit('--pdf 需要 --scale（mm/pt）和 --origin-pt')
        pages = [int(p) for p in a.pages.split(',')] if a.pages else list(range(len(floors)))
        doc = fitz.open(a.pdf); z = a.dpi / 72
        pix = doc[pages[fi]].get_pixmap(matrix=fitz.Matrix(z, z))
        g = np.array(Image.frombytes('RGB', (pix.width, pix.height), pix.samples).convert('L')).astype(int)
        ox, oy = a.origin_pt
        return g, (lambda x, y: ((x / a.scale + ox) * z, (y / a.scale + oy) * z)), a.scale / z
    ul = floors[fi].get('underlay') or spec.get('underlay')
    if not ul: sys.exit(f'第 {fi} 层没有 underlay，没法换算到原图：写上 underlay 或用 --pdf')
    p = ul['image'] if os.path.isabs(ul['image']) else os.path.join(base, ul['image'])
    g = np.array(open_upright(p, 'L')).astype(int)
    if np.median(g) < 90: g = 255 - g   # 黑底图反相
    k = 1 / ul['mmPerPx']
    return g, (lambda x, y: ((x - ul['x']) * k, (y - ul['y']) * k)), ul['mmPerPx']

def furn_rects(fl):
    out = []
    for f in fl.get('furniture', []):
        if f['key'] in NOMASK or f.get('key', '').startswith('free') and f.get('z', 0) > 1500: continue
        dw, dd = (SIZES.get(f['key']) or [600, 600])[:2]
        w, d = f.get('w', dw), f.get('d', dd)
        r = math.radians(f.get('rot', 0)); c, s = abs(math.cos(r)), abs(math.sin(r))
        hw, hd = (w * c + d * s) / 2, (w * s + d * c) / 2
        out.append((f['at'][0] - hw - 15, f['at'][1] - hd - 15, f['at'][0] + hw + 15, f['at'][1] + hd + 15))
    return out

GLASS = ('window', 'floorWindow', 'glassWall', 'slideWindow', 'highWindow', 'sliding', 'bay', 'folding')
def kind_at(w, pos):
    for o in w.get('openings', []):
        lo, hi = sorted((o['from'], o['to']))
        if lo <= pos <= hi:
            t = o['type']
            if t == 'hole' and (o.get('sill') or 0) >= 300: return 'rail'   # 栏板 / 矮墙洞口
            return t
    return 'wall'

def ok(draw, k):
    if draw == 'fill': return k == 'wall'
    if draw == 'wall': return k in ('wall', 'door', 'double', 'unequal', 'pocket', 'garage', 'rail', 'sliding', 'hole')
    if draw == 'glass': return k in GLASS or k == 'rail'
    if draw == 'none': return k != 'wall'
    return True

report, txt = [], []
for fi, fl in enumerate(floors):
    if a.floor is not None and fi != a.floor: continue
    g, P, mmpp = page_image(fi)
    H, W = g.shape
    masks = [] if a.no_mask else furn_rects(fl)
    fname = fl.get('name') or f'{fi}层'
    issues = []
    for wi, w in enumerate(fl.get('walls', [])):
        (ax, ay), (bx, by), t = w['a'], w['b'], w.get('t', 120)
        L = math.hypot(bx - ax, by - ay)
        if L < 400: continue
        ux, uy = (bx - ax) / L, (by - ay) / L; nx, ny = -uy, ux
        hor = abs(by - ay) < abs(bx - ax)
        rows = []
        for sdist in np.arange(180, L - 180, a.step):
            px_, py_ = ax + ux * sdist, ay + uy * sdist
            pos = px_ if hor else py_
            ks = np.arange(-t / 2 - 40, t / 2 + 40, max(mmpp / 2, 3))
            vals, masked = [], 0
            for k in ks:
                x, y = px_ + nx * k, py_ + ny * k
                if any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in masks) and abs(k) > t / 2 - 5:
                    masked += 1; vals.append(255); continue
                X, Y = P(x, y); X, Y = int(round(X)), int(round(Y))
                vals.append(g[Y, X] if 0 <= Y < H and 0 <= X < W else 255)
            v = np.array(vals); dark = v < a.dark; gray = (v >= a.dark) & (v < 200)
            runs = int(np.sum(dark[1:] & ~dark[:-1]) + dark[0])
            draw = 'fill' if (gray.mean() > .45 or dark.mean() > .55) else ('none' if runs == 0 else ('wall' if runs <= 2 else 'glass'))
            rows.append((pos, draw, kind_at(w, pos)))
        segs = []
        for pos, d, k in rows:
            bad = not ok(d, k)
            if segs and segs[-1][2] == d and segs[-1][3] == k and segs[-1][4] == bad: segs[-1][1] = pos
            else: segs.append([pos, pos, d, k, bad])
        for s0, s1, d, k, bad in segs:
            if bad and s1 - s0 + a.step >= a.min_len:
                issues.append({'floor': fname, 'wall': wi, 'a': w['a'], 'b': w['b'], 't': t, 'axis': 'x' if hor else 'y',
                               'from': round(s0 - a.step / 2), 'to': round(s1 + a.step / 2), 'drawing': d, 'model': k})
    # 放大图：每处一张，原图 + 建模的墙带（绿）/ 洞口（黄）+ 问题区间（红框）
    tiles = []
    for i, it in enumerate(issues):
        (ax, ay), (bx, by) = it['a'], it['b']
        if it['axis'] == 'x': cx, cy = (it['from'] + it['to']) / 2, ay
        else: cx, cy = ax, (it['from'] + it['to']) / 2
        span = max(it['to'] - it['from'], 1200) + 1200
        X0, Y0 = P(cx - span / 2, cy - span / 2); X1, Y1 = P(cx + span / 2, cy + span / 2)
        crop = Image.fromarray(np.clip(g, 0, 255).astype(np.uint8)).crop((int(X0), int(Y0), int(X1), int(Y1))).convert('RGB').resize((360, 360))
        d = ImageDraw.Draw(crop, 'RGBA'); sc = 360 / max(1, X1 - X0)
        Q = lambda x, y: ((P(x, y)[0] - X0) * sc, (P(x, y)[1] - Y0) * sc)
        ht = it['t'] / 2
        if it['axis'] == 'x':
            d.rectangle([*Q(min(ax, bx), ay - ht), *Q(max(ax, bx), ay + ht)], fill=(0, 180, 0, 50))
            d.rectangle([*Q(it['from'], ay - ht - 60), *Q(it['to'], ay + ht + 60)], outline=(230, 0, 0, 255), width=2)
        else:
            d.rectangle([*Q(ax - ht, min(ay, by)), *Q(ax + ht, max(ay, by))], fill=(0, 180, 0, 50))
            d.rectangle([*Q(ax - ht - 60, it['from']), *Q(ax + ht + 60, it['to'])], outline=(230, 0, 0, 255), width=2)
        d.rectangle([0, 0, 360, 22], fill=(0, 0, 0, 170))
        d.text((4, 2), f'#{i} 墙{it["wall"]} 图上={it["drawing"]} 建模={it["model"]}', fill=(255, 230, 0), font=FONT)
        tiles.append(crop)
    if tiles:
        cols = 4; sheet = Image.new('RGB', (cols * 364, ((len(tiles) + cols - 1) // cols) * 364), (255, 255, 255))
        for i, tl in enumerate(tiles): sheet.paste(tl, ((i % cols) * 364, (i // cols) * 364))
        sheet.save(os.path.join(a.out, f'sheet_{fi}.png'))
    txt.append(f'===== {fname}：{len(issues)} 处不一致')
    for i, it in enumerate(issues):
        txt.append(f"  #{i} 墙{it['wall']} {'H y' if it['axis'] == 'x' else 'V x'}={it['a'][1] if it['axis'] == 'x' else it['a'][0]} t={it['t']}  "
                   f"{it['axis']} {it['from']}~{it['to']}：图上={it['drawing']}  建模={it['model']}")
    report += issues

json.dump(report, open(os.path.join(a.out, 'audit.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
open(os.path.join(a.out, 'audit.txt'), 'w', encoding='utf-8').write('\n'.join(txt))
print('\n'.join(txt))
print(f'\n共 {len(report)} 处。图上=glass 建模=wall：可能是玻璃 / 窗被建成了实墙；图上=none 建模=wall：门洞 / 开敞被补了墙；'
      f'图上=wall 建模=window：窗位置不对。逐张看 sheet_*.png，能解释的（家具贴墙、开洞斜线）在交付说明里写明')
