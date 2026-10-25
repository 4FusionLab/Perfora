# SPDX-License-Identifier: GPL-3.0-only
"""Dependency-free 2D layout. Lengths use Fusion internal units (centimeters)."""
from dataclasses import dataclass
from functools import cached_property
import math

EPS = 1e-9
ORGANIC_FIELDS = ('smooth_noise', 'reaction_diffusion', 'directional_fibers', 'topographic', 'gyroid')
ORGANIC_SHAPES = ORGANIC_FIELDS + ('blue_noise',)
POLYGON_SHAPES = ('hexagon', 'square', 'triangle', 'rectangle', 'diamond', 'pentagon', 'octagon', 'cross', 'star') + ORGANIC_FIELDS + ('voronoi',)
LENGTH_SHAPES = ('slot', 'rectangle', 'diamond', 'ellipse')
SHAPE_IDS = ('circle', 'slot', 'ellipse', 'blue_noise') + POLYGON_SHAPES
VARIANT_LAYOUTS = ('contour', 'fan', 'phyllotaxis', 'poisson', 'wave', 'chevron', 'running_bond', 'between_curves')


def rotate(p, angle):
    c, s = math.cos(angle), math.sin(angle)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def edges(points):
    return zip(points, points[1:] + points[:1])


def point_segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2)) if length2 else 0.0
    return dist(p, (a[0] + t * dx, a[1] + t * dy))


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segment_distance(a, b, c, d):
    if cross(a, b, c) * cross(a, b, d) < 0 and cross(c, d, a) * cross(c, d, b) < 0:
        return 0.0
    return min(point_segment_distance(a, c, d), point_segment_distance(b, c, d),
               point_segment_distance(c, a, b), point_segment_distance(d, a, b))


def point_in_polygon(p, polygon):
    inside = False
    for a, b in edges(polygon):
        if (min(a[0], b[0])-EPS <= p[0] <= max(a[0], b[0])+EPS
                and min(a[1], b[1])-EPS <= p[1] <= max(a[1], b[1])+EPS
                and point_segment_distance(p, a, b) <= EPS):
            return True
        if (a[1] > p[1]) != (b[1] > p[1]):
            if p[0] < a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
                inside = not inside
    return inside


def stitch(paths, tolerance):
    """Join unordered, possibly reversed curve strokes; never bridge a gap."""
    pending = [list(p) for p in paths if len(p) >= 2]
    if not pending:
        raise ValueError('Unable to read the boundary.')
    result = pending.pop(0)
    while pending:
        options = [(dist(result[-1], path[end]), i, end) for i, path in enumerate(pending) for end in (0, -1)]
        gap, i, end = min(options)
        if gap > tolerance:
            raise ValueError('The boundary is open or exceeds the geometry tolerance.')
        path = pending.pop(i)
        if end == -1:
            path.reverse()
        result.extend(path[1:])
    if dist(result[-1], result[0]) > tolerance:
        raise ValueError('Select a closed planar region.')
    result.pop()
    # Evaluators sometimes return repeated end points.
    clean = []
    for p in result:
        if not clean or dist(clean[-1], p) > EPS:
            clean.append(p)
    if len(clean) < 3:
        raise ValueError('The boundary does not contain enough points.')
    return tuple(clean)


@dataclass(frozen=True)
class Loop:
    points: tuple
    outer: bool = True


class BoundaryIndex:
    """Conservative edge bounds; exact predicates still decide every contact."""
    def __init__(self, segments):
        self.segments = segments
        self.bounds = tuple((a, b, min(a[0], b[0]), max(a[0], b[0]),
                             min(a[1], b[1]), max(a[1], b[1])) for a, b in segments)

    def __iter__(self):
        return iter(self.segments)

    def nearby(self, points, padding):
        low_x, high_x = min(p[0] for p in points)-padding, max(p[0] for p in points)+padding
        low_y, high_y = min(p[1] for p in points)-padding, max(p[1] for p in points)+padding
        return tuple((a, b) for a, b, x0, x1, y0, y1 in self.bounds
                     if x1 >= low_x and x0 <= high_x and y1 >= low_y and y0 <= high_y)


@dataclass(frozen=True)
class Region:
    loops: tuple
    tolerance: float = 0.0001  # 0.001 mm boundary approximation/search tolerance.
    scope_center: tuple = None
    scope_radius: float = 0.0

    def contains(self, p):
        return ((self.scope_center is None or dist(p, self.scope_center) <= self.scope_radius)
                and any(point_in_polygon(p, l.points) for l in self.loops if l.outer)
                and not any(point_in_polygon(p, l.points) for l in self.loops if not l.outer))

    @cached_property
    def segments(self):
        return tuple(edge for loop in self.loops for edge in edges(loop.points))

    @cached_property
    def _boundary_index(self):
        return BoundaryIndex(self.segments)

    def indexed_segments(self, candidates):
        # Avoid preparing bounds for tiny simple patterns. Preparation is owned
        # by this Region, so replacing it cannot retain historical contours.
        if candidates >= 64 or len(self.segments) >= 16 and candidates >= 4:
            return self._boundary_index
        return self.segments


