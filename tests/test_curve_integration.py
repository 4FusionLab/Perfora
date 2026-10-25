# SPDX-License-Identifier: GPL-3.0-only
"""Offline adapter/storage/dialog contracts using explicitly fake adsk objects.

No Autodesk modules, installed add-in, Application, or running Fusion are used.
CAD, native events/transactions and persistent entity tracking remain unverified.
"""
from contextlib import contextmanager
from dataclasses import replace
from importlib import import_module, util
import json
import math
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import patch

from test_curve_layout import CubicLine
from Perfora.distributions import VARIANT_PARAMETERS


class XYZ:
    def __init__(self,x=0,y=0,z=0): self.x,self.y,self.z=x,y,z
    @staticmethod
    def create(x=0,y=0,z=0): return XYZ(x,y,z)
    def asArray(self): return (self.x,self.y,self.z)


class Line:
    def __init__(self): self.evaluator=CubicLine()
class Arc: pass
class Circle: pass
class Spline: pass
class SketchCurve:
    nativeObject=None
    isValid=True
    def __init__(self,component,geometry=None):
        self.geometry=geometry or Line()
        self.parentSketch=NS(parentComponent=component,revisionId='r1',
            sketchToModelSpace=lambda p: XYZ(*p.asArray()))
class Edge:
    nativeObject=None
    isValid=True
    def __init__(self,component):
        self.body=NS(parentComponent=component,revisionId='e1')
        self.geometry=Line()
        self.evaluator=CubicLine()
        self.startVertex=object()
        self.endVertex=object()
class Plane:
    nativeObject=None
    isValid=True
    def __init__(self,component): self.component=component


@contextmanager
def adapters():
    core=ModuleType('adsk.core'); core.__file__=__file__
    core.Point3D=XYZ
    core.Line3D,core.Arc3D,core.Circle3D,core.NurbsCurve3D=Line,Arc,Circle,Spline
    # Import-time event bases only; no fake Application is provided on purpose.
    for name in ('SelectionEventHandler','InputChangedEventHandler','ValidateInputsEventHandler','CustomEventHandler',
                 'CommandEventHandler','KeyboardEventHandler','CommandCreatedEventHandler'):
        setattr(core,name,type(name,(),{}))
    fusion=ModuleType('adsk.fusion')
    fusion.SketchCurve,fusion.BRepEdge,fusion.ConstructionPlane=SketchCurve,Edge,Plane
    fusion.Profile,fusion.BRepFace=type('Profile',(),{}),type('BRepFace',(),{})
    fusion.CustomFeatureEventHandler=type('CustomFeatureEventHandler',(),{})
    root=ModuleType('adsk'); root.core,root.fusion=core,fusion
    package='_perfora_offline_path'
    with patch.dict(sys.modules,{'adsk':root,'adsk.core':core,'adsk.fusion':fusion}):
        spec=util.spec_from_file_location(package,Path(__file__).parents[1]/'Perfora/__init__.py',
            submodule_search_locations=[str(Path(__file__).parents[1]/'Perfora')])
        mod=util.module_from_spec(spec);sys.modules[package]=mod;spec.loader.exec_module(mod)
        try:
            yield (import_module(package+'.model'),import_module(package+'.feature'),import_module(package+'.Perfora'))
        finally:
            for name in list(sys.modules):
                if name==package or name.startswith(package+'.'): del sys.modules[name]


class Values:
    def __init__(self,data): self.data=json.dumps(data)
    def value(self,key): return self.data
    def addOrSetValue(self,key,value): self.data=value
class Dependencies:
    def __init__(self): self.items={}
    def itemById(self,key): return self.items.get(key)
    def add(self,key,entity):
        dep=NS(entity=entity,deleteMe=lambda:self.items.pop(key))
        self.items[key]=dep
        return dep
class Parameters:
    def __init__(self,values): self.items={k:NS(value=v,expression=str(v)) for k,v in values.items()}
    def itemById(self,key): return self.items.get(key)


class Number:
    def __init__(self,value=0,expression=None):
        self._value=value
        self.expression=str(value) if expression is None else expression
        self.isVisible=True;self.isValueError=False
        self.default_expression=self.expression;self.unit='mm';self.name='Number';self.tooltip=''
    @property
    def value(self):
        if not self.isValidExpression: raise ValueError('Invalid hidden field')
        return self._value
    @value.setter
    def value(self,value): self._value=value;self.expression=str(value)
    @property
    def isValidExpression(self): return self.expression != 'invalid'
    @property
    def model_expression(self): return self.expression
