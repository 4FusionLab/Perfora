# SPDX-License-Identifier: GPL-3.0-only
"""Offline contracts; these do not establish Fusion CAD/UI acceptance."""
from dataclasses import replace
import math
import unittest
from Perfora.geometry import ORGANIC_SHAPES
from Perfora.geometry import (Settings, Loop, Region, SHAPE_IDS, VARIANT_LAYOUTS,
                              rectangle_region, disk_region, generate, dist, fits,
                              enclosing_radius, edges, segment_distance, rotate)
from Perfora.curves import ArcPath, prepare_guides
from Perfora.cache import GeometryCache
from Perfora.distributions import SeparationIndex

GUIDES = (((-1.6,-.8), (0,-.5), (1.6,-.8)),
          ((-1.6,.8), (0,1), (1.6,.8)))


def settings(layout, **kw):
    return replace(Settings(layout=layout, size=.28, gap=.12, margin=.08,
                            slot_length=.5, arm_width=.1, limit=5000,
                            contour_tolerance=.045, guide1=GUIDES[0], guide2=GUIDES[1]), **kw)


class VariantGeometryTests(unittest.TestCase):
    def test_all_distributions_and_rotated_real_shapes_keep_web(self):
        region = rectangle_region(4,3)
        for layout in VARIANT_LAYOUTS:
            for shape in (s for s in SHAPE_IDS if s not in ORGANIC_SHAPES):
                if shape == 'voronoi':
                    continue
                with self.subTest(layout=layout, shape=shape):
                    s = settings(layout, shape=shape, shape_angle=.63, grid_angle=.29)
                    cells = generate(region,s)
                    self.assertGreater(len(cells),2)
                    self.assertEqual(cells,generate(region,s))
                    safe = 2*enclosing_radius(s)+s.gap
                    for i,a in enumerate(cells):
                        self.assertTrue(fits(a,region,region.segments,s.margin))
                        for b in cells[i+1:]:
                            self.assertGreaterEqual(dist(a.center,b.center)+1e-8,safe)
                    # Inspect actual nearby shape contours as well as the bound.
                    for a,b in sorted(((a,b) for i,a in enumerate(cells) for b in cells[i+1:]),
                                      key=lambda ab: dist(ab[0].center,ab[1].center))[:4]:
                        if shape in ('circle','slot'):
                            gap = segment_distance(*a.spine,*b.spine)-s.size
                        else:
                            p = a.ellipse_points(48) if shape == 'ellipse' else a.vertices
                            q = b.ellipse_points(48) if shape == 'ellipse' else b.vertices
                            gap = min(segment_distance(c,d,e,f) for c,d in edges(p) for e,f in edges(q))
                        self.assertGreaterEqual(gap+1e-8,s.gap)

    def test_trim_candidates_preserve_whole_result_and_clearance_with_void(self):
        outer = rectangle_region(4,3).loops[0]
        void = Loop(((-.4,-.4),(.4,-.4),(.4,.4),(-.4,.4)),False)
        region = Region((outer,void))
        for layout in VARIANT_LAYOUTS:
            with self.subTest(layout=layout):
                s = settings(layout)
                whole = generate(region,s)
                trim = generate(region,replace(s,clip_boundary=True))
                self.assertTrue(set(whole).issubset(set(trim)))
                self.assertTrue(all(fits(c,region,region.segments,s.margin) for c in whole))
                if layout not in ('contour','between_curves'):
                    self.assertTrue(any(not fits(c,region,region.segments,0) for c in trim))

    def test_fan_no_duplicate_center_closed_sector_or_web_failure(self):
        s = settings('fan',fan_angle=math.tau,fan_rays=24,origin_x=0,origin_y=0)
        cells = generate(rectangle_region(5,5),s)
        self.assertEqual(sum(dist(c.center,(0,0)) < 1e-8 for c in cells),1)
        self.assertEqual(len({c.center for c in cells}),len(cells))
        for c in generate(rectangle_region(5,5),replace(s,start_radius=.7,fan_angle=math.pi/2)):
            self.assertGreaterEqual(math.hypot(*c.center),.7-1e-9)
            self.assertGreaterEqual(c.center[0],-1e-8)
            self.assertGreaterEqual(c.center[1],-1e-8)
        stepped = generate(rectangle_region(5,5),replace(s,fan_angular_step=math.pi/4))
        for c in stepped:
            if math.hypot(*c.center) > 1e-8:
                self.assertAlmostEqual(math.remainder(math.atan2(c.center[1],c.center[0]),math.pi/4),0)

    def test_phyllotaxis_keeps_golden_angle_and_density_changes_field(self):
        s = settings('phyllotaxis')
        region = disk_region(4,tolerance=.01)
        cells = generate(region,s)
        scale = (2*enclosing_radius(s)+s.gap+2e-9)/(1.5*math.sqrt(s.phyllotaxis_density))
        golden = math.pi*(3-math.sqrt(5))
        for c in cells:
            n = round((math.hypot(*c.center)/scale)**2-.5)
            self.assertAlmostEqual(math.remainder(math.atan2(c.center[1],c.center[0])-n*golden,math.tau),0,places=8)
        self.assertNotEqual(cells,generate(region,replace(s,phyllotaxis_density=.6)))

    def test_poisson_seed_and_offsets_change_random_field(self):
        region = rectangle_region(5,4)
        s = settings('poisson')
        a = generate(region,s)
        for change in (dict(seed=2),dict(offset_x=.2),dict(origin_x=.3,origin_y=.4)):
            self.assertNotEqual(a,generate(region,replace(s,**change)))
        for i,c in enumerate(a):
            self.assertTrue(all(dist(c.center,d.center)>=s.size+s.gap-1e-8 for d in a[i+1:]))
        self.assertTrue(all(c.shape=='circle' and not c.polygon for c in a))

    def test_wave_samples_length_instead_of_x_and_applies_row_phase(self):
        s = settings('wave', row_spacing=10,wave_amplitude=.5,wave_length=1.8,wave_phase=.3)
        a = generate(rectangle_region(6,4),s)
        self.assertGreater(len(a),5)
        for c in a:
            x,y = c.center
            self.assertAlmostEqual(y,s.wave_amplitude*math.sin(math.tau*x/s.wave_length+s.wave_phase),delta=.001)
        self.assertNotEqual(generate(rectangle_region(5,4),settings('wave')),
                            generate(rectangle_region(5,4),settings('wave',wave_row_phase=.7)))
        # ArcPath spaces by accumulated length, including highly unequal segments.
        path = ArcPath(((0,0),(1,0),(1,4)))
        self.assertEqual(path.spaced(1),[(0,0),(1,0),(1,1),(1,2),(1,3),(1,4)])

    def test_chevron_vertex_once_and_running_bond_fractions(self):
        region=rectangle_region(5,4)
        cells=generate(region,settings('chevron'))
        vertices=[c.center for c in cells if abs(c.center[0])<1e-8]
        self.assertGreater(len(vertices),1)
        self.assertEqual(len(set(vertices)),len(vertices))
        for fraction in (1/3,1/4,.5):
            s=settings('running_bond',bond_shift=fraction)
            step=2*enclosing_radius(s)+s.gap+2e-9
            for c in generate(region,s):
                row=round(c.center[1]/step)
                self.assertAlmostEqual(math.remainder(c.center[0]/step-row*fraction,1),0,places=8)

    def test_contour_branches_vanish_close_and_respect_inner_loop(self):
        neck=((-3,-1.5),(-.8,-1.5),(-.8,-.4),(.8,-.4),(.8,-1.5),(3,-1.5),
              (3,1.5),(.8,1.5),(.8,.4),(-.8,.4),(-.8,1.5),(-3,1.5))
        region=Region((Loop(neck),))
        s=settings('contour',margin=.02,contour_tolerance=.04)
        cells=generate(region,s)
        self.assertTrue(any(c.center[0]<-1 for c in cells))
        self.assertTrue(any(c.center[0]>1 for c in cells))
        self.assertEqual(len(cells),len(set(c.center for c in cells)))
        self.assertTrue(all(fits(c,region,region.segments,s.margin) for c in cells))
        ring=Region((disk_region(4,.02).loops[0],Loop(disk_region(1,.02).loops[0].points,False)))
        self.assertTrue(all(fits(c,ring,ring.segments,.08) for c in generate(ring,settings('contour'))))

    def test_between_direction_matching_open_curves_and_strip_failures(self):
        s=settings('between_curves')
        region=rectangle_region(4,3)
        self.assertEqual(generate(region,s),generate(region,replace(s,guide2=tuple(reversed(s.guide2)))))
        xx=[-1.7+i*3.4/64 for i in range(65)]
        a=tuple((x,-.8+.17*math.sin(x)) for x in xx)
        b=tuple((x,.8+.2*math.sin(x+.5)) for x in xx)
        # Unequal normalized vertex fractions can make adjacent connectors
        # closer than stroke tolerance without an actual fold.
        self.assertGreater(len(generate(region,replace(s,guide1=a,guide2=b))),10)
        invalid = [(((0,0),(0,0)),((0,1),(1,1))),
                   (((0,0),(1,1)),((0,1),(1,0))),
                   (((0,0),(1,0),(0,0)),((0,1),(1,1))),
                   (((0,0),(1,1),(0,1),(1,0)),((0,2),(1,2))),
                   (((0,0),(float('nan'),0)),((0,1),(1,1))),
                   (((0,0),(1,0)),((0,0),(1,1)))]
        for a,b in invalid:
            with self.subTest(a=a,b=b), self.assertRaises(ValueError):
                prepare_guides(a,b)
        with self.assertRaises(ValueError):
            prepare_guides(((0,0),(2,0)),((0,1),(2,1)),reverse=True)

    def test_cache_tracks_guides_and_parameters_and_isolation(self):
        region=rectangle_region(4,3)
        cache=GeometryCache()
        s=settings('between_curves')
        a=cache.resolve(region,s)
        self.assertIs(a,cache.resolve(region,replace(s)))
        b=cache.resolve(region,replace(s,guide2=tuple((x,y+.1) for x,y in s.guide2)))
        self.assertNotEqual(a,b)
        self.assertEqual(cache.misses,2)
        cache.clear()
        self.assertIsNone(cache.prepared)
        for layout in VARIANT_LAYOUTS:
            s=settings(layout,spread_radius=1.1)
            for c in generate(region,s):
                points = c.ellipse_points(enclosing=True) if c.shape=='ellipse' else c.vertices
                self.assertLessEqual(math.hypot(*c.center)+enclosing_radius(s)+s.margin,1.1+1e-8)

    def test_validation_density_guards_and_voronoi_rejection(self):
        bad=[('fan',dict(fan_rays=2.5)),('fan',dict(fan_angle=0)),('fan',dict(start_radius=-1)),
             ('fan',dict(fan_angular_step=-1)),('wave',dict(wave_length=0)),
             ('wave',dict(wave_amplitude=-1)),('chevron',dict(chevron_angle=math.pi/2)),
             ('running_bond',dict(bond_shift=2)),('phyllotaxis',dict(phyllotaxis_density=0)),
             ('poisson',dict(seed=-1)),('contour',dict(contour_tolerance=0)),
             ('between_curves',dict(guide_rows=1)),('between_curves',dict(guide_rows=2.5))]
        for layout,kw in bad:
            with self.subTest(layout=layout,kw=kw),self.assertRaises(ValueError):
                settings(layout,**kw).validate()
        for layout in VARIANT_LAYOUTS:
            with self.subTest(layout=layout),self.assertRaises(ValueError):
                settings(layout,shape='voronoi').validate()
            with self.subTest(layout=layout),self.assertRaises(ValueError):
                generate(rectangle_region(4,3),settings(layout,limit=1))
        for layout in ('fan','phyllotaxis','poisson','wave','chevron','running_bond'):
            with self.subTest(layout=layout),self.assertRaises(ValueError):
                generate(rectangle_region(1000,1000),settings(layout,size=.001,gap=.0001))
            with self.subTest(layout=layout,case='remote anchor'),self.assertRaises(ValueError):
                generate(rectangle_region(4,3),settings(layout,offset_x=1e308))
        with self.assertRaises(ValueError):
            generate(rectangle_region(4,3),settings('fan',fan_angular_step=1e-320))
        with self.assertRaisesRegex(ValueError,'sampling budget'):
            generate(rectangle_region(4,3),settings('contour',contour_tolerance=.000001))

    def test_spatial_index_examines_only_neighbour_buckets(self):
        index=SeparationIndex(1)
        self.assertTrue(all(index.accept((i*2,j*2)) for i in range(100) for j in range(100)))
        self.assertFalse(index.accept((100.1,100)))
        self.assertEqual(len(index.buckets),10000)


if __name__=='__main__':
    unittest.main()