@dataclass(frozen=True)
class Settings:
    shape: str = 'circle'
    size: float = 0.5
    slot_length: float = 1.0
    gap: float = 0.15
    margin: float = 0.3
    staggered: bool = True
    grid_angle: float = 0.0
    shape_angle: float = 0.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    limit: int = 1500
    clip_boundary: bool = False
    arm_width: float = 0.15
    star_ratio: float = 0.45
    star_points: int = 5
    irregularity: float = 0.8
    seed: int = 1
    corner_radius: float = 0.0
    layout: str = 'grid'
    start_radius: float = 0.0
    radial_orientation: bool = False
    tangential_orientation: bool = False
    spread_radius: float = 0.0
    origin_x: float = None
    origin_y: float = None
    along_spacing: float = 0.0  # 0 selects enclosing diameter + Web Thickness.
    row_spacing: float = 0.0
    fan_angle: float = math.pi
    fan_rays: int = 12
    fan_angular_step: float = 0.0  # 0 uses Ray Count; otherwise radians.
    phyllotaxis_density: float = 1.0
    wave_amplitude: float = 0.3
    wave_length: float = 3.0
    wave_phase: float = 0.0
    wave_row_phase: float = 0.0
    chevron_angle: float = math.pi / 4
    bond_shift: float = 1 / 3
    contour_tolerance: float = 0.02
    guide_rows: int = 5
    guide_reverse: bool = False
    guide1: tuple = ()  # Prepared 2D strokes only; live references stay in config.
    guide2: tuple = ()
    # Legacy files/defaults retain revision 1; new native commands select 2.
    distribution_revision: int = 1
    layout_orientation: str = 'fixed'
    path_spacing: float = 0.8
    path_start: float = 0.0
    path_end: float = 0.0
    path_position: float = 0.0
    path_reverse: bool = False
    path_orientation: str = 'fixed'
    # Transient, immutable (x, y, tangent angle) samples; never serialized.
    path_samples: tuple = ()
    organic_open: float = 48.0  # Requested pre-web threshold percentile, not CAD area.
    organic_direction: float = 0.0
    organic_variation: float = 80.0
    organic_gradient: float = 100.0
    organic_bridges: bool = False

    def validate(self):
        if self.distribution_revision not in (1, 2):
            raise ValueError('Unsupported Distribution revision.')
        if self.layout_orientation not in ('fixed', 'tangent'):
            raise ValueError('Layout Orientation must be Fixed or Tangent.')
        if not math.isfinite(self.spread_radius) or self.spread_radius < 0:
            raise ValueError('Spread Radius must be finite and nonnegative. Use 0 to fill the boundary.')
        if self.spread_radius > 0 and self.spread_radius <= self.margin:
            raise ValueError('Spread Radius must be larger than Edge Offset.')
        if ((self.origin_x is None) != (self.origin_y is None)
                or self.origin_x is not None and not all(math.isfinite(v) for v in (self.origin_x, self.origin_y))):
            raise ValueError('Start Point must have finite coordinates.')
        if self.shape not in SHAPE_IDS:
            raise ValueError('Unknown hole shape.')
        if self.layout not in ('grid', 'circular', 'path') + VARIANT_LAYOUTS:
            raise ValueError('Unknown distribution.')
        if self.shape in ORGANIC_SHAPES:
            from .organic import validate
            validate(self)
        if self.layout in VARIANT_LAYOUTS:
            from .distributions import validate
            validate(self)
        if self.layout == 'path':
            if self.shape == 'voronoi':
                raise ValueError('Along Path is not available for Voronoi.')
            if (not all(math.isfinite(v) and v >= 0 for v in
                        (self.path_start, self.path_end, self.path_position))
                    or not math.isfinite(self.path_spacing) or self.path_spacing <= 0):
                raise ValueError('Path Spacing must be positive; path offsets and Position must be finite and nonnegative.')
            if self.path_orientation not in ('fixed', 'tangent'):
                raise ValueError('Path Orientation must be Fixed or Tangent.')
            if (self.grid_angle or self.offset_x or self.offset_y or self.spread_radius
                    or self.origin_x is not None or self.origin_y is not None
                    or self.radial_orientation or self.tangential_orientation or self.start_radius):
                raise ValueError('Along Path does not support Pattern Angle, X/Y Offset, Start Point, Spread Radius, or circular placement.')
        if self.layout == 'circular':
            if self.shape == 'voronoi':
                raise ValueError('Circular distribution is not available for Voronoi.')
            if not math.isfinite(self.start_radius) or self.start_radius < 0:
                raise ValueError('Start Radius must be finite and nonnegative.')
        values = (self.size, self.slot_length, self.gap, self.margin, self.grid_angle,
                  self.shape_angle, self.offset_x, self.offset_y)
        if not all(math.isfinite(v) for v in values):
            raise ValueError('Enter finite parameter values.')
        if self.size <= 0 or self.gap < 0.00001 or self.margin < 0:
            raise ValueError('Size must be positive, Web Thickness at least 0.0001 mm, and Edge Offset nonnegative.')
        if self.shape == 'slot' and self.slot_length < self.size:
            raise ValueError('Slot Length must be at least its Width.')
        if self.shape in LENGTH_SHAPES and (not math.isfinite(self.slot_length) or self.slot_length <= 0):
            raise ValueError('The second dimension must be positive.')
        if self.shape == 'ellipse' and self.slot_length <= self.size:
            raise ValueError('Major Axis must be greater than Minor Axis. Use Circle for equal axes.')
        if self.shape == 'cross' and not (0 < self.arm_width < self.size):
            raise ValueError('Arm Width must be positive and less than Overall Size.')
        if self.shape == 'star':
            if not isinstance(self.star_points, int) or not 3 <= self.star_points <= 12:
                raise ValueError('A star must have 3 to 12 points.')
            if not (0.05 <= self.star_ratio < math.cos(math.pi / self.star_points)):
                raise ValueError('Inner Radius must be at least 5%% and less than %.1f%% of the outer radius.' %
                                 (100 * math.cos(math.pi / self.star_points)))
        if self.shape == 'voronoi':
            if not math.isfinite(self.corner_radius) or self.corner_radius < 0:
                raise ValueError('Corner Radius must be finite and nonnegative.')
            if not math.isfinite(self.irregularity) or not 0 <= self.irregularity <= 1:
                raise ValueError('Irregularity must be between 0% and 100%.')
            if not isinstance(self.seed, int) or not 0 <= self.seed <= 2147483647:
                raise ValueError('Seed must be an integer between 0 and 2147483647.')
        if not 1 <= self.limit <= 5000:
            raise ValueError('Maximum Holes must be between 1 and 5000.')


