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
from .organic import PARAMETERS as ORGANIC_PARAMETERS
from .feature_data import SCHEMA, decode, metadata

DEFINITION_ID = '4FusionLab.Perfora.Parametric'
EDIT_COMMAND_ID = 'DiegoV_Perforator_EditFeature'
_definition = None
_handler = None
_busy = False
# Internal units are cm/rad. UI expressions (including user parameters) are kept.
PARAMETERS = {
    'size': ('Hole Size / Cell Spacing', 'mm'),
    'start_radius': ('Start Radius', 'mm'),
    'spread_radius': ('Spread Radius', 'mm'),
    'path_spacing': ('Path Spacing', 'mm'),
    'path_start': ('Path Start Offset', 'mm'),
    'path_end': ('Path End Offset', 'mm'),
    'path_position': ('Path Position', 'mm'),
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
PARAMETERS.update({key: (label, unit) for key, (label, unit, _) in ORGANIC_PARAMETERS.items()})
OPTIONAL_PARAMETERS = ('start_radius', 'spread_radius') + tuple(VARIANT_PARAMETERS)
INTEGER_PARAMETERS = ('star_points', 'seed', 'limit', 'fan_rays', 'guide_rows')
PATH_PARAMETERS = ('path_spacing', 'path_start', 'path_end', 'path_position')
OPTIONAL_PARAMETERS += PATH_PARAMETERS
OPTIONAL_PARAMETERS += tuple(ORGANIC_PARAMETERS)


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
    global _handler, _definition
    if _definition and _handler:
        _definition.customFeatureCompute.remove(_handler)
    _handler = None
    _definition = None


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


def stored(custom):
    return decode(custom.customNamedValues.value('perfora'))


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
    if stored(custom).get('source_count', 1) > 1:
        return source_entities(custom)[0]
    dependency = custom.dependencies.itemById('source')
    if dependency:
        return model.native(dependency.entity)
    axis = stored(custom)['config'].get('_origin_plane')
    if axis not in ('xY', 'xZ', 'yZ'):
        raise ValueError('The Feature source dependency is missing.')
    return getattr(custom.parentComponent, axis + 'ConstructionPlane')


def source_entities(custom):
    count = stored(custom).get('source_count', 1)
    if count == 1:
        return [source_entity(custom)]
    result = []
    for i in range(count):
        dependency = custom.dependencies.itemById('source' + str(i))
        entity = model.native(dependency.entity) if dependency else None
        if entity is None or not entity.isValid:
            raise ValueError('Feature Profiles region %d is missing. Restore the upstream geometry.' % (i+1))
        result.append(entity)
    return result


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
    validate_path_parameters(custom, settings)
    config = dict(data['config'])
    config['center_point'] = center_entity(custom)
    config.update(zip(('guide1', 'guide2'), guide_entities(custom)))
    config['path'] = path_dependency(custom)
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
    selected = source_entities(custom)
    if any(not source or not source.isValid for source in selected):
        raise ValueError('The Feature source is missing. Restore the upstream geometry.')
    config['bodies'] = []
    for i in range(data['body_count']):
        dependency = custom.dependencies.itemById('body' + str(i))
        body = model.native(dependency.entity) if dependency else None
        if body is None or not body.isValid:
            raise ValueError('A Feature Object dependency is missing. Restore the upstream body.')
        config['bodies'].append(body)
    config.update(target1=None, target2=None)
    return selected if len(selected) > 1 else selected[0], settings, config


def path_dependency(custom, strict=True):
    dependency = custom.dependencies.itemById('path')
    entity = dependency.entity if dependency else None
    if entity is not None and not entity.isValid:
        entity = None
    if strict and stored(custom)['settings'].get('layout') == 'path' and entity is None:
        raise ValueError('Path is missing. Edit the Perfora Feature to select another curve.')
    return entity


def validate_path_parameters(custom, settings):
    if settings.layout == 'path' and any(not custom.parameters.itemById(key) for key in PATH_PARAMETERS):
        raise ValueError('This older Perfora Feature has no Path parameters. Recreate it to use Along Path.')


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
    if isinstance(source, (tuple, list)):
        from . import multi_region
        selected, _ = multi_region.validate(source, config)
        if len(selected) > 1:
            return build_many(selected, settings, config, cache)
        source = selected[0]
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
    if settings.layout == 'path':
        path = model.path_reference(config.get('path'), component)
        if isinstance(model.native(path), adsk.fusion.SketchCurve):
            data.addDependency('path_sketch', path.parentSketch)
        if not data.addDependency('path', path):
            raise ValueError('Unable to create the Path dependency.')
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
        # Face-backed reference sketches must precede the empty Custom Feature.
        # During native preview on a Base Feature result, creating them after
        # that placeholder can bind their support to the placeholder itself.
        if not config.get('surface'):
            frame = (component.sketches.addWithoutEdges(component.xYConstructionPlane)
                     if config.get('surface') else model.new_source_sketch(source))
            frame.name = 'Perfora Reference'
            # Exact temporary offsets no longer edit this compatibility sketch.
            # A second sketch on the same selected Base Feature face inside a
            # native command can acquire a circular reference to the first.
            scratch = component.sketches.addWithoutEdges(component.xYConstructionPlane)
            scratch.name = 'Perfora Edge Offset'
        # Insert the owning node before its already-created reference sketches.
        # Creating those sketches after a placeholder can make face references
        # circular; grouping sketches placed before the owner leaves that owner
        # in a permanently rolled-back state in native Edit Feature.
        if frame:
            if not frame.timelineObject.rollTo(True):
                raise ValueError('Unable to prepare the Feature timeline.')
        # Still capture dependencies before Boolean operations consume faces.
        custom = component.features.customFeatures.add(data)
        custom.customNamedValues.addOrSetValue('perfora', json.dumps(metadata(settings, config)))
        if scratch:
            if not scratch.timelineObject.rollTo(False):
                raise ValueError('Unable to restore the Feature reference sketches.')
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


def build_many(selected, settings, config, cache=None):
    """One timeline node, one source dependency/reference/base per region."""
    global _busy
    from . import multi_region
    selected, mapping = multi_region.validate(selected, config)
    component = model.source_component(selected[0])
    validate(config, component.parentDesign)
    config = dict(config, _source_count=len(selected), _body_map=mapping)
    if config['operation'] == 'body':
        config['bodies'] = []  # Hidden Objects must not become unused dependencies.
    data = component.features.customFeatures.createInput(register())
    dependencies = [('source' + str(i), dependency_entity(s, component)) for i, s in enumerate(selected)]
    dependencies.extend(('body' + str(i), dependency_entity(body, component)) for i, body in enumerate(config['bodies']))
    if config.get('center_point') is not None:
        dependencies.append(('center_point', model.point_reference(config['center_point'], component)))
    if settings.layout == 'path': dependencies.append(('path', model.path_reference(config.get('path'), component)))
    if settings.layout == 'between_curves':
        dependencies.extend((key, model.guide_reference(config.get(key), component)) for key in ('guide1','guide2'))
    for identifier, entity in dependencies:
        if not data.addDependency(identifier, entity):
            raise ValueError('Unable to create Feature dependency: ' + identifier)
    expressions = config.get('_expressions', {})
    for key, (label, unit) in parameters(config).items():
        val = expressions.get(key)
        if val is None:
            val = getattr(settings, key) if key in settings.__dict__ else config[key]
        vi = model.value(val) if isinstance(val, str) else adsk.core.ValueInput.createByReal(val)
        if not data.addCustomParameter(key, label, vi, unit, True):
            raise ValueError('Unable to create Feature parameter: ' + label)
    owned, frames, bases, combines = [], [], [], []
    previous_busy = _busy
    _busy = True
    try:
        custom = component.features.customFeatures.add(data)
        owned.append(custom)
        custom.customNamedValues.addOrSetValue('perfora', json.dumps(metadata(settings, config)))
        for index, source in enumerate(selected):
            frame = (component.sketches.addWithoutEdges(component.xYConstructionPlane)
                     if config.get('surface') else model.new_source_sketch(source))
            owned.append(frame)
            frames.append(frame)
            frame.name = 'Perfora Reference %d' % (index+1)
        plans = multi_region.prepare(selected, settings, config, cache, frames)
        # All temporary solids must succeed before the first persistent body is added.
        bodies = [multi_region.make_body(plan, config) for plan in plans]
        for index, body in enumerate(bodies):
            base = component.features.baseFeatures.add()
            owned.append(base)
            bases.append(base)
            base.name = 'Perfora Geometry %d' % (index+1)
            if not base.startEdit():
                raise ValueError('Unable to create the Perfora Feature geometry.')
            try:
                if not component.bRepBodies.add(body, base):
                    raise ValueError('Unable to add the Perfora Feature body.')
            finally:
                if not base.finishEdit():
                    raise ValueError('Unable to finish the Perfora Feature geometry.')
        if config['operation'] in ('cut', 'intersect', 'join'):
            operations = dict(cut=adsk.fusion.FeatureOperations.CutFeatureOperation,
                              join=adsk.fusion.FeatureOperations.JoinFeatureOperation,
                              intersect=adsk.fusion.FeatureOperations.IntersectFeatureOperation)
            for plan, base in zip(plans, bases):
                tool = base.bodies.item(0)
                for index in plan.body_indices:
                    tools = adsk.core.ObjectCollection.create()
                    tools.add(tool)
                    data = component.features.combineFeatures.createInput(model.native(config['bodies'][index]), tools)
                    data.operation, data.isKeepToolBodies = operations[config['operation']], True
                    combine = component.features.combineFeatures.add(data)
                    if combine is None:
                        raise ValueError('Unable to create the Perfora Feature operation.')
                    owned.append(combine)
                    combines.append(combine)
                    if combine.healthState == adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState:
                        raise ValueError(combine.errorOrWarningMessage or 'Feature operation failed.')
                tool.isVisible = False
        custom.timelineObject.rollTo(True)
        if not custom.setStartAndEndFeatures(frames[0], combines[-1] if combines else bases[-1]):
            raise ValueError('Unable to group the Perfora Feature.')
        custom.timelineObject.rollTo(False)
        for frame in frames:
            frame.isVisible = False
        return frames[0], custom, sum(len(plan.cells) for plan in plans)
    except Exception:
        multi_region.cleanup(owned, activate=True)
        raise
    finally:
        _busy = previous_busy


def rebuild_many(custom, selected, settings, config, cache=None):
    from . import multi_region
    validate(config, custom.parentComponent.parentDesign)
    features = list(custom.features)
    frames = [f for f in features if isinstance(f, adsk.fusion.Sketch)]
    bases = [f for f in features if isinstance(f, adsk.fusion.BaseFeature)]
    if len(frames) != len(selected) or len(bases) != len(selected):
        raise ValueError('The Feature region geometry is missing. Restore the owned reference sketches and bases.')
    plans = multi_region.prepare(selected, settings, config, cache, frames)
    bodies = [multi_region.make_body(plan, config) for plan in plans]
    manager = adsk.fusion.TemporaryBRepManager.get()
    backups = []
    try:
        for base, body in zip(bases, bodies):
            if not base.startEdit():
                raise ValueError('Unable to update the Perfora Feature.')
            try:
                previous = manager.copy(base.bodies.item(0))
                if not previous:
                    raise ValueError('Unable to back up the Perfora Feature geometry.')
                backups.append((base, previous))
                if not base.updateBody(base.bodies.item(0), body):
                    raise ValueError('Fusion could not update a Perfora Feature region.')
            finally:
                if not base.finishEdit():
                    raise ValueError('Unable to finish the Perfora Feature update.')
    except Exception:
        # Compute callbacks have no command transaction. Restore every attempted
        # base update, including one whose failed update may have mutated its body.
        errors = []
        for base, previous in reversed(backups):
            try:
                if not base.startEdit():
                    raise ValueError('Unable to restore a Perfora Feature region.')
                try:
                    if not base.updateBody(base.bodies.item(0), previous):
                        raise ValueError('Unable to restore a Perfora Feature body.')
                finally:
                    if not base.finishEdit():
                        raise ValueError('Unable to finish restoring a Perfora Feature region.')
            except Exception as error:
                errors.append(str(error))
        if errors:
            raise RuntimeError('Feature rollback failed: ' + '; '.join(errors))
        raise
    return sum(len(plan.cells) for plan in plans)


def rebuild(custom, cache=None):
    source, settings, config = read(custom)
    if isinstance(source, list):
        return rebuild_many(custom, source, settings, config, cache)
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
    validate_path_parameters(custom, settings)
    _busy = True
    try:
        config = dict(config)
        original = stored(custom)['config']
        for key in ('_origin_plane', '_source_count', '_body_map'):
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
        dependency = custom.dependencies.itemById('path')
        if settings.layout == 'path':
            reference = model.path_reference(config.get('path'), custom.parentComponent)
            if dependency:
                dependency.entity = reference
            else:
                custom.dependencies.add('path', reference)
            owner = custom.dependencies.itemById('path_sketch')
            if isinstance(model.native(reference), adsk.fusion.SketchCurve):
                if owner: owner.entity = reference.parentSketch
                else: custom.dependencies.add('path_sketch', reference.parentSketch)
            elif owner: owner.deleteMe()
        elif dependency:
            dependency.deleteMe()
            owner = custom.dependencies.itemById('path_sketch')
            if owner: owner.deleteMe()
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
