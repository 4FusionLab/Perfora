# SPDX-License-Identifier: GPL-3.0-only
"""Browser/desktop demo adapter. All hole geometry comes from Perfora.geometry.

This module imports no adsk and has no optional dependencies. The browser
executes the very same module sources in an isolated Python worker.
"""
from dataclasses import replace
import json
import math
from time import perf_counter
from Perfora.geometry import Settings, Region, Loop, rectangle_region, generate, VARIANT_LAYOUTS, SHAPE_IDS, LENGTH_SHAPES, ORGANIC_SHAPES, ORGANIC_FIELDS, convex_inset, clip_polygon_convex, overlaps
from Perfora.curve_layout import sample_path
from studies.source_fixtures import ArcEvaluator
from Perfora.organic import DEFAULT_OPEN, DEFAULT_CELL_SIZE, DEFAULT_WEB

LAYOUTS=('staggered','rows','circular','path','contour','fan','phyllotaxis','poisson','wave','chevron','between_curves')


def number(data,key,default,low,high):
    value=float(data.get(key,default))
    if not math.isfinite(value) or not low<=value<=high:
        raise ValueError(key.replace('_',' ').title()+f' must be between {low} and {high}.')
    return value


def region_for(width,height,kind):
    if kind=='rectangle':return rectangle_region(width,height)
    if kind=='disk':
        radius=width/2
        return Region((Loop(tuple((radius*math.cos(i*math.tau/160),radius*math.sin(i*math.tau/160)) for i in range(160))),))
    if kind=='rounded':
        points=tuple((width/2*math.copysign(abs(math.cos(t))**.65,math.cos(t)),
                      height/2*math.copysign(abs(math.sin(t))**.65,math.sin(t)))
                     for t in (i*math.tau/160 for i in range(160)))
        return Region((Loop(points),))
    raise ValueError('Unknown panel shape.')