@dataclass(frozen=True)
class Cell:
    center: tuple
    shape: str
    size: float
    length: float
    angle: float
    arm_width: float = 0.15
    star_ratio: float = 0.45
    star_points: int = 5
    polygon: tuple = ()  # Explicit world-plane vertices for non-repeating cells.
    corner_radius: float = 0.0
    curve_tolerance: float = 0.0

    @cached_property
    def contour(self):
        if self.shape in ORGANIC_FIELDS:
            from .organic import smooth_contour
            return smooth_contour(self.polygon, self.curve_tolerance)
        return rounded_polygon(self.vertices, self.corner_radius)

    @cached_property
    def vertices(self):
        if self.shape in ORGANIC_FIELDS:
            return tuple(p for edge in self.contour for p in edge.samples(self.curve_tolerance/2)[:-1])
        if self.shape == 'voronoi':
            return self.polygon
        if self.shape == 'hexagon':
            radius = self.size / math.sqrt(3)
            local = [(radius * math.cos(math.pi / 6 + i * math.pi / 3),
                      radius * math.sin(math.pi / 6 + i * math.pi / 3)) for i in range(6)]
        elif self.shape == 'square':
            h = self.size / 2
            local = [(-h, -h), (h, -h), (h, h), (-h, h)]
        elif self.shape == 'triangle':
            h = self.size * math.sqrt(3) / 2
            local = [(-self.size / 2, -h / 2), (self.size / 2, -h / 2), (0, h / 2)]
        elif self.shape == 'rectangle':
            x, y = self.length / 2, self.size / 2
            local = [(-x, -y), (x, -y), (x, y), (-x, y)]
        elif self.shape == 'diamond':
            x, y = self.length / 2, self.size / 2
            local = [(0, -y), (x, 0), (0, y), (-x, 0)]
        elif self.shape in ('pentagon', 'octagon'):
            n = 5 if self.shape == 'pentagon' else 8
            radius = self.size / 2 if n == 5 else self.size / (2 * math.cos(math.pi / 8))
            start = math.pi / 2 if n == 5 else math.pi / 8
            local = [(radius * math.cos(start + i * math.tau / n),
                      radius * math.sin(start + i * math.tau / n)) for i in range(n)]
        elif self.shape == 'cross':
            h, t = self.size / 2, self.arm_width / 2
            local = [(-t,-h),(t,-h),(t,-t),(h,-t),(h,t),(t,t),
                     (t,h),(-t,h),(-t,t),(-h,t),(-h,-t),(-t,-t)]
        elif self.shape == 'star':
            local = []
            for i in range(self.star_points * 2):
                radius = self.size / 2 * (self.star_ratio if i % 2 else 1)
                angle = math.pi / 2 + i * math.pi / self.star_points
                local.append((radius * math.cos(angle), radius * math.sin(angle)))
        else:
            return ()
        return tuple(self.at(p) for p in local)

    def ellipse_points(self, count=128, enclosing=False):
        # A circumscribed polygon conservatively tests clearance. The final CAD
        # is an analytic ellipse, independent of the display/test tessellation.
        scale = 1 / math.cos(math.pi / count) if enclosing else 1
        return tuple(self.at((scale * self.length / 2 * math.cos(i * math.tau / count),
                              scale * self.size / 2 * math.sin(i * math.tau / count))) for i in range(count))

    def at(self, p):
        x, y = rotate(p, self.angle)
        return self.center[0] + x, self.center[1] + y

    @property
    def spine(self):
        half = (self.length - self.size) / 2 if self.shape == 'slot' else 0.0
        return self.at((-half, 0)), self.at((half, 0))


@dataclass(frozen=True)
class ContourEdge:
    """Exact line or CCW circular arc shared by CAD, clipping and display."""
    start: tuple
    end: tuple
    center: tuple = None
    sweep: float = 0.0

    def at(self, fraction):
        if self.center is None:
            return tuple(a+(b-a)*fraction for a,b in zip(self.start,self.end))
        x, y = rotate((self.start[0]-self.center[0], self.start[1]-self.center[1]), self.sweep*fraction)
        return self.center[0]+x, self.center[1]+y

    @property
    def length(self):
        return dist(self.start,self.end) if self.center is None else dist(self.start,self.center)*abs(self.sweep)

    def tangent(self, end=False):
        if self.center is None:
            x,y=self.end[0]-self.start[0],self.end[1]-self.start[1]
        else:
            p=self.end if end else self.start
            sign=1 if self.sweep>0 else -1
            x,y=-(p[1]-self.center[1])*sign,(p[0]-self.center[0])*sign
        length=math.hypot(x,y)
        return x/length,y/length

    def fraction(self, point):
        if dist(point,self.start)<EPS:
            return 0.
        if dist(point,self.end)<EPS:
            return 1.
        if self.center is None:
            dx,dy=self.end[0]-self.start[0],self.end[1]-self.start[1]
            return ((point[0]-self.start[0])*dx+(point[1]-self.start[1])*dy)/(dx*dx+dy*dy)
        start=math.atan2(self.start[1]-self.center[1],self.start[0]-self.center[0])
        angle=math.atan2(point[1]-self.center[1],point[0]-self.center[0])
        return ((angle-start)*(1 if self.sweep>0 else -1) % math.tau)/abs(self.sweep)

    def samples(self, tolerance=0.0001):
        if self.center is None:
            return (self.start, self.end)
        radius = dist(self.start, self.center)
        step = 2*math.acos(max(-1, min(1, 1-tolerance/radius)))
        count = min(256, max(2, math.ceil(abs(self.sweep)/max(step, 1e-6))))
        return (self.start,) + tuple(self.at(i/count) for i in range(1, count)) + (self.end,)


