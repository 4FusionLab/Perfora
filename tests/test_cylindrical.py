# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import math
import unittest

from Perfora.geometry import ORGANIC_SHAPES
from Perfora.geometry import Settings, SHAPE_IDS
from Perfora.cylindrical_geometry import CylinderRegion, generate, tool_cell, enclosing_radius


class CylindricalTests(unittest.TestCase):
    def test_voronoi_cylinder_builds_reproducible_periodic_cells(self):
        region = CylinderRegion(2., 3.)
        settings = Settings(shape='voronoi', size=.6, gap=.12, margin=.1, seed=17)
        holes = generate(region, settings, .35)
        self.assertTrue(holes)
        self.assertEqual(holes, generate(region, settings, .35))
        self.assertTrue(all(h.cell.shape == 'voronoi' and len(h.cell.vertices) >= 3 for h in holes))

    def test_closed_rows_are_unique_and_web_safe_through_depth(self):
        for inward in (True, False):
            for staggered in (True, False):
                region = CylinderRegion(2., 2.5, inward=inward)
                settings = Settings(size=.3, gap=.12, margin=.1, staggered=staggered)
                holes = generate(region, settings, .35, start=6.1)
                self.assertEqual(len(holes), len({(round(h.angle, 9), round(h.axial, 9)) for h in holes}))
                r = enclosing_radius(tool_cell(settings))
                rho = region.radius - .35 if inward else math.sqrt(region.radius ** 2 - r ** 2)
                for i, a in enumerate(holes):
                    for b in holes[i+1:]:
                        distance = math.hypot(2 * rho * math.sin((a.angle-b.angle) / 2), a.axial-b.axial)
                        self.assertGreaterEqual(distance - 2*r + 1e-9, settings.gap)

    def test_all_repeating_shapes_respect_zone_and_margins(self):
        region = CylinderRegion(2., 3., sweep=math.pi)
        for shape in (s for s in SHAPE_IDS if s not in ORGANIC_SHAPES):
            if shape == 'voronoi':
                continue
            settings = Settings(shape=shape, size=.3, slot_length=.55, gap=.12, margin=.1, shape_angle=.4)
            holes = generate(region, settings, .35, start=.2, sweep=2., axial_start=.3, axial_length=2.)
            radius = enclosing_radius(tool_cell(settings))
            angular_margin = math.asin(radius / region.radius) + settings.margin / region.radius
            self.assertTrue(holes, shape)
            for hole in holes:
                self.assertGreaterEqual(hole.angle + 1e-9, .2 + angular_margin)
                self.assertLessEqual(hole.angle - 1e-9, 2.2 - angular_margin)
                self.assertGreaterEqual(hole.axial + 1e-9, .3 + radius + settings.margin)
                self.assertLessEqual(hole.axial - 1e-9, 2.3 - radius - settings.margin)

    def test_full_revolution_has_no_artificial_seam_margin(self):
        region = CylinderRegion(2., 1.)
        settings = Settings(size=.3, gap=.1, margin=.2)
        holes = generate(region, settings, .2)
        self.assertTrue(any(h.angle == 0 for h in holes))
        self.assertEqual(holes, generate(region, settings, .2, start=math.tau))

    def test_rejects_unsafe_or_unsupported_settings(self):
        region, settings = CylinderRegion(2., 3.), Settings()
        for change in (dict(depth=0), dict(depth=2), dict(depth=.001), dict(depth=float('nan')),
                       dict(depth=.2, sweep=0), dict(depth=.2, sweep=7),
                       dict(depth=.2, axial_start=-1), dict(depth=.2, axial_length=4)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                generate(region, settings, **change)
        for change in (dict(clip_boundary=True), dict(layout='circular'),
                       dict(grid_angle=.1), dict(spread_radius=1), dict(limit=1)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                generate(region, replace(settings, **change), .2)
        with self.assertRaises(ValueError):
            generate(CylinderRegion(2, 3, math.pi), settings, .2, start=2., sweep=2.)

    def test_voronoi_web_bounds_include_seam_and_nearly_closed_sector(self):
        for inward in (True, False):
            region = CylinderRegion(2., 2., inward=inward)
            for sweep in (math.tau, math.radians(350)):
                for irregularity in (0., 1.):
                    s = Settings(shape='voronoi', size=.5, gap=.1, margin=.1, irregularity=irregularity, seed=23)
                    holes = generate(region, s, .3, sweep=sweep)
                    radii = [enclosing_radius(h.cell) for h in holes]
                    rho = 1.7 if inward else math.sqrt(4 - (.49*2)**2)
                    for i, a in enumerate(holes):
                        self.assertGreaterEqual(a.axial-radii[i]+1e-8, s.margin)
                        self.assertLessEqual(a.axial+radii[i]-1e-8, 2-s.margin)
                        for j, b in enumerate(holes[i+1:], i+1):
                            def vertices(h):
                                c,t=math.cos(h.angle),math.sin(h.angle)
                                return [(rho*c-t*x, rho*t+c*x, h.axial+y) for x,y in h.cell.vertices]
                            ca=(rho*math.cos(a.angle),rho*math.sin(a.angle),a.axial)
                            cb=(rho*math.cos(b.angle),rho*math.sin(b.angle),b.axial)
                            n=tuple(y-x for x,y in zip(ca,cb))
                            distance=math.sqrt(sum(v*v for v in n))
                            n=tuple(v/distance for v in n)
                            project=lambda p:sum(x*y for x,y in zip(p,n))
                            gap=min(map(project,vertices(b)))-max(map(project,vertices(a)))
                            self.assertGreaterEqual(gap+1e-8,s.gap)

    def test_voronoi_seed_rounding_and_periodic_origin(self):
        region = CylinderRegion(2., 3.)
        s = Settings(shape='voronoi', size=.6, gap=.1, margin=.1, irregularity=0)
        regular = generate(region, s, .3)
        self.assertTrue(any(abs(h.angle)<1e-9 for h in regular))
        self.assertEqual(regular, generate(region, s, .3, start=math.tau))
        s = replace(s, irregularity=1, seed=11, corner_radius=.04)
        holes = generate(region, s, .3)
        self.assertNotEqual(holes, generate(region, replace(s, seed=12), .3))
        self.assertTrue(all(h.cell.corner_radius==.04 and h.cell.contour for h in holes))
        with self.assertRaises(ValueError):
            generate(region, replace(s, size=1e-8), .3)
        with self.assertRaises(ValueError):
            generate(region, replace(s, limit=1), .3)


if __name__ == '__main__':
    unittest.main()