def prepare(data):
    shape=data.get('shape','circle');layout=data.get('layout','wave')
    if shape not in SHAPE_IDS:raise ValueError('Unknown hole shape.')
    if layout not in LAYOUTS:raise ValueError('Unknown Distribution.')
    # Hidden controls must not invalidate another pattern. Inactive values are
    # intentionally replaced by defaults at the adapter boundary.
    active={'shape','layout','width','height','size','gap','margin','boundary','orientation','spacing'}
    organic=shape in ORGANIC_SHAPES
    if organic:
        layout='rows'
        active={'shape','layout','width','height','size','gap','margin','boundary','seed','organic_direction'}
        active.update(('organic_variation','organic_gradient') if shape=='blue_noise' else ('organic_bridges',))
    if shape in LENGTH_SHAPES:active.add('length')
    if shape!='circle' and not organic:active.add('angle')
    if shape=='cross':active.add('arm_width')
    if shape=='star':active.update(('star_ratio','star_points'))
    if shape=='voronoi':active.update(('seed','irregularity','corner_radius'));layout='rows'
    if layout=='poisson':active.add('seed')
    active.update({'wave':('amplitude','wavelength'),'fan':('sector','rays'),
                   'chevron':('chevron_angle',),'circular':('start_radius',),
                   'between_curves':('guide_rows',)}.get(layout,()))
    data={key:value for key,value in data.items() if key in active}
    width=number(data,'width',120,30,300)/10
    kind=data.get('boundary','rectangle')
    height=width if kind=='disk' else number(data,'height',100,30,300)/10
    size=number(data,'size',DEFAULT_CELL_SIZE*10 if organic else 2.5,1,20)/10
    length=number(data,'length',5.2,1,40)/10
    gap=number(data,'gap',DEFAULT_WEB*10 if organic else 1.2,.3,10)/10
    margin=number(data,'margin',1.8,0,20)/10
    density=number(data,'spacing',1.12,1,2.5)
    orientation=data.get('orientation','tangent')
    if orientation not in ('fixed','tangent','radial'):raise ValueError('Unknown orientation.')
    region=region_for(width,height,kind)
    core_layout='grid' if layout in ('staggered','rows') else layout
    s=Settings(shape=shape,layout=core_layout,size=size,slot_length=length,gap=gap,margin=margin,
        limit=1800,staggered=layout=='staggered',shape_angle=math.radians(number(data,'angle',0,-180,180)),
        arm_width=number(data,'arm_width',1,0.2,8)/10,star_ratio=number(data,'star_ratio',45,10,70)/100,
        star_points=int(number(data,'star_points',5,3,12)),seed=int(number(data,'seed',7,0,2147483647)),
        irregularity=number(data,'irregularity',80,0,100)/100,
        corner_radius=number(data,'corner_radius',0,0,4)/10,
        fan_angle=math.radians(number(data,'sector',180,20,360)),fan_rays=int(number(data,'rays',25,3,80)),
        wave_amplitude=number(data,'amplitude',6.5,0,20)/10,wave_length=number(data,'wavelength',51,10,150)/10,
        chevron_angle=math.radians(number(data,'chevron_angle',28,10,70)),guide_rows=int(number(data,'guide_rows',12,2,30)),
        phyllotaxis_density=1,contour_tolerance=max(.055,min(width,height)/200),
        start_radius=number(data,'start_radius',0,0,30)/10,
        distribution_revision=2 if layout in VARIANT_LAYOUTS else 1,
        layout_orientation='tangent' if orientation!='fixed' else 'fixed',
        organic_open=DEFAULT_OPEN.get(shape,48),
        organic_direction=math.radians(number(data,'organic_direction',0,-180,180)),
        organic_variation=number(data,'organic_variation',35,0,90),
        organic_gradient=number(data,'organic_gradient',0,-100,100),
        organic_bridges=bool(data.get('organic_bridges',False)) if shape in ORGANIC_FIELDS else False,
        tangential_orientation=layout=='circular' and orientation=='tangent',
        radial_orientation=layout=='circular' and orientation=='radial')
    if shape not in LENGTH_SHAPES:s=replace(s,slot_length=max(length,size))
    # Explicit spacings remain minimums. The shared planner may increase them
    # coherently to preserve full rows and requested clearances.
    if shape=='voronoi' or organic:along=normal=size+gap
    elif shape in ('circle','slot'):
        along=(length if shape=='slot' else size)+gap
        normal=size+gap
    else:
        from Perfora.geometry import enclosing_radius
        along=normal=2*enclosing_radius(s)+gap
    s=replace(s,along_spacing=along*density,row_spacing=normal*density)
    guides=[]
    if layout=='fan':s=replace(s,origin_x=0,origin_y=-height*.435)
    elif layout=='between_curves':
        a=tuple((-width*.454+width*.908*i/128,-height*.26+height*.075*math.sin(math.tau*i/128-.5)) for i in range(129))
        b=tuple((-width*.454+width*.908*i/128,height*.21+height*.105*math.sin(math.tau*i/128+.3)) for i in range(129))
        s=replace(s,guide1=a,guide2=b);guides=[a,b]
    elif layout=='path':
        class DemoArc(ArcEvaluator):
            radius=min(width,height)*.41
            def getPointAtParameter(self,t):
                from types import SimpleNamespace
                return True,SimpleNamespace(x=self.radius*math.cos(t),y=self.radius*math.sin(t)-height*.14,z=0.)
        evaluator=DemoArc()
        s=replace(s,path_spacing=max(length if shape in LENGTH_SHAPES else size,along-gap)+gap+.03,
                  path_orientation='tangent' if orientation!='fixed' else 'fixed')
        s=replace(s,path_samples=sample_path(evaluator,s,lambda p:(p.x,p.y,p.z),lambda p:(p.x,p.y,p.z)))
        guides=[tuple((p.x,p.y) for p in evaluator.getStrokes(evaluator.start,evaluator.end,.01)[1])]
    if shape=='voronoi' or organic:s=replace(s,layout='grid',distribution_revision=1,clip_boundary=organic)
    return region,s,guides


def fmt(v):return format(v,'.7g')


def polygon_path(points):
    return 'M'+'L'.join(fmt(x)+','+fmt(-y) for x,y in points)+'Z'


