# SPDX-License-Identifier: GPL-3.0-only
"""Periodic cylindrical placement for straight radial tools; no Fusion imports.

Tool dimensions live in a tangent plane, X around the cylinder and Y along its
axis. Enclosing disks and separating planes protect webs throughout the cut
depth, not just at the outer surface. Closed patterns never repeat an endpoint.
"""
from dataclasses import dataclass
import math

from .geometry import Cell, POLYGON_SHAPES, ORGANIC_FIELDS, _clip_voronoi, _site_random


@dataclass(frozen=True)
class CylinderRegion:
    radius: float
    height: float
    sweep: float = math.tau
    inward: bool = True


@dataclass(frozen=True)
class RadialHole:
    angle: float
    axial: float
    cell: Cell = None


def tool_cell(settings, hole=None):
    if hole is not None and hole.cell is not None:
        return hole.cell
    return Cell((0, 0), settings.shape, settings.size, settings.slot_length,
                settings.shape_angle, settings.arm_width, settings.star_ratio, settings.star_points)


def enclosing_radius(cell):
    if cell.shape in POLYGON_SHAPES:
        return max(math.hypot(*p) for p in cell.vertices)+(cell.curve_tolerance/2 if cell.shape in ORGANIC_FIELDS else 0)
    if cell.shape == 'circle':
        return cell.size / 2
    return max(cell.size, cell.length) / 2


def generate(region, settings, depth, start=0., sweep=math.tau, axial_start=0., axial_length=0.):
    settings.validate()
    if settings.shape in ('smooth_noise', 'reaction_diffusion', 'directional_fibers', 'topographic', 'gyroid', 'blue_noise'):
        raise ValueError('Organic fields require the common curved-surface workflow, not the legacy radial adapter.')
    values = (region.radius, region.height, region.sweep, depth, start, sweep, axial_start, axial_length)
    if not all(math.isfinite(v) for v in values):
        raise ValueError('Cylinder settings must be finite.')
    if region.radius <= 0 or region.height <= 0 or not 0 < region.sweep <= math.tau + 1e-8:
        raise ValueError('Select a bounded cylindrical face.')
    if settings.clip_boundary:
        raise ValueError('Trim to Boundary is not supported on cylindrical faces. Use complete holes.')
    if settings.layout != 'grid' or settings.spread_radius or settings.grid_angle:
        raise ValueError('Cylindrical faces use axial rows, without Pattern Angle or Spread Radius.')
    if not 0 < depth < region.radius:
        raise ValueError('Cut Depth must be positive and less than the cylinder radius to protect the opposite wall.')
    if axial_start < 0 or axial_length < 0 or axial_start >= region.height:
        raise ValueError('Axial Start and Axial Length must lie within the selected face. Use 0 length for the remaining height.')
    height = axial_length or region.height - axial_start
    if axial_start + height > region.height + 1e-8:
        raise ValueError('The axial zone extends beyond the selected face.')
    full_face = abs(region.sweep - math.tau) < 1e-8
    if not 0 < sweep <= region.sweep + 1e-8:
        raise ValueError('Sweep Angle must be positive and fit the selected cylindrical face.')
    if full_face:
        start %= math.tau
    elif start < 0 or start + sweep > region.sweep + 1e-8:
        raise ValueError('Start Angle and Sweep Angle must lie within the selected face.')
    closed = abs(sweep - math.tau) < 1e-8
    if settings.shape == 'voronoi':
        return generate_voronoi(region, settings, depth, start, sweep, axial_start, height)
    radius = enclosing_radius(tool_cell(settings))
    if radius >= region.radius:
        raise ValueError('The hole tool must be smaller than the cylinder radius.')
    sag = region.radius - math.sqrt(region.radius ** 2 - radius ** 2)
    if region.inward and depth <= sag + 1e-5:
        raise ValueError('Cut Depth is too small for this hole size and cylinder curvature.')
    # Each cutter fits in a disk of radius r around its radial segment. Keeping
    # segment distances >= 2r + web protects every pair, including across seam.
    inner = region.radius - depth if region.inward else region.radius - sag
    spacing = 2 * radius + settings.gap
    if spacing >= 2 * inner:
        raise ValueError('Reduce hole size, Web Thickness, or Cut Depth for this cylinder.')
    step = 2 * math.asin(spacing / (2 * inner))
    edge_angle = math.asin(radius / region.radius) + settings.margin / region.radius
    usable_z = height - 2 * (radius + settings.margin)
    usable_angle = sweep if closed else sweep - 2 * edge_angle
    if usable_z < -1e-9 or usable_angle < -1e-9:
        raise ValueError('No complete holes fit the cylinder zone and Edge Offset.')
    columns = max(1, int(math.floor(sweep / step))) if closed else int(math.floor(usable_angle / step + 1e-9)) + 1
    if closed and columns < 2:
        raise ValueError('At least two holes must fit around a closed cylinder.')
    angular_step = sweep / columns if closed else step
    rows = int(math.floor(max(0., usable_z) / spacing + 1e-9)) + 1
    if columns * rows > settings.limit:
        raise ValueError('The cylindrical pattern exceeds Maximum Holes. Increase spacing or reduce the zone.')
    z0 = axial_start + height / 2 - (rows - 1) * spacing / 2
    a0 = start if closed else start + sweep / 2 - (columns - 1) * step / 2
    holes = []
    for row in range(rows):
        shift = angular_step / 2 if settings.staggered and row % 2 else 0.
        for column in range(columns):
            angle = a0 + column * angular_step + shift
            if not closed and angle > start + sweep - edge_angle + 1e-9:
                continue
            holes.append(RadialHole(angle % math.tau, z0 + row * spacing))
    return tuple(holes)


