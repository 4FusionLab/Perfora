# SPDX-License-Identifier: GPL-3.0-only
"""Fusion adapter. No UI or filesystem changes; called inside command transactions."""
from dataclasses import replace
import json
import math

import adsk.core
import adsk.fusion

from .geometry import Loop, Region, Settings, POLYGON_SHAPES, disk_region, generate, rectangle_region, stitch
from .curve_layout import sample_path

ATTRIBUTE_GROUP = 'DiegoV.Perforator'  # Preserve attributes in existing documents.
TOLERANCE = 0.0001


def native(entity):
    # Fusion can briefly report a selection count while its entity is already
    # gone during cancellation/rollback. Treat it as an empty selection.
    return (entity.nativeObject or entity) if entity is not None else None


def point(p):
    return adsk.core.Point3D.create(p[0], p[1], 0)


def value(expression):
    return adsk.core.ValueInput.createByString(expression)


def source_component(source):
    source = native(source)
    if isinstance(source, adsk.fusion.Profile):
        return source.parentSketch.parentComponent
    if isinstance(source, adsk.fusion.BRepFace):
        return source.body.parentComponent
    if isinstance(source, adsk.fusion.ConstructionPlane):
        return source.component
    raise ValueError('Select a planar face, sketch profile, or construction plane.')


def source_revision(source):
    """Cheap invalidation for an edited source, even when its identity survives."""
    if isinstance(source, adsk.fusion.BRepFace):
        return source.body.revisionId
    if isinstance(source, adsk.fusion.Profile):
        return source.parentSketch.revisionId
    return tuple(source.transform.asArray())  # Construction-plane basis/origin.


def point_component(entity):
    """Owner of a supported point; preserve proxies until coordinates are resolved."""
    entity = native(entity)
    if isinstance(entity, adsk.fusion.SketchPoint):
        return entity.parentSketch.parentComponent
    if isinstance(entity, adsk.fusion.BRepVertex):
        return entity.body.parentComponent
    if isinstance(entity, adsk.fusion.ConstructionPoint):
        return entity.component
    raise ValueError('Select a sketch point, vertex, or construction point for Start Point.')


def point_reference(entity, component):
    """Assembly reference suitable for a Custom Feature dependency."""
    owner = point_component(entity)
    root = component.parentDesign.rootComponent
    if entity.assemblyContext or owner == root:
        return entity
    occurrences = root.allOccurrencesByComponent(owner)
    if occurrences.count != 1:
        raise ValueError('Select Start Point on a visible component occurrence.')
    return native(entity).createForAssemblyContext(occurrences.item(0))


def point_position(entity, component):
    if not entity or not entity.isValid:
        raise ValueError('Start Point is missing. Select another point or clear the selection.')
    local = native(entity)
    owner = point_component(local)
    position = (local.worldGeometry if isinstance(local, adsk.fusion.SketchPoint) else local.geometry).copy()
    # Native coordinates of a point in the source component are unambiguous,
    # including reused components. Cross-component references retain context.
    if owner != component:
        root = component.parentDesign.rootComponent
        if owner != root:
            position.transformBy(point_reference(entity, component).assemblyContext.transform2)
        if component != root:
            occurrences = root.allOccurrencesByComponent(component)
            if occurrences.count != 1:
                raise ValueError('Select Start Point in the Profiles component when it has multiple occurrences.')
            inverse = occurrences.item(0).transform2.copy()
            inverse.invert()
            position.transformBy(inverse)
    if not all(math.isfinite(v) for v in position.asArray()):
        raise ValueError('Start Point must have finite coordinates.')
    return position


def sketch_frame(sketch):
    origin = sketch.sketchToModelSpace(point((0, 0)))
    x = sketch.sketchToModelSpace(point((1, 0)))
    y = sketch.sketchToModelSpace(point((0, 1)))
    return (tuple(origin.asArray()), tuple(origin.vectorTo(x).asArray()),
            tuple(origin.vectorTo(y).asArray()))