@dataclass(frozen=True)
class BezierEdge:
    """Cubic with shared endpoint tangents; exact NURBS in the CAD adapter."""
    start: tuple
    control1: tuple
    control2: tuple
    end: tuple
    center = None
    sweep = 0.

    def at(self,t):
        u=1-t
        return tuple(u*u*u*a+3*u*u*t*b+3*u*t*t*c+t*t*t*d
                     for a,b,c,d in zip(self.start,self.control1,self.control2,self.end))

    def samples(self,tolerance=0.0001):
        result=[self.start]
        def split(a,b,c,d,depth):
            length=dist(a,d)
            flat=max(point_segment_distance(p,a,d) for p in (b,c))
            if depth>=12 or flat<=tolerance and length>EPS:
                result.append(d);return
            ab,bc,cd=tuple((x+y)/2 for x,y in zip(a,b)),tuple((x+y)/2 for x,y in zip(b,c)),tuple((x+y)/2 for x,y in zip(c,d))
            abc,bcd=tuple((x+y)/2 for x,y in zip(ab,bc)),tuple((x+y)/2 for x,y in zip(bc,cd))
            mid=tuple((x+y)/2 for x,y in zip(abc,bcd))
            split(a,ab,abc,mid,depth+1);split(mid,bcd,cd,d,depth+1)
        split(self.start,self.control1,self.control2,self.end,0)
        return tuple(result)

    @property
    def length(self):
        points=self.samples()
        return sum(dist(a,b) for a,b in zip(points,points[1:]))

    def tangent(self,end=False):
        a,b=(self.control2,self.end) if end else (self.start,self.control1)
        length=dist(a,b)
        return (b[0]-a[0])/length,(b[1]-a[1])/length


def rounded_polygon(points, requested_radius):
    """Convex opening by a disk: inset, then expand with exact round joins.

    Short bevels disappear when their fillets would overlap, instead of forcing
    microscopic radii. The disk expansion stays inside the original polygon.
    Reduce the radius only if the entire hole is too narrow to contain it.
    """
    if requested_radius <= EPS:
        return tuple(ContourEdge(a, b) for a, b in edges(points))
    origin=tuple(sum(p[i] for p in points)/len(points) for i in (0,1))
    local=tuple((p[0]-origin[0],p[1]-origin[1]) for p in points)
    planes=[]
    for a,b in edges(local):
        length=dist(a,b)
        nx,ny=(b[1]-a[1])/length,(a[0]-b[0])/length
        planes.append((nx,ny,nx*a[0]+ny*a[1]))

    def inset(radius):
        polygon=local
        for nx,ny,bound in planes:
            polygon=_clip_halfplane(polygon,nx,ny,bound-radius)
            if len(polygon)<3:
                return ()
        area=sum(a[0]*b[1]-b[0]*a[1] for a,b in edges(polygon))
        return polygon if area>EPS*EPS*4 else ()

    radius=requested_radius
    inner=inset(radius)
    if not inner:
        low=0.
        high=min(radius,min(max(p[i] for p in local)-min(p[i] for p in local) for i in (0,1))/2)
        for _ in range(40):
            middle=(low+high)/2
            if inset(middle):
                low=middle
            else:
                high=middle
        radius=low*.98
        inner=inset(radius)
    if not inner or radius<=EPS:
        return tuple(ContourEdge(a,b) for a,b in edges(points))
    # Discard collinear inset vertices before forming their outward round joins.
    inner=tuple(p for i,p in enumerate(inner)
                if abs(cross(inner[i-1],p,inner[(i+1)%len(inner)]))>
                1e-10*dist(inner[i-1],p)*dist(p,inner[(i+1)%len(inner)]))
    fillets=[]
    for i,p in enumerate(inner):
        before,after=inner[i-1],inner[(i+1)%len(inner)]
        incoming,outgoing=dist(before,p),dist(p,after)
        u=((p[1]-before[1])/incoming,(before[0]-p[0])/incoming)
        v=((after[1]-p[1])/outgoing,(p[0]-after[0])/outgoing)
        center=(p[0]+origin[0],p[1]+origin[1])
        start=(center[0]+radius*u[0],center[1]+radius*u[1])
        end=(center[0]+radius*v[0],center[1]+radius*v[1])
        sweep=math.atan2(u[0]*v[1]-u[1]*v[0],u[0]*v[0]+u[1]*v[1])
        fillets.append(ContourEdge(start,end,center,sweep))
    result=[]
    for i,arc in enumerate(fillets):
        result.append(arc)
        end=fillets[(i+1)%len(fillets)].start
        if dist(arc.end,end)>EPS:
            result.append(ContourEdge(arc.end,end))
    return tuple(result)


def _offset_curve(edge, radius):
    if edge.center is None:
        dx,dy=edge.tangent()
        return None,(edge.start[0]-dy*radius,edge.start[1]+dx*radius),(dx,dy)
    return dist(edge.start,edge.center)-(radius if edge.sweep>0 else -radius),edge.center,None


def _curve_intersections(a,b):
    """Intersections of infinite lines/circles used for exact planar fillets."""
    ra,pa,da=a
    rb,pb,db=b
    if ra is None and rb is None:
        divisor=da[0]*db[1]-da[1]*db[0]
        if abs(divisor)<EPS:
            return ()
        dx,dy=pb[0]-pa[0],pb[1]-pa[1]
        t=(dx*db[1]-dy*db[0])/divisor
        return ((pa[0]+t*da[0],pa[1]+t*da[1]),)
    if ra is not None and rb is None:
        return _curve_intersections(b,a)
    if ra is None:
        if rb<=EPS:
            return ()
        dx,dy=pb[0]-pa[0],pb[1]-pa[1]
        along=dx*da[0]+dy*da[1]
        perpendicular=dx*da[1]-dy*da[0]
        square=rb*rb-perpendicular*perpendicular
        if square<0:
            return ()
        delta=math.sqrt(square)
        return tuple((pa[0]+t*da[0],pa[1]+t*da[1]) for t in (along-delta,along+delta))
    distance=dist(pa,pb)
    if min(ra,rb,distance)<=EPS or distance>ra+rb or distance<abs(ra-rb):
        return ()
    along=(ra*ra-rb*rb+distance*distance)/(2*distance)
    height=math.sqrt(max(0,ra*ra-along*along))
    dx,dy=(pb[0]-pa[0])/distance,(pb[1]-pa[1])/distance
    return tuple((pa[0]+along*dx-sign*height*dy,pa[1]+along*dy+sign*height*dx) for sign in (-1,1))


