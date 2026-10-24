# SPDX-License-Identifier: GPL-3.0-only
from dataclasses import replace
import math
import unittest
from Perfora.geometry import Settings
from Perfora import surface_geometry as sg

class SurfaceGeometryTests(unittest.TestCase):
    def test_pointed_cone_uses_local_circumference_and_physical_row_pitch(self):
        slope=-math.tan(math.radians(15))
        slant=math.hypot(1,slope)
        region=sg.ConeRegion(2.5,slope,2.5,0.,9*slant)
        settings=Settings(size=.5,gap=.15,margin=.3,staggered=False)
        variants=[]
        for staggered in (False,True):
            cells=sg.conical_cells(region,replace(settings,staggered=staggered),-.2,0.)
            rows={}
            placements=[]
            for x,y,cell in cells:
                theta=x/region.reference_radius
                radius=region.radius0+slope*y/slant
                rows.setdefault(round(y,7),[]).append(theta)
                origin=(radius*math.cos(theta),radius*math.sin(theta),y/slant)
                normal=(math.cos(theta)/slant,math.sin(theta)/slant,-slope/slant)
                placements.append((origin,(0,0,0),(0,0,0),normal,-.2,0.,.25))
            heights=sorted(rows)
            counts=[len(rows[y]) for y in heights]
            self.assertGreater(counts[0],18)
            self.assertLess(counts[-1],counts[0]/3)
            self.assertGreater(len(cells),130)
            self.assertTrue(all(n%2==0 for n in counts))
            for a,b in zip(heights,heights[1:]):
                self.assertAlmostEqual(b-a,.65,places=6)
            accepted=sg.spaced_indices(placements,settings.gap)
            self.assertEqual(len(accepted),len(cells),'Pitch must preserve complete rows, including through-depth clearance')
            variants.append(tuple((round(x,7),round(y,7)) for x,y,_ in cells))
        self.assertNotEqual(*variants)

    def test_cone_offsets_and_zone_use_the_actual_row_radius(self):
        region=sg.ConeRegion(2.5,-.3,2.5,1.2,4.,math.pi)
        settings=Settings(size=.4,gap=.12,offset_x=.1,offset_y=.17)
        cells=sg.conical_cells(region,settings,-.2,0.,anchor=(.3,1.5))
        self.assertTrue(cells)
        self.assertEqual(cells,sg.conical_cells(region,settings,-.2,0.,anchor=(.3,1.5)))
        self.assertTrue(all(-.2<=y<=4.2 for _,y,_ in cells))
        self.assertTrue(any(abs(y-1.67)<1e-8 for _,y,_ in cells))

    def test_finite_segment_clamping_and_parallel_cases(self):
        for a,b,c,d,expected in (
            ((0,0,0),(1,0,0),(2,1,0),(2,2,0),math.sqrt(2)),
            ((0,0,0),(1,0,0),(0,2,0),(1,2,0),2),
            ((0,0,0),(0,0,0),(0,1,0),(0,2,0),1),
            ((0,0,0),(1,0,0),(.5,-1,0),(.5,1,0),0)):
            p,q=sg.closest_segments(a,b,c,d)
            self.assertAlmostEqual(sg.length(sg.sub(p,q)),expected)

    def test_halfplanes_protect_whole_depth_intervals(self):
        placements=(((0,0,0),(1,0,0),(0,1,0),(0,0,1),-.5,.2,.4),
                    ((.7,0,0),(1,0,0),(0,1,0),(0,0,1),-.2,.5,.4))
        planes=sg.separating_constraints(placements,.1)
        self.assertEqual(len(planes[0]),1)
        a,b=planes[0][0],planes[1][0]
        self.assertAlmostEqual(a[2],.3)
        self.assertAlmostEqual(b[2],.3)
        self.assertAlmostEqual(a[0],1)
        self.assertAlmostEqual(b[0],-1)

    def test_closed_pattern_has_one_seam_and_boundary_candidates(self):
        settings=Settings(size=.3,gap=.12,margin=.1,staggered=False)
        cells=sg.periodic_cells(2,1.5,math.tau,settings,.35)
        self.assertTrue(cells)
        self.assertEqual(len(cells),len({(round(x,8),round(y,8)) for x,y,_ in cells}))
        self.assertTrue(any(x==0 for x,y,c in cells))
        self.assertTrue(any(y<.25 for x,y,c in cells))
        shifted=sg.periodic_cells(2,1.5,math.tau,replace(settings,offset_x=4*math.pi),.35)
        self.assertEqual({(round(x,7),round(y,7)) for x,y,_ in cells},
                         {(round(x,7),round(y,7)) for x,y,_ in shifted})

    def test_periodic_voronoi_retains_edge_cells_without_mutating_dimensions(self):
        settings=Settings(shape='voronoi',size=.4,gap=.12,margin=.1,seed=11)
        a=sg.periodic_cells(2,1.5,math.tau,settings,.3)
        self.assertEqual(a,sg.periodic_cells(2,1.5,math.tau,settings,.3))
        self.assertTrue(all(c.shape=='voronoi' and len(c.vertices)>=3 for _,_,c in a))
        self.assertTrue(any(y-sg.enclosing_radius(c)<settings.margin for _,y,c in a))

    def test_periodic_neighbours_are_filtered_without_resizing_sections(self):
        def place(x):
            return ((x,0,0),(1,0,0),(0,1,0),(0,0,1),-.2,.1,.2)
        placements=(place(0),place(.35),place(.7),place(1.4))
        self.assertEqual(sg.spaced_indices(placements,.1),(0,2,3))
        self.assertEqual(placements[1][-1],.2)

    def test_physical_length_inverts_strongly_stretched_parameters(self):
        # x(t)=t+3*t**3: equal UV steps differ sevenfold in physical speed.
        curve=sg.LengthMap(lambda t:1+9*t*t,0.,1.)
        self.assertAlmostEqual(curve.total,4.,places=8)
        points=[curve.parameter_at(i/10*curve.total) for i in range(11)]
        distances=[t+3*t**3 for t in points]
        for a,b in zip(distances,distances[1:]):self.assertAlmostEqual(b-a,.4,places=7)
        for t in points:self.assertAlmostEqual(curve.parameter_at(curve.length_at(t)),t,places=8)

    def test_length_map_supports_boundary_extrapolation(self):
        curve=sg.LengthMap(lambda t:2.,-1.,3.)
        self.assertAlmostEqual(curve.parameter_at(-.5),-1.25)
        self.assertAlmostEqual(curve.parameter_at(8.5),3.25)
        self.assertAlmostEqual(curve.length_at(-1.25),-.5)

    def test_arc_pitch_preserves_through_depth_web_on_a_bend(self):
        radius,gap,curvature,low,high=.25,.15,.8,-.2,0.
        pitch=sg.arc_pitch(radius,gap,curvature,low,high)
        r=1/curvature
        distance=2*(r+low)*math.sin(pitch/(2*r))
        self.assertGreaterEqual(distance-2*radius,gap-1e-9)
        self.assertGreater(pitch,2*radius+gap)
        self.assertEqual(sg.arc_pitch(radius,gap,0,low,high),2*radius+gap)
