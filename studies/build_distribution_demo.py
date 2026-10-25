# SPDX-License-Identifier: GPL-3.0-only
"""Rebuild exact offline acceptance artifacts; no adsk, Fusion or AI images."""
import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import hashlib
import subprocess

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from studies.distribution_v2 import generate, specimen
from studies.source_fixtures import distribution_registry
NAMES=tuple(key for key,label in distribution_registry())
from Perfora.geometry import generate as previous_generate

LABELS={
 'staggered':('Staggered','Шахматная сетка'),
 'rows':('Rectangular','Прямые ряды и колонки'),
 'circular':('Circular','Концентрические кольца'),
 'path':('Along Path','Один ряд вдоль выбранного пути'),
 'contour':('Contour','Ряды повторяют границу'),
 'fan':('Fan','Целые лучи с общим началом'),
 'phyllotaxis':('Phyllotaxis','Непрерывная спираль Фогеля'),
 'poisson':('Poisson Disk','Нерегулярное поле с зазором'),
 'wave':('Wave','Ровный ритм вдоль синусоид'),
 'chevron':('Chevron','Зеркальные плечи шеврона'),
 'running_bond':('Staggered · Row Shift','Сдвиг рядов 1/3 · та же сетка'),
 'between_curves':('Between Curves','Согласованные ряды между кривыми'),
}
NOTES={
 'staggered':'Текущий генератор Fusion: прямоугольная сетка со сдвигом каждого второго ряда. Для кругов вертикальный шаг даёт плотную треугольную упаковку.',
 'rows':'Текущий генератор Fusion: прямые ряды, фиксированная ориентация отверстий.',
 'circular':'Текущий генератор Fusion: концентрические кольца. Для щелей переключается фиксированная и радиальная ориентация.',
 'path':'Настоящие sample_path и generate_path из проекта. Для теста задана аналитическая дуга; её длина и касательные вычисляются точно.',
 'contour':'Равномерное замыкание каждого ряда; щели следуют касательной. Конечные ряды не заполняются случайными остатками.',
 'fan':'Общий внутренний радиус защищает вершину. Каждый луч начинается на одной дуге и сохраняет все отверстия.',
 'phyllotaxis':'Все индексы золотого угла сохраняются. Слишком высокая плотность меняет масштаб всего поля, а не удаляет точки.',
 'poisson':'Существующий Poisson Disk сохранён: здесь нерегулярность — цель. Формы и размеры отверстий одинаковы.',
 'wave':'Шаг отсчитывается по длине волны от центра поля. Отверстия не выпадают поодиночке; поворот щелей можно отключить.',
 'chevron':'Общие вершины заменены симметричными парами. У щелей — намеренный центральный шов без пересечений.',
 'running_bond':'Running Bond объединён с шахматкой: это одна сетка. Сдвиг 1/2 — обычная шахматка; 1/3 меняет фазу рядов, но не создаёт отдельную семью Distribution.',
 'between_curves':'Все ряды используют общие поперечные станции. При тесноте уменьшается целое число рядов/колонок; направляющие не растягиваются.',
}


def path_svg(points, closed=False):
    return 'M'+'L'.join(f'{x:.4f},{-y:.4f}' for x,y in points)+('Z' if closed else '')


