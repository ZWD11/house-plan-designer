"""
把户型图“拉正”成每像素固定毫米数的图：去掉拍照透视、扫描歪斜、户型图本身画得不均匀（分段比例不一样），
之后 analyze / wallfit / wallaudit / coverage / 底图 全用拉正后的图，像素 → 毫米只是一个比例加原点，和 spec 坐标严格对齐。

做法：尺寸线刻度（像素）+ 标注数字（毫米）→ 最小二乘拟合单应矩阵（透视），再按每个刻度的残差做分段线性修正
（同 axismap 的分段定位），最后重采样。刻度少的方向自动退回仿射 / 相似变换。

用法:
  python rectify.py 图.jpg --deskew --out <工作目录>/rect                     # 没读尺寸前：只按长直线把小角度歪斜转正
  python rectify.py 图.jpg --chains chains.json --out <工作目录>/rect          # 按尺寸链拉正（推荐）
  可选：--mpp 10（输出每像素毫米，默认按原图分辨率；墙太细时自动放大 2 倍）  --model homography|affine|similarity
        --no-piecewise（不做分段修正，只用整体透视）  --margin 1500（四周留白 mm）

chains.json（毫米坐标系由你定：一般原点 = 外墙左上角外皮，x 向右、y 向下，和 spec 一致）:
{
  "ticks": "ticks/ticks.json",                      // 可选：dimticks.py 的输出，下面用 "line": 编号 直接取刻度
  "chains": [
    {"axis": "x", "line": 0, "segs": [3100, 3100, 2100, 4100, 2300], "start": 0},
    {"axis": "x", "line": 5, "use": [0, 1, 3, 4, 6], "segs": [...], "start": 0},     // use：只用这几个刻度（跳过误检）
    {"axis": "y", "p0": [128, 245], "p1": [145, 929], "ticks": [245, 401.7, 929], "segs": [2500, 8925], "start": 0}
    // 手写：axis=x 时 ticks 是 x 像素，线上每点的 y 由 p0 → p1 插值（照片里尺寸线是斜的）；不写 p0/p1 时用 "at": 线的像素位置
  ],
  "points": [{"px": [242, 143.8], "mm": [0, 0]}]    // 可选：已知点（外墙角），两个坐标都约束
}
同一方向至少 2 条尺寸链才能拟合透视；拍照的图四周的尺寸链都写上最准。

输出: rectified.png、rectify.json（模型、残差、mpp、origin_mm）、check.png（拉正图上画出每个刻度应在的位置，红 = 残差 > 30mm）
屏幕最后打印 underlay 片段，直接贴进 spec。生成脚本里要把原图像素换成毫米：
    from rectify import Rectified; R = Rectified('<工作目录>/rect/rectify.json'); X, Y = R.mm(px, py)
"""
import argparse, json, math, os, sys
import numpy as np, cv2
from PIL import Image, ImageDraw
from imgio import open_upright
sys.stdout.reconfigure(encoding='utf-8')


def apply_h(H, pts):
    pts = np.asarray(pts, float).reshape(-1, 2)
    q = np.c_[pts, np.ones(len(pts))] @ np.asarray(H).T
    return q[:, :2] / q[:, 2:3]


class Piece:
    """单调分段线性映射（外推按两端斜率），可求逆"""
    def __init__(self, src, dst):
        o = np.argsort(src); s, d = np.asarray(src, float)[o], np.asarray(dst, float)[o]
        keep = np.r_[True, np.diff(s) > 1e-6]; self.s, self.d = s[keep], d[keep]

    @staticmethod
    def _f(x, a, b):
        x = np.asarray(x, float)
        if len(a) < 2: return x + (b[0] - a[0] if len(a) else 0)
        y = np.interp(x, a, b)
        k0 = (b[1] - b[0]) / (a[1] - a[0]); k1 = (b[-1] - b[-2]) / (a[-1] - a[-2])
        return np.where(x < a[0], b[0] + (x - a[0]) * k0, np.where(x > a[-1], b[-1] + (x - a[-1]) * k1, y))

    def __call__(self, x): return self._f(x, self.s, self.d)
    def inv(self, y): return self._f(y, self.d, self.s)


