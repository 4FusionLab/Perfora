# SPDX-License-Identifier: GPL-3.0-only
"""Parametric Perfora timeline node; compute updates owned base geometry."""
from dataclasses import replace
import json
import math
from pathlib import Path
import traceback

import adsk.core
import adsk.fusion

from . import clipping, model, solid, surface
from .geometry import Settings, generate
from .distributions import VARIANT_PARAMETERS

DEFINITION_ID = '4FusionLab.Perfora.Parametric'
EDIT_COMMAND_ID = 'DiegoV_Perforator_EditFeature'
SCHEMA = 1
_definition = None
_handler = None
_busy = False
# Internal units are cm/rad. UI expressions (including user parameters) are kept.
PARAMETERS = {
    'size': ('Hole Size / Cell Spacing', 'mm'),
    'start_radius': ('Start Radius', 'mm'),
    'spread_radius': ('Spread Radius', 'mm'),
    'slot_length': ('Hole Length', 'mm'), 'gap': ('Web Thickness', 'mm'),
    'margin': ('Edge Offset', 'mm'), 'grid_angle': ('Pattern Angle', 'deg'),
    'shape_angle': ('Hole Angle', 'deg'), 'offset_x': ('X Offset', 'mm'),
    'offset_y': ('Y Offset', 'mm'), 'arm_width': ('Arm Width', 'mm'),
    'star_ratio': ('Inner Radius Ratio', ''), 'star_points': ('Points', ''),
    'irregularity': ('Irregularity Ratio', ''), 'seed': ('Seed', ''),
    'limit': ('Maximum Holes', ''), 'corner_radius': ('Corner Radius', 'mm'),
    'width': ('Boundary Width / Diameter', 'mm'), 'height': ('Boundary Height', 'mm'),
    'start': ('Start Offset', 'mm'), 'distance1': ('Distance 1', 'mm'),
    'distance2': ('Distance 2', 'mm'),
}
PARAMETERS.update({key: (label, unit) for key, (label, unit, _) in VARIANT_PARAMETERS.items()})
OPTIONAL_PARAMETERS = ('start_radius', 'spread_radius') + tuple(VARIANT_PARAMETERS)
INTEGER_PARAMETERS = ('star_points', 'seed', 'limit', 'fan_rays', 'guide_rows')


def register():
    global _definition, _handler
    if _handler is not None:
        return _definition
    _definition = adsk.fusion.CustomFeatureDefinition.create(
        DEFINITION_ID, 'Perfora', str(Path(__file__).parent / 'resources/toolbar-f692fbb3'))
    _definition.editCommandId = EDIT_COMMAND_ID
    _handler = Compute()
    _definition.customFeatureCompute.add(_handler)
    return _definition


def unregister():
    global _handler
    if _definition and _handler:
        _definition.customFeatureCompute.remove(_handler)
    _handler = None


def validate(config, design=None):
    if config.get('cylindrical') and not config.get('surface'):
        raise ValueError('Cylindrical Radial Cut uses a fixed pattern. Feature recompute and Edit Feature are not supported yet.')
    design = design or adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    if not design or design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
        raise ValueError('Feature requires Capture Design History.')
    sides = ('1', '2') if config['direction'] == 'two' else ('1',)
    if any(config['extent' + s] != 'distance' for s in sides) and config['direction'] != 'symmetric':
        raise ValueError('Feature supports Distance extents. Use Extrude for All or To Object.')
    units = design.unitsManager
    if any(abs(units.evaluateExpression(config['taper' + s], 'deg')) > 1e-10 for s in sides):
        raise ValueError('Feature requires a zero Taper Angle. Use Extrude for tapered holes.')
    if config['operation'] == 'component':
        raise ValueError('Feature supports New Body in the source component. Use Extrude for New Component.')


def parameters(config):
    return dict(PARAMETERS, **surface.ZONE_PARAMETERS) if config.get('surface') else PARAMETERS


def metadata(settings, config):
    return dict(schema=SCHEMA, settings=dict(settings.__dict__),
                config={k: v for k, v in config.items()
                        if k not in ('bodies', 'target1', 'target2', '_expressions', 'center_point', 'guide1', 'guide2')},
                center_selected=config.get('center_point') is not None,
                body_count=len(config['bodies']))


def stored(custom):
    data = json.loads(custom.customNamedValues.value('perfora'))
    if data['schema'] != SCHEMA:
        raise ValueError('This Perfora Feature was created by an unsupported version.')
    return data