def path_entity(entity, component):
    """First stage: a single path in the source component, without chain guessing."""
    if entity is None or not entity.isValid:
        raise ValueError('Select one Path in the Profiles plane.')
    entity = native(entity)
    if isinstance(entity, adsk.fusion.BRepEdge):
        owner = entity.body.parentComponent
    elif isinstance(entity, adsk.fusion.SketchCurve):
        owner = entity.parentSketch.parentComponent
    else:
        raise ValueError('Select one line, arc, circle, or spline. Path chains are not supported.')
    if owner != component:
        raise ValueError('Path and Profiles must belong to the same component.')
    if not isinstance(entity.geometry, (adsk.core.Line3D, adsk.core.Arc3D,
                                        adsk.core.Circle3D, adsk.core.NurbsCurve3D)):
        raise ValueError('Path must be one line, arc, circle, or spline. Other curves and chains are not supported.')
    return entity


def path_reference(entity, component):
    entity = path_entity(entity, component)
    root = component.parentDesign.rootComponent
    if component == root:
        return entity
    occurrences = root.allOccurrencesByComponent(component)
    if occurrences.count != 1:
        raise ValueError('Feature Path requires an unambiguous source component occurrence.')
    return entity.createForAssemblyContext(occurrences.item(0))


def path_revision(entity):
    revision = (entity.body.revisionId if isinstance(entity, adsk.fusion.BRepEdge)
                else entity.parentSketch.revisionId)
    # Fusion can defer revisionId changes until the command/event finishes.
    # Read exact curve data as well so live edits cannot reuse stale samples.
    geometry = entity.geometry
    nurbs = geometry if isinstance(geometry, adsk.core.NurbsCurve3D) else getattr(geometry, 'asNurbsCurve', None)
    if nurbs is None: return revision  # Offline evaluator contract.
    def frozen(value):
        if hasattr(value, 'asArray'): return tuple(value.asArray())
        if not isinstance(value, (str, bytes)) and hasattr(value, '__iter__'): return tuple(frozen(v) for v in value)
        return value
    return revision, frozen(nurbs.getData())


def path_samples(entity, settings, frame, component):
    entity = path_entity(entity, component)
    geometry = entity.geometry
    edge = isinstance(entity, adsk.fusion.BRepEdge)
    evaluator = entity.evaluator if edge else geometry.evaluator
    # The edge evaluator respects trimmed extents and its own direction. Using
    # edge.geometry.evaluator would incorrectly sample an entire parent curve.
    closed = (entity.startVertex == entity.endVertex if edge else
              isinstance(geometry, adsk.core.Circle3D) or
              isinstance(geometry, adsk.core.NurbsCurve3D) and geometry.isClosed)
    origin, u, v = frame
    n = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
    axes = (u, v, n)

    def component_point(p):
        # Sketch geometry is in sketch space. Avoid worldGeometry: its assembly
        # convention differs between fitted and control-point splines.
        return p if edge else entity.parentSketch.sketchToModelSpace(p)

    def project_point(p):
        xyz = component_point(p).asArray()
        delta = tuple(xyz[i]-origin[i] for i in range(3))
        return tuple(sum(a*b for a, b in zip(delta, axis)) for axis in axes)

    def project_vector(vector):
        xyz = vector.asArray()
        if not edge:
            sketch = entity.parentSketch
            zero = sketch.sketchToModelSpace(point((0, 0))).asArray()
            tip = sketch.sketchToModelSpace(adsk.core.Point3D.create(*xyz)).asArray()
            xyz = tuple(tip[i]-zero[i] for i in range(3))
        return tuple(sum(a*b for a, b in zip(xyz, axis)) for axis in axes)

    return sample_path(evaluator, settings, project_point, project_vector, closed)


class PathCache:
    """Renderer-owned one-entry sampling cache; never used for final CAD reread."""
    def __init__(self):
        self.key = self.samples = None
        self.builds = 0

    def resolve(self, entity, settings, frame, component):
        entity = path_entity(entity, component)
        key = (entity, path_revision(entity), frame, settings.path_spacing,
               settings.path_start, settings.path_end, settings.path_position,
               settings.path_reverse, settings.path_orientation)
        if key != self.key:
            samples = path_samples(entity, settings, frame, component)
            self.key, self.samples = key, samples
            self.builds += 1
        return self.samples


