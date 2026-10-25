# SPDX-License-Identifier: GPL-3.0-only
"""Offline acceptance candidates: visual topology and independent clearances."""
import math
import unittest
from dataclasses import replace
from studies.distribution_v2 import generate, minimum_gap
from studies.source_fixtures import distribution_registry
from Perfora.geometry import rectangle_region, fits, segment_distance, generate as kernel_generate
NAMES=tuple(key for key,label in distribution_registry())


class DistributionStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples={(n,s,o):generate(n,s,orientation=o) for n in NAMES
                     for s,o in (('circle','fixed'),('slot','fixed'),('slot','tangent'))}

    def test_exact_all_pairs_clearance_and_boundary_for_every_demo(self):
        # Exhaustive independent check also catches broad-phase false negatives.
        for key,a in self.samples.items():
            with self.subTest(key=key):
                self.assertGreater(len(a.cells),20)
                exact=min(segment_distance(*c.spine,*b.spine)-(c.size+b.size)/2
                          for i,c in enumerate(a.cells) for b in a.cells[i+1:])
                self.assertGreaterEqual(exact,a.settings.gap-1e-8)
                self.assertAlmostEqual(exact,a.gap,places=8)
                self.assertTrue(all(fits(c,a.region,a.region.segments,a.settings.margin) for c in a.cells))

    def test_regeneration_is_deterministic(self):
        for n in NAMES:
            self.assertEqual(self.samples[n,'circle','fixed'].cells,generate(n,orientation='fixed').cells)

    def test_fan_never_loses_an_internal_radial_station(self):
        a=self.samples['fan','slot','tangent']
        rays={}
        for c in a.cells:
            x,y=c.center[0],c.center[1]+4.35
            angle=round(math.atan2(y,x),8)
            rays.setdefault(angle,[]).append(math.hypot(x,y))
        starts=[]
        for radii in rays.values():
            radii.sort()
            starts.append(radii[0])
            for x,y in zip(radii,radii[1:]):
                self.assertAlmostEqual(y-x,(a.settings.slot_length+a.settings.gap)*a.scale,places=7)
        self.assertEqual(len(rays),25)
        self.assertLess(max(starts)-min(starts),1e-8)

    def test_phyllotaxis_preserves_every_vogel_index(self):
        a=self.samples['phyllotaxis','circle','fixed']
        c=(a.settings.size+a.settings.gap)*a.scale/1.5
        indices=[round((math.hypot(*hole.center)/c)**2-.5) for hole in a.cells]
        self.assertEqual(indices,list(range(len(indices))))

    def test_wave_boundary_crop_does_not_move_or_rephase_interior_holes(self):
        from studies.distribution_v2 import _draft
        a=self.samples['wave','slot','tangent']
        small=rectangle_region(8,6)
        factor=a.scale/ (a.settings.along_spacing/(a.settings.slot_length+a.settings.gap))
        b,_=_draft('wave',small,a.settings,factor,'tangent')
        expected=[c for c in a.cells if fits(c,small,small.segments,a.settings.margin)]
        rounded=lambda cells:[(tuple(round(v,7) for v in c.center),round(c.angle,7)) for c in cells]
        self.assertEqual(rounded(b),rounded(expected))

    def test_between_curves_keeps_common_column_count(self):
        a=self.samples['between_curves','slot','tangent']
        s=replace(a.settings,guide1=((-5,-2),(5,-2)),guide2=((-5,2),(5,2)))
        cells=kernel_generate(a.region,s)
        counts={}
        for c in cells:
            counts[round(c.center[0],8)]=counts.get(round(c.center[0],8),0)+1
        self.assertEqual(len(set(counts.values())),1)
        self.assertGreater(len(counts),10)

    def test_native_registry_is_complete_and_public_kernel_is_identical(self):
        self.assertEqual(set(NAMES),{n for n,_,_ in self.samples})
        for key,a in self.samples.items():
            with self.subTest(key=key):
                self.assertEqual(a.cells,kernel_generate(a.region,a.settings))

    def test_legacy_revision_remains_the_default(self):
        from Perfora.geometry import Settings
        from Perfora.distributions import generate_variant
        from Perfora.feature_data import metadata
        s=Settings(layout='chevron',size=.25,gap=.12,limit=5000)
        region=rectangle_region(6,4)
        self.assertEqual(s.distribution_revision,1)
        self.assertEqual(kernel_generate(region,s),generate_variant(region,s))
        new=self.samples['chevron','slot','tangent'].settings
        encoded=metadata(new,{'bodies':[]})['settings']
        self.assertEqual(encoded['distribution_revision'],2)
        self.assertEqual(encoded['layout_orientation'],'tangent')

    def test_revised_fields_follow_translated_rotated_source(self):
        from Perfora.geometry import rotate,Region,Loop
        for name in ('wave','chevron','between_curves'):
            a=self.samples[name,'slot','tangent']
            angle=.43
            def transform(p):
                x,y=rotate(p,angle)
                return x+9,y-7
            r=Region(tuple(Loop(tuple(transform(p) for p in l.points),l.outer) for l in a.region.loops),a.region.tolerance)
            s=replace(a.settings,grid_angle=angle,origin_x=9,origin_y=-7,
                      guide1=tuple(transform(p) for p in a.settings.guide1),guide2=tuple(transform(p) for p in a.settings.guide2))
            actual=kernel_generate(r,s)
            self.assertEqual(len(actual),len(a.cells))
            for before,after in zip(a.cells,actual):
                self.assertLess(math.dist(transform(before.center),after.center),1e-7)
                self.assertAlmostEqual(before.angle+angle,after.angle,places=7)

    def test_candidate_rejects_unimplemented_trim_and_other_shapes(self):
        a=self.samples['wave','circle','fixed']
        for changes in ({'clip_boundary':True},{'shape':'hexagon'},{'spread_radius':2}):
            with self.assertRaisesRegex(ValueError,'revision 2'):
                kernel_generate(a.region,replace(a.settings,**changes))

    def test_circular_fixture_fills_the_center_by_default(self):
        for shape,orientation in (('circle','fixed'),('slot','fixed'),('slot','tangent')):
            a=self.samples['circular',shape,orientation]
            self.assertEqual(a.settings.start_radius,0)
            self.assertEqual(sum(math.hypot(*c.center)<1e-8 for c in a.cells),1)

    def test_density_presets_never_violate_requested_web(self):
        for n in NAMES:
            for density in ('dense','airy'):
                with self.subTest(layout=n,density=density):
                    a=generate(n,density=density)
                    self.assertGreaterEqual(minimum_gap(a.cells,a.settings.gap),a.settings.gap-1e-8)


if __name__=='__main__':unittest.main()
