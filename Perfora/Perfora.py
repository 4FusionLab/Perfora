# SPDX-License-Identifier: GPL-3.0-only
"""Add-in entry point. A standard Fusion command with transactional previews."""
import html
import math
from pathlib import Path
import traceback
from threading import Timer
from uuid import uuid4

import adsk.core
import adsk.fusion

from .geometry import Settings, LENGTH_SHAPES, ORGANIC_SHAPES, ORGANIC_FIELDS
from . import model, ui_resources, cylindrical, surface, multi_region, feature as parametric
from .preview import Renderer, PREVIEW_COLORS
from .numeric_inputs import NumericInput
from .distributions import VARIANT_PARAMETERS, LAYOUT_PARAMETERS
from .organic import (PARAMETERS as ORGANIC_PARAMETERS, LABELS as ORGANIC_LABELS,
                      DEFAULT_OPEN, DEFAULT_CELL_SIZE, DEFAULT_WEB)

COMMAND_ID = 'DiegoV_Perforator'  # Stable ID for existing installations.
PANEL_ID = 'SolidCreatePanel'
_handlers = []
_sessions = []

SHAPES = [('circle', 'Circle'), ('hexagon', 'Hexagon'), ('square', 'Square'), ('slot', 'Slot'),
          ('triangle', 'Triangle'), ('rectangle', 'Rectangle'), ('diamond', 'Diamond'),
          ('ellipse', 'Ellipse'), ('pentagon', 'Pentagon'), ('octagon', 'Octagon'),
          ('cross', 'Cross'), ('star', 'Star')] + list(zip(ORGANIC_SHAPES, ORGANIC_LABELS)) + [('voronoi', 'Voronoi')]
PATTERN_SHAPES = [(key, label) for key, label in SHAPES if key not in ORGANIC_SHAPES]
FIELD_SHAPES = list(zip(ORGANIC_SHAPES, ORGANIC_LABELS))
PATTERN_TYPES = [('pattern', 'Pattern'), ('organic', 'Organic Field')]
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
SIZE_HELP.update({key: 'Characteristic cell size of the field. Larger values create broader, fewer cells. Web Thickness sets the material between openings.' for key in ORGANIC_FIELDS})
SIZE_HELP['blue_noise'] = 'Maximum circular hole diameter. Size Variation and Size Gradient control smaller holes; Web Thickness is checked using both radii.'
SIZE_FIELDS = {
    'size': ('Diameter', ('circle', 'pentagon', 'star')),
    'size_flats': ('Across Flats', ('hexagon', 'octagon')),
    'size_side': ('Side Length', ('square', 'triangle')),
    'size_width': ('Width', ('slot', 'rectangle')),
    'size_diagonal': ('Diagonal 1', ('diamond',)),
    'size_minor': ('Minor Axis', ('ellipse',)),
    'size_overall': ('Overall Size', ('cross',)),
    'cell_spacing': ('Cell Spacing', ('voronoi',)),
    'organic_scale': ('Cell Size', ORGANIC_FIELDS),
    'blue_diameter': ('Maximum Diameter', ('blue_noise',))}
LENGTH_FIELDS = {
    'slot_length': ('Length', ('slot', 'rectangle')),
    'length_diagonal': ('Diagonal 2', ('diamond',)),
    'length_major': ('Major Axis', ('ellipse',))}
AREA_FIELDS = {'width': ('Width', ('rectangle',)), 'area_diameter': ('Diameter', ('circle',))}
RESULTS = [('profiles', 'Sketch'), ('extrude', 'Extrude'), ('feature', 'Feature')]
MATERIALS = [('cells', 'Holes'), ('panel', 'Perforated Panel')]
OPERATIONS = [('join', 'Join'), ('cut', 'Cut'), ('intersect', 'Intersect'),
              ('body', 'New Body'), ('component', 'New Component')]
DIRECTIONS = [('one', 'One Side'), ('two', 'Two Sides'), ('symmetric', 'Symmetric')]
EXTENTS = [('distance', 'Distance'), ('object', 'To Object'), ('all', 'All')]
STARTS = [('profile', 'Profile Plane'), ('offset', 'Offset')]
LAYOUTS = [('staggered', 'Staggered'), ('rows', 'Rectangular'), ('circular', 'Circular'), ('path', 'Along Path')]
LAYOUTS += [('contour', 'Contour'), ('fan', 'Fan'), ('phyllotaxis', 'Phyllotaxis'),
            ('poisson', 'Poisson Disk'), ('wave', 'Wave'), ('chevron', 'Chevron'),
            ('between_curves', 'Between Curves')]
LEGACY_BOND = ('running_bond', 'Running Bond (Legacy)')
SURFACE_LAYOUTS = LAYOUTS[:2] + [(key, label) for key, label in LAYOUTS if key in ('poisson', 'wave', 'chevron')]
PATH_ORIENTATIONS = [('fixed', 'Fixed'), ('tangent', 'Tangent')]
ORIENTATIONS = [('fixed', 'Fixed'), ('radial', 'Radial'), ('tangential', 'Tangential')]
PREVIEW_MODES = [('fast', 'Fast'), ('exact', 'Full')]


def log_error():
    app = adsk.core.Application.get()
    app.log('Perfora: ' + traceback.format_exc())


