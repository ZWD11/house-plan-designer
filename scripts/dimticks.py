"""
自动找尺寸线和刻度：白底户型图 / 装修布置图（深色细线）和黑底 CAD 截图（按线色）都能用。
输出每条尺寸线的位置和刻度像素，直接配上图上的标注数字就是 axismap 的 Axis 链。

用法:
  python dimticks.py 图.jpg --out <工作目录>/ticks              # 白底：深色细线
  python dimticks.py 黑底截图.jpg --color green --out ...         # 黑底：尺寸线是绿色
输出: ticks.json（lines[]：side = top / bottom / left / right / inner、orient = h / v、at = 线的像素位置、ticks = 刻度像素）、ticks.png（每条线编号 + 刻度圈）
在生成脚本里：X = Axis(chain(lines[i]['ticks'], [各段标注 mm]))。双图对齐用 align2.py（会调用这里的函数）。
"""
import argparse, json, os, sys
import numpy as np
import cv2
from PIL import Image, ImageDraw
from imgio import open_upright, color_mask
sys.stdout.reconfigure(encoding='utf-8')


def line_mask(rgb, color=None):
    if color: return color_mask(rgb, color)
    g = rgb.max(2).astype(int)
    if np.median(g) < 90: g = 255 - g   # 黑底灰线
    return g < 140


def find_lines(mask, min_frac=.12, merge=2):
    """长水平 / 竖直线 + 线上的刻度（跨过这条线的短斜杠、尺寸界线）"""
    H, W = mask.shape
    out = []
    for orient in ('h', 'v'):
        m = mask if orient == 'h' else mask.T
        L = m.shape[1]
        # 每一行最长的连续段（尺寸线是一整条，墙体、文字不是）
        rows = []
        for i in range(m.shape[0]):
            r = m[i]
            if r.sum() < min_frac * L: continue
            d = np.diff(np.concatenate([[0], r.astype(np.int8), [0]]))
            st, en = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
            # 允许断口（刻度、压在线上的数字把线截断）：长边的 1.2%，至少 3px
            segs, gap = [], max(3, round(L * .012))
            for a, b in zip(st, en):
                if segs and a - segs[-1][1] <= gap: segs[-1][1] = b
                else: segs.append([a, b])
            best = max(segs, key=lambda s: s[1] - s[0])
            if best[1] - best[0] >= min_frac * L: rows.append((i, best[0], best[1]))
        groups = []
        for r in rows:
            if groups and r[0] - groups[-1][-1][0] <= merge: groups[-1].append(r)
            else: groups.append([r])
        for gq in groups:
            c = int(round(np.mean([q[0] for q in gq]))); lo = min(q[1] for q in gq); hi = max(q[2] for q in gq)
            rr = 7
            band = m[max(0, c - rr):c + rr + 1, :]
            core = m[max(0, c - 1):c + 2, :].any(0)
            # 刻度：线上下两侧都有像素的列（斜杠 / 尺寸界线穿过这条线）
            up = band[:max(1, rr - 2)].sum(0); dn = band[rr + 3:].sum(0)
            # 一般两侧都有（斜杠 / 尺寸界线穿过）；贴图边的尺寸线只有一侧有尺寸界线，单侧够长也算（多出来的假刻度 align2 会跳过）
            col = (((up >= 2) & (dn >= 2)) | (up >= rr - 3) | (dn >= rr - 3)) & core
            idx = np.nonzero(col[lo:hi + 1])[0] + lo
            ticks = []
            for t in idx:
                if ticks and t - ticks[-1][-1] <= 3: ticks[-1].append(t)
                else: ticks.append([t])
            pos = [round(float(np.mean(q)), 1) for q in ticks]
            if len(pos) >= 2: out.append({'orient': orient, 'at': c, 'from': int(lo), 'to': int(hi), 'ticks': pos})
    # 位置分类：靠图边的是外道尺寸
    for ln in out:
        if ln['orient'] == 'h': ln['side'] = 'top' if ln['at'] < H * .3 else 'bottom' if ln['at'] > H * .7 else 'inner'
        else: ln['side'] = 'left' if ln['at'] < W * .3 else 'right' if ln['at'] > W * .7 else 'inner'
    # 墙线也是长直线，但几乎没有“两侧都有像素”的刻度；刻度太少的丢掉
    return [ln for ln in out if len(ln['ticks']) >= 3 or ln['side'] != 'inner']


def detect(path, color=None):
    rgb = np.array(open_upright(path))
    return rgb, find_lines(line_mask(rgb, color))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('image'); ap.add_argument('--out'); ap.add_argument('--color', help='黑底 CAD 截图里尺寸线的颜色：green / cyan / white …')
    a = ap.parse_args()
    out = a.out or os.path.splitext(a.image)[0] + '_ticks'
    os.makedirs(out, exist_ok=True)
    rgb, lines = detect(a.image, a.color)
    vis = Image.fromarray(rgb).convert('RGB'); d = ImageDraw.Draw(vis)
    for i, ln in enumerate(lines):
        if ln['orient'] == 'h':
            d.line([ln['from'], ln['at'], ln['to'], ln['at']], fill=(255, 0, 200), width=2); d.text((ln['from'], ln['at'] - 14), f'L{i}', fill=(255, 0, 200))
            for t in ln['ticks']: d.ellipse([t - 4, ln['at'] - 4, t + 4, ln['at'] + 4], outline=(0, 120, 255), width=2)
        else:
            d.line([ln['at'], ln['from'], ln['at'], ln['to']], fill=(255, 0, 200), width=2); d.text((ln['at'] + 4, ln['from']), f'L{i}', fill=(255, 0, 200))
            for t in ln['ticks']: d.ellipse([ln['at'] - 4, t - 4, ln['at'] + 4, t + 4], outline=(0, 120, 255), width=2)
    vis.save(os.path.join(out, 'ticks.png'))
    json.dump({'image': os.path.abspath(a.image), 'lines': lines}, open(os.path.join(out, 'ticks.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for i, ln in enumerate(lines): print(f"L{i} {ln['side']:6} {ln['orient']} at={ln['at']} 刻度 {len(ln['ticks'])}: {ln['ticks'][:14]}{' …' if len(ln['ticks']) > 14 else ''}")
    print('输出', out)
