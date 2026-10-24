# SPDX-License-Identifier: GPL-3.0-only
"""Multi-region CAD preparation. All sources are read before output is modified."""
from dataclasses import dataclass, replace
import json

import adsk.core
import adsk.fusion

from . import clipping, model, regions, solid


def sources(selected):
    """Validate context before discarding assembly proxies; remove exact repeats."""
    selected = list(selected) if isinstance(selected, (tuple, list)) else [selected]
    result, component, context = [], None, None
    for item in selected:
        entity = model.native(item)
        if entity is None or not entity.isValid:
            raise ValueError('A Profiles region is missing. Select the source again.')
        owner = model.source_component(entity)
        occurrence = getattr(item, 'assemblyContext', None)
        if component is None:
            component, context = owner, occurrence
        elif owner != component or occurrence != context:
            raise ValueError('All Profiles regions must belong to the same component occurrence.')
        if not any(entity == previous for previous in result):
            result.append(entity)
    if not result:
        raise ValueError('Select a profile, planar face, or construction plane.')
    if len(result) > regions.MAX_REGIONS:
        raise ValueError('Select at most %d Profiles regions.' % regions.MAX_REGIONS)
    if len(result) > 1 and any(isinstance(s, adsk.fusion.ConstructionPlane) for s in result):
        raise ValueError('Use one construction plane, or select multiple planar faces and closed profiles.')
    # Selection filters are a convenience; API callers and Feature recompute
    # must also reject nonplanar faces and off-plane profiles.
    for entity in result:
        if isinstance(entity, adsk.fusion.BRepFace) and not isinstance(entity.geometry, adsk.core.Plane):
            raise ValueError('All selected faces must be planar.')
        if isinstance(entity, adsk.fusion.Profile) and not entity.isOnSketchPlane:
            raise ValueError('Select profiles on their sketch planes.')
    return result


def validate(selected, config):
    first = selected[0] if isinstance(selected, (tuple, list)) and selected else selected
    context = getattr(first, 'assemblyContext', None)
    selected = sources(selected)
    if len(selected) == 1:
        return selected, None
    if config['result'] != 'profiles' and config['operation'] == 'component':
        raise ValueError('Multiple Profiles support New Body in the source component. Use one region for New Component.')
    if config['result'] == 'profiles' or config['operation'] == 'body':
        return selected, tuple(() for _ in selected)
    if config['operation'] == 'join' and config['result'] == 'extrude':
        # Native Join determines touching bodies itself, as in the single-source command.
        return selected, tuple(() for _ in selected)
    if context is not None and any(getattr(b, 'assemblyContext', None) is not None and b.assemblyContext != context
           for b in config['bodies']):
        raise ValueError('Profiles and Objects must use the same component occurrence.')
    owner = model.source_component(selected[0])
    targets = [model.native(b) for b in config['bodies']]
    if any(b is None or not b.isValid or b.parentComponent != owner for b in targets):
        raise ValueError('Profiles and Objects must belong to the same component.')
    if any(targets[i] == targets[j] for i in range(len(targets)) for j in range(i)):
        raise ValueError('Select each Object only once.')
    saved = config.get('_body_map')
    if saved is not None:
        mapping = tuple(tuple(indices) for indices in saved)
        if (len(mapping) != len(selected) or any(len(indices) != 1 for indices in mapping)
                or any(not isinstance(i, int) or not 0 <= i < len(targets) for indices in mapping for i in indices)
                or set(i for indices in mapping for i in indices) != set(range(len(targets)))):
            raise ValueError('The Feature Objects mapping is invalid. Restore the source dependencies.')
        if config['operation'] == 'intersect' and len({indices[0] for indices in mapping}) != len(mapping):
            raise ValueError('Intersect supports one Profiles region per Object.')
        return selected, mapping
    return selected, regions.target_map([model.native(model.source_support_body(s)) for s in selected],
                                         targets, config['operation'])


class PlaneFrame:
    """Only the coordinate methods needed by the existing source/trim adapters."""
    def __init__(self, frame, component):
        self.frame = frame
        self.parentComponent = component

    def sketchToModelSpace(self, point):
        return adsk.core.Point3D.create(*regions.to_world(self.frame, point.asArray()))

    def modelToSketchSpace(self, point):
        return adsk.core.Point3D.create(*regions.to_local(self.frame, point.asArray()))


