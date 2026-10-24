# SPDX-License-Identifier: GPL-3.0-only
"""Arc-length placement and conservative web checks, without adsk imports.

The evaluator protocol is the CurveEvaluator3D protocol. Its length solver,
not strokes or uniform spline parameters, determines every hole center.
"""
import math

from .geometry import Cell, EPS, dist, enclosing_radius, fits, overlaps

PATH_TOLERANCE = 0.00001  # cm; maximum deviation of planarity strokes (0.0001 mm).
PLANE_TOLERANCE = 0.0001  # cm; reject rather than project an off-plane path.
MAX_SAMPLES = 100000


def path_distances(length, closed, settings):
    """Fixed arc spacing, measured from the chosen end/seam, without seam duplication.

    Position is an additional distance from Start Offset, not a wrapped phase.
    Closed curves reserve an exclusive end, even when End Offset is zero.
    """
    if not math.isfinite(length) or length <= PLANE_TOLERANCE:
        raise ValueError('Path has zero or negligible length. Select another curve.')
    first, last = settings.path_start + settings.path_position, length - settings.path_end
    # Never let a large relative epsilon erase a real short segment or last hole.
    tolerance = max(EPS, min(PATH_TOLERANCE, length * 1e-10))
    if not math.isfinite(first) or first > last + tolerance or first < 0 or last < 0:
        raise ValueError('Start Offset, Position, and End Offset leave no usable path.')
    steps = (last - first + tolerance) / settings.path_spacing
    if not math.isfinite(steps) or steps >= MAX_SAMPLES:
        raise ValueError('The path pattern is too dense. Increase Path Spacing.')
    count = math.floor(steps) + 1
    result = []
    for i in range(max(0, count)):
        value = first + i * settings.path_spacing
        if closed and value >= last - tolerance:
            break
        result.append(min(value, last))
    if not result:
        raise ValueError('Start Offset, Position, and End Offset leave no usable path.')
    return tuple(result)


def _point(evaluator, parameter, project):
    ok, point = evaluator.getPointAtParameter(parameter)
    if not ok:
        raise ValueError('Unable to evaluate Path. Select another curve.')
    value = tuple(project(point))
    if len(value) != 3 or not all(math.isfinite(v) for v in value):
        raise ValueError('Path must have finite coordinates.')
    if abs(value[2]) > PLANE_TOLERANCE:
        raise ValueError('Path must lie in the Profiles plane. Off-plane paths are not projected.')
    return value


