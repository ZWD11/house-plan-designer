"""
识别回归基准：拿做过、用户验收过的户型（<目录>/*_design/spec.json + 原图）当标准答案，量识别脚本到底准不准。
改了 analyze.py / rectify.py / coverage.py / doorcheck.py 之后跑一遍，和上次比：变好还是变差一目了然，不靠感觉。

每个案例量：
  墙召回 / 墙准确：analyze.py 自动识别出的墙（draft.json）和标准 spec 的墙按中线配对（同方向、中线差 ≤ 80mm、沿墙重叠），
                  召回 = 标准墙长度里被识别到的比例，准确 = 识别出的墙长度里是真墙的比例；中线误差 / 墙厚误差取配上的中位数
  一致度：coverage.py 对标准 spec 的分数（反过来验证 coverage 本身没有乱报）
  门：doorcheck.py 认出门弧的比例、报“不一致”的扇数（标准 spec 应该接近 0）

用法:
  python bench.py --root "D:/…/房屋设计" --out <目录>/bench          # 自动找 root 下所有 *_design/spec.json（单层、底图存在的）
  python bench.py --cases a_design/spec.json b_design/spec.json --out …
输出 bench.json、bench.txt；out 里已有上次的 bench.json 会逐项打出差值（↑ 变好 / ↓ 变差）。
"""
import argparse, glob, json, math, os, subprocess, sys, tempfile
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument('--root'); ap.add_argument('--cases', nargs='*'); ap.add_argument('--out', required=True)
ap.add_argument('--analyze-args', default='', help='传给 analyze.py 的额外参数，比较参数效果用，如 "--no-light-walls"')
ap.add_argument('--skip-audit', action='store_true', help='只跑 analyze（不跑 coverage / doorcheck），快')
ap.add_argument('--tol', type=float, default=80, help='中线差多少 mm 以内算同一面墙')
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
cases = list(a.cases or [])
if a.root: cases += sorted(glob.glob(os.path.join(a.root, '*_design', 'spec.json')))
if not cases: sys.exit('没有案例：给 --root 或 --cases')


def segs(walls):
    """→ [(方向 'h'/'v', 中线坐标, 起, 止, 厚)]，斜墙跳过"""
    out = []
    for w in walls:
        (ax, ay), (bx, by) = w['a'], w['b']
        if abs(ay - by) < 1: out.append(('h', ay, min(ax, bx), max(ax, bx), w.get('t', 120)))
        elif abs(ax - bx) < 1: out.append(('v', ax, min(ay, by), max(ay, by), w.get('t', 120)))
    return out


def cover(A, B, tol):
    """A 的总长里被 B 覆盖的长度；配上的中线差、厚度差"""
    tot = got = 0; dc, dt = [], []
    for o, c, s0, s1, t in A:
        L = s1 - s0; tot += L
        iv = []
        for o2, c2, q0, q1, t2 in B:
            if o2 != o or abs(c2 - c) > tol: continue
            lo, hi = max(s0, q0), min(s1, q1)
            if hi - lo > 50: iv.append((lo, hi)); dc.append(abs(c2 - c)); dt.append(abs(t2 - t))
        iv.sort(); m = 0; cur = None
        for lo, hi in iv:
            if cur and lo <= cur[1]: cur[1] = max(cur[1], hi)
            else:
                if cur: m += cur[1] - cur[0]
                cur = [lo, hi]
        if cur: m += cur[1] - cur[0]
        got += min(m, L)
    return got / max(1, tot), dc, dt


