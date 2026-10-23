# SPDX-License-Identifier: GPL-3.0-only
"""Add-in entry point. A standard Fusion command with transactional previews."""
import html
import math
from pathlib import Path
import traceback

import adsk.core
import adsk.fusion

from .geometry import Settings, LENGTH_SHAPES
from . import model, ui_resources
from .preview import Renderer

COMMAND_ID = 'DiegoV_Perforator'  # Stable ID for existing installations.
PANEL_ID = 'SolidCreatePanel'
_handlers = []
_sessions = []

SHAPES = [('circle', 'Circle'), ('hexagon', 'Hexagon'), ('square', 'Square'), ('slot', 'Slot'),
          ('triangle', 'Triangle'), ('rectangle', 'Rectangle'), ('diamond', 'Diamond'),
          ('ellipse', 'Ellipse'), ('pentagon', 'Pentagon'), ('octagon', 'Octagon'),
          ('cross', 'Cross'), ('star', 'Star'), ('voronoi', 'Voronoi')]
SIZE_HELP = {
    'circle': 'Diameter of the circular hole.',
    'hexagon': 'Distance between opposite flats of the hexagon.',
    'square': 'Side length of the square.',
    'slot': 'Slot width. Length includes both round ends.',
    'triangle': 'Side length of the equilateral triangle.',
    'rectangle': 'Width of the rectangle. Set its length separately.',
    'diamond': 'First diagonal of the diamond before rotation. Set the second diagonal separately.',
    'ellipse': 'Full minor axis of the ellipse. The major axis must be greater than the minor axis.',
    'pentagon': 'Diameter of the circumscribed circle of the regular pentagon.',
    'octagon': 'Distance between opposite flats of the regular octagon.',
    'cross': 'Overall width and height of the cross. Arm Width controls the width of each arm.',
    'star': 'Outer diameter of the star. Inner Radius is a percentage of the outer radius.',
    'voronoi': 'Nominal distance between Voronoi sites. Smaller spacing creates more holes. Web Thickness is independent.'}
SIZE_FIELDS = {
    'size': ('Diameter', ('circle', 'pentagon', 'star')),
    'size_flats': ('Across Flats', ('hexagon', 'octagon')),
    'size_side': ('Side Length', ('square', 'triangle')),
    'size_width': ('Width', ('slot', 'rectangle')),
    'size_diagonal': ('Diagonal 1', ('diamond',)),
    'size_minor': ('Minor Axis', ('ellipse',)),
    'size_overall': ('Overall Size', ('cross',)),
    'cell_spacing': ('Cell Spacing', ('voronoi',))}
LENGTH_FIELDS = {
    'slot_length': ('Length', ('slot', 'rectangle')),
    'length_diagonal': ('Diagonal 2', ('diamond',)),
    'length_major': ('Major Axis', ('ellipse',))}
AREA_FIELDS = {'width': ('Width', ('rectangle',)), 'area_diameter': ('Diameter', ('circle',))}
RESULTS = [('profiles', 'Sketch'), ('extrude', 'Extrude')]
MATERIALS = [('cells', 'Holes'), ('panel', 'Perforated Panel')]
OPERATIONS = [('join', 'Join'), ('cut', 'Cut'), ('intersect', 'Intersect'),
              ('body', 'New Body'), ('component', 'New Component')]
DIRECTIONS = [('one', 'One Side'), ('two', 'Two Sides'), ('symmetric', 'Symmetric')]
EXTENTS = [('distance', 'Distance'), ('object', 'To Object'), ('all', 'All')]
STARTS = [('profile', 'Profile Plane'), ('offset', 'Offset')]
LAYOUTS = [('staggered', 'Staggered'), ('rows', 'Rectangular')]
PREVIEW_MODES = [('fast', 'Fast'), ('exact', 'Full')]


def log_error():
    app = adsk.core.Application.get()
    app.log('Perfora: ' + traceback.format_exc())