def layout_settings(settings, config, region, frame, component, path_cache=None):
    """Resolve a live anchor once for every CAD/preview path, without API in geometry.

    Orthogonal projection onto the Profiles plane lets points on other sketches
    locate the pattern too. Stored offsets remain relative to the selected point.
    """
    if settings.layout == 'path':
        if config.get('center_point') is not None:
            raise ValueError('Along Path does not support Start Point. Use Position and path offsets.')
        entity = config.get('path')
        samples = (path_cache.resolve(entity, settings, frame, component) if path_cache is not None
                   else path_samples(entity, settings, frame, component))
        return replace(settings, path_samples=samples)
    center = config.get('center_point')
    if center is not None:
        position = point_position(center, component)
        origin, u, v = frame
        delta = [position.asArray()[i] - origin[i] for i in range(3)]
        x, y = sum(a*b for a, b in zip(delta, u)), sum(a*b for a, b in zip(delta, v))
        settings = replace(settings, origin_x=x, origin_y=y)
    if settings.layout == 'between_curves':
        guides = [guide_strokes(config.get(key), frame, component) for key in ('guide1', 'guide2')]
        settings = replace(settings, guide1=guides[0], guide2=guides[1])
    return settings


def guide_reference(entity, component):
    """Initial guide support is deliberately restricted to the source component.

    Preserve a selected proxy for dependency capture. Cross-component guide
    transforms are an integration extension, never a silent projection.
    """
    if entity is None or not entity.isValid:
        raise ValueError('Select two valid guides for Between Curves.')
    local = native(entity)
    if isinstance(local, adsk.fusion.SketchCurve):
        owner = local.parentSketch.parentComponent
    elif isinstance(local, adsk.fusion.BRepEdge):
        owner = local.body.parentComponent
    else:
        raise ValueError('Select an open sketch curve or model edge for each guide.')
    if owner != component:
        raise ValueError('Guides and Profiles must belong to the same component.')
    if component == component.parentDesign.rootComponent or entity.assemblyContext:
        return entity
    occurrences = component.parentDesign.rootComponent.allOccurrencesByComponent(component)
    if occurrences.count != 1:
        raise ValueError('Select guides in an unambiguous component occurrence.')
    return local.createForAssemblyContext(occurrences.item(0))


def guide_strokes(entity, frame, component):
    """Fusion -> immutable planar strokes, shared by all result/preview modes.

    BRepEdge.evaluator retains trimmed edge extents. Convert native sketch
    geometry with sketchToModelSpace, matching sketch_frame; never flatten Z or
    assume worldGeometry has the component's local assembly context.
    """
    guide_reference(entity, component)
    local = native(entity)
    is_sketch = isinstance(local, adsk.fusion.SketchCurve)
    evaluator = (local.geometry.evaluator if is_sketch
                 else local.evaluator)
    ok, start, end = evaluator.getParameterExtents()
    if not ok:
        raise ValueError('Unable to determine a guide parameter range.')
    ok, points = evaluator.getStrokes(start, end, TOLERANCE)
    if not ok or len(points) > 2048:
        raise ValueError('Unable to sample the guide within the supported complexity. Simplify the curve.')
    origin, u, v = frame
    normal = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
    result = []
    for position in points:
        if is_sketch:
            position = local.parentSketch.sketchToModelSpace(position)
        delta = [position.asArray()[i]-origin[i] for i in range(3)]
        if abs(sum(a*b for a,b in zip(delta, normal))) > TOLERANCE*5:
            raise ValueError('Both guides must lie on the Profiles plane. Nonplanar guides are not supported.')
        result.append(tuple(sum(a*b for a,b in zip(delta, axis)) for axis in (u,v)))
    return tuple(result)


def strokes(evaluator, convert):
    ok, start, end = evaluator.getParameterExtents()
    if not ok:
        raise ValueError('Unable to determine the curve parameter range.')
    ok, points = evaluator.getStrokes(start, end, TOLERANCE)
    if not ok:
        raise ValueError('Unable to read the boundary geometry.')
    result = []
    for p in points:
        p = convert(p)
        if abs(p.z) > TOLERANCE * 5:
            raise ValueError('The entire region must lie on the sketch plane.')
        result.append((p.x, p.y))
    return result


