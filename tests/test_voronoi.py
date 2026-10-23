# SPDX-License-Identifier: GPL-3.0-only
import math
import unittest
from dataclasses import replace

from Perfora.geometry import (Loop, Region, Settings, edges, fits, generate,
                              outline_coordinates, rectangle_region, rotate, segment_distance, _site_random)


class VoronoiTests(unittest.TestCase):
    def test_reproducible_seed_and_seed_variation(self):
        region = rectangle_region(4, 3)
        settings = Settings(shape='voronoi', size=.7, gap=.1, margin=.1)
        cells = generate(region, settings)
        self.assertEqual(cells, generate(region, settings))
        self.assertNotEqual(cells, generate(region, replace(settings, seed=2)))
        regular = replace(settings, irregularity=0)
        self.assertEqual(generate(region, regular), generate(region, replace(regular, seed=999)))

    def test_zero_irregularity_has_exact_square_size_and_web(self):
        s = Settings(shape='voronoi', size=1, gap=.2, margin=.1, irregularity=0)
        cells = generate(rectangle_region(4, 4), s)
        self.assertEqual(len(cells), 9)
        for cell in cells:
            self.assertEqual(len(cell.vertices), 4)
            self.assertAlmostEqual(max(x for x, _ in cell.vertices) - min(x for x, _ in cell.vertices), .8)
            self.assertAlmostEqual(max(y for _, y in cell.vertices) - min(y for _, y in cell.vertices), .8)

    def test_actual_web_clearance_convexity_and_closed_preview(self):
        region = Region((rectangle_region(4, 3).loops[0],
                         Loop(((-.25, -.25), (.25, -.25), (.25, .25), (-.25, .25)), False)))
        for seed in (0, 1, 47, 2147483647):
            for irregularity in (0, .5, 1):
                s = Settings(shape='voronoi', size=.65, gap=.12, margin=.08,
                             seed=seed, irregularity=irregularity, grid_angle=.37, offset_x=.13)
                cells = generate(region, s)
                for cell in cells:
                    self.assertTrue(fits(cell, region, region.segments, s.margin))
                    points = cell.vertices
                    self.assertGreater(sum(a[0]*b[1] - b[0]*a[1] for a, b in edges(points)), 0)
                    xyz = outline_coordinates([cell], region)
                    self.assertEqual(len(xyz), len(points)*6)
                    self.assertEqual(xyz[:3], xyz[-3:])
                for i, cell in enumerate(cells):
                    for other in cells[i+1:]:
                        actual = min(segment_distance(a, b, c, d)
                                     for a, b in edges(cell.vertices) for c, d in edges(other.vertices))
                        self.assertGreaterEqual(actual + 1e-8, s.gap)

    def test_rotation_and_periodic_placement(self):
        region = rectangle_region(4, 3)
        s = Settings(shape='voronoi', size=.7, gap=.1, margin=.1, offset_x=.19, offset_y=-.07)
        original = generate(region, s)
        rotated = Region(tuple(Loop(tuple(rotate(p, .62) for p in loop.points), loop.outer) for loop in region.loops))
        actual = generate(rotated, replace(s, grid_angle=.62))
        self.assertEqual(len(original), len(actual))
        for a, b in zip(original, actual):
            for p, q in zip(a.vertices, b.vertices):
                self.assertLess(math.dist(rotate(p, .62), q), 1e-10)
        periodic = generate(region, replace(s, offset_x=s.offset_x+700, offset_y=s.offset_y-700))
        self.assertEqual(len(original), len(periodic))
        self.assertLess(max(math.dist(a.center, b.center) for a, b in zip(original, periodic)), 1e-10)

    def test_cells_satisfy_all_site_bisectors_without_artificial_edges(self):
        # An independent, much wider set of sites checks the bounded-neighbour
        # optimisation and that every output edge is an inset Voronoi bisector.
        s = Settings(shape='voronoi', size=.7, gap=.1, margin=.1, irregularity=1, seed=73)
        sites = [((col+.45*_site_random(s.seed,row,col,0))*s.size,
                  (row+.45*_site_random(s.seed,row,col,1))*s.size)
                 for row in range(-9,10) for col in range(-9,10)]
        for cell in generate(rectangle_region(3, 2), s):
            site = min(sites, key=lambda p: math.dist(p, cell.center))
            planes = [(p[0]-site[0], p[1]-site[1], math.dist(p, site)) for p in sites if p != site]
            for p in cell.vertices:
                for dx, dy, distance in planes:
                    signed = ((p[0]-site[0])*dx+(p[1]-site[1])*dy)/distance
                    self.assertLessEqual(signed, distance/2-s.gap/2+1e-9)
            for a, b in edges(cell.vertices):
                midpoint = ((a[0]+b[0])/2, (a[1]+b[1])/2)
                error = min(abs(((midpoint[0]-site[0])*dx+(midpoint[1]-site[1])*dy)/distance
                                -distance/2+s.gap/2) for dx, dy, distance in planes)
                self.assertLess(error, 1e-9)

    def test_clipping_adds_partial_candidates_without_changing_holes(self):
        region = rectangle_region(3, 2)
        s = Settings(shape='voronoi', size=.8, gap=.1, margin=.15)
        complete = generate(region, s)
        clipped = generate(region, replace(s, clip_boundary=True))
        self.assertGreater(len(clipped), len(complete))
        self.assertTrue(set(complete).issubset(set(clipped)))

    def test_invalid_controls_limits_density_and_consumed_cells(self):
        for kwargs in (dict(irregularity=-.1), dict(irregularity=1.1), dict(irregularity=float('nan')),
                       dict(seed=-1), dict(seed=2**31), dict(seed=1.5)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Settings(shape='voronoi', **kwargs).validate()
        for kwargs in (dict(limit=1), dict(size=.00001), dict(gap=3)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                generate(rectangle_region(4, 4), Settings(shape='voronoi', **kwargs))


if __name__ == '__main__':
    unittest.main()
