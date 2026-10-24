# SPDX-License-Identifier: GPL-3.0-only
"""Pure local-tool placement and separation on non-planar surface charts."""
from dataclasses import dataclass, replace
import math

from . import geometry as geo
from .cylindrical_geometry import enclosing_radius, tool_cell, generate_voronoi, CylinderRegion


# A distribution is offered only where its chart retains a readable motif.
SURFACE_DISTRIBUTIONS = {
    'cylinder': ('grid', 'running_bond', 'poisson'),
    'cone': ('grid', 'running_bond'),
    'freeform': ('grid', 'running_bond', 'poisson', 'wave', 'chevron'),
}


def validate_distribution(kind, settings):
    if settings.layout not in SURFACE_DISTRIBUTIONS[kind]:
        raise ValueError('This Distribution is not available on ' + kind + ' faces. Select a compatible Distribution.')


def add(a, b):
    return tuple(x+y for x,y in zip(a,b))


def sub(a, b):
    return tuple(x-y for x,y in zip(a,b))


def mul(a, k):
    return tuple(x*k for x in a)


def dot(a, b):
    return sum(x*y for x,y in zip(a,b))


def length(a):
    return math.sqrt(dot(a,a))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


class SingularTangentError(ValueError):
    """A local frame is undefined; regular sites on the face can still work."""


def unit(a):
    size = length(a)
    if size < 1e-12:
        raise SingularTangentError('The surface has a singular tangent. Move the pattern away from the singularity.')
    return mul(a, 1/size)


def local_cell(cell):
    x,y = cell.center
    return replace(cell, center=(0.,0.), polygon=tuple((a-x,b-y) for a,b in cell.polygon))


@dataclass(frozen=True)
class ConeRegion:
    radius0: float
    slope: float
    reference_radius: float
    meridian_start: float
    height: float
    sweep: float = math.tau


