"""示例：写字楼培训层（装修公司“家具布置图”DXF，上下两张图里还原下面那张布置图）。读入 cadsplit 初稿 + 量出的墙面 + DXF 家具块 / 文字 / 门弧，逐项写成 spec。
家具全部按叶子块（dxfaudit.py blocks → deep_blocks.json）的插入点 / 旋转 / 镜像算朝向；P_02 / P_09 固装柜、P_03 台面、T_07 条形风口、P_19 窗帘、J-DOOR 门都照图；
墙面、门洞用 dxfaudit.py q 逐处量过，再用 walls / doors / furn 三项对账到只剩能解释的条目。依赖的 json（deep_blocks / groups / hall_floor_lines / slot_diffusers / curtains）都在工作目录里。"""
from pathlib import Path
import json,math,sys,collections
import numpy as np
ROOT=Path(__file__).resolve().parent
V=json.loads((ROOT/'vectors.json').read_text(encoding='utf-8'))
# Preserve the parser draft as evidence; corrected geometry comes from measured faces.
S=json.loads((ROOT/'split/building_draft.json').read_text(encoding='utf-8'))['floors'][0]
S.update(name='办公培训中心 · 家具布置方案',height=3200,walls=[],rooms=[],structs=[],furniture=[],elec=[],voids=[],autoElec=True)
S.pop('_candidates',None)
S['underlay']={'image':'source-underlay.png','mmPerPx':10,'x':-1000,'y':0}
S['look']={'style':'real','palette':'plan'}
S['_source']={'file':'家具布置图.dxf','drawing':'下方家具布置图','origin_cad':[320000,-130000],'units':'mm，标注/图形长度比核对约0.9994','height_note':'3200mm 为展示层高，原图未给出明确装修完成面层高','north_note':'未确认指北方向，日照方位暂用默认值'}
def half(x):return round(x*2)/2
def W(a,b,t=200,bearing=False,ops=None,status='existing',flush=None):
    w={'a':[half(v) for v in a],'b':[half(v) for v in b],'t':t,'bearing':bearing,'status':status}
    if flush:w['flush']=flush
    if ops:w['openings']=ops
    S['walls'].append(w);return w
def H(y,x0,x1,t=200,**kw):return W((x0,y),(x1,y),t,**kw)
def N(x,y0,y1,t=200,**kw):return W((x,y0),(x,y1),t,**kw)
def op(w,fr,to,typ='door',**kw):
    k=0 if abs(w['a'][1]-w['b'][1])<1 else 1
    lo,hi=sorted((w['a'][k],w['b'][k]))
    if fr<lo-1 or to>hi+1:return
    w.setdefault('openings',[]).append({'type':typ,'from':half(fr),'to':half(to),**kw})
def F(key,x,y,rot=0,**kw):
    f={'key':key,'at':[half(x),half(y)],'rot':rot,**kw};S['furniture'].append(f);return f
def room(name,x,y,mat='tile'):
    S['rooms'].append({'name':name,'at':[x,y],'mat':mat,'wallMat':'latexWarm','ceil':{'type':'flat','drop':200,'cove':False}})

# Curtain wall follows the actual notch and service-lift projection.
outline=[(1980.3,1188.5),(29055.3,1188.5),(29055.3,3988.5),(40780.3,3988.5),(40780.3,31138.5),(1980.3,31138.5),(1980.3,19363.5),(105.3,19363.5),(105.3,13018.5),(1980.3,13018.5)]
for a,b in zip(outline,outline[1:]+outline[:1]):
    glass=not (min(a[0],b[0])<1900)
    w=W(a,b,100 if glass else 200)
    if glass:
        k=0 if a[1]==b[1] else 1;lo,hi=sorted((a[k],b[k]));op(w,lo,hi,'glassWall',sill=340,head=3000,name='外幕墙／消防救援窗',material='glass')

# North suites and stepped corridor boundary, measured in the original mm coordinates.
N(8005.3,1188.5,10813.5,200)
# 走廊北墙：原图只有西头 2255~3715（核心筒转角）和杂物间那段有墙，卫生间前室 3715~7905 直接开向走廊
H(10813.5,1980.3,3617.3,200)
# 水井（SJ）东墙：原图 3517 / 3717 两条墙线，585 检修门门轴 (3615, 11079) 往东开
sj=N(3617.3,10813.5,13093.5,200);op(sj,11079.3,11664.3,hinge='from',into=[3900,11370],name='水井检修门');room('水井',2800,12000,'cement')
H(10813.5,8005.3,11055.3,200)
N(11055.3,10263.5,10813.5,200)
H(10263.5,11055.3,20055.3,200)
N(17230.3,10263.5,10913.5,200)  # 北水吧东侧挡墙（Q_06 17130~17330，伸进走廊 550 后收口）
H(10813.5,22780.3,29055.3,200)
lounge=H(10263.5,20055.3,22780.3,200);op(lounge,20855.3,22555.3,'double',into=[21705,9600],name='休息厅双开门')
N(22780.3,10263.5,10813.5,200)
# 北走廊中段、会议区门厅：200 隔墙 + 1600 双开门（P_04 门扇 2 × 800，开向西）
mid=N(25555.3,10813.5,13093.5,200);op(mid,11002.3,12705.3,'double',into=[25000,11850],name='走廊双开门')
foy=N(25555.3,22713.5,25018.5,200);op(foy,23027.3,24727.3,'double',into=[25000,23877],name='会议区门厅双开门')
room('北走廊（东段）',27300,11850,'tile');room('会议区门厅',27300,23850,'marble')
fold=N(20055.3,1188.5,10263.5,100);op(fold,2763.5,9713.5,'folding',head=3000,name='内嵌折叠隔断',material='glass')
N(11505.3,1188.5,10263.5,200)
# Toilet / store and washbasin zones; the central shaft is preserved.
H(3963.5,1980.3,6399.5,100)
N(6399.5,3963.5,7263.5,100)
H(7263.5,1980.3,6399.5,200)
N(4925.3,7263.5,9898.5,200)
N(2715.3,7263.5,9898.5,200)
H(8063.5,2715.3,4925.3,200)
H(9898.5,2715.3,6163.5,200)
room('管井',3800,8800,'cement')
# 女卫入口：原图 P_07 完成面线 y 4484.7 / 4649.9（厚 165），门扇 P_04 门轴 (7658, 4538.8)、宽 1000、往北开
ent=H(4567.3,6399.5,8005.3,165);op(ent,6660,7710,hinge='to',into=[7100,4000])
# Two equipment rooms on the north/east interface.
N(27590.3,2613.5,8303.5,130)
H(2613.5,27590.3,29055.3,100)
H(7263.5,27590.3,29055.3,200)
H(8303.5,27590.3,29055.3,200)
# The right training room and west support suites meet the structural core.
N(29055.3,3988.5,31138.5,200)

