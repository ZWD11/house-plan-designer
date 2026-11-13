"""
门的开向：按原图上的门弧 + 门扇线判读，和 spec 对账（也可以直接改好）。
每扇平开门试 4 种画法（门轴在 from / to 端 × 开向墙的哪一侧），沿理论门弧和门扇线采样原图墨迹，得分最高的就是原图的画法；
和 spec 里的 hinge / into 不一样就报出来。双开门只判开向哪一侧。推拉、折叠、门洞不查。

用法:
  python doorcheck.py spec.json --out <工作目录>/doors                # 对账：只报不一致的
  python doorcheck.py spec.json --out ... --write spec_fixed.json      # 把有把握的（得分高、差距大）直接改进 spec 另存
  可选：--floor 1  --min-score .45（最好那种画法至少要对上多少比例的采样点）  --margin .2（比 spec 的画法高多少才报）
输出: doors.json（每扇门：spec 的画法、原图最像的画法、各画法得分）、doors_<层>.png（绿 = spec 的门弧、红 = 原图最像的门弧，不一致的门加框）
门弧画得很淡 / 虚线 / 彩色图里木地板上的白线也能认（按和局部背景的反差取线）；门扇画成关着的、只画了门洞的图，得分都低，不会乱报。
"""
import argparse, json, math, os, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont
from imgio import open_upright
sys.stdout.reconfigure(encoding='utf-8')

ap = argparse.ArgumentParser()
ap.add_argument('spec'); ap.add_argument('--out', required=True); ap.add_argument('--write')
ap.add_argument('--floor', type=int); ap.add_argument('--min-score', type=float, default=.35); ap.add_argument('--margin', type=float, default=.2)
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
spec = json.load(open(a.spec, encoding='utf-8'))
floors = spec['floors'] if 'floors' in spec else [spec]
base = os.path.dirname(os.path.abspath(a.spec))
try: FONT = ImageFont.truetype('msyh.ttc', 14)
except Exception:
    try: FONT = ImageFont.truetype('NotoSansCJK-Regular.ttc', 14)
    except Exception: FONT = ImageFont.load_default()
SINGLE = {'door', 'entry', 'mother'}
DOUBLE = {'double', 'unequal'}


def frame(w):
    (ax, ay), (bx, by) = w['a'], w['b']; L = math.hypot(bx - ax, by - ay) or 1
    u = np.array([(bx - ax) / L, (by - ay) / L]); return np.array([ax, ay], float), u, np.array([-u[1], u[0]]), L


def along(w, v):
    A, u, _, _ = frame(w)
    if abs(u[1]) < 1e-6: return (v - A[0]) / u[0]
    if abs(u[0]) < 1e-6: return (v - A[1]) / u[1]
    return v


def leaves(A, u, n, h, s0, s1, kind, hinge, side):
    """→ [(门轴点, 门扇关闭方向（沿墙）, 开向（法向）, 半径)]，mm"""
    nn = n * side; out = []
    if kind == 'double':
        r = (s1 - s0) / 2
        out.append((A + u * s0 + nn * h, u, nn, r)); out.append((A + u * s1 + nn * h, -u, nn, r))
    else:
        hs, d = (s0, u) if hinge == 'from' else (s1, -u)
        out.append((A + u * hs + nn * h, d, nn, s1 - s0))
    return out


def score(ink, P, lv):
    """门弧 + 门扇线上的命中率 − 扇形里面对照点的命中率（花纹地砖、文字到处都是墨，靠对照点扣掉）"""
    def hit(pts):
        h = 0
        for p in pts:
            x, y = P(*p); xi, yi = int(round(x)), int(round(y))
            if 0 <= yi < ink.shape[0] and 0 <= xi < ink.shape[1] and ink[yi, xi]: h += 1
        return h / max(1, len(pts))
    on, ctl = [], []
    for c, d, nn, r in lv:
        ts = np.radians(np.arange(12, 80, 4))
        on += [c + r * (math.cos(t) * d + math.sin(t) * nn) for t in ts] + [c + nn * r * f for f in np.arange(.2, .92, .06)]
        ctl += [c + .62 * r * (math.cos(t) * d + math.sin(t) * nn) for t in ts] + [c + r * f * (d + nn) / math.sqrt(2) for f in np.arange(.2, .8, .05)]
    return max(0.0, hit(on) - hit(ctl))


