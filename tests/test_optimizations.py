# SPDX-License-Identifier: GPL-3.0-only
"""Exact predicates, bounded preparation, and command-local cache contracts."""
from dataclasses import fields, replace
import gc
import math
import random
import unittest
import weakref

from Perfora import geometry as g
from Perfora.cache import GeometryCache


def reference_contains(p, polygon):
    inside = False
    for a, b in g.edges(polygon):
        if g.point_segment_distance(p, a, b) <= g.EPS:
            return True
        if (a[1] > p[1]) != (b[1] > p[1]):
            if p[0] < a[0] + (p[1]-a[1])*(b[0]-a[0])/(b[1]-a[1]):
                inside = not inside
    return inside


class OptimizationTests(unittest.TestCase):
    def test_contains_matches_original_at_contacts_and_adjacent_floats(self):
        for scale, offset in ((.001, 0), (1, 0), (1000, 1e9), (1, -1e9)):
            polygon = tuple((offset+x*scale, offset+y*scale)
                            for x, y in ((0,0),(3,0),(3,2),(1,1),(0,2)))
            for a, b in g.edges(polygon):
                midpoint = ((a[0]+b[0])/2, (a[1]+b[1])/2)
                for p in (a, b, midpoint):
                    for dx in (-g.EPS, 0, g.EPS):
                        probes = ((p[0]+dx, p[1]), (math.nextafter(p[0], math.inf), p[1]),
                                  (math.nextafter(p[0], -math.inf), p[1]))
                        for probe in probes:
                            self.assertEqual(reference_contains(probe, polygon), g.point_in_polygon(probe, polygon))

    def test_edge_filter_keeps_exact_clearance_and_enclosed_void_checks(self):
        region = g.Region((g.disk_region(6).loops[0],
                           g.Loop(g.rectangle_region(.2, .3).loops[0].points, False)))
        indexed = g.BoundaryIndex(region.segments)
        rng = random.Random(241026)
        for shape in g.SHAPE_IDS:
            settings = g.Settings(shape=shape, size=.4, slot_length=.8, gap=.13, margin=.1)
            if shape == 'voronoi':
                cells = g.generate(region, settings)
            else:
                cells = [g.Cell((rng.uniform(-3,3), rng.uniform(-3,3)), shape, .4, .8,
                                rng.uniform(-math.pi,math.pi)) for _ in range(80)]
            for cell in cells:
                self.assertEqual(g.fits(cell, region, region.segments, .1),
                                 g.fits(cell, region, indexed, .1), (shape, cell.center))

    def test_small_simple_layout_avoids_preparation_and_index_is_not_global(self):
        region = g.rectangle_region(.8, .8)
        g.generate(region, g.Settings(size=.5, gap=.15, margin=.01))
        self.assertNotIn('_boundary_index', region.__dict__)
        large = g.disk_region(8)
        index = large.indexed_segments(100)
        reference = weakref.ref(index)
        self.assertIs(index, large.indexed_segments(100))
        del index, large
        gc.collect()
        self.assertIsNone(reference())

    def test_voronoi_noop_preserves_clean_polygon_and_shared_clip(self):
        points = ((-1.,-1.), (1.,-1.), (1.,1.), (-1.,1.))
        self.assertIs(g._clip_voronoi(points, 1, 0, 2), points)
        for nx, ny, bound in ((1,0,.2), (.6,.8,-.1), (-1,0,2)):
            self.assertEqual(g._clip_halfplane(points,nx,ny,bound),g._clip_voronoi(points,nx,ny,bound))

    def test_cache_accounts_for_every_setting_and_current_context(self):
        cache = GeometryCache()
        region = g.rectangle_region(3, 3)
        base = g.Settings(size=.3, margin=.1, origin_x=0., origin_y=0.)
        cells = cache.resolve(region, base, ('frame',))
        self.assertIs(cells, cache.resolve(g.rectangle_region(3,3), replace(base), ('frame',)))
        self.assertEqual(cache.hits, 1)
        for field in fields(base):
            value = getattr(base, field.name)
            if isinstance(value,bool): value = not value
            elif isinstance(value,str): value = 'slot' if field.name == 'shape' else 'circular'
            elif isinstance(value,int): value += 1
            elif isinstance(value,tuple): value = ((0.,0.), (1.,1.))
            else: value += .2
            if field.name == 'spread_radius': value = 1.0
            if field.name == 'layout_orientation': value = 'tangent'
            changed = replace(base, **{field.name:value})
            cache.resolve(region, base, ('frame',))
            before = cache.misses
            cache.resolve(region, changed, ('frame',))
            self.assertEqual(cache.misses, before+1, field.name)
        before = cache.misses
        cache.resolve(region, base, ('other frame',))
        self.assertEqual(cache.misses, before+1)
        before = cache.misses
        cache.resolve(replace(region, tolerance=.0002), base, ('other frame',))
        self.assertEqual(cache.misses, before+1)

    def test_failed_generation_is_not_published_and_clear_releases_data(self):
        cache = GeometryCache()
        region = g.rectangle_region(3,3)
        good = g.Settings(size=.4,margin=.1)
        cache.resolve(region, good)
        prepared = cache.prepared
        with self.assertRaises(ValueError): cache.resolve(region,replace(good,limit=0))
        self.assertIs(cache.prepared, prepared)
        ref = weakref.ref(region)
        del region, prepared
        cache.resolve(g.rectangle_region(4,4), good)
        gc.collect()
        self.assertIsNone(ref())
        cache.clear()
        self.assertIsNone(cache.prepared)