# Existing elevator/stair core: top/bottom faces vary in thickness.
# 核心筒南北墙：原图 Q_01 墙线——西段（到 11405）450 厚（北墙面 12793.5 / 13243.5，南墙面 19063.5 / 19513.5），东段 600 厚；
# 两段在走廊一侧墙面平齐，所以放在同一条中线上，西段用 flush 贴齐走廊那侧
H(13093.5,1980.3,11305.1,450,bearing=True,flush='N')
H(19213.5,1980.3,11305.1,450,bearing=True,flush='S')
top=H(13093.5,11305.1,29055.3,600,bearing=True)
bottom=H(19213.5,11305.1,29055.3,600,bearing=True)
N(3305.3,13093.5,19213.5,300,bearing=True)  # 原图 Q_01 墙面 3155.5 / 3455.5
N(8805.3,13093.5,19213.5,200,bearing=True)
N(11305.1,13093.5,19213.5,200,bearing=True)
N(14605.1,13093.5,19213.5,200,bearing=True)
N(17105.3,13093.5,19213.5,200,bearing=True)
N(18655.3,13093.5,19213.5,300,bearing=True)
N(21605.3,13093.5,19213.5,200,bearing=True)
N(24405.3,13093.5,19213.5,200,bearing=True)
N(27055.3,13093.5,19213.5,200,bearing=True)
H(16163.5,24405.3,29055.3,200,bearing=True)
H(16163.5,17105.3,18655.3,200,bearing=True)
H(18013.5,18655.3,21605.3,100)
# Mechanical risers in the west stairwell.
H(14313.5,5905.3,8805.3,100);N(5905.3,13093.5,17863.5,200,bearing=True)
N(7180.3,13093.5,14313.5,150);N(8030.3,13093.5,14313.5,150)

# South suites: front hall, pantry, discussion rooms, meeting room and offices.
N(6505.3,21413.5,31138.5,100)
N(11555.3,21963.5,25018.5,300);H(21963.5,11430.5,11555.3,300)  # 柱（10505~11605）以南、两个水吧台背靠背的新砌墙：Q_06 11405.3 ~ 11655.3 + 东侧完成面 P_07 11705.3 → 300 墙；起点埋在柱里，柱里接回原墙
# 25018.5 以南：新砌 200 墙（Q_07 11055~11255）+ 原墙（Q_01 10805~11255）外面再做 100 完成面（P_07 11355）→ 按 11055~11355 的 300 墙建，
# 西边凸出来的原墙段（10805~11055）按柱建；南端埋进 1100 方柱，柱里再接回外墙那段 350
N(11205.3,25018.5,30313.5,300);H(30313.5,11205.3,11430.5,300);N(11430.5,30313.5,31138.5,350)
S['structs'].append({'kind':'column','at':[11030.3,27713.5],'w':450,'d':4100})
# 讨论室2 东墙后面的两段原墙（Q_01 19505~20055 / 20055~20505），和上面一样按柱建
S['structs'] += [{'kind':'column','at':[19780.3,27864],'w':550,'d':3800},{'kind':'column','at':[20280.3,27714],'w':450,'d':4100}]
H(25018.5,11205.3,17645.3,250)  # 东头在 17645 收口（P_07 端头），和东墙之间是去讨论室的过道口
# 讨论室1 的门开在东侧隔墙上（P_04：门轴 (15530, 25344)，关门时门扇沿隔墙 25344~26344，开到 90° 贴着北墙），不在前厅那面装 LED 屏的墙上
d1=N(15555.5,25018.5,26673.5,200);op(d1,25343.5,26343.5,hinge='from',into=[15000,25850],name='讨论室1 门')
N(15555.3,26673.5,31138.5,200)
H(26673.5,15555.3,19400.3,200)
N(19400.3,25018.5,31138.5,210)
# 会议室北墙原图 200 厚（南侧墙面和讨论室北墙平齐、北侧错开 50mm）：按 250 厚和讨论室北墙连成一条，前厅一侧不留 50mm 错台
H(25018.5,19400.3,29055.3,250)
N(27835.3,25018.5,31138.5,200)
H(27213.5,27835.3,29055.3,200)  # 原图 Q_01 墙面 27113.5 / 27313.5
N(24905.3,19213.5,22713.5,200)
H(22713.5,24905.3,29055.3,200)
# Office lounge is separated by a sliding partition.
# 办公室玻璃移门隔断：原图 P_22 玻璃隔断 27113.5 / 27213.5
# 办公室：P_22 玻璃隔断 6605~9135 + 1000 平开门（P_04 门扇 9385~10385，门轴东端，往南开；标注门洞 9365~10405）
off=H(27163.5,6505.3,11205.3,100);op(off,6605.3,9135.3,'glassWall',name='办公室玻璃隔断');op(off,9365.3,10405.3,hinge='to',into=[9885,27700],name='办公室门')
# 办公区：P_22 玻璃隔断 6605~8835 + 1000 平开门（P_04 门扇 9085~10085，门轴东端，往南开；标注门洞 9065~10105）
offtop=H(21413.5,6505.3,11430.5,100);op(offtop,6605.3,8835.3,'glassWall',name='办公区玻璃隔断');op(offtop,9065.3,10105.3,hinge='to',into=[9585,21900],name='办公区门')
N(11430.5,21413.5,21963.5,350)
N(1980.3,13018.5,13093.5,100);N(1980.3,19213.5,19363.5,100)
# Separate the two cabins in each lift bank, including the service lifts.
for xa,xb in [(105.3,3305.3),(8805.3,11305.1),(14605.1,17105.3)]:H(16163.5,xa,xb,200,bearing=True)
# Public toilet cubicles. Their partitions are present in the DXF furniture plan.
# 公共卫生间厕位：原图 P_22_玻璃隔断 30 厚（两条线中线），前板分段之间就是 600 宽的门洞（门轴在洞口西头，往厕位里开）
for row,parts,x1,back,front,doors in [
    ('女',[3300.3,4212.3,5134.3,6056.3,6978.3],8005.3,1513.5,2869.1,[(3461.3,4061.3),(4373.3,4973.3),(5295.3,5895.3),(6217.3,6817.3),(7139.3,7739.3)]),
    ('男',[2270.3,3285.8,4301.4,5317.0],6399.5,3963.5,5529.1,[(2471.3,3086.3),(3494.3,4094.3),(4509.3,5109.3),(5532.0,6117.3)])]:
    H(back,parts[0],x1,100)
    stall=H(front,parts[0],x1,30)
    for x in parts:N(x,back,front,30)
    bounds=parts+[x1]
    for i,(lo,hi) in enumerate(doors):
        xa,xb=bounds[i],bounds[i+1]
        op(stall,lo,hi,hinge='from',into=[(xa+xb)/2,front-500])
        room(f'{row}卫厕位{i+1}',(xa+xb)/2,front-400,'bath')