def dependency_entity(entity, component):
    entity = model.native(entity)
    root = component.parentDesign.rootComponent
    if component == root:
        return entity
    occurrences = root.allOccurrencesByComponent(component)
    if not occurrences.count:
        raise ValueError('The source component has no assembly context.')
    return entity.createForAssemblyContext(occurrences.item(0))


def source_entity(custom):
    dependency = custom.dependencies.itemById('source')
    if dependency:
        return model.native(dependency.entity)
    axis = stored(custom)['config'].get('_origin_plane')
    if axis not in ('xY', 'xZ', 'yZ'):
        raise ValueError('The Feature source dependency is missing.')
    return getattr(custom.parentComponent, axis + 'ConstructionPlane')


def center_entity(custom):
    dependency = custom.dependencies.itemById('center_point')
    entity = dependency.entity if dependency else None
    if stored(custom).get('center_selected') and (entity is None or not entity.isValid):
        raise ValueError('Start Point is missing. Edit the Perfora Feature to select another point.')
    return entity


def guide_entities(custom, allow_missing=False):
    if stored(custom)['settings'].get('layout') != 'between_curves':
        return (None, None)
    result = []
    for key in ('guide1', 'guide2'):
        dependency = custom.dependencies.itemById(key)
        entity = dependency.entity if dependency else None
        if entity is None or not entity.isValid:
            if not allow_missing:
                raise ValueError('A guide is missing. Edit the Perfora Feature to select two valid guides.')
            entity = None  # Edit must remain usable for replacing a lost guide.
        result.append(entity)
    return tuple(result)


def read(custom):
    data = stored(custom)
    settings = Settings(**data['settings'])
    config = dict(data['config'])
    config['center_point'] = center_entity(custom)
    config.update(zip(('guide1', 'guide2'), guide_entities(custom)))
    values = {}
    for key in parameters(config):
        p = custom.parameters.itemById(key)
        if not p:
            if key in OPTIONAL_PARAMETERS:
                values[key] = getattr(settings, key)
                continue  # Older nodes predate optional placement parameters.
            raise ValueError('The Feature is missing parameter: ' + key)
        values[key] = p.value
    for key in INTEGER_PARAMETERS:
        if not math.isfinite(values[key]) or values[key] != int(values[key]):
            raise ValueError(key + ' must be an integer.')
        values[key] = int(values[key])
    settings = replace(settings, **{k: v for k, v in values.items() if k in settings.__dict__})
    settings.validate()
    for key in ('width', 'height', *surface.ZONE_PARAMETERS):
        if key in values:
            config[key] = values[key]
    for key in ('start', 'distance1', 'distance2'):
        config[key] = custom.parameters.itemById(key).expression
    source = source_entity(custom)
    if not source or not source.isValid:
        raise ValueError('The Feature source is missing. Restore the upstream geometry.')
    config['bodies'] = [model.native(custom.dependencies.itemById('body' + str(i)).entity)
                        for i in range(data['body_count'])]
    config.update(target1=None, target2=None)
    return source, settings, config


def clear_sketch(sketch):
    # Offset constraints must go first; their generated curves are then free.
    while sketch.geometricConstraints.count:
        sketch.geometricConstraints.item(sketch.geometricConstraints.count - 1).deleteMe()
    while sketch.sketchCurves.count:
        sketch.sketchCurves.item(sketch.sketchCurves.count - 1).deleteMe()
    for p in reversed(list(sketch.sketchPoints)):
        if p != sketch.originPoint and p.connectedEntities.count == 0:
            p.deleteMe()