class Rectified:
    """读 rectify.json：原图像素 ↔ 毫米 ↔ 拉正图像素"""
    def __init__(self, path):
        j = json.load(open(path, encoding='utf-8')); self.j = j
        self.H = np.array(j['H']); self.Hi = np.linalg.inv(self.H)
        self.cx = Piece(*j['corr']['x']) if j.get('corr') else None
        self.cy = Piece(*j['corr']['y']) if j.get('corr') else None
        self.mpp = j['mpp']; self.ox, self.oy = j['origin_mm']

    def mm(self, px, py):
        """原图像素 → 毫米（spec 坐标）"""
        X, Y = apply_h(self.H, [[px, py]])[0]
        if self.cx: X, Y = float(self.cx(X)), float(self.cy(Y))
        return float(X), float(Y)

    def px(self, X, Y):
        """毫米 → 原图像素"""
        if self.cx: X, Y = float(self.cx.inv(X)), float(self.cy.inv(Y))
        return tuple(apply_h(self.Hi, [[X, Y]])[0])

    def rpx(self, X, Y):
        """毫米 → 拉正图像素"""
        return ((X - self.ox) / self.mpp, (Y - self.oy) / self.mpp)


def load_obs(cfg, base):
    """→ [(px, py, 坐标轴 0/1 或 2=两个都约束, mm 值 或 (X, Y), 链编号, 标签)]"""
    tl = None
    if cfg.get('ticks'):
        tp = cfg['ticks'] if os.path.isabs(cfg['ticks']) else os.path.join(base, cfg['ticks'])
        tl = json.load(open(tp, encoding='utf-8'))['lines']
    obs = []
    for ci, c in enumerate(cfg.get('chains', [])):
        ax = 0 if c['axis'].lower() == 'x' else 1
        if 'line' in c:
            if tl is None: sys.exit('chains 里用了 "line"，要先写 "ticks": dimticks.py 的 ticks.json')
            ln = tl[c['line']]
            if (ln['orient'] == 'h') != (ax == 0): sys.exit(f'链 {ci}：line {c["line"]} 是 {ln["orient"]} 方向，和 axis={c["axis"]} 不符')
            ticks = ln['ticks']; at = ln['at']; p0 = p1 = None
        else:
            ticks = c['ticks']; at = c.get('at'); p0, p1 = c.get('p0'), c.get('p1')
        if c.get('use') is not None: ticks = [ticks[i] for i in c['use']]
        segs = c['segs']
        if len(segs) != len(ticks) - 1: sys.exit(f'链 {ci}：{len(ticks)} 个刻度要配 {len(ticks) - 1} 段尺寸，给了 {len(segs)} 段')
        acc = float(c.get('start', 0)); vals = [acc]
        for s in segs: acc += s; vals.append(acc)
        for t, m in zip(ticks, vals):
            if p0 and p1:
                k = (t - p0[ax]) / ((p1[ax] - p0[ax]) or 1); o = p0[1 - ax] + (p1[1 - ax] - p0[1 - ax]) * k
            elif at is not None: o = at
            else: sys.exit(f'链 {ci}：要写 p0/p1 或 at（尺寸线的像素位置）')
            pt = (t, o) if ax == 0 else (o, t)
            obs.append((pt[0], pt[1], ax, m, ci, f'链{ci}:{m:.0f}'))
    for p in cfg.get('points', []):
        obs.append((p['px'][0], p['px'][1], 2, tuple(p['mm']), -1, f'点{p["mm"]}'))
    return obs


