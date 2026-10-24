# SPDX-License-Identifier: GPL-3.0-only
"""Combined release CAD acceptance; disposable document per case, JSON evidence."""
from dataclasses import replace
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
entry = next(m for m in tuple(sys.modules.values()) if str(getattr(m, '__file__', '')) == str(root/'Perfora/Perfora.py'))
model, feature, surface, multi = entry.model, entry.parametric, entry.surface, entry.multi_region
geo = sys.modules[entry.Settings.__module__]
app = adsk.core.Application.get()
original = app.activeDocument
output = Path.home()/'Library/Logs/Perfora/release-integration.json'
output.parent.mkdir(parents=True, exist_ok=True)
results = []


def config(**changes):
    result = dict(surface=True, boundary='rectangle', width=4., height=3., result='extrude',
                  material='cells', operation='cut', direction='one', reverse=True, start='0 mm',
                  distance1='2 mm', distance2='2 mm', extent1='distance', extent2='distance',
                  taper1='0 deg', taper2='0 deg', bodies=[], center_point=None,
                  cylinder_start=0., cylinder_sweep=math.tau, axial_start=0., axial_length=0.)
    result.update(changes)
    return result


def face_fixture(component, kind, x=0):
    manager = adsk.fusion.TemporaryBRepManager.get()
    if kind != 'freeform':
        a, b = adsk.core.Point3D.create(x, 0, 0), adsk.core.Point3D.create(x, 0, 2.4)
        outer = manager.createCylinderOrCone(a, 1.4, b, 1.4 if kind == 'cylinder' else .8)
        inner = manager.createCylinderOrCone(a, 1.22, b, 1.22 if kind == 'cylinder' else .62)
        assert manager.booleanOperation(outer, inner, adsk.fusion.BooleanTypes.DifferenceBooleanType)
        base = component.features.baseFeatures.add(); assert base.startEdit()
        component.bRepBodies.add(outer, base); assert base.finishEdit()
        body = base.bodies.item(0)
        face = max((f for f in body.faces if multi.source_kind(f) == kind), key=lambda f:f.area)
        return body, face
    profiles = []
    for z, w, h, dx in ((0,3.,2.,0),(.9,3.5,1.6,.1),(2.4,2.4,2.1,.25)):
        data=component.constructionPlanes.createInput()
        data.setByOffset(component.xYConstructionPlane, model.value(str(z)+' cm'))
        plane=component.constructionPlanes.add(data)
        sketch=component.sketches.addWithoutEdges(plane)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(model.point((-w/2+dx+x,-h/2)),model.point((w/2+dx+x,h/2)))
        profiles.append(sketch.profiles.item(0)); sketch.isVisible=False
    data=component.features.loftFeatures.createInput(adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    for profile in profiles:data.loftSections.add(profile)
    loft=component.features.loftFeatures.add(data);body=loft.bodies.item(0)
    return body,max((f for f in body.faces if isinstance(f.geometry,adsk.core.NurbsSurface)),key=lambda f:f.area)


def healthy(custom):
    assert custom.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, custom.errorOrWarningMessage
    for item in custom.features:
        if hasattr(item, 'healthState'): assert item.healthState != adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState, item.name


def case(name, action):
    if globals().get('only_cases') and name not in only_cases:return
    doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    started=perf_counter()
    try:
        design=adsk.fusion.Design.cast(app.activeProduct)
        detail=action(design.rootComponent)
        results.append(dict(name=name,passed=True,seconds=perf_counter()-started,detail=detail))
    except Exception:
        results.append(dict(name=name,passed=False,seconds=perf_counter()-started,error=traceback.format_exc()))
    finally:
        doc.close(False)
        if original: original.activate()
        output.write_text(json.dumps(dict(fusion=app.version,platform=platform.platform(),addon=str(root/'Perfora'),
            passed=all(t['passed'] for t in results),tests=results),indent=2),encoding='utf-8')


def single(component, kind, layout):
    body,source=face_fixture(component,kind)
    s=geo.Settings(layout=layout,size=.3,gap=.22,margin=.12,clip_boundary=True,limit=5000,
                   wave_amplitude=.15,wave_length=1.8,chevron_angle=.4)
    cfg=config(bodies=[body])
    renderer=entry.Renderer()
    try:
        count=renderer.show(source,s,cfg);builds=renderer.layout_builds
        first=renderer.last_seconds
        renderer.show(source,s,cfg,color='cyan')
        assert renderer.layout_builds==builds
        before=body.volume
        _,result,actual=model.build(source,s,cfg)
        assert count==actual and count>5,(count,actual)
        assert body.isSolid and 0<body.volume<before
        assert result.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
        return dict(cells=count,fast_seconds=first,cached_seconds=renderer.last_seconds,volume_before=before,volume_after=body.volume)
    finally:renderer.reset()


for kind in ('cylinder','cone','freeform'):
    for layout in surface.sg.SURFACE_DISTRIBUTIONS[kind]:
        case(kind+'_'+layout,lambda c,k=kind,l=layout:single(c,k,l))


def several(component,kind,result):
    body1,first=face_fixture(component,kind)
    body2,second=face_fixture(component,kind,x=4)
    cfg=config(result=result,bodies=[body2,body1])
    s=geo.Settings(layout='running_bond',size=.35,gap=.3,margin=.12,clip_boundary=True,limit=5000)
    renderer=entry.Renderer()
    try:
        count=renderer.show([first,second],s,cfg)
        builds=renderer.layout_builds;renderer.show([first,second],s,cfg,color='cyan')
        assert renderer.layout_builds==builds
        before=(body1.volume,body2.volume)
        build = feature.build if result == 'feature' else model.build
        _,output,actual=build([first,second],s,cfg)
        assert actual==count
        assert all(b.isSolid and 0<b.volume<v for b,v in zip((body1,body2),before))
        if result=='feature':
            healthy(output)
            assert len(feature.source_entities(output))==2
            old=sum(b.volume for b in (body1,body2))
            output.parameters.itemById('size').expression='3 mm'
            component.parentDesign.computeAll();healthy(output)
            assert abs(sum(b.volume for b in (body1,body2))-old)>1e-5
        return dict(cells=count,volume_before=before,volume_after=(body1.volume,body2.volume))
    finally:renderer.reset()

for kind in ('cylinder','cone','freeform'):
    for result in ('extrude','feature'):
        case('multi_'+kind+'_'+result,lambda c,k=kind,r=result:several(c,k,r))


def same_body(component, result):
    manager=adsk.fusion.TemporaryBRepManager.get()
    def cylinder(z0,z1,radius):
        return manager.createCylinderOrCone(adsk.core.Point3D.create(0,0,z0),radius,
            adsk.core.Point3D.create(0,0,z1),radius)
    body=cylinder(0,2.4,1.4)
    assert manager.booleanOperation(body,cylinder(2.4,4.8,.9),adsk.fusion.BooleanTypes.UnionBooleanType)
    assert manager.booleanOperation(body,cylinder(0,4.8,.7),adsk.fusion.BooleanTypes.DifferenceBooleanType)
    base=component.features.baseFeatures.add();base.startEdit();component.bRepBodies.add(body,base);base.finishEdit()
    body=base.bodies.item(0)
    faces=[face for face in body.faces if multi.source_kind(face)=='cylinder' and face.geometry.radius>.8]
    assert len(faces)==2
    cfg=config(result=result,bodies=[body],distance1='8 mm')
    s=geo.Settings(layout='running_bond',size=.3,gap=.3,margin=.25,clip_boundary=True,limit=5000)
    before=body.volume
    build=feature.build if result=='feature' else model.build
    _,output,count=build(faces,s,cfg)
    assert body.isSolid and 0<body.volume<before
    if result=='feature':
        healthy(output);old=body.volume
        output.parameters.itemById('size').expression='2.5 mm'
        component.parentDesign.computeAll();healthy(output)
        assert abs(body.volume-old)>1e-5
    return dict(cells=count,volume_before=before,volume_after=body.volume)

for result in ('extrude','feature'):
    case('multi_cylinder_shared_body_'+result,lambda c,r=result:same_body(c,r))


def mixed(component):
    _,cylinder=face_fixture(component,'cylinder')
    _,cone=face_fixture(component,'cone',4)
    plane=next(f for f in cylinder.body.faces if multi.source_kind(f)=='plane')
    for pair in ([plane,cylinder],[cylinder,cone],[cone,plane]):
        try:multi.sources(pair)
        except ValueError as error:assert 'one surface type' in str(error)
        else:raise AssertionError('Mixed surfaces accepted')
    for kind,layout in (('cylinder','chevron'),('cone','wave'),('freeform','fan')):
        try:surface.sg.validate_distribution(kind,geo.Settings(layout=layout))
        except ValueError:pass
        else:raise AssertionError('Unsupported motif accepted')
    return dict(mixed_pairs_rejected=3,invalid_motifs_rejected=3)
case('homogeneous_selection_and_motifs',mixed)
print('PERFORA_RELEASE_INTEGRATION',str(output))