def get_region(source, sketch, config):
    if isinstance(source, adsk.fusion.BRepFace):
        loops = []
        for loop in source.loops:
            paths = [strokes(edge.evaluator, sketch.modelToSketchSpace) for edge in loop.edges]
            loops.append(Loop(stitch(paths, TOLERANCE * 2), loop.isOuter))
        return Region(tuple(loops), TOLERANCE)
    if isinstance(source, adsk.fusion.Profile):
        parent = source.parentSketch
        convert = lambda p: sketch.modelToSketchSpace(parent.sketchToModelSpace(p))
        loops = []
        for loop in source.profileLoops:
            paths = [strokes(curve.geometry.evaluator, convert) for curve in loop.profileCurves]
            loops.append(Loop(stitch(paths, TOLERANCE * 2), loop.isOuter))
        return Region(tuple(loops), TOLERANCE)
    if config['boundary'] == 'circle':
        return disk_region(config['width'])
    return rectangle_region(config['width'], config['height'])


def tag(curve, role):
    # Cell profiles live in an otherwise empty sketch. Per-edge persistent
    # attributes trigger Fusion entity tracking for every line (six per hexagon)
    # and are unnecessary. Only panel boundaries need a role.
    if role != 'cell':
        curve.attributes.add(ATTRIBUTE_GROUP, 'role', role)
    return curve


def add_polygon(sketch, vertices, role):
    lines = sketch.sketchCurves.sketchLines
    first = None
    previous = None
    for i in range(len(vertices)):
        start = previous or point(vertices[i])
        end = first if i == len(vertices) - 1 else point(vertices[(i + 1) % len(vertices)])
        line = tag(lines.addByTwoPoints(start, end), role)
        first = first or line.startSketchPoint
        previous = line.endSketchPoint


def add_cell(sketch, cell):
    curves = sketch.sketchCurves
    if cell.shape == 'circle' or (cell.shape == 'slot' and abs(cell.length - cell.size) < 1e-9):
        tag(curves.sketchCircles.addByCenterRadius(point(cell.center), cell.size / 2), 'cell')
    elif cell.shape in ('smooth_noise', 'reaction_diffusion', 'directional_fibers', 'topographic', 'gyroid') or cell.shape == 'voronoi' and cell.corner_radius > 0:
        first = previous = None
        for i, edge in enumerate(cell.contour):
            start = previous or point(edge.start)
            end = first if i == len(cell.contour)-1 else point(edge.end)
            if edge.center is None:
                curve = curves.sketchLines.addByTwoPoints(start, end)
            else:
                curve = curves.sketchArcs.addByThreePoints(start, point(edge.at(.5)), end)
            tag(curve, 'cell')
            # Fusion sketch arcs are always CCW, even when the supplied three
            # points describe a clockwise concave turn of an organic contour.
            backwards = edge.center is not None and edge.sweep < 0
            first = first or (curve.endSketchPoint if backwards else curve.startSketchPoint)
            previous = curve.startSketchPoint if backwards else curve.endSketchPoint
    elif cell.shape in POLYGON_SHAPES:
        add_polygon(sketch, cell.vertices, 'cell')
    elif cell.shape == 'ellipse':
        tag(curves.sketchEllipses.add(point(cell.center), point(cell.at((cell.length / 2, 0))),
                                     point(cell.at((0, cell.size / 2)))), 'cell')
    else:
        a, b = cell.spine
        r = cell.size / 2
        dx, dy = -math.sin(cell.angle) * r, math.cos(cell.angle) * r
        top_a, top_b = (a[0] + dx, a[1] + dy), (b[0] + dx, b[1] + dy)
        bottom_a, bottom_b = (a[0] - dx, a[1] - dy), (b[0] - dx, b[1] - dy)
        top = tag(curves.sketchLines.addByTwoPoints(point(top_a), point(top_b)), 'cell')
        bottom = tag(curves.sketchLines.addByTwoPoints(point(bottom_b), point(bottom_a)), 'cell')
        tag(curves.sketchArcs.addByCenterStartSweep(point(a), top.startSketchPoint, math.pi), 'cell')
        tag(curves.sketchArcs.addByCenterStartSweep(point(b), bottom.startSketchPoint, math.pi), 'cell')