class Select:
    def __init__(self,*entities): self.entities=list(entities);self.isVisible=True
    @property
    def selectionCount(self): return len(self.entities)
    def selection(self,i): return NS(entity=self.entities[i])
    def addSelection(self,entity): self.entities.append(entity)
class Dropdown:
    def __init__(self,options,chosen):
        self.selectedItem=NS(index=next(i for i,(key,_) in enumerate(options) if key==chosen));self.isVisible=True


class CurveIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope=adapters();cls.model,cls.feature,cls.entry=cls.scope.__enter__()
    @classmethod
    def tearDownClass(cls): cls.scope.__exit__(None,None,None)
    def setUp(self):
        self.component=type('Component',(),{})()
        self.source=Plane(self.component)
        self.path=SketchCurve(self.component)
        self.frame=((0,0,0),(1,0,0),(0,1,0))
        self.settings=self.model.Settings(layout='path',size=.3,gap=.1,margin=.05,path_spacing=.7)

    def test_adapter_uses_sketch_coordinates_and_trimmed_edge_evaluator(self):
        curve=self.path.geometry.evaluator
        # Evaluator returns tuple points in the numerical fixture. Convert to the
        # small fake Point3D used by the real model adapter.
        point=curve.getPointAtParameter;derivative=curve.getFirstDerivative;strokes=curve.getStrokes
        curve.getPointAtParameter=lambda t:(True,XYZ(*point(t)[1]))
        curve.getFirstDerivative=lambda t:(True,XYZ(*derivative(t)[1]))
        curve.getStrokes=lambda a,b,tol:(True,[XYZ(0,0,0),XYZ(7,0,0)])
        self.path.parentSketch.sketchToModelSpace=lambda p: XYZ(p.x+2,p.y-3,p.z)
        s=self.model.layout_settings(self.settings,{'path':self.path},None,self.frame,self.component)
        self.assertAlmostEqual(s.path_samples[0][0],2)
        self.assertAlmostEqual(s.path_samples[0][1],-3)
        self.assertAlmostEqual(s.path_samples[-1][0],9)
        edge=Edge(self.component)
        edge.evaluator=curve
        # If the adapter tries underlying geometry.evaluator this fails.
        edge.geometry.evaluator=None
        result=self.model.path_samples(edge,self.settings,self.frame,self.component)
        self.assertAlmostEqual(result[-1][0],7)

    def test_missing_cross_component_unsupported_and_invalid_paths_reject(self):
        for path in (None,NS(isValid=False),NS(isValid=True,nativeObject=None),
                     SketchCurve(NS()),SketchCurve(self.component,NS())):
            with self.subTest(path=path),self.assertRaises(ValueError):self.model.path_entity(path,self.component)
        with self.assertRaisesRegex(ValueError,'Start Point'):
            self.model.layout_settings(self.settings,{'path':self.path,'center_point':object()},None,self.frame,self.component)

    def test_sampling_cache_tracks_live_revision_frame_and_placement_but_not_extrusion(self):
        cache=self.model.PathCache()
        with patch.object(self.model,'path_samples',return_value=((0.,0.,0.),)) as sample:
            first=cache.resolve(self.path,self.settings,self.frame,self.component)
            self.assertIs(cache.resolve(self.path,self.settings,self.frame,self.component),first)
            self.assertEqual(sample.call_count,1)
            self.path.parentSketch.revisionId='r2'
            cache.resolve(self.path,self.settings,self.frame,self.component)
            cache.resolve(self.path,replace(self.settings,path_start=.1),self.frame,self.component)
            cache.resolve(self.path,self.settings,((1,0,0),(1,0,0),(0,1,0)),self.component)
            self.assertEqual(sample.call_count,4)
            self.assertEqual(cache.builds,4)
        previous=cache.key
        with patch.object(self.model,'path_samples',side_effect=ValueError('bad path')):
            with self.assertRaises(ValueError):cache.resolve(self.path,self.settings,self.frame,self.component)
        self.assertEqual(cache.key,previous)

    def make_custom(self,settings,config=None,old=False):
        cfg=dict(boundary='rectangle',width=4.,height=3.,bodies=[],start='0',distance1='2',distance2='2')
        cfg.update(config or {})
        data=self.feature.metadata(settings,cfg)
        if old:
            for key in list(data['settings']):
                if key.startswith('path_'):data['settings'].pop(key)
        vals={key:(getattr(settings,key) if hasattr(settings,key) else cfg[key]) for key in self.feature.PARAMETERS}
        if old:
            for key in list(vals):
                if key.startswith('path_'):vals.pop(key)
        custom=NS(customNamedValues=Values(data),parameters=Parameters(vals),dependencies=Dependencies(),parentComponent=self.component)
        custom.dependencies.add('source',self.source)
        if settings.layout=='path':custom.dependencies.add('path',self.path)
        return custom,cfg

    def test_metadata_never_serializes_native_path_or_transient_samples(self):
        data=self.feature.metadata(replace(self.settings,path_samples=((1,2,3),)),dict(path=self.path,bodies=[],_expressions={'path_spacing':'step'}))
        self.assertNotIn('path',data['config']);self.assertNotIn('path_samples',data['settings'])
        self.assertNotIn('_expressions',data['config'])
        self.assertEqual(json.loads(json.dumps(data))['settings']['layout'],'path')

    def test_feature_read_defaults_keep_old_schema_one_nodes_compatible(self):
        settings=replace(self.settings,layout='grid')
        custom,_=self.make_custom(settings,old=True)
        source,actual,cfg=self.feature.read(custom)
        self.assertIs(source,self.source)
        self.assertEqual(actual.path_spacing,.8)
        self.assertEqual(actual.layout,'grid')
        self.assertIsNone(cfg['path'])
        previous=custom.customNamedValues.data
        with self.assertRaisesRegex(ValueError,'Recreate it'):
            self.feature.update(custom,self.settings,dict(cfg,path=self.path))
        self.assertEqual(custom.customNamedValues.data,previous)
        custom.parameters.items.pop('size')
        with self.assertRaisesRegex(ValueError,'missing parameter'):self.feature.read(custom)

    def test_feature_missing_dependency_can_be_repaired_in_edit(self):
        custom,cfg=self.make_custom(self.settings)
        self.assertIs(self.feature.read(custom)[2]['path'],self.path)
        custom.dependencies.items.pop('path')
        with self.assertRaisesRegex(ValueError,'Path is missing'):self.feature.read(custom)
        self.assertIsNone(self.feature.path_dependency(custom,strict=False))
        replacement=SketchCurve(self.component)
        cfg.update(path=replacement)
        with patch.object(self.model,'path_reference',return_value=replacement),patch.object(self.feature,'rebuild',return_value=7):
            self.assertEqual(self.feature.update(custom,self.settings,cfg),7)
        self.assertIs(self.feature.read(custom)[2]['path'],replacement)

    def test_feature_update_replaces_and_removes_path_dependency_and_preserves_expressions(self):
        custom,cfg=self.make_custom(self.settings)
        replacement=SketchCurve(self.component)
        cfg.update(path=replacement,_expressions={'path_spacing':'userStep'})
        with patch.object(self.model,'path_reference',return_value=replacement),patch.object(self.feature,'rebuild',return_value=9):
            self.feature.update(custom,replace(self.settings,path_reverse=True,path_position=.2),cfg)
            self.assertIs(custom.dependencies.itemById('path').entity,replacement)
            self.assertEqual(custom.parameters.itemById('path_spacing').expression,'userStep')
            data=self.feature.stored(custom)
            self.assertTrue(data['settings']['path_reverse']);self.assertEqual(data['settings']['path_position'],.2)
            self.feature.update(custom,replace(self.settings,layout='grid'),dict(cfg,path=None))
            self.assertIsNone(custom.dependencies.itemById('path'))
        self.assertFalse(self.feature._busy)

    def session(self,layout='path',shape='slot',result='feature'):
        e=self.entry;s=e.Session.__new__(e.Session)
        s._planar_material=None;s.surface_choices=e.SURFACE_LAYOUTS
        s.layout_choices=e.LAYOUTS;s.distribution_revision=2
        s.updating=False;s._extrude_inputs={} if result=='feature' else None;s.edited_feature=None
        s.units=NS(evaluateExpression=lambda expression,unit:float(expression))
        numeric=dict(size=.3,size_flats=.3,size_side=.3,size_width=.3,size_diagonal=.3,size_minor=.3,
            size_overall=.3,cell_spacing=.3,organic_scale=.3,blue_diameter=.3,slot_length=.6,length_diagonal=.6,length_major=.6,
            gap=.1,margin=.05,grid_angle=0,shape_angle=.21,offset_x=0,offset_y=0,limit=1500,
            spread_radius=0,start_radius=0,path_spacing=.8,path_start=.1,path_end=.2,path_position=.3,
            width=4,area_diameter=4,height=3,taper1=0,taper2=0,distance1=.2,distance2=.2,start=0,
            cylinder_start=0,cylinder_sweep=6.283185307179586,axial_start=0,axial_length=0,object_offset1=0,object_offset2=0,arm_width=.15,star_ratio=45,star_points=5,irregularity=80,seed=1,corner_radius=.05)
        numeric.update({key:getattr(self.settings,key) for key in (*VARIANT_PARAMETERS, *e.ORGANIC_PARAMETERS)})
        s.numeric_inputs={k:Number(v) for k,v in numeric.items()};s.inputs=dict(s.numeric_inputs)
        d=s.inputs
        for key,options,value in (('shape',e.PATTERN_SHAPES,shape),('pattern_type',e.PATTERN_TYPES,'pattern'),('organic_shape',e.FIELD_SHAPES,'smooth_noise'),('layout',e.LAYOUTS,layout),('result',e.RESULTS,result),
            ('direction',e.DIRECTIONS,'one'),('start_mode',e.STARTS,'profile'),('operation',e.OPERATIONS,'body'),
            ('material',e.MATERIALS,'cells'),('orientation',e.ORIENTATIONS,'fixed'),
            ('layout_orientation',[('tangent','Follow Pattern'),('fixed','Fixed')],'tangent'),
            ('path_orientation',e.PATH_ORIENTATIONS,'tangent'),('preview_mode',e.PREVIEW_MODES,'fast'),
            ('extent1',e.EXTENTS,'distance'),('extent2',e.EXTENTS,'distance'),('boundary',[('rectangle','')],'rectangle')):
            d[key]=Dropdown(options,value)
        for key,value in (('clip_boundary',False),('organic_bridges',False),('reverse',False),('path_reverse',True),('round_corners',False),('preview',True)):
            d[key]=NS(value=value,isVisible=True)
        for key in ('area_group','source_info','cylinder_group','surface_layout','guide1','guide2','guide_reverse','output_group','side2','new_pattern','preview_color'):
            d[key]=NS(isVisible=True)
        d['source']=Select(self.source);d['path']=Select(self.path);d['center_point']=Select()
        d['guide1']=Select();d['guide2']=Select()
        d['bodies']=Select();d['target1']=Select();d['target2']=Select()
        return s

    def test_dialog_path_read_visibility_and_hidden_invalid_fields(self):
        s=self.session()
        for key in ('grid_angle','offset_x','offset_y','spread_radius','start_radius'):
            s.inputs[key].expression='invalid'
        s.inputs['center_point']=Select(object())  # Inactive anchor must not be used.
        s.update_visibility()
        self.assertTrue(s.inputs['path'].isVisible)
        self.assertTrue(s.inputs['path_orientation'].isVisible)
        for key in ('center_point','spread_radius','grid_angle','offset_x','offset_y','start_radius','orientation'):
            self.assertFalse(s.inputs[key].isVisible,key)
        with patch.object(self.feature,'validate'):
            _,settings,cfg=s.read()
        self.assertEqual(settings.layout,'path');self.assertTrue(settings.path_reverse)
        self.assertEqual(settings.path_orientation,'tangent')
        self.assertIsNone(cfg['center_point']);self.assertIs(cfg['path'],self.path)
        self.assertEqual(cfg['_expressions']['grid_angle'],'0 rad')
        self.assertEqual(cfg['_expressions']['start_radius'],'0 cm')
        self.assertEqual(cfg['_expressions']['path_spacing'],'0.8')
        s.inputs['path']=Select()
        with self.assertRaisesRegex(ValueError,'Select one Path'):s.read()
        s.inputs['path']=Select(self.path,self.path)
        with self.assertRaisesRegex(ValueError,'Select one Path'):s.read()

    def test_dialog_switch_to_grid_and_voronoi_restores_existing_controls(self):
        for shape in ('slot','voronoi'):
            s=self.session(layout='path' if shape=='voronoi' else 'rows',shape=shape,result='profiles')
            s.inputs['path_spacing'].expression='invalid'
            s.update_visibility()
            self.assertFalse(s.inputs['path'].isVisible)
            self.assertTrue(s.inputs['center_point'].isVisible)
            self.assertTrue(s.inputs['grid_angle'].isVisible)
            self.assertEqual(s.read()[1].layout,'grid')
            self.assertIsNone(s.read()[2]['path'])
        s=self.session(shape='circle',result='profiles');s.update_visibility()
        self.assertFalse(s.inputs['path_orientation'].isVisible)
        self.assertEqual(s.read()[1].path_orientation,'fixed')


if __name__=='__main__':unittest.main()
