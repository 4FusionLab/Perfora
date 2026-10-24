# SPDX-License-Identifier: GPL-3.0-only
"""Fusion adapter for fixed radial cuts on one rectangular cylindrical face."""
from dataclasses import dataclass
import json
import math

import adsk.core
import adsk.fusion

from . import clipping, model, solid
from . import cylindrical_geometry as geometry


def is_cylinder(source):
    return isinstance(source, adsk.fusion.BRepFace) and isinstance(source.geometry, adsk.core.Cylinder)


@dataclass(frozen=True)
class Frame:
    region: geometry.CylinderRegion
    origin: tuple
    axis: tuple
    u: tuple
    v: tuple

    def basis(self, angle):
        c, s = math.cos(angle), math.sin(angle)
        radial = tuple(c * a + s * b for a, b in zip(self.u, self.v))
        tangent = tuple(-s * a + c * b for a, b in zip(self.u, self.v))
        return radial, tangent

    def point(self, angle, axial, x=0., radial_distance=None):
        radial, tangent = self.basis(angle)
        r = self.region.radius if radial_distance is None else radial_distance
        return tuple(self.origin[i] + axial * self.axis[i] + r * radial[i] + x * tangent[i] for i in range(3))


def frame(source):
    source = model.native(source)
    if not is_cylinder(source):
        raise ValueError('Select a cylindrical face for Radial Cut.')
    if not source.body.isSolid:
        raise ValueError('Radial Cut requires a solid body.')
    cylinder = source.geometry
    axis, origin = cylinder.axis.copy(), cylinder.origin
    axis.normalize()
    evaluator = source.evaluator
    bounds = evaluator.parametricRange()
    low, high = bounds.minPoint.asArray(), bounds.maxPoint.asArray()

    def at(a, b):
        ok, p = evaluator.getPointAtParameter(adsk.core.Point2D.create(a, b))
        if not ok:
            raise ValueError('Unable to evaluate the cylindrical face bounds.')
        return p

    p00, p10, p01 = at(*low), at(high[0], low[1]), at(low[0], high[1])
    axial_u = abs(p00.vectorTo(p10).dotProduct(axis)) > abs(p00.vectorTo(p01).dotProduct(axis))
    ci = 1 if axial_u else 0
    z0 = origin.vectorTo(p00).dotProduct(axis)
    z1 = origin.vectorTo(p10 if axial_u else p01).dotProduct(axis)
    height = abs(z1 - z0)
    base = origin.copy()
    shift = axis.copy()
    shift.scaleBy(min(z0, z1))
    base.translateBy(shift)

    def radial(p):
        delta = origin.vectorTo(p)
        along = axis.copy()
        along.scaleBy(delta.dotProduct(axis))
        delta.subtract(along)
        delta.normalize()
        return delta

    sample = list(low)
    sample[ci] += (high[ci] - low[ci]) * .001
    first, near = radial(p00), radial(at(*sample))
    delta = math.atan2(first.crossProduct(near).dotProduct(axis), first.dotProduct(near))
    sweep = abs(delta) * 1000
    if abs(sweep - math.tau) < 1e-7:
        sweep = math.tau
    if delta < 0:
        endpoint = list(low)
        endpoint[ci] = high[ci]
        first = radial(at(*endpoint))
    v = axis.crossProduct(first)
    expected = cylinder.radius * height * sweep
    if height <= 1e-8 or not 0 < sweep <= math.tau + 1e-7 or abs(source.area - expected) > max(1e-6, expected * 1e-7):
        raise ValueError('Select a complete cylinder or a rectangular cylindrical sector without openings or irregular trims.')
    ok, normal = evaluator.getNormalAtPoint(source.pointOnFace)
    if not ok:
        raise ValueError('Unable to determine the cylinder material side.')
    inward = normal.dotProduct(radial(source.pointOnFace)) > 0
    return Frame(geometry.CylinderRegion(cylinder.radius, height, sweep, inward),
                 tuple(base.asArray()), tuple(axis.asArray()), tuple(first.asArray()), tuple(v.asArray()))


def prepare(source, settings, config):
    if config.get('result') != 'extrude' or config.get('operation') != 'cut':
        raise ValueError('Cylindrical faces support fixed Radial Cut only. Sketch and Feature are not available yet.')
    f = frame(source)
    holes = geometry.generate(f.region, settings, config['cut_depth'], config['cylinder_start'],
                              config['cylinder_sweep'], config['axial_start'], config['axial_length'])
    return f, holes


