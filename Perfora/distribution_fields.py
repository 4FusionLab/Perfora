# SPDX-License-Identifier: GPL-3.0-only
"""Shared revision 2 fields, independent of Fusion. All lengths are cm.

Unlike the shipped candidate rejection scheme, solve a whole field's spacing
before clipping it to the source. A clearance conflict rebuilds the field; it
never silently punches a missing sample out of a row. Legacy features keep revision 1; new native commands select revision 2.
"""
from dataclasses import dataclass
import math
from time import perf_counter
from .geometry import (EPS, Cell, Settings, Loop, Region, fits, overlaps, dist, segment_distance, rotate, placement_center, enclosing_radius)
from .curves import ArcPath
from .distributions import _poisson, _DistanceTree
from bisect import bisect_right

NAMES = ('contour', 'fan', 'phyllotaxis', 'poisson', 'wave', 'chevron', 'running_bond', 'between_curves')


@dataclass
class Field:
    cells: list
    strokes: list
    region: Region
    settings: Settings
    milliseconds: float
    scale: float
    passes: int
    gap: float




def _sample_path(path, pitch, closed=False):
    count = max(1, math.floor(path.length/pitch))
    # For a closed curve, a short chord can occur despite sufficient arc length.
    # Reduce the whole ring's integer count instead of deleting one of its holes.
    if closed:
        while count > 1:
            pts = [path.at(i/count) for i in range(count)]
            if min(dist(pts[i-1], p) for i,p in enumerate(pts)) >= pitch-1e-8:
                break
            count -= 1
    for i in range(count if closed else count+1):
        t = i/count
        p = path.at(t)
        a,b = path.at((t-.0002)%1 if closed else max(0,t-.0002)), path.at((t+.0002)%1 if closed else min(1,t+.0002))
        yield p, math.atan2(b[1]-a[1],b[0]-a[0])


def _clearance(a,b):
    # Exact capsule distance for the two acceptance shapes (circle/slot).
    if a.shape in ('circle','slot') and b.shape in ('circle','slot'):
        return segment_distance(*a.spine,*b.spine)-(a.size+b.size)/2
    return dist(a.center,b.center)-_radius(a)-_radius(b)


def _radius(c):
    if c.shape in ('slot','ellipse'):return max(c.length,c.size)/2
    if c.shape=='circle':return c.size/2
    return max(dist(c.center,p) for p in c.vertices)


def minimum_gap(cells, required=None, _refine=True):
    # Local broad phase is sufficient for proving a requested minimum.
    if not cells:
        return math.inf
    reach=2*max(_radius(c) for c in cells)+(required if required is not None else 1)
    buckets={}
    nearest=math.inf
    for c in cells:
        x,y=(math.floor(v/reach) for v in c.center)
        for i in range(x-1,x+2):
            for j in range(y-1,y+2):
                for other in buckets.get((i,j),()):
                    nearest=min(nearest,_clearance(c,other))
        buckets.setdefault((x,y),[]).append(c)
    # The first radius proves the requested lower bound, but can miss the
    # actual nearest pair when it is farther apart than that bound. Refine
    # using the best known value before reporting a measured minimum.
    if _refine and math.isfinite(nearest):
        return minimum_gap(cells,nearest,False)
    return nearest


