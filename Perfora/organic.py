# SPDX-License-Identifier: GPL-3.0-only
"""Bounded, deterministic scalar fields and variable-radius blue noise.

No CAD objects or third-party modules. Field topology is resolved on a finite
grid before circular-arc compression. A spanning forest connects material
islands, then a distance transform thickens those bridges. The sampling and
curve-fit allowances are included in the web, rather than taken out of it.
"""
from collections import deque
from dataclasses import replace
from functools import lru_cache
import math
import random

from . import geometry as g

FIELDS = g.ORGANIC_FIELDS
SHAPES = g.ORGANIC_SHAPES
LABELS = ('Smooth Noise', 'Reaction Diffusion', 'Directional Fibers', 'Ridged Noise / Topographic',
          'Gyroid Field', 'Blue Noise / Size Gradient')
PARAMETERS = {
    'organic_open': ('Field Fill (%)', '', '48'),
    'organic_direction': ('Direction', 'deg', '0 deg'),
    'organic_variation': ('Size Variation (%)', '', '65'),
    'organic_gradient': ('Size Gradient (%)', '', '75'),
}
MAX_NODES = 120000
MAX_EDGES = 16000
MAX_ITERATIONS = 1100


def validate(s):
    if s.layout != 'grid':
        raise ValueError('Organic hole shapes define their own field. Select a grid Distribution before choosing an organic shape.')
    if not isinstance(s.seed, int) or isinstance(s.seed, bool) or not 0 <= s.seed <= 2147483647:
        raise ValueError('Seed must be an integer between 0 and 2147483647.')
    if (not all(math.isfinite(v) for v in (s.organic_open, s.organic_direction,
                                          s.organic_variation, s.organic_gradient))
            or not 15 <= s.organic_open <= 75 or not 0 <= s.organic_variation <= 90
            or not -100 <= s.organic_gradient <= 100):
        raise ValueError('Field Fill must be 15–75%, Size Variation 0–90%, and Size Gradient −100–100%.')
    if s.radial_orientation or s.tangential_orientation or s.start_radius:
        raise ValueError('Organic fields do not use circular placement or hole orientation.')
    if s.size < s.gap * .6:
        raise ValueError('Increase Pattern Scale relative to Web Thickness to leave open organic holes.')


def _hash(seed, x, y):
    v = (seed ^ (x*0x9E3779B1) ^ (y*0x85EBCA77)) & 0xffffffff
    v = ((v ^ (v >> 16))*0x7FEB352D) & 0xffffffff
    v = ((v ^ (v >> 15))*0x846CA68B) & 0xffffffff
    return (v ^ (v >> 16))/4294967295


def noise(x, y, seed):
    """Quintic gradient noise (Perlin), stable across Python versions."""
    ix, iy = math.floor(x), math.floor(y)
    x, y = x-ix, y-iy
    u, v = x*x*x*(x*(x*6-15)+10), y*y*y*(y*(y*6-15)+10)
    def dot(a,b):
        angle = _hash(seed, ix+a, iy+b)*math.tau
        return (x-a)*math.cos(angle)+(y-b)*math.sin(angle)
    a,b,c,d=dot(0,0),dot(1,0),dot(0,1),dot(1,1)
    return (a+(b-a)*u)*(1-v)+(c+(d-c)*u)*v


def _field(kind, x, y, seed):
    phase = _hash(seed, 131, 7)*math.tau
    if kind == 'smooth_noise':
        return noise(x*.62,y*.62,seed)+.24*noise(x*1.24,y*1.24,seed+1)
    if kind == 'directional_fibers':
        # Direction is the long axis (chart X); transverse noise controls width.
        return noise(x*.16, y*1.25+.26*math.sin(x*.7+phase),seed)
    if kind == 'topographic':
        # Contours of a ridged low-frequency height field, including nested hills.
        height = 2.1*abs(noise(x*.19,y*.19,seed)) + .15*noise(x*.37,y*.37,seed+1)
        return math.cos(math.tau*(height*3.2+.10*x+phase/math.tau))
    # A genuine constant-z section of sin(x)cos(y)+sin(y)cos(z)+sin(z)cos(x).
    x,y = x*math.tau/2.2+phase,y*math.tau/2.2+phase*.73
    z = .72 + .14*math.sin(phase)
    return math.sin(x)*math.cos(y)+math.sin(y)*math.cos(z)+math.sin(z)*math.cos(x)