def sketch_transform(source, target):
    """Transform sketch-space geometry without relying on global assembly coordinates."""
    origin = target.modelToSketchSpace(source.sketchToModelSpace(point((0, 0))))
    x = target.modelToSketchSpace(source.sketchToModelSpace(point((1, 0))))
    y = target.modelToSketchSpace(source.sketchToModelSpace(point((0, 1))))
    z = target.modelToSketchSpace(source.sketchToModelSpace(adsk.core.Point3D.create(0, 0, 1)))
    transform = adsk.core.Matrix3D.create()
    transform.setWithCoordinateSystem(origin, origin.vectorTo(x), origin.vectorTo(y), origin.vectorTo(z))
    return transform


def copy_curve(sketch, geometry, role):
    curves = sketch.sketchCurves
    if isinstance(geometry, adsk.core.Line3D):
        result = curves.sketchLines.addByTwoPoints(geometry.startPoint, geometry.endPoint)
    elif isinstance(geometry, adsk.core.Circle3D):
        result = curves.sketchCircles.addByCenterRadius(geometry.center, geometry.radius)
    elif isinstance(geometry, adsk.core.Arc3D):
        sweep = geometry.endAngle - geometry.startAngle
        # Both sketches have matching plane normals; using the geometry normal also
        # supports a redefined source sketch whose in-plane frame is mirrored.
        if geometry.normal.z < 0:
            sweep = -sweep
        result = curves.sketchArcs.addByCenterStartSweep(geometry.center, geometry.startPoint, sweep)
    elif isinstance(geometry, adsk.core.Ellipse3D):
        major = geometry.center.copy()
        direction = geometry.majorAxis.copy()
        direction.scaleBy(geometry.majorRadius)
        major.translateBy(direction)
        minor = geometry.center.copy()
        direction = geometry.normal.crossProduct(geometry.majorAxis)
        direction.scaleBy(geometry.minorRadius)
        minor.translateBy(direction)
        result = curves.sketchEllipses.add(geometry.center, major, minor)
    elif isinstance(geometry, adsk.core.EllipticalArc3D):
        major = geometry.majorAxis.copy()
        major.scaleBy(geometry.majorRadius)
        minor = geometry.normal.crossProduct(geometry.majorAxis)
        minor.scaleBy(geometry.minorRadius)
        result = curves.sketchEllipticalArcs.addByAngle(geometry.center, major, minor,
                    geometry.startAngle, geometry.endAngle - geometry.startAngle)
    else:
        nurbs = geometry if isinstance(geometry, adsk.core.NurbsCurve3D) else geometry.asNurbsCurve
        result = curves.sketchFixedSplines.addByNurbsCurve(nurbs)
    if not result:
        raise ValueError('Unable to copy the profile boundary.')
    return tag(result, role)


def add_boundary(source, sketch, config, region):
    if isinstance(source, adsk.fusion.BRepFace):
        for loop in source.loops:
            for edge in loop.edges:
                for curve in sketch.project(edge):
                    if isinstance(curve, adsk.fusion.SketchCurve):
                        tag(curve, 'outer' if loop.isOuter else 'void')
    elif isinstance(source, adsk.fusion.Profile):
        transform = sketch_transform(source.parentSketch, sketch)
        for loop in source.profileLoops:
            for curve in loop.profileCurves:
                geometry = curve.geometry.copy()
                geometry.transformBy(transform)
                copy_curve(sketch, geometry, 'outer' if loop.isOuter else 'void')
    elif config['boundary'] == 'circle':
        tag(sketch.sketchCurves.sketchCircles.addByCenterRadius(point((0, 0)), config['width'] / 2), 'outer')
    else:
        add_polygon(sketch, region.loops[0].points, 'outer')