def _draft(name, region, s, factor, orientation):
    length=s.slot_length if s.shape=='slot' else s.size if s.shape=='circle' else 2*enclosing_radius(s)
    along=max(length+s.gap,s.along_spacing)*factor
    normal=max(s.size+s.gap,s.row_spacing)*factor
    if s.shape not in ('circle','slot'):normal=along
    if orientation=='fixed' and s.shape=='slot' and name in ('contour','fan','wave','chevron'):
        normal=along
    strokes=[]
    samples=[]
    outer=[p for l in region.loops if l.outer for p in l.points]
    x0,x1=min(p[0] for p in outer),max(p[0] for p in outer)
    y0,y1=min(p[1] for p in outer),max(p[1] for p in outer)
    reach=max(math.hypot(x,y) for x,y in outer)+length+s.gap
    if reach/min(along,normal)>3000:
        raise ValueError('The field exceeds the candidate budget. Increase spacing.')
    def path(points, closed=False):
        ap=ArcPath(points,closed)
        strokes.append(ap.points)
        samples.extend(_sample_path(ap,along,closed))
    if name=='contour':
        # Same sampled signed-distance offset geometry as the actual generator.
        # Ring closure is solved by integer count, with a shared geometric guard.
        for ap in _contour_paths(region,s,length/2,along,normal*1.16):
            span=min(max(p[k] for p in ap.points)-min(p[k] for p in ap.points) for k in (0,1))
            if span<2.2*along:
                continue  # Intentional solid core, no collapsed medial-axis rings.
            strokes.append(ap.points)
            samples.extend(_sample_path(ap,along,True))
    elif name=='fan':
        full=abs(s.fan_angle-math.tau)<EPS
        rays=(math.ceil(s.fan_angle/s.fan_angular_step)+(0 if full else 1)
              if s.fan_angular_step else s.fan_rays)
        delta=(s.fan_angular_step or s.fan_angle/(rays if full else max(1,rays-1)))
        _study_budget(rays*(reach/along+1))
        # A common inner radius makes every ray continuous and starts all rays
        # on the same arc. No greedy deletion near the apex.
        r0=max(s.start_radius,normal/(2*math.sin(delta/2)) if rays>1 else 0)
        origin=(0,0)
        for i in range(rays):
            a=i*delta
            r=r0
            pts=[]
            while r<reach:
                p=(origin[0]+r*math.cos(a),origin[1]+r*math.sin(a))
                pts.append(p)
                samples.append((p,a))
                r+=along
            strokes.append(tuple(pts))
    elif name=='phyllotaxis':
        # Preserve every Vogel index. Spacing is increased globally if needed.
        nominal=max((length if orientation=='fixed' else s.size)+s.gap,s.along_spacing if orientation=='fixed' else s.row_spacing)
        c=nominal*factor/(1.5*math.sqrt(s.phyllotaxis_density))
        golden=math.pi*(3-math.sqrt(5))
        _study_budget((reach/c)**2)
        for i in range(math.ceil((reach/c)**2)):
            r=c*math.sqrt(i+.5)
            a=i*golden
            samples.append(((r*math.cos(a),r*math.sin(a)),a+math.pi/2))
        # Parastichy families show what the eye should read; not cut geometry.
        for stride in (21,34):
            for start in range(stride):
                strokes.append(tuple(samples[i][0] for i in range(start,len(samples),stride)))
    elif name=='poisson':
        # Existing deterministic Bridson field already has an explicit spacing.
        samples=[(p,0) for p in _poisson(s,(x0,x1,y0,y1),(0,0),along)]
    elif name=='wave':
        amplitude=s.wave_amplitude
        wavelength=s.wave_length
        row_step=normal*math.hypot(1,amplitude*math.tau/wavelength)+2*amplitude*abs(math.sin(s.wave_row_phase/2))
        extent=math.ceil(max(abs(x0),abs(x1))/wavelength+1)*wavelength
        sampling_step=min(along/24,wavelength/100)
        count=math.ceil(extent/sampling_step)
        extent=count*sampling_step
        _study_budget(count*2)
        _study_budget(((y1-y0+2*amplitude)/row_step+4)*(2*extent*math.hypot(1,amplitude*math.tau/wavelength)/along+3))
        for row in range(math.floor((y0-amplitude)/row_step)-1,math.ceil((y1+amplitude)/row_step)+2):
            phase=s.wave_phase+row*s.wave_row_phase
            pts=[(-extent+2*extent*i/(count*2),row*row_step+amplitude*math.sin(math.tau*(-extent+2*extent*i/(count*2))/wavelength+phase)) for i in range(count*2+1)]
            # Arc samples anchored at x=0: crop/source changes cannot rephase it.
            center=count
            ap_left,ap_right=ArcPath(tuple(reversed(pts[:center+1]))),ArcPath(pts[center:])
            strokes.append(tuple(pts))
            for ap in (ap_left,ap_right):
                for i in range(math.floor(ap.length/along)+1):
                    t=i*along/ap.length
                    p=ap.at(t)
                    x=p[0]
                    angle=math.atan(amplitude*math.tau/wavelength*math.cos(math.tau*x/wavelength+phase))
                    if ap is ap_left and i==0:
                        continue
                    samples.append((p,angle))
    elif name=='chevron':
        angle=s.chevron_angle
        step_y=normal/math.cos(angle)
        dx=along*math.cos(angle)
        extent=max(abs(x0),abs(x1))+along
        _study_budget(((y1-y0+extent*math.tan(angle))/step_y+4)*(2*extent/dx+2))
        for row in range(math.floor((y0-extent*math.tan(angle))/step_y)-1,math.ceil(y1/step_y)+2):
            y=row*step_y
            strokes.append(((-extent,y+extent*math.tan(angle)),(0,y),(extent,y+extent*math.tan(angle))))
            # Mirror half-pitch about the ridge. Tangent slots cannot share a
            # single apex: paired ends make a clean, intentional central seam.
            for side in (-1,1):
                for col in range(math.ceil(extent/dx)):
                    x=(col+.5)*dx*side
                    samples.append(((x,y+abs(x)*math.tan(angle)),side*angle))
    elif name=='running_bond':
        # This IS a staggered grid, with row phase as a parameter, not a new
        # distribution family. Half shift gives the familiar two-row pattern.
        _study_budget(((y1-y0)/normal+4)*((x1-x0)/along+6))
        for row in range(math.floor(y0/normal)-1,math.ceil(y1/normal)+2):
            y=row*normal
            shift=(row*s.bond_shift % 1)*along
            strokes.append(((x0-along,y),(x1+along,y)))
            for col in range(math.floor(x0/along)-2,math.ceil(x1/along)+3):
                samples.append(((col*along+shift,y),0))
    elif name=='between_curves':
        from .curves import prepare_guides
        a,b,fractions=prepare_guides(s.guide1,s.guide2,reverse=s.guide_reverse)
        first=[a.at(i/256) for i in range(257)]
        second=[b.at(i/256) for i in range(257)]
        # Shared parameter stations across every row. Independent arc-length
        # counts made adjacent rows lose their cross-field alignment.
        width=min(dist(p,q) for p,q in zip(first,second))
        rows=min(s.guide_rows-1,max(1,math.floor(width/normal)))
        cols=max(1,math.floor(min(a.length,b.length)/along))
        _study_budget((rows+1)*(cols+1))
        for row in range(rows+1):
            v=row/rows
            pts=[((1-v)*p[0]+v*q[0],(1-v)*p[1]+v*q[1]) for p,q in zip(first,second)]
            ap=ArcPath(pts)
            strokes.append(ap.points)
            for col in range(cols+1):
                # Shared normalized guide stations, no guide rescaling.
                t=col/cols
                idx=min(255,math.floor(t*256))
                f=t*256-idx
                p=tuple(pts[idx][k]*(1-f)+pts[idx+1][k]*f for k in (0,1))
                a,b=pts[max(0,idx-1)],pts[min(256,idx+1)]
                samples.append((p,math.atan2(b[1]-a[1],b[0]-a[0])))
    else:
        raise ValueError('Unknown study.')
    cells=[Cell(p,s.shape,s.size,s.slot_length,(a if orientation=='tangent' else 0)+s.shape_angle,
                s.arm_width,s.star_ratio,s.star_points) for p,a in samples]
    # Exact partial contours are resolved by the common CAD clipping adapter.
    # Keep every intersecting candidate here, including centers outside the face.
    cells=[c for c in cells if (overlaps(c,region,region._boundary_index) if s.clip_boundary
                               else fits(c,region,region._boundary_index,s.margin))]
    return cells,strokes