def _fillet_contact(edge,center):
    if edge.center is None:
        return edge.at(edge.fraction(center))
    scale=dist(edge.start,edge.center)/dist(center,edge.center)
    return tuple(a+(b-a)*scale for a,b in zip(edge.center,center))


def round_contour(contour, requested_radius):
    """Round convex line/arc junctions after trimming; preserve existing arcs.

    Limits belong to each individual corner. Tangent junctions and concave
    source-boundary corners are preserved; no part of the hole is enlarged.
    """
    if requested_radius<=EPS or len(contour)<2:
        return tuple(contour)
    fillets=[]
    for i,b in enumerate(contour):
        a=contour[i-1]
        u,v=a.tangent(True),b.tangent()
        turn=math.atan2(u[0]*v[1]-u[1]*v[0],u[0]*v[0]+u[1]*v[1])
        if turn<=1e-7:
            fillets.append(None)
            continue
        radius=min(requested_radius,.45*min(a.length,b.length)/max(math.tan(turn/2),EPS))
        chosen=None
        for _ in range(32):
            for center in sorted(_curve_intersections(_offset_curve(a,radius),_offset_curve(b,radius)),
                                 key=lambda p: dist(p,b.start)):
                start,end=_fillet_contact(a,center),_fillet_contact(b,center)
                fa,fb=a.fraction(start),b.fraction(end)
                sweep=(math.atan2(end[1]-center[1],end[0]-center[0])-
                       math.atan2(start[1]-center[1],start[0]-center[0])) % math.tau
                if .51<=fa<=1+EPS and -EPS<=fb<=.49 and EPS<sweep<math.pi+1e-7:
                    chosen=ContourEdge(start,end,center,sweep)
                    break
            if chosen is not None:
                break
            radius/=2
            if radius<EPS:
                break
        if chosen is None:
            raise ValueError('A boundary corner is too small to round. Increase Cell Spacing or reduce Corner Radius.')
        fillets.append(chosen)
    result=[]
    for i,edge in enumerate(contour):
        before,after=fillets[i],fillets[(i+1)%len(contour)]
        start,end=before.end if before else edge.start,after.start if after else edge.end
        if before:
            result.append(before)
        sweep=edge.sweep*(edge.fraction(end)-edge.fraction(start)) if edge.center is not None else 0
        result.append(ContourEdge(start,end,edge.center,sweep))
    return tuple(result)


def fits(cell, region, segments, margin):
    # Edge Offset is an inclusive minimum, matching the exact inset used by
    # Trim to Boundary. A hidden stroking allowance used to remove whole holes
    # even when the exact Boolean intersection left their contours unchanged.
    clearance = margin + (cell.curve_tolerance/2 if cell.shape in ORGANIC_FIELDS else 0)
    if not region.contains(cell.center):
        return False
    rounded = cell.shape in ('circle', 'slot')
    points = (cell.spine if rounded else
              cell.ellipse_points(enclosing=True) if cell.shape == 'ellipse' else cell.vertices)
    if region.scope_center is not None:
        reach = max(dist(p, region.scope_center) for p in points) + (cell.size/2 if rounded else 0)
        if reach + clearance > region.scope_radius + EPS:
            return False
    if isinstance(segments, BoundaryIndex):
        padding = margin + region.tolerance + 2*EPS + (cell.size/2 if rounded else 0)
        segments = segments.nearby(points, padding)
    if rounded:
        a, b = points
        return all(segment_distance(a, b, c, d) + EPS >= cell.size / 2 + clearance for c, d in segments)
    if not all(region.contains(p) for p in points):
        return False
    if any(segment_distance(a, b, c, d) + EPS < clearance
           or (cross(a,b,c)*cross(a,b,d)<0 and cross(c,d,a)*cross(c,d,b)<0)
           for a, b in edges(points) for c, d in segments):
        return False
    # A cell may entirely enclose a small pre-existing void without crossing it.
    return not any(point_in_polygon(loop.points[0], points) for loop in region.loops if not loop.outer)


def pitch(settings):
    """Conservative non-overlap; exact close packing for unrotated hexagons."""
    s = settings
    if s.shape == 'voronoi':
        return s.size, s.size
    if s.shape == 'circle':
        x = s.size + s.gap
        return x, x * (math.sqrt(3) / 2 if s.staggered else 1)
    if s.shape == 'hexagon':
        if abs(math.remainder(s.shape_angle, math.pi / 3)) < 1e-10:
            x = s.size + s.gap
            return x, (x * math.sqrt(3) / 2 if s.staggered else 2 * s.size / math.sqrt(3) + s.gap)
        x = 2 * s.size / math.sqrt(3) + s.gap
        return x, x * (math.sqrt(3) / 2 if s.staggered else 1)
    if s.shape == 'square':
        width = s.size * (abs(math.cos(s.shape_angle)) + abs(math.sin(s.shape_angle)))
        return width + s.gap, width + s.gap
    if s.shape in POLYGON_SHAPES:
        points = Cell((0, 0), s.shape, s.size, s.slot_length, s.shape_angle,
                      s.arm_width, s.star_ratio, s.star_points).vertices
        return (max(p[0] for p in points) - min(p[0] for p in points) + s.gap,
                max(p[1] for p in points) - min(p[1] for p in points) + s.gap)
    if s.shape == 'ellipse':
        c, t = math.cos(s.shape_angle), math.sin(s.shape_angle)
        return (math.hypot(s.slot_length * c, s.size * t) + s.gap,
                math.hypot(s.slot_length * t, s.size * c) + s.gap)
    length = s.slot_length - s.size
    return (abs(math.cos(s.shape_angle)) * length + s.size + s.gap,
            abs(math.sin(s.shape_angle)) * length + s.size + s.gap)


