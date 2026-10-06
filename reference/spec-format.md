# HouseSpec 户型描述格式

设计器启动时用 `planFromSpec()`（项目 `src/model/spec.ts`）把它转成完整方案。
完整例子：`example-spec.json`（由 `example-gen.py` 生成，对应 `example-input.jpg`，效果见 `example-plan2d.png`）。

## 坐标约定

- 单位 **mm**；x 向右（东），**y 向下（南）**。原点随意，一般取墙体外轮廓左上角（analyze.py 就是这么取的）。
- 墙坐标是**墙中线**。外墙中线 = 外皮往里缩半个墙厚。
- 墙的端点要落在另一面墙的中线上才算连接。40mm 以内会自动吸附；T 形交接、十字交叉会自动打断。
- 房间不用画：墙围合的区域会自动识别成房间，`rooms` 只是在房间里放一个标签点，用来命名、定材质。

## 结构

```jsonc
{
  "name": "XX小区 3-1201 · 三室两卫",   // 方案名，也用作网页标题
  "height": 2800,                        // 层高
  "phase": "renovate",                   // renovate（默认，可直接布置）| original（原始结构阶段）
  "north": 0,                            // 可选：指北方向。平面“上方”相对正北顺时针偏转的角度
  "walls": [
    {
      "a": [x, y], "b": [x, y],          // 中线两端
      "t": 240,                          // 厚度。外墙/承重墙常见 200–240，隔墙 100–120
      "bearing": true,                   // 承重墙（不填时 t ≥ 180 视为承重）
      "openings": [
        { "type": "door", "from": 3620, "to": 4500, "hinge": "from", "into": [4000, 7200] },
        { "type": "window", "from": 5200, "to": 6900, "sill": 900 }
      ]
    }
  ],
  "rooms": [ { "at": [x, y], "name": "主卧", "mat": "walnut", "wallMat": "latexSage" } ],
  "structs": [ { "kind": "sewer", "at": [x, y] } ],
  "beams": [ { "a": [x, y], "b": [x, y], "w": 200, "depth": 400 } ],
  "furniture": [ { "key": "bed18", "at": [x, y], "rot": 90 } ],
  "elec": [ { "kind": "socket", "at": [x, y], "rot": 0 } ],
  "underlay": { "image": "户型图.jpg", "mmPerPx": 17.65, "x": -4413, "y": -1342 }
}
```

### 门窗 openings

| 字段 | 说明 |
|---|---|
| `type` | `door` 单开门、`double` 双开门、`sliding` 推拉门、`window` 窗、`bay` 飘窗（**往墙外凸出**的那种）、`hole` 门洞 |
| `from`, `to` | 洞口两端。**水平墙填 x 坐标，竖直墙填 y 坐标**（斜墙填到 a 点的距离）。直接用世界坐标，不用管墙的方向 |
| `hinge` | 门轴在 `from` 端还是 `to` 端（默认 `from`）。看原图门扇那条直线连着洞口哪一端 |
| `into` | 门往哪一侧开：填门扇扫过那一侧的任意一点，一般取门开进去的房间里的一点。不填就开向墙法线正方向 |
| `sill`, `head` | 离地高度 / 洞口顶高。默认：门 0/2100，推拉门 0/2400，窗 900/2400，飘窗 450/2400。卫生间高窗用 sill 1400 |
| `entry` | 入户门设为 `true` |

原图里窗台板画在**墙内侧**（室内一条白色窗台）的，用 `window`，sill 设 450，不要用 `bay`。

### 房间 rooms

- `at` 必须落在墙围合的区域里面（check.mjs 会报 `labelsOutsideRooms`）。
- 一个区域放多个标签会合并显示（如“客厅 + 餐厅”）。开放空间通常只放一个标签。
- `mat` 地面材质。不填时按名字猜：卫/厨 → `bath`，阳台/露台 → `deck`，客餐厅/过道 → `tile`，主卧 → `walnut`，其余 → `oak`。
  可选值：`oak` 橡木、`walnut` 胡桃木、`herring` 人字拼、`tile` 灰白大板、`marble` 米白大理石、`cement` 微水泥、`bath` 防滑砖、`terrazzo` 水磨石、`deck` 户外木塑。
