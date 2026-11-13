"""
反向对账（原图 → 模型）：原图上画了墙的地方，模型里有没有墙；模型的墙面和原图的墙面差多少毫米。
wallaudit.py 是沿着“已经建了的墙”去原图上数线，漏建的墙它看不到；check 的悬空墙端也查不出“两头都接上了、整段没建”的墙。
这个脚本补上这个方向，给一个一致度分数 + 每处问题一张放大图。

查三样：
  1. 漏墙：原图的墙（实心墙块，或描边墙的长直线）没有落在任何建模的墙 / 柱里 → 列出 ≥ --min-len 的块
  2. 墙面偏位：逐面墙每 100mm 横切原图量两个墙面，中线偏差 > --face-tol 或墙厚差 > 40mm 的列出（中位数，不怕局部遮挡）
  3. 一致度：原图墙像素被模型覆盖的比例（实心图按墙块、描边图按墙线）
自动判断实心 / 描边画法（--mode 指定）。家具外框、门扇扫过的范围、spec 里的 exclude 区域、模型外 1.5m 以外（指北针、logo、图例）都不算。

用法:
  python coverage.py spec.json --out <工作目录>/coverage                  # 每层 underlay 底图（建议先 rectify.py 拉正，底图对得准）
  可选：--floor 1  --mode solid|outlined  --tol 40  --min-len 300  --face-tol 30  --no-mask
spec 里不参与对账的区域（公共区不还原、图例压在户型里）：
  "exclude": [{"rect": [x0, y0, x1, y1], "why": "电梯厅不还原"}]      // 写在顶层或每层 floors[i] 里，mm
输出: coverage.json、coverage_<层>.png（淡色原图 + 蓝 = 模型墙 + 红 = 漏的 + 橙框 = 偏位的墙）、sheet_<层>.png（每处放大）
交付门槛：一致度 ≥ 98%、漏墙 0、偏位 0；改不掉的（原图自相矛盾、按标注建的）在交付说明里逐条写。
"""
import argparse, json, math, os, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont
from imgio import open_upright
sys.stdout.reconfigure(encoding='utf-8')

ap = argparse.ArgumentParser()
ap.add_argument('spec'); ap.add_argument('--out', required=True)
ap.add_argument('--floor', type=int); ap.add_argument('--mode', choices=['auto', 'solid', 'outlined'], default='auto')
ap.add_argument('--tol', type=float, default=40, help='模型墙带外扩多少 mm 还算覆盖')
ap.add_argument('--min-len', type=float, default=300); ap.add_argument('--face-tol', type=float, default=30)
ap.add_argument('--gray-max', type=int, default=175); ap.add_argument('--sat-max', type=int, default=22)
ap.add_argument('--no-mask', action='store_true')
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
spec = json.load(open(a.spec, encoding='utf-8'))
floors = spec['floors'] if 'floors' in spec else [spec]
base = os.path.dirname(os.path.abspath(a.spec))
here = os.path.dirname(os.path.abspath(__file__))
try: SIZES = json.load(open(os.path.join(here, '..', 'reference', 'catalog-sizes.json'), encoding='utf-8'))
except Exception: SIZES = {}
try: FONT = ImageFont.truetype('msyh.ttc', 15)
except Exception:
    try: FONT = ImageFont.truetype('NotoSansCJK-Regular.ttc', 15)
    except Exception: FONT = ImageFont.load_default()
NOMASK = {'rug', 'rugRound', 'roundRug', 'ceilingLight', 'downlight', 'chandelier', 'pendant', 'curtain', 'sheer', 'lawn', 'paving', 'stepStones', 'stepStone', 'floorHeat'}
DOORS = {'door', 'double', 'unequal', 'entry', 'mother'}


def rect_poly(cx, cy, w, d, rot):
    r = math.radians(rot or 0); c, s = math.cos(r), math.sin(r)
    return [(cx + x * c - y * s, cy + x * s + y * c) for x, y in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))]


def wall_frame(w):
    (ax, ay), (bx, by) = w['a'], w['b']; L = math.hypot(bx - ax, by - ay) or 1
    u = ((bx - ax) / L, (by - ay) / L); return (ax, ay), u, (-u[1], u[0]), L