class Session:
    def __init__(self, command, edited_feature=None):
        self.command = command
        self.edited_feature = edited_feature
        saved_settings = parametric.stored(edited_feature)['settings'] if edited_feature else {}
        self.distribution_revision = saved_settings.get('distribution_revision', 1) if edited_feature else 2
        self.layout_choices = LAYOUTS + ([LEGACY_BOND] if saved_settings.get('layout') == 'running_bond' else [])
        self.restore_marker = None
        self.restore_anchor = None
        self._extrude_inputs = None
        self._planar_material = None
        self._organic_trim = None
        self._auto_bodies = []
        self.initial_defaults_applied = False
        self.inputs = {}
        self.selection_memory = {}
        self.numeric_inputs = {}
        self.app = adsk.core.Application.get()
        self.preselected_sources = ([selection.entity for selection in self.app.userInterface.activeSelections]
                                    if edited_feature is None else [])
        self.units = adsk.fusion.Design.cast(self.app.activeProduct).unitsManager
        self.defaults_timer = None
        self.defaults_closed = False
        self.defaults_event_id = None
        self.handlers = []
        self.updating = False
        self.preview_error = ''
        self._status_text = None
        self.renderer = Renderer()
        self.selection_notice = ''
        self.surface_notice = ''
        self.surface_choices = SURFACE_LAYOUTS + ([LEGACY_BOND] if saved_settings.get('layout') == 'running_bond' else [])
        self.cylinder_source = None
        self.cylinder_frame = None
        self.cylinder_layout_key = None
        command.setDialogInitialSize(320, 780)
        command.okButtonText = 'OK'
        command.isRepeatable = True
        root = command.commandInputs
        self.button_row(root, 'result', 'Type', RESULTS)
        self.inputs['result'].listItems.item(2).isSelected = True
        self.selection(root, 'source', 'Profiles', ['Faces', 'Profiles', 'ConstructionPlanes'], 1, 32,
                       'Select up to 32 regions of one surface type in one component: planar, cylindrical, conical, or freeform. A construction plane is a single region.')

        self.inputs['source'].isUseCurrentSelections = False

        radial = self.group(root, 'cylinder_group', 'Boundary', expanded=False)
        self.inputs['cylinder_info'] = radial.addTextBoxCommandInput('cylinder_info', '',
            'Holes follow the local surface normal.', 1, True)
        self.inputs['cylinder_info'].isFullWidth = True
        self.number(radial, 'cylinder_start', 'Start Angle', '0 deg', 'deg')
        self.number(radial, 'cylinder_sweep', 'Sweep Angle', '360 deg', 'deg')
        self.inputs['cylinder_sweep'].tooltip = '360 deg closes the pattern without a duplicated seam. For a sector, stay within the selected face.'
        self.number(radial, 'axial_start', 'Axial Start', '0 mm')
        self.number(radial, 'axial_length', 'Axial Length', '0 mm')
        self.inputs['axial_length'].tooltip = '0 uses the remaining face height. Edge Offset applies at both ends of the zone.'
        self.inputs['source_info'] = root.addTextBoxCommandInput('source_info', '',
            'Select regions of one surface type. Planar regions share component axes and phase; '
            'curved regions follow their local surface normals.', 2, True)
        self.inputs['source_info'].isFullWidth = True
        self.inputs['source_info'].isVisible = False

        area = self.group(root, 'area_group', 'Boundary')
        self.dropdown(area, 'boundary', 'Shape', [('rectangle', 'Rectangle'), ('circle', 'Circle')])
        for identifier, (label, _) in AREA_FIELDS.items():
            self.number(area, identifier, label, '80 mm')
        self.number(area, 'height', 'Height', '60 mm')

        pattern = self.group(root, 'pattern_group', 'Pattern')
        field_options = self.group(root, 'field_options', 'Field Options', expanded=False)
        self.dropdown(pattern, 'pattern_type', 'Pattern Type', PATTERN_TYPES)
        self.inputs['pattern_type'].tooltip = 'Pattern repeats a hole shape using a Distribution. Organic Field creates flowing openings from noise or variable-size blue noise.'
        self.dropdown(pattern, 'shape', 'Hole Shape', PATTERN_SHAPES)
        self.dropdown(pattern, 'organic_shape', 'Field', FIELD_SHAPES)
        for identifier, (label, _) in SIZE_FIELDS.items():
            self.number(pattern, identifier, label, '5 mm')
        for identifier, (label, _) in LENGTH_FIELDS.items():
            self.number(pattern, identifier, label, '12 mm')
        self.number(pattern, 'arm_width', 'Arm Width', '1.5 mm')
        self.integer(pattern, 'star_points', 'Points', 3, 12, 5)
        self.number(pattern, 'star_ratio', 'Inner Radius (%)', '45', '')
        self.integer(pattern, 'irregularity', 'Irregularity (%)', 0, 100, 80)
        self.inputs['irregularity'].tooltip = ('0% creates regular square cells. Higher values create more varied '
            'Voronoi polygons while keeping the minimum Web Thickness.')
        self.integer(pattern, 'seed', 'Seed', 0, 2147483647, 1)
        self.inputs['seed'].tooltip = 'The same Seed and settings reproduce the same pattern.'
        self.inputs['new_pattern'] = pattern.addBoolValueInput('new_pattern', '', False, '', False)
        self.inputs['new_pattern'].text = 'New Pattern'
        self.inputs['new_pattern'].isFullWidth = True
        self.inputs['new_pattern'].tooltip = 'Increment Seed to explore another pattern without changing its spacing.'
        for key, (label, unit, expression) in ORGANIC_PARAMETERS.items():
            self.number(field_options if key in ('organic_variation','organic_gradient') else pattern, key, label, expression, unit)
        self.inputs['organic_open'].tooltip = ('Raw open fraction of the field (15–75%). Web Thickness, bridges, rounded tips, Edge Offset and boundary trimming reduce the final open area. Use Full Preview to inspect the actual result.')
        self.inputs['organic_direction'].tooltip = ('Field direction in sketch axes, or the local circumferential / meridian chart on curved faces. 0 deg aligns long fibers with X (around a cylinder); 90 deg aligns them with Y (along its axis).')
        self.inputs['organic_variation'].tooltip = '0 creates equal diameters; 80% permits diameters down to 20% of Maximum Diameter. Range: 0–90%.'
        self.inputs['organic_gradient'].tooltip = 'Signed size gradient along Direction. 0 varies sizes randomly; +100% grows toward +X, −100% reverses the gradient.'
        self.check(field_options,'organic_bridges','Add Bridges',False)
        self.inputs['organic_bridges'].tooltip = ('Add local cross-bridges to long organic openings. Off preserves the natural field. '
            'Material-island protection and minimum Web Thickness remain active.')
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
        self.dropdown(pattern, 'layout', 'Distribution', self.layout_choices, icons=True)
        self.dropdown(pattern, 'surface_layout', 'Distribution', self.surface_choices, icons=True)
        self.dropdown(pattern, 'layout_orientation', 'Orientation', [('tangent', 'Follow Pattern'), ('fixed', 'Fixed')])
        for key, (label, unit, expression) in VARIANT_PARAMETERS.items():
            self.number(pattern, key, label, '0.5 mm' if key == 'contour_tolerance' else expression, unit)
        self.inputs['along_spacing'].tooltip = ('Center spacing measured along each row. 0 is automatic. '
            'Spacing is raised to the enclosing hole diameter plus Web Thickness; nearby candidates may be omitted to keep the web.')
        self.inputs['row_spacing'].tooltip = 'Row spacing. 0 is automatic; the enclosing hole diameter plus Web Thickness is the minimum.'
        self.inputs['fan_angular_step'].tooltip = '0 uses Ray Count. A positive angle sets the angular step; the sector endpoint is included for an open sector.'
        self.inputs['fan_angle'].tooltip = 'Sector starting at Pattern Angle, counterclockwise. A full 360 deg sector omits the duplicate last ray.'
        self.inputs['phyllotaxis_density'].tooltip = 'Golden-angle density multiplier. Higher values add candidates; Web Thickness remains enforced.'
        self.inputs['bond_shift'].tooltip = 'Cumulative fraction of a pitch per row. Enter 1 / 3, 1 / 4, or another ratio from 0 to 1.'
        self.inputs['contour_tolerance'].tooltip = ('Resolution bound for approximate signed-distance contour rows. '
            'Smaller values cost more. Exact boundary trimming still uses Fusion geometry.')
        for key, label in (('guide1', 'Guide 1'), ('guide2', 'Guide 2')):
            self.selection(pattern, key, label, ['SketchCurves', 'Edges'], 0, 1,
                           'Select one open planar sketch curve or edge in the Profiles component. Closed, crossing and folded strips are unsupported.')
            self.inputs[key].isUseCurrentSelections = False
        self.check(pattern, 'guide_reverse', 'Reverse Guide 2', False)
        self.inputs['surface_layout'].tooltip = 'Rectangular aligns rows. Staggered shifts alternate rows by half a pitch.'
        self.selection(pattern, 'path', 'Path', ['Edges', 'SketchCurves'], 0, 1,
                       'Select one line, arc, circle, or spline in the Profiles plane and component. '
                       'Chains and off-plane curves are not supported.')
        self.inputs['path'].isUseCurrentSelections = False
        self.number(pattern, 'path_spacing', 'Path Spacing', '8 mm')
        self.inputs['path_spacing'].tooltip = ('Center spacing measured by arc length. '
            'Web Thickness is checked at turns, nearby sections, and the closing seam. '
            'Noncircular holes use conservative enclosing bounds.')
        self.number(pattern, 'path_start', 'Start Offset', '0 mm')
        self.number(pattern, 'path_end', 'End Offset', '0 mm')
        self.number(pattern, 'path_position', 'Position', '0 mm')
        self.inputs['path_position'].tooltip = ('Additional distance of the first center from Start Offset. '
            'Offsets measure hole centers, not solid end borders. A closed path uses its curve seam.')
        self.check(pattern, 'path_reverse', 'Reverse Path', False)
        self.dropdown(pattern, 'path_orientation', 'Orientation', PATH_ORIENTATIONS)
        self.inputs['path_orientation'].tooltip = ('Fixed keeps holes parallel to sketch X. '
            'Tangent follows Path in the chosen direction. Hole Angle adds a rotation.')
        self.selection(pattern, 'center_point', 'Start Point',
                       ['SketchPoints', 'Vertices', 'ConstructionPoints'], 0, 1,
                       'Select a sketch point, vertex, or construction point. Leave empty for the boundary center. '
                       'Points off the Profiles plane are projected onto it. X/Y Offset move the pattern from this point.')
        self.inputs['center_point'].isUseCurrentSelections = False
        self.number(pattern, 'spread_radius', 'Spread Radius', '0 mm')
        self.inputs['spread_radius'].tooltip = ('Limit perforation to a radius around Start Point, including X/Y Offset. '
            '0 fills the selected boundary. Edge Offset also applies to this limit; Trim to Boundary keeps partial holes.')
        self.number(pattern, 'start_radius', 'Start Radius', '0 mm')
        self.inputs['start_radius'].tooltip = ('Radius of the first ring, measured to hole centers. '
            '0 starts with a center hole. Ring spacing and holes per ring are automatic to preserve Web Thickness.')
        self.dropdown(pattern, 'orientation', 'Orientation', ORIENTATIONS)
        self.inputs['orientation'].tooltip = ('Fixed keeps all holes parallel. Radial rotates each hole with its '
            'position around the center. Tangential follows the circumference. Hole Angle adds a rotation.')

        more = self.group(root, 'more_group', 'Placement', False)
        self.number(more, 'grid_angle', 'Pattern Angle', '0 deg', 'deg')
        self.number(more, 'shape_angle', 'Hole Angle', '0 deg', 'deg')
        self.number(more, 'offset_x', 'X Offset', '0 mm')
        self.number(more, 'offset_y', 'Y Offset', '0 mm')
        self.integer(more, 'limit', 'Maximum Holes', 1, 5000, 1500)

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
        self.inputs['preview_mode'].tooltip = ('Fast displays cached contours on the selected source. Full previews the '
            'complete solid operation. OK creates the exact result.')
        self.dropdown(root, 'preview_color', 'Preview Color', PREVIEW_COLORS)
        self.inputs['preview_color'].tooltip = ('Color of Fast Preview contours. Magenta is the default. '
            'Full Preview uses the Fusion model appearance.')
        self.inputs['status'] = root.addTextBoxCommandInput('status', '', '', 2, True)
        self.inputs['status'].isFullWidth = True
        self.inputs['status'].isVisible = False
        self.connect(command.preSelect, PreSelect(self))
        self.connect(command.inputChanged, Changed(self))
        self.connect(command.validateInputs, Validate(self))
        self.connect(command.executePreview, Execute(self, True))
        self.connect(command.execute, Execute(self, False))
        self.connect(command.destroy, Destroy(self))
        if edited_feature:
            self.restore_feature()
            self.connect(command.activate, EditActivate(self))
            self.inputs['result'].isEnabled = False
            for key in ('source', 'operation', 'bodies'):
                self.inputs[key].isEnabled = False
            command.isRepeatable = False
        self.connect(command.activate, ActivateDefaults(self))
        self.connect(command.keyUp, CommitDefaults(self))
        self.defaults_event_id = COMMAND_ID + '.defaults.' + uuid4().hex
        self.connect(self.app.registerCustomEvent(self.defaults_event_id), DefaultValues(self))
        self.update_visibility()
        command.setDialogSize(320, 0)

    def restore_feature(self):
        custom = self.edited_feature
        data = parametric.stored(custom)
        settings, config = data['settings'], data['config']
        d = self.inputs
        self.updating = True
        try:
            self.set_shape(settings['shape'])
            for key, options in (('material', MATERIALS),
                                 ('operation', OPERATIONS), ('direction', DIRECTIONS),
                                 ('boundary', [('rectangle', 'Rectangle'), ('circle', 'Circle')])):
                chosen = config[key]
                d[key].listItems.item(next(i for i, (k, _) in enumerate(options) if k == chosen)).isSelected = True
            layout = settings.get('layout', 'grid')
            layout = ('staggered' if settings['staggered'] else 'rows') if layout == 'grid' else layout
            d['layout'].listItems.item(next(i for i, (key, _) in enumerate(self.layout_choices) if key == layout)).isSelected = True
            defaults = Settings()
            for key in (*VARIANT_PARAMETERS, *ORGANIC_PARAMETERS):
                d[key].value = settings.get(key, getattr(defaults, key))
            d['guide_reverse'].value = settings.get('guide_reverse', False)
            d['organic_bridges'].value = settings.get('organic_bridges',False)
            if surface.supported(self.selected_source()): self.sync_surface_layouts(self.selected_source())
            choices = getattr(self, 'surface_choices', SURFACE_LAYOUTS)
            if layout in dict(choices):
                d['surface_layout'].listItems.item(next(i for i, item in enumerate(choices) if item[0] == layout)).isSelected = True
            d['layout_orientation'].listItems.item(0 if settings.get('layout_orientation', 'fixed') == 'tangent' else 1).isSelected = True
            d['path_orientation'].listItems.item(1 if settings.get('path_orientation') == 'tangent' else 0).isSelected = True
            d['path_reverse'].value = settings.get('path_reverse', False)
            for key, fallback in (('path_spacing', .8), ('path_start', 0), ('path_end', 0), ('path_position', 0)):
                d[key].value = settings.get(key, fallback)
            d['orientation'].listItems.item(2 if settings.get('tangential_orientation') else
                (1 if settings.get('radial_orientation') else 0)).isSelected = True
            d['start_radius'].value = settings.get('start_radius', 0)
            d['spread_radius'].value = settings.get('spread_radius', 0)
            for key in ('clip_boundary',):
                d[key].value = settings[key]
            d['reverse'].value = config['reverse']
            for key in ('star_points', 'seed', 'limit'):
                d[key].value = int(custom.parameters.itemById(key).value)
            d['irregularity'].value = round(custom.parameters.itemById('irregularity').value * 100)
            d['round_corners'].value = custom.parameters.itemById('corner_radius').value > 0
            for key in parametric.parameters(config):
                if key in self.numeric_inputs and key not in ('star_points', 'seed', 'limit', 'irregularity'):
                    parameter = custom.parameters.itemById(key)
                    if parameter:
                        d[key].expression = parameter.expression
            d['star_ratio'].expression = '(' + custom.parameters.itemById('star_ratio').expression + ') * 100'
            for key in SIZE_FIELDS:
                d[key].expression = custom.parameters.itemById('size').expression
            for key in LENGTH_FIELDS:
                d[key].expression = custom.parameters.itemById('slot_length').expression
            for key in AREA_FIELDS:
                d[key].expression = custom.parameters.itemById('width').expression
            d['start_mode'].listItems.item(1 if abs(custom.parameters.itemById('start').value) > 1e-12 else 0).isSelected = True
        finally:
            self.updating = False

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
        evaluator = parent.addValueInput('_numeric_' + identifier, title, unit, model.value(expression))
        evaluator.isVisible = False
        control = parent.addStringValueInput(identifier, title, expression)
        self.inputs[identifier] = self.numeric_inputs[identifier] = NumericInput(control, evaluator, self, expression, unit)

    def integer(self, parent, identifier, title, minimum, maximum, default):
        self.number(parent, identifier, title, str(default), '')
        self.inputs[identifier].integer_bounds = (minimum, maximum)

    def schedule_defaults(self):
        if self.defaults_timer:
            self.defaults_timer.cancel()
        self.defaults_timer = Timer(1.0, self.post_defaults)
        self.defaults_timer.daemon = True
        self.defaults_timer.start()

    def post_defaults(self):
        # Only enqueue an event from the worker; all UI/CAD access stays on
        # Fusion's main thread. A cancelled command cannot retain a callback.
        event_id = self.defaults_event_id
        if event_id and not self.defaults_closed:
            try:
                self.app.fireCustomEvent(event_id)
            except RuntimeError:
                pass  # The command may have unregistered the event meanwhile.

    def restore_empty_inputs(self, exclude=None):
        if self.defaults_closed:
            return []
        restored = []
        previous = self.updating
        self.updating = True
        try:
            for identifier, control in self.numeric_inputs.items():
                if identifier != exclude and not control.expression.strip():
                    control.expression = control.default_expression
                    control.isValueError = False
                    restored.append(identifier)
        finally:
            self.updating = previous
        for identifier in restored:
            self.sync_dimensions(identifier)
        if any(k in restored for k in ('width', 'area_diameter', 'height')):
            self.renderer.reset()
        return restored

    def close_defaults(self):
        self.defaults_closed = True
        if self.defaults_timer:
            self.defaults_timer.cancel()
            self.defaults_timer = None
        if self.defaults_event_id:
            self.app.unregisterCustomEvent(self.defaults_event_id)
            self.defaults_event_id = None

    def check(self, parent, identifier, title, default, icon=''):
        resource = ui_resources.icon(icon)
        self.inputs[identifier] = parent.addBoolValueInput(identifier, title, not bool(resource), resource, default)

    def dimension_id(self, fields, shape):
        return next((identifier for identifier, (_, shapes) in fields.items() if shape in shapes), None)

    def sync_dimensions(self, identifier):
        for fields in (SIZE_FIELDS, LENGTH_FIELDS, AREA_FIELDS):
            if identifier not in fields:
                continue
            previous = self.updating
            self.updating = True
            try:
                expression = self.inputs[identifier].expression
                for linked in fields:
                    if linked != identifier and self.inputs[linked].expression != expression:
                        self.inputs[linked].expression = expression
            finally:
                self.updating = previous

    def selection(self, parent, identifier, title, filters, minimum, maximum, tooltip=''):
        control = parent.addSelectionInput(identifier, title, tooltip or title)
        for name in filters:
            control.addSelectionFilter(name)
        control.setSelectionLimits(minimum, maximum)
        self.inputs[identifier] = control

    def chosen(self, identifier, options):
        return options[self.inputs[identifier].selectedItem.index][0]

    def shape_key(self):
        if self.chosen('pattern_type', PATTERN_TYPES) == 'organic':
            return self.chosen('organic_shape', FIELD_SHAPES)
        return self.chosen('shape', PATTERN_SHAPES)

    def set_shape(self, key):
        """Restore either family without losing the other family's selection."""
        previous = self.updating
        self.updating = True
        try:
            organic = key in ORGANIC_SHAPES
            self.inputs['pattern_type'].listItems.item(1 if organic else 0).isSelected = True
            options = FIELD_SHAPES if organic else PATTERN_SHAPES
            self.inputs['organic_shape' if organic else 'shape'].listItems.item(
                next(i for i, (value, _) in enumerate(options) if value == key)).isSelected = True
        finally:
            self.updating = previous

    def field_threshold(self, shape):
        if self.edited_feature:
            parameter = self.edited_feature.parameters.itemById('organic_open')
            if parameter:
                return parameter.value
            return parametric.stored(self.edited_feature)['settings'].get('organic_open', 48.)
        return DEFAULT_OPEN.get(shape, 48.)

    def restore_timeline(self):
        if self.restore_anchor is not None:
            self.restore_anchor.rollTo(False)
        elif self.restore_marker is not None:
            self.edited_feature.parentComponent.parentDesign.timeline.markerPosition = self.restore_marker

    def field_defaults(self):
        if self.edited_feature or getattr(self, '_field_defaults_applied', False):
            return
        self.updating = True
        try:
            self.inputs['organic_scale'].value = DEFAULT_CELL_SIZE
            self.sync_dimensions('organic_scale')
            self.inputs['gap'].value = DEFAULT_WEB
            self.inputs['organic_variation'].value = 35
            self.inputs['organic_gradient'].value = 0
            self._field_defaults_applied = True
        finally:
            self.updating = False

    def selected_source(self):
        selection = self.inputs['source']
        return model.native(selection.selection(0).entity) if selection.selectionCount else None

    def selected_sources(self):
        selection = self.inputs['source']
        return multi_region.sources([selection.selection(i).entity for i in range(selection.selectionCount)])

    def status(self, message):
        if message != self._status_text:
            self._status_text = message
            self.inputs['status'].formattedText = html.escape(message).replace('\n', '<br>')
            self.inputs['status'].isVisible = bool(message)

    def capture_surface(self,source):
        if self.cylinder_source!=source or self.cylinder_frame is None:
            self.cylinder_frame=surface.Chart(source)
            self.cylinder_source=source
            if not self.edited_feature and self.cylinder_frame.kind!='freeform':
                previous=self.updating;self.updating=True
                try:
                    # Display precision must never enlarge a trimmed sector.
                    self.inputs['cylinder_sweep'].expression=format(math.degrees(self.cylinder_frame.sweep),'.12g')+' deg'
                    self.inputs['cylinder_start'].expression='0 deg'
                    self.inputs['axial_start'].expression='0 mm'
                    self.inputs['axial_length'].expression='0 mm'
                finally:self.updating=previous
        return self.cylinder_frame

    def apply_preselected_sources(self):
        """Import the first compatible set; Fusion can bypass preSelect for API preselection."""
        accepted = []
        skipped = False
        previous = self.updating
        self.updating = True
        try:
            for entity in self.preselected_sources:
                if not isinstance(entity, (adsk.fusion.BRepFace, adsk.fusion.Profile, adsk.fusion.ConstructionPlane)):
                    continue
                try:
                    multi_region.sources(accepted + [entity])
                    if self.inputs['source'].addSelection(entity):
                        accepted.append(entity)
                    else:
                        skipped = True
                except (ValueError, RuntimeError):
                    skipped = True
            self.preselected_sources = []
            if skipped:
                self.selection_notice = 'Incompatible Profiles were skipped. Select one surface type.'
        finally:
            self.updating = previous
        self.update_visibility()

    def legacy_spread_radius(self):
        """The removed control cannot validate or overwrite a saved parameter."""
        if self.edited_feature is None:
            return 0.
        parameter = self.edited_feature.parameters.itemById('spread_radius')
        return (parameter.value if parameter else
                parametric.stored(self.edited_feature)['settings'].get('spread_radius', 0.))

    def sync_surface_layouts(self, source):
        kind = ('cylinder' if isinstance(source.geometry, adsk.core.Cylinder) else
                'cone' if isinstance(source.geometry, adsk.core.Cone) else 'freeform')
        allowed = surface.sg.SURFACE_DISTRIBUTIONS[kind]
        choices = [item for item in SURFACE_LAYOUTS + ([LEGACY_BOND] if LEGACY_BOND in self.layout_choices else []) if item[0] in ('staggered', 'rows') or item[0] in allowed]
        previous = getattr(self, 'surface_choices', SURFACE_LAYOUTS)
        if choices != previous:
            key = self.chosen('surface_layout', previous)
            items = self.inputs['surface_layout'].listItems
            items.clear()
            if key not in dict(choices):
                key = 'staggered'
                self.surface_notice = 'Distribution changed to Staggered. Choose a compatible pattern.'
            for value, label in choices:
                items.add(label, value == key, '')
            self.surface_choices = choices
        self.inputs['surface_layout'].tooltip = ('Distributions suited to this surface. '
            'Centered motifs and planar guide layouts require planar Profiles.')

    def update_visibility(self):
        if self.updating:
            return
        self.updating = True
        try:
            d = self.inputs
            source = self.selected_source()
            is_curved = surface.is_curved(source)
            if not is_curved: self.surface_notice = ''
            if surface.supported(source):
                self.capture_surface(source)
                self.sync_surface_layouts(source)
            multiple = d['source'].selectionCount > 1
            is_plane = isinstance(source, adsk.fusion.ConstructionPlane)
            def visible(identifier, enabled):
                if d[identifier].isVisible != enabled:
                    remembered = identifier in ('path', 'guide1', 'guide2', 'center_point')
                    if remembered:
                        if not hasattr(self, 'selection_memory'): self.selection_memory = {}
                        if not enabled:
                            self.selection_memory[identifier] = tuple(d[identifier].selection(i).entity
                                for i in range(d[identifier].selectionCount))
                    d[identifier].isVisible = enabled
                    if remembered and enabled and not d[identifier].selectionCount:
                        for entity in self.selection_memory.get(identifier, ()):
                            if getattr(entity, 'isValid', False): d[identifier].addSelection(entity)
            visible('area_group', is_plane)
            visible('cylinder_group', is_curved)
            for identifier in surface.ZONE_PARAMETERS:
                visible(identifier, is_curved and isinstance(source.geometry,(adsk.core.Cylinder,adsk.core.Cone)))
            visible('result', True)
            visible('material', True)
            d['material'].isEnabled = not is_curved
            if is_curved:
                if self._planar_material is None:
                    self._planar_material=d['material'].selectedItem.index
                d['material'].listItems.item(0).isSelected = True
            elif self._planar_material is not None:
                d['material'].listItems.item(self._planar_material).isSelected = True
                self._planar_material=None
            d['material'].tooltip = ('Curved faces support Holes. Perforated Panel requires planar Profiles.' if is_curved else
                'Holes creates the hole profiles. Perforated Panel creates the surrounding material. '
                'Use Perforated Panel with New Body for a separate grille.')
            d['result'].tooltip = ('Sketch creates fixed 3D surface contours. Feature regenerates the pattern.' if is_curved else
                'Sketch creates profiles. Extrude creates a fixed pattern. Feature regenerates the pattern.')
            notice = getattr(self, 'surface_notice', '') or getattr(self, 'selection_notice', '')
            d['source_info'].formattedText = notice or ('Planar regions share component axes and phase.' if not is_curved else
                'Local surface normals. Maximum Holes is shared by all regions.')
            visible('source_info', multiple or bool(notice))
            boundary = self.chosen('boundary', [('rectangle', ''), ('circle', '')])
            for identifier, (_, shapes) in AREA_FIELDS.items():
                visible(identifier, boundary in shapes)
            visible('height', boundary == 'rectangle')
            shape = self.shape_key()
            visible('shape', shape not in ORGANIC_SHAPES)
            visible('organic_shape', shape in ORGANIC_SHAPES)
            for fields in (SIZE_FIELDS, LENGTH_FIELDS):
                for identifier, (_, shapes) in fields.items():
                    visible(identifier, shape in shapes)
            size_id = self.dimension_id(SIZE_FIELDS, shape)
            self.inputs[size_id].tooltip = SIZE_HELP[shape]
            visible('arm_width', shape == 'cross')
            visible('star_points', shape == 'star')
            visible('star_ratio', shape == 'star')
            organic = shape in ORGANIC_SHAPES
            if self.edited_feature is None:
                if organic and getattr(self,'_organic_trim',None) is None:
                    self._organic_trim=d['clip_boundary'].value
                    d['clip_boundary'].value=True
                elif not organic and getattr(self,'_organic_trim',None) is not None:
                    d['clip_boundary'].value=self._organic_trim
                    self._organic_trim=None
            field_shape = organic or shape == 'voronoi'
            layout = (self.chosen('surface_layout', self.surface_choices) if is_curved else self.chosen('layout', self.layout_choices)) if not field_shape else 'grid'
            for identifier in ('irregularity', 'round_corners'):
                visible(identifier, shape == 'voronoi')
            for identifier in ('seed', 'new_pattern'):
                visible(identifier, field_shape or layout == 'poisson')
            for key in ORGANIC_PARAMETERS:
                visible(key, organic and (key == 'organic_direction' or
                    (key in ('organic_variation', 'organic_gradient') and shape == 'blue_noise')))
            visible('organic_open',False)
            visible('field_options',organic)
            visible('organic_bridges',shape in ORGANIC_FIELDS)
            for key in VARIANT_PARAMETERS:
                visible(key, key in LAYOUT_PARAMETERS.get(layout, ()))
            if layout == 'fan':
                visible('fan_rays', not d['fan_angular_step'].isValidExpression or d['fan_angular_step'].value == 0)
            for key in ('guide1', 'guide2', 'guide_reverse'):
                visible(key, layout == 'between_curves')
            visible('corner_radius', shape == 'voronoi' and d['round_corners'].value)
            visible('layout', not field_shape and not is_curved)
            visible('surface_layout', not field_shape and is_curved)
            circular = layout == 'circular'
            along_path = layout == 'path'
            for identifier in ('path', 'path_spacing', 'path_start', 'path_end', 'path_position', 'path_reverse'):
                visible(identifier, along_path)
            visible('path_orientation', along_path and shape != 'circle')
            boundary_anchored = layout in ('contour', 'between_curves')
            scoped = self.legacy_spread_radius() > 0
            visible('center_point', not along_path and (not boundary_anchored or scoped))
            visible('grid_angle', not organic and not is_curved and not along_path and not boundary_anchored)
            for key in ('offset_x', 'offset_y'):
                visible(key, not along_path and (not boundary_anchored or scoped))
            visible('start_radius', circular or layout == 'fan')
            d['start_radius'].tooltip = ('Common inner radius of the rays. It may increase coherently to preserve Web Thickness.'
                if layout == 'fan' else 'Radius of the first ring, measured to hole centers. 0 starts with a center hole; ring spacing preserves Web Thickness.')
            visible('orientation', circular and shape != 'circle')
            visible('layout_orientation', self.distribution_revision == 2 and layout in LAYOUT_PARAMETERS and layout not in ('poisson', 'running_bond') and shape != 'circle' and not field_shape)
            visible('clip_boundary', True)
            visible('spread_radius',False)
            d['spread_radius'].tooltip = ('Limit the surface to the 3D distance from Start Point, including X/Y Offset. '
                '0 fills the selected boundary. Edge Offset also applies to this limit.' if is_curved else
                'Limit perforation to a radius around Start Point, including X/Y Offset. 0 fills the selected boundary. '
                'Edge Offset also applies to this limit; Trim to Boundary keeps partial holes.')
            for identifier, axis in (('offset_x', 'X'), ('offset_y', 'Y')):
                d[identifier].tooltip = (('Circumferential' if axis=='X' else 'Meridian / axial')+' pattern phase from Start Point or the automatic origin.' if is_curved else axis + ' offset from Start Point, or the boundary center when no point is selected, in sketch axes.'
                    if circular else axis + ' offset from Start Point, or the automatic center, in pattern axes. Without a spread limit, offsets are periodic.')
            visible('shape_angle', shape not in ('circle', 'voronoi') and not organic)
            is_feature = self.chosen('result', RESULTS) == 'feature'
            is_extrude = self.chosen('result', RESULTS) in ('extrude', 'feature')
            if (is_feature or is_curved) and self._extrude_inputs is None:
                self._extrude_inputs = {side: (d['extent' + side].selectedItem.index,
                    d['taper' + side].expression) for side in ('1', '2')}
                for side in ('1', '2'):
                    d['extent' + side].listItems.item(0).isSelected = True
                    d['taper' + side].expression = '0 deg'
            elif not is_feature and not is_curved and self._extrude_inputs is not None:
                for side, (extent, taper) in self._extrude_inputs.items():
                    d['extent' + side].listItems.item(extent).isSelected = True
                    d['taper' + side].expression = taper
                self._extrude_inputs = None
            direction = self.chosen('direction', DIRECTIONS)
            visible('output_group', is_extrude)
            visible('start', is_extrude and self.chosen('start_mode', STARTS) == 'offset')
            visible('side2', is_extrude and direction == 'two')
            visible('reverse', is_extrude and direction == 'one')
            d['distance1'].tooltip = ('Full length of the symmetric local tools.' if is_curved and direction=='symmetric' else
                'Bounded distance along each local surface normal. Check wall penetration in Full Preview.' if is_curved else
                'Full length of the symmetric extrusion.' if direction=='symmetric' else 'Extrusion distance for Side 1.')
            for side in ('1', '2'):
                kind = self.chosen('extent' + side, EXTENTS)
                symmetric = direction == 'symmetric' and side == '1'
                side_visible = is_extrude and (side == '1' or direction == 'two')
                visible('extent' + side, side_visible and not symmetric and not is_feature and not is_curved)
                visible('taper' + side, side_visible and not is_feature and not is_curved)
                visible('distance' + side, side_visible and (symmetric or kind == 'distance'))
                visible('target' + side, side_visible and not symmetric and kind == 'object')
                visible('object_offset' + side, side_visible and not symmetric and kind == 'object')
            uses_bodies = is_extrude and (self.chosen('operation', OPERATIONS) in ('cut', 'intersect')
                                       or ((is_feature or is_curved) and self.chosen('operation', OPERATIONS) == 'join'))
            visible('bodies', uses_bodies)
            visible('preview_mode', d['preview'].value)
            visible('preview_color', d['preview'].value and self.chosen('preview_mode', PREVIEW_MODES) == 'fast')
            if uses_bodies and source is not None and (multiple or self._auto_bodies or not d['bodies'].selectionCount):
                # Profiles on a solid face use that face's body too. Preserve
                # the visible assembly proxy expected by the selection API.
                supports = []
                for i in range(d['source'].selectionCount):
                    body = model.source_support_body(d['source'].selection(i).entity)
                    if body is not None and not any(model.native(body) == model.native(b) for b in supports):
                        supports.append(body)
                current = [d['bodies'].selection(i).entity for i in range(d['bodies'].selectionCount)]
                retained = [b for b in current if not any(model.native(b) == model.native(a) for a in self._auto_bodies)
                            or any(model.native(b) == model.native(s) for s in supports)]
                wanted = retained + [s for s in supports if not any(model.native(s) == model.native(b) for b in retained)]
                if wanted != current and not self.edited_feature:
                    d['bodies'].clearSelection()
                    for body in wanted:
                        d['bodies'].addSelection(body)
                self._auto_bodies = supports
        finally:
            self.updating = False

    def read(self):
        d = self.inputs
        source = self.selected_source()
        if not source:
            raise ValueError('Select a profile, planar face, or construction plane.')
        is_curved = surface.is_curved(source)
        if is_curved and not surface.supported(source):
            raise ValueError('Spheres and tori are not supported. Select another face.')
        if surface.supported(source):self.capture_surface(source)
        selected = self.selected_sources()
        # Hidden optional inputs must not block a different mode after an edit.
        shape = self.shape_key()
        organic = shape in ORGANIC_SHAPES
        size_id = self.dimension_id(SIZE_FIELDS, shape)
        length_id = self.dimension_id(LENGTH_FIELDS, shape)
        required = [size_id, 'gap', 'margin', 'offset_x', 'offset_y', 'limit']
        if not is_curved and not organic: required.append('grid_angle')
        if is_curved and isinstance(source.geometry,(adsk.core.Cylinder,adsk.core.Cone)):
            required += list(surface.ZONE_PARAMETERS)
        layout = (self.chosen('surface_layout', self.surface_choices) if is_curved else self.chosen('layout', self.layout_choices)) if shape != 'voronoi' and not organic else 'grid'
        organic_keys = [key for key in ORGANIC_PARAMETERS if d[key].isVisible]
        if organic: required += organic_keys + ['seed']
        circular = layout == 'circular'
        variant_keys = [key for key in LAYOUT_PARAMETERS.get(layout, ()) if d[key].isVisible]
        required += variant_keys
        if layout in ('contour', 'between_curves'):
            if 'grid_angle' in required: required.remove('grid_angle')
            if self.legacy_spread_radius() == 0:
                required.remove('offset_x')
                required.remove('offset_y')
        along_path = layout == 'path'
        if along_path:
            required = [k for k in required if k not in ('grid_angle', 'offset_x', 'offset_y', 'spread_radius')]
            required += ['path_spacing', 'path_start', 'path_end', 'path_position']
            if d['path'].selectionCount != 1:
                raise ValueError('Select one Path in the Profiles plane.')
            model.path_entity(d['path'].selection(0).entity, model.source_component(source))
        if circular or layout == 'fan':
            required.append('start_radius')
        if shape not in ('circle', 'voronoi') and not organic:
            required.append('shape_angle')
        if shape in LENGTH_SHAPES:
            required.append(length_id)
        if shape == 'cross':
            required.append('arm_width')
        if shape == 'star':
            required += ['star_ratio', 'star_points']
        if shape == 'voronoi':
            required += ['irregularity', 'seed']
        if shape == 'voronoi' and d['round_corners'].value:
            required.append('corner_radius')
        boundary = self.chosen('boundary', [('rectangle', ''), ('circle', '')])
        width_id = self.dimension_id(AREA_FIELDS, boundary)
        if isinstance(source, adsk.fusion.ConstructionPlane):
            required += [width_id] + (['height'] if boundary == 'rectangle' else [])
        result, direction = self.chosen('result', RESULTS), self.chosen('direction', DIRECTIONS)
        if result in ('extrude', 'feature'):
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
        for identifier, control in self.numeric_inputs.items():
            control.isValueError = identifier in required and bool(control.expression.strip()) and not control.isValidExpression
        for identifier in required:
            if not d[identifier].isValidExpression:
                raise ValueError('Check the value of ' + d[identifier].name + '.')
        if shape == 'voronoi' and d['round_corners'].value and d['corner_radius'].value <= 0:
            raise ValueError('Corner Radius must be positive. Clear Round Corners for sharp corners.')
        variant_values = {key: d[key].value for key in variant_keys if key in VARIANT_PARAMETERS}
        for key in ('fan_rays', 'guide_rows'):
            if key in variant_values:
                if variant_values[key] != int(variant_values[key]):
                    raise ValueError(VARIANT_PARAMETERS[key][0] + ' must be an integer.')
                variant_values[key] = int(variant_values[key])
        settings = Settings(shape=shape, size=d[size_id].value,
                            slot_length=d[length_id].value if length_id else d[size_id].value,
                            gap=d['gap'].value, margin=d['margin'].value,
                            staggered=shape != 'voronoi' and layout == 'staggered',
                            grid_angle=d['grid_angle'].value if 'grid_angle' in required else 0,
                            shape_angle=d['shape_angle'].value if shape not in ('circle', 'voronoi') and not organic else 0,
                            offset_x=d['offset_x'].value if 'offset_x' in required else 0,
                            offset_y=d['offset_y'].value if 'offset_y' in required else 0, limit=d['limit'].value,
                            clip_boundary=d['clip_boundary'].value,
                            arm_width=d['arm_width'].value if shape == 'cross' else 0.15,
                            star_ratio=d['star_ratio'].value / 100 if shape == 'star' else 0.45,
                            star_points=d['star_points'].value if shape == 'star' else 5,
                            irregularity=d['irregularity'].value / 100 if shape == 'voronoi' else 0.8,
                            seed=d['seed'].value if shape == 'voronoi' or organic or layout == 'poisson' else 1,
                            corner_radius=d['corner_radius'].value
                                if shape == 'voronoi' and d['round_corners'].value else 0,
                            layout='grid' if layout in ('staggered', 'rows') else layout,
                            start_radius=d['start_radius'].value if circular or layout == 'fan' else 0,
                            spread_radius=self.legacy_spread_radius() if not along_path else 0,
                            path_spacing=d['path_spacing'].value if along_path else .8,
                            path_start=d['path_start'].value if along_path else 0,
                            path_end=d['path_end'].value if along_path else 0,
                            path_position=d['path_position'].value if along_path else 0,
                            path_reverse=along_path and d['path_reverse'].value,
                            path_orientation=self.chosen('path_orientation', PATH_ORIENTATIONS)
                                if along_path and shape != 'circle' else 'fixed',
                            radial_orientation=circular and shape != 'circle' and
                                self.chosen('orientation', ORIENTATIONS) == 'radial',
                            tangential_orientation=circular and shape != 'circle' and
                                self.chosen('orientation', ORIENTATIONS) == 'tangential',
                            distribution_revision=self.distribution_revision,
                            layout_orientation=self.chosen('layout_orientation', [('tangent', ''), ('fixed', '')]) if self.distribution_revision == 2 else 'fixed',
                            guide_reverse=d['guide_reverse'].value if layout == 'between_curves' else False,
                            organic_open=self.field_threshold(shape),
                            organic_bridges=d['organic_bridges'].value if shape in ORGANIC_FIELDS else False,
                            **variant_values, **{key:d[key].value for key in organic_keys})
        settings.validate()
        if self.edited_feature:
            parametric.validate_path_parameters(self.edited_feature, settings)
        config = {
            'guide1': None, 'guide2': None,
            'center_point': d['center_point'].selection(0).entity
                if d['center_point'].isVisible and d['center_point'].selectionCount else None,
            'path': d['path'].selection(0).entity if along_path else None,
            'boundary': boundary,
            'width': d[width_id].value if width_id in required else
                self.units.evaluateExpression(d[width_id].default_expression, d[width_id].unit),
            'height': d['height'].value if 'height' in required else
                self.units.evaluateExpression(d['height'].default_expression, d['height'].unit),
            'result': result, 'material': self.chosen('material', MATERIALS),
            'operation': self.chosen('operation', OPERATIONS), 'direction': direction,
            'reverse': d['reverse'].value,
            'start': d['start'].model_expression if self.chosen('start_mode', STARTS) == 'offset' else '0 mm',
            'bodies': [d['bodies'].selection(i).entity for i in range(d['bodies'].selectionCount)],
        }
        if config['center_point'] is not None:
            model.point_position(config['center_point'], model.source_component(source))
        if layout == 'between_curves':
            for key in ('guide1', 'guide2'):
                if not d[key].selectionCount:
                    raise ValueError('Select two open planar guides for Between Curves.')
                config[key] = d[key].selection(0).entity
                model.guide_reference(config[key], model.source_component(source))
        for side in ('1', '2'):
            for key in ('distance', 'taper', 'object_offset'):
                config[key + side] = d[key + side].model_expression
            config['extent' + side] = self.chosen('extent' + side, EXTENTS)
            control = d['target' + side]
            config['target' + side] = control.selection(0).entity if control.selectionCount else None
        if result in ('extrude', 'feature') and (config['operation'] in ('cut', 'intersect')
                or ((result == 'feature' or is_curved) and config['operation'] == 'join')):
            if not config['bodies']:
                raise ValueError('Select Objects for Cut or Intersect.')
            component = model.source_component(source)
            if any(model.native(body).parentComponent != component for body in config['bodies']):
                raise ValueError('Profiles and Objects must belong to the same component.')
        for side in (('1', '2') if direction == 'two' else ('1',)):
            if result in ('extrude', 'feature') and abs(d['taper' + side].value) >= math.pi / 2:
                raise ValueError('Taper Angle must be between -90 deg and 90 deg.')
        if is_curved:
            config['surface'] = True
            if isinstance(source.geometry,(adsk.core.Cylinder,adsk.core.Cone)):
                config.update({k:d[k].value for k in surface.ZONE_PARAMETERS})
            config = surface.normalized(config, model.source_component(source))
            if self.cylinder_source != source or self.cylinder_frame is None:
                self.cylinder_frame = surface.Chart(source)
                self.cylinder_source = source
            surface.validate(source,settings,config,self.cylinder_frame)
        if result == 'feature':
            parametric.validate(config)
            expressions = {k: d[k].model_expression for k in parametric.parameters(config)
                           if k in self.numeric_inputs and k not in ('star_points', 'seed', 'limit', 'irregularity','spread_radius')
                           and (k not in surface.ZONE_PARAMETERS or isinstance(source.geometry,(adsk.core.Cylinder,adsk.core.Cone)))}
            for key in VARIANT_PARAMETERS:
                if key not in variant_keys:
                    expressions.pop(key, None)
            for key in ORGANIC_PARAMETERS:
                if key not in organic_keys:
                    saved = self.edited_feature.parameters.itemById(key) if self.edited_feature else None
                    if saved:
                        expressions[key] = saved.expression
                        continue
                    expressions[key] = str(getattr(settings, key)) + (' rad' if key == 'organic_direction' else '')
            for key in ('grid_angle', 'offset_x', 'offset_y', 'start_radius'):
                if key not in required:
                    expressions.pop(key, None)
            expressions.update(size=d[size_id].model_expression,
                               slot_length=d[length_id].model_expression if length_id else d[size_id].model_expression,
                               width=d[width_id].model_expression,
                               start=config['start'])
            if shape == 'star':
                expressions['star_ratio'] = '(' + d['star_ratio'].expression + ') / 100'
            else:
                expressions['star_ratio'] = '0.45'
            if shape != 'cross':
                expressions['arm_width'] = '1.5 mm'
            if shape != 'voronoi' or not d['round_corners'].value:
                expressions['corner_radius'] = '0 mm'
            # Hidden stale/invalid fields cannot re-enter through model parameters.
            for key in ('grid_angle', 'offset_x', 'offset_y', 'spread_radius', 'start_radius', 'path_spacing',
                        'path_start', 'path_end', 'path_position'):
                if key not in required:
                    expressions[key] = str(getattr(settings, key)) + (' rad' if key == 'grid_angle' else ' cm')
            if self.edited_feature is not None and not along_path:
                parameter = self.edited_feature.parameters.itemById('spread_radius')
                if parameter: expressions['spread_radius'] = parameter.expression
            if is_curved:expressions['grid_angle']='0 deg'
            config['_expressions'] = expressions
        if len(selected) > 1:
            raw = [d['source'].selection(i).entity for i in range(d['source'].selectionCount)]
            # Edit preserves the original mapping even if a support changes topology.
            if self.edited_feature:
                original = parametric.stored(self.edited_feature)['config']
                for key in ('_source_count', '_body_map'):
                    if key in original:
                        config[key] = original[key]
            multi_region.validate(raw, config)
        return selected if len(selected) > 1 else source, settings, config


