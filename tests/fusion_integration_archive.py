# SPDX-License-Identifier: GPL-3.0-only
"""Local F3D round-trip for integrated parametric dependencies, never cloud save."""
import json
from pathlib import Path
import runpy
import sys
import tempfile
import traceback
import adsk.core
import adsk.fusion

root=Path(__file__).resolve().parents[1]
entry=next(m for m in tuple(sys.modules.values()) if str(getattr(m,'__file__',''))==str(root/'Perfora/Perfora.py'))
app=adsk.core.Application.get();original=app.activeDocument
fixture=runpy.run_path(str(root/'tests/fusion_release_integration.py'),init_globals={'only_cases':('__fixtures_only__',)})
output=Path.home()/'Library/Logs/Perfora/integration-archive.json'
report=dict(passed=False,fusion=app.version,scope='local F3D only')
doc=reopened=None
try:
    doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design=adsk.fusion.Design.cast(app.activeProduct);comp=design.rootComponent
    first_body,first=fixture['face_fixture'](comp,'cylinder')
    second_body,second=fixture['face_fixture'](comp,'cylinder',4)
    cfg=fixture['config'](result='feature',bodies=[first_body,second_body])
    s=entry.Settings(layout='running_bond',size=.35,gap=.3,margin=.12,clip_boundary=True,limit=5000)
    _,multi,count=entry.parametric.build([first,second],s,cfg)
    fixture['healthy'](multi)
    report['multi_cells']=count
    occurrence=comp.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    part=occurrence.component
    path_sketch=part.sketches.addWithoutEdges(part.xYConstructionPlane)
    path=path_sketch.sketchCurves.sketchLines.addByTwoPoints(entry.model.point((-1.5,0)),entry.model.point((1.5,0)))
    path.isConstruction=True
    cfg=fixture['config'](surface=False,result='feature',operation='body',reverse=False,path=path)
    _,along,count=entry.parametric.build(part.xYConstructionPlane,entry.Settings(layout='path',size=.25,gap=.1,margin=.05,path_spacing=.5),cfg)
    fixture['healthy'](along)
    report['path_cells']=count
    guide_part=comp.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
    guide_sketch=guide_part.sketches.addWithoutEdges(guide_part.xYConstructionPlane)
    guides=[]
    for y in (-.65,.65):
        guide=guide_sketch.sketchCurves.sketchLines.addByTwoPoints(entry.model.point((-1.5,y)),entry.model.point((1.5,y)))
        guide.isConstruction=True;guides.append(guide)
    guide_cfg=fixture['config'](surface=False,result='feature',operation='body',reverse=False,guide1=guides[0],guide2=guides[1])
    _,guided,count=entry.parametric.build(guide_part.xYConstructionPlane,entry.Settings(layout='between_curves',size=.25,gap=.1,margin=.05,guide_rows=3),guide_cfg)
    fixture['healthy'](guided);report['between_curves_cells']=count
    volumes=sorted(b.volume for b in comp.bRepBodies)
    with tempfile.TemporaryDirectory(prefix='perfora-release-') as folder:
        archive=Path(folder)/'Integrated.f3d'
        assert design.exportManager.execute(design.exportManager.createFusionArchiveExportOptions(str(archive)))
        doc.close(False);doc=None
        options=app.importManager.createFusionArchiveImportOptions(str(archive))
        reopened=app.importManager.importToNewDocument(options)
        design=adsk.fusion.Design.cast(app.activeProduct);comp=design.rootComponent
        design.computeAll()
        assert len(volumes)==comp.bRepBodies.count
        assert all(abs(a-b)<1e-6 for a,b in zip(volumes,sorted(b.volume for b in comp.bRepBodies)))
        custom=comp.features.customFeatures.item(0)
        fixture['healthy'](custom)
        assert len(entry.parametric.source_entities(custom))==2
        before=sum(b.volume for b in comp.bRepBodies if b.isLightBulbOn)
        custom.parameters.itemById('size').expression='3 mm'
        design.computeAll();fixture['healthy'](custom)
        assert abs(sum(b.volume for b in comp.bRepBodies if b.isLightBulbOn)-before)>1e-5
        part=comp.occurrences.item(0).component
        along=part.features.customFeatures.item(0)
        fixture['healthy'](along)
        assert entry.parametric.path_dependency(along).isValid
        before=sum(b.volume for b in part.bRepBodies)
        along.parameters.itemById('path_spacing').expression='7 mm'
        design.computeAll();fixture['healthy'](along)
        assert abs(sum(b.volume for b in part.bRepBodies)-before)>1e-5
        guide_part=comp.occurrences.item(1).component
        guided=guide_part.features.customFeatures.item(0);fixture['healthy'](guided)
        assert all(guide.isValid for guide in entry.parametric.guide_entities(guided))
        before=sum(b.volume for b in guide_part.bRepBodies)
        guided.parameters.itemById('guide_rows').expression='4'
        design.computeAll();fixture['healthy'](guided)
        assert abs(sum(b.volume for b in guide_part.bRepBodies)-before)>1e-5
    report.update(passed=True,multi_recomputed=True,path_recomputed=True,between_curves_recomputed=True)
except Exception:report['error']=traceback.format_exc()
finally:
    if reopened:reopened.close(False)
    if doc:doc.close(False)
    original.activate()
    output.write_text(json.dumps(report,indent=2))
print('PERFORA_INTEGRATION_ARCHIVE',str(output))
