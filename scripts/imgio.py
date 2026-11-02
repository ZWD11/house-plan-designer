"""读图公共函数：所有脚本读户型图都走这里。

open_upright(path)：按 EXIF 方向标记摆正后再用。手机拍照 / 微信转发的图常带“旋转 90°”标记，
看图软件显示是竖的，PIL 直接读出来却是横的——毫米网格、刻度像素会整体错位。
"""
from PIL import Image, ImageOps


def open_upright(path, mode='RGB', rotate=0):
    """rotate：再顺时针转多少度（0 / 90 / 180 / 270），给方向和原图不一样的设计图用（underlay 里的 rotate）"""
    im = Image.open(path)
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:
        pass
    if rotate % 360: im = im.rotate(-(rotate % 360), expand=True)
    return im.convert(mode) if mode else im


def exif_rotated(path):
    """图片带不是“正常”的方向标记时返回标记值（2~8），否则 0。"""
    try:
        o = Image.open(path).getexif().get(0x0112, 1)
        return o if o and o != 1 else 0
    except Exception:
        return 0


HUES = {'red': ((0, 8), (170, 180)), 'yellow': ((20, 35),), 'green': ((35, 70),), 'cyan': ((70, 100),), 'blue': ((100, 135),), 'magenta': ((135, 170),)}


def color_mask(rgb, name):
    """黑底 CAD 截图里某个线色的像素（CAD 索引色：红 黄 绿 青 蓝 紫 白）。rgb: HxWx3 uint8 数组。
    JPEG 截图的细线边缘发灰，饱和度只有 50~80，所以门槛放得比较低。"""
    import numpy as np, cv2
    hsv = cv2.cvtColor(np.asarray(rgb, np.uint8), cv2.COLOR_RGB2HSV)
    h, s, v = (hsv[..., i].astype(int) for i in range(3))
    if name == 'white': return (v > 60) & (s <= 40)
    m = np.zeros(h.shape, bool)
    for lo, hi in HUES[name]: m |= (h >= lo) & (h < hi)
    return m & (v > 60) & (s > 40)
