"""
双图对齐：“墙按原图、家具按设计图”时，把第二张图（装修平面布置图）对到第一张图（户型原图）的毫米坐标系上，
算出第二张图的 mmPerPx 和原点，直接写成 underlay 给 furnoverlay / build 用。不用再手工找刻度像素。

做法：在图上自动找尺寸线刻度（dimticks.py），按你给的一道尺寸链（各段 mm）在刻度里找“间距比例对得上”的那一串，
最小二乘拟合 像素 → 毫米。两张图都有同一道尺寸链时自动用原图的换算定起点；没有时用 --x-start / --y-start 给起点的毫米坐标。

用法:
  python align2.py spec.json 设计图.jpg --x-segs 240 1220 240 2740 230 2370 240 3820 240 --y-segs 240 3260 120 2480 240 1780 230 4570 240 \
         --x-start -120 --y-start -120 [--rotate 180] --out <工作目录>/align
    spec.json      原图那份 spec（读 underlay：原图路径、mmPerPx、x、y）
    --x-segs       设计图上一道水平尺寸链（从左到右，mm）；--y-segs 一道竖直尺寸链（从上到下）
    --x-start      这道链第一个刻度在户型坐标系里的 x（mm）；不给就在原图上找同一道链，用原图的换算算出来
    --rotate       设计图要先转多少度才和原图同向（顺时针，0 / 90 / 180 / 270；图上文字倒着 = 180）
输出: align.json（underlay：image / mmPerPx / x / y / rotate，误差）、align.png（设计图按算出来的换算叠上原图墙线，看对不对）
下一步: python furnoverlay.py spec.json --image 设计图.jpg --mm-per-px <k> --origin <x> <y> [--rotate 180]
验收：两张图对位误差（各刻度拟合残差的均方根）≤ 20mm。
"""
import argparse, json, os, sys
import numpy as np
from PIL import Image
from imgio import open_upright
from dimticks import find_lines, line_mask
sys.stdout.reconfigure(encoding='utf-8')


def match_chain(lines, orient, segs, prefer=None):
    """在 orient 方向的尺寸线里找和 segs 比例一致的刻度串。返回 (刻度像素列表 len(segs)+1，线, 残差 px)"""
    cum = np.concatenate([[0], np.cumsum(segs)]); tot = cum[-1]
    best = None
    for ln in lines:
        if ln['orient'] != orient: continue
        t = np.array(ln['ticks'], float)
        m = len(cum) - 1
        # 两个锚点刻度对应链上的哪两个点：首尾；首尾里有一个没认出（图裁掉、数字压线）时用倒数第二 / 第二个
        for ca, cb in ((0, m), (0, m - 1), (1, m)):
            if cb <= ca: continue
            for i in range(len(t)):
                for j in range(i + 1, len(t)):
                    span = t[j] - t[i]
                    if span < 60: continue
                    k = span / (cum[cb] - cum[ca])                       # px / mm
                    pred = t[i] + (cum - cum[ca]) * k
                    tol = max(2.5, min(max(3.0, span * .012), .45 * min(segs) * k))   # 不能比最短一段的一半还宽，不然几个预测点会抢同一个刻度
                    near = [t[np.argmin(np.abs(t - p))] for p in pred]
                    ok = [abs(n - p) <= tol for n, p in zip(near, pred)]
                    used = [n for n, o in zip(near, ok) if o]
                    hit = len(set(used))
                    if hit != len(used) or hit < len(cum) - 1: continue    # 一个刻度只能用一次；最多容忍一个没认出
                    res = float(np.mean([abs(n - p) for n, p, o in zip(near, pred, ok) if o]))
                    ticks = [n if o else p for n, p, o in zip(near, pred, ok)]
                    key = (hit, ln['side'] != 'inner', -res)               # 同分时优先外道尺寸线
                    if best is None or key > best[0]: best = (key, ticks, ln, res, hit)
    if not best: return None
    return {'ticks': [round(float(v), 1) for v in best[1]], 'line_at': int(best[2]['at']), 'side': best[2]['side'], 'resid_px': round(float(best[3]), 2), 'matched': int(best[4]), 'of': len(cum)}