def fit(obs, nchain, model):
    from scipy.optimize import least_squares
    P = np.array([[o[0], o[1]] for o in obs])
    # 初值：两个方向各自线性回归出比例和偏移
    init = []
    for ax in (0, 1):
        sel = [(o[ax], o[3]) for o in obs if o[2] == ax] + [(o[ax], o[3][ax]) for o in obs if o[2] == 2]
        if len(sel) < 2: sys.exit(f'{"xy"[ax]} 方向至少要 2 个刻度')
        a = np.array(sel); k, b = np.polyfit(a[:, 0], a[:, 1], 1); init.append((k, b))
    s0 = (abs(init[0][0]) + abs(init[1][0])) / 2
    # 每条链有一个未知量：这条尺寸线在另一个方向上的毫米位置
    off0 = np.zeros(nchain)
    for ci in range(nchain):
        pts = [o for o in obs if o[4] == ci]
        if pts: ax = pts[0][2]; off0[ci] = np.mean([init[1 - ax][0] * o[1 - ax] + init[1 - ax][1] for o in pts])

    def H_of(p):
        if model == 'similarity': c, s, tx, ty = p[:4]; return np.array([[c, -s, tx], [s, c, ty], [0, 0, 1]])
        if model == 'affine': return np.array([[p[0], p[1], p[2]], [p[3], p[4], p[5]], [0, 0, 1]])
        return np.array([[p[0], p[1], p[2]], [p[3], p[4], p[5]], [p[6], p[7], 1]])
    nH = {'similarity': 4, 'affine': 6, 'homography': 8}[model]
    if model == 'similarity': p0 = [s0, 0, init[0][1], init[1][1]]
    else:
        p0 = [init[0][0], 0, init[0][1], 0, init[1][0], init[1][1]] + ([0, 0] if model == 'homography' else [])
    p0 = np.r_[p0, off0]

    def resid(p):
        H = H_of(p[:nH]); q = apply_h(H, P); r = []
        for (X, Y), o in zip(q, obs):
            if o[2] == 2: r += [X - o[3][0], Y - o[3][1]]
            else:
                v = (X, Y); r += [v[o[2]] - o[3], 0.3 * (v[1 - o[2]] - p[nH + o[4]])]
        return np.array(r)
    sol = least_squares(resid, p0, x_scale='jac', loss='soft_l1', f_scale=20)
    return H_of(sol.x[:nH])


def native_mpp(H, W, Hh):
    """原图中心一个像素对应多少毫米"""
    c = apply_h(H, [[W / 2, Hh / 2], [W / 2 + 1, Hh / 2], [W / 2, Hh / 2 + 1]])
    return float((np.linalg.norm(c[1] - c[0]) + np.linalg.norm(c[2] - c[0])) / 2)