class PreSelect(adsk.core.SelectionEventHandler):
    def __init__(self, session):
        super().__init__()
        self.session = session

    def notify(self, args):
        try:
            active = args.firingEvent.activeInput
            if active.id != 'source': return
            selected = self.session.inputs['source']
            candidate = args.selection.entity
            if selected.selectionCount:
                multi_region.sources([selected.selection(i).entity for i in range(selected.selectionCount)] + [candidate])
            else:
                multi_region.sources([candidate])
        except Exception:
            args.isSelectable = False


class Changed(adsk.core.InputChangedEventHandler):
    def __init__(self, session):
        super().__init__()
        self.session = session

    def notify(self, args):
        if self.session.updating or args.input.id == 'status' or args.input.id.startswith('_numeric_'):
            return
        # Folding sections changes presentation, not perforation parameters.
        if isinstance(args.input, adsk.core.GroupCommandInput):
            return
        try:
            if args.input.id in ('pattern_type','organic_shape') and self.session.shape_key() in ORGANIC_SHAPES:
                self.session.field_defaults()
            self.session.restore_empty_inputs(exclude=args.input.id)
            control = self.session.numeric_inputs.get(args.input.id)
            if control and not control.expression.strip():
                self.session.schedule_defaults()
                return  # Let Select All -> type replace a value without interruption.
            if args.input.id == 'new_pattern':
                self.session.updating = True
                try:
                    d = self.session.inputs
                    d['seed'].value = (d['seed'].value + 1) % 2147483648
                    d['new_pattern'].value = False
                finally:
                    self.session.updating = False
            if args.input.id in ('layout', 'surface_layout'):
                self.session.surface_notice = ''
            self.session.sync_dimensions(args.input.id)
            if args.input.id in ('source', 'boundary', 'width', 'area_diameter', 'height'):
                self.session.renderer.reset()
            if args.input.id == 'source':
                self.session.selection_notice = ''
                self.session.cylinder_source = self.session.cylinder_frame = None
                self.session.cylinder_layout_key = None
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
        if self.session.updating:
            return
        try:
            self.session.read()
            args.areInputsValid = True
        except Exception as error:
            args.areInputsValid = False
            self.session.status(str(error))


