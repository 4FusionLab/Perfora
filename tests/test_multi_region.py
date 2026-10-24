# SPDX-License-Identifier: GPL-3.0-only
"""Offline geometry and orchestration checks. Native CAD is deliberately mocked."""
from dataclasses import replace
import importlib
import json
import math
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import patch

from Perfora import geometry as g, regions
from Perfora.cache import GeometryCache
from Perfora.feature_data import decode, metadata


def rectangle(x0, y0, x1, y1):
    return g.Region((g.Loop(((x0,y0), (x1,y0), (x1,y1), (x0,y1))),))


class FrameTests(unittest.TestCase):
    def assert_vector(self, a, b):
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y, places=10)

    def test_rotated_translated_mirrored_coplanar_frames_share_axes_and_origin(self):
        n = regions.unit((.2, -.6, .7))
        x = regions.unit(regions.cross(n, (0,0,1)))
        y = regions.cross(n, x)
        origin = tuple(2*a for a in n)
        first = (origin, x, y)
        angle = .73
        u = tuple(math.cos(angle)*a+math.sin(angle)*b for a,b in zip(x,y))
        v = tuple(-math.sin(angle)*a+math.cos(angle)*b for a,b in zip(x,y))
        moved = (regions.to_world(first, (3,-4)), u, tuple(-a for a in v))
        for a, b in zip(regions.canonical_frame(first), regions.canonical_frame(moved)):
            self.assert_vector(a, b)
        self.assertTrue(regions.coplanar(first, moved))
        canonical = regions.canonical_frame(first)
        self.assert_vector(regions.to_local(canonical, regions.to_world(canonical, (3,-2,.4))), (3,-2,.4))

    def test_axis_fallback_and_different_planes_are_predictable(self):
        frame = ((2,4,5), (0,1,0), (0,0,1))
        self.assertEqual(regions.canonical_frame(frame), ((2.,0.,0.), (0.,1.,0.), (0.,0.,1.)))
        self.assertFalse(regions.coplanar(frame, ((3,4,5), frame[1], frame[2])))
        self.assertFalse(regions.coplanar(frame, ((0,0,2), (1,0,0), (0,1,0))))
        with self.assertRaises(ValueError):
            regions.canonical_frame(((0,0,0), (1,0,0), (2,0,0)))

    def test_common_phase_is_independent_of_region_bounds_for_all_shapes(self):
        a, b = rectangle(-4,-2,-.2,2), rectangle(.2,-2,4,2)
        union_bounds = rectangle(-4,-2,4,2)
        for shape in g.SHAPE_IDS:
            for trim in (False, True):
                s = g.Settings(shape=shape, size=.4, slot_length=.7, gap=.15, margin=.1,
                               origin_x=0., origin_y=0., grid_angle=.32, clip_boundary=trim)
                reference = {cell.center:cell for cell in g.generate(union_bounds, s)}
                for region in (a,b):
                    cells = g.generate(region, s)
                    for cell in cells:
                        self.assertIn(cell.center, reference, (shape, trim))
                        self.assertEqual(cell, reference[cell.center])

    def test_circular_phase_and_anchor_shared_across_regions(self):
        s = g.Settings(layout='circular', size=.3, gap=.15, margin=.02,
                       origin_x=.2, origin_y=-.1, start_radius=.3,
                       radial_orientation=True, shape='slot', slot_length=.5)
        whole = g.generate(rectangle(-3,-3,3,3), s)
        for region in (rectangle(-3,-3,-.4,3), rectangle(.4,-3,3,3)):
            self.assertTrue(set(g.generate(region,s)).issubset(set(whole)))

    def test_holes_and_edge_clearance_stay_local_to_each_region(self):
        outer = rectangle(-3,-3,3,3)
        annulus = g.Region(outer.loops + (g.Loop(g.disk_region(1).loops[0].points, False),))
        s = g.Settings(size=.3, gap=.12, margin=.15, origin_x=0., origin_y=0.)
        for cell in g.generate(annulus,s):
            self.assertTrue(g.fits(cell,annulus,annulus.segments,s.margin))
            self.assertGreaterEqual(math.hypot(*cell.center), .5+s.margin+s.size/2)

    def test_broad_phase_accepts_touching_and_nested_void_as_candidates(self):
        a = rectangle(0,0,2,2)
        self.assertTrue(regions.bounds_overlap(a,rectangle(2,0,4,2)))
        self.assertFalse(regions.bounds_overlap(a,rectangle(2.01,0,4,2)))
        self.assertTrue(regions.bounds_overlap(a,rectangle(2.00001,0,4,2)))
        self.assertTrue(regions.bounds_overlap(a,rectangle(1,1,3,3)))

    def test_target_mapping_rejects_ambiguity_unused_targets_and_shared_intersect(self):
        self.assertEqual(regions.target_map(['a','b'], ['b','a'], 'cut'), ((1,),(0,)))
        self.assertEqual(regions.target_map([None,None], ['a'], 'cut'), ((0,),(0,)))
        for supports, targets, op in (([None],['a','b'],'cut'), (['b'],['a'],'cut'),
                                       (['a'],['a','b'],'cut'), (['a','a'],['a'],'intersect')):
            with self.assertRaises(ValueError):
                regions.target_map(supports,targets,op)

    def test_schema_1_and_2_migration_preserves_single_source_and_excludes_api_objects(self):
        s = g.Settings()
        config = dict(result='feature', bodies=[object()], center_point=object(),
                      target1=object(), target2=object(), _expressions={'size':'d'})
        payload = metadata(s,config)
        self.assertEqual(decode(json.dumps(payload))['source_count'],1)
        payload['schema'] = 1
        del payload['source_count']
        self.assertEqual(decode(json.dumps(payload))['schema'],1)
        payload = metadata(s,dict(config,_source_count=2,_body_map=((0,),(0,))))
        decoded = decode(json.dumps(payload))
        self.assertEqual(decoded['config']['_body_map'], [[0],[0]])
        self.assertNotIn('bodies', decoded['config'])
        for count in (0,33,True):
            payload['source_count'] = count
            with self.assertRaises(ValueError):
                decode(json.dumps(payload))
        with self.assertRaises(ValueError):
            decode('{"schema":99}')

    def test_region_cache_is_bounded_and_clear_drops_every_slot(self):
        cache = GeometryCache()
        a,b = rectangle(-2,-2,-.2,2), rectangle(.2,-2,2,2)
        s = g.Settings(size=.3,margin=.05,origin_x=0.,origin_y=0.)
        first = cache.for_region(0).resolve(a,s)
        cache.for_region(1).resolve(b,s)
        self.assertIs(first,cache.for_region(0).resolve(a,s))
        self.assertEqual(cache.for_region(0).hits,1)
        with self.assertRaises(ValueError):
            cache.for_region(32)
        cache.clear()
        self.assertEqual(cache.regions,{})


