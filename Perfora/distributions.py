# SPDX-License-Identifier: GPL-3.0-only
"""Bounded deterministic layout generators. Pure 2D, centimeters/radians.

Enclosing disks and a spatial hash guarantee the web for every repeating shape,
even with rotation. They intentionally trade packing density for safety.
Contour uses piecewise-linear signed-distance isolines, not exact BRep offsets.
"""
import math
import random
from bisect import bisect_right
from .geometry import (EPS, Cell, dist, enclosing_radius, fits, overlaps, rotate,
                       placement_center, candidate_points, point_segment_distance)
from .curves import ArcPath, prepare_guides

MAX_CANDIDATES = 100000
VARIANT_PARAMETERS = {
    'along_spacing': ('Along Spacing', 'mm', '0 mm'),
    'row_spacing': ('Row Spacing', 'mm', '0 mm'),
    'fan_angle': ('Sector Angle', 'deg', '180 deg'),
    'fan_rays': ('Ray Count', '', '12'),
    'fan_angular_step': ('Angular Step', 'deg', '0 deg'),
    'phyllotaxis_density': ('Density Ratio', '', '1'),
    'wave_amplitude': ('Amplitude', 'mm', '3 mm'),
    'wave_length': ('Wavelength', 'mm', '30 mm'),
    'wave_phase': ('Phase', 'deg', '0 deg'),
    'wave_row_phase': ('Row Phase', 'deg', '0 deg'),
    'chevron_angle': ('Chevron Angle', 'deg', '45 deg'),
    'bond_shift': ('Row Shift Ratio', '', '1 / 3'),
    'contour_tolerance': ('Contour Tolerance', 'mm', '0.2 mm'),
    'guide_rows': ('Row Count', '', '5'),
}
# Empty/invalid hidden fields must never block another distribution.
LAYOUT_PARAMETERS = {
    'contour': ('along_spacing', 'row_spacing', 'contour_tolerance'),
    'fan': ('along_spacing', 'fan_angle', 'fan_rays', 'fan_angular_step'),
    'phyllotaxis': ('along_spacing', 'phyllotaxis_density'),
    'poisson': ('along_spacing', 'seed'),
    'wave': ('along_spacing', 'row_spacing', 'wave_amplitude', 'wave_length', 'wave_phase', 'wave_row_phase'),
    'chevron': ('along_spacing', 'row_spacing', 'chevron_angle'),
    'running_bond': ('along_spacing', 'row_spacing', 'bond_shift'),
    'between_curves': ('along_spacing', 'guide_rows'),
}


def validate(s):
    if s.shape == 'voronoi':
        raise ValueError('This Distribution requires a repeating hole shape. Voronoi has its own distribution.')
    for key in LAYOUT_PARAMETERS[s.layout]:
        if not math.isfinite(getattr(s, key)):
            raise ValueError(VARIANT_PARAMETERS.get(key, ('Seed',))[0] + ' must be finite.')
    if s.along_spacing < 0 or s.row_spacing < 0:
        raise ValueError('Spacing must be nonnegative. Use 0 for automatic spacing.')
    if s.layout == 'fan':
        if not 0 < s.fan_angle <= math.tau or not 0 <= s.fan_angular_step <= math.tau:
            raise ValueError('Sector Angle must be greater than 0 and at most 360 deg; Angular Step must be 0 to 360 deg.')
        if not isinstance(s.fan_rays, int) or not 1 <= s.fan_rays <= 720:
            raise ValueError('Ray Count must be an integer from 1 to 720.')
        if not math.isfinite(s.start_radius) or s.start_radius < 0:
            raise ValueError('Start Radius must be finite and nonnegative.')
    if s.layout == 'phyllotaxis' and not 0.05 <= s.phyllotaxis_density <= 4:
        raise ValueError('Density Ratio must be between 0.05 and 4.')
    if s.layout == 'poisson' and (not isinstance(s.seed, int) or not 0 <= s.seed <= 2147483647):
        raise ValueError('Seed must be an integer from 0 to 2147483647.')
    if s.layout == 'wave' and (s.wave_amplitude < 0 or s.wave_length <= 0):
        raise ValueError('Amplitude must be nonnegative and Wavelength positive.')
    if s.layout == 'chevron' and not 0 < s.chevron_angle < math.pi/2:
        raise ValueError('Chevron Angle must be greater than 0 and less than 90 deg.')
    if s.layout == 'running_bond' and not 0 <= s.bond_shift <= 1:
        raise ValueError('Row Shift Ratio must be between 0 and 1 (for example 1 / 3).')
    if s.layout == 'contour' and s.contour_tolerance <= 0:
        raise ValueError('Contour Tolerance must be positive.')
    if s.layout == 'between_curves' and (not isinstance(s.guide_rows, int) or not 2 <= s.guide_rows <= 200):
        raise ValueError('Row Count must be an integer from 2 to 200.')


