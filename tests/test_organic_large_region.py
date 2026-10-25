# SPDX-License-Identifier: GPL-3.0-only
"""Large planar-source regression matching the Box side-face chart size."""
import unittest
from Perfora import geometry as g, organic


class LargeOrganicRegionTests(unittest.TestCase):
    def test_default_scale_builds_on_box_sized_source(self):
        cells=g.generate(g.rectangle_region(9.,24.5),g.Settings(shape='smooth_noise',clip_boundary=True))
        self.assertGreater(len(cells),0)
        self.assertTrue(all(c.contour for c in cells))

    def test_sampling_remains_bounded_and_preserves_small_source_resolution(self):
        h,nx,ny=organic.field_grid(11.,26.5,.5)
        self.assertLessEqual(nx*ny,organic.MAX_NODES)
        self.assertLessEqual(h,.5/8)
        self.assertEqual(organic.field_grid(4.,3.,.5)[0],.5/16)
        with self.assertRaisesRegex(ValueError,'sampling budget'):
            organic.field_grid(102.,102.,.5)