def adapter_modules():
    """Load production adapters under an isolated package, with inert adsk types."""
    package = ModuleType('_perfora_offline_multi')
    package.__path__ = [str(Path(__file__).resolve().parents[1] / 'Perfora')]
    core, fusion, adsk = ModuleType('adsk.core'), ModuleType('adsk.fusion'), ModuleType('adsk')
    for name in ('Plane','Cylinder','Cone','Sphere','Torus'):
        setattr(core,name,type(name,(),{}))
    for name in ('BRepFace','Profile','ConstructionPlane','Sketch','BaseFeature','CustomFeatureEventHandler'):
        setattr(fusion,name,type(name,(),{}))
    fusion.BooleanTypes = NS(IntersectionBooleanType='intersection')
    fusion.FeatureHealthStates = NS(ErrorFeatureHealthState='error')
    adsk.core, adsk.fusion = core,fusion
    bindings = {'adsk':adsk,'adsk.core':core,'adsk.fusion':fusion,package.__name__:package}
    with patch.dict(sys.modules,bindings):
        multi = importlib.import_module(package.__name__+'.multi_region')
        feature = importlib.import_module(package.__name__+'.feature')
        preview = importlib.import_module(package.__name__+'.preview')
        loaded = {k:v for k,v in sys.modules.items() if k.startswith(package.__name__)}
        loaded.update(bindings)
    return multi,feature,preview,core,fusion,loaded


