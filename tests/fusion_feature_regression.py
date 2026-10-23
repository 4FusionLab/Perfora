# SPDX-License-Identifier: GPL-3.0-only
"""Run with runpy in Fusion with the tested Perfora add-in running.

CustomFeatureDefinition must belong to a registered add-in with a manifest UUID;
loading feature.py as a standalone test package cannot establish that identity.
All CAD changes use a separate disposable, unsaved document. JSON reports live
outside the checkout in ~/Library/Logs/Perfora/feature-regression.json.
"""
import importlib.util
import json
import math
from pathlib import Path
import sys
from time import perf_counter
import traceback

import adsk.core
import adsk.fusion

root = Path(__file__).resolve().parents[1]
addon_path = Path(globals().get('addon_path', root / 'Perfora')).resolve()
entry = next(m for m in tuple(sys.modules.values())
             if str(getattr(m, '__file__', '')) == str(addon_path / 'Perfora.py'))
feature, model = entry.parametric, entry.model
geo = sys.modules[entry.Settings.__module__]
solid, clipping = feature.solid, feature.clipping
spec = importlib.util.spec_from_file_location('_perfora_feature_fixture', root / 'PerforaSmokeTest/PerforaSmokeTest.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
app = adsk.core.Application.get()
output = Path.home() / 'Library/Logs/Perfora/feature-regression.json'
output.parent.mkdir(parents=True, exist_ok=True)
results = []
only_cases = globals().get('only_cases')


def save(stage):
    output.write_text(json.dumps(dict(stage=stage, fusion=app.version,
        addon=str(Path(entry.__file__)),
        passed=bool(results) and all(r['passed'] for r in results), tests=results), indent=2))


def case(name, action):
    if only_cases and name not in only_cases:
        return
    save(name)
    started = perf_counter()
    try:
        detail = action()
        results.append(dict(name=name, passed=True, seconds=perf_counter() - started, detail=detail))
    except Exception:
        results.append(dict(name=name, passed=False, error=traceback.format_exc()))
    save(name + ' complete')


def healthy(custom):
    assert custom.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState, custom.errorOrWarningMessage


original = app.activeDocument
doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
try:
    design = adsk.fusion.Design.cast(app.activeProduct)

    for shape, _ in entry.SHAPES:
        def exact_solid(shape=shape):
            settings = geo.Settings(shape=shape, size=.5, slot_length=.8, gap=.2, margin=.1,
                                    corner_radius=.04 if shape == 'voronoi' else 0)
            cell = geo.generate(geo.rectangle_region(2, 2), settings)[0]
            sheet = clipping.sheet([clipping.cell_curves(cell)])
            body = solid.extrude([sheet], -.1, .2)
            assert body.isSolid and abs(body.volume - sheet.area * .3) < 1e-7
            return dict(volume=body.volume, faces=body.faces.count)
        case('solid_' + shape, exact_solid)

    def panel_parameters():
        comp = fixture.component(design, 'Feature Panel')
        cfg = fixture.config(result='feature', material='panel', width=2, height=2)
        _, custom, count = feature.build(comp.xYConstructionPlane,
            geo.Settings(size=.5, gap=.2, margin=.1), cfg)
        before = sum(b.volume for b in comp.bRepBodies)
        custom.parameters.itemById('size').expression = '3 mm'
        design.computeAll()
        after = sum(b.volume for b in comp.bRepBodies)
        assert abs(after - before) > 1e-5, (before, after)
        healthy(custom)
        custom.parameters.itemById('distance1').expression = '4 mm'
        design.computeAll()
        healthy(custom)
        assert abs(sum(b.volume for b in comp.bRepBodies) - 2 * after) < 1e-6
        custom.parameters.itemById('width').expression = '30 mm'
        design.computeAll()
        healthy(custom)
        assert abs(sum(b.volume for b in comp.bRepBodies) - 2 * after) > 1e-5
        return dict(cells=count, volume_before=before, volume_after=after, parameters=custom.parameters.count)
    case('panel_parameter_recompute', panel_parameters)

    for operation in ('cut', 'join', 'intersect', 'body'):
        def boolean(operation=operation):
            comp = fixture.component(design, 'Feature ' + operation)
            body, face = fixture.plate(comp)
            cfg = fixture.config(result='feature', operation=operation,
                                 reverse=operation != 'join', bodies=[body] if operation != 'body' else [])
            if operation == 'body':
                cfg['material'] = 'panel'
            _, custom, count = feature.build(face, geo.Settings(size=.5, gap=.2, margin=.2), cfg)
            healthy(custom)
            # Measure visible output only; retained Boolean tools are hidden.
            before = sum(b.volume for b in comp.bRepBodies if b.isVisible)
            custom.parameters.itemById('size').expression = '3.5 mm'
            design.computeAll()
            healthy(custom)
            after = sum(b.volume for b in comp.bRepBodies if b.isVisible)
            assert abs(after - before) > 1e-5, (before, after)
            return dict(cells=count, volume_before=before, volume_after=after)
        case('operation_' + operation, boolean)

    def upstream_profile():
        comp = fixture.component(design, 'Feature Source')
        sketch = comp.sketches.add(comp.xYConstructionPlane)
        circle = sketch.sketchCurves.sketchCircles.addByCenterRadius(model.point((0, 0)), 1)
        dimension = sketch.sketchDimensions.addDiameterDimension(circle, model.point((1.3, 0)))
        dimension.parameter.expression = '20 mm'
        cfg = fixture.config(result='feature', material='panel')
        _, custom, count = feature.build(sketch.profiles.item(0), geo.Settings(size=.4, gap=.2, margin=.1), cfg)
        before = sum(b.volume for b in comp.bRepBodies)
        dimension.parameter.expression = '30 mm'
        design.computeAll()
        healthy(custom)
        after = sum(b.volume for b in comp.bRepBodies)
        assert after > before, (before, after)
        return dict(cells=count, volume_before=before, volume_after=after)
    case('upstream_profile_recompute', upstream_profile)

    for material in ('cells', 'panel'):
        def trimmed(material=material):
            comp = fixture.component(design, 'Feature Trim ' + material)
            cfg = fixture.config(result='feature', material=material, width=2, height=2)
            settings = geo.Settings(shape='voronoi', size=.7, gap=.12, margin=.1,
                                    clip_boundary=True, corner_radius=.04)
            _, custom, count = feature.build(comp.xYConstructionPlane, settings, cfg)
            healthy(custom)
            before = sum(b.volume for b in comp.bRepBodies)
            custom.parameters.itemById('seed').expression = '2'
            design.computeAll()
            healthy(custom)
            after = sum(b.volume for b in comp.bRepBodies)
            assert abs(after - before) > 1e-7
            return dict(cells=count, volume_before=before, volume_after=after)
        case('trim_' + material, trimmed)

    def moved_plane():
        comp = fixture.component(design, 'Feature Moved Plane')
        data = comp.constructionPlanes.createInput()
        data.setByOffset(comp.yZConstructionPlane, model.value('27 mm'))
        plane = comp.constructionPlanes.add(data)
        cfg = fixture.config(result='feature', material='panel', width=2, height=2, direction='two')
        _, custom, count = feature.build(plane, geo.Settings(shape='hexagon', size=.5, gap=.2, margin=.1), cfg)
        custom.parameters.itemById('distance1').expression = '4 mm'
        design.computeAll()
        healthy(custom)
        bounds = comp.bRepBodies.item(0).boundingBox
        assert abs(bounds.minPoint.x - 2.5) < 1e-6 and abs(bounds.maxPoint.x - 3.1) < 1e-6
        return dict(cells=count, min=bounds.minPoint.asArray(), max=bounds.maxPoint.asArray())
    case('translated_rotated_plane', moved_plane)

    def user_expression():
        comp = fixture.component(design, 'Feature Expressions')
        parameter = design.userParameters.add('perforaHoleSize', model.value('5 mm'), 'mm', '')
        cfg = fixture.config(result='feature', material='panel', width=2, height=2,
                             _expressions={'size': 'perforaHoleSize'})
        _, custom, _ = feature.build(comp.xYConstructionPlane, geo.Settings(size=.5, gap=.2, margin=.1), cfg)
        before = sum(b.volume for b in comp.bRepBodies)
        parameter.expression = '3 mm'
        # Do not force computeAll: Fusion must follow the expression dependency.
        after = sum(b.volume for b in comp.bRepBodies)
        healthy(custom)
        assert abs(after - before) > 1e-6, (before, after)
        assert custom.parameters.itemById('size').expression == 'perforaHoleSize'
        return dict(before=before, after=after)
    case('user_expression_natural_recompute', user_expression)

    for shape, _ in entry.SHAPES:
        def shape_recompute(shape=shape):
            comp = fixture.component(design, 'Feature Shape ' + shape)
            cfg = fixture.config(result='feature', material='panel', width=2, height=2)
            settings = geo.Settings(shape=shape, size=.5, slot_length=.8, gap=.2, margin=.1,
                                    corner_radius=.04 if shape == 'voronoi' else 0)
            _, custom, count = feature.build(comp.xYConstructionPlane, settings, cfg)
            healthy(custom)
            before = sum(b.volume for b in comp.bRepBodies)
            nodes = design.timeline.count
            custom.parameters.itemById('size').expression = '4 mm'
            after = sum(b.volume for b in comp.bRepBodies)
            healthy(custom)
            assert count > 0 and abs(after - before) > 1e-7, (before, after)
            assert design.timeline.count == nodes
            return dict(cells=count, before=before, after=after)
        case('feature_shape_' + shape, shape_recompute)

    for direction, reverse, low, high in (
            ('one', False, .1, .5), ('one', True, -.3, .1),
            ('two', False, -.2, .5), ('symmetric', False, -.1, .3)):
        def extent(direction=direction, reverse=reverse, low=low, high=high):
            comp = fixture.component(design, 'Feature Extent ' + direction + str(reverse))
            cfg = fixture.config(result='feature', material='panel', width=2, height=2,
                                 direction=direction, reverse=reverse, start='1 mm',
                                 distance1='4 mm', distance2='3 mm')
            _, custom, _ = feature.build(comp.xYConstructionPlane,
                                         geo.Settings(size=.5, gap=.2, margin=.1), cfg)
            healthy(custom)
            bounds = comp.bRepBodies.item(0).boundingBox
            assert abs(bounds.minPoint.z - low) < 1e-6 and abs(bounds.maxPoint.z - high) < 1e-6
            return dict(min_z=bounds.minPoint.z, max_z=bounds.maxPoint.z)
        case('extent_' + direction + ('_reverse' if reverse else ''), extent)

    for name, changes in (
            ('all', dict(extent1='all')), ('to_object', dict(extent1='object')),
            ('taper', dict(taper1='2 deg')), ('component', dict(operation='component'))):
        def unsupported(changes=changes):
            nodes = design.timeline.count
            try:
                feature.validate(fixture.config(result='feature', **changes), design)
            except ValueError as error:
                assert design.timeline.count == nodes
                return dict(message=str(error))
            raise AssertionError('Unsupported Feature configuration was accepted')
        case('reject_' + name, unsupported)

    def archive_reopen():
        import tempfile
        with tempfile.TemporaryDirectory(prefix='perfora-feature-') as directory:
            archive = str(Path(directory) / 'feature.f3d')
            export = design.exportManager.createFusionArchiveExportOptions(archive)
            assert design.exportManager.execute(export)
            options = app.importManager.createFusionArchiveImportOptions(archive)
            opened = app.importManager.importToNewDocument(options)
            assert opened
            try:
                loaded = adsk.fusion.Design.cast(app.activeProduct)
                comp = next(c for c in loaded.allComponents if c.name == 'Feature Panel')
                custom = comp.features.customFeatures.item(0)
                healthy(custom)
                before = sum(b.volume for b in comp.bRepBodies)
                custom.parameters.itemById('distance1').expression = '6 mm'
                after = sum(b.volume for b in comp.bRepBodies)
                healthy(custom)
                assert abs(after - before * 1.5) < 1e-6, (before, after)
                return dict(before=before, after=after, parameters=custom.parameters.count)
            finally:
                opened.close(False)
                doc.activate()
    case('archive_reopen_recompute', archive_reopen)

finally:
    save('complete')
    doc.close(False)
    if original:
        original.activate()
print('PERFORA_FEATURE_REGRESSION', output)
