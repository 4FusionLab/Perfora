# SPDX-License-Identifier: GPL-3.0-only
"""Replay noise on copies of a selected real body, without saving user files.

Run with runpy init_globals source_face, entry and optional modes/shapes.
Every case owns a disposable unsaved document. JSON evidence is outside Git.
"""
import adsk.core
import adsk.fusion
import json
from pathlib import Path
from time import perf_counter
import traceback

app=adsk.core.Application.get()
original=app.activeDocument
source=globals().get('source_face') or app.userInterface.activeSelections.item(0).entity
original_state=(original.name,original.isModified,source.body.volume)
manager=adsk.fusion.TemporaryBRepManager.get()
snapshot=manager.copy(source.body)
source_area,source_point=source.area,source.pointOnFace
report=dict(fusion=app.version,addon=entry.__file__,source_type=source.geometry.objectType,
            source_area=source_area,source_body=source.body.name,cases=[],passed=False)
output=Path.home()/'Library/Logs/Perfora/integration-20261025'
output.mkdir(parents=True,exist_ok=True)

def save():
    (output/globals().get('report_name','selected-noise-cad.json')).write_text(json.dumps(report,indent=2))

for shape in globals().get('shapes',entry.ORGANIC_SHAPES):
    for mode in globals().get('modes',('extrude',)):
        doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        item=dict(shape=shape,mode=mode,passed=False,stage='copy');report['cases'].append(item)
        started=perf_counter();renderer=None
        try:
            design=adsk.fusion.Design.cast(app.activeProduct);comp=design.rootComponent
            base=comp.features.baseFeatures.add();assert base.startEdit()
            comp.bRepBodies.add(snapshot,base);assert base.finishEdit()
            body=base.bodies.item(0)
            face=min(body.faces,key=lambda f:abs(f.area-source_area)+f.pointOnFace.distanceTo(source_point))
            before=body.volume
            cfg=dict(boundary='rectangle',width=8.,height=6.,result=mode,material='cells',operation='cut',direction='one',reverse=True,start='0 mm',distance1='2.2 mm',distance2='2 mm',extent1='distance',extent2='distance',taper1='0 deg',taper2='0 deg',bodies=[body],center_point=None)
            s=entry.Settings(shape=shape,clip_boundary=True)
            renderer=entry.Renderer();item['stage']='fast';t=perf_counter()
            count=renderer.show(face,s,cfg);item.update(holes=count,fast_seconds=perf_counter()-t)
            renderer.clear();item['stage']='build';t=perf_counter()
            sketch,feature,built=(entry.parametric.build if mode=='feature' else entry.model.build)(face,s,cfg,cache=renderer.geometry_cache)
            assert built==count and count>0,(built,count)
            assert body.isSolid and 0<body.volume<before,(before,body.volume)
            assert feature.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,feature.errorOrWarningMessage
            item.update(build_seconds=perf_counter()-t,volume_before=before,volume_after=body.volume)
            if mode=='feature':
                assert isinstance(feature.dependencies.itemById('body0').entity, adsk.fusion.BRepFace)
                assert entry.parametric.read(feature)[2]['bodies'][0] == body
                item['stage']='recompute';before_edit=body.volume
                p=feature.parameters.itemById('size');p.value+=.05
                assert design.computeAll()
                assert feature.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,feature.errorOrWarningMessage
                assert abs(body.volume-before_edit)>1e-7
                item['recomputed_volume']=body.volume
                item['recompute_parameter']='size'
            if globals().get('capture',False):
                app.activeViewport.fit();adsk.doEvents();app.activeViewport.refresh()
                filename=str(output/('box-'+shape+'-'+mode+'.png'))
                assert app.activeViewport.saveAsImageFile(filename,1200,900)
                item['screenshot']=filename
            item.update(passed=True,stage='complete')
        except Exception as error:item.update(error=str(error),traceback=traceback.format_exc())
        finally:
            if renderer:renderer.reset()
            doc.close(False);original.activate()
            item['seconds']=perf_counter()-started;save()
        print(shape,mode,item['passed'],item.get('error'),round(item['seconds'],2),flush=True)
assert (original.name,original.isModified,source.body.volume)==original_state
report['passed']=all(c['passed'] for c in report['cases']);save()
