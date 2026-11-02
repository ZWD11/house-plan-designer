"""
把 HouseSpec（户型描述 JSON）注入设计器模板，生成单文件 HTML。

用法:
  python build.py spec.json -o 输出.html [--template ../assets/template.html] [--no-underlay] [--zip]
  --zip  交付打包：HTML + 原图 / 底图 + 生成脚本（spec 同目录的 *.py）+ spec.json + 截图（*_check / check 目录的 png）打成 <输出>.zip

每次构建把每层墙数记在 spec 旁边的 .build_walls.json：墙数比上次少会提醒
（生成脚本里行尾注释把一面墙整个注释掉、静默少一面墙，第三次实战就这样丢过强弱电井分隔墙）。

spec.json 里可选的 "underlay": {"image": "原图路径", "mmPerPx": 17.65, "x": -4410, "y": -1340}
  会把原图作为底图打包进去（默认隐藏，可在左侧“户型”面板勾选显示，用来对照）。
  x, y = 图片左上角在户型坐标系里的位置（mm）。analyze.py 生成的 draft.json 已经算好。
"""
import argparse, base64, hashlib, io, json, os, re, sys
from PIL import Image
from imgio import open_upright

sys.stdout.reconfigure(encoding='utf-8')
here = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument('spec')
ap.add_argument('-o', '--out', required=True)
ap.add_argument('--template', default=os.path.join(here, '..', 'assets', 'template.html'))
ap.add_argument('--no-underlay', action='store_true')
ap.add_argument('--zip', action='store_true')
a = ap.parse_args()

spec = json.load(open(a.spec, encoding='utf-8'))
all_uls = [spec.get('underlay')] + [f.get('underlay') for f in spec.get('floors') or []]  # 打包 zip 用（下面会从 spec 里取走）

def pack_underlay(ul):
    p = ul['image'] if os.path.isabs(ul['image']) else os.path.join(os.path.dirname(os.path.abspath(a.spec)), ul['image'])
    im = open_upright(p, rotate=ul.get('rotate', 0))  # 按 EXIF 方向摆正（再按 rotate 转），和 analyze / gridmm 读到的像素坐标一致
    w, h = im.size
    # 底图压成 JPEG，长边不超过 1600，控制文件体积
    k = min(1, 1600 / max(w, h))
    if k < 1: im = im.resize((round(w * k), round(h * k)), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, 'JPEG', quality=85)
    return {'src': 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode(),
            'imgW': im.size[0], 'imgH': im.size[1], 'mmPerPx': ul['mmPerPx'] / k, 'x': ul.get('x', 0), 'y': ul.get('y', 0)}

preset = {'spec': spec}
if 'floors' in spec:
    # 整栋楼：每层可以有自己的底图（原图里这一层的那张平面）
    uls = [fl.pop('underlay', None) for fl in spec['floors']]
    if any(uls) and not a.no_underlay: preset['underlays'] = [pack_underlay(u) if u else None for u in uls]
else:
    ul = spec.pop('underlay', None)
    if ul and not a.no_underlay: preset['underlay'] = pack_underlay(ul)
body = json.dumps(preset, ensure_ascii=False, separators=(',', ':'))
preset['id'] = hashlib.sha1(body.encode()).hexdigest()[:12]  # 户型变了 id 就变，浏览器不会拿旧存档覆盖新户型

html = open(a.template, encoding='utf-8').read()
# 去掉模板里可能残留的预设，再紧跟 <meta charset> 插入（charset 必须留在文件开头）
html = re.sub(r'<script id="__preset">.*?</script>', '', html, count=1, flags=re.S)
m = re.search(r'<meta charset[^>]*>', html, re.I)
js = json.dumps(preset, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
html = html[:m.end()] + f'<script id="__preset">window.__PRESET__={js}</script>' + html[m.end():]
name = spec.get('name')
if name: html = re.sub(r'<title>.*?</title>', f'<title>{name} · 装修设计器</title>', html, count=1, flags=re.S)
os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
open(a.out, 'w', encoding='utf-8').write(html)
fl = spec.get('floors') or [spec]
# 墙数和上一次构建比：少了就提醒（多半是生成脚本里的注释吞了代码）
warn = []
mem = os.path.join(os.path.dirname(os.path.abspath(a.spec)), '.build_walls.json')
now = {f.get('name') or str(i): len(f.get('walls', [])) for i, f in enumerate(fl)}
try:
    last = json.load(open(mem, encoding='utf-8'))
    for k, n in now.items():
        if k in last and n < last[k]: warn.append(f'「{k}」墙数 {last[k]} → {n}，比上次少了 {last[k] - n} 面：确认是有意删的，不是生成脚本里的注释把墙注释掉了')
except Exception: pass
try: json.dump(now, open(mem, 'w', encoding='utf-8'), ensure_ascii=False)
except Exception: pass
for w in warn: print('[warn] ' + w, file=sys.stderr)
zipped = None
if a.zip:
    import zipfile, glob
    sd = os.path.dirname(os.path.abspath(a.spec)); zp = os.path.splitext(os.path.abspath(a.out))[0] + '.zip'
    files = {os.path.abspath(a.out): os.path.basename(a.out), os.path.abspath(a.spec): 'spec.json'}
    for p in glob.glob(os.path.join(sd, '*.py')): files[p] = 'scripts/' + os.path.basename(p)
    for u in all_uls:
        if u and u.get('image'):
            p = u['image'] if os.path.isabs(u['image']) else os.path.join(sd, u['image'])
            if os.path.exists(p): files[os.path.abspath(p)] = '原图/' + os.path.basename(p)
    for d in glob.glob(os.path.join(sd, '*check*')) + [os.path.join(sd, 'check')]:
        for p in glob.glob(os.path.join(d, '*.png')): files[p] = 'screenshots/' + os.path.basename(p)
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for p, n in files.items(): z.write(p, n)
    zipped = zp
print(json.dumps({'out': os.path.abspath(a.out), 'kb': round(len(html.encode()) / 1024), 'floors': len(fl), 'walls': sum(len(f.get('walls', [])) for f in fl),
                  'rooms': sum(len(f.get('rooms', [])) for f in fl), 'underlay': 'underlay' in preset or 'underlays' in preset,
                  'walls_per_floor': now, **({'zip': zipped} if zipped else {}), **({'warn': warn} if warn else {})}, ensure_ascii=False))