def along(w, v):
    """洞口 from / to → 到 a 点的距离（水平墙填的是 x 坐标、竖直墙是 y 坐标、斜墙才是距离）"""
    (ax, ay), u, _, _ = wall_frame(w)
    if abs(u[1]) < 1e-6: return (v - ax) / u[0]
    if abs(u[0]) < 1e-6: return (v - ay) / u[1]
    return v


def op_span(w, o):
    return sorted((along(w, o['from']), along(w, o['to'])))


def dirword(nrm, v):
    dx, dy = nrm[0] * v, nrm[1] * v
    return ('右侧（x+）' if dx > 0 else '左侧（x-）') if abs(dx) >= abs(dy) else ('下方（y+）' if dy > 0 else '上方（y-）')


def run_floor(fi, fl, ul_over=None):
    ul = ul_over or fl.get('underlay') or spec.get('underlay')
    fname = fl.get('name') or f'{fi}层'
    if not ul: print(f'{fname}：没有 underlay，跳过'); return None
    p = ul['image'] if os.path.isabs(ul['image']) else os.path.join(base, ul['image'])
    rgb = np.array(open_upright(p, rotate=ul.get('rotate', 0))).astype(np.int16)
    dark_bg = bool(np.median(rgb.max(2)) < 90)
    if dark_bg: rgb = 255 - rgb
    H, W = rgb.shape[:2]; S = ul['mmPerPx']; OX, OY = ul['x'], ul['y']
    P = lambda x, y: ((x - OX) / S, (y - OY) / S)
    Pi = lambda pts: np.array([[int(round(v)) for v in P(x, y)] for x, y in pts], np.int32)
    mx, mn = rgb.max(2), rgb.min(2)
    ink = ((mx - mn < a.sat_max) & (mx < a.gray_max)).astype(np.uint8)
    k = max(3, int(round(80 / S)))
    solid = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    thin = ((mx - mn < 40) & (mx < 150)).astype(np.uint8)
    if dark_bg:
        # 黑底 CAD 截图：墙线是彩色细线，反相后颜色不对；所有比底色亮的线都算线（文字、尺寸线在户型外、按双线带过滤）
        thin = ((255 - mn) > 110).astype(np.uint8); ink = np.zeros_like(ink); solid = np.zeros_like(solid)
    walls = fl.get('walls', [])
    if not walls: return None
    # 模型：墙带（含门窗洞口，洞口处原图画的是窗线 / 门框，也算墙线）、柱 / 结构
    band = np.zeros((H, W), np.uint8)
    for w in walls:
        (ax, ay), u, n, L = wall_frame(w); h = w.get('t', 120) / 2
        pts = [(ax - u[0] * h + n[0] * h, ay - u[1] * h + n[1] * h), (ax + u[0] * (L + h) + n[0] * h, ay + u[1] * (L + h) + n[1] * h),
               (ax + u[0] * (L + h) - n[0] * h, ay + u[1] * (L + h) - n[1] * h), (ax - u[0] * h - n[0] * h, ay - u[1] * h - n[1] * h)]
        cv2.fillPoly(band, [Pi(pts)], 1)
    for s in fl.get('structs', []):
        if 'at' in s: cv2.fillPoly(band, [Pi(rect_poly(s['at'][0], s['at'][1], s.get('w', 400), s.get('d', 400), s.get('rot', 0)))], 1)
    tol = max(2, int(round(a.tol / S)))
    cover = cv2.dilate(band, np.ones((2 * tol + 1, 2 * tol + 1), np.uint8))
    # 不算的地方：家具外框、门扇扫过的范围、exclude、模型外 1.5m 以外
    ign = np.zeros((H, W), np.uint8)
    if not a.no_mask:
        for f in fl.get('furniture', []):
            key = f.get('key', '')
            if key in NOMASK or 'at' not in f: continue
            dw, dd = (SIZES.get(key) or [600, 600])[:2]
            cv2.fillPoly(ign, [Pi(rect_poly(f['at'][0], f['at'][1], f.get('w', dw) + 80, f.get('d', dd) + 80, f.get('rot', 0)))], 1)
    for w in walls:
        (ax, ay), u, n, L = wall_frame(w); h = w.get('t', 120) / 2
        for o in w.get('openings', []):
            if o.get('type') not in DOORS: continue
            s0, s1 = op_span(w, o); ww = s1 - s0
            # 门扇那条线画在门轴一端、门洞边外几十毫米：两头各放宽 100
            s0, s1 = s0 - 100, s1 + 100
            for sg in (1, -1):
                q = [(ax + u[0] * s0 + n[0] * sg * h, ay + u[1] * s0 + n[1] * sg * h), (ax + u[0] * s1 + n[0] * sg * h, ay + u[1] * s1 + n[1] * sg * h),
                     (ax + u[0] * s1 + n[0] * sg * (h + ww + 60), ay + u[1] * s1 + n[1] * sg * (h + ww + 60)), (ax + u[0] * s0 + n[0] * sg * (h + ww + 60), ay + u[1] * s0 + n[1] * sg * (h + ww + 60))]
                cv2.fillPoly(ign, [Pi(q)], 1)
    for e in (spec.get('exclude') or []) + (fl.get('exclude') or []) if 'floors' in spec else (spec.get('exclude') or []):
        r = e['rect'] if isinstance(e, dict) else e
        (x0, y0), (x1, y1) = P(min(r[0], r[2]), min(r[1], r[3])), P(max(r[0], r[2]), max(r[1], r[3]))
        ign[max(0, int(y0)):max(0, int(y1)) + 1, max(0, int(x0)):max(0, int(x1)) + 1] = 1
    ys, xs = np.nonzero(band)
    pad = int(round(1500 / S)); region = np.zeros((H, W), np.uint8)
    region[max(0, ys.min() - pad):ys.max() + pad + 1, max(0, xs.min() - pad):xs.max() + pad + 1] = 1
    valid = (region > 0) & (ign == 0)
    # 实心 / 描边：模型墙带里有多少是实心墨
    sr = float((solid & band).sum()) / max(1, band.sum())
    mode = a.mode if a.mode != 'auto' else ('solid' if sr >= .3 else 'outlined')
    if mode == 'solid':
        src = solid
    else:
        # 描边墙 = 相距 60~300mm 的两条平行线：垂直方向闭运算把双线填成带，再去掉单线、短线（同 analyze --outlined）
        tmax, tmin, Lmin = int(round(300 / S)) + 2, max(2, int(round(60 / S))), max(10, int(round(600 / S)))
        hb = cv2.morphologyEx(thin, cv2.MORPH_CLOSE, np.ones((tmax, 1), np.uint8))
        hb = cv2.morphologyEx(cv2.morphologyEx(hb, cv2.MORPH_OPEN, np.ones((tmin, 1), np.uint8)), cv2.MORPH_OPEN, np.ones((1, Lmin), np.uint8))
        vb = cv2.morphologyEx(thin, cv2.MORPH_CLOSE, np.ones((1, tmax), np.uint8))
        vb = cv2.morphologyEx(cv2.morphologyEx(vb, cv2.MORPH_OPEN, np.ones((1, tmin), np.uint8)), cv2.MORPH_OPEN, np.ones((Lmin, 1), np.uint8))
        src = (hb | vb) | solid
        # 尺寸线、图框在户型外面：描边图只看模型外轮廓以内（外扩 300mm）
        cs, _ = cv2.findContours(band, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        hull = np.zeros((H, W), np.uint8); cv2.fillPoly(hull, cs, 1)
        cs2, _ = cv2.findContours(cv2.morphologyEx(hull, cv2.MORPH_CLOSE, np.ones((int(1500 / S) | 1,) * 2, np.uint8)), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.fillPoly(hull, cs2, 1)
        valid = valid & (cv2.dilate(hull, np.ones((2 * int(300 / S) + 1,) * 2, np.uint8)) > 0)
    src_all = src.astype(bool)
    src = src_all & valid
    miss = src & (cover == 0)
    score = 1 - miss.sum() / max(1, src.sum())
    if ul_over is not None: return {'score': round(float(score), 4)}
    # 底图配准：一致度低时，先看是不是底图本身没对齐（比例 / 偏移不对），是的话逐面对账没有意义
    fitted = None
    if ul_over is None and score < .95:
        z = min(1.0, 1000 / max(H, W))
        full = (src_all | solid).astype(np.float32)
        def ecc(warp):
            for sig in (12, 5, 2):
                A = cv2.GaussianBlur(cv2.resize(band.astype(np.float32), None, fx=z, fy=z), (0, 0), sig)
                B = cv2.GaussianBlur(cv2.resize(full, None, fx=z, fy=z), (0, 0), sig)
                _, warp = cv2.findTransformECC(A, B, warp, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6), None, 5)
            return warp
        inits = [np.eye(2, 3, dtype=np.float32)]
        # 按外轮廓粗配：模型墙带的范围 ↔ 原图墙的范围（去掉 1% 离群）
        yy, xx = np.nonzero(full > 0)
        if len(xx) > 100:
            ix0, ix1 = np.percentile(xx, [1, 99]); iy0, iy1 = np.percentile(yy, [1, 99])
            mx0, mx1, my0, my1 = xs.min(), xs.max(), ys.min(), ys.max()
            kx, ky = (ix1 - ix0) / max(1, mx1 - mx0), (iy1 - iy0) / max(1, my1 - my0)
            inits.append(np.array([[kx, 0, (ix0 - kx * mx0) * z], [0, ky, (iy0 - ky * my0) * z]], np.float32))
        best = None
        for w0 in inits:
            try: warp = ecc(w0.copy())
            except cv2.error as e:
                if os.environ.get('COV_DEBUG'): print('ECC 失败', e)
                continue
            if os.environ.get('COV_DEBUG'): print('ECC', warp.tolist())
            sx, sy = float(warp[0, 0]), float(warp[1, 1]); tx, ty = float(warp[0, 2]) / z, float(warp[1, 2]) / z
            if not (abs(warp[0, 1]) < .03 and abs(warp[1, 0]) < .03 and .5 < sx < 2 and .5 < sy < 2): continue
            S2x, S2y = S / sx, S / sy
            nu = dict(ul, mmPerPx=round((S2x + S2y) / 2, 4), x=round(OX - tx * S2x), y=round(OY - ty * S2y))
            r2 = run_floor(fi, fl, nu)
            if os.environ.get('COV_DEBUG'): print('→', nu, r2)
            if r2 and r2['score'] > score + .03 and (best is None or r2['score'] > best['score']):
                best = {'underlay': {k: nu[k] for k in ('mmPerPx', 'x', 'y')}, 'score': r2['score'], 'xy_scale_ratio': round(sx / sy, 4)}
        fitted = best
    # 漏的块
    mk = cv2.morphologyEx(miss.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(mk, 8)
    misses = []
    for i in range(1, n):
        x, y, w_, h_, area = st[i]
        Lm, Tm = max(w_, h_) * S, min(w_, h_) * S
        if Lm < a.min_len or Tm < 50: continue
        # 描边图：墙是细长的带；方块（家具双线框、洁具）不算
        if mode == 'outlined' and (Tm > 400 or Lm < 2.5 * Tm): continue
        cx, cy = OX + (x + w_ / 2) * S, OY + (y + h_ / 2) * S
        misses.append({'at': [round(cx), round(cy)], 'len': round(Lm), 'thick': round(Tm), 'dir': 'h' if w_ >= h_ else 'v',
                       'bbox_mm': [round(OX + x * S), round(OY + y * S), round(OX + (x + w_) * S), round(OY + (y + h_) * S)], 'bbox_px': [int(x), int(y), int(x + w_), int(y + h_)]})
    misses.sort(key=lambda m: -m['len'])
    # 墙面偏位：横切量墙面
    offs, meas = [], []
    ignm = ign > 0
    for wi, w in enumerate(walls):
        (ax, ay), u, nrm, L = wall_frame(w); t = w.get('t', 120)
        if L < 600: continue
        spans = [op_span(w, o) for o in w.get('openings', [])]
        cen, thk = [], []
        ks = np.arange(-t / 2 - 150, t / 2 + 150 + 1e-6, max(S / 2, 3))
        for sd in np.arange(150, L - 150, 100):
            if any(s0 - 60 <= sd <= s1 + 60 for s0, s1 in spans): continue
            bx, by = ax + u[0] * sd, ay + u[1] * sd
            pts = [P(bx + nrm[0] * kk, by + nrm[1] * kk) for kk in ks]
            ix = np.array([int(round(q[0])) for q in pts]); iy = np.array([int(round(q[1])) for q in pts])
            ok = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
            if not ok.all(): continue
            if ignm[iy, ix].any(): continue
            sv = solid[iy, ix] > 0
            got = None
            if sv.any():
                # 离中线最近的一段实心
                idx = np.nonzero(sv)[0]; c = idx[np.argmin(np.abs(ks[idx]))]
                lo = c
                while lo > 0 and sv[lo - 1]: lo -= 1
                hi = c
                while hi < len(sv) - 1 and sv[hi + 1]: hi += 1
                e1, e2 = ks[lo], ks[hi]
                if 40 <= e2 - e1 <= t + 200 and lo > 0 and hi < len(sv) - 1: got = (e1, e2)
            if got is None:
                tv = thin[iy, ix] > 0
                if tv.any():
                    idx = np.nonzero(tv)[0]; cl = []
                    for i in idx:
                        if cl and i - cl[-1][-1] <= 2: cl[-1].append(i)
                        else: cl.append([i])
                    cs = [float(np.mean(ks[c])) for c in cl]
                    f1 = min(cs, key=lambda v: abs(v + t / 2)); f2 = min(cs, key=lambda v: abs(v - t / 2))
                    if f1 < f2 and abs(f1 + t / 2) <= 100 and abs(f2 - t / 2) <= 100: got = (f1, f2)
            if got: cen.append((got[0] + got[1]) / 2); thk.append(got[1] - got[0])
        nsamp = max(1, int((L - 300) / 100))
        if len(cen) < max(3, .4 * nsamp): continue
        mc, mt = float(np.median(cen)), float(np.median(thk))
        # 偏移换成世界坐标（x 向 / y 向），后面估底图整体偏移
        meas.append((wi, w, nrm, t, mc, mt, len(cen), nrm[0] * mc, nrm[1] * mc, abs(nrm[0]) > abs(nrm[1])))
    # 底图整体偏移：竖墙的 x 偏移、横墙的 y 偏移各取中位数（底图 x / y 差一两个像素就会让一串墙都“偏位”）
    gx = float(np.median([m[7] for m in meas if m[9]])) if sum(m[9] for m in meas) >= 3 else 0.0
    gy = float(np.median([m[8] for m in meas if not m[9]])) if sum(not m[9] for m in meas) >= 3 else 0.0
    if abs(gx) < 12: gx = 0.0
    if abs(gy) < 12: gy = 0.0
    for wi, w, nrm, t, mc, mt, ns, dx, dy, vert in meas:
        rc = mc - (nrm[0] * gx + nrm[1] * gy)
        if abs(rc) > a.face_tol or abs(mt - t) > max(40, a.face_tol + 10):
            offs.append({'wall': wi, 'a': w['a'], 'b': w['b'], 't': t, 'shift': round(rc), 'drawn_t': round(mt), 'samples': ns,
                         'hint': (f'原图墙中线在模型{dirword(nrm, rc)} {abs(rc):.0f}mm' if abs(rc) > a.face_tol else '') +
                                 (f'{"，" if abs(rc) > a.face_tol else ""}图上墙厚约 {mt:.0f}（建模 {t}）' if abs(mt - t) > max(40, a.face_tol + 10) else '')})
    # 出图
    vis = (rgb * .45 + 255 * .55).astype(np.uint8)
    vis[band > 0] = (vis[band > 0] * .55 + np.array([60, 130, 255]) * .45).astype(np.uint8)
    vis[ignm & (region > 0)] = (vis[ignm & (region > 0)] * .85 + np.array([200, 200, 200]) * .15).astype(np.uint8)
    vis[miss] = (230, 30, 30)
    im = Image.fromarray(vis); d = ImageDraw.Draw(im)
    for i, m in enumerate(misses):
        x0, y0, x1, y1 = m['bbox_px']; d.rectangle([x0 - 5, y0 - 5, x1 + 5, y1 + 5], outline=(230, 0, 0), width=2); d.text((x1 + 6, y0 - 4), f'M{i}', fill=(230, 0, 0), font=FONT)
    for o in offs:
        (x0, y0), (x1, y1) = P(*o['a']), P(*o['b']); hh = o['t'] / S / 2 + 6
        d.rectangle([min(x0, x1) - hh, min(y0, y1) - hh, max(x0, x1) + hh, max(y0, y1) + hh], outline=(255, 140, 0), width=2)
        d.text((min(x0, x1), min(y0, y1) - hh - 18), f'W{o["wall"]} {o["shift"]:+d}', fill=(220, 110, 0), font=FONT)
    im.save(os.path.join(a.out, f'coverage_{fi}.png'))
    tiles = []
    items = [('M', i, m['bbox_mm'], f'M{i} 漏 {m["len"]}mm') for i, m in enumerate(misses)] + \
            [('W', o['wall'], [min(o['a'][0], o['b'][0]), min(o['a'][1], o['b'][1]), max(o['a'][0], o['b'][0]), max(o['a'][1], o['b'][1])], f'W{o["wall"]} {o["hint"]}') for o in offs]
    for _, _, bb, title in items[:40]:
        cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2; span = min(max(bb[2] - bb[0], bb[3] - bb[1]) + 1500, 6000)
        X0, Y0 = P(cx - span / 2, cy - span / 2); X1, Y1 = P(cx + span / 2, cy + span / 2)
        crop = im.crop((int(X0), int(Y0), int(X1), int(Y1))).resize((360, 360)); dd = ImageDraw.Draw(crop, 'RGBA')
        dd.rectangle([0, 0, 360, 22], fill=(0, 0, 0, 170)); dd.text((4, 2), title[:30], fill=(255, 230, 0), font=FONT); tiles.append(crop)
    if tiles:
        cols = 4; sheet = Image.new('RGB', (cols * 364, ((len(tiles) + cols - 1) // cols) * 364), (255, 255, 255))
        for i, tl in enumerate(tiles): sheet.paste(tl, ((i % cols) * 364, (i // cols) * 364))
        sheet.save(os.path.join(a.out, f'sheet_{fi}.png'))
    return {'floor': fname, 'mode': mode, 'solid_ratio': round(sr, 3), 'score': round(float(score), 4), 'misses': misses, 'offsets': offs, 'underlay_fit': fitted, 'underlay_shift': [round(gx), round(gy)]}


res = []
for fi, fl in enumerate(floors):
    if a.floor is not None and fi != a.floor: continue
    r = run_floor(fi, fl)
    if r: res.append(r)
json.dump(res, open(os.path.join(a.out, 'coverage.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
bad = 0
for r in res:
    good = r['score'] >= .98 and not r['misses'] and not r['offsets']; bad += not good
    print(f"===== {r['floor']}（{'实心墙' if r['mode'] == 'solid' else '描边墙'}画法）：一致度 {r['score']:.1%}，漏墙 {len(r['misses'])} 处，墙面偏位 {len(r['offsets'])} 面  {'✓' if good else '✗'}")
    if r.get('underlay_fit'):
        f = r['underlay_fit']
        print(f"  ⚠ 底图没对齐：改成 underlay {json.dumps(f['underlay'])} 后一致度 {f['score']:.1%}"
              + (f"；横竖比例差 {abs(f['xy_scale_ratio'] - 1):.1%}（图被拉伸 / 拍照透视 → 用 rectify.py 拉正）" if abs(f['xy_scale_ratio'] - 1) > .01 else '')
              + "。先把底图对齐（或墙整体按标注重建）再看下面的逐项")
    if any(r.get('underlay_shift') or []):
        sx_, sy_ = r['underlay_shift']
        print(f"  底图整体比模型偏 x {sx_:+d}、y {sy_:+d} mm（墙中位数）：下面的偏位已扣掉；要叠图更准就把 underlay 的 x / y 各减这么多（或用 rectify.py）")
    for i, m in enumerate(r['misses']):
        print(f"  M{i} 漏：{'横' if m['dir'] == 'h' else '竖'}向 长 {m['len']} 厚 {m['thick']}，范围 x {m['bbox_mm'][0]}~{m['bbox_mm'][2]}  y {m['bbox_mm'][1]}~{m['bbox_mm'][3]}")
    for o in r['offsets']:
        print(f"  W{o['wall']} {o['a']}→{o['b']} t={o['t']}：{o['hint']}（{o['samples']} 个切面的中位数）")
print(f'\n门槛：一致度 ≥ 98%、漏墙 0、偏位 0。看 coverage_*.png / sheet_*.png：红 = 原图有墙、模型没有；橙框 = 墙面和原图差太多。'
      f'\n公共区不还原、图例压在户型里：spec 写 exclude；原图自相矛盾（按标注建的）交付时逐条说明。')
sys.exit(1 if bad else 0)