def fill_score(g, P, lv, solid=None, skip=None):
    """彩色户型图的门：不画线，画一块颜色不同的扇形。扇形里面颜色均匀、和弧外一圈反差大 → 得分高"""
    def vals(pts):
        out = []
        for p in pts:
            if skip is not None and skip(p): continue
            x, y = P(*p); xi, yi = int(round(x)), int(round(y))
            # 墙体（深色实心）不算：弧外一圈碰到墙会凭空多出反差
            if 0 <= yi < g.shape[0] and 0 <= xi < g.shape[1] and not (solid is not None and solid[yi, xi]): out.append(g[yi, xi])
        return np.array(out, float)
    sc = []
    for c, d, nn, r in lv:
        ts = np.radians(np.arange(15, 76, 6))
        inn = vals([c + r * f * (math.cos(t) * d + math.sin(t) * nn) for t in ts for f in (.35, .5, .65, .8)])
        # 对照：门扇外接正方形的角上（弧外、方框内）——还是这间房的地面，不会碰到别的墙
        out = vals([c + r * (p * d + q * nn) for p in (.82, .88, .94) for q in (.82, .88, .94) if p * p + q * q > 1.25])
        if len(inn) < 10 or len(out) < 4: return 0.0
        con = abs(np.median(inn) - np.median(out)) / 30
        sc.append(max(0.0, min(1.0, con) - np.std(inn) / 25))
    return float(min(sc)) if sc else 0.0


def draw(d, P, lv, col, wdt=2):
    for c, dd, nn, r in lv:
        pts = [P(*(c + r * (math.cos(t) * dd + math.sin(t) * nn))) for t in np.radians(np.arange(0, 91, 5))]
        d.line(pts, fill=col, width=wdt); d.line([P(*c), P(*(c + nn * r))], fill=col, width=wdt)