class Session:
    def __init__(self, command):
        self.command = command
        self.inputs = {}
        self.handlers = []
        self.updating = False
        self.preview_error = ''
        self._status_text = None
        self.renderer = Renderer()
        command.setDialogInitialSize(320, 780)
        command.okButtonText = 'OK'
        command.isRepeatable = True
        root = command.commandInputs
        self.button_row(root, 'result', 'Type', RESULTS)
        self.inputs['result'].listItems.item(1).isSelected = True
        self.selection(root, 'source', 'Profiles', ['PlanarFaces', 'Profiles', 'ConstructionPlanes'], 1, 1,
                       'Select a planar face, a closed sketch profile, or a construction plane.')

        area = self.group(root, 'area_group', 'Boundary')
        self.dropdown(area, 'boundary', 'Shape', [('rectangle', 'Rectangle'), ('circle', 'Circle')])
        for identifier, (label, _) in AREA_FIELDS.items():
            self.number(area, identifier, label, '80 mm')
        self.number(area, 'height', 'Height', '60 mm')

        pattern = self.group(root, 'pattern_group', 'Pattern')
        self.dropdown(pattern, 'shape', 'Hole Shape', SHAPES)
        for identifier, (label, _) in SIZE_FIELDS.items():
            self.number(pattern, identifier, label, '5 mm')
        for identifier, (label, _) in LENGTH_FIELDS.items():
            self.number(pattern, identifier, label, '12 mm')
        self.number(pattern, 'arm_width', 'Arm Width', '1.5 mm')
        self.inputs['star_points'] = pattern.addIntegerSpinnerCommandInput('star_points', 'Points', 3, 12, 1, 5)
        self.number(pattern, 'star_ratio', 'Inner Radius (%)', '45', '')
        self.inputs['irregularity'] = pattern.addIntegerSpinnerCommandInput(
            'irregularity', 'Irregularity (%)', 0, 100, 5, 80)
        self.inputs['irregularity'].tooltip = ('0% creates regular square cells. Higher values create more varied '
            'Voronoi polygons while keeping the minimum Web Thickness.')
        self.inputs['seed'] = pattern.addIntegerSpinnerCommandInput('seed', 'Seed', 0, 2147483647, 1, 1)
        self.inputs['seed'].tooltip = 'The same Seed and settings reproduce the same pattern.'
        self.inputs['new_pattern'] = pattern.addBoolValueInput('new_pattern', '', False, '', False)
        self.inputs['new_pattern'].text = 'New Pattern'
        self.inputs['new_pattern'].isFullWidth = True
        self.inputs['new_pattern'].tooltip = 'Increment Seed to explore another pattern without changing its spacing.'
        self.check(pattern, 'round_corners', 'Round Corners', False)
        self.number(pattern, 'corner_radius', 'Corner Radius', '0.5 mm')
        self.inputs['corner_radius'].tooltip = ('Maximum corner radius. Short bevels are absorbed; the radius is reduced only for narrow holes. '
            'Rounding stays inside each hole and preserves the minimum Web Thickness. '
            'New convex corners at line and circular-arc trim boundaries are also rounded.')
        self.number(pattern, 'gap', 'Web Thickness', '1.5 mm')
        self.inputs['gap'].tooltip = 'Minimum material thickness between adjacent holes.'
        self.number(pattern, 'margin', 'Edge Offset', '3 mm')
        self.inputs['margin'].tooltip = 'Material border around the outside boundary and existing openings.'
        self.check(pattern, 'clip_boundary', 'Trim to Boundary', False)
        self.inputs['clip_boundary'].tooltip = ('Trim intersecting holes to the boundary after applying Edge Offset. '
            'Clear this option to keep only complete holes.')
        self.button_row(pattern, 'layout', 'Distribution', LAYOUTS)

        more = self.group(root, 'more_group', 'Placement', False)
        self.number(more, 'grid_angle', 'Pattern Angle', '0 deg', 'deg')
        self.number(more, 'shape_angle', 'Hole Angle', '0 deg', 'deg')
        self.number(more, 'offset_x', 'X Offset', '0 mm')
        self.number(more, 'offset_y', 'Y Offset', '0 mm')
        self.inputs['limit'] = more.addIntegerSpinnerCommandInput('limit', 'Maximum Holes', 1, 5000, 100, 1500)

        self.dropdown(root, 'material', 'Profile Type', MATERIALS)
        self.inputs['material'].tooltip = ('Holes creates the hole profiles. Perforated Panel creates the surrounding '
                                           'material. Use Perforated Panel with New Body for a separate grille.')
        output = self.group(root, 'output_group', 'Extrude')
        self.dropdown(output, 'start_mode', 'Start', STARTS, icons=True)
        self.number(output, 'start', 'Offset', '0 mm')
        self.dropdown(output, 'direction', 'Direction', DIRECTIONS, icons=True)
        self.check(output, 'reverse', 'Flip Direction', True, icon='reverse')
        self.dropdown(output, 'extent1', 'Extent Type', EXTENTS, icons=True)
        self.number(output, 'distance1', 'Distance', '2 mm')
        self.selection(output, 'target1', 'Object', ['Faces', 'ConstructionPlanes'], 0, 1)
        self.number(output, 'object_offset1', 'Offset', '0 mm')
        self.number(output, 'taper1', 'Taper Angle', '0 deg', 'deg')

        side2 = self.group(output, 'side2', 'Side 2')
        self.dropdown(side2, 'extent2', 'Extent Type', EXTENTS, icons=True)
        self.number(side2, 'distance2', 'Distance', '2 mm')
        self.selection(side2, 'target2', 'Object', ['Faces', 'ConstructionPlanes'], 0, 1)
        self.number(side2, 'object_offset2', 'Offset', '0 mm')
        self.number(side2, 'taper2', 'Taper Angle', '0 deg', 'deg')
        self.dropdown(output, 'operation', 'Operation', OPERATIONS, icons=True)
        self.inputs['operation'].listItems.item(1).isSelected = True
        self.selection(output, 'bodies', 'Objects', ['SolidBodies'], 0, 0,
                       'Select the bodies to cut or intersect. The selected face body is included by default.')
        self.check(root, 'preview', 'Preview', True)
        self.dropdown(root, 'preview_mode', 'Preview Type', PREVIEW_MODES)
        self.inputs['preview_mode'].tooltip = ('Fast displays cached contours on the profile plane. Full previews the '
            'complete extrusion. OK always creates the exact sketch or Extrude feature.')
        self.inputs['status'] = root.addTextBoxCommandInput('status', '', '', 2, True)
        self.inputs['status'].isFullWidth = True
        self.inputs['status'].isVisible = False
        self.connect(command.inputChanged, Changed(self))
        self.connect(command.validateInputs, Validate(self))
        self.connect(command.executePreview, Execute(self, True))
        self.connect(command.execute, Execute(self, False))
        self.connect(command.destroy, Destroy(self))
        self.update_visibility()
        command.setDialogSize(320, 0)

    def connect(self, event, handler):
        event.add(handler)
        self.handlers.append(handler)

    def group(self, parent, identifier, title, expanded=True):
        group = parent.addGroupCommandInput(identifier, title)
        group.isExpanded = expanded
        self.inputs[identifier] = group
        return group.children

    def dropdown(self, parent, identifier, title, options, icons=False):
        paths = [ui_resources.icon(key) for key, _ in options] if icons else []
        style = (adsk.core.DropDownStyles.LabeledIconDropDownStyle if paths and all(paths)
                 else adsk.core.DropDownStyles.TextListDropDownStyle)
        control = parent.addDropDownCommandInput(identifier, title, style)
        for index, (_, label) in enumerate(options):
            control.listItems.add(label, index == 0, paths[index] if paths else '')
        self.inputs[identifier] = control

    def button_row(self, parent, identifier, title, options):
        paths = [ui_resources.icon(key) for key, _ in options]
        if not all(paths):
            self.dropdown(parent, identifier, title, options)
            return
        control = parent.addButtonRowCommandInput(identifier, title, False)
        for index, (_, label) in enumerate(options):
            control.listItems.add(label, index == 0, paths[index])
        self.inputs[identifier] = control

    def number(self, parent, identifier, title, expression, unit='mm'):
        self.inputs[identifier] = parent.addValueInput(identifier, title, unit, model.value(expression))

    def check(self, parent, identifier, title, default, icon=''):
        resource = ui_resources.icon(icon)
        self.inputs[identifier] = parent.addBoolValueInput(identifier, title, not bool(resource), resource, default)

    def dimension_id(self, fields, shape):
        return next((identifier for identifier, (_, shapes) in fields.items() if shape in shapes), None)

    def sync_dimensions(self, identifier):
        for fields in (SIZE_FIELDS, LENGTH_FIELDS, AREA_FIELDS):
            if identifier not in fields:
                continue
            self.updating = True
            try:
                expression = self.inputs[identifier].expression
                for linked in fields:
                    if linked != identifier and self.inputs[linked].expression != expression:
                        self.inputs[linked].expression = expression
            finally:
                self.updating = False

    def selection(self, parent, identifier, title, filters, minimum, maximum, tooltip=''):
        control = parent.addSelectionInput(identifier, title, tooltip or title)
        for name in filters:
            control.addSelectionFilter(name)
        control.setSelectionLimits(minimum, maximum)
        self.inputs[identifier] = control

    def chosen(self, identifier, options):
        return options[self.inputs[identifier].selectedItem.index][0]

    def selected_source(self):
        selection = self.inputs['source']
        return model.native(selection.selection(0).entity) if selection.selectionCount else None

    def status(self, message):
        if message != self._status_text:
            self._status_text = message
            self.inputs['status'].formattedText = html.escape(message).replace('\n', '<br>')
            self.inputs['status'].isVisible = bool(message)

    def update_visibility(self):
        if self.updating:
            return
        self.updating = True
        try:
            d = self.inputs
            source = self.selected_source()
            is_plane = isinstance(source, adsk.fusion.ConstructionPlane)
            def visible(identifier, enabled):
                if d[identifier].isVisible != enabled:
                    d[identifier].isVisible = enabled
            visible('area_group', is_plane)
            boundary = self.chosen('boundary', [('rectangle', ''), ('circle', '')])
            for identifier, (_, shapes) in AREA_FIELDS.items():
                visible(identifier, boundary in shapes)
            visible('height', boundary == 'rectangle')
            shape = self.chosen('shape', SHAPES)
            for fields in (SIZE_FIELDS, LENGTH_FIELDS):
                for identifier, (_, shapes) in fields.items():
                    visible(identifier, shape in shapes)
            size_id = self.dimension_id(SIZE_FIELDS, shape)
            self.inputs[size_id].tooltip = SIZE_HELP[shape]
            visible('arm_width', shape == 'cross')
            visible('star_points', shape == 'star')
            visible('star_ratio', shape == 'star')
            for identifier in ('irregularity', 'seed', 'new_pattern', 'round_corners'):
                visible(identifier, shape == 'voronoi')
            visible('corner_radius', shape == 'voronoi' and d['round_corners'].value)
            visible('layout', shape != 'voronoi')
            visible('shape_angle', shape not in ('circle', 'voronoi'))
            is_extrude = self.chosen('result', RESULTS) == 'extrude'
            direction = self.chosen('direction', DIRECTIONS)
            visible('output_group', is_extrude)
            visible('start', is_extrude and self.chosen('start_mode', STARTS) == 'offset')
            visible('side2', is_extrude and direction == 'two')
            visible('reverse', is_extrude and direction == 'one')
            d['distance1'].tooltip = ('Full length of the symmetric extrusion.'
                                      if direction == 'symmetric' else 'Extrusion distance for Side 1.')
            for side in ('1', '2'):
                kind = self.chosen('extent' + side, EXTENTS)
                symmetric = direction == 'symmetric' and side == '1'
                side_visible = is_extrude and (side == '1' or direction == 'two')
                visible('extent' + side, side_visible and not symmetric)
                visible('distance' + side, side_visible and (symmetric or kind == 'distance'))
                visible('target' + side, side_visible and not symmetric and kind == 'object')
                visible('object_offset' + side, side_visible and not symmetric and kind == 'object')
            uses_bodies = is_extrude and self.chosen('operation', OPERATIONS) in ('cut', 'intersect')
            visible('bodies', uses_bodies)
            visible('preview_mode', d['preview'].value)
            if uses_bodies and isinstance(source, adsk.fusion.BRepFace) and not d['bodies'].selectionCount:
                # The selection API expects the visible assembly proxy when present.
                visible_face = d['source'].selection(0).entity
                d['bodies'].addSelection(visible_face.body)
        finally:
            self.updating = False

    def read(self):
        d = self.inputs
        source = self.selected_source()
        if not source:
            raise ValueError('Select a profile, planar face, or construction plane.')
        # Hidden optional inputs must not block a different mode after an edit.
        shape = self.chosen('shape', SHAPES)
        size_id = self.dimension_id(SIZE_FIELDS, shape)
        length_id = self.dimension_id(LENGTH_FIELDS, shape)
        required = [size_id, 'gap', 'margin', 'grid_angle', 'offset_x', 'offset_y']
        if shape not in ('circle', 'voronoi'):
            required.append('shape_angle')
        if shape in LENGTH_SHAPES:
            required.append(length_id)
        if shape == 'cross':
            required.append('arm_width')
        if shape == 'star':
            required.append('star_ratio')
        if shape == 'voronoi' and d['round_corners'].value:
            required.append('corner_radius')
        boundary = self.chosen('boundary', [('rectangle', ''), ('circle', '')])
        width_id = self.dimension_id(AREA_FIELDS, boundary)
        if isinstance(source, adsk.fusion.ConstructionPlane):
            required += [width_id] + (['height'] if boundary == 'rectangle' else [])
        result, direction = self.chosen('result', RESULTS), self.chosen('direction', DIRECTIONS)
        if result == 'extrude':
            required += ['taper1']
            if self.chosen('start_mode', STARTS) == 'offset':
                required.append('start')
            for side in (('1', '2') if direction == 'two' else ('1',)):
                kind = 'distance' if direction == 'symmetric' else self.chosen('extent' + side, EXTENTS)
                if kind == 'distance':
                    required.append('distance' + side)
                    if d['distance' + side].isValidExpression and d['distance' + side].value <= 0:
                        raise ValueError('Distance must be positive. Use Flip Direction to change sides.')
                elif kind == 'object':
                    required.append('object_offset' + side)
                    if not d['target' + side].selectionCount:
                        raise ValueError('Select an Object for Side ' + side + '.')
            if direction == 'two':
                required.append('taper2')
        for identifier in required:
            if not d[identifier].isValidExpression:
                raise ValueError('Check the value of ' + d[identifier].name + '.')
        if shape == 'voronoi' and d['round_corners'].value and d['corner_radius'].value <= 0:
            raise ValueError('Corner Radius must be positive. Clear Round Corners for sharp corners.')
        settings = Settings(shape=shape, size=d[size_id].value,
                            slot_length=d[length_id].value if length_id else d[size_id].value,
                            gap=d['gap'].value, margin=d['margin'].value,
                            staggered=shape != 'voronoi' and self.chosen('layout', LAYOUTS) == 'staggered',
                            grid_angle=d['grid_angle'].value,
                            shape_angle=d['shape_angle'].value if shape not in ('circle', 'voronoi') else 0,
                            offset_x=d['offset_x'].value, offset_y=d['offset_y'].value, limit=d['limit'].value,
                            clip_boundary=d['clip_boundary'].value,
                            arm_width=d['arm_width'].value if shape == 'cross' else 0.15,
                            star_ratio=d['star_ratio'].value / 100 if shape == 'star' else 0.45,
                            star_points=d['star_points'].value if shape == 'star' else 5,
                            irregularity=d['irregularity'].value / 100 if shape == 'voronoi' else 0.8,
                            seed=d['seed'].value if shape == 'voronoi' else 1,
                            corner_radius=d['corner_radius'].value
                                if shape == 'voronoi' and d['round_corners'].value else 0)
        settings.validate()
        config = {
            'boundary': boundary, 'width': d[width_id].value, 'height': d['height'].value,
            'result': result, 'material': self.chosen('material', MATERIALS),
            'operation': self.chosen('operation', OPERATIONS), 'direction': direction,
            'reverse': d['reverse'].value,
            'start': d['start'].expression if self.chosen('start_mode', STARTS) == 'offset' else '0 mm',
            'bodies': [d['bodies'].selection(i).entity for i in range(d['bodies'].selectionCount)],
        }
        for side in ('1', '2'):
            for key in ('distance', 'taper', 'object_offset'):
                config[key + side] = d[key + side].expression
            config['extent' + side] = self.chosen('extent' + side, EXTENTS)
            control = d['target' + side]
            config['target' + side] = control.selection(0).entity if control.selectionCount else None
        if result == 'extrude' and config['operation'] in ('cut', 'intersect'):
            if not config['bodies']:
                raise ValueError('Select Objects for Cut or Intersect.')
            component = model.source_component(source)
            if any(model.native(body).parentComponent != component for body in config['bodies']):
                raise ValueError('Profiles and Objects must belong to the same component.')
        for side in (('1', '2') if direction == 'two' else ('1',)):
            if result == 'extrude' and abs(d['taper' + side].value) >= math.pi / 2:
                raise ValueError('Taper Angle must be between -90 deg and 90 deg.')
        return source, settings, config


