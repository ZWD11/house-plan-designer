"""按原图量每面墙的两个墙面（像素），核对生成脚本里墙的中线和厚度。

为什么：尺寸标注的刻度常是轴线，墙不一定正好居中在轴线上；描边画的非承重墙（两条细线、中间白）
往往和旁边涂黑的承重墙一样厚、墙面对齐。只按刻度放墙、凭感觉给隔墙 100 厚，交接处就会错台。

用法（在生成脚本里）:
    from wallfit import fit
    print(fit('户型图.jpg', 'V', 858, 1215, 1345))   # 竖墙：x≈858 像素，y 从 1215 到 1345
    # → {'center': 861.8, 'thick_px': 13.5, 'faces': (855.0, 868.5), 'kind': 'outline', 'n': 17}
命令行:
    python wallfit.py 户型图.jpg V 858 1215 1345 [--mmpp 17.6] [--skip 1290-1320 ...]
kind：solid = 涂黑（实心）墙，outline = 两条线描边的墙；n = 有效取样数（太少说明这里是门窗洞或量错了位置）。
墙面位置是亚像素的：实心墙按边缘处亮度过半的位置插值，细线按深浅加权取中心（低分辨率图上 1px = 15~20mm，取整会差出一个墙面）。
给 mmpp（每像素毫米）时，实心 / 描边的判定门槛按毫米算（实心 ≥ 60mm、描边两线间 60~300mm），不同分辨率的图通用。
"""
import sys
import numpy as np
from PIL import Image
from imgio import open_upright

_cache = {}


def _img(path):
    if path not in _cache: _cache[path] = np.array(open_upright(path, 'L')).astype(int)
    return _cache[path]


def _runs(v, th):
    idx = np.where(v < th)[0]; out = []
    for i in idx:
        if out and i - out[-1][1] <= 1: out[-1][1] = i
        else: out.append([i, i])
    return out


def _edge(prof, i_out, i_in, mid):
    """在 i_out（亮）和 i_in（暗）两个相邻像素之间插值出亮度 = mid 的位置"""
    a, b = float(prof[i_out]), float(prof[i_in])
    if a == b: return (i_out + i_in) / 2
    t = min(1.0, max(0.0, (a - mid) / (a - b)))
    return i_out + (i_in - i_out) * t


def _center(prof, r, bg):
    """细线中心：按“比背景暗多少”加权"""
    lo, hi = max(0, r[0] - 1), min(len(prof) - 1, r[1] + 1)
    idx = np.arange(lo, hi + 1); w = np.clip(bg - prof[lo:hi + 1], 0, None).astype(float)
    return float((idx * w).sum() / w.sum()) if w.sum() > 0 else (r[0] + r[1]) / 2


def fit(path, kind, c, p0, p1, skip=(), search=25, th=150, step=3, mmpp=None):
    """kind 'V' = 竖墙（c 是 x 像素，p0~p1 是 y 范围），'H' = 横墙。skip = [(a, b), …] 不取样的区间（门窗洞）。"""
    a = _img(path); lo, hi = sorted((p0, p1)); res = []
    if mmpp:
        solid_min = max(3, int(round(60 / mmpp))); gmin, gmax = max(2, int(round(50 / mmpp))), max(4, int(round(300 / mmpp)))
        thin_max = max(3, int(round(30 / mmpp))); search = max(search, int(round(350 / mmpp)))
    else:
        solid_min, gmin, gmax, thin_max = 7, 6, 24, 3
    for p in range(int(lo) + 6, int(hi) - 5, step):
        if any(s0 - 3 <= p <= s1 + 3 for s0, s1 in skip): continue
        c0 = int(round(c)) - search
        prof = a[p, c0:c0 + 2 * search + 1] if kind == 'V' else a[c0:c0 + 2 * search + 1, p]
        if len(prof) < 2 * search + 1: continue
        bg = float(np.percentile(prof, 90))
        rs = _runs(prof, th); best = None
        for r in rs:  # 实心：一段连续的深色
            if r[1] - r[0] + 1 >= solid_min:
                m = (r[0] + r[1]) / 2
                if best is None or abs(m - search) < abs(best[2] - search):
                    fg = float(np.median(prof[r[0]:r[1] + 1])); mid = (bg + fg) / 2
                    e0 = _edge(prof, r[0] - 1, r[0], mid) if r[0] > 0 else r[0] - .5
                    e1 = _edge(prof, r[1] + 1, r[1], mid) if r[1] < len(prof) - 1 else r[1] + .5
                    best = (e0, e1, m, 'solid')
        if best is None:  # 描边：两条细线，中间白
            thin = [r for r in rs if r[1] - r[0] + 1 <= thin_max]
            for i in range(len(thin)):
                for j in range(i + 1, len(thin)):
                    g = thin[j][0] - thin[i][1] - 1
                    if gmin <= g <= gmax:
                        f0, f1 = _center(prof, thin[i], bg), _center(prof, thin[j], bg)
                        m = (f0 + f1) / 2
                        if abs(m - search) <= max(12, gmax / 2) and (best is None or abs(m - search) < abs(best[2] - search)): best = (f0, f1, m, 'outline')
        if best: res.append((best[0] + c0, best[1] + c0, best[3]))
    if not res: return {'center': None, 'n': 0}
    f0 = float(np.median([r[0] for r in res])); f1 = float(np.median([r[1] for r in res]))
    kinds = [r[2] for r in res]; k = max(set(kinds), key=kinds.count)
    out = {'center': round((f0 + f1) / 2, 2), 'thick_px': round(f1 - f0, 2), 'faces': (round(f0, 2), round(f1, 2)), 'kind': k, 'n': len(res)}
    if mmpp: out['thick_mm'] = round((f1 - f0) * mmpp)
    return out


if __name__ == '__main__':
    args = sys.argv[1:]; skip = []
    mmpp = None
    if '--mmpp' in args:
        i = args.index('--mmpp'); mmpp = float(args[i + 1]); args = args[:i] + args[i + 2:]
    if '--skip' in args:
        i = args.index('--skip'); skip = [tuple(map(float, s.split('-'))) for s in args[i + 1:]]; args = args[:i]
    path, kind, c, p0, p1 = args[0], args[1], float(args[2]), float(args[3]), float(args[4])
    print(fit(path, kind, c, p0, p1, skip, mmpp=mmpp))