def matrix(frame):
    origin, u, v = frame
    result = adsk.core.Matrix3D.create()
    result.setWithCoordinateSystem(adsk.core.Point3D.create(*origin),
        adsk.core.Vector3D.create(*u), adsk.core.Vector3D.create(*v),
        adsk.core.Vector3D.create(*regions.cross(u, v)))
    return result


def cleanup(items, activate=False):
    """Try every owned object, even if one deletion fails; command rollback follows."""
    # Grouping a Custom Feature rolls the marker before its owned geometry.
    # Activate the latest owned item before deleting dependants in reverse order.
    for item in reversed(items) if activate else ():
        try:
            timeline = getattr(item, 'timelineObject', None) if item is not None and item.isValid else None
            if timeline is not None and timeline.rollTo(False):
                break
        except Exception:
            pass  # Still attempt every deletion; the transaction is the final fallback.
    errors = []
    for item in reversed(items):
        try:
            if item is not None and item.isValid and item.deleteMe() is False:
                errors.append('Fusion refused to remove an output item.')
        except Exception as error:
            errors.append(str(error))
    if errors:
        raise RuntimeError('Unable to clean up all Perfora output: ' + '; '.join(errors))


@dataclass
class Plan:
    source: object
    native_frame: tuple
    frame: tuple
    region: object
    settings: object
    original: object
    cells: tuple
    clipped: object
    body_indices: tuple
    revision: object
    inset: object = None


def prepare(selected, settings, config, cache=None, frames=None, previous=None):
    selected, mapping = validate(selected, config)
    if len(selected) < 2:
        raise ValueError('Multiple Profiles requires at least two different regions.')
    plans = []
    for index, source in enumerate(selected):
        revision = model.source_revision(source)
        old = next((p for p in previous or () if p.source == source and p.revision == revision
                    and p.original.isValid), None) if frames is None else None
        if old and any(p.frame != old.frame and regions.coplanar(p.frame, old.frame) for p in plans):
            # A changed first source can resolve the plane with slightly different
            # floating-point axes. Reread rather than compare sheets in two bases.
            old = None
        sketch = None if old else (frames[index] if frames is not None else model.new_source_sketch(source))
        try:
            component = model.source_component(source)
            if old:
                native_frame, frame, region, original = old.native_frame, old.frame, old.region, old.original
            else:
                native_frame = model.sketch_frame(sketch)
                frame = regions.canonical_frame(native_frame)
                # Snap only genuinely coplanar frames to a common numerical basis.
                frame = next((p.frame for p in plans if regions.coplanar(p.frame, frame)), frame)
                adapter = PlaneFrame(frame, component)
                region = model.get_region(source, adapter, config)
                original = clipping.source_body(source, adapter, config, region)
            layout = model.layout_settings(settings, config, region, frame, component)
            if config.get('center_point') is None:
                layout = replace(layout, origin_x=0., origin_y=0.)
            candidates = cache.for_region(index).resolve(region, layout, frame) if cache is not None else None
            clipped = inset = None
            if settings.clip_boundary:
                inset = (old.inset if old and old.inset is not None and old.inset.isValid
                         and old.settings.margin == settings.margin else
                         clipping.inset_body(source, original, settings.margin))
                trimmed = clipping.apply_spread(inset, region, layout)
                clipped = clipping.layout(original, trimmed, region, layout, candidates)
                cells = clipped.cells
            else:
                from .geometry import generate
                cells = generate(region, layout) if candidates is None else candidates
            plans.append(Plan(source, native_frame, frame, region, layout, original,
                              tuple(cells), clipped, mapping[index], revision, inset))
            if sum(len(p.cells) for p in plans) > settings.limit:
                raise ValueError('The total hole count exceeds Maximum Holes (%d).' % settings.limit)
        finally:
            if frames is None and sketch is not None:
                cleanup([sketch])
    manager = adsk.fusion.TemporaryBRepManager.get()
    for i, plan in enumerate(plans):
        for other in plans[:i]:
            if plan.frame != other.frame or not regions.bounds_overlap(plan.region, other.region):
                continue
            if previous and all(any(p.source == current.source and p.original is current.original for p in previous)
                                for current in (plan, other)):
                continue  # These exact source sheets have already passed the overlap check.
            overlap = manager.copy(plan.original)
            if not manager.booleanOperation(overlap, other.original, adsk.fusion.BooleanTypes.IntersectionBooleanType):
                raise ValueError('Unable to check overlapping Profiles. Select disjoint regions.')
            if overlap.faces.count and overlap.area > model.TOLERANCE**2:
                raise ValueError('Profiles regions overlap. Select disjoint regions; repeated references are ignored.')
    return plans


