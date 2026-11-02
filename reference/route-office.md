# 办公 / 培训 / 商业楼层（写字楼标准层、核心筒）

### 办公 / 培训 / 商业楼层（写字楼标准层、核心筒）

和住宅的区别：没有卧室厨房，房间是**培训室、会议室、讨论室、开放办公、前台、茶水间、公共卫生间、核心筒（电梯厅、电梯井、消防楼梯、前室、强弱电间、管井）**；
外墙多是**玻璃幕墙**（`glassWall`，`sill` ≈ 300~500 是幕墙下的窗槛墙 / 防火层）；层高按图上的装修完成面（没写就按 3.0~3.2m 展示并说明）。
- **核心筒**：剪力墙厚 200~600、涂黑 = 承重（`bearing: true`）；电梯井里放 `elevator`（只是展示轿厢，单层不能乘坐）、层门用 `sliding`；消防楼梯用两段 `stairRun`（本层只到半层平台，不要编造上下层）；
  前室、电梯厅的门多是甲级防火门（`fireRating: "甲级"`，双开 `double`）。**电梯厅、前室、设备间每间都要有门**（看原图的门弧），否则通道检查不通。
- **公共卫生间**：厕位隔断是 60 厚的薄墙（`t: 60`）+ 每格一扇门（`into` 朝厕位里）；马桶 `toilet`（每个配 `sewer` 下水口）、小便器 `urinal`、洗手台 `vanity`、拖布池 `serviceSink`、地漏 `drain`；管井 `shaft` 放准（排水接它）。
- **培训 / 会议**：培训桌 `trainingTable`（直排）、`curveTrainingTable`（弧形 / 折线长桌，`opt.outline` 照原图描桌面轮廓，桌面能是任意多边形）、培训椅 `trainingChair`（椅子面朝桌子 / 讲台，按每个座位算朝向）、讲台 `lectern`、地台 `stage`、升降黑板 `slidingBoard`、移动会议平板 `mobileDisplay`、会议桌 `conferenceTable`、圆形洽谈桌 `roundMeeting`；
  办公：`officeDesk` / `deskBench2` / `deskBench4` 工位、`bossDesk` 大班台、`officeChair`、`lockers` 储物柜、`reception` 前台、`printer`、茶水间 `pantryCounter` + `coffeeMachine` + `waterDispenser`。
- **顶面设备**（吸顶，`ceil`）：送风口 `supplyVent`、回风口 `returnVent`、无线 AP `wifiAP`（autoElec 在吊顶里给它配网口，PoE 网线走顶）、嵌入式音箱 `ceilingSpeaker`。
- **水电**：强电间放强电箱 `panel`、弱电间放弱电箱 `weak`（照原图，不放入户门旁）；会议桌、工位离墙远的自动出地插 + 地面网口；茶水间台面有水槽时放小厨宝（`waterHeater` 放进地柜）或在 spec 里说明没有热水。
  茶水间离管井远时排水会提示“横走 xx m 要垫高 / 污水提升器”——这是真实施工问题，交付时告诉用户。
- 整层办公 1000㎡ 左右，管线自动排一次约 3 秒（打开水电图层时），属正常。
- 公共部分（核心筒）的房间名用“电梯厅 / 前室 / 楼梯间 / 强电井 / 弱电井 / 风井 / 管井 / 走道”：autoElec 认这些名字，**入户门在公共一侧的强弱电箱、对讲不放**（只放户内）；手写了 `panel` / `weak` 就不再自动放。
- 井道设备：立管 `riser`（Φ110 通高）、表箱 `meterBox`、百叶 `louver`、空调外机 `acOutdoor`，见 furnishing.md「图上符号逐项清点」。