@lru_cache(maxsize=3)
def reaction(nx, ny, seed):
    """Periodic Gray–Scott, Du=1, Dv=.5, F=.04, k=.06, dt=1.

    Fixed iteration count and seeded patches on a periodic nine-point grid.
    Axial weights .2, diagonal weights .05. The solver is independent of
    contour resolution; only immutable scalar data is cached.
    """
    rng=random.Random(seed)
    n=nx*ny
    u=[1.]*n;v=[0.]*n
    # Dense seeded spots break symmetry and settle into coral/worm structures.
    for y in range(5,ny-4,13):
        for x in range(5,nx-4,13):
            xx,yy=x+rng.randrange(-2,3),y+rng.randrange(-2,3)
            for j in range(max(1,yy-2),min(ny-1,yy+3)):
                for i in range(max(1,xx-2),min(nx-1,xx+3)):
                    k=j*nx+i;u[k]=.5;v[k]=.25+.02*rng.random()
    for _ in range(MAX_ITERATIONS):
        a=u[:];b=v[:]
        for y in range(ny):
            ym,yp,row=(y-1)%ny*nx,(y+1)%ny*nx,y*nx
            for x in range(nx):
                xm,xp=(x-1)%nx,(x+1)%nx;k=row+x;uvv=u[k]*v[k]*v[k]
                lu=-u[k]+.2*(u[row+xm]+u[row+xp]+u[ym+x]+u[yp+x])+.05*(u[ym+xm]+u[ym+xp]+u[yp+xm]+u[yp+xp])
                lv=-v[k]+.2*(v[row+xm]+v[row+xp]+v[ym+x]+v[yp+x])+.05*(v[ym+xm]+v[ym+xp]+v[yp+xm]+v[yp+xp])
                a[k]=u[k]+lu-uvv+.04*(1-u[k])
                b[k]=v[k]+.5*lv+uvv-.10*v[k]
        u,v=a,b
    return tuple(v)


def _components(mask,nx,ny):
    """4-connected material labels; includes the retained outer frame."""
    owner=[-1]*len(mask);count=0
    for start,value in enumerate(mask):
        if value or owner[start]>=0:continue
        owner[start]=count;q=deque([start])
        while q:
            k=q.popleft();x,y=k%nx,k//nx
            for j in (k-1 if x else -1,k+1 if x+1<nx else -1,
                      k-nx if y else -1,k+nx if y+1<ny else -1):
                if j>=0 and not mask[j] and owner[j]<0:
                    owner[j]=count;q.append(j)
        count+=1
    return owner,count


def connect_material(mask,nx,ny):
    """Minimum spanning forest of shortest raster paths through open cells.

    Simultaneous unweighted wavefronts meet at the nearest components. Kruskal
    union prevents adding a gratuitous lattice of bridges to already connected
    material. Every newly carved path ends in the original solid material.
    """
    owner,count=_components(mask,nx,ny)
    if count<2:return
    parent=list(range(count));previous=[-1]*len(mask)
    queue=deque(k for k,v in enumerate(owner) if v>=0)
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def carve(i):
        while i>=0 and mask[i]:mask[i]=False;i=previous[i]
    while queue and count>1:
        k=queue.popleft();x,y=k%nx,k//nx
        for j in (k-1 if x else -1,k+1 if x+1<nx else -1,
                  k-nx if y else -1,k+nx if y+1<ny else -1):
            if j<0:continue
            if owner[j]<0:
                owner[j]=owner[k];previous[j]=k;queue.append(j)
            else:
                a,b=root(owner[k]),root(owner[j])
                if a!=b:
                    parent[b]=a;count-=1;carve(k);carve(j)


def _edt_line(f):
    """Squared Euclidean distance transform of a one-dimensional lower envelope."""
    n=len(f);sites=[0]*n;bounds=[-math.inf]+[math.inf]*n;k=0
    for q in range(1,n):
        s=((f[q]+q*q)-(f[sites[k]]+sites[k]*sites[k]))/(2*(q-sites[k]))
        while s<=bounds[k]:
            k-=1
            s=((f[q]+q*q)-(f[sites[k]]+sites[k]*sites[k]))/(2*(q-sites[k]))
        k+=1;sites[k]=q;bounds[k]=s;bounds[k+1]=math.inf
    result=[];k=0
    for q in range(n):
        while bounds[k+1]<q:k+=1
        result.append((q-sites[k])**2+f[sites[k]])
    return result


