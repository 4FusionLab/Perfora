# SPDX-License-Identifier: GPL-3.0-only
"""Temporary, exact straight extrusion. Safe during a custom-feature compute."""
import math
import adsk.core
import adsk.fusion


class PointKeys:
    """Stable topology IDs for coincident kernel points, including bucket edges.

    Rounding coordinates independently can put the two copies of an exact .5
    decimal coordinate in different buckets after a ruled-surface operation.
    Search neighboring buckets and compare distance before sharing a vertex.
    """
    def __init__(self,tolerance=2e-6):
        self.tolerance=tolerance
        self.buckets={}
        self.count=0

    def key(self,point):
        p=tuple(point.asArray());bucket=tuple(math.floor(v/self.tolerance) for v in p)
        matches=[]
        for x in (-1,0,1):
            for y in (-1,0,1):
                for z in (-1,0,1):
                    for q,index in self.buckets.get((bucket[0]+x,bucket[1]+y,bucket[2]+z),()):
                        if math.dist(p,q)<=self.tolerance:matches.append(index)
        if matches:return min(matches)
        index=self.count;self.count+=1
        self.buckets.setdefault(bucket,[]).append((p,index))
        return index


def translated(body, distance):
    manager = adsk.fusion.TemporaryBRepManager.get()
    result = manager.copy(body)
    transform = adsk.core.Matrix3D.create()
    transform.translation = adsk.core.Vector3D.create(0, 0, distance)
    if not manager.transform(result, transform):
        raise ValueError('Unable to translate the Feature section.')
    return result


def extrude(sheets, start, end):
    """Sew exact caps and ruled side faces into one body with one lump per island.

    Geometry stays in sketch coordinates. No sketches, features, or documents are
    created here; this function also runs while Fusion is computing the timeline.
    """
    if end <= start:
        raise ValueError('Feature thickness must be positive.')
    manager = adsk.fusion.TemporaryBRepManager.get()
    definition = adsk.fusion.BRepBodyDefinition.create()
    for sheet in sheets:
        for planar_face in sheet.faces:
            bottom = translated(manager.copy(planar_face), start)
            top = translated(manager.copy(planar_face), end)
            lower_face, upper_face = bottom.faces.item(0), top.faces.item(0)
            ok, normal = planar_face.evaluator.getNormalAtPoint(planar_face.pointOnFace)
            if not ok:
                raise ValueError('Unable to orient the Feature section.')
            faces = [(lower_face, normal.z > 0), (upper_face, normal.z < 0)]
            for edge in planar_face.edges:
                # One ruled patch per edge prevents tangent chains (slots and
                # rounded Voronoi) from being merged into a closed NURBS edge.
                wire = manager.copy(edge)
                lower, upper = translated(wire, start), translated(wire, end)
                side = manager.createRuledSurface(lower.wires.item(0), upper.wires.item(0))
                if not side:
                    raise ValueError('Unable to extrude the Feature boundary.')
                for f in side.faces:
                    ok, normal = f.evaluator.getNormalAtPoint(f.pointOnFace)
                    if not ok:
                        raise ValueError('Unable to orient the Feature wall.')
                    probe = f.pointOnFace.copy()
                    probe.z = 0
                    shift = adsk.core.Vector3D.create(normal.x * 1e-5, normal.y * 1e-5, 0)
                    probe.translateBy(shift)
                    flip = planar_face.isPointOnFace(probe, 1e-8)
                    faces.append((f, flip))
            shell = definition.lumpDefinitions.add().shellDefinitions.add()
            vertices, edges, uses = {}, {}, {}
            key = PointKeys().key

            def vertex(point):
                k = key(point)
                if k not in vertices:
                    vertices[k] = definition.createVertexDefinition(point)
                return vertices[k]

            for face, flip in faces:
                target = shell.faceDefinitions.add(face.geometry, face.isParamReversed != flip)
                for loop in face.loops:
                    target_loop = target.loopDefinitions.add()
                    coedge = loop.coEdges.item(0)
                    for _ in range(loop.coEdges.count):
                        edge = coedge.edge
                        curve = edge.geometry
                        evaluator = curve.evaluator
                        ok, a, b = evaluator.getParameterExtents()
                        ok_mid, mid = evaluator.getPointAtParameter((a + b) / 2)
                        if not (ok and ok_mid):
                            raise ValueError('Unable to read a Feature edge.')
                        # Curve direction, rather than BRepEdge direction, is
                        # the direction used by createEdgeDefinitionByCurve.
                        p, q = edge.startVertex.geometry, edge.endVertex.geometry
                        if p.distanceTo(q) < 1e-8 and isinstance(curve, (adsk.core.Circle3D, adsk.core.Ellipse3D)):
                            # Ruled surfaces move the periodic seam of an ellipse.
                            # Use its analytic curve origin for both caps/walls.
                            ok_start, p = evaluator.getPointAtParameter(a)
                            if not ok_start:
                                raise ValueError('Unable to locate a closed Feature edge.')
                            q = p
                        if edge.isParamReversed:
                            p, q = q, p
                        k = (tuple(sorted((key(p), key(q)))), key(mid))
                        if k not in edges:
                            edges[k] = (definition.createEdgeDefinitionByCurve(vertex(p), vertex(q), curve), key(p))
                        edge_def, first = edges[k]
                        opposed = coedge.isOpposedToEdge != edge.isParamReversed
                        if first != key(p):
                            opposed = not opposed
                        target_loop.bRepCoEdgeDefinitions.add(edge_def, opposed != flip)
                        uses[k] = uses.get(k, 0) + 1
                        coedge = coedge.previous if flip else coedge.next
            if any(n != 2 for n in uses.values()):
                raise ValueError('The Feature boundary could not be sewn into a closed shell.')
    # The manifold is fully specified; healing malformed topology can spend an
    # unbounded time in Fusion's kernel. Fail explicitly instead.
    definition.doFullHealing = False
    result = definition.createBody()
    if not result or not result.isSolid:
        raise ValueError('Unable to close the Feature solid: ' + '; '.join(definition.outcomeInfo))
    return result
