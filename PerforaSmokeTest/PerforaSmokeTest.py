# SPDX-License-Identifier: GPL-3.0-only
"""Run from Fusion > Scripts. Exercises real CAD operations without mocks."""
import importlib.util
import json
import math
from pathlib import Path
import sys
import traceback

import adsk.core
import adsk.fusion


def load_package():
    here = Path(__file__).resolve().parent
    candidates = [here.parent / 'Perfora', here.parent.parent / 'AddIns/Perfora']
    directory = next((p for p in candidates if (p / '__init__.py').exists()), None)
    if directory is None:
        raise RuntimeError('Сначала установите Perfora рядом с тестовым скриптом.')
    name = '_perforator_native_test'
    # Re-running the suite in the same Fusion process must load patched adapters.
    for key in tuple(sys.modules):
        if key == name or key.startswith(name + '.'):
            del sys.modules[key]
    spec = importlib.util.spec_from_file_location(name, directory / '__init__.py', submodule_search_locations=[str(directory)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    from importlib import import_module
    return import_module(name + '.model'), import_module(name + '.geometry')


def config(**changes):
    data = dict(boundary='rectangle', width=4.0, height=3.0, result='extrude', material='cells',
                operation='body', direction='one', reverse=False, start='0 mm', bodies=[])
    for side in ('1', '2'):
        data.update({'extent' + side: 'distance', 'distance' + side: '2 mm',
                     'target' + side: None, 'object_offset' + side: '0 mm', 'taper' + side: '0 deg'})
    data.update(changes)
    return data


def component(design, name):
    occurrence = design.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    occurrence.component.name = name
    return occurrence.component


def plate(comp):
    sketch = comp.sketches.addWithoutEdges(comp.xYConstructionPlane)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-2, -1.5, 0), adsk.core.Point3D.create(2, 1.5, 0))
    data = comp.features.extrudeFeatures.createInput(sketch.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    data.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByString('4 mm')),
                          adsk.fusion.ExtentDirections.PositiveExtentDirection)
    feature = comp.features.extrudeFeatures.add(data)
    sketch.isVisible = False
    body = feature.bodies.item(0)
    top = next(face for face in body.faces if isinstance(face.geometry, adsk.core.Plane)
               and abs(face.boundingBox.minPoint.z - 0.4) < 1e-6
               and abs(face.boundingBox.maxPoint.z - 0.4) < 1e-6)
    return body, top


