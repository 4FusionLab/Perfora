# SPDX-License-Identifier: GPL-3.0-only
"""Exact planar clipping with temporary BRep; no persistent Boolean features."""
from dataclasses import dataclass
import math

import adsk.core
import adsk.fusion

from . import model
from .geometry import Loop, Region, POLYGON_SHAPES, edges, fits, generate, overlaps, point_segment_distance, stitch


def polygon_curves(points):
    return [adsk.core.Line3D.create(model.point(a), model.point(b)) for a, b in edges(points)]


def cell_curves(cell):
    if cell.shape in POLYGON_SHAPES:
        return polygon_curves(cell.vertices)
    if cell.shape == 'ellipse':
        return [adsk.core.Ellipse3D.create(model.point(cell.center), adsk.core.Vector3D.create(0, 0, 1),
                adsk.core.Vector3D.create(math.cos(cell.angle), math.sin(cell.angle), 0), cell.length / 2, cell.size / 2)]
    r = cell.size / 2
    if cell.shape == 'circle' or abs(cell.length - cell.size) < 1e-9:
        return [adsk.core.Circle3D.createByCenter(model.point(cell.center),
                                                adsk.core.Vector3D.create(0, 0, 1), r)]
    h = (cell.length - cell.size) / 2
    at = lambda x, y: model.point(cell.at((x, y)))
    return [adsk.core.Line3D.create(at(-h, r), at(h, r)),
            adsk.core.Arc3D.createByThreePoints(at(h, r), at(h + r, 0), at(h, -r)),
            adsk.core.Line3D.create(at(h, -r), at(-h, -r)),
            adsk.core.Arc3D.createByThreePoints(at(-h, -r), at(-h - r, 0), at(-h, r))]


def sheet(loops):
    manager = adsk.fusion.TemporaryBRepManager.get()
    wires = []
    for curves in loops:
        wire, _ = manager.createWireFromCurves(curves)
        if not wire:
            raise ValueError('Unable to close the trim boundary.')
        wires.append(wire)
    body = manager.createFaceFromPlanarWires(wires)
    if not body:
        raise ValueError('Unable to create the trim region. Check Edge Offset.')
    return body


def body_loops(body):
    return [(tuple(edge.geometry for edge in loop.edges), loop.isOuter)
            for face in body.faces for loop in face.loops]


def body_region(body):
    return Region(tuple(Loop(stitch([model.strokes(curve.evaluator, lambda p: p) for curve in curves],
                                   model.TOLERANCE * 2), outer)
                        for curves, outer in body_loops(body)), model.TOLERANCE)


def source_body(source, sketch, config, region):
    if isinstance(source, adsk.fusion.BRepFace):
        manager = adsk.fusion.TemporaryBRepManager.get()
        body = manager.copy(source)
        origin = sketch.sketchToModelSpace(model.point((0, 0)))
        x = sketch.sketchToModelSpace(model.point((1, 0)))
        y = sketch.sketchToModelSpace(model.point((0, 1)))
        u, v = origin.vectorTo(x), origin.vectorTo(y)
        frame = adsk.core.Matrix3D.create()
        frame.setWithCoordinateSystem(origin, u, v, u.crossProduct(v))
        frame.invert()
        if not manager.transform(body, frame):
            raise ValueError('Unable to transform the face to the trim plane.')
        return body
    if isinstance(source, adsk.fusion.Profile):
        transform = model.sketch_transform(source.parentSketch, sketch)
        loops = []
        for loop in source.profileLoops:
            curves = []
            for entry in loop.profileCurves:
                curve = entry.geometry.copy()
                curve.transformBy(transform)
                curves.append(curve)
            loops.append(curves)
        return sheet(loops)
    if config['boundary'] == 'circle':
        return sheet([[adsk.core.Circle3D.createByCenter(model.point((0, 0)),
                      adsk.core.Vector3D.create(0, 0, 1), config['width'] / 2)]])
    return sheet([polygon_curves(region.loops[0].points)])