report, changed = [], 0
for fi, fl in enumerate(floors):
    if a.floor is not None and fi != a.floor: continue
    ul = fl.get('underlay') or spec.get('underlay')
    if not ul: print(f'第 {fi} 层没有 underlay，跳过'); continue
    p = ul['image'] if os.path.isabs(ul['image']) else os.path.join(base, ul['image'])
    rgb = np.array(open_upright(p, rotate=ul.get('rotate', 0))).astype(np.int16)
    if np.median(rgb.max(2)) < 90: rgb = 255 - rgb
    S, OX, OY = ul['mmPerPx'], ul['x'], ul['y']
    P = lambda x, y: ((x - OX) / S, (y - OY) / S)
    # 门弧墨迹：比背景深就算（门弧常是浅灰 / 虚线 / 彩色）；墙体实心块去掉，不然贴墙的采样点全算命中
    g = rgb.mean(2)
    solid = cv2.morphologyEx(((rgb.max(2) - rgb.min(2) < 22) & (rgb.max(2) < 175)).astype(np.uint8), cv2.MORPH_OPEN, np.ones((max(3, int(80 / S)),) * 2, np.uint8))
    # 细线 = 和周围（中值滤波后的背景）反差大：深色线画在白底、白线画在木地板上都算
    g8 = np.clip(g, 0, 255).astype(np.uint8); km = max(7, int(round(150 / S)) | 1)
    bg = cv2.medianBlur(g8, min(km, 31)).astype(np.int16)
    ink = ((np.abs(g8.astype(np.int16) - bg) > 22) & (solid == 0)).astype(np.uint8)
    solidd = cv2.dilate(solid, np.ones((5, 5), np.uint8)) > 0
    kd = 2 * max(1, int(round(35 / S))) + 1
    ink = cv2.dilate(ink, np.ones((kd, kd), np.uint8)) > 0
    im = Image.fromarray(((rgb * .5) + 127).astype(np.uint8)); dr = ImageDraw.Draw(im)
    fname = fl.get('name') or f'{fi}层'
    def spec_leaves(w, o):
        A, u, n, L = frame(w); h = w.get('t', 120) / 2
        kind = 'double' if o.get('type') in DOUBLE else 'single'
        s0, s1 = sorted((along(w, o['from']), along(w, o['to'])))
        mid = A + u * (s0 + s1) / 2; into = o.get('into')
        sd = (1 if np.dot(np.array(into, float) - mid, n) >= 0 else -1) if into else 1
        small = along(w, o['from']) <= along(w, o['to'])
        hg = 'from' if (o.get('hinge', 'from') == 'from') == small else 'to'
        return leaves(A, u, n, h, s0, s1, kind, hg, sd)
    # 所有门在 spec 里的扇形：判读某扇门时，落进别的门扇形里的画法不算（相邻两扇门的门弧会互相“借”）
    allv = [(wi, oi, spec_leaves(w, o)) for wi, w in enumerate(fl.get('walls', [])) for oi, o in enumerate(w.get('openings', []))
            if o.get('type') in SINGLE | DOUBLE and abs(along(w, o['to']) - along(w, o['from'])) >= 500]
    def other_at(p, me):
        for wi_, oi_, ov in allv:
            if (wi_, oi_) == me: continue
            if any(np.linalg.norm(p - c) <= r + 40 and np.dot(p - c, d) >= -40 and np.dot(p - c, nn) >= -40 for c, d, nn, r in ov): return True
        return False
    def in_other(lv, me):
        pts = [c + r * f * (math.cos(t) * d + math.sin(t) * nn) for c, d, nn, r in lv for t in np.radians(np.arange(15, 76, 10)) for f in (.35, .55, .75)]
        k = 0
        for p in pts:
            for wi_, oi_, ov in allv:
                if (wi_, oi_) == me: continue
                if any(np.linalg.norm(p - c) <= r and np.dot(p - c, d) >= -20 and np.dot(p - c, nn) >= -20 for c, d, nn, r in ov): k += 1; break
        return k / max(1, len(pts)) > .2
    for wi, w in enumerate(fl.get('walls', [])):
        A, u, n, L = frame(w); h = w.get('t', 120) / 2
        for oi, o in enumerate(w.get('openings', [])):
            t = o.get('type')
            if t not in SINGLE and t not in DOUBLE: continue
            kind = 'double' if t in DOUBLE else 'single'
            s0, s1 = sorted((along(w, o['from']), along(w, o['to'])))
            if s1 - s0 < 500: continue
            mid = A + u * (s0 + s1) / 2
            into = o.get('into')
            side_m = (1 if np.dot(np.array(into, float) - mid, n) >= 0 else -1) if into else 1
            # spec 的 hinge 是 from / to（世界坐标那一端）；换算到“沿墙距离”的小端 / 大端
            fs = along(w, o['from']); h_from_small = fs <= along(w, o['to'])
            hm = o.get('hinge', 'from')
            hinge_m = 'from' if (hm == 'from') == h_from_small else 'to'
            combos = {}
            for hg in (['from', 'to'] if kind == 'single' else ['from']):
                for sd in (1, -1):
                    lv_ = leaves(A, u, n, h, s0, s1, kind, hg, sd)
                    combos[(hg, sd)] = 0.0 if in_other(lv_, (wi, oi)) else max(score(ink, P, lv_), fill_score(g, P, lv_, solidd, lambda p: other_at(p, (wi, oi))))
            best = max(combos, key=combos.get); bs = combos[best]
            ms = combos[(hinge_m if kind == 'single' else 'from', side_m)]
            item = {'floor': fname, 'wall': wi, 'opening': oi, 'type': t, 'from': o['from'], 'to': o['to'],
                    'spec': {'hinge': hm, 'side': side_m, 'score': round(ms, 2)},
                    'drawing': {'hinge': (('from' if h_from_small else 'to') if best[0] == 'from' else ('to' if h_from_small else 'from')) if kind == 'single' else None,
                                'side': best[1], 'score': round(bs, 2)},
                    'scores': {f'{k[0]}/{k[1]:+d}': round(v, 2) for k, v in combos.items()}}
            bad = bs >= a.min_score and bs - ms >= a.margin
            item['mismatch'] = bool(bad)
            report.append(item)
            draw(dr, P, leaves(A, u, n, h, s0, s1, kind, hinge_m, side_m), (0, 170, 60))
            if bad:
                lv = leaves(A, u, n, h, s0, s1, kind, *best)
                draw(dr, P, lv, (230, 30, 30), 3)
                x, y = P(*mid); r = (s1 - s0) / S + 10
                dr.rectangle([x - r, y - r, x + r, y + r], outline=(230, 30, 30), width=2)
                dr.text((x - r, y - r - 16), f'墙{wi}#{oi}', fill=(230, 30, 30), font=FONT)
                if a.write:
                    sd = best[1]; nn = n * sd
                    o['into'] = [round(float(v)) for v in (mid + nn * (h + (s1 - s0) * .6))]
                    if kind == 'single': o['hinge'] = item['drawing']['hinge']
                    changed += 1
    im.save(os.path.join(a.out, f'doors_{fi}.png'))

json.dump(report, open(os.path.join(a.out, 'doors.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
bad = [r for r in report if r['mismatch']]
weak = [r for r in report if r['drawing']['score'] < a.min_score]
print(f'平开门 {len(report)} 扇：开向和原图不一致 {len(bad)} 扇，原图门弧认不出 {len(weak)} 扇（这些人工看）')
for r in bad:
    sp, dw = r['spec'], r['drawing']
    print(f"  ✗ {r['floor']} 墙{r['wall']} 洞口#{r['opening']} {r['type']} {r['from']}~{r['to']}：spec 门轴 {sp['hinge']}、开向法向{sp['side']:+d}（{sp['score']}）"
          f" → 原图像 门轴 {dw['hinge'] or '两端'}、开向法向{dw['side']:+d}（{dw['score']}）")
if a.write:
    json.dump(spec, open(a.write, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'已改 {changed} 扇，另存 {a.write}（原 spec 没动）。改完重跑 build + check')
print('看 doors_*.png：绿 = spec 的门弧，红 = 原图最像的门弧。')
sys.exit(1 if bad else 0)