def distance_field(mask,nx,ny):
    far=float((nx+ny)**2)
    rows=[]
    for y in range(ny):rows.extend(_edt_line([far if p else 0. for p in mask[y*nx:(y+1)*nx]]))
    result=[0.]*len(mask)
    for x in range(nx):
        col=_edt_line([rows[y*nx+x] for y in range(ny)])
        for y,v in enumerate(col):result[y*nx+x]=math.sqrt(v)
    return result


def _contours(values,nx,ny,level):
    """Marching squares with solid diagonal bridges in ambiguous cells."""
    graph={};points={}
    for y in range(ny-1):
        for x in range(nx-1):
            k=y*nx+x;ids=(k,k+1,k+nx+1,k+nx)
            v=[values[i]-level for i in ids]
            case=sum(1<<i for i,a in enumerate(v) if a>0)
            if case in (0,15):continue
            contacts=[]
            for i in range(4):
                j=(i+1)%4
                if (v[i]>0)==(v[j]>0):continue
                a,b=ids[i],ids[j];key=(min(a,b),max(a,b))
                t=v[i]/(v[i]-v[j])
                points[key]=(a%nx+(b%nx-a%nx)*t,a//nx+(b//nx-a//nx)*t)
                contacts.append((i,key))
            if len(contacts)==2:pairs=[(contacts[0][1],contacts[1][1])]
            else:
                c=dict(contacts)
                pairs=[(c[3],c[0]),(c[1],c[2])] if case==5 else [(c[0],c[1]),(c[2],c[3])]
            for a,b in pairs:graph.setdefault(a,[]).append(b);graph.setdefault(b,[]).append(a)
    pending=set(graph)
    while pending:
        start=min(pending);current=start;previous=None;loop=[]
        while True:
            pending.discard(current);loop.append(points[current])
            neighbors=graph[current]
            if len(neighbors)!=2:raise ValueError('Unable to close the organic contour. Increase Pattern Scale.')
            nxt=neighbors[0] if neighbors[0]!=previous else neighbors[1]
            previous,current=current,nxt
            if current==start:break
            if len(loop)>len(graph):raise ValueError('The organic field topology is invalid.')
        yield tuple(loop)


def _area(points):
    return sum(a[0]*b[1]-a[1]*b[0] for a,b in g.edges(points))/2


def _smooth(points):
    # Uniform arclength resampling rounds a bridge tip at the motif scale,
    # instead of preserving hundreds of tiny raster corners. Chaikin then
    # creates a smooth, closed polygon without spline overshoot. The final
    # pairwise clearance check also covers changes at concave corners.
    lengths=[g.dist(a,b) for a,b in g.edges(points)]
    total=sum(lengths);count=max(8,math.ceil(total/2.0));uniform=[];edge=0;along=0.
    for i in range(count):
        target=i*total/count
        while edge+1<len(points) and along+lengths[edge]<target:
            along+=lengths[edge];edge+=1
        a,b=points[edge],points[(edge+1)%len(points)];t=(target-along)/max(lengths[edge],1e-12)
        uniform.append((a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t))
    points=tuple(uniform)
    for _ in range(2):
        points=tuple(p for a,b in g.edges(points) for p in
                     ((a[0]*.75+b[0]*.25,a[1]*.75+b[1]*.25),
                      (a[0]*.25+b[0]*.75,a[1]*.25+b[1]*.75)))
    return points


def _circle(a,b,c):
    ax,ay=b[0]-a[0],b[1]-a[1];bx,by=c[0]-a[0],c[1]-a[1]
    d=2*(ax*by-ay*bx)
    if abs(d)<1e-14:return None
    aa,bb=ax*ax+ay*ay,bx*bx+by*by
    return a[0]+(by*aa-ay*bb)/d,a[1]+(ax*bb-bx*aa)/d


def fit_contour(points,tolerance):
    """Greedy line/arc approximation with a bounded displacement budget.

    No spline overshoot, periodic seams or external approximation dependencies.
    Both vertices and segment midpoints are checked against a candidate arc.
    """
    points=tuple(points)+(points[0],);result=[];i=0
    while i<len(points)-1:
        best=g.ContourEdge(points[i],points[i+1]);end=i+1
        for j in range(i+2,min(len(points),i+97)):
            a,c=points[i],points[j];subset=points[i:j+1]
            if all(g.point_segment_distance(p,a,c)<=tolerance for p in subset):
                candidate=g.ContourEdge(a,c)
            else:
                center=_circle(a,points[(i+j)//2],c)
                if center is None:break
                r=g.dist(a,center)
                angles=[math.atan2(p[1]-center[1],p[0]-center[0]) for p in subset]
                increments=[math.remainder(b-a,math.tau) for a,b in zip(angles,angles[1:])]
                sweep=sum(increments)
                if abs(sweep)>math.pi or abs(sweep)<1e-8 or any(v*sweep<-1e-8 for v in increments):break
                probes=list(subset)+[((a[0]+b[0])/2,(a[1]+b[1])/2) for a,b in zip(subset,subset[1:])]
                if max(abs(g.dist(p,center)-r) for p in probes)>tolerance:break
                candidate=g.ContourEdge(a,c,center,sweep)
            best=candidate;end=j
        result.append(best);i=end
    return tuple(result)


def _simple(points):
    segments=list(g.edges(points))
    for i,(a,b) in enumerate(segments):
        for j in range(i+2,len(segments)-(1 if i==0 else 0)):
            c,d=segments[j]
            if (max(a[0],b[0])<min(c[0],d[0]) or max(c[0],d[0])<min(a[0],b[0])
                    or max(a[1],b[1])<min(c[1],d[1]) or max(c[1],d[1])<min(a[1],b[1])):continue
            if g.segment_distance(a,b,c,d)<1e-10:return False
    return True


def _separated(cells,gap,scale):
    """Protect new necks created when erosion splits an opening into pieces.

    Growing connected material alone does not bound the width of a *new*
    material neck. Visit larger contours first and omit conflicting fragments.
    Chord approximation allowances protect the analytic arcs, too.
    """
    buckets={};accepted=[]
    def bounds(points,padding):
        return (min(x for x,y in points)-padding,max(x for x,y in points)+padding,
                min(y for x,y in points)-padding,max(y for x,y in points)+padding)
    for cell in sorted(cells,key=lambda c:-abs(_area(c.polygon))):
        points=cell.vertices;box=bounds(points,gap+4*cell.curve_tolerance)
        keys=[(x,y) for x in range(math.floor(box[0]/scale),math.floor(box[1]/scale)+1)
                    for y in range(math.floor(box[2]/scale),math.floor(box[3]/scale)+1)]
        nearby={i for key in keys for i in buckets.get(key,())};safe=True
        for i in sorted(nearby):
            other=accepted[i];q=other.vertices;bb=bounds(q,0)
            if box[0]>bb[1] or box[1]<bb[0] or box[2]>bb[3] or box[3]<bb[2]:continue
            distance=gap+2*(cell.curve_tolerance+other.curve_tolerance)
            if g.point_in_polygon(points[0],q) or g.point_in_polygon(q[0],points):safe=False;break
            for a,b in g.edges(points):
                for c,d in g.edges(q):
                    if (max(a[0],b[0])+distance<min(c[0],d[0]) or max(c[0],d[0])+distance<min(a[0],b[0])
                            or max(a[1],b[1])+distance<min(c[1],d[1]) or max(c[1],d[1])+distance<min(a[1],b[1])):continue
                    if g.segment_distance(a,b,c,d)<distance:safe=False;break
                if not safe:break
            if not safe:break
        if safe:
            index=len(accepted);accepted.append(cell)
            for key in keys:buckets.setdefault(key,[]).append(index)
    return accepted


def generate(region,s):
    validate(s)
    if s.shape=='blue_noise':return blue_noise(region,s)
    angle=s.grid_angle+s.organic_direction
    outer=g.candidate_points(region,angle)
    x0,x1=min(p[0] for p in outer),max(p[0] for p in outer)
    y0,y1=min(p[1] for p in outer),max(p[1] for p in outer)
    # Normalized field units; one Pattern Scale contains 16 intervals. Halo
    # keeps candidates outside the exact source, enabling genuine partial trim.
    h=s.size/16;pad=2*s.size
    x0,y0=x0-pad,y0-pad
    nx,ny=math.ceil((x1-x0+pad)/h)+1,math.ceil((y1-y0+pad)/h)+1
    if nx*ny>MAX_NODES:
        raise ValueError('Organic field exceeds the sampling budget. Increase Pattern Scale or select a smaller region.')
    origin=g.rotate(g.placement_center(region,replace(s,grid_angle=angle)), -angle)
    if s.shape=='reaction_diffusion':
        # Solver wavelength is ~8 grid nodes; resample its physical scale onto
        # the same contour grid used by all other fields.
        rx=ry=64
        solver=reaction(rx,ry,s.seed)
        values=[]
        for y in range(ny):
            yy=((y0+y*h-origin[1])/s.size*12)%ry;j=int(yy);v=yy-j
            for x in range(nx):
                xx=((x0+x*h-origin[0])/s.size*12)%rx;i=int(xx);u=xx-i
                a,b=j*rx+i,j*rx+(i+1)%rx;c,d=((j+1)%ry)*rx+i,((j+1)%ry)*rx+(i+1)%rx
                values.append((solver[a]*(1-u)+solver[b]*u)*(1-v)+(solver[c]*(1-u)+solver[d]*u)*v)
    else:
        values=[_field(s.shape,(x0+x*h-origin[0])/s.size,(y0+y*h-origin[1])/s.size,s.seed)
                for y in range(ny) for x in range(nx)]
    threshold=sorted(values)[min(len(values)-1,int(len(values)*(1-s.organic_open/100)))]
    mask=[v>threshold for v in values]
    # Short cross-bridges split only overlong open components. The common 4x
    # scale envelope also bounds the deviation of curved-face normal tools.
    visited=set();span=64
    for start in range(len(mask)):
        if not mask[start] or start in visited:continue
        q=deque([start]);visited.add(start);component=[]
        while q:
            k=q.popleft();component.append(k);x,y=k%nx,k//nx
            for j in (k-1 if x else -1,k+1 if x+1<nx else -1,k-nx if y else -1,k+nx if y+1<ny else -1):
                if j>=0 and mask[j] and j not in visited:visited.add(j);q.append(j)
        xs=[k%nx for k in component];ys=[k//nx for k in component]
        def cuts(low,high,salt):
            count=math.ceil((high-low)/span)
            return {round(low+(high-low)*(i+.18*(_hash(s.seed,start,salt+i)-.5))/count) for i in range(1,count)}
        cut_x=cuts(min(xs),max(xs),0);cut_y=cuts(min(ys),max(ys),100)
        if cut_x or cut_y:
            for k in component:
                if k%nx in cut_x or k//nx in cut_y:mask[k]=False
    for x in range(nx):mask[x]=mask[(ny-1)*nx+x]=False
    for y in range(ny):mask[y*nx]=mask[y*nx+nx-1]=False
    connect_material(mask,nx,ny)
    values=distance_field(mask,nx,ny)
    # This allowance protects actual fitted curves, including concave smoothing,
    # against diagonal raster paths, interpolation, and arc-fit displacement.
    level=s.gap/(2*h)+1.75
    # Disk opening rounds the ends of bridge-split slots and removes needle
    # tips. It is a subset of the safe hole mask, so it adds material and never
    # spends the protected web. Final arc fitting has its own allowance below.
    rounding=2.0
    inner_distance=distance_field([v<=level+rounding for v in values],nx,ny)
    values=[min(v-level,rounding-d) for v,d in zip(values,inner_distance)]
    segments=region.indexed_segments(nx*ny//64)
    candidates=[];edge_count=0
    for loop in _contours(values,nx,ny,0.000001):
        if len(loop)<8 or abs(_area(loop))<3:continue
        smooth=_smooth(loop)
        if _area(smooth)<0:smooth=tuple(reversed(smooth))
        polygon=tuple(g.rotate((x0+x*h,y0+y*h),angle) for x,y in smooth)
        center=((min(p[0] for p in polygon)+max(p[0] for p in polygon))/2,
                (min(p[1] for p in polygon)+max(p[1] for p in polygon))/2)
        cell=g.Cell(center,s.shape,s.size,s.size,angle,polygon=polygon,curve_tolerance=h*.22)
        vertices=cell.vertices
        if not _simple(vertices):continue
        candidates.append(cell);edge_count+=len(cell.contour)
        if edge_count>MAX_EDGES*2:raise ValueError('Organic contours exceed the edge budget. Increase Pattern Scale or reduce the region.')
    result=[];edge_count=0
    for cell in _separated(candidates,s.gap,s.size):
        if not (g.overlaps(cell,region,segments) if s.clip_boundary else g.fits(cell,region,segments,s.margin)):continue
        result.append(cell);edge_count+=len(cell.contour)
        if len(result)>s.limit:raise ValueError('The hole count exceeds Maximum Holes. Increase Pattern Scale or Maximum Holes.')
        if edge_count>MAX_EDGES:raise ValueError('Organic contours exceed the edge budget. Increase Pattern Scale or reduce the region.')
    if not result:raise ValueError('No organic holes fit. Increase Pattern Scale or Field Fill, or reduce Web Thickness / Edge Offset.')
    return result


def blue_noise(region,s):
    """Variable-radius Bridson packing with a signed directional size gradient.

    Radius-aware bucket checks use the sum of *both* local radii plus the web;
    smaller points are never admitted by a fixed-radius Poisson check.
    """
    angle=s.grid_angle+s.organic_direction
    points=g.candidate_points(region,angle)
    x0,x1=min(p[0] for p in points),max(p[0] for p in points)
    y0,y1=min(p[1] for p in points),max(p[1] for p in points)
    maximum=s.size/2;minimum=maximum*(1-s.organic_variation/100)
    pad=maximum;x0-=pad;x1+=pad;y0-=pad;y1+=pad
    if (x1-x0)*(y1-y0)/(2*minimum+s.gap)**2>18000:
        raise ValueError('Blue Noise exceeds the candidate budget. Increase Pattern Scale or reduce Size Variation.')
    rng=random.Random(s.seed);bucket=max(maximum+s.gap,1e-6);index={};active=[];sites=[]
    origin=g.rotate(g.placement_center(region,replace(s,grid_angle=angle)),-angle)
    width=max(x1-x0,1e-9)
    def radius(x,y):
        t=max(0,min(1,(x-origin[0])/width+.5));gradient=s.organic_gradient/100
        mix=(1-abs(gradient))*rng.random()+abs(gradient)*(t if gradient>=0 else 1-t)
        return minimum+(maximum-minimum)*mix
    def accept(x,y,r):
        key=math.floor(x/bucket),math.floor(y/bucket)
        for dx in range(-2,3):
            for dy in range(-2,3):
                for xx,yy,rr in index.get((key[0]+dx,key[1]+dy),()):
                    if math.hypot(x-xx,y-yy)<r+rr+s.gap+1e-8:return False
        index.setdefault(key,[]).append((x,y,r));active.append((x,y,r));sites.append((x,y,r));return True
    cx=(x0+x1)/2+math.remainder(origin[0]-(x0+x1)/2,2*maximum+s.gap)
    cy=(y0+y1)/2+math.remainder(origin[1]-(y0+y1)/2,2*maximum+s.gap)
    accept(cx,cy,radius(cx,cy))
    attempts=0
    while active:
        i=rng.randrange(len(active));x,y,r=active[i]
        for _ in range(30):
            attempts+=1
            if attempts>540000:raise ValueError('Blue Noise exceeds the candidate budget. Increase Pattern Scale.')
            a=rng.random()*math.tau;d=(r+maximum+s.gap)*(1+rng.random())
            xx,yy=x+d*math.cos(a),y+d*math.sin(a)
            if x0<=xx<=x1 and y0<=yy<=y1 and accept(xx,yy,radius(xx,yy)):break
        else:active[i]=active[-1];active.pop()
    segments=region.indexed_segments(len(sites));result=[]
    for x,y,r in sites:
        cell=g.Cell(g.rotate((x,y),angle),'circle',2*r,2*r,0)
        if g.overlaps(cell,region,segments) if s.clip_boundary else g.fits(cell,region,segments,s.margin):
            result.append(cell)
            if len(result)>s.limit:raise ValueError('The hole count exceeds Maximum Holes. Increase Pattern Scale or Maximum Holes.')
    if not result:raise ValueError('No Blue Noise holes fit. Reduce Pattern Scale or Edge Offset.')
    return result