- `wallMat` 墙面：`latexWhite`、`latexGrey`、`latexSage`、`latexWarm`、`wallpaper`、`wallTile`、`woodPanel`。卫生间/厨房不填时自动用 `wallTile` 和 300mm 平顶吊顶。
- `ceil` 吊顶：`{ "type": "none" | "flat" | "edge", "drop": 250, "edgeW": 450, "cove": true }`（edge 是边吊，cove 是灯带）。
- `skirting` 踢脚线：`none` | `wood` | `metal`。

### 结构 structs

`kind`：`column` 柱（400×400）、`shaft` 管井（600×400）、`flue` 烟道（450×350）、`drain` 地漏、`sewer` 马桶下水口。
可填 `w`、`d`、`rot`。原图标了的就画上；马桶下水口一般在马桶中心靠墙一侧，离墙约 300。

### 家具 furniture

`at` 是家具中心。`rot` 是朝向（度）：家具“背面”默认朝北（-y）。
**rot 0 = 背靠北墙、90 = 背靠东墙、180 = 背靠南墙、270 = 背靠西墙**。
放在墙边时：中心离墙内皮 = 深度/2（墙内皮 = 墙中线 ± t/2）。`w` 指左右宽，`d` 指前后深，可以覆盖默认尺寸。

| key | 名称 | 默认 w×d×h |
|---|---|---|
| bed18 / bed15 / bed12 | 双人床 1.8 / 1.5、单人床 1.2 | 1800×2100、1500×2050、1200×2000 |
| nightstand | 床头柜 | 500×420 |
| wardrobe | 衣柜 | 2000×600×2400 |
| cabWardrobe / cabSlide | 定制衣柜 / 推拉门衣柜 | 2400×600 / 2000×650 |
| cabTall / cabBase / cabWall / cabTV | 书柜高柜 / 地柜 / 吊柜 / 悬空电视柜 | 1200×400 / 1600×600 / 1600×350 / 2400×400 |
| desk / officeChair / bookshelf | 书桌 / 办公椅 / 书架 | 1200×600 / 600×600 / 900×350 |
| sofa / armchair | 三人沙发 / 单人沙发 | 2200×950 / 850×850 |
| coffeeTable / tvCabinet | 茶几 / 电视柜 | 1200×600 / 2000×400 |
| diningTable / chair | 餐桌 / 餐椅 | 1600×900 / 460×520 |
| counter / fridge | 开放式橱柜 / 冰箱 | 2100×600 / 700×700 |
| shoeCabinet / rug / plant | 鞋柜 / 地毯 / 绿植 | 1200×350 / 2000×1700 / 500×500 |
| toilet / vanity / shower / bathtub | 马桶 / 浴室柜 / 淋浴房 / 浴缸 | 400×700 / 800×500 / 900×900 / 1600×750 |
| washer / lounge / sideTable / island | 洗衣机 / 休闲椅 / 边几 / 衣帽岛台 | 600×600 / 700×750 / 500×500 / 1200×600 |

餐椅围着餐桌：桌 rot 0 时，椅子放在桌子南北两侧，北侧椅 rot 0、南侧椅 rot 180。
椅子推进桌下、边几靠沙发这些重叠是允许的，不会报错。

### 水电 elec（可选）

`kind`：`socket` 五孔、`socketW` 防水、`socket16` 16A、`socketAC` 空调、`switch1` 单控、`switch2` 双控、`light` 主灯、`downlight` 筒灯、`panel` 强电箱、`weak` 弱电箱、`net` 网络、`tv` 电视、`cold` 冷水、`hot` 热水。
墙上点位的 `at` 放在墙内皮上，`rot` 是面朝方向：0 朝南、180 朝北、-90 朝东、90 朝西。灯具放房间里，rot 填 0。`h` 离地高度有默认值。
用户没要求就不画，用户可以自己在“水电”图层里加。

### 底图 underlay

`build.py` 会把原图打包成底图（默认隐藏，用户可在左侧“户型”面板勾选显示、调透明度）。
`mmPerPx` 是比例，`x`、`y` 是图片左上角的世界坐标（mm）。analyze.py 输出的 draft.json 已经算好；
如果你换了原点，`x = -OX * mmPerPx`，`y = -OY * mmPerPx`（OX、OY 是原点在图上的像素位置）。