# 清洁间东侧玻璃隔断（P_22 3285~3315），600 门洞 3084~3684，门轴在南端、开向清洁间
cl=N(3300.3,2869,3963.5,30);op(cl,3084.1,3684.2,hinge='to',into=[2800,3300],name='清洁间门')

# Recover door swings directly from vector ARC centres and endpoints.
for door in V['doors']:
    cx,cy=door['at'][0]-320000,door['at'][1]-130000;r=door['r']
    endpoints=[(cx+r*math.cos(math.radians(a)),cy-r*math.sin(math.radians(a))) for a in (door['a0'],door['a1'])]
    hits=[]
    for w in S['walls']:
        a,b=w['a'],w['b'];h=abs(a[1]-b[1])<1
        k=0 if h else 1;perp=1-k;c=a[perp]
        if abs((cy if h else cx)-c)>w['t']/2+120:continue
        e=min(endpoints,key=lambda p:abs(p[perp]-c))
        if abs(e[perp]-c)>w['t']/2+120:continue
        lo,hi=sorted(((cx,cy)[k],e[k]))
        if hi-lo<r*.8 or lo<min(a[k],b[k])-100 or hi>max(a[k],b[k])+100:continue
        hits.append((abs((cy if h else cx)-c),w,lo,hi,h))
    if hits:
        _,w,lo,hi,h=min(hits,key=lambda v:v[0]);mid=math.radians((door['a0']+door['a1'])/2)
        if door['a1']<door['a0']:mid+=math.pi
        into=[cx+r*.7*math.cos(mid),cy-r*.7*math.sin(mid)]
        if any(max(lo,v['from'])<min(hi,v['to'])-30 for v in w.get('openings',[])):continue
        op(w,lo,hi,hinge='from' if abs((cx if h else cy)-lo)<50 else 'to',into=[half(z) for z in into])
# Explicit entrances where source uses sliding/electric door symbols rather than arcs.
op(bottom,11505.3,14505.1,'sliding',head=2700,entry=True,name='主入口电动玻璃门',material='glass')
op(top,11669.3,14241.3,'double',head=2700,name='主电梯厅玻璃双开门',material='glass',into=[13000,12000])
# Lift doors and adjacent emergency stair access (existing core, not invented storeys).
for x in [3305.3,11305.1,14605.1,24405.3]:
    for w in S['walls']:
        if abs(w['a'][0]-x)<1 and abs(w['a'][0]-w['b'][0])<1 and w['a'][1]<14000:
            for lo,hi in [(14038.5,15438.5),(16888.5,18288.5)]:
                if not any(max(lo,v['from'])<min(hi,v['to'])-30 for v in w.get('openings',[])):op(w,lo,hi,'sliding',head=2500,name='电梯层门',material='metal')
# Complete the known corridor doors only when no arc has supplied one.
def ensure_door(w,lo,hi,typ='door',**kw):
    if not any(max(lo,q['from'])<min(hi,q['to'])-20 for q in w.get('openings',[])):op(w,lo,hi,typ,**kw)
for w in S['walls']:
    a,b=w['a'],w['b']
    if a==b:continue
    if a[1]==b[1] and abs(a[1]-10813.5)<1:
        if 8000<a[0]<9000:ensure_door(w,8705.3,10305.3,'double',into=[9500,10000])  # 杂物间双开门：P_04 门扇 2 × 800
    if a[1]==b[1] and abs(a[1]-10263.5)<1 and a[0]<18000<b[0]:
        # 双开门：P_04 两扇 800（门轴 17555 / 19155，开到 90° 在南侧走廊里），门槛石 17555~19155，标注门洞 17505~19205
        w['openings']=[o for o in w.get('openings',[]) if o['to']<17505 or o['from']>19205]
        op(w,17505.3,19205.3,'double',into=[18355,10900])
    if a[0]==b[0] and abs(a[0]-29055.3)<1:
        # 本图在这两处不画门、墙线断开（Q_01 10914~12794、22814~24944）→ 敞开的洞口；西北角 800 门（P_04 门扇 29256~29306，门轴在南端，开向西）
        ensure_door(w,10913.5,12793.5,'hole',name='培训厅北入口');ensure_door(w,22813.5,24943.5,'hole',name='培训厅南入口')
        ensure_door(w,8548.3,9348.3,hinge='to',into=[28700,8950])
    if a[1]==b[1] and abs(a[1]-25018.5)<1 and a[0]>19000:ensure_door(w,21005.3,22705.3,'double',into=[21900,26300])
    if a[1]==b[1] and abs(a[1]-26673.5)<1:ensure_door(w,15655.3,16555.3,into=[16800,28000])
    if a[1]==b[1] and abs(a[1]-22713.5)<1:ensure_door(w,26505.3,27405.3,into=[27000,21000])
    if a[0]==b[0] and abs(a[0]-6399.5)<1:ensure_door(w,6000,6900,into=[6000,6400])
    if a[1]==b[1] and abs(a[1]-7263.5)<1 and a[0]>27000:ensure_door(w,28005,28905,into=[28500,6500])