def sample_path(evaluator, settings, project_point, project_vector, closed=False):
    """Read bounded geometry in its own coordinates; projections return plane XYZ.

    Validate the entire path with bounded-deviation strokes, even outside the
    retained interval. Singular tangents are explicitly rejected in Tangent mode.
    """
    settings.validate()
    ok, start, end = evaluator.getParameterExtents()
    if not ok or not all(math.isfinite(v) for v in (start, end)) or end <= start:
        raise ValueError('Path must be a bounded line, arc, circle, or spline.')
    ok, length = evaluator.getLengthAtParameter(start, end)
    if not ok or not math.isfinite(length) or length <= PLANE_TOLERANCE:
        raise ValueError('Path has zero or negligible length. Select another curve.')
    a, b = _point(evaluator, start, project_point), _point(evaluator, end, project_point)
    # Topological closure comes from the adapter. Physically joined endpoints
    # also form a seam (a nonperiodic spline can have merged end points).
    # Use EPS, not the much larger plane/stroking tolerance, for that decision.
    closed = closed or math.dist(a, b) <= EPS
    if closed and math.dist(a, b) > PLANE_TOLERANCE:
        raise ValueError('The closed Path seam is inconsistent. Select another curve.')
    distances = path_distances(length, closed, settings)
    ok, strokes = evaluator.getStrokes(start, end, PATH_TOLERANCE)
    if not ok or len(strokes) < 2 or len(strokes) > MAX_SAMPLES:
        raise ValueError('Unable to validate Path planarity within the sampling limit.')
    for point in strokes:
        xyz = tuple(project_point(point))
        if (len(xyz) != 3 or not all(math.isfinite(v) for v in xyz)
                or abs(xyz[2]) > PLANE_TOLERANCE - PATH_TOLERANCE):
            raise ValueError('Path must lie in the Profiles plane. Off-plane paths are not projected.')
    samples = []
    for distance in distances:
        measured = length - distance if settings.path_reverse else distance
        if measured <= EPS:
            parameter = start
        elif measured >= length - EPS:
            parameter = end
        else:
            ok, parameter = evaluator.getParameterAtLength(start, measured)
            if not ok or not math.isfinite(parameter) or not start <= parameter <= end:
                raise ValueError('Unable to measure Path by arc length. Select another curve.')
        x, y, _ = _point(evaluator, parameter, project_point)
        angle = 0.0
        if settings.path_orientation == 'tangent':
            ok, derivative = evaluator.getFirstDerivative(parameter)
            if not ok:
                raise ValueError('Path tangent is undefined. Use Fixed or select a smooth curve.')
            dx, dy, dz = project_vector(derivative)
            magnitude = math.sqrt(dx*dx + dy*dy + dz*dz)
            if (not all(math.isfinite(v) for v in (dx, dy, dz)) or magnitude <= 1e-12
                    or abs(dz) > magnitude * 1e-6):
                raise ValueError('Path tangent is singular or off-plane. Use Fixed or select a smooth planar curve.')
            angle = math.atan2(dy, dx) + (math.pi if settings.path_reverse else 0)
        samples.append((x, y, angle))
    return tuple(samples)


def generate_path(region, settings):
    """Keep arc positions; reject unsafe webs instead of silently skipping holes.

    Enclosing disks are exact for circles and conservative for other shapes.
    A spatial hash checks all nearby pairs, including nonadjacent path sections
    and the closing seam. Trimming can only enlarge this guaranteed web.
    """
    s = settings
    if not s.path_samples:
        raise ValueError('Select one Path in the Profiles plane.')
    if len(s.path_samples) > MAX_SAMPLES:
        raise ValueError('The path pattern is too dense. Increase Path Spacing.')
    minimum = 2 * enclosing_radius(s) + s.gap
    if not math.isfinite(minimum):
        raise ValueError('The hole dimensions are too large for Along Path.')
    segments = region.indexed_segments(len(s.path_samples))
    result, buckets = [], {}
    for sample in s.path_samples:
        if len(sample) != 3 or not all(math.isfinite(v) for v in sample):
            raise ValueError('Path must have finite positions and tangents.')
        x, y, tangent = sample
        cell = Cell((x, y), s.shape, s.size, s.slot_length,
                    s.shape_angle + (tangent if s.path_orientation == 'tangent' else 0),
                    s.arm_width, s.star_ratio, s.star_points)
        if not (overlaps(cell, region, segments) if s.clip_boundary
                else fits(cell, region, segments, s.margin)):
            continue
        bx, by = math.floor(x / minimum), math.floor(y / minimum)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in buckets.get((bx+dx, by+dy), ()):
                    if dist(cell.center, other.center) < minimum - EPS:
                        raise ValueError('Path holes violate Web Thickness near a turn, nearby section, or closing seam. '
                                         'Increase Path Spacing, adjust path offsets or Position, reduce the hole size, or edit Path. '
                                         'Noncircular holes use conservative enclosing bounds.')
        buckets.setdefault((bx, by), []).append(cell)
        result.append(cell)
        if len(result) > s.limit:
            raise ValueError('The hole count exceeds Maximum Holes. Increase Path Spacing or Maximum Holes.')
    if not result:
        raise ValueError('No path holes fit. Check Path, the hole size, Edge Offset, and path offsets.')
    return result
