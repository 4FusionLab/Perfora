# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import math
import unittest

from Perfora.geometry import (Settings, dist, generate, outline_coordinates,
                              point_in_polygon, rectangle_region, rounded_polygon)
from Perfora import geometry


def contour_area(contour):
    area = sum(e.start[0]*e.end[1]-e.end[0]*e.start[1] for e in contour)/2
    return area+sum(dist(e.start,e.center)**2*(e.sweep-math.sin(e.sweep))/2
                    for e in contour if e.center is not None)


class RoundingTests(unittest.TestCase):
    def test_clipped_line_arc_corners_become_tangent(self):
        contour = (geometry.ContourEdge((-1,0),(1,0)),
                   geometry.ContourEdge((1,0),(-1,0),(0,0),math.pi))
        rounded = geometry.round_contour(contour,.1)
        self.assertEqual(sum(e.center is not None for e in rounded),3)
        def tangent(edge,end):
            if edge.center is None:
                x,y=edge.end[0]-edge.start[0],edge.end[1]-edge.start[1]
            else:
                p=edge.end if end else edge.start
                sign=1 if edge.sweep>0 else -1
                x,y=-(p[1]-edge.center[1])*sign,(p[0]-edge.center[0])*sign
            length=math.hypot(x,y)
            return x/length,y/length
        for i,edge in enumerate(rounded):
            other=rounded[(i+1)%len(rounded)]
            self.assertLess(dist(edge.end,other.start),1e-8)
            self.assertGreater(sum(a*b for a,b in zip(tangent(edge,True),tangent(other,False))),1-1e-8)
            for x,y in edge.samples():
                self.assertGreaterEqual(y,-1e-8)
                self.assertLessEqual(math.hypot(x,y),1+1e-8)

    def test_short_bevel_does_not_shrink_distant_corner_radii(self):
        # A tiny Voronoi edge used to reduce every radius in an otherwise large
        # cell, making all its ordinary corners look sharp in the final model.
        contour = rounded_polygon(((-1,-1),(.999,-1),(1,-.999),(1,1),(-1,1)), .2)
        ordinary = [e for e in contour if e.center is not None and e.center[0] < 0]
        self.assertEqual(len(ordinary),2)
        for edge in ordinary:
            self.assertAlmostEqual(dist(edge.start,edge.center),.2)

    def test_short_bevel_is_absorbed_instead_of_leaving_microscopic_fillets(self):
        points=((-1,-1),(.999,-1),(1,-.999),(1,1),(-1,1))
        contour=rounded_polygon(points,.2)
        arcs=[e for e in contour if e.center is not None]
        self.assertEqual(len(arcs),4)
        for arc in arcs:
            self.assertAlmostEqual(dist(arc.start,arc.center),.2)
            self.assertTrue(all(point_in_polygon(p,points) for p in arc.samples()))

    def test_square_has_exact_radius_area_and_tangent_lines(self):
        contour = rounded_polygon(((-1,-1),(1,-1),(1,1),(-1,1)), .2)
        self.assertEqual(len(contour), 8)
        self.assertAlmostEqual(contour_area(contour), 4-(4-math.pi)*.2**2)
        for i, edge in enumerate(contour):
            self.assertEqual(edge.end, contour[(i+1) % len(contour)].start)
            if edge.center is not None:
                self.assertAlmostEqual(dist(edge.start, edge.center), .2)
                self.assertAlmostEqual(dist(edge.end, edge.center), .2)
                for fraction in (0, .25, .5, .75, 1):
                    self.assertAlmostEqual(dist(edge.at(fraction), edge.center), .2)
                line = contour[(i+1) % len(contour)]
                radial = (edge.end[0]-edge.center[0],edge.end[1]-edge.center[1])
                tangent = (line.end[0]-line.start[0],line.end[1]-line.start[1])
                self.assertAlmostEqual(sum(a*b for a,b in zip(radial,tangent)),0)

    def test_large_radius_is_limited_per_hole_without_crossing_edges(self):
        points = ((-1,-.25),(1,-.25),(1,.25),(-1,.25))
        contour = rounded_polygon(points, 100)
        radii = [dist(e.start,e.center) for e in contour if e.center is not None]
        self.assertTrue(all(abs(r-.245)<1e-9 for r in radii))
        self.assertGreater(contour_area(contour), 0)
        self.assertLess(contour_area(contour), 1)
        for e in contour:
            self.assertGreater(dist(e.start,e.end),0)
            self.assertTrue(all(point_in_polygon(p,points) for p in e.samples()))

    def test_rounding_preserves_layout_minimum_web_and_closed_preview(self):
        region = rectangle_region(3, 2)
        sharp = Settings(shape='voronoi', size=.6, gap=.12, margin=.1, seed=47)
        original = generate(region, sharp)
        for radius in (.03, .1, 10):
            cells = generate(region, replace(sharp, corner_radius=radius))
            self.assertEqual([c.vertices for c in cells], [c.vertices for c in original])
            for cell in cells:
                for i, edge in enumerate(cell.contour):
                    self.assertLess(dist(edge.end,cell.contour[(i+1)%len(cell.contour)].start),1e-9)
                    self.assertTrue(all(point_in_polygon(p,cell.vertices) for p in edge.samples()))
                xyz = outline_coordinates([cell],region)
                self.assertEqual(xyz[:3],xyz[-3:])
                for i in range(0,len(xyz)-6,6):
                    self.assertEqual(xyz[i+3:i+6],xyz[i+6:i+9])
            # Sampling inscribed arcs can only overestimate gaps very slightly;
            # compare with the conservative, original polygon envelopes too.
            for i, cell in enumerate(cells):
                points = [p for e in cell.contour for p in e.samples()[:-1]]
                for other in cells[i+1:]:
                    for p in points:
                        self.assertFalse(point_in_polygon(p,other.vertices))

    def test_disabled_is_unchanged_and_invalid_radius_is_rejected(self):
        points = ((0,0),(1,0),(0,1))
        self.assertTrue(all(e.center is None for e in rounded_polygon(points,0)))
        for radius in (-1,float('inf'),float('nan')):
            with self.subTest(radius=radius), self.assertRaises(ValueError):
                Settings(shape='voronoi',corner_radius=radius).validate()


if __name__ == '__main__':
    unittest.main()