def generate_voronoi(region, settings, depth, start, sweep, axial_start, height, retain_boundary_cells=False):
    """Periodic sites and local straight Voronoi tools with through-depth webs.

    The diagram lives in circumference/axis coordinates. Ghost sites repeat
    exactly at the seam. 3D separating planes then constrain every pair of
    nearby radial tools, including both ends of an almost-closed sector.
    This is not a wrapped surface tiling.
    """
    s, r = settings, region.radius
    closed = abs(sweep - math.tau) < 1e-8
    width = r * sweep
    columns = int(width / s.size) if closed else math.ceil(width / s.size)
    rows = math.ceil(height / s.size)
    if closed and columns < 3:
        raise ValueError('At least three Voronoi sites must fit around the cylinder. Reduce Cell Spacing.')
    if columns * rows > min(25000, max(2500, 4 * s.limit)):
        raise ValueError('The cylindrical Voronoi pattern is too dense. Increase Cell Spacing.')
    dx, dy = (width / columns if closed else s.size), s.size
    sites = {}

    def site(row, col):
        # The same indexed jitter and axial position repeat at +/- one turn.
        key = row, col % columns if closed else col
        if key not in sites:
            sites[key] = (.45 * s.irregularity * _site_random(s.seed, *key, 0),
                          .45 * s.irregularity * _site_random(s.seed, *key, 1))
        jx, jy = sites[key]
        return ((col + (0 if closed else .5) + jx) * dx, (row + .5 + jy) * dy)

    # A source-side radius bound also keeps inner-wall tools away from the axis.
    maximum = .49 * r
    if region.inward:
        available_depth = depth - 2e-5
        if available_depth <= 0:
            raise ValueError('Cut Depth is too small for cylindrical Voronoi.')
        maximum = min(maximum, math.sqrt(available_depth * (2*r - available_depth)))
    rho = r - depth if region.inward else math.sqrt(r*r - maximum*maximum)

    candidates = []
    for row in (range(-1,rows+1) if retain_boundary_cells else range(rows)):
        for col in range(columns):
            x, y = site(row, col)
            bound = 2 * max(dx, dy)
            polygon = ((-bound,-bound), (bound,-bound), (bound,bound), (-bound,bound))
            neighbours = []
            for dr in range(-4, 5):
                for dc in range(-4, 5):
                    if dr or dc:
                        qx, qy = site(row+dr, col+dc)
                        vx, vy = qx-x, qy-y
                        distance = math.hypot(vx, vy)
                        neighbours.append((distance, vx, vy))
            for distance, vx, vy in sorted(neighbours):
                polygon = _clip_voronoi(polygon, vx/distance, vy/distance, (distance-s.gap)/2)
                if len(polygon) < 3:
                    break
            if len(polygon) < 3:
                continue
            radius = max(math.hypot(*v) for v in polygon)
            if radius > maximum:
                polygon = tuple((px*maximum/radius, py*maximum/radius) for px,py in polygon)
                radius = maximum
            angle = x/r
            candidates.append((x, y, (rho*math.cos(angle), rho*math.sin(angle), y), polygon, radius))
    if not candidates:
        raise ValueError('No Voronoi holes fit. Reduce Web Thickness.')
    # Bounded spatial search includes neighbours across either kind of seam.
    # Farther pairs are already separated by their enclosing tool disks.
    cap = 2 * max(c[4] for c in candidates) + s.gap
    buckets = {}
    for index, (_, _, p, _, _) in enumerate(candidates):
        key = tuple(math.floor(v/cap) for v in p)
        buckets.setdefault(key, []).append(index)
    result = []
    for index, (x, y, p, polygon, radius) in enumerate(candidates):
        key = tuple(math.floor(v/cap) for v in p)
        tangent = (-math.sin(x/r), math.cos(x/r))
        constraints = []
        for a in (-1, 0, 1):
            for b in (-1, 0, 1):
                for c in (-1, 0, 1):
                    for other in buckets.get((key[0]+a, key[1]+b, key[2]+c), ()):
                        if other != index:
                            q = candidates[other][2]
                            n = tuple(w-v for v,w in zip(p,q))
                            distance = math.sqrt(sum(v*v for v in n))
                            if distance < radius+candidates[other][4]+s.gap:
                                constraints.append((distance, (n[0]*tangent[0]+n[1]*tangent[1])/distance,
                                                    n[2]/distance))
        # n = (B-A)/|B-A| separates the two sites at their minimum
        # material radius rho. n.radial(A) <= 0, so moving outward along
        # tool A can only move farther from B's halfspace (and vice versa).
        # A gap between the two planes therefore protects the entire depth.
        for distance, nx, ny in sorted(constraints):
            polygon = _clip_voronoi(polygon, nx, ny, (distance-s.gap)/2)
            if len(polygon) < 3:
                break
        if len(polygon) < 3:
            continue
        radius = max(math.hypot(*v) for v in polygon)
        if abs(sum(px*qy-py*qx for (px,py),(qx,qy) in zip(polygon, polygon[1:]+polygon[:1]))) < 1e-8:
            continue
        if not retain_boundary_cells and (y-radius < s.margin or y+radius > height-s.margin):
            continue  # Complete local tools only; do not trim or distort edges.
        if not retain_boundary_cells and not closed and (x/r < math.asin(radius/r)+s.margin/r or
                           x/r > sweep-math.asin(radius/r)-s.margin/r):
            continue
        cell = Cell((0., 0.), 'voronoi', s.size, s.size, 0., polygon=polygon, corner_radius=s.corner_radius)
        result.append(RadialHole((start+x/r) % math.tau, axial_start+y, cell))
        if len(result) > s.limit:
            raise ValueError('The cylindrical pattern exceeds Maximum Holes. Increase Cell Spacing or reduce the zone.')
    if not result:
        raise ValueError('No Voronoi holes fit. Reduce Cell Spacing, Web Thickness, or Edge Offset.')
    return tuple(result)
