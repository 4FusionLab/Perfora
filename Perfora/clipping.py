# SPDX-License-Identifier: GPL-3.0-only
"""Exact planar clipping with temporary BRep; no persistent Boolean features."""
import math

import adsk.core
import adsk.fusion

from . import model
from .geometry import (Loop, Region, ContourEdge, POLYGON_SHAPES, ORGANIC_FIELDS, ORGANIC_SHAPES, dist, edges, fits, generate,
                       overlaps, placement_center, point_segment_distance, round_contour, stitch)


def polygon_curves(points):
    return [adsk.core.Line3D.create(model.point(a), model.point(b)) for a, b in edges(points)]


def cell_curves(cell):
    if cell.shape in ORGANIC_FIELDS or cell.shape == 'voronoi' and cell.corner_radius > 0:
        return contour_curves(cell.contour)
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


def contour_curves(contour):
    result=[]
    for edge in contour:
        if edge.center is None:
            curve=adsk.core.Line3D.create(model.point(edge.start),model.point(edge.end))
        elif abs(abs(edge.sweep)-math.tau)<1e-8:
            curve=adsk.core.Circle3D.createByCenter(model.point(edge.center),
                adsk.core.Vector3D.create(0,0,1),dist(edge.start,edge.center))
        else:
            curve=adsk.core.Arc3D.createByThreePoints(model.point(edge.start),model.point(edge.at(.5)),model.point(edge.end))
        result.append(curve)
    return result


def loop_contour(loop):
    """Read connected, oriented analytic geometry, independent of face normal."""
    result=[]
    coedge=loop.coEdges.item(0)
    for _ in range(loop.coEdges.count):
        edge=coedge.edge
        curve=edge.geometry
        center=None
        sweep=0.
        if isinstance(curve,adsk.core.Line3D):
            start,end=curve.startPoint,curve.endPoint
        elif isinstance(curve,adsk.core.Arc3D):
            start,end=curve.startPoint,curve.endPoint
            center=tuple(curve.center.asArray()[:2])
            sweep=(curve.endAngle-curve.startAngle)*(1 if curve.normal.z>0 else -1)
        elif isinstance(curve,adsk.core.Circle3D):
            center=tuple(curve.center.asArray()[:2])
            start=end=adsk.core.Point3D.create(center[0]+curve.radius,center[1],0)
            sweep=math.tau*(1 if curve.normal.z>0 else -1)
        else:
            return None  # Keep spline/elliptic source boundaries exact.
        start,end=tuple(start.asArray()[:2]),tuple(end.asArray()[:2])
        if coedge.isOpposedToEdge != edge.isParamReversed:
            start,end,sweep=end,start,-sweep
        result.append(ContourEdge(start,end,center,sweep))
        coedge=coedge.next
    area=sum(e.start[0]*e.end[1]-e.end[0]*e.start[1] +
             (dist(e.start,e.center)**2*(e.sweep-math.sin(e.sweep)) if e.center is not None else 0)
             for e in result)/2
    if (area>0) != loop.isOuter:
        result=[ContourEdge(e.end,e.start,e.center,-e.sweep) for e in reversed(result)]
    if any(dist(e.end,result[(i+1)%len(result)].start)>model.TOLERANCE for i,e in enumerate(result)):
        raise ValueError('Unable to order the trim boundary for corner rounding.')
    return tuple(result)


def rounded_body(body,radius):
    loops=[]
    for face in body.faces:
        for loop in face.loops:
            contour=loop_contour(loop) if loop.isOuter else None
            loops.append(contour_curves(round_contour(contour,radius)) if contour is not None
                         else [edge.geometry for edge in loop.edges])
    result=sheet(loops)
    manager=adsk.fusion.TemporaryBRepManager.get()
    outside=manager.copy(result)
    if (not manager.booleanOperation(outside,body,adsk.fusion.BooleanTypes.DifferenceBooleanType)
            or outside.area>1e-8):
        raise ValueError('Boundary corner rounding would reduce clearance. Reduce Corner Radius.')
    return result


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


def apply_spread(body, region, settings):
    if settings.spread_radius <= 0:
        return body
    radius = settings.spread_radius - settings.margin
    if radius <= model.TOLERANCE:
        raise ValueError('Spread Radius must be larger than Edge Offset.')
    center = placement_center(region, settings)
    disk = sheet([[adsk.core.Circle3D.createByCenter(model.point(center),
                  adsk.core.Vector3D.create(0, 0, 1), radius)]])
    manager = adsk.fusion.TemporaryBRepManager.get()
    result = manager.copy(body)
    if not manager.booleanOperation(result, disk, adsk.fusion.BooleanTypes.IntersectionBooleanType):
        raise ValueError('Unable to limit the pattern to Spread Radius.')
    if not result.faces.count or result.area <= 1e-10:
        raise ValueError('Spread Radius leaves no region for perforation.')
    return result