for name,x,y,mat in [
 ('女卫',4800,3300,'bath'),('男卫',4200,6200,'bath'),('洗手区',6500,9000,'bath'),('清洁间',2500,2800,'bath'),
 ('杂物间',9500,6500,'cement'),('内部培训室2 · 36席',15500,6000,'oak'),('休息厅 · 24席',23600,6000,'oak'),
 ('设备间（北）',28300,4500,'cement'),('消防前室（北）',28300,7800,'tile'),
 ('过廊',17000,11800,'tile'),('内部培训室 · 118席',35000,18100,'carpet'),
 ('酒店服务梯1',1800,14600,'cement'),('酒店服务梯2',1800,17600,'cement'),
 ('电梯厅1',4500,16200,'marble'),('消防楼梯1',7300,16400,'cement'),
 ('酒店客梯1',10000,14600,'cement'),('酒店客梯2',10000,17600,'cement'),
 ('主电梯厅',13000,16300,'marble'),('酒店客梯3',15800,14600,'cement'),('酒店客梯4',15800,17600,'cement'),
 ('楼梯设备井',17900,14600,'cement'),('楼梯设备区',17900,17600,'cement'),
 ('消防楼梯2',20200,15300,'cement'),('楼梯前室',20100,18600,'tile'),
 ('电梯厅2',23000,16000,'marble'),('公寓客梯1',25600,14600,'cement'),('公寓客梯2',25600,17600,'cement'),
 ('强电间',28100,14500,'cement'),('弱电间',28100,17800,'cement'),
 ('前厅',17500,22000,'marble'),('设备间（南）',27400,20700,'cement'),
 ('开放办公室',4100,25200,'oak'),('办公休息区',8800,24000,'oak'),('办公室',8800,29300,'oak'),
 ('讨论室1',13600,28100,'oak'),('讨论室2',17500,29000,'oak'),('会议室 · 12席',24000,27900,'oak'),
 ('会议设备间',28400,26100,'cement'),('会议储物间',28400,29100,'cement')]:room(name,x,y,mat)

# Original support rectangles, using their DXF boundaries, not the H symbol.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from dxf_prepare import flatten
import ezdxf
from ezdxf import bbox
doc=ezdxf.readfile(ROOT.parent/'家具布置图.dxf')
for e,layer in flatten(doc.modelspace()):
    if e.dxftype()!='POLYLINE' or layer!='Q_01_原始墙柱':continue
    b=bbox.extents([e],fast=True)
    if not b.has_data:continue
    p,q=b.extmin,b.extmax;w,d=b.size.x,b.size.y
    if not (319000<p.x<362000 and 130000<-q.y<163000 and 500<w<1600 and 500<d<1600 and len(e.vertices) in (4,6)):continue
    if p.x<324000 and -q.y>137000 and -q.y<143000:continue
    S['structs'].append({'kind':'column','at':[half((p.x+q.x)/2-320000),half(-(p.y+q.y)/2-130000)],'w':half(w),'d':half(d)})

# Furniture block inventory: composite groups are broken into actual editable pieces.
B=json.loads((ROOT/'blocks.json').read_text(encoding='utf-8'))
def block_f(i,key,rot=None,**kw):
    b=B[i];x0,y0,x1,y1=b['box'];r=b['rot'] if rot is None else rot
    return F(key,(x0+x1)/2-320000,(y0+y1)/2-130000,r,**kw)
# ---- 椅子：每一把都按 DXF 块的插入点、旋转、镜像算位置和朝向（正面 = 块定义里没有靠背的那一边）----
DB=json.loads((ROOT/'deep_blocks.json').read_text(encoding='utf-8'))
GR=json.loads((ROOT/'groups.json').read_text(encoding='utf-8'))
def front_rot(sx,sy,rot,fx,fy):
    """块局部正面方向 (fx, fy)（DXF y 朝上）→ 设计器 rot（正面 = rot2(0, 1, rot)，y 朝下）"""
    vx,vy=fx*sx,fy*sy;a=math.radians(rot);X=vx*math.cos(a)-vy*math.sin(a);Y=vx*math.sin(a)+vy*math.cos(a)
    return round(math.degrees(math.atan2(-X,-Y))%360,2)
# 块名 → (家具 key, 局部正面方向, 宽, 深, 名字)；正面方向看 deep-*.png 的块定义图（弧形靠背的对边是正面）
CHAIR_BLOCKS={'A$C93A2A354':('trainingChair',(0,1),600,577,'培训椅'),'SADFASFAF':('trainingChair',(0,-1),559,572,'培训椅'),
 '450FSY':('officeChair',(0,1),698,663,'会议椅'),'X-L2-MEETING_ROOM$0$X-L2-M':('chair',(0,-1),550,550,'会议椅'),
 '8':('officeChair',(0,-1),748,743,'办公椅'),'A$C911907E5':('officeChair',(-1,0),600,577,'讲师椅'),'RHREYRYWY':('officeChair',(0,1),660,667,'前台椅'),'A$C38F656A8':('armchair',(0,-1),807,790,'休闲单椅')}
for l in DB:
    c=CHAIR_BLOCKS.get(l['name'])
    if not c:continue
    key,(fx,fy),w,d,nm=c;k=abs(l['sx'])
    # DXF 里偶尔有两个块叠在同一位置（复制时多粘了一次）：只放一把
    if any(f['key']==key and math.dist(f['at'],(l['cx'],l['cy']))<50 for f in S['furniture']):continue
    F(key,l['cx'],l['cy'],front_rot(l['sx'],l['sy'],l['rot'],fx,fy),w=round(w*k),d=round(d*k),name=nm)
