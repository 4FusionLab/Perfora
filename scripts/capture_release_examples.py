# SPDX-License-Identifier: GPL-3.0-only
"""Capture real Fusion 1.0 examples with the registered add-in; no cloud save.

Run with runpy in Fusion, optionally passing addon_path and output_dir. Creates
one disposable document and restores the user's original document in finally.
"""
from dataclasses import replace
import json
import math
from pathlib import Path
import runpy
import sys

import adsk.core
import adsk.fusion

ROOT = Path(__file__).resolve().parents[1]
ADDON = Path(globals().get('addon_path', ROOT / 'Perfora')).resolve()
OUT = Path(globals().get('output_dir', ROOT / 'docs/assets/examples/v1.0.0'))


def capture_examples():
    entry = next(m for m in tuple(sys.modules.values())
        if str(getattr(m, '__file__', '')) == str(ADDON / 'Perfora.py'))
    model, feature = entry.model, entry.parametric
    fixture = runpy.run_path(str(ROOT / 'PerforaSmokeTest/PerforaSmokeTest.py'))
    app = adsk.core.Application.get()
    original = app.activeDocument
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    doc.name = 'Perfora 1.0 Release Examples'
    OUT.mkdir(parents=True, exist_ok=True)
    report = dict(fusion=app.version, images=[], models=[])
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        root = design.rootComponent
        root.isOriginFolderLightBulbOn = False
        library = app.materialLibraries.itemByName('Fusion Appearance Library')
        base = library.appearances.itemByName('ABS (White)')
        appearances = []
        for name, rgb in [('Gold', (218, 138, 48)), ('Blue', (35, 128, 170)),
                          ('Green', (63, 153, 124)), ('Purple', (163, 94, 146))]:
            appearance = design.appearances.addByCopy(base, 'Perfora ' + name)
            for key in ('opaque_albedo', 'surface_albedo'):
                adsk.core.ColorProperty.cast(appearance.appearanceProperties.itemById(key)).value = adsk.core.Color.create(*rgb, 255)
            appearances.append(appearance)

        def component(name, x=0):
            transform = adsk.core.Matrix3D.create()
            transform.translation = adsk.core.Vector3D.create(x, 0, 0)
            occ = root.occurrences.addNewComponent(transform)
            occ.component.name = name
            occ.component.isOriginFolderLightBulbOn = False
            return occ

        def style(occ, color):
            comp = occ.component
            comp.isSketchFolderLightBulbOn = False
            comp.isConstructionFolderLightBulbOn = False
            for body in comp.bRepBodies:
                if body.isVisible:
                    body.appearance = appearances[color]

        def capture(name, occurrences, top=False):
            for occ in root.occurrences:
                occ.isLightBulbOn = occ in occurrences
            app.userInterface.activeSelections.clear()
            view = app.activeViewport
            camera = view.camera
            camera.cameraType = adsk.core.CameraTypes.OrthographicCameraType
            camera.eye = adsk.core.Point3D.create(0, -8, 24) if top else adsk.core.Point3D.create(7, -11, 22)
            camera.target = adsk.core.Point3D.create()
            camera.upVector = adsk.core.Vector3D.create(0, 0, 1)
            camera.isSmoothTransition = False
            camera.isFitView = True
            view.camera = camera
            adsk.doEvents()
            view.refresh()
            options = adsk.core.SaveImageFileOptions.create(str(OUT / (name + '.jpg')))
            options.width, options.height = 1920, 1440
            options.isBackgroundTransparent = True
            options.isAntiAliased = True
            assert view.saveAsImageFileWithOptions(options)
            report['images'].append(name + '.jpg')

        def annulus(occ, outer, inner):
            sketch = occ.component.sketches.addWithoutEdges(occ.component.xYConstructionPlane)
            for radius in (outer, inner):
                sketch.sketchCurves.sketchCircles.addByCenterRadius(model.point((0, 0)), radius)
            return next(p for p in sketch.profiles if p.profileLoops.count == 2)

        def build(occ, source, settings, config, color):
            _, custom, count = feature.build(source, settings, config)
            assert custom.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, custom.errorOrWarningMessage
            style(occ, color)
            report['models'].append(dict(name=occ.component.name, holes=count, source_type=source.objectType,
                volume_cm3=sum(b.volume for b in occ.component.bRepBodies if b.isVisible)))
            return custom, count

        def plate(occ, width, height):
            comp = occ.component
            sketch = comp.sketches.addWithoutEdges(comp.xYConstructionPlane)
            sketch.sketchCurves.sketchLines.addTwoPointRectangle(model.point((-width / 2, -height / 2)), model.point((width / 2, height / 2)))
            for x in (-width / 2 + .9, width / 2 - .9):
                for y in (-height / 2 + .9, height / 2 - .9):
                    sketch.sketchCurves.sketchCircles.addByCenterRadius(model.point((x, y)), .16)
            source = max(sketch.profiles, key=lambda p: p.areaProperties().area)
            data = comp.features.extrudeFeatures.createInput(source, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
            data.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(model.value('3 mm')),
                adsk.fusion.ExtentDirections.PositiveExtentDirection)
            solid = comp.features.extrudeFeatures.add(data)
            body = solid.bodies.item(0)
            face = next(f for f in body.faces if isinstance(f.geometry, adsk.core.Plane)
                and abs(f.boundingBox.minPoint.z - .3) < 1e-7 and abs(f.boundingBox.maxPoint.z - .3) < 1e-7)
            return body, face

        circular = entry.Settings(shape='slot', layout='circular', size=.32,
            slot_length=1.15, gap=.2, margin=.3, start_radius=1.5,
            tangential_orientation=True, clip_boundary=True)
        occ = component('Circular Tangential Grille')
        build(occ, annulus(occ, 5, 1.0), circular,
              fixture['config'](result='feature', material='panel', distance1='3 mm'), 0)
        capture('circular-tangential', [occ], True)

        pair = []
        for index, tangent in enumerate((False, True)):
            occ = component('Tangential Slots' if tangent else 'Radial Slots', (index - .5) * 8.3)
            settings = replace(circular, size=.28, slot_length=.9, start_radius=1.25,
                tangential_orientation=tangent, radial_orientation=not tangent, margin=.22)
            build(occ, annulus(occ, 3.6, .65), settings,
                  fixture['config'](result='feature', material='panel', distance1='3 mm'), index)
            pair.append(occ)
        capture('radial-and-tangential', pair, True)

        occ = component('Point and Spread Radius')
        body, face = plate(occ, 12, 8)
        comp = occ.component
        anchor_sketch = comp.sketches.addWithoutEdges(comp.xYConstructionPlane)
        anchor = anchor_sketch.sketchPoints.add(model.point((2.2, .45)))
        settings = entry.Settings(shape='hexagon', size=.52, gap=.14, margin=.24,
            spread_radius=2.3, clip_boundary=True)
        build(occ, face, settings, fixture['config'](result='feature', operation='cut',
            reverse=True, distance1='3 mm', bodies=[body], center_point=anchor), 2)
        capture('point-scoped-perforation', [occ])

        occ = component('Sketch Profile Without Split Face')
        body, face = plate(occ, 11, 7.5)
        sketch = occ.component.sketches.addWithoutEdges(face)
        points = [(-3.5, -2), (1.6, -2), (3.5, 0), (1.6, 2), (-3.5, 2)]
        model.add_polygon(sketch, points, 'outer')
        source = max(sketch.profiles, key=lambda p: p.areaProperties().area)
        settings = entry.Settings(shape='voronoi', size=.66, gap=.13, margin=.22,
            corner_radius=.1, irregularity=1., seed=27, clip_boundary=True)
        build(occ, source, settings, fixture['config'](result='feature', operation='cut',
            reverse=True, distance1='3 mm', bodies=[body]), 1)
        assert occ.component.features.splitFaceFeatures.count == 0
        capture('profile-region', [occ])

        pair = []
        for index, radius in enumerate((1.6, 2.6)):
            occ = component('Spread Radius ' + str(int(radius * 10)) + ' mm', (index - .5) * 10.5)
            body, face = plate(occ, 9.5, 6.5)
            settings = entry.Settings(shape='circle', size=.38, gap=.13, margin=.24,
                spread_radius=1.6, clip_boundary=True)
            custom, count = build(occ, face, settings, fixture['config'](result='feature',
                operation='cut', reverse=True, distance1='3 mm', bodies=[body]), 2)
            before = body.volume
            if index:
                custom.parameters.itemById('spread_radius').expression = '26 mm'
                computed = design.computeAll()
                if not computed:
                    details = []
                    for item in root.occurrences:
                        for collection in (item.component.features.customFeatures,
                                           item.component.features.extrudeFeatures,
                                           item.component.features.combineFeatures,
                                           item.component.features.baseFeatures,
                                           item.component.sketches):
                            for entity in collection:
                                if entity.healthState != adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState:
                                    details.append((item.component.name, entity.name, entity.errorOrWarningMessage))
                    assert not details, details
                report['models'][-1]['compute_all_returned'] = computed
                assert body.volume < before
                assert custom.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, custom.errorOrWarningMessage
                report['models'][-1].update(recomputed_spread_mm=26, volume_after_cm3=body.volume)
            pair.append(occ)
        capture('parametric-spread', pair, True)
        (OUT / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print('PERFORA_RELEASE_EXAMPLES', json.dumps(report))
    finally:
        doc.close(False)
        if original and original.isValid:
            original.activate()


capture_examples()
