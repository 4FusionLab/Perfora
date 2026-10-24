# SPDX-License-Identifier: GPL-3.0-only
"""Live loaded add-in: dependencies, count changes, expressions and local reopen."""
import adsk.core
import adsk.fusion
import json
from pathlib import Path
import platform
import sys
import traceback

app=adsk.core.Application.get()
root=Path(__file__).resolve().parents[1]
entry=next(m for m in tuple(sys.modules.values()) if str(getattr(m,'__file__',''))==str(root/'Perfora/Perfora.py'))
original=app.activeDocument
doc=reopened=None
out=Path.home()/'Library/Logs/Perfora/surface-feature.json'
report=dict(version=app.version,os=platform.platform(),checkout=entry.__file__,passed=False)

def healthy(custom):
    assert custom.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState,custom.errorOrWarningMessage

def visible_volume(comp):
    return sum(b.volume for b in comp.bRepBodies if b.isVisible)

try:
    doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design=adsk.fusion.Design.cast(app.activeProduct)
    comp=design.rootComponent
    diameter=design.userParameters.add('surfaceDiameter',adsk.core.ValueInput.createByString('30 mm'),'mm','')
    height=design.userParameters.add('surfaceHeight',adsk.core.ValueInput.createByString('16 mm'),'mm','')
    sketch=comp.sketches.add(comp.xYConstructionPlane)
    circle=sketch.sketchCurves.sketchCircles.addByCenterRadius(entry.model.point((0,0)),1.5)
    dimension=sketch.sketchDimensions.addDiameterDimension(circle,entry.model.point((2.,0)))
    dimension.parameter.expression='surfaceDiameter'
    data=comp.features.extrudeFeatures.createInput(sketch.profiles.item(0),adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    data.setDistanceExtent(False,adsk.core.ValueInput.createByString('surfaceHeight'))
    extrusion=comp.features.extrudeFeatures.add(data)
    body=extrusion.bodies.item(0)
    face=next(f for f in body.faces if isinstance(f.geometry,adsk.core.Cylinder))
    config=dict(surface=True,result='feature',operation='cut',material='cells',distance1='3 mm',bodies=[body])
    settings=entry.Settings(shape='voronoi',size=.5,gap=.18,margin=.12,clip_boundary=True,corner_radius=.02)
    _,custom,count=entry.parametric.build(face,settings,config)
    healthy(custom)
    base=next(f for f in custom.features if isinstance(f,adsk.fusion.BaseFeature))
    before=visible_volume(comp)
    original_lumps=base.bodies.item(0).lumps.count
    custom.parameters.itemById('size').expression='4 mm'
    healthy(custom)
    smaller=visible_volume(comp)
    changed_lumps=base.bodies.item(0).lumps.count
    assert abs(smaller-before)>1e-5 and original_lumps!=changed_lumps
    diameter.expression='34 mm'
    healthy(custom)
    wider=visible_volume(comp)
    assert abs(wider-smaller)>1e-5
    height.expression='22 mm'
    healthy(custom)
    taller=visible_volume(comp)
    assert abs(taller-wider)>1e-5
    assert design.computeAll()
    healthy(custom)
    archive=out.with_suffix('.f3d')
    assert design.exportManager.execute(design.exportManager.createFusionArchiveExportOptions(str(archive)))
    imported=app.importManager.importToNewDocument(app.importManager.createFusionArchiveImportOptions(str(archive)))
    reopened=app.activeDocument
    other=adsk.fusion.Design.cast(app.activeProduct)
    node=other.rootComponent.features.customFeatures.item(0)
    healthy(node)
    assert other.computeAll()
    healthy(node)
    assert abs(visible_volume(other.rootComponent)-taller)<1e-5
    node.parameters.itemById('cylinder_sweep').expression='180 deg'
    healthy(node)
    assert abs(visible_volume(other.rootComponent)-taller)>1e-5
    report.update(passed=True,holes=count,initial_lumps=original_lumps,changed_lumps=changed_lumps,
                  natural_parameter_recompute=True,natural_radius_recompute=True,natural_height_recompute=True,
                  local_f3d_reopen=True,reopened_zone_edit=True,volume=taller)
except Exception:
    report['error']=traceback.format_exc()
finally:
    if reopened and reopened!=doc and reopened.isValid:
        reopened.close(False)
    if doc and doc.isValid:
        doc.close(False)
    if original and original.isValid:
        original.activate()
    out.write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
