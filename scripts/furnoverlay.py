"""把 spec 里的家具（外框 + 名字 + 朝向箭头）画回原图上，逐件核对“家具一比一还原”。

用法:
    python furnoverlay.py spec.json --out 目录 [--tiles 3x3] [--scale 2]
输出:
    目录/furn_all.png       整张原图 + 家具外框（红框 = 落地家具，蓝虚框 = 挂墙 / 吸顶，绿 = 门窗洞口）
    目录/furn_r<i>c<j>.png   切块放大，逐块对照原图上画的家具轮廓
坐标换算用 spec 的 underlay（mmPerPx、x、y），所以生成脚本里要写对 underlay。
看什么：每件家具的框要正好压在原图那件家具的轮廓上；箭头指向家具正面（rot 0 时朝南 / 朝下）。
框偏了就回生成脚本改 at / w / d / rot；原图上有、框里没有的就是漏放的。
"""
import argparse, json, math, os, sys
from PIL import Image, ImageDraw, ImageFont

ap = argparse.ArgumentParser()
ap.add_argument('spec'); ap.add_argument('--out', default='furncheck')
ap.add_argument('--tiles', default='3x3'); ap.add_argument('--scale', type=float, default=2)
ap.add_argument('--floor', type=int, default=0)
a = ap.parse_args()
spec = json.load(open(a.spec, encoding='utf-8'))
fl = spec['floors'][a.floor] if 'floors' in spec else spec
ul = fl.get('underlay') or spec.get('underlay')
if not ul: sys.exit('spec 里没有 underlay，没法换算到原图像素')
img_path = ul['image'] if os.path.isabs(ul['image']) else os.path.join(os.path.dirname(os.path.abspath(a.spec)), ul['image'])
im = Image.open(img_path).convert('RGB')
S = a.scale
im = im.resize((int(im.width * S), int(im.height * S)), Image.LANCZOS)
d = ImageDraw.Draw(im, 'RGBA')
k = S / ul['mmPerPx']
px = lambda x, y: ((x - ul['x']) * k, (y - ul['y']) * k)
try: font = ImageFont.truetype('msyh.ttc', int(11 * S))
except Exception:
    try: font = ImageFont.truetype('/System/Library/Fonts/PingFang.ttc', int(11 * S))
    except Exception: font = ImageFont.load_default()

# 家具库默认尺寸：从 spec-format.md 的表里读不全，这里只认 spec 写了的 w / d，没写的用一份常用默认
here = os.path.dirname(os.path.abspath(__file__))
defaults = {}
try:
    import re
    t = open(os.path.join(here, '..', 'reference', 'catalog-sizes.json'), encoding='utf-8').read()
    defaults = json.loads(t)
except Exception: pass
OVERHEAD = {'acWall', 'waterHeater', 'gasHeater', 'hood', 'bathHeater', 'clothesRack', 'wallTV', 'mirrorCabinet', 'towelWarmer',
            'wallArt', 'wallArt3', 'wallClock', 'hangingPlant', 'projScreen', 'cabWall', 'chandelier', 'curtain', 'sheer'}
for f in fl.get('furniture', []):
    dw, dd = defaults.get(f['key'], [600, 600])[:2]
    w, dep = f.get('w', dw), f.get('d', dd)
    cx, cy = f['at']; r = math.radians(f.get('rot', 0)); c, s = math.cos(r), math.sin(r)
    pts = [px(cx + u * c - v * s, cy + u * s + v * c) for u, v in ((-w / 2, -dep / 2), (w / 2, -dep / 2), (w / 2, dep / 2), (-w / 2, dep / 2))]
    over = f['key'] in OVERHEAD
    col = (30, 90, 255, 230) if over else (230, 30, 30, 230)
    d.polygon(pts, outline=col, width=max(1, int(S)))
    # 朝向箭头：从中心指向正面（+v）
    p0 = px(cx, cy); p1 = px(cx - s * dep / 2, cy + c * dep / 2)
    d.line([p0, p1], fill=col, width=max(1, int(S)))
    d.text((p0[0] + 3, p0[1] - 6 * S), f['key'], fill=col, font=font)
    path = (f.get('opt') or {}).get('path')
    if path:
        pts = [tuple(map(float, t.split(',')[:2])) for t in path.split('|')]
        d.line([px(cx + u * c - v * s, cy + u * s + v * c) for u, v in pts], fill=col, width=max(1, int(S * 2)))
for wl in fl.get('walls', []):
    # 墙按厚度画成半透明带（绿 = 承重，青 = 非承重），门窗洞口画成黄色，方便和原图的墙线逐段对
    ax, ay = wl['a']; bx, by = wl['b']; L = math.hypot(bx - ax, by - ay) or 1; ux, uy = (bx - ax) / L, (by - ay) / L; nx, ny = -uy, ux
    ht = wl.get('t', 120) / 2; col = (0, 170, 0, 70) if wl.get('bearing') else (0, 150, 200, 70)
    q = [px(ax + nx * ht, ay + ny * ht), px(bx + nx * ht, by + ny * ht), px(bx - nx * ht, by - ny * ht), px(ax - nx * ht, ay - ny * ht)]
    d.polygon(q, fill=col, outline=col[:3] + (200,))
    for o in wl.get('openings', []):
        horiz = abs(by - ay) < abs(bx - ax)
        s0, s1 = sorted((o['from'], o['to']))
        if horiz: p0, p1 = (s0, ay + (s0 - ax) / (bx - ax or 1) * (by - ay)), (s1, ay + (s1 - ax) / (bx - ax or 1) * (by - ay))
        else: p0, p1 = (ax + (s0 - ay) / (by - ay or 1) * (bx - ax), s0), (ax + (s1 - ay) / (by - ay or 1) * (bx - ax), s1)
        qq = [px(p0[0] + nx * ht, p0[1] + ny * ht), px(p1[0] + nx * ht, p1[1] + ny * ht), px(p1[0] - nx * ht, p1[1] - ny * ht), px(p0[0] - nx * ht, p0[1] - ny * ht)]
        d.polygon(qq, fill=(255, 200, 0, 90), outline=(220, 150, 0, 220))
        d.text(px(*p0), o['type'], fill=(160, 100, 0, 255), font=font)
os.makedirs(a.out, exist_ok=True)
im.save(os.path.join(a.out, 'furn_all.png'))
nx, ny = map(int, a.tiles.lower().split('x'))
W, H = im.size
for i in range(ny):
    for j in range(nx):
        box = (int(W * j / nx), int(H * i / ny), int(W * (j + 1) / nx), int(H * (i + 1) / ny))
        im.crop(box).save(os.path.join(a.out, f'furn_r{i}c{j}.png'))
print(json.dumps({'out': a.out, 'furniture': len(fl.get('furniture', [])), 'tiles': nx * ny}, ensure_ascii=False))
