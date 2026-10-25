# SPDX-License-Identifier: GPL-3.0-only
"""Bounded, deterministic scalar fields and variable-radius blue noise.

No CAD objects or third-party modules. Field topology is resolved on a finite
grid before adaptive cubic compression. A spanning forest connects material
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
    'organic_variation': ('Size Variation (%)', '', '80'),
    'organic_gradient': ('Size Gradient (%)', '', '100'),
}
MAX_NODES = 120000
MAX_EDGES = 16000
MAX_ITERATIONS = 1000


def validate(s):
    if not isinstance(s.organic_bridges,bool):
        raise ValueError('Add Bridges must be on or off.')
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
        return noise(x*.78,y*.78,seed)+.18*noise(x*1.56,y*1.56,seed+1)
    if kind == 'directional_fibers':
        # Direction is the long axis (chart X); transverse noise controls width.
        return noise(x*.13, y*1.6+.26*math.sin(x*.7+phase),seed)
    if kind == 'topographic':
        # Contours of a ridged low-frequency height field, including nested hills.
        height = 12*abs(noise(x*.10,y*.10,seed)) + .12*noise(x*.25,y*.25,seed+1)
        return math.cos(math.tau*(height+.12*x+phase/math.tau))
    # A genuine oblique (111) section of the triply periodic gyroid field.
    # This section retains the three-armed flowing motif instead of reducing
    # the field to nearly parallel sinusoidal slots of an axis-aligned slice.
    a,b=x*math.tau/1.8+phase,y*math.tau/1.8+phase*.73
    offset=.05*math.sin(phase)
    xx=a/math.sqrt(2)+b/math.sqrt(6)+offset
    yy=-a/math.sqrt(2)+b/math.sqrt(6)+offset
    zz=-2*b/math.sqrt(6)+offset
    return math.sin(xx)*math.cos(yy)+math.sin(yy)*math.cos(zz)+math.sin(zz)*math.cos(xx)


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


def _blur(values,nx,ny,passes=3):
    """Separable binomial smoothing of the bounded signed distance field."""
    for _ in range(passes):
        horizontal=values[:]
        for y in range(ny):
            for x in range(2,nx-2):
                k=y*nx+x
                horizontal[k]=(values[k-2]+4*values[k-1]+6*values[k]+4*values[k+1]+values[k+2])/16
        result=horizontal[:]
        for y in range(2,ny-2):
            for x in range(nx):
                k=y*nx+x
                result[k]=(horizontal[k-2*nx]+4*horizontal[k-nx]+6*horizontal[k]+4*horizontal[k+nx]+horizontal[k+2*nx])/16
        values=result
    return values


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


def smooth_contour(points,tolerance):
    """Adaptive cubic fitting with the same tangent on both sides of a join.

    Endpoint tangent directions come from the closed smoothed contour. A
    two-variable least-squares fit chooses handle lengths. One curve can cover
    many samples; the curve count follows curvature, not raster resolution.
    """
    n=len(points)
    tangents=[]
    for i,p in enumerate(points):
        a,b=points[i-1],points[(i+1)%n];length=g.dist(a,b)
        tangents.append(((b[0]-a[0])/length,(b[1]-a[1])/length))
    points=tuple(points)+(points[0],);tangents.append(tangents[0])
    result=[];i=0
    while i<n:
        best=None;last=i+1
        for j in range(i+1,min(n,i+96)+1):
            a,d=points[i],points[j];ta,td=tangents[i],tangents[j]
            lengths=[0.]
            for k in range(i+1,j+1):lengths.append(lengths[-1]+g.dist(points[k-1],points[k]))
            total=lengths[-1]
            if total<1e-10:continue
            c00=c01=c11=x0=x1=0.
            for k,along in enumerate(lengths[1:-1],i+1):
                t=along/total;u=1-t;b0=u*u*u;b1=3*u*u*t;b2=3*u*t*t;b3=t*t*t
                v1=(ta[0]*b1,ta[1]*b1);v2=(-td[0]*b2,-td[1]*b2)
                rhs=(points[k][0]-a[0]*(b0+b1)-d[0]*(b2+b3),points[k][1]-a[1]*(b0+b1)-d[1]*(b2+b3))
                c00+=v1[0]**2+v1[1]**2;c01+=v1[0]*v2[0]+v1[1]*v2[1];c11+=v2[0]**2+v2[1]**2
                x0+=v1[0]*rhs[0]+v1[1]*rhs[1];x1+=v2[0]*rhs[0]+v2[1]*rhs[1]
            determinant=c00*c11-c01*c01
            alpha=(x0*c11-x1*c01)/determinant if determinant>1e-14 else total/3
            beta=(x1*c00-x0*c01)/determinant if determinant>1e-14 else total/3
            if min(alpha,beta)<total*.01 or max(alpha,beta)>total:
                alpha=beta=total/3
            curve=g.BezierEdge(a,(a[0]+ta[0]*alpha,a[1]+ta[1]*alpha),
                               (d[0]-td[0]*beta,d[1]-td[1]*beta),d)
            error=max((g.dist(points[k],curve.at(along/total)) for k,along in enumerate(lengths,i)),default=0)
            if error>tolerance and best is not None:break
            best=curve;last=j
        if best is None:raise ValueError('Unable to smooth an organic contour. Increase Pattern Scale.')
        result.append(best);i=last
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


def _contact(a,b,c,d):
    if g.cross(a,b,c)*g.cross(a,b,d)<0 and g.cross(c,d,a)*g.cross(c,d,b)<0:
        ab,cd=g.dist(a,b),g.dist(c,d)
        return g._curve_intersections((None,a,((b[0]-a[0])/ab,(b[1]-a[1])/ab)),
                                      (None,c,((d[0]-c[0])/cd,(d[1]-c[1])/cd)))[0]
    def project(p,a,b):
        dx,dy=b[0]-a[0],b[1]-a[1]
        t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/max(dx*dx+dy*dy,1e-20)))
        return a[0]+t*dx,a[1]+t*dy
    p,q=min(((a,project(a,c,d)),(b,project(b,c,d)),(c,project(c,a,b)),(d,project(d,a,b))),key=lambda pair:g.dist(*pair))
    return (p[0]+q[0])/2,(p[1]+q[1])/2


def _separated(cells,gap,scale,repair=None):
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
        nearby={i for key in keys for i in buckets.get(key,())};safe=True;nested=False
        for i in sorted(nearby):
            other=accepted[i];q=other.vertices;bb=bounds(q,0)
            if box[0]>bb[1] or box[1]<bb[0] or box[2]>bb[3] or box[3]<bb[2]:continue
            distance=gap+2*(cell.curve_tolerance+other.curve_tolerance)
            if g.point_in_polygon(points[0],q) or g.point_in_polygon(q[0],points):safe=False;nested=True;break
            for a,b in g.edges(points):
                for c,d in g.edges(q):
                    if (max(a[0],b[0])+distance<min(c[0],d[0]) or max(c[0],d[0])+distance<min(a[0],b[0])
                            or max(a[1],b[1])+distance<min(c[1],d[1]) or max(c[1],d[1])+distance<min(a[1],b[1])):continue
                    if g.segment_distance(a,b,c,d)<distance:
                        if repair is not None:repair(_contact(a,b,c,d),distance)
                        safe=False;break
                if not safe:break
            if not safe:break
        if safe or repair is not None and not nested:
            index=len(accepted);accepted.append(cell)
            for key in keys:buckets.setdefault(key,[]).append(index)
    return accepted


def _add_bridges(mask,nx,ny,s):
    # A bridge crosses one narrow branch of an elongated opening. Never
    # slice every run in a row/column: that creates artificial panel-wide bars.
    visited=set();span=64
    for start in range(len(mask)):
        if not mask[start] or start in visited:continue
        queue=deque([start]);visited.add(start);component=[]
        while queue:
            k=queue.popleft();component.append(k);x,y=k%nx,k//nx
            for j in (k-1 if x else -1,k+1 if x+1<nx else -1,k-nx if y else -1,k+nx if y+1<ny else -1):
                if j>=0 and mask[j] and j not in visited:visited.add(j);queue.append(j)
        xs=[k%nx for k in component];ys=[k//nx for k in component]
        width,height=max(xs)-min(xs),max(ys)-min(ys)
        horizontal=width>height;major=max(width,height);minor=max(1,min(width,height))
        if major<=span:continue
        coordinates={}
        for k in component:
            axis,cross=(k%nx,k//nx) if horizontal else (k//nx,k%nx)
            coordinates.setdefault(axis,[]).append((cross,k))
        low=min(coordinates);count=max(1,major//span)
        for bridge in range(1,count+1):
            target=low+major*(bridge+.3*(_hash(s.seed,start,bridge)-.5))/(count+1)
            reach=max(3,major/(count+1)*.18);options=[]
            for axis in range(math.ceil(target-reach),math.floor(target+reach)+1):
                run=[];previous=None;runs=[]
                for cross,k in sorted(coordinates.get(axis,())):
                    if previous is not None and cross!=previous+1:
                        runs.append(tuple(run));run=[]
                    run.append(k);previous=cross
                if run:runs.append(tuple(run))
                if runs:
                    main=max(runs,key=len)
                    options.append((len(main)+.08*abs(axis-target),main))
            if options:
                for k in min(options)[1]:mask[k]=False


def field_grid(width, height, scale):
    """Bound raster work, retaining 8–16 samples per physical Pattern Scale.

    Previously accepted regions retain their exact grid. Larger regions use
    a coarser grid within a fixed resolution floor; the physical field scale
    is unchanged and curve/web allowances continue to use the actual step.
    """
    step = scale/16
    def dimensions(h):
        return math.ceil(width/h)+1, math.ceil(height/h)+1
    nx, ny = dimensions(step)
    if nx*ny > MAX_NODES:
        step *= math.sqrt(nx*ny/MAX_NODES)*1.01
        nx, ny = dimensions(step)
        while nx*ny > MAX_NODES:
            step *= 1.01
            nx, ny = dimensions(step)
        if step > scale/8:
            raise ValueError('Organic field exceeds the sampling budget. Increase Pattern Scale or select a smaller region.')
    return step, nx, ny


def generate(region,s):
    validate(s)
    if s.shape=='blue_noise':return blue_noise(region,s)
    angle=s.grid_angle+s.organic_direction
    outer=g.candidate_points(region,angle)
    x0,x1=min(p[0] for p in outer),max(p[0] for p in outer)
    y0,y1=min(p[1] for p in outer),max(p[1] for p in outer)
    # Normalized field units; one Pattern Scale contains 16 intervals. Halo
    # keeps candidates outside the exact source, enabling genuine partial trim.
    pad=2*s.size
    x0,y0=x0-pad,y0-pad
    h,nx,ny=field_grid(x1-x0+pad,y1-y0+pad,s.size)
    origin=g.rotate(g.placement_center(region,replace(s,grid_angle=angle)), -angle)
    if s.shape=='reaction_diffusion':
        # Solver wavelength is ~8 grid nodes; resample its physical scale onto
        # the same contour grid used by all other fields.
        rx=ry=128
        solver=reaction(rx,ry,s.seed)
        values=[]
        for y in range(ny):
            for x in range(nx):
                px,py=(x0+x*h-origin[0])/s.size,(y0+y*h-origin[1])/s.size
                xx=(px*12+10*noise(px*.17,py*.17,s.seed+41))%rx
                yy=(py*12+10*noise(px*.17,py*.17,s.seed+73))%ry
                i,j=int(xx),int(yy);u,v=xx-i,yy-j
                a,b=j*rx+i,j*rx+(i+1)%rx;c,d=((j+1)%ry)*rx+i,((j+1)%ry)*rx+(i+1)%rx
                values.append((solver[a]*(1-u)+solver[b]*u)*(1-v)+(solver[c]*(1-u)+solver[d]*u)*v)
    else:
        values=[_field(s.shape,(x0+x*h-origin[0])/s.size,(y0+y*h-origin[1])/s.size,s.seed)
                for y in range(ny) for x in range(nx)]
    threshold=sorted(values)[min(len(values)-1,int(len(values)*(1-s.organic_open/100)))]
    mask=[v>threshold for v in values]
    if s.organic_bridges:_add_bridges(mask,nx,ny,s)
    for x in range(nx):mask[x]=mask[(ny-1)*nx+x]=False
    for y in range(ny):mask[y*nx]=mask[y*nx+nx-1]=False
    connect_material(mask,nx,ny)
    values=distance_field(mask,nx,ny)
    # This allowance protects actual fitted curves, including concave smoothing,
    # against diagonal raster paths, interpolation, and arc-fit displacement.
    level=s.gap/(2*h)+.85
    # Bounded signed-distance smoothing rounds caps and removes needle tips.
    # Clamping both sides prevents a large opening from eating a narrow bridge.
    # Actual cubic curves receive a separate exact clearance selection below.
    values=_blur([max(-3.,min(3.,v-level)) for v in values],nx,ny)
    segments=region.indexed_segments(nx*ny//64)
    for attempt in range(4):
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
        repairs=[]
        candidates=_separated(candidates,s.gap,s.size,lambda point,distance:repairs.append((point,distance)))
        if not repairs or attempt==3:break
        # Widen only an insufficient neck. Retain both surrounding openings
        # instead of deleting an entire hole and leaving a blank band.
        for point,distance in repairs:
            x,y=g.rotate(point,-angle);cx,cy=(x-x0)/h,(y-y0)/h
            radius=distance/(2*h)+1.5
            for j in range(max(0,math.floor(cy-radius-1)),min(ny,math.ceil(cy+radius+1)+1)):
                for i in range(max(0,math.floor(cx-radius-1)),min(nx,math.ceil(cx+radius+1)+1)):
                    k=j*nx+i;values[k]=min(values[k],math.hypot(i-cx,j-cy)-radius)
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
            a=rng.random()*math.tau;d=(2*r+s.gap)*(1+rng.random())
            guess=radius(x+d*math.cos(a),y+d*math.sin(a))
            d=(r+guess+s.gap)*math.sqrt(1+3*rng.random())
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
