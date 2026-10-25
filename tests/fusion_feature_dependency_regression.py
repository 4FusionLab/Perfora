# SPDX-License-Identifier: GPL-3.0-only
"""Real Fusion regression for target-body self-dependency and legacy repair.

Run with runpy while Perfora is loaded. Every case owns an unsaved document.
No event-handler replacements are used: the installed add-in must compute.
"""
from dataclasses import replace
import json
from pathlib import Path
import runpy
import adsk.core
import adsk.fusion

root = Path(__file__).resolve().parents[1]
fixture = runpy.run_path(str(root/'tests/fusion_organic_regression.py'),
                         init_globals={'fixtures_only': True})
entry = fixture['entry']
parametric = entry.parametric
app = adsk.core.Application.get()
original = app.activeDocument
original_state = (original.name, original.isModified)
report = dict(fusion=app.version, addon=entry.__file__, passed=False, cases=[])
output = Path.home()/'Library/Logs/Perfora/integration-20261025/feature-dependency-regression.json'


def healthy(custom):
    for feature in [custom, *custom.features]:
        assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, (
            feature.name, int(feature.healthState), feature.errorOrWarningMessage)


for legacy in (False, True):
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    case = dict(legacy=legacy, passed=False)
    report['cases'].append(case)
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        component = design.rootComponent
        body, face = fixture['fixture'](component, 'plane')
        settings = entry.Settings(shape='circle', size=.4, gap=.15, margin=.1,
                                  clip_boundary=True)
        config = fixture['config'](result='feature', bodies=[body])
        reference = parametric.body_reference
        if legacy:
            # Recreate the exact old dependency, using the real Fusion API.
            parametric.body_reference = parametric.dependency_entity
        try:
            _, custom, count = parametric.build(face, settings, config)
        finally:
            parametric.body_reference = reference
        case.update(holes=count, initial_health=int(custom.healthState),
                    volume_before=body.volume)
        before = body.volume
        if legacy:
            assert custom.healthState == adsk.fusion.FeatureHealthStates.RolledBackFeatureHealthState
            assert isinstance(custom.dependencies.itemById('body0').entity, adsk.fusion.BRepBody)
            custom.timelineObject.rollTo(True)
            parametric.update(custom, replace(settings, size=.45), config)
            custom.timelineObject.rollTo(False)
        else:
            healthy(custom)
            custom.parameters.itemById('size').value = .45
        assert design.computeAll()
        healthy(custom)
        assert isinstance(custom.dependencies.itemById('body0').entity, adsk.fusion.BRepFace)
        assert parametric.read(custom)[2]['bodies'][0] == body
        assert abs(body.volume-before) > 1e-7
        case['volume_after_size'] = body.volume
        # The reference must also respond to upstream source-body edits.
        upstream = component.features.extrudeFeatures.item(0)
        thickness = adsk.fusion.DistanceExtentDefinition.cast(upstream.extentOne).distance
        thickness.value += .05
        assert design.computeAll()
        healthy(custom)
        assert abs(body.volume-case['volume_after_size']) > 1e-7
        case.update(passed=True, volume_after_upstream=body.volume,
                    final_health=int(custom.healthState))
    finally:
        doc.close(False)
        original.activate()
        report['original_unchanged'] = (original.name, original.isModified) == original_state
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2))
assert report['original_unchanged']
report['passed'] = all(case['passed'] for case in report['cases'])
output.write_text(json.dumps(report, indent=2))
print(report)
