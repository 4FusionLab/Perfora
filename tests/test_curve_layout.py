# SPDX-License-Identifier: GPL-3.0-only
"""Offline numerical tests. Evaluators model documented API contracts, not Fusion CAD."""
from dataclasses import replace
import math
import time
import unittest

from Perfora.cache import GeometryCache
from Perfora.curve_layout import (MAX_SAMPLES, PATH_TOLERANCE, PLANE_TOLERANCE,
                                  path_distances, sample_path)
from Perfora.geometry import ORGANIC_SHAPES
from Perfora.geometry import (Loop, Region, Settings, SHAPE_IDS, dist, edges,
                             enclosing_radius, fits, generate, rectangle_region,
                             segment_distance)


class CubicLine:
    """Nonuniform parameterization: x=t^3-1, t in [1,2], length=7 cm."""
    def __init__(self):
        self.measured = []

    def getParameterExtents(self): return True, 1., 2.
    def getLengthAtParameter(self, a, b): return True, b**3-a**3
    def getParameterAtLength(self, start, length):
        self.measured.append(length)
        return True, (start**3+length)**(1/3)
    def getPointAtParameter(self, t): return True, (t**3-1, 0., 0.)
    def getFirstDerivative(self, t): return True, (3*t*t, 0., 0.)
    def getStrokes(self, a, b, tolerance):
        return True, [self.getPointAtParameter(a)[1], self.getPointAtParameter(b)[1]]


class Circle:
    def __init__(self, radius=2, sweep=math.tau):
        self.radius, self.sweep = radius, sweep
    def getParameterExtents(self): return True, 0., self.sweep
    def getLengthAtParameter(self, a, b): return True, (b-a)*self.radius
    def getParameterAtLength(self, start, length): return True, start+length/self.radius
    def getPointAtParameter(self, t):
        return True, (self.radius*math.cos(t), self.radius*math.sin(t), 0.)
    def getFirstDerivative(self, t):
        return True, (-self.radius*math.sin(t), self.radius*math.cos(t), 0.)
    def getStrokes(self, a, b, tolerance):
        n = math.ceil((b-a)/(2*math.acos(1-tolerance/self.radius)))
        return True, [self.getPointAtParameter(a+(b-a)*i/n)[1] for i in range(n+1)]


def resolve(evaluator, settings, closed=False, project=lambda p: p, vector=lambda v: v):
    return replace(settings, path_samples=sample_path(evaluator, settings, project, vector, closed))


class CurveLayoutTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(layout='path', size=.3, gap=.1, margin=.05, path_spacing=.7)
        self.region = rectangle_region(20, 20)

    def test_nonuniform_parameters_use_true_arc_lengths(self):
        curve = CubicLine()
        s = resolve(curve, self.settings)
        self.assertEqual(len(s.path_samples), 11)
        self.assertEqual(curve.measured, [.7*i for i in range(1, 10)])
        for i, (x,y,_) in enumerate(s.path_samples):
            self.assertAlmostEqual(x, i*.7)
            self.assertEqual(y, 0)
        # Uniform t increments would create unequal x increments.
        self.assertNotAlmostEqual((1.1**3-1), .7)

    def test_offsets_position_and_reverse_measure_from_chosen_end(self):
        s = replace(self.settings, path_start=.2, path_end=.4, path_position=.3, path_spacing=1)
        self.assertEqual(path_distances(7, False, s), (.5,1.5,2.5,3.5,4.5,5.5,6.5))
        forward = resolve(CubicLine(), s).path_samples
        reverse = resolve(CubicLine(), replace(s,path_reverse=True)).path_samples
        for a,b in zip(forward, reverse):
            self.assertAlmostEqual(a[0]+b[0], 7)
        single = replace(s,path_start=7,path_end=0,path_position=0)
        self.assertEqual(path_distances(7, False, single), (7,))

    def test_closed_seam_is_exclusive_with_no_duplicate_centers(self):
        curve = Circle()
        s = resolve(curve, replace(self.settings, path_spacing=math.tau*2/12), True)
        cells = generate(self.region, s)
        self.assertEqual(len(cells), 12)
        self.assertEqual(len(set(c.center for c in cells)), 12)
        self.assertGreater(dist(cells[-1].center, cells[0].center), s.size+s.gap)
        reverse = resolve(curve, replace(self.settings, path_spacing=math.tau*2/12, path_reverse=True), True)
        self.assertEqual(len(generate(self.region,reverse)),12)
        cropped = replace(self.settings,path_start=1,path_end=1,path_position=.1,path_spacing=1)
        positions = path_distances(math.tau*2,True,cropped)
        self.assertAlmostEqual(positions[0],1.1)
        self.assertLess(positions[-1],math.tau*2-1)

    def test_closed_seam_gap_and_chord_are_checked(self):
        # Arc spacing exceeds size+gap, but the chord does not.
        curve = Circle(radius=.3)
        s = resolve(curve, replace(self.settings,size=.27,gap=.025,path_spacing=.3),True)
        with self.assertRaisesRegex(ValueError,'Web Thickness'):
            generate(self.region,s)
        # Long loop: only the short closing residual violates the web.
        curve = Circle(radius=2)
        s = resolve(curve, replace(self.settings,size=.4,path_spacing=1.03),True)
        self.assertGreater(dist(s.path_samples[0][:2],s.path_samples[1][:2]),.5)
        with self.assertRaisesRegex(ValueError,'closing seam'):
            generate(self.region,s)

    def test_tangent_and_fixed_angles_include_hole_angle_and_reverse(self):
        curve = Circle(sweep=math.pi)
        for reverse in (False,True):
            s = resolve(curve,replace(self.settings,shape='slot',slot_length=.6,path_spacing=1,
                                     path_orientation='tangent',shape_angle=.21,path_reverse=reverse))
            for cell in generate(self.region,s):
                expected = math.atan2(cell.center[1],cell.center[0])+math.pi/2+.21+(math.pi if reverse else 0)
                self.assertAlmostEqual(math.remainder(cell.angle-expected,math.tau),0)
        fixed = resolve(curve,replace(self.settings,shape='square',shape_angle=.3))
        self.assertTrue(all(c.angle == .3 for c in generate(self.region,fixed)))

    def test_all_repeating_shapes_preserve_true_web_in_both_orientations(self):
        for shape in (s for s in SHAPE_IDS if s not in ORGANIC_SHAPES):
            if shape == 'voronoi': continue
            for orientation in ('fixed','tangent'):
                with self.subTest(shape=shape,orientation=orientation):
                    base = replace(self.settings,shape=shape,slot_length=.6,path_orientation=orientation,shape_angle=.31)
                    base = replace(base,path_spacing=2*enclosing_radius(base)+base.gap+.03)
                    cells = generate(self.region,resolve(CubicLine(),base))
                    for a,b in zip(cells,cells[1:]):
                        self.assertGreaterEqual(dist(a.center,b.center)+1e-9,2*enclosing_radius(base)+base.gap)
                    self.assertGreater(len(cells),2)

    def test_nonadjacent_sections_and_self_intersections_are_checked(self):
        for tail in ((.1,.1,0), (0,0,0)):
            samples = ((0,0,0),(1,0,0),(1,1,0),(0,1,0),tail)
            with self.assertRaisesRegex(ValueError,'nearby section'):
                generate(self.region,replace(self.settings,path_samples=samples))

    def test_boundary_void_margin_and_partial_candidates(self):
        samples = tuple((x*.5,0.,0.) for x in range(-8,9))
        region = Region((rectangle_region(4,3).loops[0],Loop(rectangle_region(.6,.6).loops[0].points,False)))
        s = replace(self.settings,path_samples=samples,margin=.15)
        whole = generate(region,s)
        self.assertTrue(all(fits(c,region,region.segments,s.margin) for c in whole))
        trimmed = generate(region,replace(s,clip_boundary=True))
        self.assertTrue(set(whole).issubset(set(trimmed)))
        self.assertTrue(any(not fits(c,region,region.segments,s.margin) for c in trimmed))
        self.assertFalse(any(c.center == (0,0) for c in trimmed))

    def test_planarity_rejects_interior_excursion_even_with_planar_endpoints(self):
        class Nonplanar(CubicLine):
            def getStrokes(self,a,b,tol): return True,[(0,0,0),(3,0,.01),(7,0,0)]
        with self.assertRaisesRegex(ValueError,'Profiles plane'):
            resolve(Nonplanar(),self.settings)
        with self.assertRaisesRegex(ValueError,'Profiles plane'):
            resolve(CubicLine(),self.settings,project=lambda p:(p[0],p[1],.01))

    def test_rotated_translated_frame_preserves_positions_and_vectors(self):
        # Adapter projects component-space geometry through the explicit plane basis.
        angle=.61
        c,s=math.cos(angle),math.sin(angle)
        project=lambda p:(7+c*p[0],-9+s*p[0],0)
        vector=lambda v:(c*v[0],s*v[0],0)
        settings=resolve(CubicLine(),replace(self.settings,path_orientation='tangent'),project=project,vector=vector)
        for i,(x,y,a) in enumerate(settings.path_samples):
            self.assertAlmostEqual(x,7+c*i*.7)
            self.assertAlmostEqual(y,-9+s*i*.7)
            self.assertAlmostEqual(a,angle)

    def test_zero_length_singular_tangent_and_solver_failures(self):
        class Zero(CubicLine):
            def getLengthAtParameter(self,a,b): return True,0.
        class Singular(CubicLine):
            def getFirstDerivative(self,t): return True,(0,0,0)
        class Failed(CubicLine):
            def getParameterAtLength(self,a,b): return False,0.
        class Infinite(CubicLine):
            def getPointAtParameter(self,t): return True,(float('inf'),0,0)
        for curve in (Zero(),Failed(),Infinite()):
            with self.subTest(curve=curve),self.assertRaises(ValueError): resolve(curve,self.settings)
        with self.assertRaisesRegex(ValueError,'singular'):
            resolve(Singular(),replace(self.settings,path_orientation='tangent'))
        self.assertTrue(resolve(Singular(),self.settings).path_samples)  # Fixed needs no tangent.

    def test_inconsistent_closed_flag_and_unbounded_geometry_fail(self):
        with self.assertRaisesRegex(ValueError,'seam'):
            resolve(CubicLine(),self.settings,closed=True)
        class Unbounded(CubicLine):
            def getParameterExtents(self): return False,0,0
        with self.assertRaisesRegex(ValueError,'bounded'):
            resolve(Unbounded(),self.settings)

    def test_density_count_empty_path_and_nonfinite_inputs_are_bounded(self):
        for change in (dict(path_spacing=0),dict(path_spacing=-1),dict(path_spacing=math.nan),
                       dict(path_start=-1),dict(path_end=math.inf),dict(path_position=-1),
                       dict(path_orientation='radial'),dict(shape='voronoi'),dict(grid_angle=.1),
                       dict(offset_y=.1),dict(spread_radius=1),dict(origin_x=0,origin_y=0)):
            with self.subTest(change=change),self.assertRaises(ValueError): replace(self.settings,**change).validate()
        for s in (replace(self.settings,path_spacing=1e-300),replace(self.settings,path_start=8),
                  replace(self.settings,path_end=9),replace(self.settings,path_start=1e308,path_position=1e308)):
            with self.assertRaises(ValueError): path_distances(7,False,s)
        with self.assertRaisesRegex(ValueError,'Select one Path'): generate(self.region,self.settings)
        samples=resolve(CubicLine(),self.settings).path_samples
        with self.assertRaisesRegex(ValueError,'Maximum Holes'):
            generate(self.region,replace(self.settings,path_samples=samples,limit=2))
        with self.assertRaises(ValueError): generate(self.region,replace(self.settings,path_samples=((math.nan,0,0),)))
        with self.assertRaises(ValueError): generate(self.region,replace(self.settings,path_samples=((100,100,0),)))

    def test_path_changes_invalidate_geometry_cache_and_failed_result_is_not_published(self):
        s=resolve(CubicLine(),self.settings)
        cache=GeometryCache()
        cells=cache.resolve(self.region,s,('frame',))
        self.assertIs(cache.resolve(self.region,replace(s),('frame',)),cells)
        for changed in (replace(s,path_samples=tuple((x,y+.1,a) for x,y,a in s.path_samples)),
                        replace(s,path_orientation='tangent'),replace(s,shape_angle=.4)):
            before=cache.misses
            cache.resolve(self.region,changed,('frame',))
            self.assertEqual(cache.misses,before+1)
        before=cache.prepared
        with self.assertRaises(ValueError): cache.resolve(self.region,replace(s,path_samples=((0,0,0),(0,0,0))))
        self.assertIs(cache.prepared,before)

    def test_large_path_uses_bounded_pair_checks(self):
        s=replace(self.settings,path_samples=tuple((i*.7,0,0) for i in range(5000)),limit=5000)
        started=time.perf_counter()
        cells=generate(rectangle_region(8000,2),s)
        self.assertEqual(len(cells),5000)
        # Generous regression guard against accidentally comparing all 12.5M pairs.
        self.assertLess(time.perf_counter()-started,5)


if __name__ == '__main__': unittest.main()
