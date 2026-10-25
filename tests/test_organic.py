# SPDX-License-Identifier: GPL-3.0-only
"""Organic geometry invariants; native CAD is checked separately in Fusion."""
from dataclasses import replace
import math
import unittest

from Perfora import geometry as g, organic as o, surface_geometry as sg
from Perfora.cache import GeometryCache
from Perfora.feature_data import metadata, decode


class OrganicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.region=g.rectangle_region(5,4)
        cls.settings=g.Settings(size=.55,gap=.09,margin=.12,clip_boundary=True)
        cls.cells={shape:g.generate(cls.region,replace(cls.settings,shape=shape)) for shape in o.SHAPES}

    def test_all_fields_are_distinct_deterministic_and_bounded(self):
        fingerprints=[]
        for shape,cells in self.cells.items():
            s=replace(self.settings,shape=shape)
            self.assertEqual(cells,g.generate(self.region,s))
            self.assertGreater(len(cells),2,shape)
            self.assertNotEqual(cells,g.generate(self.region,replace(s,seed=19)),shape)
            self.assertLess(sum(len(c.contour) for c in cells if c.shape!='circle'),o.MAX_EDGES)
            fingerprints.append(tuple(c.center for c in cells))
        self.assertEqual(len(set(fingerprints)),6)

    def test_field_contours_close_without_self_intersection(self):
        for shape,cells in self.cells.items():
            if shape=='blue_noise':continue
            for cell in cells:
                contour=cell.contour
                for i,e in enumerate(contour):
                    self.assertLess(g.dist(e.end,contour[(i+1)%len(contour)].start),1e-8)
                    self.assertGreater(e.length,1e-8)
                self.assertTrue(o._simple(cell.vertices),shape)
                self.assertGreater(o._area(cell.vertices),0)
                self.assertTrue(any(e.center is not None for e in contour),shape)

    def test_actual_contours_keep_minimum_web(self):
        for shape,cells in self.cells.items():
            for i,a in enumerate(cells):
                for b in cells[:i]:
                    if shape=='blue_noise':
                        gap=g.dist(a.center,b.center)-(a.size+b.size)/2
                    else:
                        p,q=a.vertices,b.vertices
                        bounds=lambda p:(min(x for x,y in p),max(x for x,y in p),min(y for x,y in p),max(y for x,y in p))
                        aa,bb=bounds(p),bounds(q)
                        if (aa[0]-bb[1]>=self.settings.gap or bb[0]-aa[1]>=self.settings.gap or
                            aa[2]-bb[3]>=self.settings.gap or bb[2]-aa[3]>=self.settings.gap):continue
                        gap=min(g.segment_distance(c,d,e,f) for c,d in g.edges(p) for e,f in g.edges(q))
                    self.assertGreaterEqual(gap+2e-6,self.settings.gap,shape)

    def test_material_forest_connects_nested_islands(self):
        nx=ny=31
        mask=[0<x<nx-1 and 0<y<ny-1 for y in range(ny) for x in range(nx)]
        for x,y in ((8,8),(23,12),(15,21)):mask[y*nx+x]=False
        before=list(mask)
        self.assertEqual(o._components(mask,nx,ny)[1],4)
        o.connect_material(mask,nx,ny)
        self.assertEqual(o._components(mask,nx,ny)[1],1)
        self.assertTrue(all(not b or a for a,b in zip(before,mask)))
        field=o.distance_field(mask,nx,ny)
        dilated=[v>2.5 for v in field]
        self.assertEqual(o._components(dilated,nx,ny)[1],1)

    def test_distance_transform_matches_brute_force(self):
        nx,ny=11,9;solid=((1,1),(8,3),(5,7))
        mask=[(x,y) not in solid for y in range(ny) for x in range(nx)]
        field=o.distance_field(mask,nx,ny)
        for y in range(ny):
            for x in range(nx):self.assertAlmostEqual(field[y*nx+x],min(math.hypot(x-a,y-b) for a,b in solid))

    def test_blue_noise_has_gradient_and_radius_aware_spacing(self):
        cells=self.cells['blue_noise'];left=[c.size for c in cells if c.center[0]<-.8];right=[c.size for c in cells if c.center[0]>.8]
        self.assertGreater(sum(right)/len(right),sum(left)/len(left)*1.35)
        uniform=g.generate(self.region,replace(self.settings,shape='blue_noise',organic_variation=0))
        self.assertTrue(all(c.shape=='circle' and c.size==self.settings.size for c in uniform))

    def test_direction_rotation_offsets_threshold_and_scale_change_geometry(self):
        for shape,cells in self.cells.items():
            s=replace(self.settings,shape=shape)
            for changes in (dict(organic_direction=.57),dict(offset_x=.24,offset_y=.13),dict(size=.63)):
                self.assertNotEqual(cells,g.generate(self.region,replace(s,**changes)),(shape,changes))
            if shape in o.FIELDS:
                self.assertNotEqual(cells,g.generate(self.region,replace(s,organic_open=60)),shape)

    def test_complete_holes_keep_outer_inner_margin_and_trim_adds_candidates(self):
        region=g.Region(self.region.loops+(g.Loop(g.rectangle_region(.6,.8).loops[0].points,False),))
        for shape in o.SHAPES:
            s=replace(self.settings,shape=shape,clip_boundary=False)
            whole=g.generate(region,s);partial=g.generate(region,replace(s,clip_boundary=True))
            self.assertTrue(all(g.fits(c,region,region.segments,s.margin) for c in whole))
            self.assertTrue(set(whole).issubset(set(partial)),shape)

    def test_incompatible_distributions_and_bad_values_fail_explicitly(self):
        for shape in o.SHAPES:
            for layout in ('circular','path',*g.VARIANT_LAYOUTS):
                with self.assertRaisesRegex(ValueError,'Organic hole shapes'):replace(self.settings,shape=shape,layout=layout).validate()
            for change in (dict(seed=-1),dict(organic_open=0),dict(organic_variation=100),
                           dict(organic_gradient=101),dict(organic_direction=math.nan)):
                with self.assertRaises(ValueError):replace(self.settings,shape=shape,**change).validate()

    def test_sampling_limit_and_hole_limit_fail_before_unbounded_work(self):
        with self.assertRaisesRegex(ValueError,'sampling budget'):
            g.generate(g.rectangle_region(100,100),replace(self.settings,shape='smooth_noise'))
        with self.assertRaisesRegex(ValueError,'Maximum Holes'):
            g.generate(self.region,replace(self.settings,shape='gyroid',limit=1))

    def test_cache_and_versioned_feature_payload_include_all_parameters(self):
        cache=GeometryCache();s=replace(self.settings,shape='gyroid')
        first=cache.resolve(self.region,s)
        self.assertIs(first,cache.resolve(self.region,s))
        for key in o.PARAMETERS:
            changed=replace(s,**{key:getattr(s,key)+.1})
            self.assertIsNot(first,cache.resolve(self.region,changed))
        cfg=dict(bodies=[],result='feature')
        restored=g.Settings(**decode(__import__('json').dumps(metadata(s,cfg)))['settings'])
        self.assertEqual(restored,s)
        legacy={k:v for k,v in s.__dict__.items() if k not in o.PARAMETERS}
        self.assertEqual(g.Settings(**legacy).organic_open,g.Settings().organic_open)

    def test_periodic_curved_cells_local_contours_and_seam_phase(self):
        for shape in o.SHAPES:
            s=replace(self.settings,shape=shape,size=.7)
            a=sg.periodic_cells(1.4,2.4,math.tau,s,.2)
            b=sg.periodic_cells(1.4,2.4,math.tau,replace(s,offset_x=1.4*math.tau),.2)
            self.assertTrue(a,shape)
            self.assertEqual([(round(x,7),round(y,7),c) for x,y,c in a],[(round(x,7),round(y,7),c) for x,y,c in b])
            self.assertEqual(len(a),len({(round(x,7),round(y,7)) for x,y,c in a}))
            for x,y,c in a:
                self.assertEqual(c.center,(0.,0.))
                self.assertGreater(sg.enclosing_radius(c),0)


if __name__=='__main__':unittest.main()