# ---- 圆桌 + 4 把椅子（$PLAN$00002692）：桌面是块里的圆（直径 760），椅子取每把的最大外轮廓，正面朝桌心 ----
for g in GR['$PLAN$00002692']:
    circ=max((p for p in g['parts'] if p[0]=='CIRCLE'),key=lambda p:p[6]);r=circ[6];cx=circ[2]+r;cy=circ[3]+r
    F('roundTable',cx,cy,w=2*r,d=2*r,name='圆形洽谈桌')
    polys=[p for p in g['parts'] if p[0]=='POLYLINE'];big=max(max(p[4],p[5]) for p in polys)
    outl=[p for p in polys if max(p[4],p[5])>big*.95]
    seen=[]
    for p in sorted(outl,key=lambda p:-p[4]*p[5]):
        px,py=p[2]+p[4]/2,p[3]+p[5]/2
        if any(math.dist((px,py),q)<200 for q in seen):continue
        seen.append((px,py));dx,dy=cx-px,cy-py;k=r/380
        F('chair',px,py,round(math.degrees(math.atan2(-dx,dy))%360,2),w=round(594*k),d=round(620*k),name='洽谈椅')
# ---- 会议室、两个讨论室的桌子：组合块里的桌面外框 ----
mt=[p for p in GR['º£ýˆ_06221636'][0]['parts'] if p[0]=='POLYLINE'][0]
F('conferenceTable',mt[2]+mt[4]/2,mt[3]+mt[5]/2,w=mt[4],d=mt[5],name='会议桌')
for nm,label in [('HY010','讨论桌'),('156','讨论桌')]:
    ls=[p for p in GR[nm][0]['parts'] if p[0]=='LINE'];xs=[p[2] for p in ls]+[p[2]+p[4] for p in ls];ys=[p[3] for p in ls]+[p[3]+p[5] for p in ls]
    F('conferenceTable',(min(xs)+max(xs))/2,(min(ys)+max(ys))/2,w=max(xs)-min(xs),d=max(ys)-min(ys),name=label)
# ---- 开放办公 8 个工位（块 27：600×1100 桌面 + 中间 50 厚屏风 + 端头挡板 + 椅子）----
for g in GR['27']:
    P=g['parts'];desk=[p for p in P if p[0]=='POLYLINE' and p[4]==600 and p[5]==1100][0]
    dx0,dy0=desk[2]+300,desk[3]+550
    arms=[p for p in P if p[0]=='POLYLINE' and abs(p[4]-425)<5 and abs(p[5]-53)<5]
    ax=(min(p[2] for p in arms)+max(p[2]+p[4] for p in arms))/2;ay=(min(p[3] for p in arms)+max(p[3]+p[5] for p in arms))/2
    east=ax>dx0  # 椅子在桌子东边 → 人面朝西
    F('trainingTable',dx0,dy0,270 if east else 90,w=1100,d=600,name='开放办公桌')
    F('officeChair',ax,ay,90 if east else 270,w=540,d=520,name='办公椅')
    side=[p for p in P if p[0]=='POLYLINE' and p[4]==50 and p[5]==1100][0];end=[p for p in P if p[0]=='POLYLINE' and p[4]==650 and p[5]==50][0]
    F('freeBox',side[2]+25,side[3]+550,0,w=50,d=1100,h=1150,color='#9aa3ad',name='工位屏风',opt={'shape':'box','mat':'fabric'})
    F('freeBox',end[2]+325,end[3]+25,0,w=650,d=50,h=1150,color='#9aa3ad',name='工位端头挡板',opt={'shape':'box','mat':'fabric'})
# ---- 办公室 L 形桌（块 A$CBAA38EBB：2000×800 桌面 + 400×1700 侧柜）----
lp=GR['A$CBAA38EBB'][0]['parts'];top=[p for p in lp if p[0]=='POLYLINE' and p[4]==2000][0]
F('officeDesk',top[2]+1000,top[3]+400,0,w=2000,d=800,name='办公桌')
ls=[p for p in lp if p[0]=='LINE'];xs=[p[2] for p in ls]+[p[2]+p[4] for p in ls];ys=[p[3] for p in ls]+[p[3]+p[5] for p in ls]
F('cabBase',(min(xs)+top[2])/2,(min(ys)+max(ys))/2,270,w=max(ys)-min(ys),d=top[2]-min(xs),h=750,name='办公桌侧柜')
for i in [150,157,158,159]:block_f(i,'urinal',0,w=410,d=360)
for i in [151,152,153,154,155,156,168,170,181]:
    f=block_f(i,'toilet',0,w=410,d=651)
    S['structs'].append({'kind':'sewer','at':[f['at'][0],f['at'][1]-f['d']/2+305]})
for i in [105,107,109,111,113,115,117,119,121,123,125,183,185]:block_f(i,'drain',0) if False else S['structs'].append({'kind':'drain','at':[half((B[i]['box'][0]+B[i]['box'][2])/2-320000),half((B[i]['box'][1]+B[i]['box'][3])/2-130000)]})
# Individual CAD training tables in the north room (rectangles, no monitor).
seen=set()
for f in V['furniture_paths']:
    x0,y0,x1,y1=f['box'];w=x1-x0;d=y1-y0
    if f['type']=='POLYLINE' and 331000<x0<339000 and y1<140000 and (abs(w-600)<2 and d>1000):
        key=(round(x0),round(y0),round(x1),round(y1))
        if key in seen:continue
        seen.add(key);F('trainingTable',(x0+x1)/2-320000,(y0+y1)/2-130000,90,w=half(d),d=half(w))