def make_body(source, settings, config, frame=None, scratch=None, cache=None):
    if config.get('surface'):
        validate(config, model.source_component(source).parentDesign)
        return surface.make_body(source, settings, config)
    validate(config, frame.parentComponent.parentDesign)
    if isinstance(source, adsk.fusion.ConstructionPlane):
        keys = ('width', 'height') if config['boundary'] == 'rectangle' else ('width',)
        if any(not math.isfinite(config[k]) or config[k] <= 0 for k in keys):
            raise ValueError('Boundary dimensions must be positive and finite.')
    region = model.get_region(source, frame, config)
    context = model.sketch_frame(frame)
    settings = model.layout_settings(settings, config, region, context, frame.parentComponent)
    candidates = cache.resolve(region, settings, context) if cache is not None else None
    original = clipping.source_body(source, frame, config, region)
    if settings.clip_boundary:
        trimmed = clipping.inset_body(source, original, settings.margin, scratch)
        trimmed = clipping.apply_spread(trimmed, region, settings)
        layout = clipping.layout(original, trimmed, region, settings, candidates)
        cells = layout.cells
        sheets = [clipping.sheet([clipping.cell_curves(cell)]) for cell in layout.whole]
        sheets.extend(layout.partial_bodies)
    else:
        cells = generate(region, settings) if candidates is None else candidates
        sheets = [clipping.sheet([clipping.cell_curves(cell)]) for cell in cells]
    if config['material'] == 'panel':
        panel = adsk.fusion.TemporaryBRepManager.get().copy(original)
        for sheet in sheets:
            if not adsk.fusion.TemporaryBRepManager.get().booleanOperation(
                    panel, sheet, adsk.fusion.BooleanTypes.DifferenceBooleanType):
                raise ValueError('Unable to build the perforated Feature panel.')
        sheets = [panel]
    units = frame.parentComponent.parentDesign.unitsManager
    start = units.evaluateExpression(config['start'], 'mm')
    d1 = units.evaluateExpression(config['distance1'], 'mm')
    d2 = units.evaluateExpression(config['distance2'], 'mm')
    if d1 <= 0 or (config['direction'] == 'two' and d2 <= 0):
        raise ValueError('Feature distances must be positive.')
    if config['direction'] == 'symmetric':
        low, high = start - d1 / 2, start + d1 / 2
    elif config['direction'] == 'two':
        low, high = start - d2, start + d1
    else:
        low, high = (start - d1, start) if config['reverse'] else (start, start + d1)
    body = solid.extrude(sheets, low, high)
    origin = frame.sketchToModelSpace(model.point((0, 0)))
    u = origin.vectorTo(frame.sketchToModelSpace(model.point((1, 0))))
    v = origin.vectorTo(frame.sketchToModelSpace(model.point((0, 1))))
    transform = adsk.core.Matrix3D.create()
    transform.setWithCoordinateSystem(origin, u, v, u.crossProduct(v))
    if not adsk.fusion.TemporaryBRepManager.get().transform(body, transform):
        raise ValueError('Unable to position the Feature body.')
    return body, len(cells)


def build(source, settings, config, cache=None):
    global _busy
    from . import cylindrical
    if cylindrical.is_cylinder(model.native(source)) and not config.get('surface'):
        raise ValueError('Cylindrical faces support fixed Radial Cut only. Feature recompute and Edit Feature are not supported yet.')
    component = model.source_component(source)
    config = surface.normalized(config, component) if config.get('surface') else dict(config)
    validate(config, component.parentDesign)
    if config.get('surface') and config['operation'] in ('cut','join','intersect') and not config['bodies']:
        config['bodies'] = [model.native(source).body]
    data = component.features.customFeatures.createInput(register())
    origin = next((axis for axis in ('xY', 'xZ', 'yZ')
                   if source == getattr(component, axis + 'ConstructionPlane')), None)
    if origin:
        config['_origin_plane'] = origin
    else:
        data.addDependency('source', dependency_entity(source, component))
    if config.get('center_point') is not None:
        data.addDependency('center_point', model.point_reference(config['center_point'], component))
    if settings.layout == 'between_curves':
        for key in ('guide1', 'guide2'):
            if not data.addDependency(key, model.guide_reference(config.get(key), component)):
                raise ValueError('Unable to capture the guide dependency.')
    for i, target in enumerate(config['bodies']):
        data.addDependency('body' + str(i), dependency_entity(target, component))
    expressions = config.get('_expressions', {})
    for key, (label, unit) in parameters(config).items():
        val = expressions.get(key)
        if val is None:
            val = getattr(settings, key) if key in settings.__dict__ else config[key]
        vi = model.value(val) if isinstance(val, str) else adsk.core.ValueInput.createByReal(val)
        if not data.addCustomParameter(key, label, vi, unit, True):
            raise ValueError('Unable to create Feature parameter: ' + label)
    custom = frame = scratch = base = None
    combines = []
    previous_busy = _busy
    _busy = True
    try:
        # Capture dependencies before our Boolean operations consume the source
        # face/body. Adding the custom feature afterwards binds to its own result
        # and leaves it rolled back, producing a dependency cycle.
        custom = component.features.customFeatures.add(data)
        custom.customNamedValues.addOrSetValue('perfora', json.dumps(metadata(settings, config)))
        if not config.get('surface'):
            frame = model.new_source_sketch(source)
            frame.name = 'Perfora Reference'
            scratch = model.new_source_sketch(source)
            scratch.name = 'Perfora Edge Offset'
        body, count = make_body(source, settings, config, frame, scratch, cache)
        base = component.features.baseFeatures.add()
        base.name = 'Perfora Geometry'
        base.startEdit()
        try:
            component.bRepBodies.add(body, base)
        finally:
            base.finishEdit()
        tool = base.bodies.item(0)
        if config['operation'] in ('cut', 'intersect', 'join'):
            targets = config['bodies']
            if not targets:
                raise ValueError('Select Objects for the Feature operation.')
            operations = dict(cut=adsk.fusion.FeatureOperations.CutFeatureOperation,
                              join=adsk.fusion.FeatureOperations.JoinFeatureOperation,
                              intersect=adsk.fusion.FeatureOperations.IntersectFeatureOperation)
            for target in targets:
                tools = adsk.core.ObjectCollection.create()
                tools.add(tool)
                combine_input = component.features.combineFeatures.createInput(model.native(target), tools)
                combine_input.operation = operations[config['operation']]
                combine_input.isKeepToolBodies = True
                combine = component.features.combineFeatures.add(combine_input)
                combines.append(combine)
                if combine.healthState == adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState:
                    raise ValueError(combine.errorOrWarningMessage)
            tool.isVisible = False
        custom.timelineObject.rollTo(True)
        if not custom.setStartAndEndFeatures(base if config.get('surface') else frame, combines[-1] if combines else base):
            raise ValueError('Unable to group the Perfora Feature.')
        custom.timelineObject.rollTo(False)
        if frame:
            frame.isVisible = scratch.isVisible = False
        return frame, custom, count
    except Exception:
        for item in reversed([custom, frame, scratch, base] + combines):
            if item and item.isValid:
                item.deleteMe()
        raise
    finally:
        _busy = previous_busy


