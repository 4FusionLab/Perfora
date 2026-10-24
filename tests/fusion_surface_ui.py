# SPDX-License-Identifier: GPL-3.0-only
"""Registered command acceptance. Click real OK/Cancel, then call finish().

runpy.run_path(..., init_globals={'mode': 'fast'}) returns the finish function.
The test creates its own unsaved document and restores the previous document.
"""
import json
import math
from pathlib import Path
import sys
import traceback

import adsk.core
import adsk.fusion

app = adsk.core.Application.get()
entry = next(m for m in tuple(sys.modules.values()) if str(getattr(m, '__file__', '')) ==
             str(Path(__file__).resolve().parents[1] / 'Perfora/Perfora.py'))
original = app.activeDocument
original_design = adsk.fusion.Design.cast(app.activeProduct)
original_count = original_design.timeline.count
original_volume = sum(b.volume for b in original_design.rootComponent.bRepBodies)
kind = globals().get('kind','cylinder')
selected_snapshot=selected_reference=None
if kind=='selected':
    selected_body=original_design.rootComponent.bRepBodies.itemByName(globals()['source_body_name'])
    selected_reference=next(f for f in selected_body.faces if f.tempId==globals()['source_face_id'])
    selected_area=selected_reference.area
    selected_type=selected_reference.geometry.objectType
    selected_snapshot=adsk.fusion.TemporaryBRepManager.get().copy(selected_body)
doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
doc.name = 'Perfora Surface Acceptance'
design = adsk.fusion.Design.cast(app.activeProduct)
comp = design.rootComponent
manager = adsk.fusion.TemporaryBRepManager.get()
kind = globals().get('kind','cylinder')
a, b = adsk.core.Point3D.create(), adsk.core.Point3D.create(0, 0, 3.)
if kind=='selected':
    base=comp.features.baseFeatures.add();base.startEdit();comp.bRepBodies.add(selected_snapshot,base);base.finishEdit()
    body=base.bodies.item(0)
    face=min((f for f in body.faces if f.geometry.objectType==selected_type),key=lambda f:abs(f.area-selected_area))
