# SPDX-License-Identifier: GPL-3.0-only
"""Run via runpy in Fusion. All CAD lives in a separate unsaved document."""
from dataclasses import replace
import importlib.util
from importlib import import_module
import json
import math
from pathlib import Path
import platform
import sys
from time import perf_counter
import traceback

import adsk.core
import adsk.fusion

root = Path(__file__).resolve().parents[1]
package = '_perfora_surface_test'
for key in tuple(sys.modules):
    if key == package or key.startswith(package + '.'):
        del sys.modules[key]
spec = importlib.util.spec_from_file_location(package, root / 'Perfora/__init__.py',
    submodule_search_locations=[str(root / 'Perfora')])
module = importlib.util.module_from_spec(spec)
sys.modules[package] = module
spec.loader.exec_module(module)
model = import_module(package + '.model')
geo = import_module(package + '.geometry')
surface = import_module(package + '.surface')
preview = import_module(package + '.preview')
app = adsk.core.Application.get()
original = app.activeDocument
doc = None
results = []
output = Path.home() / 'Library/Logs/Perfora/surface-regression.json'
output.parent.mkdir(parents=True, exist_ok=True)


def case(name, action):
    if globals().get('only') and name not in only:
        return
    output.write_text(json.dumps(dict(running=name, tests=results)), encoding='utf-8')
    try:
        results.append(dict(name=name, passed=True, detail=action()))
    except Exception:
        results.append(dict(name=name, passed=False, error=traceback.format_exc()))


def config(**changes):
    data = dict(surface=True, result='extrude', operation='cut', material='cells',
                cut_depth=.32, cylinder_start=0., cylinder_sweep=math.tau, axial_start=0., axial_length=0.)
    data.update(changes)
    return data


def tube(name, rotated=False, solid=False, inner=False, sector=False):
    component = design.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
    component.name = name
    manager = adsk.fusion.TemporaryBRepManager.get()
    a, b = adsk.core.Point3D.create(0, 0, 0), adsk.core.Point3D.create(0, 0, 1.6)
    body = manager.createCylinderOrCone(a, 1.5, b, 1.5)
    if not solid:
        assert manager.booleanOperation(body, manager.createCylinderOrCone(a, 1.3, b, 1.3),
                                        adsk.fusion.BooleanTypes.DifferenceBooleanType)
    if sector:
        box = adsk.core.OrientedBoundingBox3D.create(adsk.core.Point3D.create(1, 1, .8),
            adsk.core.Vector3D.create(1, 0, 0), adsk.core.Vector3D.create(0, 1, 0), 2., 2., 4.)
        assert manager.booleanOperation(body, manager.createBox(box), adsk.fusion.BooleanTypes.IntersectionBooleanType)
    if rotated:
        matrix = adsk.core.Matrix3D.create()
        matrix.setToRotation(.73, adsk.core.Vector3D.create(1, 2, .5), adsk.core.Point3D.create(0, 0, 0))
        matrix.translation = adsk.core.Vector3D.create(3, -2, 4)
        assert manager.transform(body, matrix)
    base = component.features.baseFeatures.add()
    base.startEdit()
    component.bRepBodies.add(body, base)
    base.finishEdit()
    body = base.bodies.item(0)
    face = next(f for f in body.faces if isinstance(f.geometry, adsk.core.Cylinder)
                and abs(f.geometry.radius - (1.3 if inner else 1.5)) < 1e-7)
    return component, body, face