class Owned:
    def __init__(self,name='item',events=None):
        self.name, self.events, self.isValid = name, events if events is not None else [], True
        self.isVisible = True
        self.attributes = NS(add=lambda *args:None)

    def deleteMe(self):
        self.events.append('delete '+self.name)
        self.isValid = False
        return True


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.multi,cls.feature,cls.preview,cls.core,cls.fusion,cls.modules = adapter_modules()

    def setUp(self):
        bindings = patch.dict(sys.modules,self.modules)
        bindings.start()
        self.addCleanup(bindings.stop)
        self.component = NS(parentDesign=NS())
        self.body = NS(parentComponent=self.component, revisionId='r1', nativeObject=None,isValid=True)
        self.a,self.b = self.face(self.body),self.face(self.body)
        self.config = dict(result='profiles', operation='body', bodies=[],material='cells',center_point=None)
        self.frame = ((0.,0.,0.), (1.,0.,0.), (0.,1.,0.))
        self.settings = g.Settings(size=.4,gap=.1,margin=.1,origin_x=0.,origin_y=0.)

    def face(self,body):
        face = self.fusion.BRepFace()
        face.body,face.geometry,face.nativeObject,face.isValid = body,self.core.Plane(),None,True
        face.assemblyContext = None
        return face

    def plan(self,source,indices=()):
        return self.multi.Plan(source,self.frame,self.frame,rectangle(-1,-1,1,1),self.settings,
                               Owned(),(g.Cell((0,0),'circle',.4,.4,0),),None,indices,'r1')

    def test_duplicate_sources_and_mixed_component_occurrences(self):
        self.assertEqual(self.multi.sources([self.a,self.a,self.b]),[self.a,self.b])
        proxy = NS(nativeObject=self.a,assemblyContext='occurrence A')
        other = NS(nativeObject=self.b,assemblyContext='occurrence B')
        with self.assertRaisesRegex(ValueError,'occurrence'):
            self.multi.sources([proxy,other])
        foreign = self.face(NS(parentComponent=object()))
        with self.assertRaisesRegex(ValueError,'component'):
            self.multi.sources([self.a,foreign])
        self.a.geometry = object()
        with self.assertRaisesRegex(ValueError,'planar'):
            self.multi.sources([self.a,self.b])

    def test_surface_selection_is_homogeneous_and_deduplicated(self):
        self.a.geometry = self.core.Cylinder()
        self.b.geometry = self.core.Cylinder()
        self.assertEqual(self.multi.sources([self.a,self.a,self.b]),[self.a,self.b])
        self.b.geometry = self.core.Cone()
        with self.assertRaisesRegex(ValueError,'one surface type'):
            self.multi.sources([self.a,self.b])
        self.b.geometry = self.core.Plane()
        with self.assertRaisesRegex(ValueError,'one surface type'):
            self.multi.sources([self.a,self.b])

    def test_multiple_construction_planes_and_unsupported_component_output(self):
        plane = self.fusion.ConstructionPlane()
        plane.component,plane.nativeObject,plane.isValid = self.component,None,True
        with self.assertRaisesRegex(ValueError,'construction plane'):
            self.multi.sources([self.a,plane])
        with self.assertRaisesRegex(ValueError,'New Body'):
            self.multi.validate([self.a,self.b],dict(self.config,result='extrude',operation='component'))

    def test_persisted_target_map_is_used_without_rereading_support(self):
        cfg = dict(self.config,result='feature',operation='cut',bodies=[self.body],_body_map=[[0],[0]])
        with patch.object(self.multi.model,'source_support_body',side_effect=AssertionError('must not infer')):
            self.assertEqual(self.multi.validate([self.a,self.b],cfg)[1],((0,),(0,)))
        with self.assertRaisesRegex(ValueError,'mapping'):
            self.multi.validate([self.a,self.b],dict(cfg,_body_map=[[0],[1]]))
        with self.assertRaisesRegex(ValueError,'one Profiles'):
            self.multi.validate([self.a,self.b],dict(cfg,operation='intersect'))

    def prepare_context(self, region_b=None, area=0.):
        module = self.multi
        sketches = []
        def sketch(source):
            item = Owned()
            item.parentComponent = self.component
            sketches.append(item)
            return item
        manager = NS(copy=lambda body: NS(faces=NS(count=1),area=area), booleanOperation=lambda *args:True)
        region_b = region_b or rectangle(.2,-1,2,1)
        return sketches, [patch.object(module.model,'new_source_sketch',side_effect=sketch),
            patch.object(module.model,'sketch_frame',return_value=self.frame),
            patch.object(module.model,'get_region',side_effect=lambda source,*args:rectangle(-2,-1,-.2,1) if source is self.a else region_b),
            patch.object(module.clipping,'source_body',side_effect=lambda *args:Owned()),
            patch.object(self.fusion,'TemporaryBRepManager',NS(get=lambda:manager),create=True)]

    def test_preparation_reads_all_sources_limits_total_and_reuses_source_geometry(self):
        from contextlib import ExitStack
        sketches, patches = self.prepare_context()
        with ExitStack() as stack:
            for item in patches: stack.enter_context(item)
            cache = GeometryCache()
            plans = self.multi.prepare([self.a,self.b],self.settings,self.config,cache)
            self.assertTrue(all(not s.isValid for s in sketches))
            self.assertEqual(plans[0].frame,plans[1].frame)
            self.assertEqual(plans[0].settings.origin_x,0.)
            before = len(sketches)
            self.multi.prepare([self.a,self.b],replace(self.settings,gap=.2),self.config,cache,previous=plans)
            self.assertEqual(len(sketches),before)
            self.body.revisionId = 'r2'
            self.multi.prepare([self.a,self.b],self.settings,self.config,cache,previous=plans)
            self.assertEqual(len(sketches),before+2)
            count = sum(len(p.cells) for p in plans)
            with self.assertRaisesRegex(ValueError,'total hole count'):
                self.multi.prepare([self.a,self.b],replace(self.settings,limit=count-1),self.config)

    def test_exact_overlap_rejected_and_empty_intersection_preserves_nested_void(self):
        from contextlib import ExitStack
        for area, error in ((1.,True),(0.,False)):
            sketches, patches = self.prepare_context(rectangle(-1,-.5,1,.5),area)
            with ExitStack() as stack:
                for item in patches: stack.enter_context(item)
                if error:
                    with self.assertRaisesRegex(ValueError,'overlap'):
                        self.multi.prepare([self.a,self.b],self.settings,self.config)
                else:
                    self.assertEqual(len(self.multi.prepare([self.a,self.b],self.settings,self.config)),2)
                self.assertTrue(all(not s.isValid for s in sketches))

    def test_changed_first_frame_realigns_cached_coplanar_sources_before_overlap_check(self):
        from contextlib import ExitStack
        self.b.body=NS(parentComponent=self.component,revisionId='b1',nativeObject=None,isValid=True)
        sketches,patches=self.prepare_context()
        with ExitStack() as stack:
            for item in patches:stack.enter_context(item)
            previous=self.multi.prepare([self.a,self.b],self.settings,self.config)
            self.a.body.revisionId='changed'
            tilted=((0.,0.,0.),(1.,0.,-1e-8),(0.,1.,0.))
            manager=NS(copy=lambda body:NS(faces=NS(count=1),area=1.),booleanOperation=lambda *args:True)
            with patch.object(self.multi.model,'sketch_frame',side_effect=[tilted,self.frame]), \
                 patch.object(self.multi.model,'get_region',side_effect=lambda source,*args:rectangle(-2,-1,1,1)
                              if source is self.a else rectangle(.2,-1,2,1)), \
                 patch.object(self.fusion,'TemporaryBRepManager',NS(get=lambda:manager)):
                with self.assertRaisesRegex(ValueError,'overlap'):
                    self.multi.prepare([self.a,self.b],self.settings,self.config,previous=previous)

    def test_build_draws_all_sketches_before_extrude_and_rolls_back_second_failure(self):
        events,created = [],[]
        plans = [self.plan(self.a),self.plan(self.b)]
        def sketch(source):
            item = Owned('sketch'+str(len(created)),events)
            item.parentComponent = self.component
            created.append(item)
            return item
        def draw(plan,sketch,cfg):
            events.append('draw')
            return object()
        def extrude(*args):
            events.append('extrude')
            if events.count('extrude') == 2:
                raise ValueError('second failed')
            item = Owned('extrude1',events)
            created.append(item)
            return item
        with patch.object(self.multi,'prepare',return_value=plans), patch.object(self.multi.model,'new_source_sketch',side_effect=sketch), \
             patch.object(self.multi,'draw',side_effect=draw), patch.object(self.multi.model,'extrude',side_effect=extrude):
            with self.assertRaisesRegex(ValueError,'second failed'):
                self.multi.build([self.a,self.b],self.settings,dict(self.config,result='extrude'))
        self.assertEqual(events[:4],['draw','draw','extrude','extrude'])
        self.assertTrue(all(not item.isValid for item in created))
        self.assertEqual(events[4:7],['delete extrude1','delete Perforation 2 - Circle','delete Perforation 1 - Circle'])

    def test_failed_draw_does_not_leave_sketches_and_cleanup_attempts_all_items(self):
        items = [Owned(),Owned()]
        for item in items: item.parentComponent = self.component
        with patch.object(self.multi,'prepare',return_value=[self.plan(self.a),self.plan(self.b)]), \
             patch.object(self.multi.model,'new_source_sketch',side_effect=items), \
             patch.object(self.multi,'draw',side_effect=[object(),ValueError('bad contour')]):
            with self.assertRaisesRegex(ValueError,'bad contour'):
                self.multi.build([self.a,self.b],self.settings,self.config)
        self.assertTrue(all(not item.isValid for item in items))
        bad,good = Owned(),Owned()
        bad.deleteMe = lambda:False
        with self.assertRaisesRegex(RuntimeError,'clean up'):
            self.multi.cleanup([good,bad])
        self.assertFalse(good.isValid)

    def test_cleanup_activates_grouped_output_before_deleting_dependants(self):
        events=[]
        first,last=Owned('reference',events),Owned('combine',events)
        last.timelineObject=NS(rollTo=lambda before:events.append(('roll',before)) or True)
        self.multi.cleanup([first,last],activate=True)
        self.assertEqual(events,[('roll',False),'delete combine','delete reference'])

    def test_feature_recompute_restores_first_and_failed_second_base(self):
        class Base(self.fusion.BaseFeature):
            def __init__(self, value, fail=False):
                self.value,self.fail,self.editing = value,fail,False
                self.bodies = NS(item=lambda index:self)
            def startEdit(self): self.editing=True; return True
            def finishEdit(self): self.editing=False; return True
            def updateBody(self,source,body):
                if self.fail:
                    self.fail=False
                    self.value='partially modified'
                    return False
                self.value=body
                return True
        a,b = Base('old A'),Base('old B',True)
        frames = [self.fusion.Sketch(),self.fusion.Sketch()]
        custom = NS(features=frames+[a,b],parentComponent=self.component)
        manager = NS(copy=lambda base:base.value)
        with patch.object(self.feature,'validate'), patch.object(self.multi,'prepare',return_value=[self.plan(self.a),self.plan(self.b)]), \
             patch.object(self.multi,'make_body',side_effect=['new A','new B']), \
             patch.object(self.fusion,'TemporaryBRepManager',NS(get=lambda:manager),create=True):
            with self.assertRaisesRegex(ValueError,'update'):
                self.feature.rebuild_many(custom,[self.a,self.b],self.settings,self.config)
        self.assertEqual((a.value,b.value),('old A','old B'))
        self.assertFalse(a.editing or b.editing)

    def test_feature_preflight_failure_changes_no_base(self):
        frames = [self.fusion.Sketch(),self.fusion.Sketch()]
        bases = [self.fusion.BaseFeature(),self.fusion.BaseFeature()]
        for base in bases: base.startEdit = lambda:self.fail('preflight must precede edit')
        custom = NS(features=frames+bases,parentComponent=self.component)
        with patch.object(self.feature,'validate'), patch.object(self.multi,'prepare',return_value=[self.plan(self.a),self.plan(self.b)]), \
             patch.object(self.multi,'make_body',side_effect=[object(),ValueError('bad solid')]):
            with self.assertRaisesRegex(ValueError,'bad solid'):
                self.feature.rebuild_many(custom,[self.a,self.b],self.settings,self.config)

    def test_feature_create_second_solid_failure_removes_node_and_all_references(self):
        dependencies,owned=[],[]
        data=NS(addDependency=lambda key,entity:dependencies.append(key) or True,
                addCustomParameter=lambda *args:True)
        custom=Owned('custom')
        custom.customNamedValues=NS(addOrSetValue=lambda *args:True)
        def sketch(source):
            item=Owned('reference')
            owned.append(item)
            return item
        self.component.features=NS(customFeatures=NS(createInput=lambda definition:data,add=lambda data:custom),
                                   baseFeatures=NS(add=lambda:self.fail('all solids must be ready before adding bases')))
        cfg=dict(self.config,result='feature',width=4.,height=3.,start='0 mm',distance1='2 mm',distance2='2 mm')
        with patch.object(self.feature,'validate'),patch.object(self.feature,'register',return_value=object()), \
             patch.object(self.feature,'dependency_entity',side_effect=lambda entity,component:entity), \
             patch.object(self.multi.model,'new_source_sketch',side_effect=sketch), \
             patch.object(self.multi,'prepare',return_value=[self.plan(self.a),self.plan(self.b)]), \
             patch.object(self.multi,'make_body',side_effect=[object(),ValueError('bad second solid')]), \
             patch.object(self.core,'ValueInput',NS(createByReal=lambda x:x),create=True), \
             patch.object(self.feature.model,'value',side_effect=lambda x:x):
            with self.assertRaisesRegex(ValueError,'bad second solid'):
                self.feature.build_many([self.a,self.b],self.settings,cfg)
        self.assertEqual(dependencies,['source0','source1'])
        self.assertFalse(custom.isValid)
        self.assertTrue(all(not item.isValid for item in owned))
        self.assertFalse(self.feature._busy)

    def test_fast_preview_reuses_layout_for_color_material_and_thickness(self):
        plans = [self.plan(self.a),self.plan(self.b)]
        plans[1].frame = ((0.,0.,2.),(1.,0.,0.),(0.,1.,0.))
        groups = []
        def group():
            item = Owned()
            item.addLines = lambda *args:NS()
            groups.append(item)
            return item
        self.component.customGraphicsGroups = NS(add=group)
        renderer = self.preview.Renderer()
        with patch.object(self.multi,'prepare',return_value=plans) as prepare, \
             patch.object(self.fusion,'CustomGraphicsCoordinates',NS(create=lambda x:x),create=True), \
             patch.object(self.fusion,'CustomGraphicsSolidColorEffect',NS(create=lambda x:x),create=True), \
             patch.object(self.core,'Color',NS(create=lambda *x:x),create=True):
            self.assertEqual(renderer.show([self.a,self.b],self.settings,self.config),2)
            first = renderer.graphics
            self.assertTrue(any(abs(z-2.) < 1e-10 for z in renderer.coordinates[2::3]))
            renderer.show([self.a,self.b],self.settings,self.config,color='cyan')
            self.assertIs(renderer.graphics,first)
            renderer.show([self.a,self.b],self.settings,dict(self.config,distance1='20 mm'))
            renderer.show([self.a,self.b],self.settings,dict(self.config,material='panel'))
            self.assertEqual(prepare.call_count,1)
            self.assertFalse(first.isValid)
            self.body.revisionId = 'r2'
            renderer.show([self.a,self.b],self.settings,self.config)
            self.assertEqual(prepare.call_count,2)
            renderer.reset()
            self.assertIsNone(renderer.multi_plans)
            self.assertTrue(all(not item.isValid for item in groups))

    def test_feature_source_dependencies_include_every_region_and_schema1_fallback(self):
        payload = metadata(g.Settings(),dict(self.config,_source_count=2,_body_map=((),())))
        dependencies = {'source0':NS(entity=self.a),'source1':NS(entity=self.b)}
        custom = NS(customNamedValues=NS(value=lambda key:json.dumps(payload)),
                    dependencies=NS(itemById=lambda key:dependencies.get(key)),parentComponent=self.component)
        self.assertEqual(self.feature.source_entities(custom),[self.a,self.b])
        self.b.isValid = False
        with self.assertRaisesRegex(ValueError,'region 2'):
            self.feature.source_entities(custom)
        payload = metadata(g.Settings(),self.config)
        payload['schema'] = 1
        del payload['source_count']
        dependencies['source'] = NS(entity=self.a)
        self.assertEqual(self.feature.source_entities(custom),[self.a])


if __name__ == '__main__':
    unittest.main()