def selected_profiles(sketch, material, clipped=False):
    wanted = 'outer' if material == 'panel' else 'cell'
    profiles = adsk.core.ObjectCollection.create()
    for profile in sketch.profiles:
        if material == 'cells':
            if clipped:
                outer = next(loop for loop in profile.profileLoops if loop.isOuter)
                if all((a := c.sketchEntity.attributes.itemByName(ATTRIBUTE_GROUP, 'role'))
                       and a.value == 'clip_void' for c in outer.profileCurves):
                    continue
            profiles.add(profile)
            continue
        # The panel encloses at least one generated cell. Single-loop profiles
        # are cell interiors or original voids, so no entity tracking is needed.
        if not clipped and profile.profileLoops.count == 1:
            continue
        outer = next(loop for loop in profile.profileLoops if loop.isOuter)
        roles = []
        for curve in outer.profileCurves:
            attribute = curve.sketchEntity.attributes.itemByName(ATTRIBUTE_GROUP, 'role')
            roles.append(attribute.value if attribute else '')
        if roles and all(role == wanted for role in roles):
            profiles.add(profile)
    if not profiles.count:
        raise ValueError('Fusion could not create closed profiles for the selected result.')
    return profiles


def extent(config, side):
    kind = config['extent' + side]
    if kind == 'all':
        return adsk.fusion.ThroughAllExtentDefinition.create()
    if kind == 'object':
        return adsk.fusion.ToEntityExtentDefinition.create(config['target' + side], False, value(config['object_offset' + side]))
    return adsk.fusion.DistanceExtentDefinition.create(value(config['distance' + side]))


def extrude(component, profiles, config):
    operations = {
        'join': adsk.fusion.FeatureOperations.JoinFeatureOperation,
        'cut': adsk.fusion.FeatureOperations.CutFeatureOperation,
        'intersect': adsk.fusion.FeatureOperations.IntersectFeatureOperation,
        'body': adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        'component': adsk.fusion.FeatureOperations.NewComponentFeatureOperation,
    }
    extrudes = component.features.extrudeFeatures
    data = extrudes.createInput(profiles, operations[config['operation']])
    if not data:
        raise ValueError('Unable to initialize Extrude.')
    data.startExtent = adsk.fusion.OffsetStartDefinition.create(value(config['start']))
    if config['direction'] == 'symmetric':
        ok = data.setSymmetricExtent(value(config['distance1']), True, value(config['taper1']))
    elif config['direction'] == 'two':
        ok = data.setTwoSidesExtent(extent(config, '1'), extent(config, '2'),
                                    value(config['taper1']), value(config['taper2']))
    else:
        direction = (adsk.fusion.ExtentDirections.NegativeExtentDirection if config['reverse']
                     else adsk.fusion.ExtentDirections.PositiveExtentDirection)
        ok = data.setOneSideExtent(extent(config, '1'), direction, value(config['taper1']))
    if not ok:
        raise ValueError('Fusion rejected the Direction or Extent settings.')
    if config['operation'] in ('cut', 'intersect'):
        participants = [native(body) for body in config['bodies']]
        if not participants:
            raise ValueError('Select bodies for Cut or Intersect.')
        if any(body.parentComponent != component for body in participants):
            raise ValueError('The selected bodies must belong to the profile component.')
        data.participantBodies = participants
    feature = extrudes.add(data)
    if not feature:
        raise ValueError('Fusion could not create the Extrude feature.')
    try:
        if feature.healthState == adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState:
            raise ValueError(feature.errorOrWarningMessage or 'Extrude failed.')
        operation_name = {'join': 'Join', 'cut': 'Cut', 'intersect': 'Intersect',
                          'body': 'New Body', 'component': 'New Component'}[config['operation']]
        feature.name = 'Perforation (' + operation_name + ')'
        return feature
    except Exception:
        if feature.isValid:
            feature.deleteMe()
        raise


def sketch_reference_plane(sketch):
    """Resolve a face-backed sketch at its historical position, then restore it.

    Fusion raises when reading referencePlane for a BRepFace after the sketch.
    Keep the caller's exact marker (including an edit rollback), even on failure.
    The returned native support remains usable at the restored position.
    """
    try:
        return sketch.referencePlane
    except RuntimeError:
        if not sketch.isParametric:
            raise
        timeline = sketch.parentComponent.parentDesign.timeline
        marker = timeline.markerPosition
        try:
            if not sketch.timelineObject.rollTo(True):
                raise ValueError('Unable to resolve the sketch support face.')
            return sketch.referencePlane
        finally:
            timeline.markerPosition = marker