def draw(plan, sketch, config):
    """Copy exact canonical curves into the actual source sketch, including reflections."""
    adapter = PlaneFrame(plan.frame, sketch.parentComponent)
    transform = model.sketch_transform(adapter, sketch)

    def curves(items, role):
        for item in items:
            curve = item.copy()
            curve.transformBy(transform)
            model.copy_curve(sketch, curve, role)

    # Copy boundaries before deferred compute, matching the single-source path.
    if config['material'] == 'panel':
        loops = plan.clipped.panel_loops if plan.clipped else clipping.body_loops(plan.original)
        for items, outer in loops:
            curves(items, 'outer' if outer else 'void')
    sketch.isComputeDeferred = True
    try:
        if plan.clipped:
            if config['material'] != 'panel':
                for items, outer in plan.clipped.partial_loops:
                    curves(items, 'cell' if outer else 'clip_void')
            for cell in plan.clipped.whole:
                curves(clipping.cell_curves(cell), 'cell')
        else:
            for cell in plan.cells:
                curves(clipping.cell_curves(cell), 'cell')
    finally:
        sketch.isComputeDeferred = False
    profiles = model.selected_profiles(sketch, config['material'], plan.clipped is not None)
    if not plan.clipped and config['material'] == 'cells' and profiles.count != len(plan.cells):
        raise ValueError('The profile count differs from the hole count. Increase Web Thickness.')
    return profiles


def build(selected, settings, config, cache=None):
    plans = prepare(selected, settings, config, cache)
    owned, outputs = [], []
    try:
        # Every sketch is complete before the first Boolean consumes a source face.
        for index, plan in enumerate(plans):
            sketch = model.new_source_sketch(plan.source)
            owned.append(sketch)
            sketch.name = 'Perforation %d - %s' % (index+1, settings.shape.title())
            profiles = draw(plan, sketch, config)
            payload = dict(settings.__dict__)
            payload.update(region_index=index, region_count=len(plans), frame=plan.frame,
                           binding='component', material=config['material'], result=config['result'])
            sketch.attributes.add(model.ATTRIBUTE_GROUP, 'settings', json.dumps(payload))
            outputs.append((sketch, profiles, plan))
        features = []
        for sketch, profiles, plan in outputs:
            if config['result'] == 'extrude':
                local = dict(config)
                local['bodies'] = [config['bodies'][i] for i in plan.body_indices]
                feature = model.extrude(sketch.parentComponent, profiles, local)
                owned.append(feature)
                features.append(feature)
                sketch.isVisible = False
            else:
                sketch.isVisible = True
        return outputs[0][0], features[-1] if features else None, sum(len(p.cells) for p in plans)
    except Exception:
        cleanup(owned)
        raise


def make_body(plan, config):
    manager = adsk.fusion.TemporaryBRepManager.get()
    sheets = [clipping.sheet([clipping.cell_curves(c)]) for c in
              (plan.clipped.whole if plan.clipped else plan.cells)]
    if plan.clipped:
        sheets.extend(plan.clipped.partial_bodies)
    if config['material'] == 'panel':
        panel = manager.copy(plan.original)
        for sheet in sheets:
            if not manager.booleanOperation(panel, sheet, adsk.fusion.BooleanTypes.DifferenceBooleanType):
                raise ValueError('Unable to build the perforated Feature panel.')
        sheets = [panel]
    units = model.source_component(plan.source).parentDesign.unitsManager
    start, d1, d2 = (units.evaluateExpression(config[k], 'mm') for k in ('start', 'distance1', 'distance2'))
    if d1 <= 0 or (config['direction'] == 'two' and d2 <= 0):
        raise ValueError('Feature distances must be positive.')
    if config['direction'] == 'symmetric':
        low, high = start-d1/2, start+d1/2
    elif config['direction'] == 'two':
        low, high = start-d2, start+d1
    else:
        low, high = (start-d1, start) if config['reverse'] else (start, start+d1)
    if regions.dot(regions.cross(plan.native_frame[1], plan.native_frame[2]),
                   regions.cross(plan.frame[1], plan.frame[2])) < 0:
        low, high = -high, -low
    body = solid.extrude(sheets, low, high)
    if not manager.transform(body, matrix(plan.frame)):
        raise ValueError('Unable to position the Feature body.')
    return body
