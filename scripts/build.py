"""
把 HouseSpec（户型描述 JSON）注入设计器模板，生成单文件 HTML。

用法:
  python build.py spec.json -o 输出.html [--template ../assets/template.html] [--no-underlay]

spec.json 里可选的 "underlay": {"image": "原图路径", "mmPerPx": 17.65, "x": -4410, "y": -1340}
  会把原图作为底图打包进去（默认隐藏，可在左侧“户型”面板勾选显示，用来对照）。
  x, y = 图片左上角在户型坐标系里的位置（mm）。analyze.py 生成的 draft.json 已经算好。
"""
import argparse, base64, hashlib, io, json, os, re, sys
from PIL import Image

sys.stdout.reconfigure(encoding='utf-8')
here = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument('spec')
ap.add_argument('-o', '--out', required=True)
ap.add_argument('--template', default=os.path.join(here, '..', 'assets', 'template.html'))
ap.add_argument('--no-underlay', action='store_true')
a = ap.parse_args()

spec = json.load(open(a.spec, encoding='utf-8'))
ul = spec.pop('underlay', None)
preset = {'spec': spec}
if ul and not a.no_underlay:
    p = ul['image'] if os.path.isabs(ul['image']) else os.path.join(os.path.dirname(os.path.abspath(a.spec)), ul['image'])
    im = Image.open(p).convert('RGB')
    w, h = im.size
    # 底图压成 JPEG，长边不超过 1600，控制文件体积
    k = min(1, 1600 / max(w, h))
    if k < 1: im = im.resize((round(w * k), round(h * k)), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, 'JPEG', quality=85)
    preset['underlay'] = {'src': 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode(),
                          'imgW': im.size[0], 'imgH': im.size[1], 'mmPerPx': ul['mmPerPx'] / k, 'x': ul.get('x', 0), 'y': ul.get('y', 0)}
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
print(json.dumps({'out': os.path.abspath(a.out), 'kb': round(len(html.encode()) / 1024), 'walls': len(spec.get('walls', [])),
                  'rooms': len(spec.get('rooms', [])), 'underlay': 'underlay' in preset}, ensure_ascii=False))
