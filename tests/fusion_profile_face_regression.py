# SPDX-License-Identifier: GPL-3.0-only
"""Face-backed sketch profiles: no Split Face; run with runpy inside Fusion."""
import json
from pathlib import Path
import runpy
import sys
import traceback

import adsk.core
import adsk.fusion

root = Path(__file__).resolve().parents[1]
entry = globals().get('entry') or next(m for m in tuple(sys.modules.values())
    if str(getattr(m, '__file__', '')) == str(root / 'Perfora/Perfora.py'))
model = entry.model
fixture = runpy.run_path(str(root / 'PerforaSmokeTest/PerforaSmokeTest.py'))
app = adsk.core.Application.get()
original = app.activeDocument
doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
results = []


def case(name, action):
    try:
        results.append(dict(name=name, passed=True, detail=action()))
    except Exception:
        results.append(dict(name=name, passed=False, error=traceback.format_exc()))


def source_profile(comp, vertical=False, void=False):
    base = comp.sketches.addWithoutEdges(comp.yZConstructionPlane if vertical else comp.xYConstructionPlane)
    base.sketchCurves.sketchLines.addTwoPointRectangle(model.point((-2, -1.5)), model.point((2, 1.5)))
    data = comp.features.extrudeFeatures.createInput(base.profiles.item(0),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    data.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(model.value('4 mm')),
        adsk.fusion.ExtentDirections.PositiveExtentDirection)
    solid = comp.features.extrudeFeatures.add(data)
    body = solid.bodies.item(0)
    axis = 'x' if vertical else 'z'
    face = next(f for f in body.faces if isinstance(f.geometry, adsk.core.Plane)
        and abs(getattr(f.boundingBox.minPoint, axis) - .4) < 1e-7
        and abs(getattr(f.boundingBox.maxPoint, axis) - .4) < 1e-7)
    source = comp.sketches.addWithoutEdges(face)
    circle = source.sketchCurves.sketchCircles.addByCenterRadius(model.point((.2, -.1)), 1.1)
    dimension = source.sketchDimensions.addDiameterDimension(circle, model.point((1.5, -.1)))
    dimension.parameter.expression = '22 mm'
    if void:
        source.sketchCurves.sketchCircles.addByCenterRadius(model.point((.2, -.1)), .32)
    profile = next(p for p in source.profiles if p.profileLoops.count == (2 if void else 1))
    base.isVisible = False
    return body, source, profile, dimension


try:
    design = adsk.fusion.Design.cast(app.activeProduct)
    for vertical in (False, True):
        for trim in (False, True):
            for void in (False, True):
                def check(vertical=vertical, trim=trim, void=void):
                    comp = fixture['component'](design, 'Profile Face')
                    body, source, profile, _ = source_profile(comp, vertical, void)
                    settings = entry.Settings(size=.3, gap=.12, margin=.1, clip_boundary=trim)
                    cfg = fixture['config'](result='profiles', operation='cut', reverse=True, bodies=[body])
                    marker = design.timeline.markerPosition
                    assert model.source_support_body(profile) == body
                    assert design.timeline.markerPosition == marker and profile.isValid
                    renderer = entry.Renderer()
                    try:
                        count = renderer.show(profile, settings, cfg)
                        assert design.timeline.markerPosition == marker
                        assert model.sketch_frame(source) == renderer.frame
                        built, _, actual = model.build(profile, settings, cfg, renderer.geometry_cache)
                        assert count == actual > 0
                        area = sum(p.areaProperties().area for p in model.selected_profiles(built, 'cells', trim))
                        assert 0 < area < profile.areaProperties().area
                        for curve in built.sketchCurves:
                            p = curve.startSketchPoint.worldGeometry if hasattr(curve, 'startSketchPoint') else None
                            if p:
                                assert abs(source.modelToSketchSpace(p).z) < 1e-7
                        built.deleteMe()
                        before = body.volume
                        _, cut, actual = model.build(profile, settings, dict(cfg, result='extrude'), renderer.geometry_cache)
                        assert count == actual
                        assert cut.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
                        assert abs(before - body.volume - area * .2) < 1e-6
                        assert comp.features.splitFaceFeatures.count == 0
                        assert source.isValid and profile.isValid
                        return dict(cells=count, removed_cm3=before-body.volume, marker_restored=True)
                    finally:
                        renderer.reset()
                case('profile_face_' + ('YZ' if vertical else 'XY') +
                     ('_trim' if trim else '_whole') + ('_annulus' if void else '_disk'), check)

    def parametric():
        comp = fixture['component'](design, 'Profile Feature')
        body, source, profile, dimension = source_profile(comp)
        settings = entry.Settings(size=.3, gap=.12, margin=.1, clip_boundary=True)
        cfg = fixture['config'](result='feature', operation='cut', reverse=True, bodies=[body])
        _, custom, count = entry.parametric.build(profile, settings, cfg)
        assert custom.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, custom.errorOrWarningMessage
        before = body.volume
        dimension.parameter.expression = '25 mm'
        design.computeAll()
        assert custom.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, custom.errorOrWarningMessage
        assert body.volume < before
        custom.parameters.itemById('size').expression = '3.5 mm'
        design.computeAll()
        assert custom.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, custom.errorOrWarningMessage
        assert comp.features.splitFaceFeatures.count == 0
        return dict(cells=count, source_recomputed=True, pattern_recomputed=True)
    case('profile_face_feature_recompute', parametric)

    def plane_profile():
        comp = fixture['component'](design, 'Plane Profile')
        sketch = comp.sketches.addWithoutEdges(comp.xYConstructionPlane)
        sketch.sketchCurves.sketchCircles.addByCenterRadius(model.point((0, 0)), 1)
        assert model.source_support_body(sketch.profiles.item(0)) is None
        marker = design.timeline.markerPosition
        assert isinstance(model.sketch_reference_plane(sketch), adsk.fusion.ConstructionPlane)
        assert design.timeline.markerPosition == marker
        return dict(no_automatic_body=True)
    case('construction_plane_profile_unchanged', plane_profile)
finally:
    doc.close(False)
    if original and original.isValid:
        original.activate()
    report = dict(passed=bool(results) and all(r['passed'] for r in results), tests=results)
    output = Path.home() / 'Library/Logs/Perfora/profile-face-regression.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
print('PERFORA_PROFILE_FACE', json.dumps(report))
