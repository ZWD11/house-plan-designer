"""
截图 / 扫描件上的尺寸数字识别（位图 OCR 兜底，不装任何 OCR 库）。
思路和 dimtext.py（矢量字形）一样是“破译”：同一张图里同一个数字的字形几乎一样 → 字形聚类；
每段尺寸线的长度按比例大致量得出来（误差 1~3%）→ 每个位置该是哪个数字基本确定 → 投票得到“哪类字形是哪个数字”
→ 再把每段读出来，和量出来的长度逐段校验（差 > 2% 的标 ✗，交给人看）。

用法:
  python dimocr.py 图.jpg --scale 12.96 --out <工作目录>/ocr                 # 白底：深色文字（尺寸线、刻度自动找，同 dimticks.py）
  python dimocr.py 黑底截图.jpg --color green --scale 5.902 --out ...          # 黑底：尺寸文字和尺寸线同色
  可选 --lines 0,3,5（只读 dimticks 输出里的这几条线）  --band 40（文字离尺寸线最远多少像素）
输出: ocr.json（每条线：ticks、每段 measured_mm / read（读出的数字，?=没读准）/ ok）、glyphs.png（每类字形和认成的数字）、ocr.png（读数标回图上）
生成脚本里：读出且 ok 的段直接当标注值用；`?` 的段人工看图补。
"""
import argparse, json, os, sys
from collections import Counter, defaultdict
import numpy as np
import cv2
from PIL import Image, ImageDraw
from imgio import open_upright
from dimticks import find_lines, line_mask
sys.stdout.reconfigure(encoding='utf-8')

GW, GH = 16, 24


def glyphs_of(mask, ln, a, b, band, side, rot=1):
    """尺寸线 ln 上 a~b 段、side 一侧（-1 上 / 左，+1 下 / 右）的文字 → 按阅读顺序的字形位图列表"""
    at = ln['at']
    if ln['orient'] == 'h':
        y0, y1 = (at - band, at - 2) if side < 0 else (at + 3, at + band)
        crop = mask[max(0, y0):max(0, y1), int(a):int(b) + 1]
    else:
        x0, x1 = (at - band, at - 2) if side < 0 else (at + 3, at + band)
        crop = mask[int(a):int(b) + 1, max(0, x0):max(0, x1)]
        crop = np.rot90(crop, rot)         # 竖向文字：从下往上写的 rot=1，从上往下（或图转过）的 rot=-1，调用方两种都试
    if crop.size == 0: return [], crop
    n, lab, st, _ = cv2.connectedComponentsWithStats(crop.astype(np.uint8), 8)
    H, W = crop.shape
    # 碰到裁剪框边缘的是尺寸线、刻度斜杠、尺寸界线的碎块，不是字
    comps = [k for k in range(1, n) if st[k, 4] >= 4 and st[k, 3] >= 3 and st[k, 0] > 0 and st[k, 1] > 0 and st[k, 0] + st[k, 2] < W and st[k, 1] + st[k, 3] < H]
    if not comps: return [], crop
    hs = np.array([st[k, 3] for k in comps]); hmed = np.median(hs)
    # 文字：高度接近中位数的那几个（尺寸界线、斜杠是细长的，高得多 / 扁得多）
    comps = [k for k in comps if .55 * hmed <= st[k, 3] <= 1.5 * hmed and st[k, 2] <= 1.4 * hmed]
    # 同一行：按 y 中心聚
    if not comps: return [], crop
    yc = np.median([st[k, 1] + st[k, 3] / 2 for k in comps])
    comps = [k for k in comps if abs(st[k, 1] + st[k, 3] / 2 - yc) < hmed * .6]
    # 横向重叠的并成一个字（断开的“5”、“7”）
    comps.sort(key=lambda k: st[k, 0])
    groups = []
    for k in comps:
        x, w = st[k, 0], st[k, 2]
        if groups and x <= groups[-1][1] - 1: groups[-1][1] = max(groups[-1][1], x + w); groups[-1][2].append(k)
        else: groups.append([x, x + w, [k]])
    out = []
    for x0, x1, ks in groups:
        ys = [st[k, 1] for k in ks]; ye = [st[k, 1] + st[k, 3] for k in ks]
        g = np.isin(lab[min(ys):max(ye), x0:x1], ks).astype(np.uint8) * 255
        # 按高度缩放、保持宽高比（“1”很窄，拉满宽度会和别的字混成一类），居中放进 GW × GH
        h, w = g.shape; k2 = GH / h; nw = max(1, min(GW, round(w * k2)))
        r = cv2.resize(g, (nw, GH), interpolation=cv2.INTER_AREA); cv = np.zeros((GH, GW), np.uint8); x0 = (GW - nw) // 2; cv[:, x0:x0 + nw] = r
        out.append(cv.astype(np.float32) / 255)
    return out, crop