class SeparationIndex:
    def __init__(self, spacing):
        self.spacing = spacing
        self.buckets = {}

    def accept(self, p):
        x, y = (math.floor(v/self.spacing) for v in p)
        for i in range(x-1, x+2):
            for j in range(y-1, y+2):
                if any(dist(p, q) < self.spacing-EPS for q in self.buckets.get((i, j), ())):
                    return False
        self.buckets.setdefault((x, y), []).append(p)
        return True


def _bounds(region, s, radius):
    points = candidate_points(region, s.grid_angle)
    # A fixed candidate envelope makes Trim on/off share the same point field.
    return (min(p[0] for p in points)-radius, max(p[0] for p in points)+radius,
            min(p[1] for p in points)-radius, max(p[1] for p in points)+radius)


def _budget(count):
    if not math.isfinite(count) or count > MAX_CANDIDATES:
        raise ValueError('The pattern is too dense or its center is too far away. Increase spacing or simplify the source.')


def _rows(low, high, origin, spacing):
    first, last = math.floor((low-origin)/spacing), math.ceil((high-origin)/spacing)
    _budget(last-first+1)
    return range(first, last+1)


def _wave_points(low, high, amplitude, length, phase, step):
    # Explicit derivative bound prevents under-sampling steep short waves.
    speed = math.hypot(1, amplitude*math.tau/length)
    count = max(1, math.ceil((high-low)*speed/(step/16)))
    _budget(count)
    return [(low+(high-low)*i/count,
             amplitude*math.sin(math.tau*(low+(high-low)*i/count)/length+phase)) for i in range(count+1)]


def _regular(region, s, along, rows, bound, origin):
    x0, x1, y0, y1 = bound
    ox, oy = origin
    if s.layout == 'running_bond':
        rr = _rows(y0, y1, oy, rows)
        _budget(len(rr)*(math.ceil((x1-x0)/along)+3))
        for row in rr:
            shift = (row*s.bond_shift % 1)*along
            for col in _rows(x0, x1, ox+shift, along):
                yield (ox+shift+col*along, oy+row*rows)
    elif s.layout == 'chevron':
        slope = math.tan(s.chevron_angle)
        reach = max(abs(x0-ox), abs(x1-ox))
        rr = _rows(y0-slope*reach, y1, oy, rows)
        columns = math.ceil(reach/(along*math.cos(s.chevron_angle)))
        _budget(len(rr)*(2*columns+1))
        for row in rr:
            yield (ox, oy+row*rows)  # Vertex once, both arms omit it.
            for col in range(1, columns+1):
                dx = col*along*math.cos(s.chevron_angle)
                for side in (-1, 1):
                    yield (ox+side*dx, oy+row*rows+slope*dx)
    elif s.layout == 'wave':
        rr = _rows(y0-s.wave_amplitude, y1+s.wave_amplitude, oy, rows)
        # Keep arc-length samples anchored to the pattern origin, including when
        # the domain is translated. Start the bounded stroke at the left extent.
        _budget(len(rr)*((x1-x0)*math.hypot(1, s.wave_amplitude*math.tau/s.wave_length)/along+3))
        for row in rr:
            path = ArcPath(_wave_points(x0-ox, x1-ox, s.wave_amplitude, s.wave_length,
                                        s.wave_phase+row*s.wave_row_phase, along))
            for x, y in path.spaced(along):
                yield (x+ox, y+oy+row*rows)