class Changed(adsk.core.InputChangedEventHandler):
    def __init__(self, session):
        super().__init__()
        self.session = session

    def notify(self, args):
        if self.session.updating or args.input.id == 'status':
            return
        # Folding sections changes presentation, not perforation parameters.
        if isinstance(args.input, adsk.core.GroupCommandInput):
            return
        try:
            if args.input.id == 'new_pattern':
                self.session.updating = True
                try:
                    d = self.session.inputs
                    d['seed'].value = (d['seed'].value + 1) % 2147483648
                    d['new_pattern'].value = False
                finally:
                    self.session.updating = False
            self.session.sync_dimensions(args.input.id)
            if args.input.id in ('source', 'boundary', 'width', 'area_diameter', 'height'):
                self.session.renderer.reset()
            self.session.preview_error = ''
            self.session.update_visibility()
            self.session.read()
            self.session.status('' if self.session.inputs['preview'].value else 'Preview is off. Click OK to create the result.')
        except ValueError as error:
            self.session.status(str(error))
        except Exception:
            log_error()
            self.session.status('Unable to update the command. See the Fusion log for details.')


class Validate(adsk.core.ValidateInputsEventHandler):
    def __init__(self, session):
        super().__init__()
        self.session = session

    def notify(self, args):
        try:
            self.session.read()
            args.areInputsValid = True
        except Exception as error:
            args.areInputsValid = False
            self.session.status(str(error))


