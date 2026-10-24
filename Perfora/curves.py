# SPDX-License-Identifier: GPL-3.0-only
"""Shared, dependency-free open planar guide contract (cm).

Adapters supply finite 2D strokes. This module owns normalized arc length,
endpoint matching and conservative strip validation, reusable by Along Curve.
It never imports Fusion and does not promise arbitrary spline correspondence.
"""
from bisect import bisect_right
import math
from .geometry import EPS, dist, segment_distance, cross


class SegmentIndex:
    """Uniform broad phase for stroke intersections; bounded storage."""
    def __init__(self, scale):
        self.scale = scale
        self.buckets = {}
        self.items = []
        self.entries = 0

    def keys(self, a, b, padding=0):
        x0, x1 = (math.floor((min(a[0], b[0])-padding)/self.scale),
                  math.floor((max(a[0], b[0])+padding)/self.scale))
        y0, y1 = (math.floor((min(a[1], b[1])-padding)/self.scale),
                  math.floor((max(a[1], b[1])+padding)/self.scale))
        if (x1-x0+1)*(y1-y0+1) > 100000:
            raise ValueError('Guide geometry is too complex. Simplify the curves.')
        return ((x, y) for x in range(x0, x1+1) for y in range(y0, y1+1))

    def nearby(self, a, b, padding=0):
        ids = set()
        for key in self.keys(a, b, padding):
            ids.update(self.buckets.get(key, ()))
        return (self.items[i] for i in sorted(ids))

    def add(self, a, b, label):
        index = len(self.items)
        self.items.append((a, b, label))
        for key in self.keys(a, b):
            self.buckets.setdefault(key, []).append(index)
            self.entries += 1
            if self.entries > 200000:
                raise ValueError('Guide geometry is too complex. Simplify the curves.')


class ArcPath:
    def __init__(self, points, closed=False):
        clean = []
        for p in points:
            if len(p) != 2 or not all(math.isfinite(v) for v in p):
                raise ValueError('Guides must contain finite planar coordinates.')
            p = tuple(p)
            if not clean or dist(clean[-1], p) > EPS:
                clean.append(p)
        if len(clean) < 2:
            raise ValueError('A guide has zero length.')
        if closed and dist(clean[0], clean[-1]) > EPS:
            clean.append(clean[0])
        self.points = tuple(clean)
        self.lengths = [0.0]
        for a, b in zip(clean, clean[1:]):
            self.lengths.append(self.lengths[-1] + dist(a, b))
        self.length = self.lengths[-1]
        if not math.isfinite(self.length):
            raise ValueError('The guide exceeds the supported coordinate range.')

    def at(self, fraction):
        target = max(0.0, min(1.0, fraction)) * self.length
        i = min(len(self.points)-2, bisect_right(self.lengths, target)-1)
        a, b = self.points[i:i+2]
        t = (target-self.lengths[i])/(self.lengths[i+1]-self.lengths[i])
        return (a[0]+t*(b[0]-a[0]), a[1]+t*(b[1]-a[1]))

    def spaced(self, spacing, closed=False):
        # Closed paths omit the duplicate endpoint. floor never shortens the
        # requested arc-length pitch; the layout guard also checks the chord.
        count = max(1, math.floor(self.length/spacing))
        return [self.at(i/count) for i in range(count if closed else count+1)]


def prepare_guides(first, second, tolerance=0.0005, reverse=False):
    if max(len(first), len(second)) > 2048:
        raise ValueError('Guides have too many stroke points. Simplify the curves.')
    a, b = ArcPath(first), ArcPath(second)
    for path in (a, b):
        if dist(path.points[0], path.points[-1]) <= tolerance:
            raise ValueError('Between Curves requires two open guides.')
    direct = dist(a.points[0], b.points[0])+dist(a.points[-1], b.points[-1])
    flipped = dist(a.points[0], b.points[-1])+dist(a.points[-1], b.points[0])
    if (flipped < direct) != reverse:
        b = ArcPath(tuple(reversed(b.points)))
    scale = max(a.length, b.length)/max(4, math.sqrt(len(first)+len(second)))
    index = SegmentIndex(max(scale, tolerance*10))
    for which, path in enumerate((a, b)):
        for i, (p, q) in enumerate(zip(path.points, path.points[1:])):
            for c, d, (owner, j) in index.nearby(p, q, tolerance):
                if owner == which and abs(j-i) <= 1:
                    continue
                if segment_distance(p, q, c, d) <= tolerance:
                    raise ValueError('Guides must be separate, open and free of intersections.')
            index.add(p, q, (which, i))
    # Include every source vertex fraction: corners must not disappear during
    # common-length resampling. A bounded regular mesh also detects strip folds.
    samples = sorted(set([i/128 for i in range(129)] +
                         [v/a.length for v in a.lengths] + [v/b.length for v in b.lengths]))
    fractions = []
    for t in samples:
        if not fractions or (t-fractions[-1])*max(a.length,b.length) > tolerance*.01:
            fractions.append(t)
    fractions[-1] = 1.0
    links = SegmentIndex(max(scale, tolerance*10))
    sign = None
    for i, t in enumerate(fractions):
        p, q = a.at(t), b.at(t)
        if dist(p, q) <= tolerance:
            raise ValueError('The guide strip collapses. Select separate guides.')
        cutoff = min(.05, 4*tolerance/dist(p,q))
        interior_p = tuple(p[k]+cutoff*(q[k]-p[k]) for k in (0,1))
        interior_q = tuple(q[k]+cutoff*(p[k]-q[k]) for k in (0,1))
        for c,d,_ in index.nearby(p,q,tolerance):
            if segment_distance(interior_p,interior_q,c,d) <= tolerance:
                raise ValueError('The guide strip crosses a guide or is too narrow at this tolerance.')
        for c, d, j in links.nearby(p, q, tolerance):
            # Nearby normalized samples may be much closer than the stroke
            # tolerance. Only an actual crossing is a fold; mere proximity is
            # expected and must not reject smooth guides of unequal length.
            if segment_distance(p, q, c, d) <= EPS:
                raise ValueError('The guide strip folds or crosses. Select simpler guides or reverse direction.')
        links.add(p, q, i)
        if i:
            # Both triangles of each quadrilateral must retain orientation.
            for area in (cross(previous_p, p, q), cross(previous_p, q, previous_q)):
                if abs(area) <= EPS*EPS or sign is not None and area*sign <= 0:
                    raise ValueError('The guide strip folds or degenerates. Select simpler guides.')
                sign = 1 if area > 0 else -1
        previous_p, previous_q = p, q
    return a, b, fractions