def rebuild(custom, cache=None):
    source, settings, config = read(custom)
    features = custom.features
    sketches = [f for f in features if isinstance(f, adsk.fusion.Sketch)]
    base = next(f for f in features if isinstance(f, adsk.fusion.BaseFeature))
    body, count = (make_body(source, settings, config) if config.get('surface') else
                   make_body(source, settings, config, sketches[0], sketches[1], cache))
    if not base.startEdit():
        raise ValueError('Unable to update the Perfora Feature.')
    try:
        if not base.updateBody(base.bodies.item(0), body):
            raise ValueError('Fusion could not update the Perfora Feature body.')
    finally:
        base.finishEdit()
    return count


def update(custom, settings, config, cache=None):
    """Called in an edit transaction; intermediate parameter writes cannot compute."""
    global _busy
    _busy = True
    try:
        config = dict(config)
        original = stored(custom)['config']
        for key in ('_origin_plane',):
            if key in original:
                config[key] = original[key]
        center = config.get('center_point')
        dependency = custom.dependencies.itemById('center_point')
        if center is not None:
            reference = model.point_reference(center, custom.parentComponent)
            if dependency:
                dependency.entity = reference
            else:
                custom.dependencies.add('center_point', reference)
        elif dependency:
            dependency.deleteMe()
        for key in ('guide1', 'guide2'):
            dependency = custom.dependencies.itemById(key)
            entity = config.get(key) if settings.layout == 'between_curves' else None
            if entity is not None:
                reference = model.guide_reference(entity, custom.parentComponent)
                if dependency:
                    dependency.entity = reference
                else:
                    custom.dependencies.add(key, reference)
            elif dependency:
                dependency.deleteMe()
        custom.customNamedValues.addOrSetValue('perfora', json.dumps(metadata(settings, config)))
        expressions = config.get('_expressions', {})
        for key, (_, unit) in parameters(config).items():
            val = expressions.get(key)
            if val is None:
                val = getattr(settings, key) if key in settings.__dict__ else config[key]
            parameter = custom.parameters.itemById(key)
            if not parameter and key in OPTIONAL_PARAMETERS:
                continue  # Older nodes retain this value in their versioned settings.
            if isinstance(val, str):
                parameter.expression = val
            else:
                parameter.value = val
        return rebuild(custom, cache)
    finally:
        _busy = False


class Compute(adsk.fusion.CustomFeatureEventHandler):
    def notify(self, args):
        global _busy
        if _busy:
            return
        _busy = True
        try:
            rebuild(args.customFeature)
        except Exception as error:
            adsk.core.Application.get().log('Perfora Feature: ' + traceback.format_exc())
            # Fusion requires a predefined status ID; include the explanation
            # as additional information and keep the full traceback in its log.
            args.computeStatus.statusMessages.addError('DRPOINT_COMPUTE_FAILED', str(error))
        finally:
            _busy = False