def inset_body(source, original, margin):
    if margin <= 1e-9:
        return original
    # Offset constraints live only in this scratch sketch, deleted immediately.
    scratch = model.new_source_sketch(source)
    try:
        wires = []
        for geometries, _ in body_loops(original):
            curves = [model.copy_curve(scratch, g, 'cell') for g in geometries]
            evaluator = curves[0].geometry.evaluator
            ok, start, end = evaluator.getParameterExtents()
            if not ok:
                raise ValueError('Unable to determine the Edge Offset direction.')
            parameter = (start + end) / 2
            ok_p, midpoint = evaluator.getPointAtParameter(parameter)
            ok_t, tangent = evaluator.getFirstDerivative(parameter)
            if not (ok_p and ok_t) or tangent.length < 1e-12:
                raise ValueError('Unable to determine the Edge Offset direction.')
            step = min(margin * 0.01, 0.0001) / tangent.length
            probe = adsk.core.Point3D.create(midpoint.x + tangent.y * step,
                                            midpoint.y - tangent.x * step, 0)
            right_inside = any(f.isPointOnFace(probe, 1e-7) for f in original.faces)
            data = scratch.geometricConstraints.createOffsetInput(
                curves, adsk.core.ValueInput.createByReal(margin if right_inside else -margin))
            data.isTopologyMatched = False
            try:
                constraint = scratch.geometricConstraints.addOffset2(data)
            except RuntimeError as error:
                raise ValueError('Unable to offset the boundary. Reduce Edge Offset.') from error
            if not constraint or not constraint.childCurves:
                raise ValueError('Edge Offset leaves no region for perforation.')
            wires.append([c.geometry for c in constraint.childCurves])
        result = sheet(wires)
        # An invalid oversized inward offset can turn through itself. Never
        # silently accept an expanded or inverted trimming region.
        if result.area >= original.area:
            raise ValueError('Edge Offset is too large for this region.')
        original_region = body_region(original)
        original_segments = original_region.segments
        for loop in body_region(result).loops:
            for p in loop.points:
                if (not original_region.contains(p)
                        or min(point_segment_distance(p, a, b) for a, b in original_segments)
                        < margin - model.TOLERANCE * 3):
                    raise ValueError('Edge Offset creates a degenerate or self-intersecting boundary.')
        return result
    finally:
        scratch.deleteMe()


@dataclass
class Layout:
    cells: list
    whole: list
    partial_loops: list
    panel_loops: list

    def outlines(self, region, panel):
        from .geometry import outline_coordinates
        coordinates = outline_coordinates(self.whole, region, False)
        loops = self.panel_loops if panel else self.partial_loops
        for curves, _ in loops:
            for curve in curves:
                points = model.strokes(curve.evaluator, lambda p: p)
                for a, b in zip(points, points[1:]):
                    coordinates.extend((a[0], a[1], 0, b[0], b[1], 0))
        return coordinates


def layout(original, trimmed, region, settings):
    manager = adsk.fusion.TemporaryBRepManager.get()
    trim_region = body_region(trimmed)
    trim_segments = trim_region.segments
    cells, whole, partial = [], [], []
    panel = manager.copy(original)
    for cell in generate(region, settings):
        if fits(cell, trim_region, trim_segments, 0):
            cells.append(cell)
            whole.append(cell)
        elif overlaps(cell, trim_region, trim_segments):
            cut = sheet([cell_curves(cell)])
            if not manager.booleanOperation(cut, trimmed, adsk.fusion.BooleanTypes.IntersectionBooleanType):
                raise ValueError('Fusion could not trim the hole to the boundary.')
            if cut.faces.count and cut.area > 1e-10:
                cells.append(cell)
                partial.extend(body_loops(cut))
                if not manager.booleanOperation(panel, cut, adsk.fusion.BooleanTypes.DifferenceBooleanType):
                    raise ValueError('Fusion could not create the panel boundary.')
    if not cells:
        raise ValueError('No holes remain after applying Edge Offset.')
    return Layout(cells, whole, partial, body_loops(panel))


def draw(sketch, result, material):
    if material == 'panel':
        for curves, outer in result.panel_loops:
            for curve in curves:
                model.copy_curve(sketch, curve, 'outer' if outer else 'void')
    else:
        for curves, outer in result.partial_loops:
            for curve in curves:
                model.copy_curve(sketch, curve, 'cell' if outer else 'clip_void')
    for cell in result.whole:
        model.add_cell(sketch, cell)
