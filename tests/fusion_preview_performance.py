# SPDX-License-Identifier: GPL-3.0-only
"""Run in Fusion's Py console. Real rendering/cache/CAD performance checks.

Creates and closes one separate unsaved test document, leaving the user's
document untouched. Report: ~/Library/Logs/Perfora/preview-performance.json.
"""
import importlib.util
import json
from pathlib import Path
import sys
from time import perf_counter
import traceback

import adsk.core
import adsk.fusion

_preview_package = '_perforator_perf'
_preview_directory = Path(__file__).resolve().parents[1] / 'Perfora'
for _key in tuple(sys.modules):
    if _key == _preview_package or _key.startswith(_preview_package + '.'):
        del sys.modules[_key]
_spec = importlib.util.spec_from_file_location(_preview_package, _preview_directory / '__init__.py',
                                             submodule_search_locations=[str(_preview_directory)])
_module = importlib.util.module_from_spec(_spec)
sys.modules[_preview_package] = _module
_spec.loader.exec_module(_module)
from importlib import import_module
_preview_model = import_module(_preview_package + '.model')
_preview_geometry = import_module(_preview_package + '.geometry')
_preview_module = import_module(_preview_package + '.preview')
_preview_app = adsk.core.Application.get()
_preview_original = _preview_app.activeDocument
_preview_doc = None
_preview_report = {'passed': False}
try:
    _preview_doc = _preview_app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    _preview_design = adsk.fusion.Design.cast(_preview_app.activeProduct)
    _preview_comp = _preview_design.rootComponent
    _preview_config = dict(boundary='rectangle', width=12.0, height=25.0, material='cells', result='profiles')
    _renderer = _preview_module.Renderer()
    _preview_shapes = []
    for _shape in ('circle', 'hexagon', 'square', 'slot'):
        _settings = _preview_geometry.Settings(shape=_shape, size=0.5, gap=0.15, margin=0.3,
                                              slot_length=1.0, limit=1500)
        _start = perf_counter()
        _count = _renderer.show(_preview_comp.xYConstructionPlane, _settings, _preview_config)
        _preview_app.activeViewport.refresh()
        _elapsed = perf_counter() - _start
        assert _renderer.graphics.isValid
        assert _preview_comp.sketches.count == 0 and _preview_design.timeline.count == 0
        _layouts_before = _renderer.layout_builds
        _start = perf_counter()
        for _i in range(100):
            _renderer.show(_preview_comp.xYConstructionPlane, _settings, _preview_config)
        _cached_elapsed = perf_counter() - _start
        assert _renderer.layout_builds == _layouts_before, 'Menu/layout changes rebuilt cells'
        assert _preview_comp.customGraphicsGroups.count == 1
        _preview_shapes.append(dict(shape=_shape, cells=_count, first_seconds=_elapsed,
                                    hundred_cached_seconds=_cached_elapsed))
        _renderer.reset()
        assert _preview_comp.customGraphicsGroups.count == 0
    # Compare the actual rendered vertex (including the graphics transform) with
    # Fusion's independent sketchToModelSpace, on a translated, rotated plane.
    _plane_input = _preview_comp.constructionPlanes.createInput()
    _plane_input.setByOffset(_preview_comp.yZConstructionPlane, adsk.core.ValueInput.createByString('60 mm'))
    _offset_plane = _preview_comp.constructionPlanes.add(_plane_input)
    _settings = _preview_geometry.Settings(shape='hexagon', size=0.5, gap=0.2, margin=0.2)
    _renderer.show(_offset_plane, _settings, _preview_config)
    _local = _preview_geometry.outline_coordinates(_renderer.cells, _renderer.region)[:3]
    _actual = _renderer.graphics.item(0).coordinates.getCoordinate(0)
    _actual.transformBy(_renderer.graphics.transform)
    _reference = _preview_model.new_source_sketch(_offset_plane)
    try:
        _expected_point = _reference.sketchToModelSpace(adsk.core.Point3D.create(*_local))
        _frame_error = _actual.distanceTo(_expected_point)
    finally:
        _reference.deleteMe()
        _renderer.reset()
    assert _frame_error < 1e-5, ('Preview is off its source plane', _frame_error)
    # The preview uses exactly the coordinate frame and cell count of final CAD.
    _preview_config.update(width=4.0, height=3.0)
    _settings = _preview_geometry.Settings(shape='hexagon', size=0.5, gap=0.2, margin=0.2)
    _count = _renderer.show(_preview_comp.xZConstructionPlane, _settings, _preview_config)
    _renderer.reset()
    _start = perf_counter()
    _sketch, _feature, _final_count = _preview_model.build(_preview_comp.xZConstructionPlane, _settings, _preview_config)
    _final_seconds = perf_counter() - _start
    assert _final_count == _count and _feature is None
    assert _sketch.profiles.count == _count
    assert all(c.attributes.count == 0 for c in _sketch.sketchCurves), 'Cell-edge attributes slow down native CAD'
    _preview_report.update(passed=True, shapes=_preview_shapes, final_hexagon_cells=_final_count,
                           final_hexagon_seconds=_final_seconds, translated_frame_error_cm=_frame_error)
except Exception:
    _preview_report['error'] = traceback.format_exc()
finally:
    if _preview_doc:
        _preview_doc.close(False)
    if _preview_original and _preview_original.isValid:
        _preview_original.activate()
    _out = Path.home() / 'Library/Logs/Perfora/preview-performance.json'
    _out.parent.mkdir(parents=True, exist_ok=True)
    _out.write_text(json.dumps(_preview_report, ensure_ascii=False, indent=2), encoding='utf-8')
print('PERFORATOR_PREVIEW_REPORT', _preview_report)
