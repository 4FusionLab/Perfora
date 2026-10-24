# SPDX-License-Identifier: GPL-3.0-only
"""Stable acceptance in Fusion: real OK, native Undo/Redo, edit, F3D reopen.

Run from the Python console via runpy with the registered add-in. Choose
result_mode='feature' (default) or 'extrude', and optionally addon_path.
Confirm the real dialog, call verify_created(), perform native Undo, call
verify_undo(), perform native Redo, then call finish(). No cloud save.
"""
import json
from pathlib import Path
import platform
import runpy
import sys
import tempfile

import adsk.core
import adsk.fusion

root = Path(__file__).resolve().parents[1]
addon = Path(globals().get('addon_path', root / 'Perfora')).resolve()
mode = globals().get('result_mode', 'feature')
entry = next(m for m in tuple(sys.modules.values()) if str(getattr(m, '__file__', '')) == str(addon / 'Perfora.py'))
ui = runpy.run_path(str(root / 'tests/fusion_ui_contract.py'), init_globals=dict(
    entry=entry, result_mode=mode, registered_command=True, source_profile=True))
app, design, comp = ui['app'], ui['design'], ui['comp']
report = dict(passed=False, fusion=app.version, platform=platform.platform(), result_mode=mode)
output = Path.home() / ('Library/Logs/Perfora/release-acceptance-' + mode + '.json')


def volume(component):
    return sum(b.volume for b in component.bRepBodies if b.isVisible)


def save():
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')


def verify_created():
    assert app.activeDocument == ui['doc'] and ui['report']['passed'], ui['report']
    assert app.userInterface.activeCommand == 'SelectCommand'
    assert design.timeline.count == ui['timeline'] + (1 if mode == 'feature' else 2)
    assert 0 < volume(comp) < ui['volume']
    report.update(created_volume_cm3=volume(comp), created_timeline=design.timeline.count, created=True)
    save()
    print('RELEASE_CREATED', report)


def verify_undo():
    assert report.get('created')
    assert design.timeline.count == ui['timeline']
    assert abs(volume(comp) - ui['volume']) < 1e-8
    report['undo'] = True
    save()
    print('RELEASE_UNDO_OK')


def finish():
    reopened = None
    try:
        assert report.get('undo')
        assert design.timeline.count == report['created_timeline']
        assert abs(volume(comp) - report['created_volume_cm3']) < 1e-8
        report['redo'] = True
        collection = comp.features.customFeatures if mode == 'feature' else comp.features.extrudeFeatures
        feature = collection.item(collection.count - 1)
        assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
        if mode == 'feature':
            feature.parameters.itemById('spread_radius').expression = '9 mm'
        else:
            distance = adsk.fusion.DistanceExtentDefinition.cast(feature.extentOne).distance
            # Fusion stores a signed ModelParameter for a negative extrusion.
            distance.expression = '-1 mm' if distance.value < 0 else '1 mm'
        report['compute_all_after_edit'] = design.computeAll()
        assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, feature.errorOrWarningMessage
        edited_volume = volume(comp)
        assert edited_volume > report['created_volume_cm3'] + 1e-7
        report['parameter_edit'] = True
        with tempfile.TemporaryDirectory(prefix='perfora-stable-acceptance-') as directory:
            archive = Path(directory) / ('perfora-' + mode + '.f3d')
            assert design.exportManager.execute(design.exportManager.createFusionArchiveExportOptions(str(archive)))
            assert archive.stat().st_size > 0
            ui['finish'](True)
            assert ui['report']['passed'] and ui['report']['original_unchanged'], ui['report']
            reopened = app.importManager.importToNewDocument(app.importManager.createFusionArchiveImportOptions(str(archive)))
            assert reopened is not None
            reopened_design = adsk.fusion.Design.cast(app.activeProduct)
            component = reopened_design.rootComponent
            assert reopened_design.timeline.count == report['created_timeline']
            assert abs(volume(component) - edited_volume) < 1e-7
            collection = component.features.customFeatures if mode == 'feature' else component.features.extrudeFeatures
            feature = collection.item(collection.count - 1)
            assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, feature.errorOrWarningMessage
            if mode == 'feature':
                assert abs(feature.parameters.itemById('spread_radius').value - .9) < 1e-8
                feature.parameters.itemById('spread_radius').expression = '10 mm'
            else:
                distance = adsk.fusion.DistanceExtentDefinition.cast(feature.extentOne).distance
                assert abs(abs(distance.value) - .1) < 1e-8
                distance.expression = '-1.5 mm' if distance.value < 0 else '1.5 mm'
            report['compute_all_after_reopen'] = reopened_design.computeAll()
            assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, feature.errorOrWarningMessage
            assert abs(volume(component) - edited_volume) > 1e-7
            report.update(local_f3d_reopen=True, recompute_after_reopen=True, passed=True)
    finally:
        if reopened is not None and reopened.isValid:
            reopened.close(False)
        if ui['doc'].isValid:
            ui['definition'].commandCreated.remove(ui['handler'])
            ui['doc'].close(False)
        ui['original'].activate()
        report['original_unchanged'] = (ui['original_design'].timeline.count == ui['original_timeline'] and
            abs(sum(b.volume for b in ui['original_design'].rootComponent.bRepBodies) - ui['original_volume']) < 1e-8)
        report['passed'] = report['passed'] and report['original_unchanged']
        save()
    print('RELEASE_ACCEPTANCE', report)
