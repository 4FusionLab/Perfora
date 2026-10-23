# SPDX-License-Identifier: GPL-3.0-only
import math
import unittest

from Perfora.geometry import (Cell, Settings, POLYGON_SHAPES, edges, fits, generate,
                                 outline_coordinates, rectangle_region, segment_distance)

NEW_SHAPES = ('triangle', 'rectangle', 'diamond', 'ellipse', 'pentagon', 'octagon', 'cross', 'star')


def area(points):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in edges(points))) / 2


class ShapeTests(unittest.TestCase):
    def test_new_polygon_dimensions_and_areas(self):
        expected = dict(triangle=math.sqrt(3), rectangle=12, diamond=6,
                        pentagon=5 * math.sin(math.tau / 5) / 2,
                        octagon=8 * math.tan(math.pi / 8), cross=1.75,
                        star=5 * 1 * 0.45 * math.sin(math.pi / 5))
        for shape, expected_area in expected.items():
            with self.subTest(shape=shape):
                c = Cell((0, 0), shape, 2, 6, 0, arm_width=0.5)
                self.assertAlmostEqual(area(c.vertices), expected_area)

    def test_rotated_new_shapes_keep_clearance_and_web(self):
        region = rectangle_region(4, 3)
        for shape in NEW_SHAPES:
            for angle in (0, 0.53, 1.11):
                with self.subTest(shape=shape, angle=angle):
                    s = Settings(shape=shape, size=0.5, slot_length=0.85, gap=0.12, margin=0.2,
                                 shape_angle=angle, grid_angle=0.24, star_points=7, star_ratio=0.4)
                    cells = generate(region, s)
                    self.assertGreater(len(cells), 2)
                    for cell in cells:
                        self.assertTrue(fits(cell, region, region.segments, s.margin))
                    # Near neighbours exercise real boundary distances; the
                    # ellipse polygon is inscribed so the bound allows its sag.
                    for i, cell in enumerate(cells):
                        points = cell.ellipse_points(48) if shape == 'ellipse' else cell.vertices
                        for other in cells[i + 1:]:
                            if math.dist(cell.center, other.center) > 1.8:
                                continue
                            other_points = other.ellipse_points(48) if shape == 'ellipse' else other.vertices
                            gap = min(segment_distance(a,b,c,d) for a,b in edges(points) for c,d in edges(other_points))
                            self.assertGreaterEqual(gap + 1e-7, s.gap)

    def test_new_outlines_are_closed_and_polygons_keep_vertices(self):
        for shape in NEW_SHAPES:
            with self.subTest(shape=shape):
                cell = Cell((1, -2), shape, 0.6, 1.2, 0.47)
                xyz = outline_coordinates([cell], rectangle_region(4, 4))
                pairs = [(xyz[i:i+3], xyz[i+3:i+6]) for i in range(0, len(xyz), 6)]
                self.assertGreater(len(pairs), 2)
                for i, (_, end) in enumerate(pairs):
                    self.assertEqual(end, pairs[(i+1) % len(pairs)][0])
                if shape in POLYGON_SHAPES:
                    self.assertEqual(len(pairs), len(cell.vertices))

    def test_shape_specific_parameters_are_validated(self):
        for kwargs in (dict(shape='cross',arm_width=0),dict(shape='cross',arm_width=0.5),
                       dict(shape='star',star_ratio=0.99),dict(shape='star',star_points=2),
                       dict(shape='star',star_ratio=float('nan')),dict(shape='ellipse',slot_length=0.4),
                       dict(shape='rectangle',slot_length=-1),dict(shape='diamond',slot_length=0)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Settings(**kwargs).validate()


if __name__ == '__main__':
    unittest.main()