class DefaultValues(adsk.core.CustomEventHandler):
    def __init__(self, session):
        super().__init__()
        self.session = session

    def notify(self, args):
        if self.session.defaults_closed:
            return
        try:
            if self.session.restore_empty_inputs():
                self.session.command.doExecutePreview()
        except Exception:
            log_error()


class ActivateDefaults(adsk.core.CommandEventHandler):
    def __init__(self, session):
        super().__init__()
        self.session = session

    def notify(self, args):
        # Fusion restores remembered command values after commandCreated.
        # Apply the requested default once, without resetting later user edits.
        if not self.session.initial_defaults_applied:
            self.session.initial_defaults_applied = True
            self.session.inputs['result'].listItems.item(2).isSelected = True
            self.session.inputs['preview_color'].listItems.item(0).isSelected = True
            if self.session.shape_key() in ORGANIC_SHAPES:
                self.session.field_defaults()
            self.session.apply_preselected_sources()
        self.session.restore_empty_inputs()


class CommitDefaults(adsk.core.KeyboardEventHandler):
    def __init__(self, session):
        super().__init__()
        self.session = session

    def notify(self, args):
        if args.keyCode in (adsk.core.KeyCodes.TabKeyCode, adsk.core.KeyCodes.ReturnKeyCode,
                            adsk.core.KeyCodes.EnterKeyCode):
            try:
                if self.session.restore_empty_inputs():
                    self.session.command.doExecutePreview()
            except Exception:
                log_error()