def run(context):
    app = adsk.core.Application.get()
    original = app.activeDocument
    results = []
    doc = None
    output = Path.home() / 'Library/Logs/Perfora' if sys.platform == 'darwin' else Path.home() / 'Perfora-test-results'
    output.mkdir(parents=True, exist_ok=True)
    try:
        model, geo = load_package()
        doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        settings = geo.Settings(size=0.5, gap=0.2, margin=0.2, limit=500)

        def case(name, action):
            try:
                detail = action()
                results.append(dict(name=name, passed=True, detail=detail))
            except Exception:
                results.append(dict(name=name, passed=False, error=traceback.format_exc()))

        for shape in ('circle', 'hexagon', 'square', 'slot'):
            def check_shape(shape=shape):
                comp = component(design, 'Profiles ' + shape)
                _, face = plate(comp)
                s = geo.Settings(shape=shape, size=0.5, slot_length=0.9, gap=0.2, margin=0.2, limit=500)
                sketch, feature, count = model.build(face, s, config(result='profiles'))
                assert feature is None and sketch.profiles.count == count and count > 5
                return dict(cells=count, profiles=sketch.profiles.count)
            case('profiles_' + shape, check_shape)

        for operation in ('cut', 'join', 'intersect', 'body', 'component'):
            def check_operation(operation=operation):
                comp = component(design, 'Operation ' + operation)
                body, face = plate(comp)
                before = body.volume
                data = config(operation=operation, reverse=operation in ('cut', 'intersect'), bodies=[body])
                if operation in ('body', 'component'):
                    data['material'] = 'panel'
                _, feature, count = model.build(face, settings, data)
                assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
                assert feature.bodies.count > 0
                if operation == 'cut':
                    assert body.volume < before
                if operation == 'join':
                    assert body.volume > before
                if operation == 'intersect':
                    assert sum(b.volume for b in feature.bodies) < before
                if operation == 'component':
                    assert feature.bodies.item(0).parentComponent != comp
                if operation in ('body', 'component'):
                    expected = (4 * 3 - count * math.pi * (settings.size / 2) ** 2) * 0.2
                    actual = sum(b.volume for b in feature.bodies)
                    assert abs(actual - expected) < 1e-5, (actual, expected)
                return dict(cells=count, bodies=feature.bodies.count)
            case('operation_' + operation, check_operation)

        for direction in ('symmetric', 'two'):
            def check_direction(direction=direction):
                comp = component(design, 'Direction ' + direction)
                _, feature, _ = model.build(comp.xYConstructionPlane, settings,
                                            config(direction=direction, material='panel'))
                body = feature.bodies.item(0)
                height = body.boundingBox.maxPoint.z - body.boundingBox.minPoint.z
                expected = 0.2 if direction == 'symmetric' else 0.4
                assert abs(height - expected) < 1e-5, (height, expected)
                return dict(height_cm=height)
            case('direction_' + direction, check_direction)

        def check_through_all():
            comp = component(design, 'Through all')
            body, face = plate(comp)
            _, feature, count = model.build(face, settings, config(operation='cut', extent1='all', reverse=True, bodies=[body]))
            assert len([f for f in body.faces if isinstance(f.geometry, adsk.core.Cylinder)]) == count
            assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
            return dict(through_holes=count)
        case('through_all', check_through_all)

        def check_to_object():
            comp = component(design, 'To object')
            plane_input = comp.constructionPlanes.createInput()
            plane_input.setByOffset(comp.xYConstructionPlane, adsk.core.ValueInput.createByString('5 mm'))
            target = comp.constructionPlanes.add(plane_input)
            _, feature, _ = model.build(comp.xYConstructionPlane, settings,
                                        config(material='panel', extent1='object', target1=target,
                                               object_offset1='-2 mm'))
            assert abs(feature.bodies.item(0).boundingBox.maxPoint.z - 0.3) < 1e-5
            return '3 mm'
        case('to_object_offset', check_to_object)

        def check_profile_with_void():
            comp = component(design, 'Profile with void')
            sketch = comp.sketches.addWithoutEdges(comp.xZConstructionPlane)
            circles = sketch.sketchCurves.sketchCircles
            circles.addByCenterRadius(adsk.core.Point3D.create(0, 0, 0), 2)
            circles.addByCenterRadius(adsk.core.Point3D.create(0, 0, 0), 0.5)
            profile = next(p for p in sketch.profiles if p.profileLoops.count == 2)
            output_sketch, feature, count = model.build(profile, settings, config(material='panel'))
            assert feature.bodies.count == 1
            assert feature.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
            assert model.selected_profiles(output_sketch, 'panel').count == 1
            return dict(cells=count, volume_cm3=feature.bodies.item(0).volume)
        case('rotated_profile_with_void', check_profile_with_void)

        report = dict(fusion_version=app.version, tests=results,
                      passed=sum(r['passed'] for r in results), total=len(results))
        (output / 'native-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        passed = report['passed'] == report['total']
        if passed:
            doc.close(False)
            doc = None
        app.userInterface.messageBox(
            '%d / %d проверок пройдено.\nОтчёт: %s\n%s' %
            (report['passed'], report['total'], output / 'native-smoke.json',
             'Тестовый документ закрыт без сохранения.' if passed else 'Документ с результатами оставлен открытым для диагностики.'),
            'Perfora — проверка в Fusion')
    except Exception:
        error = traceback.format_exc()
        (output / 'native-smoke-error.txt').write_text(error, encoding='utf-8')
        app.userInterface.messageBox(error, 'Perfora — ошибка проверки')
    finally:
        if original and original.isValid:
            original.activate()