def _fan(s, bound, origin, along):
    ox, oy = origin
    reach = max(dist((x,y), origin) for x in bound[:2] for y in bound[2:])
    full = abs(s.fan_angle-math.tau) < EPS
    count = (math.ceil(s.fan_angle/s.fan_angular_step)+(0 if full else 1)
             if s.fan_angular_step else s.fan_rays)
    _budget(count*(reach/along+2))
    for ray in range(count):
        angle = (min(s.fan_angle, ray*s.fan_angular_step) if s.fan_angular_step else
                 (ray*s.fan_angle/(count if full else max(1, count-1))))
        for index in range(max(0, math.floor((reach-s.start_radius)/along))+1):
            r = s.start_radius+index*along
            yield (ox+r*math.cos(angle), oy+r*math.sin(angle))


def _phyllotaxis(s, bound, origin, along):
    reach = max(dist((x,y), origin) for x in bound[:2] for y in bound[2:])
    # Half-index Vogel spiral avoids a crowded center. At density 1 the
    # nominal neighbour distance is above the safe pitch; higher densities
    # remain protected by the shared geometric guard.
    scale = along/(1.5*math.sqrt(s.phyllotaxis_density))
    count = math.ceil((reach/scale)**2)+1
    _budget(count)
    golden = math.pi*(3-math.sqrt(5))
    for i in range(count):
        r = scale*math.sqrt(i+.5)
        yield (origin[0]+r*math.cos(i*golden), origin[1]+r*math.sin(i*golden))


def _poisson(s, bound, origin, along):
    # A finite field anchored at Start Point; offsets translate it, and the
    # envelope still covers the source. A remote anchor is rejected by budget.
    rx = max(abs(bound[0]-origin[0]), abs(bound[1]-origin[0]))
    ry = max(abs(bound[2]-origin[1]), abs(bound[3]-origin[1]))
    x0, x1, y0, y1 = -rx, rx, -ry, ry
    _budget((x1-x0)*(y1-y0)/along**2*8)
    rng = random.Random(s.seed)
    index = SeparationIndex(along)
    point = (rng.uniform(x0,x1), rng.uniform(y0,y1))
    index.accept(point)
    active = [point]
    yield (point[0]+origin[0], point[1]+origin[1])
    attempts = 0
    while active:
        i = rng.randrange(len(active))
        p = active[i]
        for _ in range(30):
            attempts += 1
            if attempts > MAX_CANDIDATES*30:
                raise ValueError('Poisson Disk exceeds the candidate budget. Increase spacing.')
            angle, r = rng.random()*math.tau, along*math.sqrt(1+3*rng.random())
            q = (p[0]+r*math.cos(angle), p[1]+r*math.sin(angle))
            if x0 <= q[0] <= x1 and y0 <= q[1] <= y1 and index.accept(q):
                active.append(q)
                yield (q[0]+origin[0], q[1]+origin[1])
                break
        else:
            active[i] = active[-1]
            active.pop()


def _between(s, along):
    a, b, fractions = prepare_guides(s.guide1, s.guide2, reverse=s.guide_reverse)
    _budget(s.guide_rows*(max(a.length,b.length)/along+len(fractions)))
    for row in range(s.guide_rows):
        v = row/(s.guide_rows-1)
        points = []
        for t in fractions:
            p, q = a.at(t), b.at(t)
            points.append(((1-v)*p[0]+v*q[0], (1-v)*p[1]+v*q[1]))
        yield from ArcPath(points).spaced(along)


