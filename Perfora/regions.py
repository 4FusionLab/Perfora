# SPDX-License-Identifier: GPL-3.0-only
"""Dependency-free component-space frames for multiple planar regions (cm)."""
import math

MAX_REGIONS = 32
FRAME_TOLERANCE = 1e-7


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def unit(a):
    length = math.sqrt(dot(a, a))
    if length < 1e-12 or not math.isfinite(length):
        raise ValueError('Unable to resolve the Profiles plane.')
    return tuple(x/length for x in a)


def canonical_frame(frame):
    """Order-independent frame: signed normal, projected component X (or Y).

    Dominant normal component is positive (X wins ties, then Y). Projecting
    component origin onto the plane gives coplanar sources one lattice phase.
    """
    origin, u, v = frame
    n = unit(cross(u, v))
    dominant = max(range(3), key=lambda i: (abs(n[i]), -i))
    if n[dominant] < 0:
        n = tuple(-x for x in n)
    axis = (1., 0., 0.) if abs(n[0]) < .9 else (0., 1., 0.)
    x = unit(tuple(axis[i]-dot(axis, n)*n[i] for i in range(3)))
    y = unit(cross(n, x))
    offset = dot(origin, n)
    return (tuple(offset*a for a in n), x, y)


def to_world(frame, point):
    origin, u, v = frame
    n = cross(u, v)
    z = point[2] if len(point) > 2 else 0.
    return tuple(origin[i]+point[0]*u[i]+point[1]*v[i]+z*n[i] for i in range(3))


def to_local(frame, point):
    origin, u, v = frame
    delta = tuple(point[i]-origin[i] for i in range(3))
    return (dot(delta, u), dot(delta, v), dot(delta, cross(u, v)))


def coplanar(a, b, tolerance=FRAME_TOLERANCE):
    na, nb = unit(cross(a[1], a[2])), unit(cross(b[1], b[2]))
    return (abs(abs(dot(na, nb))-1.) <= 1e-10
            and abs(dot(tuple(b[0][i]-a[0][i] for i in range(3)), na)) <= tolerance)


def bounds_overlap(a, b):
    """Conservative broad phase, including curve-stroking uncertainty."""
    def bounds(region):
        points = [p for loop in region.loops if loop.outer for p in loop.points]
        pad = region.tolerance
        return (min(p[0] for p in points)-pad, max(p[0] for p in points)+pad,
                min(p[1] for p in points)-pad, max(p[1] for p in points)+pad)
    x, y = bounds(a), bounds(b)
    return min(x[1], y[1]) > max(x[0], y[0]) and min(x[3], y[3]) > max(x[2], y[2])


def target_map(supports, targets, operation):
    """Indices persist as Feature metadata; never infer by nearest geometry."""
    if operation not in ('cut', 'intersect', 'join'):
        return tuple(() for _ in supports)
    if not targets:
        raise ValueError('Select Objects for the operation.')
    result = []
    for support in supports:
        if support is not None:
            index = next((i for i, body in enumerate(targets) if body == support), None)
            if index is None:
                raise ValueError('Objects must include the supporting body of every Profiles region.')
        elif len(targets) == 1:
            index = 0
        else:
            raise ValueError('A profile without a supporting body requires exactly one Object.')
        result.append((index,))
    used = [i for indices in result for i in indices]
    if len(set(used)) != len(targets):
        raise ValueError('Remove Objects that are not assigned to a Profiles region.')
    if operation == 'intersect' and len(set(used)) != len(used):
        raise ValueError('Intersect supports one Profiles region per Object. Use separate Objects or Cut.')
    return tuple(result)
