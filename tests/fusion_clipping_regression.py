# SPDX-License-Identifier: GPL-3.0-only
"""Execute in Fusion's Py console. A separate unsaved document is closed afterwards."""
import importlib.util
from importlib import import_module
import json
import math
from pathlib import Path
import sys
from time import perf_counter
import traceback

import adsk.core
import adsk.fusion

_clip_root = Path(__file__).resolve().parents[1]
_clip_package = '_perforator_clip_test'
for _key in tuple(sys.modules):
    if _key == _clip_package or _key.startswith(_clip_package + '.'):
        del sys.modules[_key]
_spec = importlib.util.spec_from_file_location(_clip_package, _clip_root / 'Perfora/__init__.py',
                                             submodule_search_locations=[str(_clip_root / 'Perfora')])
_module = importlib.util.module_from_spec(_spec)
sys.modules[_clip_package] = _module
_spec.loader.exec_module(_module)
_cm = import_module(_clip_package + '.model')
_cg = import_module(_clip_package + '.geometry')
_cc = import_module(_clip_package + '.clipping')
_cp = import_module(_clip_package + '.preview')
_smoke_spec = importlib.util.spec_from_file_location('_clip_smoke', _clip_root / 'PerforaSmokeTest/PerforaSmokeTest.py')
_smoke = importlib.util.module_from_spec(_smoke_spec)
_smoke_spec.loader.exec_module(_smoke)
_clip_app = adsk.core.Application.get()
_clip_original = _clip_app.activeDocument
_clip_doc = None
_clip_results = []


def _clip_case(name, action):
    try:
        _clip_results.append(dict(name=name, passed=True, detail=action()))
    except Exception:
        _clip_results.append(dict(name=name, passed=False, error=traceback.format_exc()))


