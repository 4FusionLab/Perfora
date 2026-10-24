# SPDX-License-Identifier: GPL-3.0-only
"""Run with runpy in Fusion, with the tested Perfora add-in registered/running.

Uses disposable unsaved documents. Checks the Boolean children as well as the
Custom Feature: Fusion can report Healthy on Perfora while Combine lost its body.
"""
import json
from pathlib import Path
import runpy
import sys
from time import perf_counter
import traceback

import adsk.core
import adsk.fusion

root = Path(__file__).resolve().parents[1]
addon_path = Path(globals().get('addon_path', root / 'Perfora')).resolve()
entry = next(m for m in tuple(sys.modules.values())
             if str(getattr(m, '__file__', '')) == str(addon_path / 'Perfora.py'))
fixture = runpy.run_path(str(root / 'PerforaSmokeTest/PerforaSmokeTest.py'))
app = adsk.core.Application.get()
original = app.activeDocument
output = Path.home() / 'Library/Logs/Perfora/height-regression.json'
output.parent.mkdir(parents=True, exist_ok=True)
report = dict(fusion=app.version, addon=str(entry.__file__), tests=[])


def save(stage):
    report.update(stage=stage, passed=bool(report['tests']) and
                  all(t['passed'] for t in report['tests']))
    output.write_text(json.dumps(report, indent=2))


def box(design, height):
    comp = design.rootComponent
    parameter = design.userParameters.add('h', entry.model.value(str(height) + ' mm'), 'mm', 'Box height')
    sketch = comp.sketches.addWithoutEdges(comp.xYConstructionPlane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        entry.model.point((-2.5, -2.5)), entry.model.point((2.5, 2.5)))
    data = comp.features.extrudeFeatures.createInput(sketch.profiles.item(0),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    data.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(entry.model.value('h')),
                         adsk.fusion.ExtentDirections.PositiveExtentDirection)
    body = comp.features.extrudeFeatures.add(data).bodies.item(0)
    top = next(f for f in body.faces if abs(f.boundingBox.minPoint.z - height / 10) < 1e-7
               and abs(f.boundingBox.maxPoint.z - height / 10) < 1e-7)
    faces = adsk.core.ObjectCollection.create()
    faces.add(top)
    shell = comp.features.shellFeatures.createInput(faces)
    shell.insideThickness = entry.model.value('2 mm')
    comp.features.shellFeatures.add(shell)
    face = next(f for f in body.faces if abs(f.boundingBox.minPoint.y + 2.5) < 1e-7
                and abs(f.boundingBox.maxPoint.y + 2.5) < 1e-7)
    sketch.isVisible = False
    return parameter, body, face


def healthy(feature):
    children = list(feature.features) if isinstance(feature, adsk.fusion.CustomFeature) else []
    for item in [feature] + children:
        assert item.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, (
            item.name, item.errorOrWarningMessage)


def visible_body(comp, height):
    bodies = [b for b in comp.bRepBodies if b.isVisible]
    assert len(bodies) == 1, len(bodies)
    body = bodies[0]
    assert body.isValid, 'The visible box body lost its geometry'
    assert body.isSolid and body.volume > 0
    bounds = body.boundingBox
    assert abs(bounds.maxPoint.z - bounds.minPoint.z - height / 10) < 1e-7
    return body.volume


try:
    for mode, shape, trim, rounding in (
            ('feature', 'voronoi', True, .04),
            ('feature', 'voronoi', True, 0),
            ('feature', 'voronoi', False, .04),
            ('feature', 'circle', True, 0),
            ('extrude', 'voronoi', True, .04)):
        result = dict(mode=mode, shape=shape, trim=trim, rounding=rounding, passed=False, steps=[])
        report['tests'].append(result)
        doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        try:
            design = adsk.fusion.Design.cast(app.activeProduct)
            comp = design.rootComponent
            h, body, face = box(design, 70)
            settings = entry.Settings(shape=shape, size=.8, gap=.12, margin=.3,
                                      clip_boundary=trim, corner_radius=rounding)
            config = fixture['config'](result=mode, operation='cut', reverse=True,
                                       distance1='3 mm', bodies=[body])
            _, feature, count = (entry.parametric if mode == 'feature' else entry.model).build(
                face, settings, config)
            healthy(feature)
            baseline = visible_body(comp, 70)
            volumes = {70: baseline}
            result.update(cells=count, initial_volume_cm3=baseline)
            for height in (20, 70, 20):
                save('before h=' + str(height))
                started = perf_counter()
                h.expression = str(height) + ' mm'
                healthy(feature)  # Natural recompute, before computeAll can mask it.
                natural = visible_body(comp, height)
                assert design.computeAll(), 'The design failed to recompute'
                healthy(feature)
                volume = visible_body(comp, height)
                assert abs(natural - volume) < 1e-7
                if height in volumes:
                    assert abs(volume - volumes[height]) < 1e-7, (height, volume, volumes)
                volumes[height] = volume
                result['steps'].append(dict(h_mm=height, volume_cm3=volume,
                                            seconds=perf_counter() - started))
            assert volumes[20] < volumes[70]
            result['passed'] = True
        except Exception:
            result['error'] = traceback.format_exc()
        finally:
            doc.close(False)
            if original and original.isValid:
                original.activate()
        save('case complete')
finally:
    save('complete')
print('HEIGHT_REGRESSION', json.dumps(report))