def cluster(gs, thr=.82):
    """字形聚类：归一化相关系数 > thr 的归一类"""
    reps, ids = [], []
    for g in gs:
        v = g.flatten() - g.mean(); v /= (np.linalg.norm(v) + 1e-6)
        best, bi = -1, -1
        for i, r in enumerate(reps):
            c = float(v @ r[0]);
            if c > best: best, bi = c, i
        if best > thr: ids.append(bi); r = reps[bi]; r[1].append(v); m = np.mean(r[1], 0); reps[bi] = (m / (np.linalg.norm(m) + 1e-6), r[1], r[2] + [g])
        else: ids.append(len(reps)); reps.append((v, [v], [g]))
    return ids, reps


def candidates(mm):
    """量出来的长度 → 可能的标注值（取整到 10 / 50，按接近程度排）"""
    c = {int(round(mm / s) * s) for s in (10, 50, 100)}
    # 图上的尺寸绝大多数是 50 的整倍数：先排 50 的倍数，再按接近程度
    return sorted((v for v in c if v > 0 and abs(v - mm) <= max(25, mm * .035)), key=lambda v: (v % 50 != 0, abs(v - mm)))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('image'); ap.add_argument('--scale', type=float, required=True, help='mm / 像素（cadshot.py / analyze.py / align2.py 算出来的）')
    ap.add_argument('--color'); ap.add_argument('--lines'); ap.add_argument('--band', type=int, help='文字离尺寸线最远多少像素（默认按图片大小：长边的 2.5%，至少 40）'); ap.add_argument('--out', required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rgb = np.array(open_upright(a.image)); lmask = line_mask(rgb, a.color)
    # 文字常和尺寸线不同色（黑底截图：线绿、字白）：黑底取所有亮像素，白底取所有深色像素
    mask = rgb.max(2) > 90 if np.median(rgb.max(2)) < 90 else line_mask(rgb)
    if not a.band: a.band = max(40, round(max(rgb.shape[:2]) * .025))
    lines = find_lines(lmask)
    if a.lines: lines = [lines[int(i)] for i in a.lines.split(',')]
    def read_segs(ln, li, rot):
        t, outl = ln['ticks'], []
        for si in range(len(t) - 1):
            mm = (t[si + 1] - t[si]) * a.scale
            if mm < 50: continue
            best = []
            for side in (-1, 1):
                gs, _ = glyphs_of(mask, ln, t[si] + 1, t[si + 1] - 1, a.band, side, rot)
                if 2 <= len(gs) <= 6 and (not best or abs(len(gs) - len(str(round(mm)))) < abs(len(best) - len(str(round(mm))))): best = gs
            outl.append((li, si, mm, best))
        return outl
    def learn(segs):
        """字形聚类 + 投票：位数对得上的段，候选值的每一位投给对应字形类 → 每类字形是哪个数字"""
        allg = [g for s2 in segs for g in s2[3]]
        ids, reps = cluster(allg)
        votes = defaultdict(Counter); k = 0
        for li, si, mm, gs in segs:
            my = ids[k:k + len(gs)]; k += len(gs)
            for ci, cand in enumerate(candidates(mm)):
                st_ = str(cand)
                if len(st_) != len(my): continue
                for d, c in zip(st_, my): votes[c][d] += 3 if ci == 0 else 1
        digit = {c: v.most_common(1)[0][0] for c, v in votes.items() if v}
        return reps, digit, [(reps[c][0], d) for c, d in digit.items()]
    def judge(sg, tmpl):
        li, si, mm, gs = sg
        def classify(g):
            v = g.flatten() - g.mean(); v /= (np.linalg.norm(v) + 1e-6)
            best = max(tmpl, key=lambda t2: float(v @ t2[0])); return best[1] if float(v @ best[0]) > .6 else '?'
        txt = ''.join(classify(g) for g in gs) if gs else ''
        val = int(txt) if txt and '?' not in txt else None
        ok = val is not None and abs(val - mm) <= max(30, mm * .02)   # 2%：读错一位（3900 读成 3800）也能被拦下
        return {'line': li, 'seg': si, 'measured_mm': round(mm), 'read': txt or '?', 'value': val if ok else None, 'ok': ok}
    # 1. 横向尺寸线先学一遍字形
    hsegs = [s2 for li, ln in enumerate(lines) if ln['orient'] == 'h' for s2 in read_segs(ln, li, 1)]
    if not any(s2[3] for s2 in hsegs): sys.exit('横向尺寸线旁边没找到文字：看 dimticks.py 的 ticks.png，调 --band / --color')
    reps, digit, tmpl = learn(hsegs)
    # 2. 竖向线两个旋转方向都试，取对得上更多的那个方向
    vsegs = []
    for li, ln in enumerate(lines):
        if ln['orient'] != 'v': continue
        vsegs += max((read_segs(ln, li, r) for r in (1, -1)), key=lambda sg: sum(judge(x, tmpl)['ok'] for x in sg))
    # 3. 横竖所有字形合起来再学一遍（只在横向线上出现过的数字太少时，竖向线能补全 0~9），然后全部重读
    allsegs = hsegs + vsegs
    reps, digit, tmpl = learn(allsegs)
    order = {(s2[0], s2[1]): s2 for s2 in allsegs}
    res = [judge(order[k2], tmpl) for k2 in sorted(order)]
    okn = sum(r['ok'] for r in res)
    out = []
    for li, ln in enumerate(lines):
        rs = [r for r in res if r['line'] == li]
        out.append({'line': li, 'side': ln['side'], 'orient': ln['orient'], 'at': ln['at'], 'ticks': ln['ticks'], 'segs': rs})
    json.dump({'image': os.path.abspath(a.image), 'scale': a.scale, 'lines': out, 'digits': {str(c): d for c, d in digit.items()}}, open(os.path.join(a.out, 'ocr.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    # glyphs.png：每类字形一格 + 认成的数字
    sheet = Image.new('RGB', (len(reps) * 40 + 10, 70), (255, 255, 255)); d = ImageDraw.Draw(sheet)
    for i, r in enumerate(reps):
        g = (np.mean(r[2], 0) * 255).astype(np.uint8); sheet.paste(Image.fromarray(255 - g).resize((GW * 2, GH * 2)), (5 + i * 40, 2))
        d.text((15 + i * 40, 52), digit.get(i, '?'), fill=(220, 0, 0))
    sheet.save(os.path.join(a.out, 'glyphs.png'))
    vis = Image.fromarray(rgb).convert('RGB'); d = ImageDraw.Draw(vis)
    for L in out:
        for r in L['segs']:
            t0, t1 = L['ticks'][r['seg']], L['ticks'][r['seg'] + 1]; m = (t0 + t1) / 2
            p = (m, L['at'] + 6) if L['orient'] == 'h' else (L['at'] + 6, m)
            d.text(p, r['read'], fill=(0, 160, 0) if r['ok'] else (230, 0, 0))
    vis.save(os.path.join(a.out, 'ocr.png'))
    print(f'{okn} / {len(res)} 段读出且和量出的长度一致（{len(reps)} 类字形）')
    for L in out:
        rs = L['segs']
        if rs: print(f"L{L['line']} {L['side']:6} {L['orient']}: " + '  '.join(f"{r['read']}{'' if r['ok'] else '✗'}(量 {r['measured_mm']})" for r in rs))
