# SPDX-License-Identifier: GPL-3.0-only
"""Execute actual adapter/Feature/UI method bodies against narrow offline doubles.

AST loading avoids importing adsk or contacting Fusion. These verify contracts,
not native transactions, event order or Custom Feature registration.
"""
import ast
from dataclasses import replace
import json
import math
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from Perfora.geometry import Settings, LENGTH_SHAPES, generate
from Perfora.distributions import VARIANT_PARAMETERS, LAYOUT_PARAMETERS
from Perfora.feature_data import metadata, decode

ROOT = Path(__file__).resolve().parents[1]


def definitions(file, namespace, methods=()):
    tree=ast.parse((ROOT/'Perfora'/file).read_text())
    nodes=[]
    for node in tree.body:
        if isinstance(node,(ast.Assign,ast.AnnAssign,ast.AugAssign,ast.FunctionDef)):
            nodes.append(node)
        elif isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Attribute) and node.value.func.attr=='update':
            nodes.append(node)
        elif isinstance(node,ast.ClassDef) and node.name=='Session':
            node.body=[m for m in node.body if isinstance(m,ast.FunctionDef) and m.name in methods]
            nodes.append(node)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(ROOT/'Perfora'/file),'exec'),namespace)
    return NS(**namespace)


class Entity:
    isValid=True
    nativeObject=None
    assemblyContext=None


class Plane(Entity):
    pass


class SketchCurve(Entity):
    pass


class BRepEdge(Entity):
    pass


ADSK=NS(fusion=NS(ConstructionPlane=Plane,SketchCurve=SketchCurve,BRepEdge=BRepEdge),core=NS(Cylinder=type('Cylinder',(),{}),Cone=type('Cone',(),{})))
SURFACE=NS(ZONE_PARAMETERS={},is_curved=lambda source:False,supported=lambda source:False)


def model_definitions():
    return definitions('model.py',dict(adsk=ADSK,replace=replace,math=math,json=json))


def feature_definitions(model=None):
    return definitions('feature.py',dict(Settings=Settings,VARIANT_PARAMETERS=VARIANT_PARAMETERS,
        decode=decode,metadata=metadata,surface=SURFACE,model=model or NS(native=lambda x:x),replace=replace,json=json,math=math,Path=Path,adsk=ADSK))


class Collection:
    def __init__(self,values): self.values=values
    def itemById(self,key): return self.values.get(key)


def custom_feature(f, old=False, **changes):
    s=replace(Settings(),**changes)
    cfg=dict(center_point=None,boundary='rectangle',width=4,height=3,result='feature',
             material='cells',operation='body',direction='one',reverse=False,bodies=[],
             start='0 mm',distance1='2 mm',distance2='2 mm')
    data=f.metadata(s,cfg)
    params={k:NS(value=getattr(s,k) if hasattr(s,k) else
                 (.2 if k.startswith('distance') else 0 if k=='start' else cfg[k]),
                 expression='0') for k in f.PARAMETERS}
    if old:
        for key in tuple(VARIANT_PARAMETERS)+('start_radius','spread_radius'):
            params.pop(key)
            data['settings'].pop(key)
        for key in ('guide_rows','guide_reverse','guide1','guide2'):
            data['settings'].pop(key,None)
    source=Entity()
    return NS(parameters=Collection(params),dependencies=Collection({'source':NS(entity=source)}),
              customNamedValues=NS(value=lambda key:json.dumps(data))),data


