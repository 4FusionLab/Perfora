# SPDX-License-Identifier: GPL-3.0-only
"""Run via runpy in Fusion. All CAD lives in a separate unsaved document."""
from dataclasses import replace
import importlib.util
from importlib import import_module
import json
import math
from pathlib import Path
import platform
import sys
from time import perf_counter
import traceback

import adsk.core
import adsk.fusion

root = Path(__file__).resolve().parents[1]
package = '_perfora_cylindrical_test'
for key in tuple(sys.modules):
    if key == package or key.startswith(package + '.'):
        del sys.modules[key]
spec = importlib.util.spec_from_file_location(package, root / 'Perfora/__init__.py',
    submodule_search_locations=[str(root / 'Perfora')])
module = importlib.util.module_from_spec(spec)
sys.modules[package] = module
spec.loader.exec_module(module)
model = import_module(package + '.model')
geo = import_module(package + '.geometry')
cylinder = import_module(package + '.cylindrical')
preview = import_module(package + '.preview')
app = adsk.core.Application.get()
original = app.activeDocument
doc = None
results = []
output = Path.home() / 'Library/Logs/Perfora/cylindrical-regression.json'
output.parent.mkdir(parents=True, exist_ok=True)


def case(name, action):
    output.write_text(json.dumps(dict(running=name, tests=results)), encoding='utf-8')
    try:
        results.append(dict(name=name, passed=True, detail=action()))
    except Exception:
        results.append(dict(name=name, passed=False, error=traceback.format_exc()))


def config(**changes):
    data = dict(cylindrical=True, result='extrude', operation='cut', material='cells',
                cut_depth=.32, cylinder_start=0., cylinder_sweep=math.tau, axial_start=0., axial_length=0.)
    data.update(changes)
    return data


def tube(name, rotated=False, solid=False, inner=False, sector=False):
    component = design.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
    component.name = name
    manager = adsk.fusion.TemporaryBRepManager.get()
    a, b = adsk.core.Point3D.create(0, 0, 0), adsk.core.Point3D.create(0, 0, 1.6)
    body = manager.createCylinderOrCone(a, 1.5, b, 1.5)
    if not solid:
        assert manager.booleanOperation(body, manager.createCylinderOrCone(a, 1.3, b, 1.3),
                                        adsk.fusion.BooleanTypes.DifferenceBooleanType)
    if sector:
        box = adsk.core.OrientedBoundingBox3D.create(adsk.core.Point3D.create(1, 1, .8),
            adsk.core.Vector3D.create(1, 0, 0), adsk.core.Vector3D.create(0, 1, 0), 2., 2., 4.)
        assert manager.booleanOperation(body, manager.createBox(box), adsk.fusion.BooleanTypes.IntersectionBooleanType)
    if rotated:
        matrix = adsk.core.Matrix3D.create()
        matrix.setToRotation(.73, adsk.core.Vector3D.create(1, 2, .5), adsk.core.Point3D.create(0, 0, 0))
        matrix.translation = adsk.core.Vector3D.create(3, -2, 4)
        assert manager.transform(body, matrix)
    base = component.features.baseFeatures.add()
    base.startEdit()
    component.bRepBodies.add(body, base)
    base.finishEdit()
    body = base.bodies.item(0)
    face = next(f for f in body.faces if isinstance(f.geometry, adsk.core.Cylinder)
                and abs(f.geometry.radius - (1.3 if inner else 1.5)) < 1e-7)
    return component, body, face