def cell_path(c):
    # Millimetre conversion happens in the outer SVG transform, preserving the
    # exact geometry/units used by Fusion. No JS placement approximation.
    x,y=c.center
    if c.shape=='circle':
        r=c.size/2
        return f'M{fmt(x-r)},{fmt(-y)}a{fmt(r)},{fmt(r)} 0 1 0 {fmt(2*r)},0a{fmt(r)},{fmt(r)} 0 1 0 {fmt(-2*r)},0Z'
    if c.shape=='slot':
        a,b=c.spine;r=c.size/2
        nx,ny=-math.sin(c.angle)*r,math.cos(c.angle)*r
        pts=((a[0]+nx,a[1]+ny),(b[0]+nx,b[1]+ny),(b[0]-nx,b[1]-ny),(a[0]-nx,a[1]-ny))
        p,q,t,u=pts
        return f'M{fmt(p[0])},{fmt(-p[1])}L{fmt(q[0])},{fmt(-q[1])}A{fmt(r)},{fmt(r)} 0 0 1 {fmt(t[0])},{fmt(-t[1])}L{fmt(u[0])},{fmt(-u[1])}A{fmt(r)},{fmt(r)} 0 0 1 {fmt(p[0])},{fmt(-p[1])}Z'
    if c.shape=='ellipse':
        # Exact SVG ellipse represented by two half-arcs in the world basis.
        a,b=c.at((-c.length/2,0)),c.at((c.length/2,0))
        rx,ry=c.length/2,c.size/2;angle=-math.degrees(c.angle)
        return f'M{fmt(a[0])},{fmt(-a[1])}A{fmt(rx)},{fmt(ry)} {fmt(angle)} 1 0 {fmt(b[0])},{fmt(-b[1])}A{fmt(rx)},{fmt(ry)} {fmt(angle)} 1 0 {fmt(a[0])},{fmt(-a[1])}Z'
    if c.shape in ORGANIC_FIELDS:
        result='M'+fmt(c.contour[0].start[0])+','+fmt(-c.contour[0].start[1])
        for edge in c.contour:
            result+='C'+','.join(fmt(v) for p in (edge.control1,edge.control2,edge.end) for v in (p[0],-p[1]))
        return result+'Z'
    if c.shape=='voronoi' and c.corner_radius>0:
        result='M'+fmt(c.contour[0].start[0])+','+fmt(-c.contour[0].start[1])
        for edge in c.contour:
            x,y=edge.end
            if edge.center is None:result+='L'+fmt(x)+','+fmt(-y)
            else:
                r=math.dist(edge.start,edge.center)
                result+=f'A{fmt(r)},{fmt(r)} 0 {int(abs(edge.sweep)>math.pi)} {int(edge.sweep<0)} {fmt(x)},{fmt(-y)}'
        return result+'Z'
    return polygon_path(c.vertices)


def area(c):
    if c.shape=='circle':return math.pi*c.size**2/4
    if c.shape=='slot':return math.pi*c.size**2/4+(c.length-c.size)*c.size
    if c.shape=='ellipse':return math.pi*c.length*c.size/4
    p=c.vertices
    return abs(sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(p,p[1:]+p[:1])))/2


def visible_area(cell,cut):
    if cut is None:
        return area(cell)
    points=(tuple((cell.center[0]+cell.size/2*math.cos(i*math.tau/96),
                   cell.center[1]+cell.size/2*math.sin(i*math.tau/96)) for i in range(96))
            if cell.shape=='circle' else cell.vertices)
    points=clip_polygon_convex(points,cut.loops[0].points)
    return abs(sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(points,points[1:]+points[:1])))/2


def compute(data):
    started=perf_counter()
    region,s,guides=prepare(data)
    cells=generate(region,s)
    cut=convex_inset(region,s.margin) if s.shape in ORGANIC_SHAPES else None
    if cut is not None:
        cells=[c for c in cells if overlaps(c,cut,cut.segments)]
        if not cells:raise ValueError('No openings remain. Reduce Web Thickness or Edge Offset, or increase Cell Size.')
    outer=' '.join(polygon_path(l.points) for l in region.loops)
    holes=' '.join(cell_path(c) for c in cells)
    panel_area=sum(abs(sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(l.points,l.points[1:]+l.points[:1])))/2*(1 if l.outer else -1) for l in region.loops)
    points=[p for l in region.loops for p in l.points]
    box=[min(p[0] for p in points),-max(p[1] for p in points),max(p[0] for p in points)-min(p[0] for p in points),max(p[1] for p in points)-min(p[1] for p in points)]
    open_area=sum(visible_area(c,cut) for c in cells)
    return dict(outer=outer,holes=holes,box=box,clip=' '.join(polygon_path(l.points) for l in cut.loops) if cut else None,guides=['M'+'L'.join(fmt(x)+','+fmt(-y) for x,y in p) for p in guides],
                count=len(cells),open_area=round(open_area/panel_area*100,1),
                milliseconds=round((perf_counter()-started)*1000),settings={k:v for k,v in s.__dict__.items() if k not in ('guide1','guide2','path_samples')},
                first_center=cells[0].center,revision=s.distribution_revision)


def compute_json(payload):return json.dumps(compute(json.loads(payload)),separators=(',',':'))