def overlaps(cell, region, segments):
    """Conservative positive-area candidates; exact trimming is done by Fusion."""
    if region.scope_center is not None:
        # Conservative disk rejection before exact BRep intersection. A hole
        # may overlap each constraint separately without overlapping both.
        if cell.shape in ('circle', 'slot'):
            if point_segment_distance(region.scope_center, *cell.spine) >= region.scope_radius + cell.size/2:
                return False
        else:
            points = cell.ellipse_points(enclosing=True) if cell.shape == 'ellipse' else cell.vertices
            if (not point_in_polygon(region.scope_center, points)
                    and min(point_segment_distance(region.scope_center, a, b) for a, b in edges(points)) >= region.scope_radius):
                return False
        return overlaps(cell, Region(region.loops, region.tolerance), segments)
    if region.contains(cell.center):
        return True
    if cell.shape in ('circle', 'slot'):
        a, b = cell.spine
        return any(segment_distance(a, b, c, d) < cell.size / 2 + region.tolerance
                   for c, d in segments)
    points = cell.ellipse_points(enclosing=True) if cell.shape == 'ellipse' else cell.vertices
    return (any(region.contains(p) for p in points)
            or any(point_in_polygon(p, points) for loop in region.loops for p in loop.points)
            or any(segment_distance(a, b, c, d) <= region.tolerance
                   for a, b in edges(points) for c, d in segments))


def boundary_center(region):
    points = [p for loop in region.loops if loop.outer for p in loop.points]
    if not points:
        raise ValueError('The selected region has no outer boundary.')
    return ((min(p[0] for p in points) + max(p[0] for p in points))/2,
            (min(p[1] for p in points) + max(p[1] for p in points))/2)


def placement_center(region, settings):
    origin = (settings.origin_x, settings.origin_y) if settings.origin_x is not None else boundary_center(region)
    offset = ((settings.offset_x, settings.offset_y) if settings.layout == 'circular' else
              rotate((settings.offset_x, settings.offset_y), settings.grid_angle))
    return origin[0]+offset[0], origin[1]+offset[1]


def candidate_points(region, angle=0):
    points = [rotate(p, -angle) for loop in region.loops if loop.outer for p in loop.points]
    if not points or region.scope_center is None:
        return points
    x,y = rotate(region.scope_center, -angle)
    r = region.scope_radius
    low_x, high_x = max(min(p[0] for p in points), x-r), min(max(p[0] for p in points), x+r)
    low_y, high_y = max(min(p[1] for p in points), y-r), min(max(p[1] for p in points), y+r)
    if low_x >= high_x or low_y >= high_y:
        raise ValueError('Spread Radius does not overlap the selected boundary.')
    return [(low_x, low_y), (high_x, low_y), (high_x, high_y), (low_x, high_y)]


def generate(region, settings):
    settings.validate()
    if settings.layout == 'path':
        from .curve_layout import generate_path
        return generate_path(region, settings)
    if settings.spread_radius > 0:
        from dataclasses import replace
        if settings.origin_x is None:
            x,y = boundary_center(region)
            settings = replace(settings, origin_x=x, origin_y=y)
        region = Region(region.loops, region.tolerance, placement_center(region, settings), settings.spread_radius)
    if settings.shape == 'voronoi':
        return generate_voronoi(region, settings)
    if settings.shape in ORGANIC_SHAPES:
        from .organic import generate as generate_organic
        return generate_organic(region, settings)
    if settings.layout == 'circular':
        return generate_circular(region, settings)
    if settings.layout in VARIANT_LAYOUTS:
        if settings.distribution_revision == 2:
            from .distribution_fields import build_field
            return build_field(region, settings).cells
        from .distributions import generate_variant
        return generate_variant(region, settings)
    outer = candidate_points(region, settings.grid_angle)
    if not outer:
        raise ValueError('The selected region has no outer boundary.')
    min_x, max_x = min(p[0] for p in outer), max(p[0] for p in outer)
    min_y, max_y = min(p[1] for p in outer), max(p[1] for p in outer)
    sx, sy = pitch(settings)
    # Offsets are periodic. Reducing them also avoids enormous row indices.
    origin = (rotate((settings.origin_x, settings.origin_y), -settings.grid_angle)
              if settings.origin_x is not None else ((min_x + max_x)/2, (min_y + max_y)/2))
    ox = origin[0] + math.remainder(settings.offset_x, sx)
    oy = origin[1] + math.remainder(settings.offset_y, 2 * sy)
    if settings.clip_boundary:
        # A cell can overlap even with its centre outside the boundary.
        probe = Cell((0, 0), settings.shape, settings.size, settings.slot_length, 0,
                     settings.arm_width, settings.star_ratio, settings.star_points)
        radius = (max(settings.slot_length, settings.size) / 2 if settings.shape in ('slot', 'ellipse') else
                  max(math.hypot(*p) for p in probe.vertices) if probe.vertices else settings.size / 2)
        min_x, max_x = min_x - radius, max_x + radius
        min_y, max_y = min_y - radius, max_y + radius
    first_row, last_row = math.floor((min_y - oy) / sy), math.ceil((max_y - oy) / sy)
    columns = math.ceil((max_x - min_x) / sx) + 4
    if (last_row - first_row + 1) * columns > 100000:
        raise ValueError('The pattern is too dense. Increase the hole size or Web Thickness.')
    result = []
    segments = region.indexed_segments((last_row-first_row+1)*columns)
    for row in range(first_row, last_row + 1):
        shift = sx / 2 if settings.staggered and row % 2 else 0.0
        for col in range(math.floor((min_x - ox - shift) / sx), math.ceil((max_x - ox - shift) / sx) + 1):
            center = rotate((ox + col * sx + shift, oy + row * sy), settings.grid_angle)
            cell = Cell(center, settings.shape, settings.size, settings.slot_length,
                        settings.grid_angle + settings.shape_angle,
                        settings.arm_width, settings.star_ratio, settings.star_points)
            if (overlaps(cell, region, segments) if settings.clip_boundary
                    else fits(cell, region, segments, settings.margin)):
                result.append(cell)
                if len(result) > settings.limit:
                    raise ValueError('The hole count exceeds the limit of %d. Adjust the pattern or Maximum Holes.' % settings.limit)
    if not result:
        raise ValueError('No holes fit in the region. Reduce the hole size or Edge Offset.')
    return result