# East hall long tables: actual 450mm parallel vectors, including every splayed segment.
lines=[f['pts'] for f in V['furniture_paths'] if f['type']=='LINE' and f['box'][0]>349000 and math.dist(f['pts'][0],f['pts'][-1])>2000]
used=set();tables=[]
for i,p in enumerate(lines):
    if i in used:continue
    a,b=np.array(p[0]),np.array(p[-1]);u=(b-a)/np.linalg.norm(b-a);L=np.linalg.norm(b-a)
    cand=[]
    for j,q in enumerate(lines):
        if j<=i or j in used:continue
        c,e=np.array(q[0]),np.array(q[-1]);v=e-c;ll=np.linalg.norm(v)
        if abs(np.cross(u,v/ll))>.002:continue
        sep=abs(np.cross(u,c-a));along=sorted((np.dot(c-a,u),np.dot(e-a,u)))
        if 440<sep<460 and min(L,along[1])-max(0,along[0])>.9*min(L,ll):cand.append((abs(L-ll),j,c,e))
    if not cand:continue
    _,j,c,e=min(cand,key=lambda v:v[0]);used.update([i,j])
    if np.dot(e-c,u)<0:c,e=e,c
    poly=[a,b,e,c];center=np.mean(poly,axis=0)
    local=[p-center for p in poly];xs=[v[0] for v in local];ys=[v[1] for v in local]
    F('curveTrainingTable',center[0]-320000,center[1]-130000,w=half(max(xs)-min(xs)),d=half(max(ys)-min(ys)),name='折线培训长桌',opt={'outline':'|'.join(f'{half(p[0])},{half(p[1])}' for p in local)})
    tables.append((a,b))
# CAD marked equipment and all ancillary fittings.
for i in [27,41,127]:
    b=B[i];x0,y0,x1,y1=b['box'];cx=(x0+x1)/2-320000;cy=(y0+y1)/2-130000
    if i in [27,41]:key='slidingBoard';ww=6000;dd=160;rr=270 if i==27 else 90
    elif i==127:key='slidingBoard';ww=9000;dd=150;rr=270
    else:key='mobileDisplay';ww=1700;dd=600;rr=0
    if i==55:cx=12200;cy=(y0+y1)/2-130000;rr=270;ww=2400
    if i==57:cx=26900;cy=(y0+y1)/2-130000;rr=90;ww=2400
    if i==136:cx=27400;cy=27928;rr=90;ww=2400
    if i==147:cx=12700;cy=25600;rr=0;ww=2000
    if i==149:cx=17900;cy=27350;rr=0;ww=1900
    F(key,cx,cy,rr,w=ww,d=dd)
F('lectern',31605.3,17783.5,270,w=1600,d=700)
# 显示屏：屏幕线的位置和长度，正面朝屏幕前面画放射线（可视范围）的那一边
for x,y,L,rot,nm in [(11898,5889,2500,270,'培训室2 显示屏'),(27235,5521,2500,90,'休息厅 显示屏'),(27544,27929,2500,90,'会议室显示屏'),(13392,25233,2100,0,'讨论室1 显示屏'),(17675,26863,1500,0,'讨论室2 显示屏')]:
    off=30;dx,dy={270:(off,0),90:(-off,0),0:(0,off)}[rot]  # 每 30mm 一份：中心 = 屏幕线 + 150（d 的一半）
    # 落地支架式显示屏（原图屏幕不贴墙）：屏幕在模型背面附近，中心往正面挪 90
    F('mobileDisplay',x+dx*5,y+dy*5,rot,w=L,d=300,name=nm)  # 2D 里屏幕画在背面那条边：背面正好压在原图屏幕线上
# 阶梯培训厅：DXF 里 3 条弧形台阶边线（D_01_地材分格）+ 过道标高 +0.24 / +0.48 / +0.72 / +0.96 → 4 级弧形台阶（第 1 排在 ±0.000）
HL=json.loads((ROOT/'hall_floor_lines.json').read_text(encoding='utf-8'))
edges=[sorted(s['pts'],key=lambda p:p[1]) for s in HL if s['layer'].startswith('D_01')]
edges.sort(key=lambda e:e[0][0])
def edge_x0(e,y):
    for (x0,y0),(x1,y1) in zip(e,e[1:]):
        if y0<=y<=y1:return x0+(x1-x0)*(y-y0)/max(y1-y0,1e-6)
    return e[0][0] if y<e[0][1] else e[-1][0]
# 第 4 条：原图没画（标高 +0.84 / +0.96 在第 4 排椅子后面），照第 2、3 条的间距往后推一条
edges.append([[round(x+(x-edge_x0(edges[1],y))),y] for x,y in edges[2]])
HALL_Y0,HALL_Y1,HALL_X1=4038.5,31088.5,40730.5
def ext_edge(e):
    # 台阶边线两头延到大厅南北墙面
    return [[e[0][0],HALL_Y0]]+e+[[e[-1][0],HALL_Y1]]
def edge_x(e,y):
    for (x0,y0),(x1,y1) in zip(e,e[1:]):
        if y0<=y<=y1:return x0+(x1-x0)*(y-y0)/max(y1-y0,1e-6)
    return e[0][0] if y<e[0][1] else e[-1][0]
def tier_of(x,y):
    return sum(1 for e in edges if x>edge_x(e,y))
for k in range(4):
    a=ext_edge(edges[k]);b=ext_edge(edges[k+1]) if k<3 else [[HALL_X1,HALL_Y0],[HALL_X1,HALL_Y1]]
    poly=a+b[::-1];xs=[p[0] for p in poly];ys=[p[1] for p in poly];cx=(max(xs)+min(xs))/2;cy=(max(ys)+min(ys))/2
    F('freeExtrude',cx,cy,0,w=max(xs)-min(xs),d=max(ys)-min(ys),h=240*(k+1),color='#7b8088',name=f'阶梯地台 +{0.24*(k+1):.2f}',
      opt={'shape':'extrude','mat':'fabric','floor':True,'outline':'|'.join(f'{half(x-cx)},{half(y-cy)}' for x,y in poly)})
# 大厅里的桌椅、讲台放到所在那一级台阶上
for f in S['furniture']:
    x,y=f['at']
    if f['key'] in ('trainingChair','curveTrainingTable','officeChair') and x>29300 and HALL_Y0<y<HALL_Y1:
        t=tier_of(x,y)
        if t:f['z']=240*t
F('printer',2810,23060,w=740,d=840,name='复印打印一体机')  # P_01 外框 2440~3180 × 22640~23480
# 厕位纸巾盒（P_03：每个厕位隔板西侧一个 200 × 150 的小盒，离地 700）
for cx,cy in [(4130,2320),(5050,2320),(5980,2320),(6900,2320),(7820,2320),(3190,4980),(4210,4980),(5220,4980),(6250,4980)]:
    F('freeBox',cx,cy,90,w=200,d=150,h=150,z=700,color='#c9ced4',name='纸巾盒',opt={'shape':'roundBox','mat':'metal','r':20})