class AdapterAndFeatureTests(unittest.TestCase):
    def test_sketch_snapshot_serializes_prepared_guides_without_live_references(self):
        m=model_definitions()
        s=replace(Settings(),layout='between_curves',guide1=((0,0),(1,0)),guide2=((0,1),(1,1)))
        config=dict(guide1=Entity(),guide2=Entity(),bodies=[Entity()],center_point=Entity(),
                    target1=Entity(),target2=Entity(),_expressions={'size':'5 mm'},result='profiles')
        snapshot=json.loads(json.dumps(m.sketch_metadata(s,config)))
        self.assertNotIn('guide1',snapshot)
        self.assertNotIn('guide2',snapshot)
        self.assertEqual(snapshot['result'],'profiles')
        self.assertNotIn('center_point',snapshot)

    def test_feature_old_nodes_use_defaults_without_missing_parameter_failure(self):
        f=feature_definitions()
        custom,_=custom_feature(f,old=True)
        source,s,cfg=f.read(custom)
        self.assertEqual(s,Settings())
        self.assertIsNone(cfg['guide1'])
        custom.parameters.values.pop('gap')
        with self.assertRaisesRegex(ValueError,'missing parameter: gap'): f.read(custom)

    def test_feature_round_trip_preserves_variants_and_excludes_live_entities(self):
        f=feature_definitions()
        for layout in LAYOUT_PARAMETERS:
            custom,data=custom_feature(f,layout=layout,bond_shift=.25,fan_rays=17,guide_rows=7)
            if layout=='between_curves':
                for key in ('guide1','guide2'): custom.dependencies.values[key]=NS(entity=Entity())
            source,s,cfg=f.read(custom)
            self.assertEqual(s.layout,layout)
            self.assertEqual(s.bond_shift,.25)
            self.assertEqual(s.fan_rays,17)
            self.assertEqual(s.guide_rows,7)
            cfg.update(guide1=Entity(),guide2=Entity())
            encoded=json.dumps(f.metadata(s,cfg))
            self.assertNotIn('guide1',json.loads(encoded)['config'])
        custom,_=custom_feature(f,layout='between_curves')
        with self.assertRaisesRegex(ValueError,'guide is missing'): f.read(custom)
        self.assertEqual(f.guide_entities(custom,allow_missing=True),(None,None))

    def test_edit_old_feature_keeps_new_values_and_manages_guide_dependencies(self):
        f=feature_definitions(NS(native=lambda x:x,guide_reference=lambda entity,comp:entity))
        custom,data=custom_feature(f,old=True)
        custom.parentComponent=NS()
        saved={'perfora':json.dumps(data)}
        custom.customNamedValues=NS(value=lambda key:saved[key],
                                   addOrSetValue=lambda key,value:saved.update({key:value}))
        def add(key,entity):
            dependency=NS(entity=entity,deleteMe=lambda:custom.dependencies.values.pop(key))
            custom.dependencies.values[key]=dependency
            return dependency
        custom.dependencies.add=add
        f.update.__globals__['rebuild']=lambda custom,cache:42
        cfg=data['config'].copy()
        cfg.update(bodies=[],center_point=None,guide1=Entity(),guide2=Entity())
        s=replace(Settings(),layout='between_curves',bond_shift=.25,guide_rows=7)
        self.assertEqual(f.update(custom,s,cfg),42)
        self.assertEqual(f.read(custom)[1].guide_rows,7)
        self.assertIsNone(custom.parameters.itemById('guide_rows'))
        self.assertEqual(f.guide_entities(custom),(cfg['guide1'],cfg['guide2']))
        replacement=Entity()
        cfg['guide1']=replacement
        f.update(custom,s,cfg)
        self.assertIs(f.guide_entities(custom)[0],replacement)
        f.update(custom,replace(s,layout='running_bond'),cfg)
        self.assertIsNone(custom.dependencies.itemById('guide1'))
        self.assertEqual(f.read(custom)[1].bond_shift,.25)

    def test_adapter_checks_plane_and_uses_native_coordinates_and_trimmed_evaluator(self):
        m=model_definitions()
        comp=NS()
        comp.parentDesign=NS(rootComponent=comp)
        frame=((3,4,5),(0,0,1),(1,0,0))
        def guide(klass,points):
            g=klass()
            evaluator=NS(getParameterExtents=lambda:(True,2,3),
                         getStrokes=lambda a,b,t:(True,[NS(asArray=lambda p=p:p) for p in points]))
            g.evaluator=evaluator
            g.geometry=NS(evaluator=evaluator)
            g.worldGeometry=None  # Deliberately unavailable: no root-space assumption.
            g.parentSketch=NS(parentComponent=comp,sketchToModelSpace=lambda p:p)
            g.body=NS(parentComponent=comp)
            return g
        for klass in (SketchCurve,BRepEdge):
            g=guide(klass,((3,4,5),(4,4,7)))
            self.assertEqual(m.guide_strokes(g,frame,comp),((0,0),(2,1)))
            g=guide(klass,((3,4,5),(4,4.1,7)))
            with self.assertRaisesRegex(ValueError,'Profiles plane'): m.guide_strokes(g,frame,comp)
            g.parentSketch.parentComponent=g.body.parentComponent=NS()
            with self.assertRaisesRegex(ValueError,'same component'): m.guide_reference(g,comp)
        with self.assertRaises(ValueError): m.guide_strokes(None,frame,comp)


