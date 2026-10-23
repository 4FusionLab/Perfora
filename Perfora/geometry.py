# SPDX-License-Identifier: GPL-3.0-only
"""Dependency-free 2D layout. Lengths use Fusion internal units (centimeters)."""
from dataclasses import dataclass
import math

EPS = 1e-9
POLYGON_SHAPES = ('hexagon', 'square', 'triangle', 'rectangle', 'diamond', 'pentagon', 'octagon', 'cross', 'star')
LENGTH_SHAPES = ('slot', 'rectangle', 'diamond', 'ellipse')
SHAPE_IDS = ('circle', 'slot', 'ellipse') + POLYGON_SHAPES


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
        if point_segment_distance(p, a, b) <= EPS:
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


@dataclass(frozen=True)
class Region:
    loops: tuple
    tolerance: float = 0.0001  # 0.001 mm; applied as an extra boundary clearance.

    def contains(self, p):
        return (any(point_in_polygon(p, l.points) for l in self.loops if l.outer)
                and not any(point_in_polygon(p, l.points) for l in self.loops if not l.outer))

    @property
    def segments(self):
        return tuple(edge for loop in self.loops for edge in edges(loop.points))


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

    def validate(self):
        if self.shape not in SHAPE_IDS:
            raise ValueError('Unknown hole shape.')
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

    @property
    def vertices(self):
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


def fits(cell, region, segments, margin):
    clearance = margin + region.tolerance + EPS
    if not region.contains(cell.center):
        return False
    if cell.shape in ('circle', 'slot'):
        a, b = cell.spine
        return all(segment_distance(a, b, c, d) >= cell.size / 2 + clearance for c, d in segments)
    points = cell.ellipse_points(enclosing=True) if cell.shape == 'ellipse' else cell.vertices
    if not all(region.contains(p) for p in points):
        return False
    if any(segment_distance(a, b, c, d) < clearance for a, b in edges(points) for c, d in segments):
        return False
    # A cell may entirely enclose a small pre-existing void without crossing it.
    return not any(point_in_polygon(loop.points[0], points) for loop in region.loops if not loop.outer)


def pitch(settings):
    """Conservative non-overlap; exact close packing for unrotated hexagons."""
    s = settings
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


def generate(region, settings):
    settings.validate()
    outer = [rotate(p, -settings.grid_angle) for loop in region.loops if loop.outer for p in loop.points]
    if not outer:
        raise ValueError('The selected region has no outer boundary.')
    min_x, max_x = min(p[0] for p in outer), max(p[0] for p in outer)
    min_y, max_y = min(p[1] for p in outer), max(p[1] for p in outer)
    sx, sy = pitch(settings)
    # Offsets are periodic. Reducing them also avoids enormous row indices.
    ox = (min_x + max_x) / 2 + math.remainder(settings.offset_x, sx)
    oy = (min_y + max_y) / 2 + math.remainder(settings.offset_y, 2 * sy)
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
    segments = region.segments
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
        if cell.shape in POLYGON_SHAPES:
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
