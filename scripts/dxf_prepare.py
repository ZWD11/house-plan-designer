"""Flatten legacy DXF blocks, repair GBK mojibake, and crop one drawing.

The --box uses CAD coordinates (x right, y up); it never implies storeys.
Keeps dimensions, curves and hatches as entities, and writes a provenance report.
"""
import argparse, collections, json, math
from pathlib import Path
import ezdxf
from ezdxf import bbox

def repair_text(value):
    try:
        result = value.encode('latin1').decode('gbk')
        return result if any('\u4e00' <= c <= '\u9fff' for c in result) else value
    except (UnicodeError, AttributeError):
        return value

def flatten(entities, parent='0', depth=0):
    if depth > 16:
        raise ValueError('Nested INSERT depth exceeds 16')
    for entity in entities:
        layer = repair_text(entity.dxf.layer)
        if layer == '0': layer = parent
        if entity.dxftype() == 'INSERT':
            yield from flatten(entity.virtual_entities(), layer, depth + 1)
            for attr in entity.attribs:
                yield attr, layer
        else:
            yield entity, layer

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input');ap.add_argument('output')
    ap.add_argument('--box',nargs=4,type=float,required=True,metavar=('X0','Y0','X1','Y1'))
    ap.add_argument('--structure-only',action='store_true')
    a=ap.parse_args(); src=ezdxf.readfile(a.input); dest=ezdxf.new('R2010');dest.units=src.units
    x0,y0,x1,y1=a.box
    if x0>=x1 or y0>=y1:ap.error('box must have positive width and height')
    stats=collections.Counter(); problems=[]; repaired=set()
    for entity,layer in flatten(src.modelspace()):
        if a.structure_only and not any(s in layer.lower() for s in ('wall','墙','柱','门','窗','door','window','dim','尺寸','平面文字','文字说明')):continue
        try:
            bounds=bbox.extents([entity],fast=True)
            if not bounds.has_data:continue
            p,q=bounds.extmin,bounds.extmax
            if q.x<x0 or p.x>x1 or q.y<y0 or p.y>y1:continue
            # Long cross-sheet axes must not drag unrelated drawings into this crop.
            if p.x<x0-5000 or q.x>x1+5000 or p.y<y0-5000 or q.y>y1+5000:continue
            copy=entity.copy();copy.dxf.layer=layer
            # Normalize semantic colours so downstream wall extraction does not
            # confuse furniture outlines or threshold stones with walls.
            low=layer.lower()
            color=7 if any(s in low for s in ('wall','墙','柱')) else 8
            if any(s in low for s in ('尺寸','dim','文字','text')):color=2
            elif any(s in low for s in ('窗','window','glaz')):color=4
            elif any(s in low for s in ('门','door')):color=3
            copy.dxf.color=color
            if layer not in dest.layers:dest.layers.new(layer,dxfattribs={'color':7})
            for field in ('text',):
                if copy.dxf.is_supported(field) and copy.dxf.hasattr(field):
                    old=copy.dxf.get(field);new=repair_text(old)
                    if new!=old:repaired.add(old)
                    copy.dxf.set(field,new)
            dest.modelspace().add_entity(copy);stats[copy.dxftype()]+=1
        except Exception as exc:
            problems.append({'type':entity.dxftype(),'layer':layer,'error':str(exc)})
    target=Path(a.output);target.parent.mkdir(parents=True,exist_ok=True);dest.saveas(target)
    report={'input':str(Path(a.input).resolve()),'box_cad':a.box,'units':src.units,'unit_note':'unitless; verify dimensions' if src.units==0 else 'declared by source','entities':dict(stats),'repaired_texts':len(repaired),'errors':problems}
    target.with_suffix('.report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))
if __name__=='__main__':main()
