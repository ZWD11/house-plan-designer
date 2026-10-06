"""
示例：户型图2.jpg（12340×11940，三室两卫）的户型描述生成脚本。
做法：用 analyze.py 得到比例 S 和外轮廓左上角像素 (OX, OY)，再对照 analysis.png 上的像素标尺
读出每条墙中线、每个门窗两端的像素坐标，用 H()/V() 写墙，脚本统一换算成 mm。
"""
import json, sys
S=17.654; OX,OY=250,76
X=lambda p: round((p-OX)*S/10)*10
Y=lambda p: round((p-OY)*S/10)*10
P=lambda x,y:[X(x),Y(y)]
def H(y,x0,x1,t,bearing=False,ops=()):  # horizontal wall, openings in px
    return dict(a=P(x0,y),b=P(x1,y),t=t,bearing=bearing,openings=[dict(o, **{'from':X(o.pop('f')),'to':X(o.pop('e'))}) for o in map(dict,ops)])
def V(x,y0,y1,t,bearing=False,ops=()):
    return dict(a=P(x,y0),b=P(x,y1),t=t,bearing=bearing,openings=[dict(o, **{'from':Y(o.pop('f')),'to':Y(o.pop('e'))}) for o in map(dict,ops)])
E,I,T=240,200,120
walls=[
 # 外圈
 H(84,614,942,E,True,[dict(type='double',f=625,e=695,entry=True,into=P(660,50))]),
 V(942,84,248,E,True),
 H(248,739,942,I,False,[dict(type='door',f=752,e=800,hinge='from',into=P(780,200)),dict(type='window',f=850,e=930)]),
 V(840,248,746,E,True),
 H(746,445,840,E,True,[dict(type='window',f=483,e=802)]),
 V(445,650,746,E,True),
 H(684,257,445,E,True,[dict(type='window',f=295,e=393,sill=450)]),
 V(257,288,684,E,True,[dict(type='window',f=345,e=398,sill=1400)]),
 H(288,257,512,E,True,[dict(type='window',f=368,e=480,sill=1400)]),
 V(512,192,384,E,True,[dict(type='window',f=198,e=276)]),
 H(192,512,614,I),
 V(614,84,192,I),
 # 内部
 V(739,84,248,I),
 V(614,192,384,T,False,[dict(type='sliding',f=235,e=355)]),
 H(384,360,614,I,False,[dict(type='door',f=455,e=505,hinge='to',into=P(480,350))]),
 V(360,288,452,T,False,[dict(type='door',f=395,e=445,hinge='to',into=P(330,420))]),
 H(452,257,360,T),
 V(445,384,650,I,False,[dict(type='door',f=395,e=445,hinge='from',into=P(410,420))]),
 H(455,445,614,T,False,[dict(type='door',f=457,e=505,hinge='from',into=P(480,490))]),
 V(614,455,650,T),
 H(650,445,840,E,True,[dict(type='window',f=483,e=585,sill=450),dict(type='sliding',f=620,e=805)]),
]
for w in walls:
    if not w['openings']: del w['openings']
rooms=[(840,160,'次卧'),(566,280,'厨房'),(440,330,'卫生间'),(307,365,'主卫'),(700,395,'客餐厅'),(357,545,'主卧'),(533,545,'次卧'),(642,700,'阳台')]
F=lambda key,x,y,rot=0,**k: dict(key=key,at=[x,y],rot=rot,**k)
furniture=[
 # 主卧
 F('bed18',1290,8300,270),F('nightstand',450,7130,270),F('nightstand',450,9470,270),F('cabWardrobe',3050,8300,90,w=2400),F('rug',1900,8300,270,w=2400,d=2000),
 # 次卧（南）
 F('bed15',5345,8600,90),F('nightstand',6160,7590,90),F('nightstand',6160,9610,90),F('wardrobe',3860,8900,270,w=1600),
 # 次卧（北）
 F('bed12',10700,1260,0),F('nightstand',11600,470,0),F('wardrobe',9160,1100,270,w=1500),
 # 客餐厅
 F('rug',8500,8300,90),F('sofa',9825,8300,90),F('coffeeTable',8600,8300,90),F('tvCabinet',6690,8300,270),F('armchair',8500,6900,180),
 F('diningTable',8400,4300,0),F('chair',8000,3740,0),F('chair',8800,3740,0),F('chair',8000,4860,180),F('chair',8800,4860,180),
 F('shoeCabinet',6705,1100,270),F('plant',10000,6400,0),
 # 厨房
 F('counter',5050,3300,270,w=2100),F('fridge',5100,4950,270),
 # 主卫
 F('toilet',650,4210,0),F('shower',1400,4310,0),F('vanity',490,5300,270),
 # 卫生间
 F('shower',2450,4310,0),F('toilet',3300,4210,0),F('vanity',2700,5090,180),
 # 阳台
 F('washer',3900,11400,0),F('lounge',8000,11000,0),F('lounge',8800,11000,0),F('sideTable',8400,11050,0),F('plant',10000,11400,0),
]
structs=[dict(kind='sewer',at=[650,4170]),dict(kind='sewer',at=[3300,4170]),dict(kind='drain',at=[1400,4310]),dict(kind='drain',at=[2450,4310]),dict(kind='drain',at=[4300,11500])]
spec=dict(structs=structs,furniture=furniture,name='户型图2 · 三室两卫',height=2800,phase='renovate',walls=walls,
  rooms=[dict(at=P(x,y),name=n) for x,y,n in rooms],
  underlay=dict(image='example-input.jpg',mmPerPx=S,x=round(-OX*S),y=round(-OY*S)))
json.dump(spec,open(sys.argv[1] if len(sys.argv)>1 else 'spec.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print(len(walls))
