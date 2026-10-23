# SPDX-License-Identifier: GPL-3.0-only
"""Run with runpy in Fusion. Uses a real command and separate disposable document.

Leaves the test dialog open. Confirm or cancel it, then call finish() from the
returned namespace to validate the transaction and restore the user's document.
"""
import importlib.util
import json
from pathlib import Path
import re
import sys
import traceback

import adsk.core
import adsk.fusion

root = Path(__file__).resolve().parents[1]
entry = next(m for m in tuple(sys.modules.values())
             if str(getattr(m, '__file__', '')).endswith(('/Perfora/Perfora.py', '/Perforator/Perforator.py')))
app = adsk.core.Application.get()
original = app.activeDocument
original_design = adsk.fusion.Design.cast(app.activeProduct)
original_timeline = original_design.timeline.count
original_volume = sum(b.volume for b in original_design.rootComponent.bRepBodies)
doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
design = adsk.fusion.Design.cast(app.activeProduct)
comp = design.rootComponent
spec = importlib.util.spec_from_file_location('_ui_fixture', root / 'PerforaSmokeTest/PerforaSmokeTest.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
body, face = fixture.plate(comp)
timeline = design.timeline.count
volume = body.volume
report = {'passed': False}
lifetime = []
output = Path.home() / 'Library/Logs/Perfora/ui-contract.json'
output.parent.mkdir(parents=True, exist_ok=True)


def save():
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def choose(s, identifier, options, key):
    s.inputs[identifier].listItems.item(next(i for i, (k, _) in enumerate(options) if k == key)).isSelected = True
    s.update_visibility()


class Activate(adsk.core.CommandEventHandler):
    def __init__(self, session):
        super().__init__()
        self.session = session
        self.done = False

    def notify(self, args):
        if self.done:
            return
        self.done = True
        s = self.session
        try:
            s.inputs['source'].addSelection(face)
            s.update_visibility()
            assert s.chosen('operation', entry.OPERATIONS) == 'cut'
            assert s.read()[2]['bodies']
            for shape, _ in entry.SHAPES:
                choose(s, 'shape', entry.SHAPES, shape)
                settings, config = s.read()[1:]
                assert settings.shape == shape and abs(settings.size - 0.5) < 1e-8
                assert config['result'] == 'extrude'
            # Dimension labels change through distinct native inputs, preserving
            # one expression without trying to assign the read-only input name.
            s.inputs['size_diagonal'].expression = '7 mm'
            s.sync_dimensions('size_diagonal')
            assert all(abs(s.inputs[k].value - 0.7) < 1e-8 for k in entry.SIZE_FIELDS)
            choose(s, 'shape', entry.SHAPES, 'triangle')
            assert s.read()[1].size == s.inputs['size_side'].value
            s.inputs['size'].expression = '5 mm'
            s.sync_dimensions('size')
            for key, _ in entry.OPERATIONS:
                choose(s, 'operation', entry.OPERATIONS, key)
                assert s.read()[2]['operation'] == key
            for key, _ in entry.DIRECTIONS:
                choose(s, 'direction', entry.DIRECTIONS, key)
                assert s.read()[2]['direction'] == key
                assert s.inputs['side2'].isVisible == (key == 'two')
            choose(s, 'direction', entry.DIRECTIONS, 'one')
            s.inputs['start'].expression = '1 mm'
            choose(s, 'start_mode', entry.STARTS, 'profile')
            assert s.read()[2]['start'] == '0 mm' and not s.inputs['start'].isVisible
            choose(s, 'start_mode', entry.STARTS, 'offset')
            assert s.read()[2]['start'] == '1 mm' and s.inputs['start'].isVisible
            choose(s, 'start_mode', entry.STARTS, 'profile')
            choose(s, 'extent1', entry.EXTENTS, 'all')
            assert s.read()[2]['extent1'] == 'all'
            s.inputs['target1'].addSelection(comp.xYConstructionPlane)
            choose(s, 'extent1', entry.EXTENTS, 'object')
            assert s.read()[2]['target1'] is not None
            choose(s, 'extent1', entry.EXTENTS, 'distance')
            choose(s, 'result', entry.RESULTS, 'profiles')
            s.inputs['distance1'].expression = '-2 mm'
            assert s.read()[2]['result'] == 'profiles' and not s.inputs['output_group'].isVisible
            s.inputs['distance1'].expression = '2 mm'
            choose(s, 'result', entry.RESULTS, 'extrude')
            choose(s, 'shape', entry.SHAPES, 'voronoi')
            assert not s.inputs['corner_radius'].isVisible
            s.inputs['round_corners'].value = True
            s.update_visibility()
            assert s.inputs['corner_radius'].isVisible
            assert abs(s.read()[1].corner_radius - .05) < 1e-9
            s.inputs['round_corners'].value = False
            s.inputs['corner_radius'].expression = '-1 mm'
            assert s.read()[1].corner_radius == 0, 'Inactive rounding must not block the command'
            s.inputs['corner_radius'].expression = '0.5 mm'
            s.inputs['round_corners'].value = True
            s.update_visibility()
            choose(s, 'operation', entry.OPERATIONS, 'cut')
            s.inputs['clip_boundary'].value = True
            s.inputs['margin'].expression = '2 mm'
            s.inputs['preview'].value = True
            for key, control in s.inputs.items():
                assert not re.search('[А-Яа-яЁё]', control.name + control.tooltip), key
            report.update(passed=True, stage='ready', shapes=len(entry.SHAPES), operations=5, directions=3,
                          native_icons=all(entry.ui_resources.icon(k) for k in ('cut','join','body','one','all')),
                          fields=len(s.inputs))
        except Exception:
            report.update(error=traceback.format_exc())
        save()


class Created(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            s = entry.Session(args.command)
            s.inputs['preview'].value = False
            lifetime.append(s)
            handler = Activate(s)
            lifetime.append(handler)
            args.command.activate.add(handler)
        except Exception:
            report.update(error=traceback.format_exc())
            save()


def finish(created=False):
    try:
        assert app.userInterface.activeCommand != definition.id, 'Confirm or cancel the test dialog first'
        assert report['passed'], report
        if created:
            assert design.timeline.count == timeline + 2, (timeline, design.timeline.count)
            assert body.volume < volume
            feature = comp.features.extrudeFeatures.item(comp.features.extrudeFeatures.count - 1)
            assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
            assert feature.name == 'Perforation (Cut)'
        else:
            assert design.timeline.count == timeline and abs(body.volume - volume) < 1e-9
        report.update(transaction='created' if created else 'cancelled', transaction_passed=True)
    except Exception:
        report.update(passed=False, transaction_error=traceback.format_exc())
    finally:
        doc.close(False)
        original.activate()
        report['original_unchanged'] = (original_design.timeline.count == original_timeline and
            abs(sum(b.volume for b in original_design.rootComponent.bRepBodies) - original_volume) < 1e-9)
        save()
    print('PERFORATE_UI_CONTRACT', report)


definition = app.userInterface.commandDefinitions.itemById('DiegoV_Perforate_UITest')
if definition:
    definition.deleteMe()
definition = app.userInterface.commandDefinitions.addButtonDefinition('DiegoV_Perforate_UITest', 'Perforate',
    'Native UI transaction test', str(Path(entry.__file__).parent / 'resources/toolbar-v015'))
handler = Created()
lifetime.append(handler)
definition.commandCreated.add(handler)
definition.execute()