def source_support_body(source):
    """Infer Objects from a face or a profile sketched directly on a solid face."""
    selected = source
    source = native(source)
    support = (sketch_reference_plane(source.parentSketch)
               if isinstance(source, adsk.fusion.Profile) else source)
    if not isinstance(support, adsk.fusion.BRepFace):
        return None
    body = native(support.body)
    if selected.assemblyContext:
        return body.createForAssemblyContext(selected.assemblyContext)
    return body


def new_source_sketch(source):
    """Create an empty sketch with exactly the frame used by final geometry."""
    source = native(source)
    component = source_component(source)
    if isinstance(source, adsk.fusion.Profile):
        if not source.isOnSketchPlane:
            raise ValueError('Select a profile on the sketch plane.')
        plane = sketch_reference_plane(source.parentSketch)
        if not plane:
            raise ValueError('This profile has no reference plane. Select a planar face or construction plane.')
    else:
        plane = source
    sketch = component.sketches.addWithoutEdges(plane)
    if not sketch:
        raise ValueError('Unable to create a sketch on the selected plane.')
    return sketch


def sketch_metadata(settings, config):
    """Frozen result snapshot; live references must never enter sketch JSON."""
    result = {key: val for key, val in settings.__dict__.items() if key not in ('path_samples', 'guide1', 'guide2')}
    result.update({key: val for key, val in config.items()
                   if key not in ('bodies', 'target1', 'target2', 'center_point',
                                  'guide1', 'guide2', 'path', '_expressions')})
    return result


def build(source, settings, config, cache=None):
    """Must run within a Fusion command transaction (execute/executePreview)."""
    if isinstance(source, (tuple, list)):
        from . import multi_region
        selected, _ = multi_region.validate(source, config)
        if len(selected) > 1:
            return multi_region.build(selected, settings, config, cache)
        source = selected[0]
    source = native(source)
    from . import cylindrical, surface
    if config.get('surface'):
        return surface.build(source, settings, config)
    if cylindrical.is_cylinder(source):
        return cylindrical.build(source, settings, config)
    component = source_component(source)
    sketch = new_source_sketch(source)
    feature = None
    try:
        sketch.name = 'Perforation - ' + settings.shape.title()
        region = get_region(source, sketch, config)
        frame = sketch_frame(sketch)
        layout = layout_settings(settings, config, region, frame, component)
        candidates = cache.resolve(region, layout, frame) if cache is not None else None
        clipped = None
        if settings.clip_boundary:
            from . import clipping
            original = clipping.source_body(source, sketch, config, region)
            trimmed = clipping.inset_body(source, original, settings.margin)
            trimmed = clipping.apply_spread(trimmed, region, layout)
            clipped = clipping.layout(original, trimmed, region, layout, candidates)
            cells = clipped.cells
        else:
            cells = generate(region, layout) if candidates is None else candidates
        # project(edge) returns an empty collection while compute is deferred,
        # although the curves appear later. Project and tag the boundary first.
        if config['material'] == 'panel' and clipped is None:
            add_boundary(source, sketch, config, region)
        sketch.isComputeDeferred = True
        try:
            if clipped is not None:
                clipping.draw(sketch, clipped, config['material'])
            else:
                for cell in cells:
                    add_cell(sketch, cell)
        finally:
            sketch.isComputeDeferred = False
        profiles = selected_profiles(sketch, config['material'], settings.clip_boundary)
        if not settings.clip_boundary and config['material'] == 'cells' and profiles.count != len(cells):
            raise ValueError('The profile count differs from the hole count. Increase Web Thickness.')
        metadata = sketch_metadata(layout, config)
        sketch.attributes.add(ATTRIBUTE_GROUP, 'settings', json.dumps(metadata, ensure_ascii=False))
        if config['result'] == 'extrude':
            feature = extrude(component, profiles, config)
            sketch.isVisible = False
        else:
            sketch.isVisible = True
        return sketch, feature, len(cells)
    except Exception:
        # The command transaction also rolls back. This removes failed-preview
        # geometry immediately instead of leaving it visible until the next event.
        if feature and feature.isValid:
            feature.deleteMe()
        if sketch.isValid:
            sketch.deleteMe()
        raise