try:
    _clip_doc = _clip_app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    _clip_design = adsk.fusion.Design.cast(_clip_app.activeProduct)
    _clip_comp = _clip_design.rootComponent

    def _half_hexagon():
        manager = adsk.fusion.TemporaryBRepManager.get()
        cell = _cg.Cell((1, 0), 'hexagon', 1, 1, 0)
        body = _cc.sheet([_cc.cell_curves(cell)])
        boundary = _cc.sheet([_cc.polygon_curves(_cg.rectangle_region(2, 4).loops[0].points)])
        assert manager.booleanOperation(body, boundary, adsk.fusion.BooleanTypes.IntersectionBooleanType)
        expected = math.sqrt(3) / 4
        assert abs(body.area - expected) < 1e-8, (body.area, expected)
        assert abs(body.boundingBox.maxPoint.x - 1) < 1e-8
        return dict(area_cm2=body.area, fraction=0.5)
    _clip_case('exact_half_hexagon', _half_hexagon)

    for _shape in ('hexagon', 'circle', 'square', 'slot', 'triangle', 'rectangle', 'diamond',
                   'ellipse', 'pentagon', 'octagon', 'cross', 'star', 'voronoi'):
        for _margin in (0, 0.2):
            def _profiles(shape=_shape, margin=_margin):
                comp = _smoke.component(_clip_design, shape + str(margin))
                settings = _cg.Settings(shape=shape, size=0.65, slot_length=1.1, gap=0.17,
                                        margin=margin, clip_boundary=True, staggered=False, offset_x=0.21)
                config = _smoke.config(result='profiles', width=3.2, height=2.6)
                renderer = _cp.Renderer()
                before = _clip_design.timeline.count
                count = renderer.show(comp.xYConstructionPlane, settings, config)
                assert _clip_design.timeline.count == before and comp.sketches.count == 0
                start = perf_counter()
                for _ in range(100):
                    renderer.show(comp.xYConstructionPlane, settings, config)
                cached = perf_counter() - start
                assert renderer.layout_builds == 1
                assert renderer.clipped_layout.partial_loops
                if margin:
                    assert abs(renderer.trimmed_body.area - (3.2 - 2 * margin) * (2.6 - 2 * margin)) < 1e-6
                renderer.reset()
                sketch, _, built_count = _cm.build(comp.xYConstructionPlane, settings, config)
                assert count == built_count
                selected = _cm.selected_profiles(sketch, 'cells', True)
                area = sum(p.areaProperties().area for p in selected)
                for curve in sketch.sketchCurves:
                    for x, y in _cm.strokes(curve.geometry.evaluator, lambda p: p):
                        assert abs(x) <= 1.6 - margin + 2e-6, (shape, margin, x)
                        assert abs(y) <= 1.3 - margin + 2e-6, (shape, margin, y)
                if shape in ('circle', 'slot'):
                    assert sketch.sketchCurves.sketchArcs.count > 0, 'Clipped arcs lost analytic geometry'
                if shape == 'ellipse':
                    assert sketch.sketchCurves.sketchEllipticalArcs.count > 0, 'Clipped ellipses lost analytic arcs'
                _, feature, _ = _cm.build(comp.xYConstructionPlane, settings, _smoke.config(
                    width=3.2, height=2.6, material='panel'))
                expected = (3.2 * 2.6 - area) * 0.2
                actual = sum(b.volume for b in feature.bodies)
                assert abs(actual - expected) < 1e-5, (actual, expected)
                return dict(cells=count, profiles=selected.count, area_cm2=area, panel_volume_cm3=actual,
                            hundred_cached_seconds=cached)
            _clip_case('profiles_panel_' + _shape + '_' + str(_margin), _profiles)

    def _annulus():
        comp = _smoke.component(_clip_design, 'Annulus')
        source = comp.sketches.addWithoutEdges(comp.xZConstructionPlane)
        source.sketchCurves.sketchCircles.addByCenterRadius(_cm.point((0, 0)), 2)
        source.sketchCurves.sketchCircles.addByCenterRadius(_cm.point((0, 0)), 0.45)
        profile = next(p for p in source.profiles if p.profileLoops.count == 2)
        settings = _cg.Settings(shape='hexagon', size=0.7, gap=0.13, margin=0.2, clip_boundary=True)
        renderer = _cp.Renderer()
        config = _smoke.config(result='profiles')
        renderer.show(profile, settings, config)
        expected_trim = math.pi * (1.8 ** 2 - 0.65 ** 2)
        assert abs(renderer.trimmed_body.area - expected_trim) < 1e-6, renderer.trimmed_body.area
        renderer.reset()
        output, _, count = _cm.build(profile, settings, config)
        for curve in output.sketchCurves:
            for p in _cm.strokes(curve.geometry.evaluator, lambda p: p):
                assert 0.65 - 2e-6 <= math.hypot(*p) <= 1.8 + 2e-6, p
        return dict(cells=count, trim_area_cm2=expected_trim)
    _clip_case('rotated_annulus_with_margin', _annulus)

    def _concave_split():
        comp = _smoke.component(_clip_design, 'Concave')
        source = comp.sketches.addWithoutEdges(comp.xYConstructionPlane)
        _cm.add_polygon(source, ((-2,-2),(2,-2),(2,2),(1,2),(1,-1),(-1,-1),(-1,2),(-2,2)), 'cell')
        settings = _cg.Settings(shape='hexagon', size=1.2, gap=0.2, margin=0.1, clip_boundary=True)
        output, _, count = _cm.build(source.profiles.item(0), settings, _smoke.config(result='profiles'))
        assert count > 0 and output.profiles.count > 0
        return dict(cells=count, profiles=output.profiles.count)
    _clip_case('concave_boundary_inset', _concave_split)

    def _oversized_inset():
        comp = _smoke.component(_clip_design, 'Invalid margin')
        before = comp.sketches.count
        try:
            _cm.build(comp.xYConstructionPlane, _cg.Settings(clip_boundary=True, margin=1.5),
                      _smoke.config(result='profiles', width=2, height=4))
        except ValueError:
            assert comp.sketches.count == before
            return 'Oversized inset rejected without residue'
        raise AssertionError('Inverted inset was accepted')
    _clip_case('oversized_inset_rejected', _oversized_inset)

    for _op in ('cut', 'join', 'intersect', 'body', 'component'):
        def _operation(operation=_op):
            comp = _smoke.component(_clip_design, 'Clipped ' + operation)
            body, face = _smoke.plate(comp)
            settings = _cg.Settings(shape='hexagon', size=0.7, gap=0.17, margin=0.15, clip_boundary=True)
            _, feature, count = _cm.build(face, settings, _smoke.config(
                operation=operation, reverse=operation in ('cut','intersect'), bodies=[body]))
            assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
            return dict(cells=count, bodies=feature.bodies.count)
        _clip_case('operation_' + _op, _operation)
finally:
    if _clip_doc:
        _clip_doc.close(False)
    if _clip_original and _clip_original.isValid:
        _clip_original.activate()
    _clip_report = dict(passed=bool(_clip_results) and all(r['passed'] for r in _clip_results), tests=_clip_results)
    _clip_out = Path.home() / 'Library/Logs/Perfora/clipping-regression.json'
    _clip_out.parent.mkdir(parents=True, exist_ok=True)
    _clip_out.write_text(json.dumps(_clip_report, ensure_ascii=False, indent=2), encoding='utf-8')
print('PERFORATOR_CLIPPING', _clip_report)