class Execute(adsk.core.CommandEventHandler):
    def __init__(self, session, preview):
        super().__init__()
        self.session = session
        self.preview = preview

    def notify(self, args):
        if not self.preview:
            self.session.restore_empty_inputs()
        if self.preview:
            args.isValidResult = False
            if not self.session.inputs['preview'].value:
                self.session.renderer.clear()
                return
        try:
            source, settings, config = self.session.read()
            if self.preview and self.session.chosen('preview_mode', PREVIEW_MODES) == 'fast':
                count = self.session.renderer.show(source, settings, config,
                    color=self.session.chosen('preview_color', PREVIEW_COLORS))
                self.session.status('%d holes. Fast preview.' % count)
                return
            self.session.renderer.clear()
            if self.preview and self.session.edited_feature:
                count = self.session.renderer.show_edit_solid(self.session.edited_feature,
                    source, settings, config)
                self.session.status('%d holes. Full preview.' % count)
                return
            if self.session.edited_feature:
                count = parametric.update(self.session.edited_feature, settings, config, cache=self.session.renderer.geometry_cache)
                feature = self.session.edited_feature
                if self.session.restore_marker is not None:
                    self.session.restore_timeline()
            elif config['result'] == 'feature':
                sketch, feature, count = parametric.build(source, settings, config, cache=self.session.renderer.geometry_cache)
            else:
                sketch, feature, count = model.build(source, settings, config, cache=self.session.renderer.geometry_cache)
            message = '%d holes. %s' % (count, 'Radial Cut ready.' if config.get('cylindrical') else
                'Sketch ready.' if feature is None else ('Feature ready.' if config['result'] == 'feature' else 'Extrude ready.'))
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
        self.session.close_defaults()
        self.session.renderer.reset()
        if self.session.edited_feature and self.session.restore_marker is not None:
            self.session.restore_timeline()
        if self.session in _sessions:
            _sessions.remove(self.session)
        self.session.selection_memory.clear()
        self.session.handlers.clear()