class Execute(adsk.core.CommandEventHandler):
    def __init__(self, session, preview):
        super().__init__()
        self.session = session
        self.preview = preview

    def notify(self, args):
        if self.preview:
            args.isValidResult = False
            if not self.session.inputs['preview'].value:
                self.session.renderer.clear()
                return
        try:
            source, settings, config = self.session.read()
            if self.preview and self.session.chosen('preview_mode', PREVIEW_MODES) == 'fast':
                count = self.session.renderer.show(source, settings, config)
                self.session.status('%d holes. Fast preview.' % count)
                return
            self.session.renderer.clear()
            sketch, feature, count = model.build(source, settings, config)
            message = '%d holes. %s' % (count, 'Sketch ready.' if feature is None else 'Extrude ready.')
            if feature and feature.healthState == adsk.fusion.FeatureHealthStates.WarningFeatureHealthState:
                message += '\n' + feature.errorOrWarningMessage
            self.session.status(message)
            # A successful exact preview is already the final native result.
            # Fusion commits it on OK without constructing the model a second time.
            if self.preview:
                args.isValidResult = True
        except Exception as error:
            self.session.renderer.clear()
            if not isinstance(error, ValueError):
                log_error()
            self.session.preview_error = str(error)
            self.session.status(('Preview: ' if self.preview else '') + str(error))
            if not self.preview:
                args.executeFailed = True
                args.executeFailedMessage = str(error)