def med(v): v = sorted(v); return round(v[len(v) // 2]) if v else None


rows = []
for sp in cases:
    name = os.path.basename(os.path.dirname(os.path.abspath(sp)))
    try: spec = json.load(open(sp, encoding='utf-8'))
    except Exception as e: print(f'{name}：读不了 spec（{e}）'); continue
    if 'floors' in spec: print(f'{name}：多层，跳过（基准只用单层）'); continue
    ul = spec.get('underlay')
    if not ul: print(f'{name}：没有 underlay，跳过'); continue
    img = ul['image'] if os.path.isabs(ul['image']) else os.path.join(os.path.dirname(os.path.abspath(sp)), ul['image'])
    if not os.path.exists(img) or ul.get('rotate'): print(f'{name}：底图不存在或转过，跳过'); continue
    row = {'case': name}
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([sys.executable, os.path.join(HERE, 'analyze.py'), img, '--scale', str(ul['mmPerPx']), '--origin', str(ul['x']), str(ul['y']), '--out', td] + a.analyze_args.split(),
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        dp = os.path.join(td, 'draft.json')
        if os.path.exists(dp):
            draft = json.load(open(dp, encoding='utf-8'))
            G, D = segs(spec['walls']), segs(draft.get('walls', []))
            rec, dc, dt = cover(G, D, a.tol); prec, _, _ = cover(D, G, a.tol)
            row.update(wall_recall=round(rec, 3), wall_precision=round(prec, 3), center_err=med(dc), thick_err=med(dt), n_walls=[len(G), len(D)])
        else:
            row['analyze_error'] = (r.stderr or r.stdout)[-300:]
        if a.skip_audit: rows.append(row); print(name, row); continue
        r = subprocess.run([sys.executable, os.path.join(HERE, 'coverage.py'), sp, '--out', td], capture_output=True, text=True, encoding='utf-8', errors='replace')
        cp = os.path.join(td, 'coverage.json')
        if os.path.exists(cp):
            c = json.load(open(cp, encoding='utf-8'))[0]
            row.update(consistency=c['score'], misses=len(c['misses']), offsets=len(c['offsets']), mode=c['mode'])
        r = subprocess.run([sys.executable, os.path.join(HERE, 'doorcheck.py'), sp, '--out', td], capture_output=True, text=True, encoding='utf-8', errors='replace')
        dp2 = os.path.join(td, 'doors.json')
        if os.path.exists(dp2):
            d = json.load(open(dp2, encoding='utf-8'))
            if d: row.update(doors=len(d), doors_read=round(sum(x['drawing']['score'] >= .35 for x in d) / len(d), 2), doors_flag=sum(x['mismatch'] for x in d))
    if not a.skip_audit: rows.append(row); print(name, row)

prev = {}
pp = os.path.join(a.out, 'bench.json')
if os.path.exists(pp):
    try: prev = {r['case']: r for r in json.load(open(pp, encoding='utf-8'))['rows']}
    except Exception: prev = {}
KEYS = [('wall_recall', '墙召回', 1), ('wall_precision', '墙准确', 1), ('center_err', '中线误差mm', -1), ('thick_err', '墙厚误差mm', -1),
        ('consistency', '一致度', 1), ('misses', '漏墙', -1), ('offsets', '偏位', -1), ('doors_read', '门弧认出', 1), ('doors_flag', '门报错', -1)]
lines = ['案例'.ljust(14) + ''.join(k[1].rjust(11) for k in KEYS)]
for r in rows:
    cells = []
    for k, _, good in KEYS:
        v = r.get(k); s = '-' if v is None else (f'{v:.1%}' if isinstance(v, float) and v <= 1 and k not in ('center_err', 'thick_err') else str(v))
        pv = prev.get(r['case'], {}).get(k)
        if v is not None and pv is not None and v != pv: s += '↑' if (v - pv) * good > 0 else '↓'
        cells.append(s.rjust(11))
    lines.append(r['case'][:14].ljust(14) + ''.join(cells))
def avg(k):
    v = [r[k] for r in rows if r.get(k) is not None]; return sum(v) / len(v) if v else None
summ = {k: (round(avg(k), 3) if avg(k) is not None else None) for k, _, _ in KEYS}
lines.append('平均'.ljust(14) + ''.join(('-' if summ[k] is None else (f'{summ[k]:.1%}' if k in ('wall_recall', 'wall_precision', 'consistency', 'doors_read') else f'{summ[k]:.1f}')).rjust(11) for k, _, _ in KEYS))
txt = '\n'.join(lines)
print('\n' + txt)
open(os.path.join(a.out, 'bench.txt'), 'w', encoding='utf-8').write(txt)
if prev: os.replace(pp, os.path.join(a.out, 'bench_prev.json'))
json.dump({'rows': rows, 'summary': summ}, open(pp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
