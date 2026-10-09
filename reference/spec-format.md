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
  "north": 0,                            // 可选：指北针在图上指的方向，相对图纸上方顺时针多少度（指北针朝上 = 0，朝右 = 90）
  "site": { "city": "上海", "month": 9 },  // 可选：日照模拟的城市（自动查纬度）和月份
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
  "autoElec": true,                      // 自动布置全套水电并关联开关（推荐）
  "look": { "style": "real", "palette": "plan" }, // 可选：3D 视觉风格与配色，见下文
  "underlay": { "image": "户型图.jpg", "mmPerPx": 17.65, "x": -4413, "y": -1342 }
}
```

### 门窗 openings

| 字段 | 说明 |
|---|---|
| `type` | 门：`door` 单开门、`double` 双开门、`unequal` 子母门（大扇 2/3，在 hinge 一端）、`sliding` 推拉门、`folding` 折叠门、`pocket` 隐形推拉门（门扇藏进 hinge 一端的墙里）、`hole` 门洞/垭口<br>窗：`window` 平开窗、`slideWindow` 推拉窗、`floorWindow` 落地窗（自带室内护栏）、`highWindow` 高窗、`bay` 飘窗（**往墙外凸出**的那种） |
| `from`, `to` | 洞口两端。**水平墙填 x 坐标，竖直墙填 y 坐标**（斜墙填到 a 点的距离）。直接用世界坐标，不用管墙的方向 |
| `hinge` | 门轴在 `from` 端还是 `to` 端（默认 `from`）。看原图门扇那条直线连着洞口哪一端 |
| `into` | 门往哪一侧开：填门扇扫过那一侧的任意一点，一般取门开进去的房间里的一点。不填就开向墙法线正方向 |
| `sill`, `head` | 离地高度 / 洞口顶高。默认：门 0/2100，推拉门、折叠门 0/2400，窗 900/2400，落地窗 0/2500，高窗 1500/2100，飘窗 450/2400 |
| `entry` | 入户门设为 `true` |

原图里窗台板画在**墙内侧**（室内一条白色窗台）的，用 `window`，sill 设 450，不要用 `bay`。
怎么从户型图判断窗型：
- 窗线一直画到地面、通常在客厅/卧室朝阳台或外墙的大面宽 → `floorWindow`
- 窗线里画了两段错开的窗扇 → `slideWindow`；普通三线窗 → `window`
- 卫生间、厨房很窄的窗，或图上虚线画的窗 → `highWindow`
- 厨房、阳台门画成折线 → `folding`；入户门一大一小两扇 → `unequal`

### 房间 rooms

- `at` 必须落在墙围合的区域里面（check.mjs 会报 `labelsOutsideRooms`）。
- 一个区域放多个标签会合并显示（如“客厅 + 餐厅”）。开放空间通常只放一个标签。
- `mat` 地面材质。不填时按名字猜：卫/厨 → `bath`，阳台/露台 → `deck`，客餐厅/过道 → `tile`，主卧 → `walnut`，其余 → `oak`。
  可选值：`oak` 橡木、`walnut` 胡桃木、`herring` 人字拼、`tile` 灰白大板、`marble` 米白大理石、`cement` 微水泥、`bath` 防滑砖、`terrazzo` 水磨石、`deck` 户外木塑。
- `wallMat` 墙面：`latexWhite`、`latexGrey`、`latexSage`、`latexWarm`、`wallpaper`、`wallTile`、`woodPanel`。卫生间/厨房不填时自动用 `wallTile` 和 300mm 平顶吊顶。
- `ceil` 吊顶：`{ "type": "none" | "flat" | "edge", "drop": 250, "edgeW": 450, "cove": true }`（edge 是边吊，cove 是灯带）。
- `skirting` 踢脚线：`none` | `wood` | `metal`。
- `tile` 自定义铺砖（可选，写了就按砖一块块铺，覆盖 `mat` 的预设纹理；不写的字段用默认值）：
  ```json
  "tile": { "w": 800, "h": 800, "gap": 2, "pattern": "grid", "color": "#e6e1d8", "grout": "#c4beb4", "tex": "marble", "origin": "center" }
  ```
  - `w` / `h` 砖的长宽 mm（常见 300×300、300×600、600×600、600×1200、750×1500、800×800、900×1800；木纹砖 200×1200、150×900）
  - `gap` 灰缝 mm（常见 1~3，仿古砖 3~5）
  - `pattern`：`grid` 直铺对缝、`half` 工字铺（1/2 错缝）、`third` 1/3 错缝、`diag` 斜铺 45°、`herring` 人字拼、`basket` 田字编织、`checker` 双色棋盘（配 `color2`）、`random` 随机错缝（木纹砖）
  - `tex` 砖面纹理：`plain` 素色、`marble` 大理石纹、`stone` 石纹、`wood` 木纹、`terrazzo` 水磨石、`cement` 水泥灰
  - `color` 砖色、`color2` 棋盘第二色、`grout` 缝色
  - `origin`：`center` 房间居中起铺（四周切砖一样大，默认）/ `corner` 左上墙角整砖起铺；`ox` / `oy` 起铺偏移 mm；`rot` 0 或 90

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
| bunkBed / crib / tatami | 上下床 / 婴儿床 / 榻榻米 | 1000×2000 / 1250×700 / 2000×2000 |
| nightstand / bedBench | 床头柜（台灯 3D 里可点亮）/ 床尾凳 | 500×420 / 1400×400 |
| wardrobe / dresser / mirror | 衣柜 / 梳妆台 / 穿衣镜 | 2000×600×2400 / 1000×450 / 600×60 |
| cabWardrobe / cabSlide | 定制衣柜 / 推拉门衣柜 | 2400×600 / 2000×650 |
| cabTall / cabBase / cabWall / cabTV | 书柜高柜 / 地柜 / 吊柜 / 悬空电视柜 | 1200×400 / 1600×600 / 1600×350 / 2400×400 |
| desk / officeChair / bookshelf | 书桌 / 办公椅 / 书架 | 1200×600 / 600×600 / 900×350 |
| sofa / lSofa / armchair | 三人沙发 / L 形转角沙发（贵妃位在 rot 0 时的西侧，即局部 -x 端）/ 单人沙发 | 2200×950 / 2800×1700 / 850×850 |
| coffeeTable / tvCabinet | 茶几 / 电视柜（含电视，3D 里可开关） | 1200×600 / 2000×400 |
| diningTable / chair / sideboard | 餐桌 / 餐椅 / 餐边柜 | 1600×900 / 460×520 / 1600×400×2200 |
| kitchenIsland / barStool | 中岛台 / 吧椅 | 1800×900 / 400×400 |
| shoeCabinet / entryBench / piano | 鞋柜 / 换鞋凳 / 立式钢琴 | 1200×350 / 900×350 / 1500×600 |
| rug / plant | 地毯 / 绿植 | 2000×1700 / 500×500 |
| counter / fridge / fridgeDouble | 整体橱柜（含水槽灶台烟机）/ 冰箱 / 对开门冰箱 | 2100×600 / 700×700 / 910×720 |
| hood / microwave / dishwasher / tallOven / purifier | 油烟机（挂墙）/ 微波炉 / 洗碗机 / 电器高柜 / 台下净水器 | 900×520 / 480×380 / 600×600 / 600×600 / 400×200 |
| acWall / acFloor | 挂机空调（离地 2150）/ 柜机空调 | 900×260 / 520×380 |
| waterHeater / gasHeater | 电热水器（离地 1800）/ 燃气热水器（离地 1400） | 800×450 / 360×180 |
| waterDispenser / airPurifier / robotVac / treadmill | 饮水机 / 空气净化器 / 扫地机器人基站 / 跑步机 | 320×330 / 380×250 / 380×420 / 800×1800 |
| wallTV | 壁挂电视（离地 850，3D 里可开关） | 1450×60 |
| floorLamp / deskLamp | 落地灯 / 台灯（3D 里可点亮；台灯默认 z 750 放桌上） | 400×400 / 250×250 |
| curtain / sheer | 落地窗帘 / 纱帘（3D 里可开合）：rot 让背面朝窗，w 比窗宽 200~400 | 2400×160 / 2400×120 |
| toilet / vanity / mirrorCabinet | 马桶 / 浴室柜（含镜）/ 镜柜（挂墙） | 400×700 / 800×500 / 800×150 |
| shower / showerScreen / bathtub | 淋浴房 / 一字淋浴隔断 / 浴缸 | 900×900 / 1200×80 / 1600×750 |
| towelWarmer / bathHeater | 电热毛巾架（挂墙）/ 风暖浴霸（吸顶，自动贴顶） | 500×100 / 300×300 |
| washer / dryer / laundrySink / clothesRack | 洗衣机 / 烘干机 / 洗衣池柜 / 升降晾衣架（吸顶） | 600×600 / 600×620 / 700×550 / 2400×450 |
| lounge / sideTable / island | 休闲椅 / 边几 / 衣帽岛台 | 700×750 / 500×500 / 1200×600 |
| bed20 / roundBed | 双人床 2.0m / 圆床 | 2000×2200 / 2200×2200 |
| chest / fileCabinet / coatRack / stool | 五斗柜 / 文件柜 / 衣帽架 / 圆凳化妆凳 | 900×480 / 450×550 / 500×500 / 400×400 |
| lDesk / kidsDesk / gamingChair / bayCushion | L 形书桌 / 儿童学习桌 / 电竞椅 / 飘窗垫 | 1600×1400 / 1000×600 / 700×700 / 1800×500 |
| loveseat / uSofa / curvedSofa / chaise | 双人沙发 / U 形沙发 / 弧形沙发 / 贵妃椅 | 1600×900 / 3200×2000 / 2600×1100 / 1700×750 |
| beanbag / ottoman / rockingChair / hangingChair | 懒人沙发 / 圆脚凳 / 摇椅 / 吊椅 | 900×900 / 550×550 / 700×950 / 1000×1000 |
| roundCoffee / roundTable / longTable / booth / diningBench | 圆茶几 / 圆餐桌 / 8 人长餐桌 / 卡座 / 餐凳 | 900 / 1300 / 2400×1000 / 1800×600 / 1400×350 |
| wineCabinet / displayCabinet / consoleTable / hallCabinet | 酒柜 / 玻璃展示柜 / 玄关桌 / 玄关柜（中空） | 900×450 / 1000×400 / 1200×350 / 1200×400 |
| fireplace / fishTank / projScreen / speaker / screenDivider | 电壁炉 / 鱼缸 / 投影幕布（挂墙）/ 落地音箱 / 屏风 | 1400×400 / 1200×450 / 2400×80 / 300×350 / 1800×40 |
| bigPlant / smallPlant / hangingPlant / floorVase | 大型绿植 / 小盆栽 / 吊兰（吸顶）/ 落地花瓶 | 800 / 300 / 400 / 350 |
| wallArt / wallArt3 / wallClock | 装饰画 / 三联装饰画 / 挂钟（都挂墙） | 900×40 / 1500×40 / 400×50 |
| roundRug / doormat / fan / radiator | 圆地毯 / 门口地垫 / 落地扇 / 暖气片 | 2000 / 900×600 / 400 / 1000×100 |
| lCounter / freezer / trashBin / fridgeFrench | L 形橱柜（长边靠背墙，短边在左）/ 冰柜 / 垃圾桶 / 法式多门冰箱 | 2400×1800 / 1000×600 / 300 / 830×700 |
| wallToilet / squatToilet / doubleVanity / pedestalSink | 壁挂马桶 / 蹲便器 / 双盆浴室柜 / 立柱盆 | 380×550 / 450×600 / 1400×550 / 500×450 |
| freeTub / bathShelf | 独立浴缸 / 置物架 | 1700×800 / 600×250 |
| outdoorSet / plantShelf / bike / yogaMat / catTree / petBed | 户外桌椅（带遮阳伞）/ 花架 / 动感单车 / 瑜伽垫 / 猫爬架 / 宠物窝 | 1600 / 1000×350 / 550×1100 / 610×1830 / 600 / 700×550 |

挂墙、吸顶的家具（空调、热水器、油烟机、壁挂电视、浴霸、晾衣架……）和落地家具上下错开，可以叠在床、马桶、洗衣机上方，不算重叠。
家电要放齐：每个卧室和客厅一台空调；卫生间一台热水器（电热水器挂在马桶或淋浴上方）或在厨房/阳台放燃气热水器；
厨房橱柜 + 冰箱（空间够再加洗碗机、电器高柜）；阳台洗衣机（+ 烘干机叠放或并排、晾衣架）；客厅电视柜或壁挂电视；卫生间浴霸；
落地窗、卧室窗前放窗帘。

餐椅围着餐桌：桌 rot 0 时，椅子放在桌子南北两侧，北侧椅 rot 0、南侧椅 rot 180。
椅子推进桌下、边几靠沙发这些重叠是允许的，不会报错。

### 水电 elec / autoElec

**默认写 `"autoElec": true`**：设计器会按房间名字、门窗位置和已摆的家具自动生成整套点位并关联开关：
每个房间主灯（餐桌上方吊灯）和门锁一侧的开关（卧室门口 + 床头双控，卫生间/阳台开关放门外），入户门旁强电箱、弱电箱、可视对讲，
床头柜 / 书桌 / 电视柜 / 沙发两侧插座，橱柜的台面插座、烟机插座、冷热水、排水、燃气，马桶智能插座和冷水，浴室柜、淋浴、热水器的水电，
洗衣机防水插座和水点，空调插座和空调孔（没放空调的卧室/客厅在窗边预留）。所以**先把家具（尤其家电、洁具）摆对，水电就跟着对**。

也可以手写 `elec`（和 autoElec 一起写时手写的在前，自动的不会在同一位置重复放）：
- 强电：`socket` 五孔、`socketUSB` USB、`socketW` 防水、`socket16` 16A、`socketAC` 空调、`socketHood` 烟机、`socketFloor` 地插、`panel` 强电箱
- 开关：`switch1` 单控、`switch2` 双控、`switch3` 三开、`dimmer` 调光
- 灯具：`light` 吸顶灯、`pendant` 吊灯、`downlight` 筒灯、`spot` 射灯、`wallLamp` 壁灯（挂墙）
- 弱电：`weak` 弱电箱、`net` 网络、`tv` 电视、`intercom` 可视对讲、`smoke` 烟感
- 给排水：`cold` 冷水、`hot` 热水、`waste` 墙排水；暖通燃气：`acHole` 空调孔、`freshAir` 新风口、`gas` 燃气

墙上点位的 `at` 放在墙内皮上，`rot` 是面朝方向：0 朝南、180 朝北、-90 朝东、90 朝西。灯具放房间里，rot 填 0。`h` 离地高度有默认值。
开关控制哪些灯：给灯写 `"id": "L1"`，开关写 `"links": ["L1"]`；不写 links 的开关自动关联同一房间的灯。
3D 里点击墙上的开关就能开关它关联的灯（双控两处都能控制，调光开关 关→暗→亮，三开 关→主灯→全开）；门、窗帘、电视、台灯/落地灯也都能点。

### 指北与日照 north / site（可选）

- `north`：户型图上一般有指北针（"北"字箭头）。指北针朝上写 0，朝右 90，朝左 -90，朝下 180；斜的按顺时针角度估。没有指北针就不写（默认 0，按“上北下南”）
- `site`：`{ "city": "北京", "month": 6 }`，城市从内置列表里选（哈尔滨、北京、上海、成都、广州、深圳、三亚等 29 个，自动查纬度），也可以直接写 `"lat": 39.9`。用户说了房子在哪个城市就写上
- 设计器里太阳位置按纬度、月份、时间真实计算（太阳赤纬 + 时角），3D 视图 ☀ 面板可以拖时间（0~24 点）、换城市和月份、调指北，有“日照演示”从日出放到深夜；太阳落山后换成月亮和星空

### 3D 视觉风格 look（可选）

`{ "style": "real" | "diorama" | "colorplan", "palette": "plan" | 色板 id, "glow": true, "labels": true, "round": true }`

- `style`：`real` 写实（默认）；`diorama` 沙盘效果图（实物微缩模型感）：清晰的日光阴影、环境光遮蔽、加厚底座投影到背景、移轴景深、底座外沿暖光、地面房间名、圆润家具
- `colorplan` 彩平图：正上方俯视、不变形的彩色平面图（售楼处 / 设计公司那种）。地面用真实材质纹理，墙剖到约 1.1m、墙顶压深色，家具带柔和投影和环境光遮蔽，吊顶上和挂在高处的东西不画；叠加房间名 + 面积、外围两道尺寸线、指北针。此模式只能平移和缩放，不能漫游；配色同样生效
- `tilt`：沙盘鸟瞰时的微缩移轴景深，默认开
- `cpDims`：彩平图上的尺寸，`simple` 简洁（默认：外围总尺寸 + 房间名下的开间 × 进深）/ `full` 完整（三道尺寸线）/ `none` 不标。彩平图是给业主看的展示图，一般用简洁；要当施工参考时用完整
- `palette`：`plan` 方案原色（默认，直接用方案里的材质颜色）；主题色板：`cream` 奶油白、`wood` 原木、`morandi` 莫兰迪、`wabi` 侘寂、`nordic` 北欧、`midcentury` 中古、`chinese` 新中式、`french` 法式、`industrial` 工业风、`mono` 极简黑白、`coastal` 海风、`dusk` 深色夜景
- 色板只改 3D 显示（鸟瞰、漫游、渲染出图都生效），不改方案材质；用户在 3D 视图的「🎨 风格」里随时切换，随方案保存
- 用户没提就不写（默认写实 + 方案原色）；用户说“沙盘效果图 / 彩平图 / 奶油风 / 某种风格的效果”时写上对应值

### 底图 underlay

`build.py` 会把原图打包成底图（默认隐藏，用户可在左侧“户型”面板勾选显示、调透明度）。
`mmPerPx` 是比例，`x`、`y` 是图片左上角的世界坐标（mm）。analyze.py 输出的 draft.json 已经算好；
如果你换了原点，`x = -OX * mmPerPx`，`y = -OY * mmPerPx`（OX、OY 是原点在图上的像素位置）。
