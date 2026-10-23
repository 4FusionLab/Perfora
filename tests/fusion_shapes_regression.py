# SPDX-License-Identifier: GPL-3.0-only
"""Run with runpy.run_path in Fusion. Checks exact areas, solids and caching."""
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

_root = Path(__file__).resolve().parents[1]
_pkg = '_perforator_shapes'
for _key in tuple(sys.modules):
    if _key == _pkg or _key.startswith(_pkg + '.'):
        del sys.modules[_key]
_spec = importlib.util.spec_from_file_location(_pkg, _root / 'Perfora/__init__.py',
                                             submodule_search_locations=[str(_root / 'Perfora')])
_module = importlib.util.module_from_spec(_spec)
sys.modules[_pkg] = _module
_spec.loader.exec_module(_module)
_model = import_module(_pkg + '.model')
_geometry = import_module(_pkg + '.geometry')
_preview = import_module(_pkg + '.preview')
_spec = importlib.util.spec_from_file_location('_shape_smoke', _root / 'PerforaSmokeTest/PerforaSmokeTest.py')
_smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_smoke)
_app = adsk.core.Application.get()
_original = _app.activeDocument
_doc = None
_results = []


def _case(name, action):
    try:
        _results.append(dict(name=name, passed=True, detail=action()))
    except Exception:
        _results.append(dict(name=name, passed=False, error=traceback.format_exc()))


try:
    _doc = _app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    _design = adsk.fusion.Design.cast(_app.activeProduct)
    for _shape in ('triangle', 'rectangle', 'diamond', 'ellipse', 'pentagon', 'octagon', 'cross', 'star'):
        def _check_shape(shape=_shape):
            comp = _smoke.component(_design, shape)
            s = _geometry.Settings(shape=shape, size=0.6, slot_length=1.1, gap=0.15, margin=0.2,
                                   grid_angle=0.19, shape_angle=0.37, arm_width=0.16,
                                   star_points=7, star_ratio=0.4)
            expected = dict(triangle=s.size**2 * math.sqrt(3)/4, rectangle=s.size*s.slot_length,
                            diamond=s.size*s.slot_length/2, ellipse=math.pi*s.size*s.slot_length/4,
                            pentagon=5*(s.size/2)**2*math.sin(math.tau/5)/2,
                            octagon=2*s.size**2*math.tan(math.pi/8),
                            cross=2*s.size*s.arm_width-s.arm_width**2,
                            star=s.star_points*(s.size/2)**2*s.star_ratio*math.sin(math.pi/s.star_points))[shape]
            config = _smoke.config(result='profiles')
            renderer = _preview.Renderer()
            timeline = _design.timeline.count
            start = perf_counter()
            count = renderer.show(comp.xYConstructionPlane, s, config)
            first = perf_counter() - start
            assert _design.timeline.count == timeline and comp.sketches.count == 0
            for _ in range(100):
                renderer.show(comp.xYConstructionPlane, s, config)
            assert renderer.layout_builds == 1
            renderer.reset()
            sketch, _, final_count = _model.build(comp.xYConstructionPlane, s, config)
            assert count == final_count == sketch.profiles.count
            actual_area = sum(p.areaProperties().area for p in sketch.profiles)
            assert abs(actual_area - count*expected) < 1e-6, (actual_area,count*expected)
            if shape == 'ellipse':
                assert sketch.sketchCurves.sketchEllipses.count == count
            _, feature, _ = _model.build(comp.xYConstructionPlane, s, _smoke.config())
            volume = sum(b.volume for b in feature.bodies)
            assert abs(volume-count*expected*0.2)<1e-6, (volume,count*expected*0.2)
            return dict(cells=count, cell_area_cm2=expected, volume_cm3=volume, preview_seconds=first)
        _case('profiles_volume_cache_' + _shape, _check_shape)

    for _shape in ('triangle','ellipse','cross','star'):
        for _operation in ('cut','join','intersect','body','component'):
            def _operation_test(shape=_shape,operation=_operation):
                comp = _smoke.component(_design, shape + ' ' + operation)
                body,face = _smoke.plate(comp)
                s = _geometry.Settings(shape=shape, size=0.6, slot_length=1.0, margin=0.2,
                                       arm_width=0.16, clip_boundary=True)
                _,feature,count = _model.build(face,s,_smoke.config(operation=operation,
                    reverse=operation in ('cut','intersect'),bodies=[body]))
                assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
                return dict(cells=count,bodies=feature.bodies.count)
            _case(_shape + '_' + _operation, _operation_test)
finally:
    if _doc:
        _doc.close(False)
    if _original and _original.isValid:
        _original.activate()
    _report = dict(passed=bool(_results) and all(r['passed'] for r in _results),tests=_results)
    _out = Path.home() / 'Library/Logs/Perfora/shapes-regression.json'
    _out.parent.mkdir(parents=True,exist_ok=True)
    _out.write_text(json.dumps(_report,ensure_ascii=False,indent=2),encoding='utf-8')
print('PERFORATOR_SHAPES',_report)