def local_coordinates(f, cell):
    """Sample one exact local tool section and its cylinder intersection."""
    local = []
    radius = geometry.enclosing_radius(cell)
    # Bound the extra chord error introduced by projecting even a straight edge
    # onto the cylinder. First stroke analytic tool curves, then refine their X
    # intervals using the maximum second derivative of sqrt(R^2 - x^2).
    tolerance = model.TOLERANCE / 2
    step = math.sqrt(8 * tolerance * f.region.radius * (1 - (radius / f.region.radius) ** 2) ** 1.5)
    for curve in clipping.cell_curves(cell):
        evaluator = curve.evaluator
        ok, start, end = evaluator.getParameterExtents()
        ok_strokes, points = evaluator.getStrokes(start, end, tolerance / 4)
        if not ok or not ok_strokes:
            raise ValueError('Unable to display the radial tool contour.')
        for a, b in zip(points, points[1:]):
            count = max(1, math.ceil(abs(b.x - a.x) / step))
            parameters = None
            if count > 1 and not isinstance(curve, adsk.core.Line3D):
                ok_a, pa = evaluator.getParameterAtPoint(a)
                ok_b, pb = evaluator.getParameterAtPoint(b)
                if not ok_a or not ok_b:
                    raise ValueError('Unable to refine the radial tool contour.')
                parameters = pa, pb
            for i in range(count):
                for t in (i/count, (i+1)/count):
                    x, y = a.x + (b.x-a.x)*t, a.y + (b.y-a.y)*t
                    if parameters is not None:
                        ok_p, p = evaluator.getPointAtParameter(parameters[0] + (parameters[1]-parameters[0])*t)
                        if not ok_p:
                            raise ValueError('Unable to refine the radial tool contour.')
                        x, y = p.x, p.y
                    local.append((x, y, math.sqrt(max(0., f.region.radius ** 2 - x ** 2))))
    return local


def coordinates(f, settings, holes):
    """Sample the actual tool/cylinder intersection, rather than a wrapped shape."""
    result, sections = [], {}
    for hole in holes:
        cell = geometry.tool_cell(settings, hole)
        if cell not in sections:
            sections[cell] = local_coordinates(f, cell)
        radial, tangent = f.basis(hole.angle)
        for x, y, r in sections[cell]:
            result.extend(f.origin[j] + (hole.axial+y)*f.axis[j] + r*radial[j] + x*tangent[j] for j in range(3))
    return result


def tools(f, settings, config, holes):
    manager = adsk.fusion.TemporaryBRepManager.get()
    depth = config['cut_depth']
    result, templates = [], {}
    for hole in holes:
        cell = geometry.tool_cell(settings, hole)
        if cell not in templates:
            radius = geometry.enclosing_radius(cell)
            sag = f.region.radius - math.sqrt(f.region.radius ** 2 - radius ** 2)
            lead = sag + 1e-4
            start, end = ((-depth, lead) if f.region.inward else (-lead, depth))
            section = clipping.sheet([clipping.cell_curves(cell)])
            templates[cell] = solid.extrude([section], start, end)
        radial, tangent = f.basis(hole.angle)
        matrix = adsk.core.Matrix3D.create()
        matrix.setWithCoordinateSystem(adsk.core.Point3D.create(*f.point(hole.angle, hole.axial)),
            adsk.core.Vector3D.create(*tangent), adsk.core.Vector3D.create(*f.axis),
            adsk.core.Vector3D.create(*radial))
        tool = manager.copy(templates[cell])
        if not manager.transform(tool, matrix):
            raise ValueError('Unable to position a radial cutting tool.')
        result.append(tool)
    return result


def build(source, settings, config):
    """One native Combine Cut, with fixed tool geometry in an owned Base Feature."""
    source = model.native(source)
    component = model.source_component(source)
    if component.parentDesign.designType != adsk.fusion.DesignTypes.ParametricDesignType:
        raise ValueError('Radial Cut currently requires Capture Design History.')
    f, holes = prepare(source, settings, config)
    temporary = tools(f, settings, config, holes)
    target = source.body
    base = combine = None
    try:
        base = component.features.baseFeatures.add()
        base.name = 'Perfora Radial Tools'
        if not base.startEdit():
            raise ValueError('Unable to create radial cutting tools.')
        try:
            for tool in temporary:
                if not component.bRepBodies.add(tool, base):
                    raise ValueError('Unable to add a radial cutting tool.')
        finally:
            base.finishEdit()
        collection = adsk.core.ObjectCollection.create()
        for body in base.bodies:
            collection.add(body)
        data = component.features.combineFeatures.createInput(target, collection)
        data.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
        combine = component.features.combineFeatures.add(data)
        if not combine or combine.healthState != adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState:
            raise ValueError(combine.errorOrWarningMessage if combine else 'Unable to create Radial Cut.')
        combine.name = 'Perforation (Radial Cut)'
        combine.attributes.add(model.ATTRIBUTE_GROUP, 'cylindrical_settings', json.dumps(dict(
            schema=1, settings=settings.__dict__, config={k: config[k] for k in
            ('cut_depth', 'cylinder_start', 'cylinder_sweep', 'axial_start', 'axial_length')})))
        return None, combine, len(holes)
    except Exception:
        for item in (combine, base):
            if item and item.isValid:
                item.deleteMe()
        raise