def conical_cells(region, settings, low, high, anchor=None):
    """Physical meridian pitch and local ring capacity, without tip starvation.

    The number of columns changes with local circumference. Closed rows have
    opposing sites, with a half-pitch phase on alternate Staggered rows. Full
    finite-tool separation is checked by the caller after surface placement.
    """
    slant = math.hypot(1., region.slope)
    cell = tool_cell(settings)
    r = enclosing_radius(cell)
    spacing = max(2*r + settings.gap + 1e-8, settings.row_spacing if settings.layout == 'running_bond' else 0)
    closed = abs(region.sweep-math.tau) < 1e-8
    width = region.reference_radius*region.sweep
    oy = settings.offset_y + (anchor[1] if anchor is not None else region.height/2)
    ox = settings.offset_x + (anchor[0] if anchor is not None else 0.)
    first = math.ceil((-r-oy)/spacing)
    last = math.floor((region.height+r-oy)/spacing)
    if last-first > 100000:
        raise ValueError('The surface pattern is too dense. Increase spacing or Maximum Holes.')
    result = []
    for row in range(first, last+1):
        y = oy + row*spacing
        radius = region.radius0 + region.slope*(y+region.meridian_start)/slant
        # The finite normal interval determines the smallest tool-axis radius.
        # Include the automatic entry lead used for a curved tangent section.
        curvature_radius = radius*slant
        if curvature_radius <= r:
            continue
        lead = r*r/(curvature_radius+math.sqrt(curvature_radius**2-r*r)) + 1e-5
        rho = radius+min(low, high, -lead)/slant
        if rho <= spacing/2:
            continue
        along = max(2*r+settings.gap+1e-8, settings.along_spacing if settings.layout == 'running_bond' else 0)
        if rho <= along/2: continue
        angular = 2*math.asin(along/(2*rho))
        if closed:
            count = math.floor(region.sweep/angular)
            count -= count % 2
            if count < 2:
                continue
            angular = region.sweep/count
            start = ((row*settings.bond_shift)%1)*angular if settings.layout == 'running_bond' else angular/2 if settings.staggered and row%2 else 0.
            columns = range(count)
        else:
            count = math.floor(region.sweep/angular)+1
            start = (region.sweep-(count-1)*angular)/2
            if settings.layout == 'running_bond':
                start += ((row*settings.bond_shift)%1)*angular
            elif settings.staggered and row%2:
                start += angular/2
            columns = range(-1, count+1)
        for col in columns:
            x = (start+col*angular)*region.reference_radius
            yy = y
            placed = cell
            if settings.grid_angle:
                dx,dy = geo.rotate((x-width/2,y-region.height/2),settings.grid_angle)
                x,yy = dx+width/2,dy+region.height/2
                placed = replace(cell,angle=cell.angle+settings.grid_angle)
            x += ox
            if closed:
                x %= width
            if yy+r < 0 or yy-r > region.height or not closed and (x+r < 0 or x-r > width):
                continue
            result.append((x,yy,placed))
            if len(result) > settings.limit+max(20,settings.limit//2):
                raise ValueError('The surface pattern is too dense. Increase spacing or Maximum Holes.')
    return tuple(result)


def periodic_cells(radius, height, sweep, settings, depth, closed=True, anchor=None):
    """Stable chart phase, including boundary candidates for exact later trim."""
    width = radius*sweep
    if settings.shape == 'voronoi' and settings.layout == 'grid':
        source = CylinderRegion(radius, height, sweep)
        holes = generate_voronoi(source, replace(settings, grid_angle=0, clip_boundary=False),
                                 min(depth, radius*.9), 0, sweep, 0, height, retain_boundary_cells=True)
        cells = [(h.angle*radius, h.axial, h.cell) for h in holes]
    elif settings.layout == 'grid':
        r = enclosing_radius(tool_cell(settings))
        rho = radius-depth
        if rho <= r+settings.gap/2:
            raise ValueError('Reduce Distance, hole size, or Web Thickness near the surface axis.')
        spacing = 2*r+settings.gap
        step = 2*math.asin(spacing/(2*rho))
        columns = max(1, math.floor(sweep/step)) if closed else max(1, math.ceil(sweep/step))
        angular = sweep/columns if closed else step
        rows = range(-math.ceil(height/(2*spacing))-1, math.ceil(height/(2*spacing))+2)
        cells = []
        for row in rows:
            for col in range(0 if closed else -1, columns if closed else columns+2):
                # Closed rows contain exactly N sites, including a single seam site.
                if closed and not 0 <= col < columns:
                    continue
                shift = angular/2 if settings.staggered and row%2 else 0
                x = (col*angular+shift)*radius
                cells.append((x, height/2+row*spacing, tool_cell(settings)))
    else:
        region = geo.rectangle_region(width, height)
        base = geo.generate(region, replace(settings, clip_boundary=True, margin=0,
            spread_radius=0, grid_angle=0, offset_x=0, offset_y=0, origin_x=None, origin_y=None))
        cells = [(c.center[0]+width/2, c.center[1]+height/2, local_cell(c)) for c in base]
    output, seen = [], set()
    ox = settings.offset_x+((anchor[0]-width/2 if settings.layout=='circular' else anchor[0]) if anchor is not None else 0)
    oy = settings.offset_y+(anchor[1]-height/2 if anchor is not None else 0)
    for x,y,cell in cells:
        if settings.grid_angle:
            dx,dy = geo.rotate((x-width/2,y-height/2), settings.grid_angle)
            x,y = dx+width/2,dy+height/2
            if cell.shape == 'voronoi':
                cell = replace(cell, polygon=tuple(geo.rotate(v,settings.grid_angle) for v in cell.vertices))
            else:
                cell = replace(cell, angle=cell.angle+settings.grid_angle)
        x,y = x+ox,y+oy
        if closed:
            x %= width
        r = enclosing_radius(cell)
        if y+r < 0 or y-r > height or not closed and (x+r < 0 or x-r > width):
            continue
        key = round(x,8),round(y,8)
        if key in seen:
            continue
        seen.add(key)
        output.append((x,y,cell))
        if len(output) > settings.limit+max(20, settings.limit//2):
            raise ValueError('The surface pattern is too dense. Increase spacing or Maximum Holes.')
    return tuple(output)


def closest_segments(a0, a1, b0, b1):
    """Closest points on finite 3D segments, including parallel/zero-length ones."""
    u,v,w = sub(a1,a0),sub(b1,b0),sub(a0,b0)
    aa,bb,cc,dd,ee = dot(u,u),dot(u,v),dot(v,v),dot(u,w),dot(v,w)
    clamp = lambda x:max(0.,min(1.,x))
    if aa < 1e-20:
        s,t = 0.,clamp(ee/cc) if cc > 1e-20 else 0.
    elif cc < 1e-20:
        s,t = clamp(-dd/aa),0.
    else:
        denominator = aa*cc-bb*bb
        s = clamp((bb*ee-cc*dd)/denominator) if denominator > 1e-20 else 0.
        t = (bb*s+ee)/cc
        if t < 0:
            s,t = clamp(-dd/aa),0.
        elif t > 1:
            s,t = clamp((bb-dd)/aa),1.
    return add(a0,mul(u,s)),add(b0,mul(v,t))


def separating_constraints(placements, gap):
    """Local halfplanes protecting entire finite tool segments, not only entries.

    Each placement is (origin,u,v,n,low,high,radius). Spatial buckets bound work
    for dense patterns; all possibly intersecting enclosing capsules are visited.
    """
    if not placements:
        return []
    reach = max(max(abs(p[4]),abs(p[5]))+p[6] for p in placements)
    size = max(2*reach+gap,1e-5)
    buckets = {}
    for i,p in enumerate(placements):
        key = tuple(math.floor(v/size) for v in p[0])
        buckets.setdefault(key,[]).append(i)
    result = [[] for _ in placements]
    for i,(origin,u,v,n,low,high,radius) in enumerate(placements):
        key = tuple(math.floor(x/size) for x in origin)
        for a in (-1,0,1):
            for b in (-1,0,1):
                for c in (-1,0,1):
                    for j in buckets.get((key[0]+a,key[1]+b,key[2]+c),()):
                        if j <= i:
                            continue
                        q,qu,qv,qn,qlow,qhigh,qr = placements[j]
                        ca,cb = closest_segments(add(origin,mul(n,low)),add(origin,mul(n,high)),
                                                add(q,mul(qn,qlow)),add(q,mul(qn,qhigh)))
                        delta = sub(cb,ca)
                        distance = length(delta)
                        if distance >= radius+qr+gap-1e-9:
                            continue
                        if distance < 1e-9:
                            raise ValueError('Surface normals cross within Distance. Reduce Distance or increase spacing.')
                        normal = mul(delta,1/distance)
                        boundary = dot(normal,mul(add(ca,cb),.5))
                        for index,o,x,y,z,lo,hi,sign in ((i,origin,u,v,n,low,high,1),
                                                       (j,q,qu,qv,qn,qlow,qhigh,-1)):
                            nn = mul(normal,sign)
                            bound = boundary*sign-gap/2-dot(nn,o)-max(dot(nn,z)*lo,dot(nn,z)*hi)
                            result[index].append((dot(nn,x),dot(nn,y),bound))
    return result


def spaced_indices(placements,gap,groups=None):
    """Keep full repeating tools in stable order, including periodic seam contacts.

    A rotated chart or circular rings can put distant chart sites together in
    3D. Preserve section dimensions and drop the later conflicting site.
    """
    if not placements:
        return ()
    reach=max(max(abs(p[4]),abs(p[5]))+p[6] for p in placements)
    size=max(2*reach+gap,1e-5)
    buckets={}
    accepted=[]
    for i,(o,u,v,n,lo,hi,r) in enumerate(placements):
        key=tuple(math.floor(x/size) for x in o)
        allowed=True
        for a in (-1,0,1):
            for b in (-1,0,1):
                for c in (-1,0,1):
                    for j in buckets.get((key[0]+a,key[1]+b,key[2]+c),()):
                        if groups is not None and groups[i] == groups[j]: continue
                        q,_,_,qn,qlo,qhi,qr=placements[j]
                        ca,cb=closest_segments(add(o,mul(n,lo)),add(o,mul(n,hi)),
                                               add(q,mul(qn,qlo)),add(q,mul(qn,qhi)))
                        if length(sub(cb,ca))<r+qr+gap-1e-9:
                            allowed=False
                            break
        if allowed:
            accepted.append(i)
            buckets.setdefault(key,[]).append(i)
    return tuple(accepted)


class LengthMap:
    """Monotone physical arc length for a nonuniform curve parameter.

    Adaptive Simpson leaves retain positive quadratic speed integrals. Inverse
    queries use those integrals, never linear interpolation of raw UV values.
    The map is pure Python; the caller supplies physical derivative magnitude.
    """
    def __init__(self,speed,low,high,tolerance=1e-7):
        from bisect import bisect_right
        self._bisect=bisect_right
        self.low,self.high=low,high
        self.parts=[]
        def sample(t):
            value=speed(t)
            if not math.isfinite(value) or value<0:
                raise ValueError('Unable to measure the surface length.')
            return value
        def split(a,b,fa,fm,fb,depth,tol):
            m=(a+b)/2;l=sample((a+m)/2);r=sample((m+b)/2)
            whole=(b-a)*(fa+4*fm+fb)/6
            left=(m-a)*(fa+4*l+fm)/6;right=(b-m)*(fm+4*r+fb)/6
            def positive(x,y,z):
                aa=2*(x+z-2*y);bb=4*y-3*x-z
                t=-bb/(2*aa) if aa>0 else -1
                return not 0<t<1 or aa*t*t+bb*t+x>=0
            if depth>=5 and abs(left+right-whole)<=15*tol and positive(fa,l,fm) and positive(fm,r,fb):
                self.parts.extend(((a,m,fa,l,fm,left),(m,b,fm,r,fb,right)))
            elif depth>=18:
                raise ValueError('Unable to resolve surface length. Select a smaller regular region.')
            else:
                split(a,m,fa,l,fm,depth+1,tol/2)
                split(m,b,fm,r,fb,depth+1,tol/2)
        fa,fm,fb=sample(low),sample((low+high)/2),sample(high)
        split(low,high,fa,fm,fb,0,tolerance)
        self.starts=[p[0] for p in self.parts]
        self.lengths=[0.]
        for p in self.parts:self.lengths.append(self.lengths[-1]+p[5])
        self.total=self.lengths[-1]
        if self.total<1e-10:
            raise ValueError('The surface has no measurable length.')

    @staticmethod
    def _partial(part,t):
        a,b,fa,fm,fb,_=part
        aa=2*(fa+fb-2*fm);bb=4*fm-3*fa-fb
        return (b-a)*(aa*t*t*t/3+bb*t*t/2+fa*t)

    def parameter_at(self,distance):
        if distance<=0:
            return self.low+distance/max(self.parts[0][2],1e-12)
        if distance>=self.total:
            return self.high+(distance-self.total)/max(self.parts[-1][4],1e-12)
        i=min(self._bisect(self.lengths,distance)-1,len(self.parts)-1)
        part=self.parts[i];target=distance-self.lengths[i];lo,hi=0.,1.
        for _ in range(36):
            middle=(lo+hi)/2
            if self._partial(part,middle)<target:lo=middle
            else:hi=middle
        return part[0]+(part[1]-part[0])*(lo+hi)/2

    def length_at(self,parameter):
        if parameter<=self.low:
            return (parameter-self.low)*self.parts[0][2]
        if parameter>=self.high:
            return self.total+(parameter-self.high)*self.parts[-1][4]
        i=min(self._bisect(self.starts,parameter)-1,len(self.parts)-1)
        part=self.parts[i];t=(parameter-part[0])/(part[1]-part[0])
        return self.lengths[i]+self._partial(part,t)


def arc_pitch(radius,gap,curvature,low,high):
    """Surface arc pitch retaining the web between finite normal tools."""
    target=2*radius+gap
    if abs(curvature)<1e-9:return target
    r=1/abs(curvature)
    if r<=radius:return None
    lead=radius*radius/(r+math.sqrt(r*r-radius*radius))+1e-4
    lo,hi=min(low,-lead) if curvature>0 else low,max(high,lead) if curvature<0 else high
    side=1 if curvature>0 else -1
    rho=min(r+side*lo,r+side*hi)
    if rho<=target/2:return None
    return max(target,2*r*math.asin(target/(2*rho)))
