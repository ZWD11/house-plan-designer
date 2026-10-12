"""
读尺寸数字：CAD 导出的 PDF 里，尺寸文字常常是 SHX / TrueType 字体炸成的轮廓或线条，没有文字层，OCR 也不一定装得了。
这里用“破译”的办法：同一张图里同一个数字的字形完全一样 → 把字形按形状聚类；每段尺寸线量出来的长度大致知道
（比例误差 < 1%），所以每个位置上的数字基本确定 → 投票得到“哪一类字形是哪个数字” → 再把所有尺寸读出来、逐段校验。

cadvec.py 调用：decode(fills, strokes, chains, ticks, tick_size, T, scale_guesses) → (每条尺寸线每段的标注值, 比例, 报告)
单位：输入是图纸单位（PDF 的 pt），输出的标注值是 mm。
"""
import math
from collections import Counter, defaultdict
import numpy as np
import cv2

GH, GW = 56, 48  # 字形归一化画布（高 × 宽）


def _bbox(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def collect_chars(fills, strokes, chains, ticks, tick_size, T):
    """尺寸线附近的小图元 → 按包围盒相交并成“字符”"""
    tk = np.array([(t[0], t[1]) for t in ticks]) if ticks else np.zeros((0, 2))
    near = 3.2 * tick_size
    lines = [(d['orient'], d['at'], min(d['ticks']) - tick_size * 3, max(d['ticks']) + tick_size * 3) for d in chains]

    def close_to_dim(b):
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        for o, at, lo, hi in lines:
            if o == 'h' and abs(cy - at) < near and lo <= cx <= hi: return True
            if o == 'v' and abs(cx - at) < near and lo <= cy <= hi: return True
        return False

    prims = []  # (bbox, kind, data, grp)
    for f in fills:
        b = _bbox(f['poly']); m = max(b[2] - b[0], b[3] - b[1])
        if not (.03 * T <= m <= 1.1 * T) or not close_to_dim(b): continue
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        if len(tk) and (np.hypot(tk[:, 0] - cx, tk[:, 1] - cy) < tick_size * .6).any(): continue  # 起止符号
        prims.append((b, 'f', f['poly'], f.get('grp', id(f))))
    if len(prims) < 6:  # 没有填充字：用细线字（SHX 单线字体）
        for s in strokes:
            if s.get('filled'): continue
            b = _bbox(s['pts']); m = max(b[2] - b[0], b[3] - b[1])
            if not (.03 * T <= m <= 1.1 * T) or not close_to_dim(b): continue
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            if len(tk) and (np.hypot(tk[:, 0] - cx, tk[:, 1] - cy) < tick_size * .6).any(): continue
            prims.append((b, 's', s['pts'], None))
    # 并查集：包围盒相交（留一点余量）就是同一个字
    pad = .02 * T
    par = list(range(len(prims)))
    def find(i):
        while par[i] != i: par[i] = par[par[i]]; i = par[i]
        return i
    order = sorted(range(len(prims)), key=lambda i: prims[i][0][0])
    for ii, i in enumerate(order):
        bi = prims[i][0]
        for j in order[ii + 1:]:
            bj = prims[j][0]
            if bj[0] > bi[2] + pad: break
            if bj[1] <= bi[3] + pad and bi[1] <= bj[3] + pad:
                # 只在一个包住另一个、或明显重叠时合并（相邻两个字只是挨着，不合并）
                ox = min(bi[2], bj[2]) - max(bi[0], bj[0]); oy = min(bi[3], bj[3]) - max(bi[1], bj[1])
                small = min((bi[2] - bi[0]) * (bi[3] - bi[1]), (bj[2] - bj[0]) * (bj[3] - bj[1])) + 1e-9
                if ox > -pad and oy > -pad and (max(ox, 0) * max(oy, 0) > .15 * small or ox > 0 and oy > 0):
                    par[find(i)] = find(j)
    groups = defaultdict(list)
    for i in range(len(prims)): groups[find(i)].append(prims[i])
    chars = []
    for g in groups.values():
        b = (min(p[0][0] for p in g), min(p[0][1] for p in g), max(p[0][2] for p in g), max(p[0][3] for p in g))
        chars.append(dict(bbox=b, prims=g, cx=(b[0] + b[2]) / 2, cy=(b[1] + b[3]) / 2))
    return chars


def raster(ch, rot):
    """字 → 归一化位图。rot: 0 = 正向，1 = 逆时针转了 90°（从下往上读），-1 = 顺时针 90°"""
    def tr(p):
        x, y = p
        if rot == 0: return x, y
        if rot == 1: return -y, x
        return y, -x
    pts_all = [tr(p) for pr in ch['prims'] for p in pr[2]]
    u0, v0, u1, v1 = _bbox(pts_all)
    h = max(v1 - v0, 1e-9); k = (GH - 4) / h
    w = (u1 - u0) * k
    ox = (GW - w) / 2 - u0 * k; oy = 2 - v0 * k
    img = np.zeros((GH, GW), np.uint8)
    by_grp = defaultdict(list)
    for pr in ch['prims']:
        if pr[1] == 'f': by_grp[pr[3]].append(pr[2])
        else:
            q = np.array([[tr(p)[0] * k + ox, tr(p)[1] * k + oy] for p in pr[2]], np.float32)
            cv2.polylines(img, [np.round(q * 4).astype(np.int32)], False, 1, 2 * 4, cv2.LINE_8, shift=2)
    for polys in by_grp.values():
        layer = np.zeros_like(img)
        for pl in polys:
            q = np.array([[tr(p)[0] * k + ox, tr(p)[1] * k + oy] for p in pl], np.float32)
            one = np.zeros_like(img); cv2.fillPoly(one, [np.round(q * 4).astype(np.int32)], 1, shift=2); layer ^= one
        img |= layer
    return img, (u1 - u0) / h  # 位图 + 宽高比


def _iou(a, b):
    # 允许 1 像素的错位：a 落在 b 膨胀后的范围里、b 落在 a 膨胀后的范围里
    k = np.ones((3, 3), np.uint8)
    ad, bd = cv2.dilate(a, k), cv2.dilate(b, k)
    na, nb = a.sum(), b.sum()
    if not na or not nb: return 0
    return min((a & bd).sum() / na, (b & ad).sum() / nb) * (1 - abs(int(na) - int(nb)) / max(na, nb))


def decode(fills, strokes, chains, ticks, tick_size, T, scale_guesses):
    chars = collect_chars(fills, strokes, chains, ticks, tick_size, T)
    if len(chars) < 8: return None
    # 1. 每条尺寸线：附近的字按沿线方向串成“词”，再分给最近的一段
    words = []
    for ci, d in enumerate(chains):
        o, at = d['orient'], d['at']
        cs = [c for c in chars if (abs(c['cy'] - at) < 3.2 * tick_size if o == 'h' else abs(c['cx'] - at) < 3.2 * tick_size)
              and min(d['ticks']) - tick_size * 4 <= (c['cx'] if o == 'h' else c['cy']) <= max(d['ticks']) + tick_size * 4]
        if not cs: continue
        hs = [((c['bbox'][3] - c['bbox'][1]) if o == 'h' else (c['bbox'][2] - c['bbox'][0])) for c in cs]
        hmed = float(np.median(hs))
        cs = [c for c, h in zip(cs, hs) if .5 * hmed <= h <= 1.6 * hmed]  # 字高差太多的不是同一行数字
        along = (lambda c: c['cx']) if o == 'h' else (lambda c: c['cy'])
        perp = (lambda c: c['cy']) if o == 'h' else (lambda c: c['cx'])
        cs.sort(key=along)
        cur = []
        for c in cs:
            if cur:
                last = cur[-1]
                gap = (c['bbox'][0] - last['bbox'][2]) if o == 'h' else (c['bbox'][1] - last['bbox'][3])
                if gap > .55 * hmed or abs(perp(c) - perp(last)) > .45 * hmed:
                    words.append(dict(chain=ci, chars=cur)); cur = []
            cur.append(c)
        if cur: words.append(dict(chain=ci, chars=cur))
    # 词 → 段：词的中心落在哪一段（落在刻度附近就给更近的中点）
    seg_word = {}
    for w in words:
        d = chains[w['chain']]; o = d['orient']
        mid = np.mean([(c['cx'] if o == 'h' else c['cy']) for c in w['chars']])
        tks = d['ticks']
        best = None
        for k in range(len(tks) - 1):
            m = (tks[k] + tks[k + 1]) / 2
            inside = tks[k] - tick_size * .3 <= mid <= tks[k + 1] + tick_size * .3
            dist = abs(mid - m) - (1e9 if inside else 0)
            if best is None or dist < best[0]: best = (dist, k)
        if best is None: continue
        key = (w['chain'], best[1])
        prev = seg_word.get(key)
        if prev is None or abs(np.mean([(c['cx'] if o == 'h' else c['cy']) for c in prev['chars']]) - (tks[best[1]] + tks[best[1] + 1]) / 2) > abs(mid - (tks[best[1]] + tks[best[1] + 1]) / 2):
            seg_word[key] = w
    if len(seg_word) < 4: return None
    # 2. 字形聚类。竖向尺寸的字是转过 90° 的：两个方向都试，取和横向字形更像的那个
    hchars = [c for (ci, k), w in seg_word.items() if chains[ci]['orient'] == 'h' for c in w['chars']]
    for c in hchars: c['bm'], c['ar'] = raster(c, 0)
    vwords = [w for (ci, k), w in seg_word.items() if chains[ci]['orient'] == 'v']
    vrot = 1
    if vwords and hchars:
        score = {}
        for r in (1, -1):
            tot = 0
            for w in vwords[:12]:
                for c in w['chars']:
                    bm, _ = raster(c, r); tot += max(_iou(bm, h['bm']) for h in hchars[:80])
            score[r] = tot
        vrot = max(score, key=score.get)
    for (ci, k), w in seg_word.items():
        if chains[ci]['orient'] == 'v':
            for c in w['chars']: c['bm'], c['ar'] = raster(c, vrot)
            # 从下往上读（逆时针转）时，阅读顺序是 y 递减
            w['chars'].sort(key=lambda c: -c['cy'] if vrot == 1 else c['cy'])
        else:
            w['chars'].sort(key=lambda c: c['cx'])
    protos = []  # [bitmap, members]
    for w in seg_word.values():
        for c in w['chars']:
            best = None
            for pi, pr in enumerate(protos):
                s = _iou(c['bm'], pr[0])
                if s > .82 and (best is None or s > best[0]): best = (s, pi)
            if best: c['cls'] = best[1]; protos[best[1]][1] += 1
            else: c['cls'] = len(protos); protos.append([c['bm'], 1])
    # 3. 破译：先按候选比例量出每段长度，按位投票
    def solve(S):
        votes = defaultdict(Counter)
        segs = []
        for (ci, k), w in seg_word.items():
            d = chains[ci]; L = (d['ticks'][k + 1] - d['ticks'][k]) * S
            n = len(w['chars'])
            if not (1 <= n <= 6) or L <= 0: continue
            segs.append((ci, k, w, L))
            tol = max(8.0, .005 * L)
            for pos, c in enumerate(w['chars']):
                unit = 10 ** (n - 1 - pos)
                lo, hi = int((L - tol) // unit) % 10, int((L + tol) // unit) % 10
                if lo == hi and (L - tol) // unit == (L + tol) // unit:
                    votes[c['cls']][lo] += 1
        mapping = {}
        cand = sorted(((v, cls, dgt) for cls, cnt in votes.items() for dgt, v in cnt.items() if v >= .6 * sum(cnt.values())), reverse=True)
        used = Counter()
        for v, cls, dgt in cand:
            if cls in mapping: continue
            if used[dgt] and v < 3: continue  # 同一个数字分成两类字形的情况少见：票数不够多就不重复分配
            mapping[cls] = dgt; used[dgt] += 1
        # 只差一个不认识的字：取让数值最接近量出长度的那个数字，再回填
        for _ in range(3):
            for ci, k, w, L in segs:
                unk = [c for c in w['chars'] if c['cls'] not in mapping]
                if len(unk) != 1: continue
                best = None
                for dgt in range(10):
                    s = ''.join(str(mapping[c['cls']]) if c['cls'] in mapping else str(dgt) for c in w['chars'])
                    v = int(s); e = abs(v - L)
                    if best is None or e < best[0]: best = (e, dgt)
                if best[0] <= max(12, .008 * L): mapping[unk[0]['cls']] = best[1]
        out, good = {}, 0
        seglen = lambda ci, k: (chains[ci]['ticks'][k + 1] - chains[ci]['ticks'][k]) * S if 0 <= k < len(chains[ci]['ticks']) - 1 else None
        for ci, k, w, L in segs:
            if any(c['cls'] not in mapping for c in w['chars']): continue
            txt = ''.join(str(mapping[c['cls']]) for c in w['chars'])
            v = int(txt)
            ok = abs(v - L) <= max(12, .008 * L)
            if not ok:
                # 相邻两段很短时两个数字会挤成一串（“390120”）：拆成两半，分给这一段和旁边没有数字的那段
                for nb in (k + 1, k - 1):
                    L2 = seglen(ci, nb)
                    if L2 is None or (ci, nb) in seg_word: continue
                    for cut in range(1, len(txt)):
                        a_, b_ = (txt[:cut], txt[cut:]) if nb == k + 1 else (txt[cut:], txt[:cut])
                        if a_.startswith('0') or b_.startswith('0'): continue
                        if abs(int(a_) - L) <= max(12, .008 * L) and abs(int(b_) - L2) <= max(12, .008 * L2):
                            out[(ci, nb)] = dict(value=int(b_), measured=L2, ok=True, text=b_); good += 1
                            v, txt, ok = int(a_), a_, True
                            break
                    if ok: break
            out[(ci, k)] = dict(value=v, measured=L, ok=ok, text=txt)
            good += ok
        return out, good, len(segs), mapping
    best = None
    for S in scale_guesses:
        r = solve(S)
        if best is None or r[1] > best[1][1]: best = (S, r)
    S, (out, good, n, mapping) = best
    if good < max(4, .5 * n): return None
    # 用读出的数字反算比例，再解一遍（量出的长度更准，个位数投票更多）
    ratios = [v['value'] / (chains[ci]['ticks'][k + 1] - chains[ci]['ticks'][k]) for (ci, k), v in out.items() if v['ok'] and v['value'] >= 300]
    if ratios:
        S2 = float(np.median(ratios))
        out, good, n, mapping = solve(S2)
        S = S2
    return dict(values=out, scale=S, good=good, total=n, classes=len(protos), mapping=mapping, vrot=vrot, protos=protos)


def montage(dec, path):
    """字形类别一览（调试用）：每类一格，下面写识别成的数字和出现次数"""
    ps = dec['protos']; n = len(ps); cols = 12; rows = (n + cols - 1) // cols
    img = np.full((rows * (GH + 18), cols * (GW + 8), 3), 255, np.uint8)
    for i, (bm, cnt) in enumerate(ps):
        r, c = divmod(i, cols); y, x = r * (GH + 18), c * (GW + 8)
        img[y:y + GH, x:x + GW][bm > 0] = (0, 0, 0)
        cv2.putText(img, f"{dec['mapping'].get(i, '?')}:{cnt}", (x, y + GH + 13), cv2.FONT_HERSHEY_SIMPLEX, .4, (0, 0, 200), 1)
    cv2.imencode('.png', img)[1].tofile(path)