def build_field(region,s):
    """Shared versioned kernel used by geometry.generate and visual regression.

    Revision 2 accepts repeating shapes. Partial-hole candidates go through
    the same exact clipping path as grid, circular and legacy distributions.
    """
    if s.shape=='voronoi':
        raise ValueError('Distribution revision 2 requires repeating hole shapes.')
    s.validate()
    origin=placement_center(region,s)
    def local(p):return rotate((p[0]-origin[0],p[1]-origin[1]),-s.grid_angle)
    local_region=Region(tuple(Loop(tuple(local(p) for p in l.points),l.outer) for l in region.loops),region.tolerance,
                        local(region.scope_center) if region.scope_center is not None else None,region.scope_radius)
    from dataclasses import replace
    local_s=replace(s,grid_angle=0,origin_x=0,origin_y=0,offset_x=0,offset_y=0,
                    guide1=tuple(local(p) for p in s.guide1),guide2=tuple(local(p) for p in s.guide2))
    factor=1.
    if s.shape=='slot' and s.layout_orientation=='tangent' and s.layout=='contour':factor=1.3/1.12
    if s.shape=='slot' and s.layout_orientation=='tangent' and s.layout=='phyllotaxis':factor=1.7/1.12
    started=perf_counter()
    for attempt in range(48):
        cells,strokes=_draft(s.layout,local_region,local_s,factor,s.layout_orientation)
        _study_budget(len(cells))
        clearance=minimum_gap(cells,s.gap)
        if clearance>=s.gap-1e-8:
            if not cells:raise ValueError('No holes fit in the region.')
            if len(cells)>s.limit:raise ValueError('The hole count exceeds Maximum Holes.')
            def world(p):
                x,y=rotate(p,s.grid_angle)
                return x+origin[0],y+origin[1]
            cells=[replace(c,center=world(c.center),angle=c.angle+s.grid_angle) for c in cells]
            strokes=[tuple(world(p) for p in path) for path in strokes]
            effective=factor*max(s.size+s.gap,s.along_spacing)/(s.size+s.gap)
            if s.shape=='slot':effective=factor*max(s.slot_length+s.gap,s.along_spacing)/(s.slot_length+s.gap)
            return Field(cells,strokes,region,s,(perf_counter()-started)*1000,effective,attempt+1,clearance)
        factor*=1.045
    raise ValueError('Cannot make a coherent field with the requested clearance.')




