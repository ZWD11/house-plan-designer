"""按原图量每面墙的两个墙面（像素），核对生成脚本里墙的中线和厚度。

为什么：尺寸标注的刻度常是轴线，墙不一定正好居中在轴线上；描边画的非承重墙（两条细线、中间白）
往往和旁边涂黑的承重墙一样厚、墙面对齐。只按刻度放墙、凭感觉给隔墙 100 厚，交接处就会错台。

用法（在生成脚本里）:
    from wallfit import fit
    print(fit('户型图.jpg', 'V', 858, 1215, 1345))   # 竖墙：x≈858 像素，y 从 1215 到 1345
    # → {'center': 861.8, 'thick_px': 13.5, 'faces': (855.0, 868.5), 'kind': 'outline', 'n': 17}
命令行:
    python wallfit.py 户型图.jpg V 858 1215 1345 [--skip 1290-1320 ...]
kind：solid = 涂黑（实心）墙，outline = 两条线描边的墙；n = 有效取样数（太少说明这里是门窗洞或量错了位置）。
"""
import sys
import numpy as np
from PIL import Image

_cache = {}


def _img(path):
    if path not in _cache: _cache[path] = np.array(Image.open(path).convert('L')).astype(int)
    return _cache[path]


def _runs(v, th):
    idx = np.where(v < th)[0]; out = []
    for i in idx:
        if out and i - out[-1][1] <= 1: out[-1][1] = i
        else: out.append([i, i])
    return out


def fit(path, kind, c, p0, p1, skip=(), search=25, th=150, step=3):
    """kind 'V' = 竖墙（c 是 x 像素，p0~p1 是 y 范围），'H' = 横墙。skip = [(a, b), …] 不取样的区间（门窗洞）。"""
    a = _img(path); lo, hi = sorted((p0, p1)); res = []
    for p in range(int(lo) + 6, int(hi) - 5, step):
        if any(s0 - 3 <= p <= s1 + 3 for s0, s1 in skip): continue
        c0 = int(round(c)) - search
        prof = a[p, c0:c0 + 2 * search + 1] if kind == 'V' else a[c0:c0 + 2 * search + 1, p]
        if len(prof) < 2 * search + 1: continue
        rs = _runs(prof, th); best = None
        for r in rs:  # 实心：一段连续的深色 ≥ 7px
            if r[1] - r[0] + 1 >= 7:
                m = (r[0] + r[1]) / 2
                if best is None or abs(m - search) < abs(best[2] - search): best = (r[0] - .5, r[1] + .5, m, 'solid')
        if best is None:  # 描边：两条细线，中间白 6~24px
            thin = [r for r in rs if r[1] - r[0] + 1 <= 3]
            for i in range(len(thin)):
                for j in range(i + 1, len(thin)):
                    g = thin[j][0] - thin[i][1] - 1
                    if 6 <= g <= 24:
                        f0, f1 = (thin[i][0] + thin[i][1]) / 2, (thin[j][0] + thin[j][1]) / 2
                        m = (f0 + f1) / 2
                        if abs(m - search) <= 12 and (best is None or abs(m - search) < abs(best[2] - search)): best = (f0, f1, m, 'outline')
        if best: res.append((best[0] + c0, best[1] + c0, best[3]))
    if not res: return {'center': None, 'n': 0}
    f0 = float(np.median([r[0] for r in res])); f1 = float(np.median([r[1] for r in res]))
    kinds = [r[2] for r in res]; k = max(set(kinds), key=kinds.count)
    return {'center': round((f0 + f1) / 2, 1), 'thick_px': round(f1 - f0, 1), 'faces': (round(f0, 1), round(f1, 1)), 'kind': k, 'n': len(res)}


if __name__ == '__main__':
    args = sys.argv[1:]; skip = []
    if '--skip' in args:
        i = args.index('--skip'); skip = [tuple(map(float, s.split('-'))) for s in args[i + 1:]]; args = args[:i]
    path, kind, c, p0, p1 = args[0], args[1], float(args[2]), float(args[3]), float(args[4])
    print(fit(path, kind, c, p0, p1, skip))