def enclosing_radius(settings):
    """Rotation-independent bound about Cell.center, including asymmetric shapes."""
    if settings.shape in ('circle', 'slot', 'ellipse'):
        return (settings.size if settings.shape == 'circle' else
                max(settings.size, settings.slot_length)) / 2
    probe = Cell((0, 0), settings.shape, settings.size, settings.slot_length, 0,
                 settings.arm_width, settings.star_ratio, settings.star_points)
    return max(math.hypot(*p) for p in probe.vertices)


def generate_circular(region, settings):
    """Concentric rings with chord spacing, bounded work and guaranteed web.

    Enclosing disks keep holes separated within and between rings, even when
    each hole follows its radial direction. The center is fixed in sketch axes;
    Pattern Angle rotates the pattern without moving that center.
    """
    s = settings
    outer = candidate_points(region)
    if not outer:
        raise ValueError('The selected region has no outer boundary.')
    low_x, high_x = min(p[0] for p in outer), max(p[0] for p in outer)
    low_y, high_y = min(p[1] for p in outer), max(p[1] for p in outer)
    ox, oy = placement_center(region, s)
    radius = enclosing_radius(s)
    step = 2 * radius + s.gap
    reach = max(math.hypot(x - ox, y - oy) for x, y in outer) + radius
    nearest = math.hypot(max(low_x - ox, 0, ox - high_x),
                         max(low_y - oy, 0, oy - high_y)) - radius
    first = max(0, math.ceil((nearest - s.start_radius) / step))
    last = math.floor((reach - s.start_radius) / step)
    # Bound full-ring candidates before allocating/iterating. A remote center
    # must not cause millions of angular samples even for a tiny source region.
    if last >= first and (last - first + 1) * (math.tau * reach / step + 1) > 100000:
        raise ValueError('The circular pattern is too dense. Increase the hole size or Web Thickness, or move its center closer.')
    result = []
    segments = region.indexed_segments(max(0, last-first+1)*(math.tau*reach/step+1))
    for ring in range(first, last + 1):
        r = s.start_radius + ring * step
        count = (1 if r < step / 2 else
                 max(2, math.floor(math.pi / math.asin(min(1.0, step / (2 * r))) + 1e-12)))
        if count > 1:
            # Retain the original chord-packed rings (6, 12, 18, ...), adding
            # opposite partners only when the capacity is odd. Forcing square
            # symmetry reduces the first ring to four sites and creates a cross.
            count -= count % 2
        for index in range(count):
            angle = s.grid_angle + index * math.tau / count
            center = (ox + r * math.cos(angle), oy + r * math.sin(angle))
            cell = Cell(center, s.shape, s.size, s.slot_length,
                        (angle if s.radial_orientation or s.tangential_orientation else s.grid_angle)
                        + (math.pi / 2 if s.tangential_orientation else 0) + s.shape_angle,
                        s.arm_width, s.star_ratio, s.star_points)
            if (overlaps(cell, region, segments) if s.clip_boundary
                    else fits(cell, region, segments, s.margin)):
                result.append(cell)
                if len(result) > s.limit:
                    raise ValueError('The hole count exceeds the limit of %d. Adjust the pattern or Maximum Holes.' % s.limit)
    if not result:
        raise ValueError('No holes fit in the region. Reduce Start Radius, the hole size, or Edge Offset.')
    return result


def _clip_halfplane(points, nx, ny, bound):
    """Clip a convex CCW polygon to dot(normal, point) <= bound."""
    result = []
    for a, b in edges(points):
        da, db = nx * a[0] + ny * a[1] - bound, nx * b[0] + ny * b[1] - bound
        if da <= 0:
            result.append(a)
        if (da < 0 < db) or (db < 0 < da):
            t = da / (da - db)
            result.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    clean = []
    for p in result:
        if not clean or dist(clean[-1], p) > EPS:
            clean.append(p)
    if len(clean) > 1 and dist(clean[0], clean[-1]) <= EPS:
        clean.pop()
    return tuple(clean)


def _site_random(seed, row, col, axis):
    # Stable indexed mixing: changing index ranges never re-seeds lattice sites.
    value = (seed ^ (row * 0x9e3779b1) ^ (col * 0x85ebca77) ^ (axis * 0xc2b2ae3d)) & 0xffffffff
    value = ((value ^ (value >> 16)) * 0x7feb352d) & 0xffffffff
    value = ((value ^ (value >> 15)) * 0x846ca68b) & 0xffffffff
    return ((value ^ (value >> 16)) / 4294967296.0 - 0.5) * 2


def _clip_voronoi(points, nx, ny, bound):
    # Voronoi polygons are already cleaned by the preceding clip. The shared
    # clipping primitive used for fillets keeps its original cleanup semantics.
    if all(nx*p[0]+ny*p[1]-bound <= 0 for p in points):
        return points
    return _clip_halfplane(points, nx, ny, bound)