class EditActivate(adsk.core.CommandEventHandler):
    def __init__(self, session):
        super().__init__()
        self.session = session

    def notify(self, args):
        s = self.session
        if s.restore_marker is not None:
            return
        try:
            custom = s.edited_feature
            timeline = custom.parentComponent.parentDesign.timeline
            s.restore_marker = timeline.markerPosition
            s.restore_anchor = timeline.item(s.restore_marker-1) if s.restore_marker else None
            custom.timelineObject.rollTo(True)
            args.command.beginStep()
            s.updating = True
            try:
                for source in parametric.source_entities(custom):
                    s.inputs['source'].addSelection(source)
                center = parametric.center_entity(custom)
                if center is not None:
                    s.inputs['center_point'].addSelection(center)
                for key, entity in zip(('guide1', 'guide2'), parametric.guide_entities(custom, allow_missing=True)):
                    if entity is not None:
                        s.inputs[key].addSelection(entity)
                path = parametric.path_dependency(custom, strict=False)
                if path is not None:
                    s.inputs['path'].addSelection(path)
                data = parametric.stored(custom)
                for i in range(data['body_count']):
                    s.inputs['bodies'].addSelection(custom.dependencies.itemById('body' + str(i)).entity)
            finally:
                s.updating = False
            s.update_visibility()
        except Exception as error:
            log_error()
            s.status(str(error))


class EditCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            ui = adsk.core.Application.get().userInterface
            selected = [model.native(selection.entity) for selection in ui.activeSelections]
            custom = next((f for f in selected if isinstance(f, adsk.fusion.CustomFeature)
                           and f.definition.id == parametric.DEFINITION_ID), None)
            if custom is None:
                raise ValueError('Select a Perfora Feature in the timeline.')
            _sessions.append(Session(args.command, custom))
        except Exception as error:
            log_error()
            adsk.core.Application.get().userInterface.messageBox(str(error), 'Perfora')


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
        edit = ui.commandDefinitions.itemById(parametric.EDIT_COMMAND_ID)
        if not edit:
            edit = ui.commandDefinitions.addButtonDefinition(parametric.EDIT_COMMAND_ID,
                'Edit Perfora Feature', 'Edit the parametric Perfora pattern.')
        parametric.register()
        edit_handler = EditCreated()
        edit.commandCreated.add(edit_handler)
        _handlers.append(edit_handler)
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
        edit = ui.commandDefinitions.itemById(parametric.EDIT_COMMAND_ID)
        if edit:
            edit.deleteMe()
        parametric.unregister()
        _handlers.clear()
    except Exception:
        log_error()
