# SPDX-License-Identifier: GPL-3.0-only
"""Six real CAD panels in one disposable document; no synthetic image editing."""
import json
import math
from pathlib import Path
import sys
from time import perf_counter

import adsk.core
import adsk.fusion

root=Path(__file__).resolve().parents[1]
entry=next(m for m in tuple(sys.modules.values()) if str(getattr(m,'__file__',''))==str(root/'Perfora/Perfora.py'))
geo=sys.modules[entry.Settings.__module__]
app=adsk.core.Application.get();original=app.activeDocument
output=Path(globals().get('output_dir',Path.home()/'Library/Logs/Perfora/organic'))
output.mkdir(parents=True,exist_ok=True)
old_style=app.activeViewport.visualStyle
doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
doc.name='Perfora Organic Patterns - CAD Examples'
report=dict(fusion=app.version,passed=False,panels=[])
try:
    design=adsk.fusion.Design.cast(app.activeProduct);component=design.rootComponent
    component.isOriginFolderLightBulbOn=False
    library=app.materialLibraries.itemByName('Fusion Appearance Library')
    appearance=design.appearances.addByCopy(library.appearances.itemByName('ABS (White)'),'Perfora Graphite')
    for key in ('opaque_albedo','surface_albedo'):
        prop=adsk.core.ColorProperty.cast(appearance.appearanceProperties.itemById(key))
        if prop:prop.value=adsk.core.Color.create(61,65,67,255)
    for i,shape in enumerate(geo.ORGANIC_SHAPES):
        started=perf_counter();matrix=adsk.core.Matrix3D.create()
        matrix.translation=adsk.core.Vector3D.create((i%3-1)*6,3 if i<3 else -3,0)
        occ=component.occurrences.addNewComponent(matrix);owner=occ.component
        owner.name=str(i+1)+' - '+entry.ORGANIC_LABELS[i]
        owner.isOriginFolderLightBulbOn=False
        sketch=owner.sketches.addWithoutEdges(owner.xYConstructionPlane)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(entry.model.point((-2.5,-2.5)),entry.model.point((2.5,2.5)))
        data=owner.features.extrudeFeatures.createInput(sketch.profiles.item(0),adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        data.setDistanceExtent(False,entry.model.value('2 mm'))
        body=owner.features.extrudeFeatures.add(data).bodies.item(0);sketch.isVisible=False
        face=max((f for f in body.faces if isinstance(f.geometry,adsk.core.Plane)),key=lambda f:f.pointOnFace.z)
        size=.34 if shape in ('smooth_noise','directional_fibers') else .38
        settings=geo.Settings(shape=shape,size=size,gap=.055,margin=.18,clip_boundary=True,
            organic_open=58 if shape=='topographic' else 48,
            organic_direction=math.pi/2 if shape=='directional_fibers' else 0)
        cfg=dict(boundary='rectangle',width=5.,height=5.,result='extrude',material='cells',operation='cut',
            direction='one',reverse=True,start='0 mm',distance1='2.2 mm',distance2='2 mm',
            extent1='distance',extent2='distance',taper1='0 deg',taper2='0 deg',bodies=[body],center_point=None)
        _,feature,count=entry.model.build(face,settings,cfg)
        assert body.isSolid and body.lumps.count==1 and body.volume>0
        body.appearance=appearance;owner.isSketchFolderLightBulbOn=False
        report['panels'].append(dict(shape=shape,holes=count,volume=body.volume,settings=settings.__dict__,seconds=perf_counter()-started))
    view=app.activeViewport;view.visualStyle=adsk.core.VisualStyles.ShadedVisualStyle
    camera=view.camera;camera.cameraType=adsk.core.CameraTypes.OrthographicCameraType
    camera.eye=adsk.core.Point3D.create(0,-4,50);camera.target=adsk.core.Point3D.create(0,0,.1)
    camera.upVector=adsk.core.Vector3D.create(0,1,0);camera.isSmoothTransition=False
    camera.isFitView=False
    assert camera.setExtents(20,16);view.camera=camera
    # Fusion 2706 can discard setExtents when assigning an orthographic camera.
    # Validate the actual viewport and use its supported legacy setter only
    # when the new API has failed to apply the requested framing.
    ok,width,height=view.camera.getExtents()
    if not ok or min(width,height)<10:
        camera=view.camera;camera.viewExtents=15.;view.camera=camera
    adsk.doEvents();view.refresh()
    path=str(output/'organic-cad-gallery.png')
    options=adsk.core.SaveImageFileOptions.create(path);options.width,options.height=2000,1500
    options.isBackgroundTransparent=True;options.isAntiAliased=True
    assert view.saveAsImageFileWithOptions(options)
    report['screenshot']=path
    manager=design.exportManager;archive=str(output/'organic-cad-gallery.f3d')
    assert manager.execute(manager.createFusionArchiveExportOptions(archive));report['archive']=archive
    report['passed']=True
finally:
    if not globals().get('keep_open',False):doc.close(False)
    original.activate();app.activeViewport.visualStyle=old_style
    (output/'gallery.json').write_text(json.dumps(report,indent=2))