class _DistanceTree:
    """Nearest segment BVH for the contour field (no node-by-edge scan)."""
    def __init__(self, segments):
        points = [p for a,b in segments for p in (a,b)]
        self.bound = (min(p[0] for p in points), max(p[0] for p in points),
                      min(p[1] for p in points), max(p[1] for p in points))
        self.children = None
        self.segments = segments
        if len(segments) > 8:
            axis = 0 if self.bound[1]-self.bound[0] > self.bound[3]-self.bound[2] else 1
            ordered = sorted(segments, key=lambda ab: ab[0][axis]+ab[1][axis])
            middle = len(ordered)//2
            self.children = (_DistanceTree(ordered[:middle]), _DistanceTree(ordered[middle:]))
            self.segments = ()

    def lower(self, p):
        x0,x1,y0,y1 = self.bound
        return math.hypot(max(x0-p[0],0,p[0]-x1), max(y0-p[1],0,p[1]-y1))

    def nearest(self, p, best=math.inf):
        if self.lower(p) >= best:
            return best
        if self.children:
            a,b = sorted(self.children, key=lambda child: child.lower(p))
            return b.nearest(p, a.nearest(p,best))
        return min(best, min(point_segment_distance(p,a,b) for a,b in self.segments))


def _contour(region, s, radius, along, row_step):
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
    _budget(levels)
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
                yield from ArcPath(loop, closed=True).spaced(along, closed=True)


def generate_variant(region, s):
    try:
        return _generate_variant(region, s)
    except OverflowError:
        raise ValueError('The Distribution exceeds the supported coordinate or sampling range. Reduce offsets, density or source size.') from None


def _generate_variant(region, s):
    radius = enclosing_radius(s)
    safe = 2*radius+s.gap+2*EPS
    along = max(safe, s.along_spacing)
    rows = max(safe, s.row_spacing)
    if s.layout == 'wave' and s.along_spacing == 0 and s.wave_amplitude > 0:
        curvature = s.wave_amplitude*(math.tau/s.wave_length)**2
        ratio = safe*curvature/2
        if 0 < ratio < 1:
            # Arc pitch must exceed chord clearance on curved rows. The small
            # reserve covers polyline sampling; tight waves still use the guard.
            along = 2*math.asin(ratio)/curvature*1.002
    if s.row_spacing == 0:
        if s.layout == 'wave':
            speed = math.hypot(1, s.wave_amplitude*math.tau/s.wave_length)
            rows = safe*speed + 2*s.wave_amplitude*abs(math.sin(s.wave_row_phase/2))
        elif s.layout == 'chevron':
            rows = safe/math.cos(s.chevron_angle)
        elif s.layout == 'contour':
            # Allow for opposing level-set interpolation errors. Explicit
            # pitches remain available; the shared guard handles any contacts.
            rows = safe+2*min(s.contour_tolerance,safe/6)
    bound = _bounds(region, s, radius)
    origin = rotate(placement_center(region, s), -s.grid_angle)
    if s.layout not in ('contour', 'between_curves'):
        _budget(max(abs(bound[0]-origin[0]), abs(bound[1]-origin[0]),
                    abs(bound[2]-origin[1]), abs(bound[3]-origin[1])) / safe)
    if s.layout == 'contour':
        candidates = _contour(region, s, radius, along, rows)
    elif s.layout == 'fan':
        candidates = _fan(s, bound, origin, along)
    elif s.layout == 'phyllotaxis':
        candidates = _phyllotaxis(s, bound, origin, along)
    elif s.layout == 'poisson':
        candidates = _poisson(s, bound, origin, along)
    elif s.layout == 'between_curves':
        candidates = _between(s, along)
    else:
        candidates = _regular(region, s, along, rows, bound, origin)
    index = SeparationIndex(safe)
    segments = region.indexed_segments(1000)
    result = []
    for count, p in enumerate(candidates):
        _budget(count+1)
        # Contour and guide strokes already use the source plane coordinates.
        if s.layout not in ('contour', 'between_curves'):
            p = rotate(p, s.grid_angle)
        if not index.accept(p):
            continue
        cell = Cell(p, s.shape, s.size, s.slot_length, s.grid_angle+s.shape_angle,
                    s.arm_width, s.star_ratio, s.star_points)
        if overlaps(cell, region, segments) if s.clip_boundary else fits(cell, region, segments, s.margin):
            result.append(cell)
            if len(result) > s.limit:
                raise ValueError('The hole count exceeds the limit of %d. Adjust the pattern or Maximum Holes.' % s.limit)
    if not result:
        raise ValueError('No holes fit in the region. Reduce the hole size, spacing or Edge Offset.')
    return result
