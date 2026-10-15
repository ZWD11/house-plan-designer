"""
给户型图的一块区域叠毫米网格（每 100mm 细线、500mm 蓝线、1000mm 红线带数字）并放大，用来直接按毫米读墙、门窗、楼梯的位置。
图片路线（尤其一张图上并排几层、每层比例不同）时，每层先定好“原点像素 + 每像素毫米数”，再逐块读。

  python gridmm.py 户型图.jpg OX OY S X0 Y0 X1 Y1 out.png [放大倍数=3] [SY]
    OX OY   原点（一般是这一层最西外墙外皮 / 最北外墙外皮）在原图上的像素位置
    S       每像素多少毫米（按分段尺寸刻度量出来；横竖比例不一样时再给 SY）
    X0..Y1  要看的范围（毫米，可以是负数）

楼层对齐：几层并排在一张图上时，找各层完全相同的分段尺寸链（如西侧 220/1590/220/1900），
让它们的起点落在同一个毫米坐标，各层就在同一坐标系里了。
"""
import sys
from PIL import Image, ImageDraw, ImageFont


def grid(img, ox, oy, sx, x0, y0, x1, y1, out, k=3, sy=None):
    sy = sy or sx
    im = Image.open(img).convert('RGB')
    px = lambda m: ox + m / sx
    py = lambda m: oy + m / sy
    cx0, cy0 = int(px(x0)), int(py(y0))
    c = im.crop((cx0, cy0, int(px(x1)), int(py(y1))))
    W, H = c.size
    c = c.resize((W * k, H * k), Image.LANCZOS)
    d = ImageDraw.Draw(c)
    try:
        f = ImageFont.truetype('arial.ttf', 14)
    except OSError:
        f = ImageFont.load_default()
    col = lambda m: (255, 0, 0) if m % 1000 == 0 else ((0, 160, 255) if m % 500 == 0 else (200, 230, 200))
    lo, hi = int(min(x0, y0) // 100 * 100) - 100, int(max(x1, y1)) + 200
    for m in range(lo, hi, 100):
        X = (px(m) - cx0) * k
        if 0 <= X < W * k:
            d.line([(X, 0), (X, H * k)], fill=col(m), width=1)
            if m % 500 == 0: d.text((X + 2, 2), str(m), fill=col(m), font=f)
        Y = (py(m) - cy0) * k
        if 0 <= Y < H * k:
            d.line([(0, Y), (W * k, Y)], fill=col(m), width=1)
            if m % 500 == 0: d.text((2, Y + 2), str(m), fill=col(m), font=f)
    c.save(out)


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) < 9:
        print(__doc__); sys.exit(1)
    grid(a[0], *map(float, a[1:8]), a[8], int(a[9]) if len(a) > 9 else 3, float(a[10]) if len(a) > 10 else None)
    print('写出', a[8])
