# SPDX-License-Identifier: GPL-3.0-only
"""Global pattern origin and bounded radial spread across every distribution."""
from dataclasses import replace
import math
import unittest

from Perfora.geometry import (Settings, SHAPE_IDS, Region, Loop, rectangle_region, generate,
                             dist, fits, placement_center, rotate)


class OriginTests(unittest.TestCase):
    def test_grid_and_rings_contain_a_hole_at_the_selected_origin(self):
        for layout in ('grid', 'circular'):
            s = Settings(layout=layout, size=.25, gap=.12, margin=.1, staggered=True,
                         grid_angle=.43, origin_x=.37, origin_y=-.29, offset_x=.13, offset_y=-.09)
            region = rectangle_region(5, 4)
            center = placement_center(region, s)
            cells = generate(region, s)
            self.assertTrue(any(dist(cell.center, center) < 1e-8 for cell in cells), layout)

    def test_spread_applies_to_every_shape_and_distribution(self):
        region = rectangle_region(6, 5)
        for shape in SHAPE_IDS:
            for layout in ('grid', 'circular') if shape != 'voronoi' else ('grid',):
                with self.subTest(shape=shape, layout=layout):
                    s = Settings(layout=layout, shape=shape, size=.3, slot_length=.55,
                                 gap=.12, margin=.1, origin_x=.31, origin_y=-.23,
                                 grid_angle=.37, offset_x=.11, offset_y=-.09, spread_radius=1.4,
                                 tangential_orientation=layout == 'circular')
                    center = placement_center(region, s)
                    scope = Region(region.loops, region.tolerance, center, s.spread_radius)
                    cells = generate(region, s)
                    self.assertTrue(cells)
                    self.assertTrue(all(fits(cell, scope, scope.segments, s.margin) for cell in cells))
                    if shape in ('circle', 'slot'):
                        reaches = [max(dist(p, center) for p in c.spine) + c.size/2 for c in cells]
                    else:
                        reaches = [max(dist(p, center) for p in
                            (c.ellipse_points(enclosing=True) if shape == 'ellipse' else c.vertices)) for c in cells]
                    self.assertLessEqual(max(reaches), s.spread_radius-s.margin)

    def test_radius_changes_do_not_rephase_the_lattice(self):
        region = rectangle_region(9, 8)
        for shape, layout in (('circle', 'grid'), ('slot', 'circular'), ('voronoi', 'grid')):
            s = Settings(shape=shape, layout=layout, size=.35, slot_length=.7,
                         gap=.12, margin=.1, grid_angle=.3, spread_radius=1.2)
            small = generate(region, s)
            large = generate(region, replace(s, spread_radius=1.7))
            self.assertTrue(set(small).issubset(set(large)), (shape, layout))

    def test_spread_bounds_work_on_large_boundaries(self):
        region = rectangle_region(1e5, 1e5)
        for shape, layout in (('circle', 'grid'), ('slot', 'circular'), ('voronoi', 'grid')):
            s = Settings(shape=shape, layout=layout, size=.35, slot_length=.7,
                         margin=.1, spread_radius=1.6, origin_x=1234, origin_y=-2134)
            cells = generate(region, s)
            self.assertGreater(len(cells), 1)
            self.assertLess(len(cells), 100)

    def test_unlimited_defaults_preserve_existing_layouts(self):
        region = rectangle_region(4, 3)
        for shape in ('circle', 'voronoi'):
            s = Settings(shape=shape)
            self.assertEqual(generate(region, s), generate(region, replace(s, spread_radius=0)))

    def test_invalid_radius_and_missing_origin_coordinate_are_rejected(self):
        for changes in (dict(spread_radius=-1), dict(spread_radius=math.inf),
                        dict(spread_radius=math.nan), dict(spread_radius=.1, margin=.2),
                        dict(origin_x=.3), dict(origin_x=math.inf, origin_y=0)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(Settings(), **changes).validate()
        with self.assertRaises(ValueError):
            generate(rectangle_region(3, 2), Settings(spread_radius=1, origin_x=10, origin_y=10))