# Signed-distance tracing retained from Perfora.distributions; different sampling above.
def _contour_paths(region, s, radius, along, row_step):
    # A shared triangulated signed-distance field naturally handles components
    # splitting, merging around voids and vanishing. Never offset each vertex
    # independently: that produces self-crossings at concave necks.
    points = [p for loop in region.loops for p in loop.points]
    x0, x1 = min(p[0] for p in points), max(p[0] for p in points)
    y0, y1 = min(p[1] for p in points), max(p[1] for p in points)
    h = min(row_step/6, s.contour_tolerance/math.sqrt(2))
    nx, ny = math.ceil((x1-x0)/h)+2, math.ceil((y1-y0)/h)+2
    if nx*ny > 180000 or ny*len(region.segments) > 12000000:
        raise ValueError('Contour exceeds the sampling budget. Increase Contour Tolerance or simplify the boundary.')
    vertices, values = [], []
    tree = _DistanceTree(region.segments)
    for j in range(ny+1):
        y = y0-h+j*h
        crossings = [(loop.outer, sorted(a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1])
                                        for a,b in zip(loop.points, loop.points[1:]+loop.points[:1])
                                        if (a[1] > y) != (b[1] > y))) for loop in region.loops]
        for i in range(nx+1):
            p = (x0-h+i*h, y)
            d = tree.nearest(p)
            inside = (any(bisect_right(xs,p[0]) % 2 for outer,xs in crossings if outer) and
                      not any(bisect_right(xs,p[0]) % 2 for outer,xs in crossings if not outer))
            vertices.append(p)
            values.append(d if inside else -d)
    first = s.margin+radius+region.tolerance
    levels = max(0, math.floor((max(values)-first)/row_step)+1)
    _study_budget(levels)
    contours = [{} for _ in range(levels)]
    positions = [{} for _ in range(levels)]
    for j in range(ny):
        for i in range(nx):
            n = j*(nx+1)+i
            for tri in ((n,n+1,n+nx+2), (n,n+nx+2,n+nx+1)):
                lo = max(0, math.ceil((min(values[k] for k in tri)-first)/row_step))
                hi = min(levels-1, math.floor((max(values[k] for k in tri)-first)/row_step))
                for level in range(lo, hi+1):
                    height = first+level*row_step
                    contacts = []
                    for a,b in zip(tri, tri[1:]+tri[:1]):
                        va, vb = values[a]-height, values[b]-height
                        if (va > 0) == (vb > 0):
                            continue
                        t = va/(va-vb)
                        # Share exact vertex contacts too, avoiding microscopic
                        # gaps and degree-four artifacts when a level hits a node.
                        key = (a,a) if t < 1e-10 else (b,b) if t > 1-1e-10 else tuple(sorted((a,b)))
                        p,q = vertices[a], vertices[b]
                        positions[level][key] = (p[0]+t*(q[0]-p[0]), p[1]+t*(q[1]-p[1]))
                        if key not in contacts:
                            contacts.append(key)
                    if len(contacts) == 2 and contacts[0] != contacts[1]:
                        a,b = contacts
                        contours[level].setdefault(a,set()).add(b)
                        contours[level].setdefault(b,set()).add(a)
    for graph, points in zip(contours, positions):
        if any(len(v) != 2 for v in graph.values()):
            raise ValueError('Contour topology is ambiguous at this tolerance. Change Contour Tolerance or Row Spacing.')
        pending = set(graph)
        while pending:
            start = min(pending)
            loop, previous, current = [], None, start
            while True:
                pending.discard(current)
                loop.append(points[current])
                nxt = min(graph[current]-{previous})
                previous, current = current, nxt
                if current == start:
                    break
                if len(loop) > len(graph):
                    raise ValueError('Unable to close an offset contour.')
            if len(loop) >= 3:
                yield ArcPath(loop, closed=True)



def _study_budget(count):
    if not math.isfinite(count) or count > 100000:
        raise ValueError("Study exceeds the candidate budget.")
