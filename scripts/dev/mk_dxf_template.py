"""生成 DXF R2007 骨架（designer/src/export/dxfTemplate.ts）。
线型按图纸毫米定义，$LTSCALE = 出图比例分母（占位 @LTS@）；图层线宽按 GB/T 50001 线宽组 b = 0.5（0.5 / 0.35 / 0.25 / 0.13）。"""
import json, os, re, sys, tempfile, ezdxf
# 用法：python mk_dxf_template.py <设计器项目>/src/export/dxfTemplate.ts
OUT = sys.argv[1] if len(sys.argv) > 1 else "dxfTemplate.ts"
SKEL = os.path.join(tempfile.gettempdir(), "house_dxf_skel2007.dxf")
doc = ezdxf.new('R2007', setup=False)
doc.header['$INSUNITS'] = 4; doc.header['$MEASUREMENT'] = 1; doc.header['$LTSCALE'] = 1.0; doc.header['$TEXTSTYLE'] = 'HZ'; doc.header['$LWDISPLAY'] = 1
doc.header['$CELTSCALE'] = 1.0
doc.linetypes.add('DASHED', pattern=[6.0, 4.0, -2.0], description='虚线 __ __ __')
doc.linetypes.add('CENTER', pattern=[24.0, 18.0, -3.0, 0.0, -3.0], description='单点长画线 ____ . ____ .')
st = doc.styles.add('HZ', font='gbenor.shx'); st.dxf.bigfont = 'gbcbig.shx'; st.dxf.width = 0.7
LAYERS = [  # 名称, 颜色, 线型, 线宽(1/100mm)
    ('WALL', 7, 'CONTINUOUS', 50), ('WALL-HATCH', 7, 'CONTINUOUS', 13), ('WALL-NEW', 30, 'CONTINUOUS', 50), ('WALL-DEMO', 1, 'DASHED', 25),
    ('COLUMN', 7, 'CONTINUOUS', 50), ('DOOR', 4, 'CONTINUOUS', 25), ('WINDOW', 4, 'CONTINUOUS', 25), ('STRUCT', 7, 'CONTINUOUS', 25),
    ('FURN', 8, 'CONTINUOUS', 13), ('ELEC', 6, 'CONTINUOUS', 18), ('ROOM-TEXT', 7, 'CONTINUOUS', 25),
    ('AXIS', 1, 'CENTER', 13), ('AXIS-NUM', 3, 'CONTINUOUS', 18), ('DIM', 3, 'CONTINUOUS', 13), ('ANNO', 7, 'CONTINUOUS', 25),
    ('FRAME', 7, 'CONTINUOUS', 70), ('TITLE', 7, 'CONTINUOUS', 18),
]
for n, c, lt, lw in LAYERS:
    L = doc.layers.add(n, color=c, linetype=lt, lineweight=lw)
    if n == 'ELEC': L.off()  # 水电点位默认关闭：平面布置图和水电点位图按国标习惯分开看，需要时在图层里打开
# 尺寸标注样式 GB：图纸毫米定义，DIMSCALE = 出图比例分母（占位 777）。45° 建筑斜线（DIMTSZ），字高 3、尺寸界线偏移 2 / 超出 2.5、
# 文字在尺寸线上方、与尺寸线平行，整数毫米，基线间距 10；颜色 BYBLOCK（跟随 DIM 图层）
doc.dimstyles.new('GB', dxfattribs=dict(dimscale=777.0, dimtxt=3.0, dimtsz=1.25, dimasz=1.25, dimexo=2.0, dimexe=2.5, dimgap=1.0, dimtad=1,
    dimtih=0, dimtoh=0, dimdec=0, dimlunit=2, dimzin=8, dimdli=10.0, dimtmove=1, dimclrd=0, dimclre=0, dimclrt=0, dimtxsty='HZ', dimlfac=1.0, dimjust=0))
doc.saveas(SKEL)
s = open(SKEL, encoding="utf-8").read()
s = s.replace('$EXTMIN\n 10\n1e+20\n 20\n1e+20\n 30\n1e+20\n', '$EXTMIN\n 10\n@X0@\n 20\n@Y0@\n 30\n0\n')
s = s.replace('$EXTMAX\n 10\n-1e+20\n 20\n-1e+20\n 30\n-1e+20\n', '$EXTMAX\n 10\n@X1@\n 20\n@Y1@\n 30\n0\n')
s = re.sub(r'\$HANDSEED\n  5\n[0-9A-F]+\n', '$HANDSEED\n  5\n@SEED@\n', s)
s = re.sub(r'\$LTSCALE\n 40\n[0-9.]+\n', '$LTSCALE\n 40\n@LTS@\n', s)
s = s.replace('$LASTSAVEDBY\n  1\nezdxf\n', '$LASTSAVEDBY\n  1\nhouse-designer\n')
s = s.replace(' 40\n777.0\n', ' 40\n@DIMSCALE@\n')
s = s.replace('BLOCK_RECORD\n  5\n9\n330\n0\n100\nAcDbSymbolTable\n 70\n2\n', 'BLOCK_RECORD\n  5\n9\n330\n0\n100\nAcDbSymbolTable\n 70\n@BRN@\n')
s = s.replace('*Paper_Space\n340\n1E\n 70\n0\n280\n1\n281\n0\n', '*Paper_Space\n340\n1E\n 70\n0\n280\n1\n281\n0\n@BREC@')
k = s.index('  2\nENTITIES\n'); e = s.rindex('  0\nENDSEC\n', 0, k); s = s[:e] + '@BLKS@' + s[e:]
s = s.replace('  0\nDICTIONARY\n  5\nC\n330\nA\n100\nAcDbDictionary\n281\n1\n', '  0\nDICTIONARY\n  5\nC\n330\nA\n100\nAcDbDictionary\n281\n1\n@GRPENT@')
e = s.rindex('  0\nENDSEC\n'); s = s[:e] + '@GRPOBJ@' + s[e:]
for k in ['@GRPENT@', '@GRPOBJ@', '@X0@', '@X1@', '@SEED@', '@LTS@', '@DIMSCALE@', '@BRN@', '@BREC@', '@BLKS@']: assert k in s, k
i = s.index('  2\nENTITIES\n') + len('  2\nENTITIES\n')
j = s.index('  0\nENDSEC\n', i)
head, tail = s[:i], s[j:]
ts = ("/* 由 ezdxf 生成的 DXF R2007（AC1021）骨架（生成脚本见 skill 的 scripts/dev/mk_dxf_template.py）：\n"
      " * 图层（线宽按 GB/T 50001 线宽组 b=0.5）、线型（DASHED 虚线 / CENTER 单点长画线，按图纸毫米定义）、文字样式 HZ（gbenor.shx + gbcbig.shx，宽度 0.7 ≈ 长仿宋）。\n"
      " * 实体插在 ENTITIES 段里；模型空间块记录句柄 = 17。占位符 @X0@ @Y0@ @X1@ @Y1@ @SEED@ @LTS@ @DIMSCALE@（标注样式 GB 的比例）@BRN@ @BREC@（块表记录数 / 记录）@BLKS@（块定义）@GRPENT@ @GRPOBJ@（编组：ACAD_GROUP 字典句柄 C）；块表句柄 = 9。 */\n"
      f"export const DXF_HEAD = {json.dumps(head, ensure_ascii=False)};\n"
      f"export const DXF_TAIL = {json.dumps(tail, ensure_ascii=False)};\n"
      "export const MSP_OWNER = '17';\n")
open(OUT, "w", encoding="utf-8").write(ts)
print(len(ts))
