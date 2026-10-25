# SPDX-License-Identifier: GPL-3.0-only
"""Organic CAD acceptance using the actually registered add-in and disposable docs.

Run via runpy.run_path with optional shapes/kinds/modes subsets. Outputs JSON,
real viewport PNGs and local F3D archives outside the repository. Interactive
OK/Cancel/Edit/Undo are deliberately covered by fusion_organic_ui.py instead.
"""
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

root=Path(__file__).resolve().parents[1]
entry=next(m for m in tuple(sys.modules.values()) if str(getattr(m,'__file__',''))==str(root/'Perfora/Perfora.py'))
geo=sys.modules[entry.Settings.__module__]
app=adsk.core.Application.get()
output=Path.home()/'Library/Logs/Perfora/organic'
output.mkdir(parents=True,exist_ok=True)
original=app.activeDocument
original_state=(original.name,original.isModified)
report=dict(fusion=app.version,os=platform.platform(),addon=str(root/'Perfora'),passed=False,cases=[])


def config(**changes):
    result=dict(boundary='rectangle',width=5.,height=4.,result='extrude',material='cells',
        operation='cut',direction='one',reverse=True,start='0 mm',distance1='2.2 mm',distance2='2 mm',
        extent1='distance',extent2='distance',taper1='0 deg',taper2='0 deg',bodies=[],center_point=None,
        cylinder_start=0.,cylinder_sweep=math.tau,axial_start=0.,axial_length=0.)
    result.update(changes);return result