elif kind=='freeform':
    profiles=[]
    for z,w,h,dx in ((0,3.,2.,0),(1.5,3.4,1.8,.1),(3.,2.7,2.1,.2)):
        data=comp.constructionPlanes.createInput()
        data.setByOffset(comp.xYConstructionPlane,adsk.core.ValueInput.createByReal(z))
        plane=comp.constructionPlanes.add(data)
        sketch=comp.sketches.add(plane)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(-w/2+dx,-h/2,0),adsk.core.Point3D.create(w/2+dx,h/2,0))
        profiles.append(sketch.profiles.item(0))
    data=comp.features.loftFeatures.createInput(adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    for profile in profiles:
        data.loftSections.add(profile)
    loft=comp.features.loftFeatures.add(data)
    body=loft.bodies.item(0)
    face=max((f for f in body.faces if isinstance(f.geometry,adsk.core.NurbsSurface)),key=lambda f:f.area)
else:
    body = manager.createCylinderOrCone(a, 2., b, 1.4 if kind=='cone' else 2.)
    assert manager.booleanOperation(body, manager.createCylinderOrCone(a, 1.8, b, 1.2 if kind=='cone' else 1.8),
                                    adsk.fusion.BooleanTypes.DifferenceBooleanType)
    base = comp.features.baseFeatures.add()
    base.startEdit()
    comp.bRepBodies.add(body, base)
    base.finishEdit()
    body = base.bodies.item(0)
    face = max((f for f in body.faces if isinstance(f.geometry, (adsk.core.Cylinder,adsk.core.Cone))),key=lambda f:f.area)
initial_sketches=comp.sketches.count
initial_base_features=comp.features.baseFeatures.count
timeline = design.timeline.count
volume = body.volume
mode = globals().get('mode', 'fast')
pattern = globals().get('shape', 'voronoi')
result_type = globals().get('result_type','feature')
report = dict(passed=False, mode=mode, shape=pattern, kind=kind,checkout=entry.__file__)
output = Path.home() / ('Library/Logs/Perfora/surface-ui-' + mode + ('-'+kind if kind!='cylinder' else '') + ('-'+result_type if result_type!='feature' else '') + ('-'+pattern if pattern!='circle' else '') + '.json')
output.parent.mkdir(parents=True, exist_ok=True)
lifetime = []


def save():
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')


class Activate(adsk.core.CommandEventHandler):
    def __init__(self, session):
        super().__init__()
        self.session, self.done = session, False

    def notify(self, args):
        if self.done:
            return
        self.done = True
        s = self.session
        try:
            s.updating = True
            try:
                s.inputs['preview'].value = False
                s.inputs['preview_mode'].listItems.item(0).isSelected = True
                s.inputs['shape'].listItems.item(0).isSelected = True
                s.inputs['size'].expression = '4 mm'
                s.sync_dimensions('size')
                s.inputs['gap'].expression = '2 mm'
                s.inputs['margin'].expression = '2 mm'
                s.inputs['distance1'].expression = '3 mm'
                s.inputs['cylinder_start'].expression = '0 deg'
                if kind!='selected':s.inputs['cylinder_sweep'].expression = '360 deg'
                s.inputs['axial_start'].expression = '0 mm'
                s.inputs['axial_length'].expression = '0 mm'
                s.inputs['surface_layout'].listItems.item(1).isSelected = True
                s.inputs['result'].listItems.item(next(i for i,p in enumerate(entry.RESULTS) if p[0]==result_type)).isSelected = True
                s.inputs['clip_boundary'].value = True
                s.inputs['material'].listItems.item(1).isSelected=True
                s.inputs['source'].clearSelection()
                s.inputs['source'].addSelection(face)
            finally:
                s.updating = False
            s.update_visibility()
            assert s.inputs['cylinder_group'].isVisible
            assert all(s.inputs[k].isVisible for k in
                       ('result','material','clip_boundary','center_point','surface_layout'))
            assert not s.inputs['layout'].isVisible and not s.inputs['spread_radius'].isVisible
            assert not s.inputs['grid_angle'].isVisible
            assert [i.name for i in s.inputs['surface_layout'].listItems]==[label for _,label in s.surface_choices]
            assert s.inputs['output_group'].isVisible == (result_type!='profiles')
            source, settings, cfg = s.read()
            assert cfg['surface'] and cfg['result']==result_type
            if kind=='selected':
                expected=entry.surface.Chart(source).sweep
                assert abs(cfg['cylinder_sweep']-expected)<1e-10,'Display rounding changed the actual face sweep'
                report['exact_sector_angle']=True
            # Switching back to a planar source restores native planar controls.
            planar = next(f for f in body.faces if isinstance(f.geometry, adsk.core.Plane))
            s.inputs['source'].clearSelection()
            s.inputs['source'].addSelection(planar)
            s.update_visibility()
            assert s.inputs['result'].isVisible and not s.inputs['cylinder_group'].isVisible
            assert s.chosen('material',entry.MATERIALS)=='panel'
            s.inputs['source'].clearSelection()
            s.inputs['source'].addSelection(face)
            s.update_visibility()
            if kind!='freeform':
                s.inputs['distance1'].expression = str(entry.surface.Chart(face).radius+1)+' cm'
                try:
                    s.read()
                    raise AssertionError('Unsafe depth accepted')
                except ValueError as error:
                    assert 'radius' in str(error)
            s.inputs['distance1'].expression = '3 mm'
            for shape, _ in entry.SHAPES:
                s.inputs['shape'].listItems.item(next(i for i, p in enumerate(entry.SHAPES) if p[0] == shape)).isSelected = True
                s.update_visibility()
                s.read()
            s.inputs['shape'].listItems.item(next(i for i,p in enumerate(entry.SHAPES) if p[0]==pattern)).isSelected = True
            if pattern=='voronoi':
                s.inputs['cell_spacing'].expression = '7 mm'
                s.sync_dimensions('cell_spacing')
                s.inputs['gap'].expression = '1 mm'
                s.inputs['margin'].expression = '1.5 mm'
                s.inputs['round_corners'].value = True
                s.inputs['corner_radius'].expression = '0.5 mm'
            s.update_visibility()
            s.inputs['preview_mode'].listItems.item(0 if mode == 'fast' else 1).isSelected = True
            s.inputs['preview'].value = True
            args.command.doExecutePreview()
            camera = app.activeViewport.camera
            camera.eye = adsk.core.Point3D.create(7, -9, 7)
            camera.target = adsk.core.Point3D.create(0, 0, 1.5)
            camera.upVector = adsk.core.Vector3D.create(0, 0, 1)
            camera.isFitView = True
            app.activeViewport.camera = camera
            report.update(passed=True, stage='ready', common_controls=True, planar_switch=True,planar_material_restored=True,
                          unsafe_depth_rejected=kind!='freeform', supported_shapes=13)
        except Exception:
            report.update(error=traceback.format_exc())
        save()


class Created(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            s = entry._sessions[-1]
            lifetime.append(s)
            activate = Activate(s)
            lifetime.append(activate)
            args.command.activate.add(activate)
        except Exception:
            report.update(error=traceback.format_exc())
            save()


def verify(created):
    assert app.userInterface.activeCommand != definition.id, 'Click OK or Cancel first.'
    assert report['passed'], report
    if created and result_type=='profiles':
        assert comp.sketches.count==initial_sketches+1 and comp.features.combineFeatures.count==0
        assert abs(comp.bRepBodies.item(0).volume-volume)<1e-8
        report['sketch_curves']=comp.sketches.item(comp.sketches.count-1).sketchCurves.count
    elif created:
        result = comp.features.combineFeatures.item(0)
        assert result.healthState == adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
        assert result.bodies.item(0).isSolid and result.bodies.item(0).volume < volume
        if result_type=='feature':
            custom=comp.features.customFeatures.item(0)
            assert custom.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
            assert custom.parameters.itemById('cylinder_sweep')
            report['feature_created']=True
        report.update(volume_after=result.bodies.item(0).volume)
    else:
        assert design.timeline.count == timeline and abs(comp.bRepBodies.item(0).volume - volume) < 1e-8
        assert comp.features.combineFeatures.count == 0 and comp.features.baseFeatures.count == initial_base_features
    assert comp.sketches.count == initial_sketches+(1 if created and result_type=='profiles' else 0)
    assert comp.customGraphicsGroups.count == 0
    report.update(transaction='created' if created else 'cancelled', transaction_passed=True)
    save()
    return report


def finish(created=False,close=True):
    try:
        verify(created)
    except Exception:
        report.update(passed=False, transaction_error=traceback.format_exc())
    finally:
        if close:
            definition.commandCreated.remove(handler)
            doc.close(False)
            original.activate()
        report['original_unchanged'] = (original_design.timeline.count == original_count and
            abs(sum(b.volume for b in original_design.rootComponent.bRepBodies) - original_volume) < 1e-9)
        save()
    return report


definition = app.userInterface.commandDefinitions.itemById(entry.COMMAND_ID)
handler = Created()
lifetime.append(handler)
definition.commandCreated.add(handler)
if kind=='selected':
    app.userInterface.activeSelections.clear();app.userInterface.activeSelections.add(face)
definition.execute()