def fit(px, mm):
    k, b = np.polyfit(np.array(px, float), np.array(mm, float), 1)
    r = np.array(mm) - (k * np.array(px) + b)
    return float(k), float(b), float(np.abs(r).max()), float(np.sqrt((r ** 2).mean()))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec'); ap.add_argument('image')
    ap.add_argument('--x-segs', type=float, nargs='+', required=True); ap.add_argument('--y-segs', type=float, nargs='+', required=True)
    ap.add_argument('--x-start', type=float); ap.add_argument('--y-start', type=float)
    ap.add_argument('--rotate', type=int, default=0, choices=[0, 90, 180, 270]); ap.add_argument('--color')
    ap.add_argument('--floor', type=int, default=0); ap.add_argument('--out', required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    spec = json.load(open(a.spec, encoding='utf-8'))
    fl = spec['floors'][a.floor] if 'floors' in spec else spec
    ul = fl.get('underlay') or spec.get('underlay')
    base = os.path.dirname(os.path.abspath(a.spec))

    imB = open_upright(a.image, rotate=a.rotate)
    rgbB = np.array(imB); linesB = find_lines(line_mask(rgbB, a.color))
    mx, my = match_chain(linesB, 'h', a.x_segs), match_chain(linesB, 'v', a.y_segs)
    if not mx or not my:
        sys.exit(f"设计图上没找到这道尺寸链：{'水平' if not mx else '竖直'}。先跑 dimticks.py 看 ticks.png，核对各段数字 / 方向（--rotate）")
    res = {'image': os.path.abspath(a.image), 'rotate': a.rotate, 'x_chain_B': mx, 'y_chain_B': my}
    starts = {}
    for ax, m, segs, st in (('x', mx, a.x_segs, a.x_start), ('y', my, a.y_segs, a.y_start)):
        if st is not None: starts[ax] = st; continue
        # 原图上找同一道链，按原图 underlay 换算出起点毫米
        if not ul: sys.exit(f'没给 --{ax}-start，原图 spec 里也没有 underlay')
        pA = ul['image'] if os.path.isabs(ul['image']) else os.path.join(base, ul['image'])
        rgbA = np.array(open_upright(pA, rotate=ul.get('rotate', 0)))
        mA = match_chain(find_lines(line_mask(rgbA)), 'h' if ax == 'x' else 'v', segs)
        if not mA: sys.exit(f'原图上没找到同一道 {ax} 方向尺寸链：用 --{ax}-start 直接给第一个刻度的毫米坐标')
        starts[ax] = ul[ax] + mA['ticks'][0] * ul['mmPerPx']
        res[f'{ax}_chain_A'] = mA
    out = {}
    for ax, m, segs in (('x', mx, a.x_segs), ('y', my, a.y_segs)):
        mm = starts[ax] + np.concatenate([[0], np.cumsum(segs)])
        k, b, err, rms = fit(m['ticks'], mm)
        out[ax] = {'mmPerPx': round(k, 4), 'origin': round(b, 1), 'rms_mm': round(rms, 1), 'max_err_mm': round(err, 1)}
    kx, ky = out['x']['mmPerPx'], out['y']['mmPerPx']
    res['fit'] = out
    res['scale_diff_pct'] = round(abs(kx - ky) / ((kx + ky) / 2) * 100, 2)
    res['underlay'] = {'image': os.path.abspath(a.image), 'mmPerPx': round((kx + ky) / 2, 4), 'x': out['x']['origin'], 'y': out['y']['origin'], **({'rotate': a.rotate} if a.rotate else {})}
    # 位图上一个像素就是十几毫米，单个刻度偏 1~2px 是画图 / 截图本身的误差：按均方根 ≤ 20mm 判定，最大误差列出来供参考
    res['ok'] = max(out['x']['rms_mm'], out['y']['rms_mm']) <= 20 and res['scale_diff_pct'] <= 1.5
    # 叠图：原图（红）+ 设计图（按算出的换算对齐到原图像素）
    if ul:
        pA = ul['image'] if os.path.isabs(ul['image']) else os.path.join(base, ul['image'])
        A = open_upright(pA, 'L', rotate=ul.get('rotate', 0)); sAB = res['underlay']['mmPerPx'] / ul['mmPerPx']
        Bs = imB.convert('L').resize((max(1, round(imB.width * sAB)), max(1, round(imB.height * sAB))))
        canvas = Image.new('L', A.size, 255); canvas.paste(Bs, (round((res['underlay']['x'] - ul['x']) / ul['mmPerPx']), round((res['underlay']['y'] - ul['y']) / ul['mmPerPx'])))
        Image.merge('RGB', (A, canvas, canvas)).save(os.path.join(a.out, 'align.png'))
    json.dump(res, open(os.path.join(a.out, 'align.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps({'underlay': res['underlay'], 'fit': out, 'scale_diff_pct': res['scale_diff_pct'], 'ok': res['ok'],
                      'next': f"python furnoverlay.py {a.spec} --image \"{a.image}\" --mm-per-px {res['underlay']['mmPerPx']} --origin {out['x']['origin']} {out['y']['origin']}" + (f' --rotate {a.rotate}' if a.rotate else '')}, ensure_ascii=False, indent=1))
    if not res['ok']: print('均方根误差超过 20mm 或两个方向比例差 > 1.5%：看 align.png（红 = 原图、青 = 设计图），检查尺寸链数字 / 起点', file=sys.stderr)