class Control:
    def __init__(self,value=0):
        self.value=value
        self.expression=str(value)
        self.model_expression=str(value)
        self.default_expression=str(value)
        self.unit=''
        self.isVisible=True
        self.isValidExpression=True
        self.name='Field'
        self.tooltip=''
        self.selectionCount=0
        self.selectedItem=NS(index=0)
        self.listItems=NS(item=self.item)
        self._selected=[]
    def item(self,i):
        parent=self
        class Item:
            @property
            def isSelected(self): return parent.selectedItem.index==i
            @isSelected.setter
            def isSelected(self,v):
                if v: parent.selectedItem.index=i
        return Item()
    def selection(self,i): return NS(entity=self._selected[i])
    def addSelection(self,e): self._selected.append(e); self.selectionCount=len(self._selected)
    def clearSelection(self): self._selected=[]; self.selectionCount=0


class DialogContractTests(unittest.TestCase):
    def session(self):
        f=feature_definitions()
        f.validate=lambda *args:None
        model=NS(native=lambda x:x,source_component=lambda x:NS(),point_position=lambda *args:None,
                 guide_reference=lambda *args:None,source_support_body=lambda x:None)
        ui=definitions('Perfora.py',dict(math=math,Path=Path,Settings=Settings,LENGTH_SHAPES=LENGTH_SHAPES,
                       VARIANT_PARAMETERS=VARIANT_PARAMETERS,LAYOUT_PARAMETERS=LAYOUT_PARAMETERS,
                       multi_region=NS(sources=lambda selected:selected),surface=SURFACE,parametric=f,model=model,adsk=ADSK),
                       methods=('chosen','selected_source','selected_sources','legacy_spread_radius','dimension_id','update_visibility','read','restore_feature'))
        s=ui.Session()
        s.updating=False
        s._extrude_inputs=None
        s._planar_material=None
        s.edited_feature=None
        s.surface_choices=ui.SURFACE_LAYOUTS
        s.inputs={}
        s.numeric_inputs={}
        # Extract constructor declarations so new/missing controls cannot be
        # silently absent in the offline fixture. No constructor/API execution.
        for key in ('area_group','height','shape','shape_angle','result','material','operation','direction','boundary',
                    'source_info','cylinder_group','surface_layout','path','path_reverse','path_orientation','layout','orientation','source','clip_boundary','round_corners','seed','new_pattern','irregularity',
                    'center_point','guide1','guide2','guide_reverse','start_mode','reverse','side2','bodies','output_group',
                    'preview','preview_mode','preview_color','distance1','distance2','taper1','taper2','start','target1',
                    'target2','extent1','extent2','object_offset1','object_offset2'):
            s.inputs[key]=Control()
        values=dict(Settings().__dict__,width=4,height=3,distance1=.2,distance2=.2,taper1=0,taper2=0,
                    object_offset1=0,object_offset2=0,start=0,star_ratio=45,irregularity=80)
        for fields in (ui.SIZE_FIELDS,ui.LENGTH_FIELDS,ui.AREA_FIELDS):
            for key in fields: values[key]=.5 if fields==ui.SIZE_FIELDS else 1 if fields==ui.LENGTH_FIELDS else 4
        for key,value in values.items():
            if isinstance(value,(float,int)) and not isinstance(value,bool):
                s.inputs[key]=s.numeric_inputs[key]=Control(value)
        source=Plane()
        s.inputs['source'].addSelection(source)
        s.inputs['preview'].value=False
        s.units=NS(evaluateExpression=lambda expression,unit:float(expression))
        s.update_visibility()
        return ui,s

    def test_inferred_objects_follow_single_source_replacement(self):
        ui,s=self.session()
        first=s.inputs['source'].selection(0).entity
        second=Plane()
        bodies={first:Entity(),second:Entity()}
        ui.Session.update_visibility.__globals__['model'].source_support_body=lambda source:bodies[source]
        s._auto_bodies=[]
        s.inputs['result'].selectedItem.index=1  # Extrude
        s.inputs['operation'].selectedItem.index=1  # Cut
        s.update_visibility()
        self.assertIs(s.inputs['bodies'].selection(0).entity,bodies[first])
        s.inputs['source'].clearSelection();s.inputs['source'].addSelection(second)
        s.update_visibility()
        self.assertEqual(s.inputs['bodies'].selectionCount,1)
        self.assertIs(s.inputs['bodies'].selection(0).entity,bodies[second])

    def choose(self,s,ui,key):
        s.inputs['layout'].selectedItem.index=next(i for i,(k,_) in enumerate(ui.LAYOUTS) if k==key)
        s.update_visibility()

    def test_visibility_parameter_reading_and_no_silent_grid_fallback(self):
        ui,s=self.session()
        for key in ('guide1','guide2'): s.inputs[key].addSelection(Entity())
        for layout in LAYOUT_PARAMETERS:
            self.choose(s,ui,layout)
            self.assertEqual(s.read()[1].layout,layout)
            for key in VARIANT_PARAMETERS:
                self.assertEqual(s.inputs[key].isVisible,key in LAYOUT_PARAMETERS[layout],(layout,key))
            self.assertEqual(s.inputs['guide1'].isVisible,layout=='between_curves')
            self.assertEqual(s.inputs['seed'].isVisible,layout=='poisson')
            self.assertEqual(s.inputs['start_radius'].isVisible,layout=='fan')
            self.assertEqual(s.inputs['orientation'].isVisible,False)
        s.inputs['fan_angular_step'].value=.2
        self.choose(s,ui,'fan')
        self.assertFalse(s.inputs['fan_rays'].isVisible)
        s.inputs['fan_rays'].isValidExpression=False
        self.assertEqual(s.read()[1].fan_rays,12)
        s.inputs['wave_length'].isValidExpression=False
        self.choose(s,ui,'running_bond')
        self.assertEqual(s.read()[1].wave_length,Settings().wave_length)
        self.choose(s,ui,'wave')
        with self.assertRaises(ValueError): s.read()

    def test_between_selection_integer_validation_and_scope_only_fields(self):
        ui,s=self.session()
        self.choose(s,ui,'between_curves')
        with self.assertRaisesRegex(ValueError,'two open planar guides'): s.read()
        for key in ('guide1','guide2'): s.inputs[key].addSelection(Entity())
        s.inputs['guide_rows'].value=2.5
        with self.assertRaisesRegex(ValueError,'integer'): s.read()
        s.inputs['guide_rows'].value=5
        for key in ('grid_angle','offset_x','offset_y'):
            s.inputs[key].isValidExpression=False
        self.assertEqual(s.read()[1].offset_x,0)
        s.inputs['spread_radius'].value=1
        s.update_visibility()
        self.assertFalse(s.inputs['offset_x'].isVisible)
        self.assertEqual(s.read()[1].spread_radius,0)

    def test_optional_guides_and_path_survive_hiding_but_respect_clear(self):
        ui,s=self.session()
        path=Entity()
        self.choose(s,ui,'path');s.inputs['path'].addSelection(path)
        self.choose(s,ui,'wave')
        s.inputs['path'].clearSelection()  # Native Fusion clears hidden selection inputs.
        self.choose(s,ui,'path')
        self.assertIs(s.inputs['path'].selection(0).entity,path)
        s.inputs['path'].clearSelection()  # An explicit user clear must remain cleared.
        self.choose(s,ui,'wave');self.choose(s,ui,'path')
        self.assertEqual(s.inputs['path'].selectionCount,0)
        guides=(Entity(),Entity())
        self.choose(s,ui,'between_curves')
        for key,guide in zip(('guide1','guide2'),guides):s.inputs[key].addSelection(guide)
        self.choose(s,ui,'running_bond')
        for key in ('guide1','guide2'):s.inputs[key].clearSelection()
        self.choose(s,ui,'between_curves')
        for key,guide in zip(('guide1','guide2'),guides):
            self.assertIs(s.inputs[key].selection(0).entity,guide)

    def test_hidden_spread_does_not_block_edit_or_lose_legacy_expression(self):
        ui,s=self.session()
        custom,_=custom_feature(ui.parametric)
        s.edited_feature=custom
        s.inputs['result'].selectedItem.index=2
        s.inputs['operation'].selectedItem.index=3
        s.inputs['spread_radius'].isValidExpression=False
        self.assertEqual(s.read()[1].spread_radius,0)
        parameter=custom.parameters.itemById('spread_radius')
        parameter.value=.8;parameter.expression='LegacyRadius'
        _,settings,config=s.read()
        self.assertEqual(settings.spread_radius,.8)
        self.assertEqual(config['_expressions']['spread_radius'],'LegacyRadius')

    def test_feature_restore_retains_new_and_old_distribution_values(self):
        ui,s=self.session()
        for layout in ('grid','circular')+tuple(LAYOUT_PARAMETERS):
            custom,data=custom_feature(ui.parametric,layout=layout,bond_shift=.25)
            s.edited_feature=custom
            s.restore_feature()
            self.assertEqual(s.chosen('layout',ui.LAYOUTS),'staggered' if layout=='grid' else layout)
            self.assertEqual(s.inputs['bond_shift'].value,.25)
        custom,_=custom_feature(ui.parametric,old=True)
        s.edited_feature=custom
        s.restore_feature()
        self.assertEqual(s.inputs['bond_shift'].value,Settings().bond_shift)


if __name__=='__main__': unittest.main()
