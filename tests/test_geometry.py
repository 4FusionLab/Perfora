# SPDX-License-Identifier: GPL-3.0-only
import math
import random
import unittest

from Perfora.geometry import (Cell, Loop, Region, Settings, disk_region, fits, generate,
                                 pitch, point_segment_distance, rectangle_region, rotate, stitch)


class GeometryTests(unittest.TestCase):
    def test_exact_edge_offset_keeps_whole_cells_without_extra_clearance(self):
        region=rectangle_region(5,5)
        for shape in ('circle','slot','square'):
            for x,expected in ((-1.95,True),(-1.95+1e-5,True),(-1.95-1e-5,False)):
                with self.subTest(shape=shape,x=x):
                    cell=Cell((x,0),shape,.5,.5,0)
                    self.assertEqual(fits(cell,region,region.segments,.3),expected)

    def test_touching_source_boundary_is_not_a_crossing(self):
        region=rectangle_region(5,5)
        for shape in ('circle','square'):
            with self.subTest(shape=shape):
                self.assertTrue(fits(Cell((-2.25,0),shape,.5,.5,0),region,region.segments,0))
                self.assertFalse(fits(Cell((-2.25001,0),shape,.5,.5,0),region,region.segments,0))

    def test_clipped_candidates_include_centres_outside_boundary(self):
        region = rectangle_region(2, 2)
        cells = generate(region, Settings(shape='hexagon', size=1, gap=0.2, margin=0.2,
                                         staggered=False, offset_x=0.5, clip_boundary=True))
        self.assertTrue(any(not region.contains(c.center) for c in cells))
        self.assertTrue(any(not fits(c, region, region.segments, 0) for c in cells))

    def test_clip_checkbox_off_preserves_whole_cell_mode(self):
        region = rectangle_region(5, 4)
        whole = generate(region, Settings(shape='hexagon', margin=0.3))
        clipped = generate(region, Settings(shape='hexagon', margin=0.3, clip_boundary=True))
        self.assertGreater(len(clipped), len(whole))
        self.assertTrue(all(fits(c, region, region.segments, 0.3) for c in whole))

    def test_circle_margin_and_neighbor_web(self):
        settings = Settings(size=0.5, gap=0.15, margin=0.3)
        cells = generate(rectangle_region(8, 6), settings)
        self.assertGreater(len(cells), 40)
        for i, cell in enumerate(cells):
            x, y = cell.center
            self.assertGreaterEqual(4 - abs(x) - cell.size / 2, settings.margin)
            self.assertGreaterEqual(3 - abs(y) - cell.size / 2, settings.margin)
            for other in cells[i + 1:]:
                self.assertGreaterEqual(math.dist(cell.center, other.center) - cell.size + 1e-8, settings.gap)

    def test_circle_boundary_is_respected_analytically(self):
        settings = Settings(size=0.3, margin=0.2, gap=0.1, grid_angle=0.71)
        for cell in generate(disk_region(4), settings):
            self.assertLessEqual(math.hypot(*cell.center) + settings.size / 2 + settings.margin, 2)

    def test_all_shapes_respect_rotated_rectangle(self):
        random.seed(21)
        for shape in ('circle', 'hexagon', 'square', 'slot'):
            for _ in range(6):
                s = Settings(shape=shape, size=0.4, slot_length=0.9, gap=0.15, margin=0.21,
                             grid_angle=random.uniform(-math.pi, math.pi), shape_angle=random.uniform(-1, 1))
                cells = generate(rectangle_region(6, 4), s)
                for cell in cells:
                    if shape in ('square', 'hexagon'):
                        points, radius = cell.vertices, 0
                    else:
                        points, radius = cell.spine, s.size / 2
                    for x, y in points:
                        self.assertLessEqual(abs(x) + radius + s.margin, 3)
                        self.assertLessEqual(abs(y) + radius + s.margin, 2)

    def test_concavity_does_not_allow_bridging_notch(self):
        # A large square has all four vertices inside this U but bridges its notch.
        loop = Loop(((0, 0), (4, 0), (4, 4), (3, 4), (3, 1), (1, 1), (1, 4), (0, 4)))
        region = Region((loop,))
        cell = Cell((2, 2), 'square', 3.8, 3.8, 0)
        self.assertFalse(fits(cell, region, region.segments, 0))

    def test_cell_cannot_enclose_small_existing_void(self):
        outer = rectangle_region(6, 6).loops[0]
        void = Loop(((0.5, 0.5), (0.6, 0.5), (0.6, 0.6), (0.5, 0.6)), False)
        region = Region((outer, void))
        for shape in ('circle', 'square', 'hexagon', 'slot'):
            cell = Cell((0, 0), shape, 2, 3, 0)
            self.assertFalse(fits(cell, region, region.segments, 0))

    def test_annulus_leaves_clearance_around_inner_void(self):
        outer = disk_region(6).loops[0]
        inner = disk_region(2).loops[0]
        region = Region((outer, Loop(inner.points, False)))
        s = Settings(size=0.3, gap=0.2, margin=0.15)
        cells = generate(region, s)
        for cell in cells:
            self.assertGreaterEqual(math.hypot(*cell.center) - s.size / 2, 1 + s.margin - 0.0001)

    def test_slot_detects_middle_crossing_hole(self):
        outer = rectangle_region(8, 8).loops[0]
        void = Loop(((0.4, -0.1), (0.6, -0.1), (0.6, 0.1), (0.4, 0.1)), False)
        region = Region((outer, void))
        cell = Cell((0, 0), 'slot', 0.3, 3, 0)
        self.assertFalse(fits(cell, region, region.segments, 0.1))

    def test_stitch_accepts_reordered_and_reversed_edges(self):
        paths = [((1, 0), (1, 1)), ((0, 0), (0, 1)), ((1, 1), (0, 1)), ((0, 0), (1, 0))]
        polygon = stitch(paths, 1e-6)
        self.assertEqual(set(polygon), {(0, 0), (0, 1), (1, 0), (1, 1)})

    def test_stitch_refuses_open_boundary(self):
        with self.assertRaises(ValueError):
            stitch([((0, 0), (1, 0)), ((1, 0), (1, 1))], 1e-6)

    def test_limit_rejects_instead_of_silently_truncating(self):
        with self.assertRaisesRegex(ValueError, 'limit'):
            generate(rectangle_region(8, 6), Settings(limit=2))

    def test_extreme_density_is_bounded(self):
        with self.assertRaisesRegex(ValueError, 'dense'):
            generate(rectangle_region(100, 100), Settings(size=0.001, gap=0.001))

    def test_invalid_parameters_and_no_fit(self):
        for args in ({'size': 0}, {'gap': -1}, {'margin': -1}, {'shape': 'unknown'},
                     {'shape': 'slot', 'size': 2, 'slot_length': 1}, {'size': float('nan')}):
            with self.assertRaises(ValueError):
                generate(rectangle_region(8, 6), Settings(**args))
        with self.assertRaisesRegex(ValueError, 'No holes fit'):
            generate(rectangle_region(0.1, 0.1), Settings())

    def test_large_offsets_are_periodic_and_remain_bounded(self):
        a = generate(rectangle_region(8, 6), Settings(offset_x=1000000, offset_y=-1000000))
        self.assertGreater(len(a), 20)

    def test_hexagonal_lattice_has_requested_flat_to_flat_gap(self):
        s = Settings(shape='hexagon', size=0.6, gap=0.12)
        sx, sy = pitch(s)
        self.assertAlmostEqual(sx - s.size, s.gap)
        self.assertAlmostEqual(math.hypot(sx / 2, sy), sx)

    def test_rotated_square_cells_cannot_overlap(self):
        from Perfora.geometry import segment_distance, edges
        s = Settings(shape='square', size=0.5, shape_angle=0.73, gap=0.12)
        cells = generate(rectangle_region(4, 3), s)
        for i, cell in enumerate(cells):
            for other in cells[i + 1:]:
                distance = min(segment_distance(a, b, c, d) for a, b in edges(cell.vertices)
                               for c, d in edges(other.vertices))
                self.assertGreaterEqual(distance + 1e-8, s.gap)

    def test_preview_outlines_are_closed_and_match_hexagon_size(self):
        from Perfora.geometry import outline_coordinates
        cell = Cell((2, -1), 'hexagon', 0.6, 0.6, 0.43)
        coordinates = outline_coordinates([cell], rectangle_region(8, 6))
        self.assertEqual(len(coordinates), 6 * 2 * 3)
        segments = [(tuple(coordinates[i:i + 3]), tuple(coordinates[i + 3:i + 6]))
                    for i in range(0, len(coordinates), 6)]
        for i, (a, b) in enumerate(segments):
            self.assertEqual(b, segments[(i + 1) % 6][0])
            self.assertAlmostEqual(math.dist(a, b), 0.6 / math.sqrt(3))

    def test_slot_preview_uses_full_length_and_width(self):
        from Perfora.geometry import outline_coordinates
        coordinates = outline_coordinates([Cell((0, 0), 'slot', 0.4, 1.2, 0)], rectangle_region(8, 6))
        xs, ys = coordinates[0::3], coordinates[1::3]
        self.assertAlmostEqual(max(xs) - min(xs), 1.2)
        self.assertAlmostEqual(max(ys) - min(ys), 0.4)


if __name__ == '__main__':
    unittest.main()
