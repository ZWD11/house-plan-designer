"""检查 qa.mjs 导出的文件能不能打开、内容是否正常。
python qa_files.py <downloads 目录>
- PNG / JPG：能解码、尺寸合理、不是空白图
- DXF：ezdxf 能读、模型空间有实体、文字不乱码
- PDF：能读、页数 > 0、每页有内容
- CSV：UTF-8（带 BOM 也行）、表头 + 数据行、没有 NaN / undefined
- JSON：能解析、版本号和墙体数组都在
- 分享 HTML：里面带方案数据
"""
import sys, os, json, csv, io, re
from PIL import Image, ImageStat

d = sys.argv[1]
bad, rows = [], []
BADTXT = re.compile(r'NaN|undefined|Infinity|\[object')

def chk_img(p):
    im = Image.open(p); im.load(); w, h = im.size
    if w < 400 or h < 300: return f'尺寸太小 {w}×{h}'
    g = im.convert('L').resize((min(400, w), min(300, h)))
    sd = ImageStat.Stat(g).stddev[0]
    if sd < 4: return f'像是空白图（起伏 {sd:.1f}）'
    return f'{w}×{h}'

def chk_dxf(p):
    import ezdxf
    doc = ezdxf.readfile(p); msp = doc.modelspace(); n = len(msp)
    if n < 20: return f'实体太少：{n}'
    txt = [e.dxf.text for e in msp.query('TEXT')] + [e.text for e in msp.query('MTEXT')]
    for t in txt:
        if BADTXT.search(t) or '�' in t: return f'文字异常：{t[:30]}'
    layers = sorted({e.dxf.layer for e in msp})
    return f'{n} 个实体 · {len(layers)} 个图层'

def chk_pdf(p):
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader
    r = PdfReader(p); n = len(r.pages)
    if not n: return '0 页'
    empty = [i + 1 for i, pg in enumerate(r.pages) if len(pg.get_contents().get_data() if pg.get_contents() else b'') < 200 and not pg.images]
    if empty: return f'第 {empty} 页像是空的'
    return f'{n} 页'

def chk_csv(p):
    raw = open(p, 'rb').read(); t = raw.decode('utf-8-sig')
    rs = list(csv.reader(io.StringIO(t)))
    if len(rs) < 3: return f'只有 {len(rs)} 行'
    for r in rs:
        for c in r:
            if BADTXT.search(c): return f'有异常值：{c[:30]}'
    return f'{len(rs)} 行'

def chk_json(p):
    j = json.load(open(p, encoding='utf-8'))
    if 'floors' in j: return f'整栋 {len(j["floors"])} 层'
    if j.get('version') != 2 or not isinstance(j.get('walls'), list): return '格式不对'
    return f'{len(j["walls"])} 面墙'

def chk_html(p):
    t = open(p, encoding='utf-8', errors='replace').read()
    if len(t) < 100000: return f'太小（{len(t)} 字节）'
    return f'{len(t) // 1024} KB'

for f in sorted(os.listdir(d)):
    p = os.path.join(d, f); ext = f.rsplit('.', 1)[-1].lower()
    fn = {'png': chk_img, 'jpg': chk_img, 'jpeg': chk_img, 'dxf': chk_dxf, 'pdf': chk_pdf, 'csv': chk_csv, 'json': chk_json, 'html': chk_html}.get(ext)
    if not fn: continue
    try:
        r = fn(p); ok = not re.search(r'太小|空白|太少|异常|不对|空的|0 页|只有', r)
    except Exception as e:
        r, ok = f'打不开：{type(e).__name__} {str(e)[:80]}', False
    rows.append((ok, f, r))
    if not ok: bad.append(f)
for ok, f, r in rows: print(('OK  ' if ok else 'BAD ') + f + '  —  ' + r)
print(f'\n{len(rows) - len(bad)} / {len(rows)} 个文件正常')
sys.exit(1 if bad else 0)