# 小便斗隔板（J-洁具：三块 420 深、靠门那块 680 深，厚 60，离地 300、高 1200）
for cx,y0,y1 in [(3010,6720,7140),(3760,6720,7140),(4510,6720,7140),(5190,6480,7140)]:
    F('freeBox',cx,(y0+y1)/2,0,w=60,d=y1-y0,h=1200,z=300,color='#e6e6e2',name='小便斗隔板',opt={'shape':'box','mat':'paint'})
# 清洁间：原图只画了地漏、注“加龙头”——没有拖把池，地漏旁墙上留一个冷水龙头点位
S['elec'].append({'kind':'cold','at':[2450,3913.5],'rot':180,'name':'清洁间拖地龙头'})
for y in [7779,8569,9359]:F('vanity',5350.5,y,270,w=790,d=593,h=850,name='公共洗手台',opt={'mirror':False})
# 水吧台：台面外框（P_03 / P_01）+ 台盆块的中心（at = 从台面局部左端量起）
for x,y,r,w,dp,at in [(14377.65,10663.5,0,5445,600,4419.5),(11055.3,23754,90,2380,700,1269.5),(12005.3,23503.5,270,2680,600,1261),(24505.3,21109,90,2950,600,505.5)]:
    F('counter',x,y,r,w=w,d=dp,name='水吧台',kit={'sink':{'leg':0,'at':at,'w':700,'bowls':1},'hob':False,'wall':False,'hood':False})
    # 茶水间水槽配台下小厨宝（办公茶水间通行做法），贴背墙放在水槽旁的地柜里
    a=math.radians(r);bx,by=-math.sin(a)*-1,math.cos(a)*-1  # 背面方向 = 局部 -y
    ux,uy=math.cos(a),math.sin(a);off=min(350,w/2-200)
    F('miniHeater',x+bx*140+ux*off,y+by*140+uy*off,r)
F('coffeeMachine',12038,23583,270,z=900)
F('waterDispenser',10500,23833,90)
# 固装柜：P_02 落地到顶（X = 柜门分格），P_09 悬空到顶（吊柜 / 悬空展示柜）；吊顶高度原图没标，柜顶按 2700
TOP=2700
for x,y,r,w,dp,nm in [(3510.3,10323.5,0,510,580,'储物高柜'),(19900.3,25293.5,0,500,300,'装饰柜'),(10880.3,25303.5,90,720,350,'储物高柜'),(10755.3,26388.5,90,1450,100,'装饰立板'),
                      (20705.3,27478.5,270,4570,400,'储物高柜'),(20755.3,30138.5,270,750,300,'储物高柜'),(10655.3,28488.5,90,2550,300,'办公储物柜')]:
    F('cabTall',x,y,r,w=w,d=dp,h=TOP,name=nm)
for x,y,r,w,dp,nm in [(14377.65,10526,0,5445,325,'水吧吊柜'),(11230.3,23754,90,2380,350,'水吧吊柜'),(12005.3,23993.5,270,1700,600,'水吧吊柜'),
                      (25115.25,10538.9,180,4420,350,'悬空展示柜'),(24630.3,21108.5,90,2950,350,'水吧吊柜')]:
    F('cabWall',x,y,r,w=w,d=dp,z=1600,h=TOP-1600,name=nm)
for x,r in [(19355.3,270),(20755.3,90)]:F('cabTall',x,21963.5,r,w=1200,d=300,z=900,h=TOP-900,name='悬空展示柜')
# 会议设备间原图是空房间（只有一扇门），不放柜子
F('wallTV',15175,24863.5,180,w=3320,d=60,h=1890,z=600,name='前厅 150 寸 LED 显示屏')
F('wallTV',11435,16164,270,w=1200,d=60,z=1200,name='主电梯厅电视屏')
# Open office: four opposing desk pairs, chairs, and the actual lounge group.
F('sofa',7935.8,26557.8,180,w=2500,d=1000)
F('armchair',7185.8,23457.8,w=1000,d=1000);F('armchair',8535.8,23457.8,w=1000,d=1000)
F('coffeeTable',7860.8,25007.8,w=1000,d=1000)
F('trainingTable',13600,21900,w=2400,d=700,name='前厅接待工作台')
# 休闲单椅前面的脚踏（P_01 线：600 宽、520 深，紧贴椅子正面）
_r=math.radians(310.74);F('freeBox',7221.5-math.sin(_r)*648,27805+math.cos(_r)*648,310.74,w=600,d=520,h=420,color='#8c8f94',name='脚踏',opt={'shape':'roundBox','mat':'fabric','r':40})
# 窗帘（P_19：沿外墙玻璃的收拢窗帘，每束 640 × 126，按图上的位置放）
for x0,y0,x1,y1 in json.loads((ROOT/'curtains.json').read_text(encoding='utf-8')):
    cx,cy=(x0+x1)/2,(y0+y1)/2;hz=x1-x0>y1-y0
    r=(0 if cy<16000 else 180) if hz else 90
    F('curtain',cx,cy,r,w=round(max(x1-x0,y1-y0)),d=round(min(x1-x0,y1-y0)),name='落地窗帘（收拢）')
# 吊顶条形风口（T_07_空调设备 里 4 条平行长线 = 75 宽的条缝，长度照图）；旁边标的 A/S、A/R 就是标这条风口的，不再另放方形风口
SLOTS=json.loads((ROOT/'slot_diffusers.json').read_text(encoding='utf-8'))
def near_slot(x,y):
    for o in SLOTS:
        (cx,cy),L=o['c'],o['L']
        if (abs(x-cx)<L/2+300 and abs(y-cy)<600) if o['h'] else (abs(y-cy)<L/2+300 and abs(x-cx)<600):return o
