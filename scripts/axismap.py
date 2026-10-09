"""
按图上的标注尺寸，把像素坐标精确换算成毫米（分段线性），代替“整体乘一个比例”。

为什么：户型图本身画得不一定准，整体按一个比例换算，每面墙会差几十毫米；
标注数字才是准的。把尺寸线上每个刻度（尺寸界线）的像素位置，和它对应的累计毫米数配成对，
刻度之间线性插值、两头按平均比例外推，墙就会正好落在标注尺寸上。

用法（在户型生成脚本里）:
    import sys; sys.path.insert(0, r'<skill>/scripts'); from axismap import Axis, chain
    # analysis.json 的 dims_px.top 里有一条尺寸线的刻度像素：[447.5, 569.5, 576.5, 658.5, ...]
    # 按图上标注读出相邻刻度之间的毫米数（刻度多了的就跳过，少了就补）
    X = Axis(chain([447.5, 569.5, 576.5, 658.5, 669.5, 751.5, 761.5, 926.5],
                   [2750, 120, 1860, 240, 1850, 200, 3738]))
    Y = Axis(chain([...左侧尺寸线刻度...], [...]))
    X(600)        # 像素 → 毫米
    X.report()    # 每段的 毫米/像素，偏离平均 3% 以上的段会标出来（多半是读错了数字或者刻度选错了）

注意标注量的是什么：多数户型图的分段尺寸量的是“墙面到墙面”（净尺寸）或“轴线到轴线”。
量到墙面时，墙中线 = 墙面 ± 墙厚/2；Axis 只负责把刻度位置换算准。
"""


def chain(ticks_px, dims_mm, start_mm=0.0):
    """刻度像素 + 相邻刻度间的标注毫米数 → [(像素, 累计毫米)]"""
    if len(dims_mm) != len(ticks_px) - 1:
        raise ValueError(f'{len(ticks_px)} 个刻度应该对应 {len(ticks_px) - 1} 段尺寸，现在给了 {len(dims_mm)} 段')
    out, acc = [(float(ticks_px[0]), float(start_mm))], float(start_mm)
    for t, d in zip(ticks_px[1:], dims_mm):
        acc += d; out.append((float(t), acc))
    return out


class Axis:
    """分段线性的 像素 → 毫米 换算。pairs 可以来自多条尺寸线（同一方向），会自动合并排序"""

    def __init__(self, *pair_lists, offset_mm=0.0):
        pts = sorted({round(p, 2): m for pl in pair_lists for p, m in pl}.items())
        if len(pts) < 2: raise ValueError('至少要两个刻度')
        self.px = [p for p, _ in pts]; self.mm = [m + offset_mm for _, m in pts]
        n = len(pts); mp, mm_ = sum(self.px) / n, sum(self.mm) / n
        num = sum((p - mp) * (m - mm_) for p, m in zip(self.px, self.mm)); den = sum((p - mp) ** 2 for p in self.px)
        self.scale = num / den if den else 1.0  # 平均 毫米/像素（外推用）

    def __call__(self, p, snap=10):
        px, mm = self.px, self.mm
        if p <= px[0]: v = mm[0] - (px[0] - p) * self.scale
        elif p >= px[-1]: v = mm[-1] + (p - px[-1]) * self.scale
        else:
            i = next(k for k in range(1, len(px)) if px[k] >= p)
            v = mm[i - 1] + (p - px[i - 1]) * (mm[i] - mm[i - 1]) / (px[i] - px[i - 1])
        return round(v / snap) * snap if snap else v

    def report(self):
        import sys
        try: sys.stdout.reconfigure(encoding='utf-8')
        except Exception: pass
        print(f'平均 {self.scale:.3f} mm/px')
        for k in range(1, len(self.px)):
            dp, dm = self.px[k] - self.px[k - 1], self.mm[k] - self.mm[k - 1]
            if dp <= 0: continue
            r = dm / dp; flag = '  ← 偏离平均 {:.0%}，核对这段'.format(r / self.scale - 1) if abs(r / self.scale - 1) > .03 and dp > 15 else ''  # 短段（墙厚）像素太少，不评判
            print(f'  {self.px[k - 1]:7.1f} → {self.px[k]:7.1f} px  {dm:6.0f} mm  {r:6.3f} mm/px{flag}')


if __name__ == '__main__':
    X = Axis(chain([447.5, 569.5, 576.5, 658.5, 669.5, 751.5, 761.5, 926.5], [2750, 120, 1860, 240, 1850, 200, 3738]))
    X.report(); print(X(500), X(700), X(1000))