def fixture(component,kind):
    if kind=='plane':
        sketch=component.sketches.addWithoutEdges(component.xYConstructionPlane)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(entry.model.point((-2.5,-2)),entry.model.point((2.5,2)))
        data=component.features.extrudeFeatures.createInput(sketch.profiles.item(0),adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        data.setDistanceExtent(False,entry.model.value('2 mm'))
        body=component.features.extrudeFeatures.add(data).bodies.item(0);sketch.isVisible=False
        return body,max((f for f in body.faces if isinstance(f.geometry,adsk.core.Plane)),key=lambda f:f.pointOnFace.z)
    if kind!='freeform':
        manager=adsk.fusion.TemporaryBRepManager.get();a,b=entry.model.point((0,0)),adsk.core.Point3D.create(0,0,3.)
        outer=manager.createCylinderOrCone(a,1.8,b,1.8 if kind=='cylinder' else 1.)
        inner=manager.createCylinderOrCone(a,1.62,b,1.62 if kind=='cylinder' else .82)
        assert manager.booleanOperation(outer,inner,adsk.fusion.BooleanTypes.DifferenceBooleanType)
        base=component.features.baseFeatures.add();assert base.startEdit()
        component.bRepBodies.add(outer,base);assert base.finishEdit();body=base.bodies.item(0)
        return body,max((f for f in body.faces if entry.multi_region.source_kind(f)==kind),key=lambda f:f.area)
    profiles=[]
    for z,w,h,dx in ((0,4.,2.5,0),(1.3,4.4,2.1,.1),(3.,3.4,2.7,.25)):
        data=component.constructionPlanes.createInput();data.setByOffset(component.xYConstructionPlane,entry.model.value(str(z)+' cm'))
        plane=component.constructionPlanes.add(data);sketch=component.sketches.addWithoutEdges(plane)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(entry.model.point((-w/2+dx,-h/2)),entry.model.point((w/2+dx,h/2)))
        profiles.append(sketch.profiles.item(0));sketch.isVisible=False
    data=component.features.loftFeatures.createInput(adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    for profile in profiles:data.loftSections.add(profile)
    body=component.features.loftFeatures.add(data).bodies.item(0)
    return body,max((f for f in body.faces if isinstance(f.geometry,adsk.core.NurbsSurface)),key=lambda f:f.area)


def healthy(design):
    for item in design.timeline:
        if hasattr(item.entity,'healthState'):
            assert item.entity.healthState!=adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState,(item.entity.name,item.entity.errorOrWarningMessage)
    for body in design.rootComponent.bRepBodies:assert body.isSolid and body.volume>0


def save():
    (output/globals().get('report_name','cad-regression.json')).write_text(json.dumps(report,indent=2))


def run_case(shape,kind,mode,trim):
    doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    detail=dict(shape=shape,kind=kind,mode=mode,trim=trim,passed=False)
    report['cases'].append(detail);started=perf_counter();renderer=None
    try:
        design=adsk.fusion.Design.cast(app.activeProduct);component=design.rootComponent
        body,face=fixture(component,kind);volume=body.volume;lumps=body.lumps.count
        cfg=config(result=mode,bodies=[body],surface=kind!='plane')
        if kind=='freeform':cfg['distance1']='8 mm'
        s=geo.Settings(shape=shape,size=.45,gap=.055,margin=.07,clip_boundary=trim,
                       organic_open=60,organic_direction=math.pi/2 if shape=='directional_fibers' else 0)
        renderer=entry.Renderer();t=perf_counter()
        count=renderer.show(face,s,cfg)
        detail.update(holes=count,fast_seconds=perf_counter()-t)
        assert count>1,(kind,shape,count)
        renderer.clear();t=perf_counter()
        if mode=='feature':
            sketch,custom,built=entry.parametric.build(face,s,cfg)
            healthy(design);assert built==count,(built,count)
            assert body.volume<volume and body.lumps.count==lumps
            before=body.volume
            key='organic_gradient' if shape=='blue_noise' else 'organic_open'
            p=custom.parameters.itemById(key);p.value+=5
            assert design.computeAll();healthy(design)
            assert abs(body.volume-before)>1e-7,(shape,'no real recompute',before,body.volume)
            detail.update(recompute_parameter=key,recompute_volume=body.volume,initial_volume=before)
            if globals().get('archive',False):
                filename=str(output/(kind+'-'+shape+('-trim' if trim else '-whole')+'.f3d'))
                manager=design.exportManager;assert manager.execute(manager.createFusionArchiveExportOptions(filename))
                reopened=app.importManager.importToNewDocument(app.importManager.createFusionArchiveImportOptions(filename))
                try:
                    reopened_design=adsk.fusion.Design.cast(app.activeProduct);healthy(reopened_design)
                    node=reopened_design.rootComponent.features.customFeatures.item(0)
                    p=node.parameters.itemById(key);v=sum(b.volume for b in reopened_design.rootComponent.bRepBodies)
                    p.value+=3;assert reopened_design.computeAll();healthy(reopened_design)
                    assert abs(sum(b.volume for b in reopened_design.rootComponent.bRepBodies)-v)>1e-7
                    detail['archive_recompute']=True
                finally:reopened.close(False);doc.activate()
        else:
            sketch,native,built=entry.model.build(face,s,cfg)
            assert built==count,(shape,kind,built,count)
            if mode=='profiles':assert body.volume==volume
            else:assert 0<body.volume<volume and body.lumps.count==lumps
            healthy(design)
        detail['build_seconds']=perf_counter()-t
        if globals().get('capture',False):
            app.activeViewport.fit()
            filename=str(output/(kind+'-'+shape+'-'+mode+('-trim' if trim else '-whole')+'.png'))
            assert app.activeViewport.saveAsImageFile(filename,1400,1000)
            detail['screenshot']=filename
        detail['passed']=True
    except Exception:detail['error']=traceback.format_exc()
    finally:
        if renderer:renderer.clear()
        doc.close(False);original.activate();detail['seconds']=perf_counter()-started;save()


if not globals().get('fixtures_only',False):
    for kind in globals().get('kinds',('plane','cylinder','cone','freeform')):
        for shape in globals().get('shapes',geo.ORGANIC_SHAPES):
            for mode in globals().get('modes',('extrude','feature','profiles')):
                for trim in globals().get('trims',(False,True)):run_case(shape,kind,mode,trim)
    report['original_unchanged']=(original.name,original.isModified)==original_state
    report['passed']=bool(report['cases']) and all(c['passed'] for c in report['cases']) and report['original_unchanged']
    save()