for t in V['texts']:
    x,y=t['at'];x-=320000;y-=130000
    if t['text'] in ['A/S','A/R'] and (o:=near_slot(x,y)):
        o.setdefault('kind',t['text']);continue
    if t['text']=='无线AP':F('wifiAP',x,y)
    elif t['text']=='嵌入式安装扬声器箱':F('ceilingSpeaker',x,y)
    elif t['text'] in ['A/S','A/R']:F('supplyVent' if t['text']=='A/S' else 'returnVent',x,y)
for o in SLOTS:
    r=o.get('kind')=='A/R'
    F('returnVent' if r else 'supplyVent',o['c'][0],o['c'][1],0 if o['h'] else 90,w=round(o['L']),d=round(o['W']),name='条形回风口' if r else '条形送风口')
# Existing two flights in each emergency stairwell, kept on this floor only.
for x,y in [(7250,16600),(20150,15100)]:
    F('stairRun',x-400,y,0,w=800,d=2100,h=1600,opt={'steps':10,'cut':1500})
    F('stairRun',x+400,y,180,w=800,d=2100,h=1600,z=1600,opt={'steps':10,'cut':1500})
# 8 existing lifts are represented as cabins; shaft geometry remains editable.
for x in [1700,10050,15800,25600]:
    for y in [14700,17600]:F('elevator',x,y,90 if x in [1700,15800,25600] else 270,w=1900,d=2000,h=2500,name='既有电梯轿厢')
# Separate infrastructure origins: use the marked electrical rooms and wet core.
S['elec'] += [{'kind':'panel','at':[27800,14800],'rot':90},{'kind':'weak','at':[27800,17800],'rot':90},{'kind':'waterIn','at':[5100,9100],'rot':0}]
S['structs'] += [{'kind':'shaft','at':[3800,8000],'w':350,'d':350}]
# Doors confirmed against the DXF (arcs the parser missed): lift hall 2 (south / north / stair side),
# fire lobby lower leaf, meeting equipment room, lower lift swing door.
for w in S['walls']:
    a,b=w['a'],w['b']
    if a[1]==b[1] and abs(a[1]-19213.5)<1 and a[0]<22000<b[0]:ensure_door(w,21913,23043,hinge='from',into=[22450,18300])
    # J-DOOR-门 图层里画成折线弧的 4 扇门（门轴 = 弧心，关门门扇沿墙）
    if a[1]==b[1] and abs(a[1]-13093.5)<1 and a[0]<4500<b[0]:ensure_door(w,4005.3,5126.5,hinge='to',into=[4566,13600],name='电梯厅1 北侧防火门')
    if a[1]==b[1] and abs(a[1]-19213.5)<1 and a[0]<4100<b[0]:ensure_door(w,3534,4655.3,hinge='from',into=[4100,18800],name='电梯厅1 南侧防火门')
    if a[1]==b[1] and abs(a[1]-13093.5)<1 and a[0]<17600<b[0]:ensure_door(w,17320,17905.3,hinge='from',into=[17610,12600])
    if a[1]==b[1] and abs(a[1]-13093.5)<1 and a[0]<22800<b[0]:ensure_door(w,22261,23370,hinge='to',into=[22800,13900])
    if a[0]==b[0] and abs(a[0]-21605.3)<1:ensure_door(w,16756,17880,hinge='to',into=[21000,17300])
    if a[1]==b[1] and abs(a[1]-8303.5)<1 and a[0]>27000:ensure_door(w,28040,28640,hinge='from',into=[28340,7800])
    if a[1]==b[1] and abs(a[1]-25018.5)<1 and a[0]<28500<b[0]:ensure_door(w,27985,28995,hinge='from',into=[28500,25700])
    if a[0]==b[0] and abs(a[0]-24405.3)<1:
        w['openings']=[o for o in w.get('openings',[]) if not (o['from']>16800 and o['to']<18400)]
        ensure_door(w,17275,17900,hinge='to',into=[24900,17600],name='电梯检修门')
# Ceiling fittings read from text labels can sit inside a wall band: push them into the room on the same side.
for f in S['furniture']:
    if f['key'] not in ('supplyVent','returnVent','wifiAP','ceilingSpeaker') or f.get('name','').startswith('条形'):continue  # 条形风口照图上的线放，不推
    cw=f.get('w',600 if 'Vent' in f['key'] else 240);cd=f.get('d',300 if 'Vent' in f['key'] else 240)
    for _ in range(3):
        x,y=f['at']
        for w in S['walls']:
            (ax,ay),(bx,by)=w['a'],w['b'];L=math.hypot(bx-ax,by-ay)
            if L<1:continue
            ux,uy=(bx-ax)/L,(by-ay)/L;t=(x-ax)*ux+(y-ay)*uy;o=-(x-ax)*uy+(y-ay)*ux
            ext=(cd if abs(ux)>.5 else cw)/2 if f.get('rot',0)%180==0 else (cw if abs(ux)>.5 else cd)/2
            need=w['t']/2+ext+40
            if -ext<t<L+ext and abs(o)<need:
                sg=1 if o>=0 else -1;dlt=need-abs(o);x+=-uy*sg*dlt;y+=ux*sg*dlt
        f['at']=[half(x),half(y)]
# Remove exact duplicates only; preserve every physical item.
for w in S['walls']:
    w['openings']=sorted(w.get('openings',[]),key=lambda o:o['from'])
    ops=w['openings'];clean=[]
    for q in ops:
        if clean and q['from']<clean[-1]['to']-20:
            # Explicit measured entrances supersede inferred overlapping swings.
            if q.get('name') or q.get('entry'):clean[-1]=q
            continue
        clean.append(q)
    w['openings']=clean
(ROOT/'spec.json').write_text(json.dumps(S,ensure_ascii=False,indent=2),encoding='utf-8')
summary={'walls':len(S['walls']),'openings':sum(len(w.get('openings',[])) for w in S['walls']),'labels':len(S['rooms']),'furniture':len(S['furniture']),'furniture_by_key':dict(collections.Counter(f['key'] for f in S['furniture'])),'east_hall_seats':sum(1 for f in S['furniture'] if f['key']=='trainingChair' and f['at'][0]>29300),'east_hall_table_segments':len(tables),'assumptions':S['_source']}
(ROOT/'inventory-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=True))