def generate_voronoi(region, settings):
    """Jittered-lattice Voronoi with a metric inset of half the minimum web.

    Sites move at most .45 pitch on each axis. Every point is within
    sqrt(2)*.95 pitch of a site; a cell therefore cannot reach further.
    Competitors beyond twice this radius cannot affect it. The +/-4 lattice
    neighbourhood includes every possible competitor (5 - .9 > 2*sqrt(2)*.95).
    This bounds work per cell independently of total pattern density.
    """
    s = settings
    outer = candidate_points(region, s.grid_angle)
    if not outer:
        raise ValueError('The selected region has no outer boundary.')
    low_x, high_x = min(p[0] for p in outer), max(p[0] for p in outer)
    low_y, high_y = min(p[1] for p in outer), max(p[1] for p in outer)
    # Keep the same centred, periodic placement convention as regular patterns.
    origin = (rotate((s.origin_x, s.origin_y), -s.grid_angle) if s.origin_x is not None
              else ((low_x + high_x)/2, (low_y + high_y)/2))
    ox = origin[0] + math.remainder(s.offset_x, s.size)
    oy = origin[1] + math.remainder(s.offset_y, s.size)
    first_col, last_col = math.floor((low_x - ox) / s.size) - 2, math.ceil((high_x - ox) / s.size) + 2
    first_row, last_row = math.floor((low_y - oy) / s.size) - 2, math.ceil((high_y - oy) / s.size) + 2
    if (last_col - first_col + 1) * (last_row - first_row + 1) > 25000:
        raise ValueError('The Voronoi pattern is too dense. Increase Cell Spacing.')
    sites = {}

    def site(row, col):
        key = (row, col)
        if key not in sites:
            sites[key] = (col + .45 * s.irregularity * _site_random(s.seed, row, col, 0),
                          row + .45 * s.irregularity * _site_random(s.seed, row, col, 1))
        return sites[key]

    result, segments = [], region.indexed_segments((last_row-first_row+1)*(last_col-first_col+1))
    for row in range(first_row, last_row + 1):
        for col in range(first_col, last_col + 1):
            x, y = site(row, col)
            # Normalised local coordinates keep predicates independent of spacing.
            polygon = ((-2., -2.), (2., -2.), (2., 2.), (-2., 2.))
            neighbours = []
            for dr in range(-4, 5):
                for dc in range(-4, 5):
                    if dr or dc:
                        qx, qy = site(row + dr, col + dc)
                        dx, dy = qx - x, qy - y
                        distance = math.hypot(dx, dy)
                        neighbours.append((distance, dx, dy))
            # Nearby constraints shrink the working polygon first.
            for distance, dx, dy in sorted(neighbours):
                polygon = _clip_voronoi(polygon, dx / distance, dy / distance,
                                          distance / 2 - s.gap / (2 * s.size))
                if len(polygon) < 3:
                    break
            if len(polygon) < 3:
                continue  # A large web can consume an entire cell.
            if abs(sum(a[0]*b[1] - b[0]*a[1] for a, b in edges(polygon))) * s.size**2 < region.tolerance**2:
                continue
            vertices = tuple(rotate((ox + (x + px) * s.size, oy + (y + py) * s.size), s.grid_angle)
                             for px, py in polygon)
            center = tuple(sum(p[i] for p in vertices) / len(vertices) for i in (0, 1))
            cell = Cell(center, 'voronoi', s.size, s.size, s.grid_angle, polygon=vertices,
                        corner_radius=s.corner_radius)
            if (overlaps(cell, region, segments) if s.clip_boundary else fits(cell, region, segments, s.margin)):
                result.append(cell)
                if len(result) > s.limit:
                    raise ValueError('The hole count exceeds the limit of %d. Increase Cell Spacing or Maximum Holes.' % s.limit)
    if not result:
        raise ValueError('No Voronoi holes fit. Reduce Cell Spacing, Web Thickness, or Edge Offset.')
    return result


def rectangle_region(width, height):
    if width <= 0 or height <= 0:
        raise ValueError('Boundary Width and Height must be positive.')
    x, y = width / 2, height / 2
    return Region((Loop(((-x, -y), (x, -y), (x, y), (-x, y))),))


def disk_region(diameter, tolerance=0.0001):
    if diameter <= 0:
        raise ValueError('Boundary Diameter must be positive.')
    radius = diameter / 2
    count = max(16, math.ceil(math.pi / math.acos(max(-1, 1 - min(tolerance, radius) / radius))))
    if count > 20000:
        raise ValueError('The circular boundary is too large.')
    return Region((Loop(tuple((radius * math.cos(i * 2 * math.pi / count),
                               radius * math.sin(i * 2 * math.pi / count)) for i in range(count))),), tolerance)


def outline_coordinates(cells, region, panel=False):
    """Batched line-list coordinates for display only; final CAD stays analytic."""
    coordinates = []

    def add_loop(points):
        for a, b in edges(tuple(points)):
            coordinates.extend((a[0], a[1], 0.0, b[0], b[1], 0.0))

    if panel:
        for loop in region.loops:
            add_loop(loop.points)
    for cell in cells:
        if cell.shape in ORGANIC_FIELDS or cell.shape == 'voronoi' and cell.corner_radius > 0:
            for edge in cell.contour:
                points = edge.samples(max(region.tolerance,cell.curve_tolerance/2)) if cell.shape in ORGANIC_FIELDS else edge.samples()
                for a, b in zip(points, points[1:]):
                    coordinates.extend((a[0], a[1], 0.0, b[0], b[1], 0.0))
        elif cell.shape in POLYGON_SHAPES:
            add_loop(cell.vertices)
        elif cell.shape == 'ellipse':
            add_loop(cell.ellipse_points(96))
        elif cell.shape == 'circle':
            add_loop([cell.at((cell.size / 2 * math.cos(i * math.tau / 48),
                               cell.size / 2 * math.sin(i * math.tau / 48))) for i in range(48)])
        else:
            h, r = (cell.length - cell.size) / 2, cell.size / 2
            add_loop([cell.at((h + r * math.cos(-math.pi / 2 + i * math.pi / 24),
                               r * math.sin(-math.pi / 2 + i * math.pi / 24))) for i in range(25)] +
                     [cell.at((-h + r * math.cos(math.pi / 2 + i * math.pi / 24),
                               r * math.sin(math.pi / 2 + i * math.pi / 24))) for i in range(25)])
    return coordinates
