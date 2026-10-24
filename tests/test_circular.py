# SPDX-License-Identifier: GPL-3.0-only
"""Circular layout contracts: rings, true hole clearances and placement."""
from dataclasses import replace
import math
import unittest

from Perfora.geometry import (Loop, Region, Settings, SHAPE_IDS, disk_region, dist,
                             edges, fits, generate, rectangle_region, rotate,
                             segment_distance)


class CircularTests(unittest.TestCase):
    def test_closed_rings_have_expected_counts_and_minimum_web(self):
        s = Settings(layout='circular', size=.5, gap=.2, margin=.1)
        cells = generate(disk_region(5), s)
        rings = {}
        for cell in cells:
            rings.setdefault(round(math.hypot(*cell.center), 8), []).append(cell)
        self.assertEqual([len(ring) for ring in rings.values()], [1, 6, 12, 18])
        for i, cell in enumerate(cells):
            for other in cells[i + 1:]:
                self.assertGreaterEqual(dist(cell.center, other.center) - s.size + 1e-9, s.gap)

    def test_all_repeating_shapes_preserve_boundary_and_true_contour_gap(self):
        region = rectangle_region(4, 3)
        for shape in SHAPE_IDS:
            if shape == 'voronoi':
                continue
            for radial, tangential in ((False, False), (True, False), (False, True)):
                with self.subTest(shape=shape, radial=radial, tangential=tangential):
                    s = Settings(layout='circular', shape=shape, size=.4, slot_length=.7,
                                 gap=.13, margin=.12, grid_angle=.31, shape_angle=.63,
                                 radial_orientation=radial, tangential_orientation=tangential, offset_x=.11, offset_y=-.17)
                    cells = generate(region, s)
                    self.assertGreater(len(cells), 3)
                    for cell in cells:
                        self.assertTrue(fits(cell, region, region.segments, s.margin))
                    for i, cell in enumerate(cells):
                        for other in cells[i + 1:]:
                            if dist(cell.center, other.center) > 1.5:
                                continue
                            if shape in ('circle', 'slot'):
                                gap = segment_distance(*cell.spine, *other.spine) - s.size
                            else:
                                a = cell.ellipse_points(48) if shape == 'ellipse' else cell.vertices
                                b = other.ellipse_points(48) if shape == 'ellipse' else other.vertices
                                gap = min(segment_distance(p, q, r, t) for p, q in edges(a) for r, t in edges(b))
                            self.assertGreaterEqual(gap + 1e-8, s.gap)

    def test_start_radius_omits_center_and_orientation_tracks_radius(self):
        s = Settings(layout='circular', shape='slot', size=.25, slot_length=.6,
                     gap=.1, margin=.1, start_radius=.9, radial_orientation=True,
                     grid_angle=.21, shape_angle=math.pi / 2, offset_x=.2, offset_y=-.1)
        cells = generate(rectangle_region(6, 6), s)
        for cell in cells:
            x, y = cell.center[0] - .2, cell.center[1] + .1
            self.assertGreaterEqual(math.hypot(x, y) + 1e-9, .9)
            self.assertAlmostEqual(math.remainder(cell.angle - math.atan2(y, x) - math.pi / 2, math.tau), 0)
        fixed = generate(rectangle_region(6, 6), replace(s, radial_orientation=False))
        self.assertTrue(all(abs(c.angle - (s.grid_angle + s.shape_angle)) < 1e-9 for c in fixed))

    def test_tangential_slots_follow_the_circumference(self):
        s = Settings(layout='circular', shape='slot', size=.25, slot_length=.7,
                     gap=.12, margin=.1, start_radius=1.1, grid_angle=.37,
                     tangential_orientation=True, offset_x=.2, offset_y=-.3)
        cells = generate(rectangle_region(6, 6), s)
        for cell in cells:
            a, b = cell.spine
            tangent = (b[0] - a[0], b[1] - a[1])
            radial = (cell.center[0] - .2, cell.center[1] + .3)
            self.assertAlmostEqual(sum(x*y for x, y in zip(tangent, radial)), 0)
        rotated = generate(rectangle_region(6, 6),
                           replace(s, tangential_orientation=False, radial_orientation=True, shape_angle=math.pi/2))
        self.assertEqual(cells, rotated)

    def test_pattern_angle_rotates_about_offset_center(self):
        s = Settings(layout='circular', size=.3, gap=.12, margin=.1,
                     start_radius=.5, offset_x=.2, offset_y=-.1)
        region = rectangle_region(3, 3)
        # Restrict to an interior ring so boundary rejection cannot affect the comparison.
        a = [c for c in generate(region, s) if dist(c.center, (.2, -.1)) < 1]
        b = [c for c in generate(region, replace(s, grid_angle=.47)) if dist(c.center, (.2, -.1)) < 1]
        self.assertEqual(len(a), len(b))
        for first, second in zip(a, b):
            x, y = rotate((first.center[0] - .2, first.center[1] + .1), .47)
            self.assertLess(dist(second.center, (x + .2, y - .1)), 1e-9)

    def test_annulus_respects_existing_void_and_margin(self):
        region = Region((disk_region(6).loops[0], Loop(disk_region(2).loops[0].points, False)))
        s = Settings(layout='circular', size=.45, gap=.15, margin=.2)
        for cell in generate(region, s):
            self.assertTrue(fits(cell, region, region.segments, s.margin))
            self.assertGreaterEqual(math.hypot(*cell.center) - s.size / 2, 1 + s.margin)

    def test_trim_candidates_include_partial_holes_and_keep_whole_cells(self):
        region = rectangle_region(3, 2.2)
        s = Settings(layout='circular', shape='slot', size=.35, slot_length=.7,
                     gap=.1, margin=.15, radial_orientation=True, offset_x=.2)
        whole = generate(region, s)
        trimmed = generate(region, replace(s, clip_boundary=True))
        self.assertTrue(set(whole).issubset(set(trimmed)))
        self.assertTrue(any(not fits(c, region, region.segments, 0) for c in trimmed))
        self.assertTrue(any(not region.contains(c.center) for c in trimmed))

    def test_translation_and_reproducibility(self):
        region = rectangle_region(4, 3)
        translated = Region(tuple(Loop(tuple((x + 7, y - 9) for x, y in l.points), l.outer) for l in region.loops))
        s = Settings(layout='circular', size=.4, gap=.1, margin=.1, grid_angle=.39)
        cells = generate(region, s)
        self.assertEqual(cells, generate(region, s))
        for a, b in zip(cells, generate(translated, s)):
            self.assertLess(dist((a.center[0] + 7, a.center[1] - 9), b.center), 1e-9)

    def test_validation_limits_density_and_no_fit(self):
        for change in (dict(layout='unknown'), dict(start_radius=-1), dict(start_radius=float('nan')),
                       dict(start_radius=float('inf')), dict(shape='voronoi')):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(Settings(layout='circular'), **change).validate()
        for change in (dict(limit=2), dict(size=.001, gap=.001), dict(start_radius=100),
                       dict(offset_x=1e9)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                generate(rectangle_region(4, 3), replace(Settings(layout='circular'), **change))
        # Circular-only fields do not affect an existing grid setting.
        s = Settings(start_radius=float('nan'))
        self.assertEqual(generate(rectangle_region(4, 3), s), generate(rectangle_region(4, 3), Settings()))


if __name__ == '__main__':
    unittest.main()