try:
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)
    def basic(shape='circle', trim=False, cone=False,inner=False,rotated=False,parametric=False):
        comp, body, face = tube('Surface '+shape,inner=inner,rotated=rotated)
        if cone:
            manager=adsk.fusion.TemporaryBRepManager.get()
            temp=manager.createCylinderOrCone(adsk.core.Point3D.create(),1.5,adsk.core.Point3D.create(0,0,1.6),1.)
            base=comp.features.baseFeatures.add();base.startEdit()
            comp.bRepBodies.add(temp,base);base.finishEdit()
            body=base.bodies.item(0)
            face=next(f for f in body.faces if isinstance(f.geometry,adsk.core.Cone))
        settings=geo.Settings(shape=shape,size=.35,gap=.18,margin=.1,clip_boundary=trim,staggered=False)
        started=perf_counter()
        prepared=surface.prepare(face,settings,config())
        before=body.volume
        coords=prepared.coordinates
        for i in range(0,len(coords),max(3,(len(coords)//300//3)*3)):
            assert face.isPointOnFace(adsk.core.Point3D.create(*coords[i:i+3]),1e-6),coords[i:i+3]
        if parametric:
            entry=next(m for m in tuple(sys.modules.values()) if str(getattr(m,'__file__',''))==str(root/'Perfora/Perfora.py'))
            _,custom,count=entry.parametric.build(face,settings,config(result='feature',bodies=[body]))
            feature=comp.features.combineFeatures.item(0)
        else:
            _,feature,count=surface.build(face,settings,config())
        result=feature.bodies.item(0)
        assert result.isSolid and result.volume<before
        checked=0
        for i in range(0,len(coords),max(6,(len(coords)//300//6)*6)):
            p=adsk.core.Point3D.create(*coords[i:i+3])
            assert result.pointContainment(p)==adsk.fusion.PointContainment.PointOnPointContainment,(i,p.asArray())
            checked+=1
        if parametric:
            initial=result.volume
            custom.parameters.itemById('size').expression='2.8 mm'
            assert custom.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,custom.errorOrWarningMessage
            assert abs(feature.bodies.item(0).volume-initial)>1e-5
        return dict(holes=count,seconds=perf_counter()-started,rim_samples=checked,parametric=parametric)
    for shape in geo.SHAPE_IDS:
        for trim in (False,True):
            case(shape+'_trim_'+str(trim),lambda shape=shape,trim=trim:basic(shape,trim))
    case('cone',lambda:basic(cone=True))
    for shape in geo.SHAPE_IDS:
        if shape=='voronoi':continue
        for trim in (False,True):
            case('cone_'+shape+'_trim_'+str(trim),lambda shape=shape,trim=trim:basic(shape,trim,cone=True))
    case('cone_voronoi_trim',lambda:basic(shape='voronoi',trim=True,cone=True))
    case('inner_rotated_circle',lambda:basic(inner=True,rotated=True))
    case('inner_rotated_voronoi_trim',lambda:basic(shape='voronoi',trim=True,inner=True,rotated=True))

    case('cone_feature_recompute',lambda:basic(cone=True,parametric=True))

    def freeform(parametric=False):
        comp=design.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
        profiles=[]
        for z,w,h,dx in ((0,3.,2.,0),(.8,3.5,1.6,.1),(1.6,2.4,2.1,.25)):
            pi=comp.constructionPlanes.createInput()
            pi.setByOffset(comp.xYConstructionPlane,adsk.core.ValueInput.createByReal(z))
            plane=comp.constructionPlanes.add(pi)
            sketch=comp.sketches.add(plane)
            sketch.sketchCurves.sketchLines.addTwoPointRectangle(model.point((-w/2+dx,-h/2)),model.point((w/2+dx,h/2)))
            profiles.append(sketch.profiles.item(0))
        data=comp.features.loftFeatures.createInput(adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        for profile in profiles:
            data.loftSections.add(profile)
        loft=comp.features.loftFeatures.add(data)
        body=loft.bodies.item(0)
        face=max((f for f in body.faces if isinstance(f.geometry,adsk.core.NurbsSurface)),key=lambda f:f.area)
        settings=geo.Settings(size=.25,gap=.35,margin=.08,staggered=False,clip_boundary=True)
        cfg=config()
        chart=surface.Chart(face)
        prepared=surface.prepare(face,settings,cfg)
        coords=prepared.coordinates
        for i in range(0,len(coords),max(3,(len(coords)//150//3)*3)):
            assert face.isPointOnFace(adsk.core.Point3D.create(*coords[i:i+3]),1e-6)
        before=body.volume
        if parametric:
            entry=next(m for m in tuple(sys.modules.values()) if str(getattr(m,'__file__',''))==str(root/'Perfora/Perfora.py'))
            _,custom,count=entry.parametric.build(face,settings,config(result='feature',bodies=[body]))
            feature=comp.features.combineFeatures.item(0)
        else:
            _,feature,count=surface.build(face,settings,cfg)
        result=feature.bodies.item(0)
        assert result.isSolid and result.volume<before
        for i in range(0,len(coords),max(6,(len(coords)//150//6)*6)):
            assert result.pointContainment(adsk.core.Point3D.create(*coords[i:i+3]))==adsk.fusion.PointContainment.PointOnPointContainment
        if parametric:
            initial=result.volume
            custom.parameters.itemById('size').expression='1.8 mm'
            assert custom.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,custom.errorOrWarningMessage
            assert abs(feature.bodies.item(0).volume-initial)>1e-5
            initial=feature.bodies.item(0).volume
            comp.constructionPlanes.item(2).definition.offset.expression='20 mm'
            assert custom.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,custom.errorOrWarningMessage
            assert abs(feature.bodies.item(0).volume-initial)>1e-5
        return dict(holes=count,kind=chart.kind,width=chart.width,height=chart.height)
    case('open_freeform_loft',freeform)
    case('freeform_feature_upstream_recompute',lambda:freeform(True))
    def contours():
        comp,body,face=tube('Surface Sketch',rotated=True)
        settings=geo.Settings(size=.3,gap=.18,margin=.1,staggered=False)
        sketch,_,count=surface.build(face,settings,config(result='profiles'))
        assert sketch.sketchCurves.count>=count
        for curve in sketch.sketchCurves:
            evaluator=curve.worldGeometry.evaluator
            ok,a,b=evaluator.getParameterExtents()
            for fraction in (0,.25,.5,.75,1):
                ok,point=evaluator.getPointAtParameter(a+(b-a)*fraction)
                assert ok and face.isPointOnFace(point,1e-6),point.asArray()
        return dict(holes=count,curves=sketch.sketchCurves.count)
    case('surface_3d_sketch_rotated',contours)
    def openings():
        comp,body,face=tube('Existing surface opening')
        manager=adsk.fusion.TemporaryBRepManager.get()
        temp=manager.copy(body)
        box=manager.createBox(adsk.core.OrientedBoundingBox3D.create(adsk.core.Point3D.create(1.4,0,.8),adsk.core.Vector3D.create(1,0,0),adsk.core.Vector3D.create(0,1,0),1.,.7,.5))
        assert manager.booleanOperation(temp,box,adsk.fusion.BooleanTypes.DifferenceBooleanType)
        base=comp.features.baseFeatures.add();base.startEdit()
        comp.bRepBodies.add(temp,base);base.finishEdit()
        body=base.bodies.item(0)
        face=max((f for f in body.faces if isinstance(f.geometry,adsk.core.Cylinder) and abs(f.geometry.radius-1.5)<1e-7),key=lambda f:f.area)
        assert face.loops.count>1
        settings=geo.Settings(shape='voronoi',size=.4,gap=.15,margin=.08,clip_boundary=True)
        prepared=surface.prepare(face,settings,config())
        coords=prepared.coordinates
        for i in range(0,len(coords),max(3,(len(coords)//150//3)*3)):
            assert face.isPointOnFace(adsk.core.Point3D.create(*coords[i:i+3]),1e-6)
        _,feature,count=surface.build(face,settings,config())
        assert feature.bodies.item(0).isSolid
        return dict(holes=count,existing_opening_preserved=True)
    case('trim_existing_opening',openings)

    def cone_distribution():
        comp=design.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
        manager=adsk.fusion.TemporaryBRepManager.get()
        temp=manager.createCylinderOrCone(adsk.core.Point3D.create(),2.,adsk.core.Point3D.create(0,0,3.),1.5)
        base=comp.features.baseFeatures.add();base.startEdit();comp.bRepBodies.add(temp,base);base.finishEdit()
        face=next(f for f in base.bodies.item(0).faces if isinstance(f.geometry,adsk.core.Cone))
        settings=geo.Settings(size=.3,gap=.15,margin=.1,staggered=False)
        rows=surface.prepare(face,settings,config())
        staggered=surface.prepare(face,replace(settings,staggered=True),config())
        signature=lambda p:tuple(sorted(tuple(round(x,6) for x in s.frame[0]) for s in p.sections))
        assert signature(rows)!=signature(staggered),'Rectangular and Staggered produce identical conical sites'
        angular_rows={}
        for section in rows.sections:
            x,y,z=section.frame[0]
            angular_rows.setdefault(round(z,6),[]).append(round(math.atan2(y,x)%math.tau,6))
        counts=[len(values) for values in angular_rows.values()]
        assert len(counts)>2 and max(counts)>min(counts),'Conical rows must adapt to the local circumference'
        assert all(any(abs(a)<1e-5 or abs(a-math.tau)<1e-5 for a in values) for values in angular_rows.values())
        return dict(rectangular=len(rows.sections),staggered=len(staggered.sections),row_counts=counts,different_sites=True)
    case('cone_distribution_changes_sites',cone_distribution)

    def pointed_cone():
        comp=design.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
        manager=adsk.fusion.TemporaryBRepManager.get()
        temp=manager.createCylinderOrCone(adsk.core.Point3D.create(),2.5,adsk.core.Point3D.create(0,0,9.),.088457268)
        base=comp.features.baseFeatures.add();base.startEdit();comp.bRepBodies.add(temp,base);base.finishEdit()
        face=next(f for f in base.bodies.item(0).faces if isinstance(f.geometry,adsk.core.Cone))
        settings=geo.Settings(size=.5,gap=.15,margin=.3,staggered=False)
        cfg=config(cut_depth=.2)
        prepared=surface.prepare(face,settings,cfg)
        rings={}
        for section in prepared.sections:
            rings.setdefault(round(section.frame[0][2],6),[]).append(section)
        counts=[len(rings[z]) for z in sorted(rings)]
        assert counts[0]>=18 and len(prepared.sections)>=120,(counts,len(prepared.sections))
        for group in rings.values():
            assert len(group)%2==0,'A complete row lost its opposite sites'
        _,feature,count=surface.build(face,settings,cfg)
        assert count==len(prepared.sections) and feature.bodies.item(0).isSolid
        assert feature.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
        return dict(holes=count,row_counts=counts,preview_final_match=True,native_cut=True)
    case('pointed_cone_density',pointed_cone)

    def placement_modes():
        details=[]
        for options in (dict(layout='circular',start_radius=.2),dict(grid_angle=.2,offset_x=.1,offset_y=.07),dict(spread_radius=.65)):
            comp,body,face=tube('Surface Placement')
            settings=geo.Settings(size=.2,gap=.18,margin=.05,staggered=False,clip_boundary=True,**options)
            prepared=surface.prepare(face,settings,config())
            _,feature,count=surface.build(face,settings,config())
            assert feature.bodies.item(0).isSolid
            details.append(dict(mode=str(options),holes=count))
        return details
    case('circular_angle_offsets_spread',placement_modes)
    def operations():
        details=[]
        for operation in ('join','intersect','body','component'):
            comp,body,face=tube('Surface '+operation)
            cfg=config(operation=operation,reverse=operation!='join')
            settings=geo.Settings(size=.3,gap=.2,margin=.1,staggered=False)
            _,feature,count=surface.build(face,settings,cfg)
            assert feature.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,feature.errorOrWarningMessage
            assert all(b.isSolid for b in feature.bodies)
            details.append(dict(operation=operation,holes=count))
        return details
    case('native_operations',operations)

    def zone_and_axis():
        comp,body,face=tube('Surface Zone')
        settings=geo.Settings(size=.25,gap=.15,margin=.1,staggered=False,clip_boundary=True)
        cfg=config(cylinder_start=6.1,cylinder_sweep=1.1,axial_start=.2,axial_length=1.1)
        chart=surface.Chart(face)
        opposite=adsk.core.Point3D.create(*chart.frame((6.1+.55+math.pi)*chart.radius,.75)[0])
        prepared=surface.prepare(face,settings,cfg)
        _,feature,count=surface.build(face,settings,cfg)
        assert feature.bodies.item(0).pointContainment(opposite)==adsk.fusion.PointContainment.PointOnPointContainment
        return dict(holes=count,wrapped_zone=True,opposite_wall_intact=True)
    case('bounded_wrapped_zone',zone_and_axis)
    def cached_preview():
        comp,body,face=tube('Dense Surface Preview')
        settings=geo.Settings(shape='hexagon',size=.1,gap=.05,margin=.04,staggered=False,clip_boundary=True)
        renderer=preview.Renderer()
        try:
            count=renderer.show(face,settings,config())
            cold=renderer.last_seconds
            builds=renderer.layout_builds
            for _ in range(10):
                assert renderer.show(face,settings,config(),color='cyan')==count
            assert renderer.layout_builds==builds
            cached=renderer.last_seconds
            assert cached<.1
            _,feature,actual=model.build(face,settings,config())
            assert count==actual and feature.bodies.item(0).isSolid
            return dict(holes=count,cold_seconds=cold,cached_seconds=cached,no_rebuild_on_color=True)
        finally:
            renderer.reset()
    case('dense_preview_cache',cached_preview)
    def parametric_surface():
        entry=next(m for m in tuple(sys.modules.values()) if str(getattr(m,'__file__',''))==str(root/'Perfora/Perfora.py'))
        feature=entry.parametric
        comp,body,face=tube('Surface Feature')
        settings=entry.Settings(shape='hexagon',size=.35,gap=.18,margin=.1,clip_boundary=True,staggered=False)
        cfg=surface.normalized(config(result='feature',bodies=[body]),comp)
        _,custom,count=feature.build(face,settings,cfg)
        assert custom.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,custom.errorOrWarningMessage
        before=sum(b.volume for b in comp.bRepBodies if b.isVisible)
        custom.parameters.itemById('size').expression='2.5 mm'
        after=sum(b.volume for b in comp.bRepBodies if b.isVisible)
        assert custom.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,custom.errorOrWarningMessage
        assert abs(before-after)>1e-5,(before,after)
        custom.parameters.itemById('cylinder_sweep').expression='180 deg'
        assert custom.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,custom.errorOrWarningMessage
        assert design.computeAll()
        return dict(holes=count,before=before,after=after,parameters=custom.parameters.count)
    case('feature_natural_recompute',parametric_surface)

finally:
    if doc and doc.isValid:
        doc.close(False)
    if original and original.isValid:
        original.activate()
    output.write_text(json.dumps(dict(version=app.version,tests=results),indent=2),encoding='utf-8')
    print(json.dumps(dict(total=len(results),passed=sum(r['passed'] for r in results),failed=[dict(name=r['name'],error=r['error'].splitlines()[-1]) for r in results if not r['passed']])))