def deskew_angle(gray):
    """长直线的主方向（度）：户型图的墙、尺寸线绝大多数横平竖直"""
    e = cv2.Canny(gray, 60, 160)
    L = cv2.HoughLinesP(e, 1, np.pi / 720, threshold=80, minLineLength=max(40, min(gray.shape) // 8), maxLineGap=4)
    if L is None: return 0.0
    ang, wt = [], []
    for x0, y0, x1, y1 in L[:, 0]:
        a = math.degrees(math.atan2(y1 - y0, x1 - x0)); a = (a + 45) % 90 - 45
        ang.append(a); wt.append(math.hypot(x1 - x0, y1 - y0))
    ang, wt = np.array(ang), np.array(wt)
    m = np.median(ang); sel = np.abs(ang - m) < 1.5
    return float(np.average(ang[sel], weights=wt[sel])) if sel.any() else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image'); ap.add_argument('--out', required=True)
    ap.add_argument('--chains'); ap.add_argument('--deskew', action='store_true')
    ap.add_argument('--mpp', type=float); ap.add_argument('--model', choices=['auto', 'homography', 'affine', 'similarity'], default='auto')
    ap.add_argument('--no-piecewise', action='store_true'); ap.add_argument('--margin', type=float, default=1500)
    ap.add_argument('--rotate', type=int, default=0, help='先顺时针转多少度（同 underlay.rotate）')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    img = np.array(open_upright(a.image, rotate=a.rotate)); h0, w0 = img.shape[:2]
    report = {'image': os.path.abspath(a.image)}
    corr = None; obs = []
    if a.chains:
        cfg = json.load(open(a.chains, encoding='utf-8'))
        obs = load_obs(cfg, os.path.dirname(os.path.abspath(a.chains)))
        nchain = len(cfg.get('chains', []))
        per = [len({o[4] for o in obs if o[2] == ax}) + (1 if any(o[2] == 2 for o in obs) else 0) for ax in (0, 1)]
        model = a.model if a.model != 'auto' else ('homography' if min(per) >= 2 else 'affine')
        H = fit(obs, nchain, model)
        # 分段修正：整体透视之后每个刻度还剩的偏差（图本身画得不均匀）按 axismap 的方式逐段消掉
        res = {0: [], 1: []}
        for o in obs:
            X, Y = apply_h(H, [[o[0], o[1]]])[0]
            if o[2] == 2: res[0].append((X, o[3][0])); res[1].append((Y, o[3][1]))
            else: res[o[2]].append(((X, Y)[o[2]], o[3]))
        if not a.no_piecewise:
            def merged(lst):
                # 同一毫米值（几条链共用的刻度）合并成一个点，取平均
                d = {}
                for got, want in lst: d.setdefault(round(want), []).append(got)
                return [float(np.mean(v)) for v in d.values()], [float(k) for k in d.keys()]
            gx, wx = merged(res[0]); gy, wy = merged(res[1])
            corr = {'x': [gx, wx], 'y': [gy, wy]}
        cx = Piece(*corr['x']) if corr else (lambda v: v); cy = Piece(*corr['y']) if corr else (lambda v: v)
        # 残差：整体模型的（说明透视 / 比例拟合得好不好）和每个刻度读数是否可疑
        rows = []
        for o in obs:
            X, Y = apply_h(H, [[o[0], o[1]]])[0]
            if o[2] == 2: e = math.hypot(X - o[3][0], Y - o[3][1])
            else: e = (X, Y)[o[2]] - o[3]
            rows.append({'label': o[5], 'px': [round(o[0], 1), round(o[1], 1)], 'err_mm': round(float(e), 1)})
        errs = np.array([abs(r['err_mm']) for r in rows])
        report.update(model=model, rms_mm=round(float(np.sqrt((errs ** 2).mean())), 1), max_mm=round(float(errs.max()), 1), ticks=rows)
        print(f'模型 {model}：{len(obs)} 个刻度，整体拟合残差 rms {report["rms_mm"]}mm、最大 {report["max_mm"]}mm'
              + ('（之后按刻度分段修正到 0）' if corr else ''))
        bad = [r for r in rows if abs(r['err_mm']) > 60]
        for r in bad: print(f'  ✗ {r["label"]} 像素 {r["px"]} 偏 {r["err_mm"]:+.0f}mm —— 偏这么多多半是数字读错 / 刻度配错，先核对再用')
        report['suspect'] = bad
    else:
        if not a.deskew: sys.exit('要么给 --chains，要么 --deskew')
        g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        ang = deskew_angle(g)
        print(f'主方向偏 {ang:+.2f}°' + ('，转正' if abs(ang) > .05 else '，不用转'))
        c, s = math.cos(math.radians(-ang)), math.sin(math.radians(-ang))
        # 像素 → “毫米”（此时还没有比例：1 单位 = 1 原图像素）
        H = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]]); model = 'rotate'
        report.update(model=model, angle_deg=round(ang, 3))
    nm = native_mpp(H, w0, h0)
    if a.mpp: mpp = a.mpp
    elif a.chains:
        # 100mm 的隔墙不到 6 个像素时放大 2 倍再识别（量墙面能到亚像素），否则保持原图分辨率
        mpp = nm / 2 if 100 / nm < 6 else nm
        mpp = float(f'{mpp:.3g}')
    else: mpp = 1.0
    cx = Piece(*corr['x']) if corr else None; cy = Piece(*corr['y']) if corr else None
    fwd = lambda pts: (lambda q: np.c_[cx(q[:, 0]), cy(q[:, 1])] if cx else q)(apply_h(H, pts))
    cor = fwd([[0, 0], [w0, 0], [w0, h0], [0, h0]])
    mg = a.margin if a.chains else 0
    if obs:
        # 有尺寸链时按尺寸链范围 + 留白裁（照片里的桌面、屏幕边框不要）
        q = fwd([[o[0], o[1]] for o in obs]); lo = q.min(0) - mg; hi = q.max(0) + mg
        lo = np.maximum(lo, cor.min(0)); hi = np.minimum(hi, cor.max(0))
    else: lo, hi = cor.min(0), cor.max(0)
    ox, oy = float(math.floor(lo[0] / 10) * 10), float(math.floor(lo[1] / 10) * 10)
    W, Hh = int(math.ceil((hi[0] - ox) / mpp)), int(math.ceil((hi[1] - oy) / mpp))
    if W * Hh > 60e6: sys.exit(f'输出 {W}x{Hh} 太大，加 --mpp 调大每像素毫米数')
    # 逆映射：拉正图每个像素 → 毫米 → 去掉分段修正 → 单应逆 → 原图像素
    u, v = np.meshgrid(np.arange(W, dtype=np.float64), np.arange(Hh, dtype=np.float64))
    X = ox + (u + .5) * mpp; Y = oy + (v + .5) * mpp
    if cx: X, Y = cx.inv(X), cy.inv(Y)
    Hi = np.linalg.inv(H); d = Hi[2, 0] * X + Hi[2, 1] * Y + Hi[2, 2]
    mx = ((Hi[0, 0] * X + Hi[0, 1] * Y + Hi[0, 2]) / d - .5).astype(np.float32)
    my = ((Hi[1, 0] * X + Hi[1, 1] * Y + Hi[1, 2]) / d - .5).astype(np.float32)
    out = cv2.remap(img, mx, my, cv2.INTER_CUBIC if mpp < nm else cv2.INTER_AREA if mpp > nm * 1.5 else cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    Image.fromarray(out).save(os.path.join(a.out, 'rectified.png'))
    report.update(H=H.tolist(), corr=corr, mpp=mpp, native_mpp=round(nm, 3), origin_mm=[ox, oy], size=[W, Hh])
    json.dump(report, open(os.path.join(a.out, 'rectify.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if obs:
        vis = Image.fromarray(out).convert('RGB'); dr = ImageDraw.Draw(vis)
        for o, r in zip(obs, report['ticks']):
            Xp, Yp = fwd([[o[0], o[1]]])[0]; x, y = (Xp - ox) / mpp, (Yp - oy) / mpp
            col = (220, 30, 30) if abs(r['err_mm']) > 30 else (20, 160, 60)
            dr.ellipse([x - 6, y - 6, x + 6, y + 6], outline=col, width=2)
        vis.save(os.path.join(a.out, 'check.png'))
    print(f'拉正图 {W}x{Hh}，{mpp} mm/px（原图约 {nm:.2f} mm/px），左上角 = ({ox:.0f}, {oy:.0f}) mm')
    rel = os.path.join(a.out, 'rectified.png').replace('\\', '/')
    print('spec 里的底图（路径按 spec 所在目录改成相对路径）：')
    print(json.dumps({'underlay': {'image': rel, 'mmPerPx': mpp, 'x': ox, 'y': oy}}, ensure_ascii=False))
    if a.chains: print(f'之后识别：python analyze.py {rel} --scale {mpp} --origin {ox:.0f} {oy:.0f} --out …')


if __name__ == '__main__':
    main()