def pack(study, old=False):
    cells=study.cells
    data=dict(cells=[[round(c.center[0],4),round(c.center[1],4),round(c.angle,4)] for c in cells],
              width=study.settings.size,length=study.settings.slot_length,shape=study.settings.shape,
              count=len(cells),gap=round(study.gap*10,3),ms=round(study.milliseconds,1),passes=study.passes,row_shift=study.settings.bond_shift,
              loops=[[[round(x,4),round(y,4)] for x,y in l.points] for l in study.region.loops])
    data['settings']={k:v for k,v in study.settings.__dict__.items() if k not in ('guide1','guide2','path_samples')}
    # Overlay is diagnostic only; exact hole positions are never simplified.
    data['strokes']=[[[round(x,3),round(y,3)] for x,y in p[::max(1,len(p)//28)]] for p in study.strokes]
    return data


def previous(study,name):
    if name in ('rows','staggered','circular','path'):
        return study
    s=replace(study.settings,layout=name,fan_angle=math.pi,fan_rays=25,
              wave_amplitude=.65,wave_length=5.1,chevron_angle=math.radians(28),
              origin_x=0,origin_y=-4.35 if name=='fan' else 0,distribution_revision=1)
    if name=='between_curves':
        s=replace(s,guide_rows=12,guide1=tuple((-5.45+10.9*i/128,-2.6+.75*math.sin(math.tau*i/128-.5)) for i in range(129)),
                  guide2=tuple((-5.45+10.9*i/128,2.1+1.05*math.sin(math.tau*i/128+.3)) for i in range(129)))
    from time import perf_counter
    started=perf_counter()
    result=previous_generate(study.region,s)
    from studies.distribution_v2 import Study,minimum_gap
    return Study(result,[],study.region,s,(perf_counter()-started)*1000,1,1,minimum_gap(result,s.gap))


def raster_sheet(cases,names,dest,circles=False):
    from PIL import Image,ImageDraw,ImageFont
    scale=2
    w,h=1600,1360
    im=Image.new('RGB',(w*scale,h*scale),'#f7f6f2')
    d=ImageDraw.Draw(im)
    def font(size):return ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',size*scale)
    title=font(31);label=font(27);small=font(19)
    d.text((55*scale,32*scale),'PERFORA / DISTRIBUTION — OFFLINE v2',font=title,fill='#242725')
    d.text((55*scale,83*scale),'Точные контуры алгоритмов • минимальная перемычка 1.2 mm • без Fusion',font=small,fill='#535b58')
    for i,name in enumerate(names):
        sh='circle' if circles or name in ('phyllotaxis','poisson') else 'slot-tangent'
        a=cases[name][sh]['after']
        x=55+(i%2)*770;y=144+(i//2)*595
        d.text((x*scale,y*scale),f'{NAMES.index(name)+1:02d}   {LABELS[name][0]}',font=label,fill='#242725')
        unit=48*scale
        ox=(x+340)*scale;oy=(y+286)*scale
        def xy(p):return ox+p[0]*unit,oy-p[1]*unit
        # Same physical cm-to-pixel scale across all four specimens.
        for loop in a['loops']:
            d.polygon([xy(p) for p in loop],fill='#2c3332')
        for px,py,angle in a['cells']:
            r=a['width']/2
            if a['shape']=='circle':
                cx,cy=xy((px,py));rr=r*unit
                d.ellipse((cx-rr,cy-rr,cx+rr,cy+rr),fill='#f7f6f2')
            else:
                half=(a['length']-a['width'])/2
                dx,dy=half*math.cos(angle),half*math.sin(angle)
                points=[]
                for sign,start in ((1,-math.pi/2),(-1,math.pi/2)):
                    for k in range(25):
                        t=angle+start+math.pi*k/24
                        points.append(xy((px+sign*dx+r*math.cos(t),py+sign*dy+r*math.sin(t))))
                d.polygon(points,fill='#f7f6f2')
        d.text((x*scale,(y+535)*scale),LABELS[name][1],font=small,fill='#242725')
        desc=f"{a['count']} отверстий · "+('Ø 2.5 mm' if a['shape']=='circle' else '1.7 × 5.2 mm · по касательной')
        d.text((x*scale,(y+565)*scale),desc,font=small,fill='#535b58')
    im.resize((w,h),Image.Resampling.LANCZOS).save(dest)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True,help='One standalone .html file, or an artifact directory.')
    args=parser.parse_args()
    single_file=args.output.suffix.lower()=='.html'
    destination=args.output
    if single_file:
        destination.parent.mkdir(parents=True,exist_ok=True)
    else:args.output.mkdir(parents=True,exist_ok=True)
    cases={}
    for name in NAMES:
        cases[name]={}
        for mode,shape,orientation in (('circle','circle','fixed'),('slot-tangent','slot','tangent'),('slot-fixed','slot','fixed')):
            study=generate(name,shape,orientation=orientation)
            cases[name][mode]={'after':pack(study),'before':pack(previous(study,name))}
            print(name,mode,len(study.cells),round(study.milliseconds),flush=True)
    data={'names':NAMES,'labels':LABELS,'notes':NOTES,'cases':cases}
    tracked=('geometry.py','distributions.py','distribution_fields.py','curve_layout.py','curves.py')
    data['source']={name:hashlib.sha256((ROOT/'Perfora'/name).read_bytes()).hexdigest() for name in tracked}
    data['base']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    data['half_shift']={}
    for mode,shape,orientation in (('circle','circle','fixed'),('slot-tangent','slot','tangent'),('slot-fixed','slot','fixed')):
        study=generate('running_bond',shape,orientation=orientation,row_shift=.5)
        data['half_shift'][mode]={'after':pack(study),'before':pack(previous(study,'running_bond'))}
    template=(ROOT/'studies/distribution-demo.template.html').read_text()
    fragment=template.replace('__STUDY_DATA__',json.dumps(data,ensure_ascii=False,separators=(',',':')))
    if len(fragment.encode())>1000000:
        raise ValueError('Inline visual test exceeds 1 MB; use a smaller exact dataset.')
    export=(ROOT/'studies/distribution-export.template.html').read_text().replace('__FRAGMENT__',fragment)
    source_summary=data['base'][:7]+' / geometry.py SHA-256 '+data['source']['geometry.py'][:16]+' / distribution_fields.py '+data['source']['distribution_fields.py'][:16]
    export=export.replace('__SOURCE_REVISION__',source_summary)
    if single_file:
        destination.write_text(export)
        print('Standalone visual test:',destination)
        return
    (args.output/'distribution-visual-test.html').write_text(export)
    (args.output/'data.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')))
    (args.output/'distribution-demo.html').write_text(fragment)
    for i in range(0,len(NAMES),4):
        raster_sheet(cases,NAMES[i:i+4],args.output/f'distribution-v2-{i//4+1:02d}.png')
    # Store numeric proof separately from the compact display dataset.
    metrics={n:{m:{k:v for k,v in item['after'].items() if k not in ('cells','loops','strokes')} for m,item in modes.items()} for n,modes in cases.items()}
    (args.output/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