class Destroy(adsk.core.CommandEventHandler):
    def __init__(self, session):
        super().__init__()
        self.session = session

    def notify(self, args):
        self.session.renderer.reset()
        if self.session in _sessions:
            _sessions.remove(self.session)
        self.session.handlers.clear()


class Created(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
            if not design:
                raise ValueError('Open a Fusion Design document.')
            _sessions.append(Session(args.command))
        except Exception as error:
            log_error()
            adsk.core.Application.get().userInterface.messageBox(str(error), 'Perfora')


def run(context):
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        definition = ui.commandDefinitions.itemById(COMMAND_ID)
        if not definition:
            resources = str(Path(__file__).parent / 'resources' / 'toolbar-f692fbb3')
            definition = ui.commandDefinitions.addButtonDefinition(
                COMMAND_ID, 'Perfora', 'Create a hole pattern as sketch profiles or an Extrude feature.', resources)
        handler = Created()
        definition.commandCreated.add(handler)
        _handlers.append(handler)
        panel = ui.allToolbarPanels.itemById(PANEL_ID)
        if not panel:
            raise RuntimeError('The Create panel is not available in the Design workspace.')
        if not panel.controls.itemById(COMMAND_ID):
            control = panel.controls.addCommand(definition)
            control.isPromoted = True
            control.isPromotedByDefault = True
    except Exception:
        log_error()
        adsk.core.Application.get().userInterface.messageBox(traceback.format_exc(), 'Perfora - Start')


def stop(context):
    try:
        ui = adsk.core.Application.get().userInterface
        panel = ui.allToolbarPanels.itemById(PANEL_ID)
        if panel:
            control = panel.controls.itemById(COMMAND_ID)
            if control:
                control.deleteMe()
        definition = ui.commandDefinitions.itemById(COMMAND_ID)
        if definition:
            definition.deleteMe()
        _handlers.clear()
    except Exception:
        log_error()