try:
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)
    for shape in (*(s for s in geo.SHAPE_IDS if s not in geo.ORGANIC_SHAPES), 'voronoi_rounded'):

        def shape_cut(shape=shape):
            comp, body, face = tube('Cylinder ' + shape)
            settings = geo.Settings(shape='voronoi' if shape=='voronoi_rounded' else shape,
                                    size=.35, slot_length=.55, arm_width=.12,
                                    gap=.18, margin=.12, shape_angle=.27, staggered=False,
                                    corner_radius=.025 if shape=='voronoi_rounded' else 0)
            cfg = config()
            renderer = preview.Renderer()
            before = body.volume
            try:
                count = renderer.show(face, settings, cfg)
                coordinates = tuple(renderer.coordinates)
                builds = renderer.layout_builds
                for _ in range(10):
                    assert renderer.show(face, settings, cfg) == count
                assert renderer.layout_builds == builds
                fast_seconds = renderer.last_seconds
            finally:
                renderer.reset()
            started = perf_counter()
            _, feature, actual = model.build(face, settings, cfg)
            seconds = perf_counter() - started
            result = feature.bodies.item(0)
            assert actual == count and result.isSolid and result.isValid
            assert 0 < result.volume < before
            # Exact surface samples from Fast Preview must lie on final cut rims.
            sampled = 0
            for i in range(0, len(coordinates), max(6, (len(coordinates)//300//6)*6)):
                p = adsk.core.Point3D.create(*coordinates[i:i+3])
                assert result.pointContainment(p) == adsk.fusion.PointContainment.PointOnPointContainment, (shape, p.asArray())
                sampled += 1
            return dict(holes=count, volume_before=before, volume_after=result.volume,
                        cut_seconds=seconds, cached_fast_seconds=fast_seconds, rim_samples=sampled)
        case('full_360_' + shape, shape_cut)

    def opposite_wall():
        comp, body, face = tube('Bounded radial cut')
        settings = geo.Settings(size=.3, gap=.15, margin=.1, staggered=False)
        cfg = config(cylinder_start=.1, cylinder_sweep=1.1, axial_start=.2, axial_length=1.1)
        f, holes = cylinder.prepare(face, settings, cfg)
        hole = holes[len(holes)//2]
        cut_probe = adsk.core.Point3D.create(*f.point(hole.angle, hole.axial, radial_distance=1.4))
        opposite_probe = adsk.core.Point3D.create(*f.point(hole.angle+math.pi, hole.axial, radial_distance=1.4))
        assert body.pointContainment(cut_probe) == adsk.fusion.PointContainment.PointInsidePointContainment
        _, feature, count = model.build(face, settings, cfg)
        result = feature.bodies.item(0)
        assert result.pointContainment(cut_probe) == adsk.fusion.PointContainment.PointOutsidePointContainment
        assert result.pointContainment(opposite_probe) == adsk.fusion.PointContainment.PointInsidePointContainment
        return dict(holes=count, selected_wall_open=True, opposite_wall_intact=True)
    case('bounded_zone_opposite_wall', opposite_wall)

    def cylindrical_sector():
        comp, body, face = tube('Quarter cylinder', sector=True)
        settings = geo.Settings(size=.25, gap=.12, margin=.1, staggered=False)
        cfg = config(cylinder_sweep=math.pi/2)
        f, holes = cylinder.prepare(face, settings, cfg)
        assert abs(f.region.sweep - math.pi/2) < 1e-7
        coordinates = cylinder.coordinates(f, settings, holes)
        for i in range(0, len(coordinates), 3):
            assert face.isPointOnFace(adsk.core.Point3D.create(*coordinates[i:i+3]), 1e-6)
        _, feature, count = model.build(face, settings, cfg)
        assert feature.bodies.item(0).isSolid and count == len(holes)
        return dict(holes=count, sweep_deg=90, preview_on_sector=True)
    case('finite_cylindrical_face', cylindrical_sector)

    def unsupported_sources_and_failed_build_cleanup():
        comp, body, face = tube('Rejected cases')
        baseline = design.timeline.count
        for cfg in (config(cut_depth=1.5), config(cut_depth=.00001), config(result='feature')):
            try:
                model.build(face, geo.Settings(), cfg)
                raise AssertionError('Unsupported configuration accepted')
            except ValueError:
                pass
            assert design.timeline.count == baseline
        _, feature, _ = model.build(face, geo.Settings(size=.3, margin=.1), config(cylinder_sweep=1.))
        cut_face = max((f for f in feature.bodies.item(0).faces if isinstance(f.geometry, adsk.core.Cylinder)), key=lambda f:f.area)
        try:
            cylinder.prepare(cut_face, geo.Settings(), config())
            raise AssertionError('Existing openings were ignored')
        except ValueError as error:
            assert 'openings' in str(error)
        return dict(rejected=4, no_failed_build_residue=True)
    case('unsupported_sources_cleanup', unsupported_sources_and_failed_build_cleanup)

    for inner, shape in ((False, 'hexagon'), (True, 'hexagon'), (False, 'voronoi'), (True, 'voronoi')):
        def rotated_cut(inner=inner, shape=shape):
            comp, body, face = tube('Rotated inner' if inner else 'Rotated outer', rotated=True, inner=inner)
            settings = geo.Settings(shape=shape, size=.3, gap=.15, margin=.1,
                                    corner_radius=.025 if shape=='voronoi' else 0)
            cfg = config()
            renderer = preview.Renderer()
            try:
                count = renderer.show(face, settings, cfg)
                f = renderer.frame
                for i in range(0, len(renderer.coordinates), 3):
                    p = adsk.core.Point3D.create(*renderer.coordinates[i:i+3])
                    assert face.isPointOnFace(p, 1e-6)
                assert f.region.inward != inner
            finally:
                renderer.reset()
            _, feature, actual = model.build(face, settings, cfg)
            assert actual == count and feature.bodies.item(0).isSolid
            return dict(holes=count, preview_on_face=True, material_side='outward' if inner else 'inward')
        case(('rotated_inner_' if inner else 'rotated_outer_')+shape, rotated_cut)

    def boss():
        comp, body, face = tube('Solid boss', solid=True)
        _, feature, count = model.build(face, geo.Settings(size=.3, margin=.1), config(cut_depth=.2))
        assert feature.bodies.item(0).isSolid
        return dict(holes=count, blind_depth_cm=.2)
    case('solid_boss_blind_cut', boss)

    def cache_and_dense_preview():
        comp, body, face = tube('Dense hexagon preview')
        settings = geo.Settings(shape='hexagon', size=.07, gap=.04, margin=.05)
        renderer = preview.Renderer()
        cfg = config(cut_depth=.24)
        try:
            started = perf_counter()
            count = renderer.show(face, settings, cfg)
            cold = perf_counter() - started
            builds = renderer.layout_builds
            started = perf_counter()
            for _ in range(100):
                renderer.show(face, settings, cfg)
            warm = (perf_counter() - started) / 100
            assert renderer.layout_builds == builds
            for key, val in [('cut_depth', .3), ('cylinder_start', .2), ('cylinder_sweep', math.pi),
                             ('axial_start', .1), ('axial_length', 1.)]:
                cfg = dict(cfg, **{key: val})
                renderer.show(face, settings, cfg)
                builds += 1
                assert renderer.layout_builds == builds
            renderer.clear()
            assert comp.customGraphicsGroups.count == 0
            return dict(holes=count, cold_seconds=cold, cached_seconds=warm, invalidations=5,
                        sketches=comp.sketches.count)
        finally:
            renderer.reset()
    case('dense_preview_cache_cleanup', cache_and_dense_preview)

    def voronoi_preview_and_seed():
        comp, body, face = tube('Periodic Voronoi preview')
        settings = geo.Settings(shape='voronoi', size=.15, gap=.025, margin=.05, seed=17, corner_radius=.015)
        renderer = preview.Renderer()
        try:
            cfg = config(cut_depth=.25)
            started = perf_counter()
            count = renderer.show(face, settings, cfg)
            cold = perf_counter()-started
            cells = renderer.cells
            builds = renderer.layout_builds
            started = perf_counter()
            for _ in range(100):
                renderer.show(face, settings, cfg)
            cached = (perf_counter()-started)/100
            assert renderer.layout_builds==builds
            for change in (dict(seed=18), dict(irregularity=0), dict(corner_radius=0)):
                settings = replace(settings, **change)
                renderer.show(face, settings, cfg)
                assert renderer.cells != cells
                cells = renderer.cells
                builds += 1
                assert renderer.layout_builds==builds
            assert comp.sketches.count==0 and comp.features.combineFeatures.count==0
            return dict(holes=count, cold_seconds=cold, cached_seconds=cached, seed_irregularity_rounding_invalidate=True)
        finally:
            renderer.reset()
    case('voronoi_preview_seed_cache', voronoi_preview_and_seed)
finally:
    if doc:
        doc.close(False)
    if original:
        original.activate()
    output.write_text(json.dumps(dict(passed=bool(results) and all(r['passed'] for r in results),
        fusion=app.version, os=platform.platform(), checkout=str(root), tests=results), indent=2), encoding='utf-8')
    print(str(output))