def inset_body(source, original, margin, scratch=None):
    """Offset temporary wires without editing the parametric design.

    Keep source/scratch arguments for callers and existing Feature documents.
    Editing an owned face-supported sketch during CustomFeature compute can
    invalidate the target of its downstream Combine after an upstream resize.
    """
    if margin <= 1e-9:
        return original
    manager = adsk.fusion.TemporaryBRepManager.get()
    wires = []
    for geometries, _ in body_loops(original):
        wire_body, _ = manager.createWireFromCurves(list(geometries))
        if not wire_body or wire_body.wires.count != 1:
            raise ValueError('Unable to close the Edge Offset boundary.')
        wire = wire_body.wires.item(0)
        coedge = wire.coEdges.item(0)
        edge = coedge.edge
        evaluator = edge.geometry.evaluator
        ok, start, end = evaluator.getParameterExtents()
        if not ok:
            raise ValueError('Unable to determine the Edge Offset direction.')
        parameter = (start + end) / 2
        ok_p, midpoint = evaluator.getPointAtParameter(parameter)
        ok_t, tangent = evaluator.getFirstDerivative(parameter)
        if not (ok_p and ok_t) or tangent.length < 1e-12:
            raise ValueError('Unable to determine the Edge Offset direction.')
        # offsetPlanarWire uses wire traversal, which can oppose curve geometry.
        if coedge.isOpposedToEdge != edge.isParamReversed:
            tangent.scaleBy(-1)
        step = min(margin * 0.01, 0.0001) / tangent.length
        probe = adsk.core.Point3D.create(midpoint.x + tangent.y * step,
                                        midpoint.y - tangent.x * step, 0)
        right_inside = any(f.isPointOnFace(probe, 1e-7) for f in original.faces)
        try:
            offset = wire.offsetPlanarWire(adsk.core.Vector3D.create(0, 0, 1),
                margin if right_inside else -margin,
                adsk.fusion.OffsetCornerTypes.ExtendedOffsetCornerType)
        except RuntimeError as error:
            raise ValueError('Unable to offset the boundary. Reduce Edge Offset.') from error
        if not offset or not offset.wires.count:
            raise ValueError('Edge Offset leaves no region for perforation.')
        # A narrow region can split into several wires; preserve every island.
        wires.extend([[e.geometry.copy() for e in w.edges] for w in offset.wires])
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


class Layout:
    def __init__(self, cells, whole, partial_loops, original, partial_bodies):
        self.cells = cells
        self.whole = whole
        self.partial_loops = partial_loops
        self.partial_bodies = tuple(partial_bodies)
        # The caller owns this temporary source and treats it as read-only.
        self._original = original
        self._panel_loops = None
        self._panel_body = None
        self.panel_builds = 0
        self.panel_subtractions = 0

    @property
    def panel_loops(self):
        if self._panel_loops is None:
            manager = adsk.fusion.TemporaryBRepManager.get()
            panel = manager.copy(self._original)
            for cut in self.partial_bodies:
                self.panel_subtractions += 1
                if not manager.booleanOperation(panel, cut, adsk.fusion.BooleanTypes.DifferenceBooleanType):
                    raise ValueError('Fusion could not create the panel boundary.')
            # Publish only a complete panel. A failed Boolean may mutate its
            # target, so a retry must start from a fresh copy of the source.
            loops = body_loops(panel)
            self._panel_body = panel
            self._panel_loops = loops
            self.panel_builds += 1
        return self._panel_loops

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


def layout(original, trimmed, region, settings, candidates=None):
    manager = adsk.fusion.TemporaryBRepManager.get()
    trim_region = body_region(trimmed)
    candidates = generate(region, settings) if candidates is None else candidates
    trim_segments = trim_region.indexed_segments(len(candidates))
    cells, whole, partial, partial_bodies = [], [], [], []
    material = (manager.copy(original) if settings.shape in ORGANIC_SHAPES
                and settings.margin < 4*model.TOLERANCE else None)
    for cell in candidates:
        if fits(cell, trim_region, trim_segments, 0):
            cells.append(cell)
            whole.append(cell)
        elif overlaps(cell, trim_region, trim_segments):
            cut = sheet([cell_curves(cell)])
            if not manager.booleanOperation(cut, trimmed, adsk.fusion.BooleanTypes.IntersectionBooleanType):
                raise ValueError('Fusion could not trim the hole to the boundary.')
            if cut.faces.count and cut.area > 1e-10:
                if settings.shape=='voronoi' and settings.corner_radius>0:
                    cut=rounded_body(cut,settings.corner_radius)
                if material is not None:
                    remaining=manager.copy(material)
                    if not manager.booleanOperation(remaining,cut,adsk.fusion.BooleanTypes.DifferenceBooleanType):
                        raise ValueError('Unable to check material connectivity at the boundary.')
                    if remaining.faces.count>material.faces.count:
                        continue  # Retain this local boundary fragment as a material bridge.
                    material=remaining
                cells.append(cell)
                partial.extend(body_loops(cut))
                partial_bodies.append(cut)
    if not cells:
        raise ValueError('No holes remain after applying Edge Offset.')
    return Layout(cells, whole, partial, original, partial_bodies)


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
