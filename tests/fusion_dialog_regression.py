# SPDX-License-Identifier: GPL-3.0-only
"""Execute in Fusion's Py console; exercises the real Session and native inputs.

exec(open('/path/to/tests/fusion_dialog_regression.py').read())
The report is written to ~/Library/Logs/Perfora/dialog-regression.json.
No CAD geometry is changed. Cancel the test dialog when finished.
"""
import json
from pathlib import Path
import re
import sys
import traceback

import adsk.core

_dialog_entry = globals().get('entry') or next(module for module in tuple(sys.modules.values())
                     if str(getattr(module, '__file__', '')).endswith('/Perfora/Perfora.py'))
_dialog_report = Path.home() / 'Library/Logs/Perfora/dialog-regression.json'
_dialog_report.parent.mkdir(parents=True, exist_ok=True)
_dialog_lifetime = []


class PerforaDialogRegression(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        report = {'passed': False}
        try:
            session = _dialog_entry.Session(args.command)
            session.inputs['preview'].value = False
            session.update_visibility()
            assert session.chosen('preview_color', _dialog_entry.PREVIEW_COLORS) == 'gold'
            assert not session.inputs['preview_color'].isVisible
            session.inputs['preview'].value = True
            session.update_visibility()
            assert session.inputs['preview_color'].isVisible
            session.inputs['preview_mode'].listItems.item(1).isSelected = True
            session.update_visibility()
            assert not session.inputs['preview_color'].isVisible
            session.inputs['preview'].value = False
            session.inputs['preview_mode'].listItems.item(0).isSelected = True
            session.update_visibility()
            _dialog_lifetime.append(session)
            assert len(session.handlers) == 9, 'Missing command handlers'
            assert any(isinstance(handler, _dialog_entry.PreSelect) for handler in session.handlers)
            assert all(key in session.inputs for key in ('status', 'bodies', 'distance2', 'preview'))
            assert 'clip_boundary' in session.inputs and not session.inputs['clip_boundary'].value
            session.inputs['clip_boundary'].value = True
            session.update_visibility()
            assert session.inputs['margin'].isEnabled, 'Clipping must keep the edge margin active'
            session.inputs['clip_boundary'].value = False
            assert len(_dialog_entry.SHAPES) == 19 and _dialog_entry.SHAPES[-1][0]=='voronoi'
            for index, (shape, _) in enumerate(_dialog_entry.SHAPES):
                session.inputs['shape'].listItems.item(index).isSelected = True
                session.update_visibility()
                size_id = session.dimension_id(_dialog_entry.SIZE_FIELDS, shape)
                length_id = session.dimension_id(_dialog_entry.LENGTH_FIELDS, shape)
                for identifier in _dialog_entry.SIZE_FIELDS:
                    assert session.inputs[identifier].isVisible == (identifier == size_id)
                for identifier in _dialog_entry.LENGTH_FIELDS:
                    assert session.inputs[identifier].isVisible == (identifier == length_id)
                assert session.inputs['arm_width'].isVisible == (shape == 'cross')
                assert session.inputs['star_ratio'].isVisible == (shape == 'star')
                assert session.inputs['star_points'].isVisible == (shape == 'star')
                for identifier in ('irregularity', 'seed', 'new_pattern'):
                    assert session.inputs[identifier].isVisible == (shape == 'voronoi' or
                        identifier!='irregularity' and shape in _dialog_entry.ORGANIC_SHAPES)
                assert session.inputs['round_corners'].isVisible == (shape == 'voronoi')
                assert not session.inputs['corner_radius'].isVisible
                if shape == 'voronoi':
                    session.inputs['round_corners'].value = True
                    session.update_visibility()
                    assert session.inputs['corner_radius'].isVisible
                    session.inputs['round_corners'].value = False
                    session.update_visibility()
                assert session.inputs['layout'].isVisible == (shape != 'voronoi' and shape not in _dialog_entry.ORGANIC_SHAPES)
                assert session.inputs['shape_angle'].isVisible == (shape not in ('circle', 'voronoi') and shape not in _dialog_entry.ORGANIC_SHAPES)
                assert session.inputs[size_id].tooltip == _dialog_entry.SIZE_HELP[shape]
            session.inputs['shape'].listItems.item(0).isSelected = True
            session.update_visibility()
            session.inputs['layout'].listItems.item(2).isSelected = True
            session.update_visibility()
            assert session.inputs['center_point'].isVisible
            assert session.inputs['start_radius'].isVisible
            assert not session.inputs['orientation'].isVisible
            session.inputs['shape'].listItems.item(3).isSelected = True
            session.update_visibility()
            assert session.inputs['orientation'].isVisible
            session.inputs['orientation'].listItems.item(2).isSelected = True
            assert session.chosen('orientation', _dialog_entry.ORIENTATIONS) == 'tangential'
            session.inputs['shape'].listItems.item(12).isSelected = True
            session.update_visibility()
            assert session.inputs['center_point'].isVisible
            assert not session.inputs['start_radius'].isVisible and not session.inputs['orientation'].isVisible
            session.inputs['shape'].listItems.item(0).isSelected = True
            session.inputs['layout'].listItems.item(0).isSelected = True
            session.update_visibility()
            for identifier, options in (('result', _dialog_entry.RESULTS), ('layout', _dialog_entry.LAYOUTS)):
                expected = (adsk.core.ButtonRowCommandInput if identifier != 'layout' and all(_dialog_entry.ui_resources.icon(k) for k, _ in options)
                            else adsk.core.DropDownCommandInput)
                assert isinstance(session.inputs[identifier], expected), identifier
            for identifier in ('result', 'layout', 'direction', 'extent1', 'operation', 'start_mode'):
                for item in session.inputs[identifier].listItems:
                    if item.icon:
                        assert Path(item.icon).is_dir(), (identifier, item.name)
            for identifier, control in session.inputs.items():
                assert not re.search('[А-Яа-яЁё]', control.name + control.tooltip), identifier
            for control in session.inputs.values():
                if isinstance(control, adsk.core.GroupCommandInput):
                    if control.parentCommandInput and not control.isEnabledCheckBoxDisplayed:
                        assert control.isExpanded, 'A mandatory nested group must stay expanded'
            report.update(passed=True, inputs=len(session.inputs), handlers=len(session.handlers))
        except Exception:
            report['error'] = traceback.format_exc()
        _dialog_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


_dialog_ui = adsk.core.Application.get().userInterface
_dialog_ui.terminateActiveCommand()
_dialog_definition = _dialog_ui.commandDefinitions.itemById('DiegoV_Perfora_DialogRegression')
if _dialog_definition:
    _dialog_definition.deleteMe()
_dialog_definition = _dialog_ui.commandDefinitions.addButtonDefinition(
    'DiegoV_Perfora_DialogRegression', 'Perforate', 'Native dialog regression')
_dialog_handler = PerforaDialogRegression()
_dialog_lifetime.append(_dialog_handler)
_dialog_definition.commandCreated.add(_dialog_handler)
_dialog_definition.execute()
