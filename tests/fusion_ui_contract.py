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
entry = globals().get('entry') or next(m for m in tuple(sys.modules.values())
             if str(getattr(m, '__file__', '')).endswith(('/Perfora/Perfora.py', '/Perforator/Perforator.py')))
app = adsk.core.Application.get()
original = app.activeDocument
original_design = adsk.fusion.Design.cast(app.activeProduct)
original_timeline = original_design.timeline.count
original_volume = sum(b.volume for b in original_design.rootComponent.bRepBodies)
result_mode = globals().get('result_mode', 'extrude')
layout_variant = globals().get('layout_variant')
distribution = globals().get('distribution', 'circular')
assert distribution in ('circular', 'path')
registered_command = globals().get('registered_command', False)
doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
design = adsk.fusion.Design.cast(app.activeProduct)
comp = design.rootComponent
spec = importlib.util.spec_from_file_location('_ui_fixture', root / 'PerforaSmokeTest/PerforaSmokeTest.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
body, face = fixture.plate(comp)
source_profile = globals().get('source_profile', False)
selected_source = face
if source_profile:
    boundary_sketch = comp.sketches.addWithoutEdges(face)
    boundary_sketch.sketchCurves.sketchCircles.addByCenterRadius(adsk.core.Point3D.create(), 1.1)
    selected_source = boundary_sketch.profiles.item(0)
anchor_sketch = comp.sketches.addWithoutEdges(comp.xYConstructionPlane)
anchor = anchor_sketch.sketchPoints.add(adsk.core.Point3D.create(.35, .2, 0))
variant_guides = []
if layout_variant == 'between_curves':
    guide_sketch = comp.sketches.addWithoutEdges(face)
    for y in (-.65, .65):
        guide = guide_sketch.sketchCurves.sketchLines.addByTwoPoints(
            adsk.core.Point3D.create(-1.4, y, 0), adsk.core.Point3D.create(1.4, y+.1, 0))
        guide.isConstruction = True
        variant_guides.append(guide)
    guide_sketch.isVisible = False
path_sketch = comp.sketches.addWithoutEdges(face)
path_curve = path_sketch.sketchCurves.sketchLines.addByTwoPoints(
    adsk.core.Point3D.create(-1.4, 0, 0), adsk.core.Point3D.create(1.4, 0, 0))
path_curve.isConstruction = True
design.userParameters.add('PerforaDefaultProbe', adsk.core.ValueInput.createByString('7 mm'), 'mm', '')
timeline = design.timeline.count
volume = body.volume
report = {'passed': False}
lifetime = []
output = Path.home() / 'Library/Logs/Perfora/ui-contract.json'
output.parent.mkdir(parents=True, exist_ok=True)


def save():
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def model_body(body):
    return entry.model.native(body)


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
            # Fusion can restore remembered values after commandCreated. Keep
            # bulk UI contract edits from launching intermediate CAD previews.
            s.inputs['preview'].value = False
            assert s.chosen('preview_color', entry.PREVIEW_COLORS) == 'gold'
            if hasattr(entry, 'parametric'):
                assert s.chosen('result', entry.RESULTS) == 'feature'
            choose(s, 'result', entry.RESULTS, 'extrude')
            choose(s, 'preview_mode', entry.PREVIEW_MODES, 'fast')
            s.inputs['source'].addSelection(selected_source)
            s.update_visibility()
            assert s.chosen('operation', entry.OPERATIONS) == 'cut'
            assert model_body(s.read()[2]['bodies'][0]) == body
            defaults = {k: (v.default_expression, v.value) for k, v in s.numeric_inputs.items()}
            assert all(expression.strip() for expression, _ in defaults.values())
            # Exercise every numeric field, including linked/hidden dimensions,
            # degrees, unitless percentages and all former integer spinners.
            s.updating = True
            try:
                for control in s.numeric_inputs.values():
                    control.expression = ''
            finally:
                s.updating = False
            restored = s.restore_empty_inputs()
            assert set(restored) == set(defaults)
            for key, (expression, value) in defaults.items():
                assert s.inputs[key].expression == expression, key
                assert s.inputs[key].isValidExpression and abs(s.inputs[key].value - value) < 1e-9, key
            s.inputs['gap'].expression = 'not_a_parameter'
            assert not s.inputs['gap'].isValidExpression
            s.restore_empty_inputs()
            assert s.inputs['gap'].expression == 'not_a_parameter', 'Nonempty errors must remain visible'
            s.inputs['gap'].expression = '1.5 mm'
            s.inputs['margin'].expression = '0'
            s.restore_empty_inputs()
            assert s.inputs['margin'].value == 0, 'An explicit zero is not an empty value'
            s.inputs['margin'].expression = '3 mm'
            s.inputs['grid_angle'].expression = '90 deg'
            assert abs(s.read()[1].grid_angle - 1.5707963267948966) < 1e-9
            s.inputs['grid_angle'].expression = '0 deg'
            s.inputs['size'].expression = '1 in / 2'
            s.sync_dimensions('size')
            assert abs(s.read()[1].size - 1.27) < 1e-9
            s.inputs['size'].expression = '5 mm'
            s.sync_dimensions('size')
            s.inputs['distance1'].expression = '2'
            assert s.read()[2]['distance1'] == '2 mm', 'Bare distances must retain the field units'
            s.inputs['distance1'].expression = '2 mm'
            s.inputs['size'].expression = 'PerforaDefaultProbe / 2'
            s.sync_dimensions('size')
            assert abs(s.read()[1].size - .35) < 1e-9
            s.inputs['size'].expression = '5 mm'
            s.sync_dimensions('size')
            for key, invalid in (('limit', '5001'), ('star_points', '2.5'), ('seed', '-1')):
                s.inputs[key].expression = invalid
                assert not s.inputs[key].isValidExpression, key
                s.inputs[key].expression = defaults[key][0]
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
            choose(s, 'shape', entry.SHAPES, 'slot')
            choose(s, 'layout', entry.LAYOUTS, 'circular')
            s.inputs['start_radius'].expression = '8 mm'
            choose(s, 'orientation', entry.ORIENTATIONS, 'radial')
            circular = s.read()[1]
            assert circular.layout == 'circular' and circular.radial_orientation
            assert abs(circular.start_radius - .8) < 1e-9
            assert s.inputs['start_radius'].isVisible and s.inputs['orientation'].isVisible
            choose(s, 'shape', entry.SHAPES, 'circle')
            assert not s.inputs['orientation'].isVisible and not s.read()[1].radial_orientation
            choose(s, 'shape', entry.SHAPES, 'voronoi')
            assert not s.inputs['start_radius'].isVisible and s.read()[1].layout == 'grid'
            s.inputs['start_radius'].expression = '-1 mm'
            assert s.read()[1].start_radius == 0, 'Inactive circular fields must not block Voronoi'
            choose(s, 'shape', entry.SHAPES, 'slot')
            choose(s, 'layout', entry.LAYOUTS, 'rows')
            assert s.read()[1].layout == 'grid' and not s.inputs['start_radius'].isVisible
            s.inputs['start_radius'].expression = '8 mm'
            choose(s, 'layout', entry.LAYOUTS, 'staggered')
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
            choose(s, 'operation', entry.OPERATIONS, 'cut')
            choose(s, 'result', entry.RESULTS, 'feature')
            assert s.read()[2]['result'] == 'feature' and s.inputs['output_group'].isVisible
            assert not s.inputs['extent1'].isVisible and not s.inputs['taper1'].isVisible
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
            choose(s, 'shape', entry.SHAPES, 'slot')
            s.inputs['slot_length'].expression = '9 mm'
            s.sync_dimensions('slot_length')
            choose(s, 'layout', entry.LAYOUTS, 'circular')
            choose(s, 'orientation', entry.ORIENTATIONS, 'tangential')
            s.inputs['center_point'].addSelection(anchor)
            assert s.read()[2]['center_point'] == anchor
            choose(s, 'layout', entry.LAYOUTS, 'rows')
            assert s.read()[2]['center_point'] == anchor
            assert s.inputs['center_point'].isVisible
            choose(s, 'layout', entry.LAYOUTS, 'circular')
            assert s.inputs['center_point'].isVisible and s.inputs['center_point'].selectionCount == 1
            choose(s, 'operation', entry.OPERATIONS, 'cut')
            s.inputs['clip_boundary'].value = True
            s.inputs['margin'].expression = '2 mm'
            s.inputs['spread_radius'].expression = '12 mm'
            assert s.read()[1].spread_radius==0
            assert not s.inputs['spread_radius'].isVisible
            assert s.read()[1].tangential_orientation
            assert not s.read()[1].radial_orientation
            s.inputs['preview'].value = True
            s.update_visibility()
            assert s.inputs['preview_color'].isVisible
            for color, _ in entry.PREVIEW_COLORS:
                choose(s, 'preview_color', entry.PREVIEW_COLORS, color)
            choose(s, 'preview_color', entry.PREVIEW_COLORS, 'gold')
            choose(s, 'preview_mode', entry.PREVIEW_MODES, 'exact')
            assert not s.inputs['preview_color'].isVisible
            choose(s, 'preview_mode', entry.PREVIEW_MODES, 'fast')
            assert s.inputs['preview_color'].isVisible
            choose(s, 'layout', entry.LAYOUTS, 'path')
            assert s.inputs['path'].isVisible and s.inputs['path_spacing'].isVisible
            assert s.inputs['path_orientation'].isVisible
            assert not any(s.inputs[k].isVisible for k in
                           ('center_point', 'spread_radius', 'grid_angle', 'offset_x', 'offset_y', 'orientation', 'start_radius'))
            try:
                s.read()
                raise AssertionError('Missing Path was accepted')
            except ValueError as error:
                assert 'Path' in str(error)
            s.inputs['path'].addSelection(path_curve)
            s.inputs['path_spacing'].expression = '12 mm'
            s.inputs['path_start'].expression = '1 mm'
            s.inputs['path_end'].expression = '1 mm'
            s.inputs['path_position'].expression = '0 mm'
            choose(s, 'path_orientation', entry.PATH_ORIENTATIONS, 'tangent')
            s.inputs['path_reverse'].value = True
            path_settings, path_config = s.read()[1:]
            assert path_settings.layout == 'path' and path_settings.path_reverse
            assert path_settings.path_orientation == 'tangent'
            assert abs(path_settings.path_spacing - 1.2) < 1e-9
            assert path_config['path'] == path_curve and path_config['center_point'] is None
            choose(s, 'shape', entry.SHAPES, 'circle')
            assert not s.inputs['path_orientation'].isVisible
            choose(s, 'shape', entry.SHAPES, 'voronoi')
            assert not s.inputs['path'].isVisible and s.read()[1].layout == 'grid'
            choose(s, 'shape', entry.SHAPES, 'slot')
            choose(s, 'layout', entry.LAYOUTS, distribution)
            # Path controls retain their values on switching back; old Circular
            # acceptance still leaves the original circular scenario selected.
            assert s.read()[1].layout == distribution
            for key, control in s.inputs.items():
                assert not re.search('[А-Яа-яЁё]', control.name + control.tooltip), key
            choose(s, 'result', entry.RESULTS, result_mode)
            if layout_variant:
                s.inputs['spread_radius'].expression = '0 mm'
                for key, guide in zip(('guide1', 'guide2'), variant_guides):
                    s.inputs[key].addSelection(guide)
                choose(s, 'layout', entry.LAYOUTS, layout_variant)
                assert s.read()[1].layout == layout_variant
                for key in entry.VARIANT_PARAMETERS:
                    assert s.inputs[key].isVisible == (key in entry.LAYOUT_PARAMETERS[layout_variant]), key
                assert s.inputs['guide1'].isVisible == (layout_variant == 'between_curves')
                assert s.inputs['seed'].isVisible == (layout_variant == 'poisson')
            report.update(result_mode=result_mode, registered_command=registered_command, source_profile=source_profile,
                          layout_variant=layout_variant,
                          passed=True, stage='ready', shapes=len(entry.SHAPES), operations=5, directions=3,
                          distributions=len(entry.LAYOUTS), distribution=distribution, settings=str(s.read()[1]),
                          numeric_defaults=len(defaults),
                          native_icons=all(entry.ui_resources.icon(k) for k in ('cut','join','body','one','all')),
                          fields=len(s.inputs))
        except Exception:
            report.update(error=traceback.format_exc())
        save()


class Created(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            s = entry._sessions[-1] if registered_command else entry.Session(args.command)
            assert s.command == args.command
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
            assert design.timeline.count == timeline + (2 if result_mode == 'extrude' else 1), (timeline, design.timeline.count)
            if result_mode == 'profiles':
                assert abs(body.volume - volume) < 1e-9
                assert comp.sketches.item(comp.sketches.count - 1).profiles.count > 0
                assert comp.features.extrudeFeatures.count == 1
                assert comp.features.customFeatures.count == 0
            else:
                assert body.volume < volume
                collection = comp.features.customFeatures if result_mode == 'feature' else comp.features.extrudeFeatures
                feature = collection.item(collection.count - 1)
                assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
                assert feature.name.startswith('Perfora') if result_mode == 'feature' else feature.name == 'Perforation (Cut)'
        else:
            assert design.timeline.count == timeline and abs(body.volume - volume) < 1e-9
        report.update(transaction='created' if created else 'cancelled', transaction_passed=True)
    except Exception:
        report.update(passed=False, transaction_error=traceback.format_exc())
    finally:
        definition.commandCreated.remove(handler)
        doc.close(False)
        original.activate()
        report['original_unchanged'] = (original_design.timeline.count == original_timeline and
            abs(sum(b.volume for b in original_design.rootComponent.bRepBodies) - original_volume) < 1e-9)
        save()
    print('PERFORATE_UI_CONTRACT', report)


if registered_command:
    definition = app.userInterface.commandDefinitions.itemById('DiegoV_Perforator')
    assert definition, 'Run the registered Perfora add-in first'
else:
    definition = app.userInterface.commandDefinitions.itemById('DiegoV_Perforate_UITest')
    if definition:
        definition.deleteMe()
    definition = app.userInterface.commandDefinitions.addButtonDefinition('DiegoV_Perforate_UITest', 'Perforate',
        'Native UI transaction test', str(Path(entry.__file__).parent / 'resources/toolbar-v015'))
handler = Created()
lifetime.append(handler)
definition.commandCreated.add(handler)
definition.execute()
