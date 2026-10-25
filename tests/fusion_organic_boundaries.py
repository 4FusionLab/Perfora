# SPDX-License-Identifier: GPL-3.0-only
"""Real zero-offset/inner-cutout acceptance in disposable Fusion documents."""
import json
from pathlib import Path
import runpy
import traceback

import adsk.core
import adsk.fusion

root=Path(__file__).resolve().parents[1]
n=runpy.run_path(str(root/'tests/fusion_organic_regression.py'),init_globals={'fixtures_only':True})
entry,geo,app=n['entry'],n['geo'],n['app']
original=app.activeDocument
report=dict(fusion=app.version,passed=False,cases=[])
output=Path.home()/'Library/Logs/Perfora/organic/final-boundaries.json'
for shape in geo.ORGANIC_SHAPES:
    doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    case=dict(shape=shape,passed=False);report['cases'].append(case);renderer=None
    try:
        design=adsk.fusion.Design.cast(app.activeProduct);component=design.rootComponent
        body,face=n['fixture'](component,'plane')
        sketch=component.sketches.addWithoutEdges(face)
        sketch.sketchCurves.sketchCircles.addByCenterRadius(entry.model.point((0,0)),.4)
        cfg=n['config'](bodies=[body])
        entry.model.extrude(component,sketch.profiles.item(0),cfg);sketch.isVisible=False
        face=max((f for f in body.faces if isinstance(f.geometry,adsk.core.Plane)),key=lambda f:f.pointOnFace.z)
        assert face.loops.count==2
        volume=body.volume
        settings=geo.Settings(shape=shape,size=.45,gap=.055,margin=0,clip_boundary=True,
            organic_open=58 if shape=='topographic' else 48)
        renderer=entry.Renderer();count=renderer.show(face,settings,cfg);renderer.clear()
        _,_,built=entry.model.build(face,settings,cfg)
        assert count==built and count>0
        assert body.isSolid and body.lumps.count==1 and 0<body.volume<volume
        n['healthy'](design)
        case.update(passed=True,holes=built,volume=body.volume,settings=settings.__dict__)
    except Exception:case['error']=traceback.format_exc()
    finally:
        if renderer:renderer.clear()
        doc.close(False);original.activate()
        output.write_text(json.dumps(report,indent=2))
report['passed']=all(c['passed'] for c in report['cases'])
output.write_text(json.dumps(report,indent=2))
