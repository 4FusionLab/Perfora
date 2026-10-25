# SPDX-License-Identifier: GPL-3.0-only
"""Native command transactions in a disposable document.

From the native Python console: ui=runpy.run_path(..., init_globals={...});
ui['prepare'](); ui['preview']('fast'/'exact'); click actual OK/Cancel.
Call verify(created), native Undo/Redo and verify_undo()/verify(True), or
begin_edit() then edit_preview() and click actual OK/Cancel before end_edit().
finish() closes only the disposable test document and restores the original.
"""
import json
from pathlib import Path
import runpy
import adsk.core
import adsk.fusion

root=Path(__file__).resolve().parents[1]
fixture=runpy.run_path(str(root/'tests/fusion_organic_regression.py'),init_globals={'fixtures_only':True})
entry=fixture['entry'];app=fixture['app'];original=app.activeDocument
original_state=(original.name,original.isModified)
kind=globals().get('kind','plane');shape=globals().get('shape','reaction_diffusion');mode=globals().get('result_mode','feature')
selected=globals().get('selected_face')
snapshot=adsk.fusion.TemporaryBRepManager.get().copy(selected.body) if selected else None
doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
design=adsk.fusion.Design.cast(app.activeProduct);component=design.rootComponent
if selected:
    base=component.features.baseFeatures.add();base.startEdit();component.bRepBodies.add(snapshot,base);base.finishEdit()
    body=base.bodies.item(0)
    face=min(body.faces,key=lambda f:abs(f.area-selected.area)+f.pointOnFace.distanceTo(selected.pointOnFace))
else:
    body,face=fixture['fixture'](component,kind)
baseline=(design.timeline.count,component.sketches.count,body.volume)
session=None;edit_volume=None;edit_value=None
report=dict(shape=shape,kind=kind,mode=mode,fusion=app.version,stage='opening',passed=False,checks=[])
output=Path.home()/'Library/Logs/Perfora/organic'/('ui-'+kind+'-'+shape+'-'+mode+'.json')


def save():output.write_text(json.dumps(report,indent=2))


def choose(s,key,options,value):
    if key=='shape':s.set_shape(value);return
    s.inputs[key].listItems.item(next(i for i,(k,_) in enumerate(options) if k==value)).isSelected=True


def prepare():
    global session
    session=entry._sessions[-1];s=session;d=s.inputs;s.updating=True
    try:
        d['preview'].value=False;d['source'].clearSelection();assert d['source'].addSelection(face)
        choose(s,'shape',entry.SHAPES,shape);choose(s,'result',entry.RESULTS,mode)
        choose(s,'operation',entry.OPERATIONS,'cut')
        d['size'].expression='5 mm' if selected else '4.5 mm';s.sync_dimensions('size')
        d['gap'].expression='1.5 mm' if selected else '0.55 mm';d['margin'].expression='3 mm' if selected else '0.7 mm'
        d['organic_bridges'].value=globals().get('bridges',False);d['organic_open'].expression='58' if shape=='topographic' else '48';d['organic_direction'].expression='90 deg' if shape=='directional_fibers' else '0 deg'
        d['clip_boundary'].value=True;d['distance1'].expression='8 mm' if kind=='freeform' else '2.2 mm';d['reverse'].value=True
        d['bodies'].clearSelection();d['bodies'].addSelection(body)
    finally:s.updating=False
    s.update_visibility();source,settings,cfg=s.read()
    assert settings.shape==shape and settings.layout=='grid'
    assert not d['layout'].isVisible and not d['surface_layout'].isVisible
    assert d['seed'].isVisible and d['organic_direction'].isVisible
    assert not d['organic_open'].isVisible
    assert d['organic_variation'].isVisible==(shape=='blue_noise')
    assert entry.SHAPES[-1][0]=='voronoi'
    report.update(stage='ready',settings=str(settings));app.activeViewport.fit();save();return report['stage']


def preview(kind='fast'):
    choose(session,'preview_mode',entry.PREVIEW_MODES,kind)
    session.inputs['preview'].value=True;session.command.doExecutePreview()
    return kind


def check_preview():
    assert not session.preview_error,session.preview_error
    assert session._status_text and 'holes.' in session._status_text,session._status_text
    report['checks'].append(dict(preview=session.chosen('preview_mode',entry.PREVIEW_MODES),status=session._status_text))
    save();return session._status_text


def verify(created):
    assert app.userInterface.activeCommand not in (entry.COMMAND_ID,entry.parametric.EDIT_COMMAND_ID)
    current=component.bRepBodies.item(0)
    if created:
        if mode=='profiles':assert component.sketches.count==baseline[1]+1 and abs(current.volume-baseline[2])<1e-8
        else:assert 0<current.volume<baseline[2]
        fixture['healthy'](design)
    else:
        assert (design.timeline.count,component.sketches.count)==baseline[:2]
        assert abs(current.volume-baseline[2])<1e-8
    assert component.customGraphicsGroups.count==0
    report.update(passed=True,stage='created' if created else 'cancelled');save();return report['stage']


def verify_undo():
    current=component.bRepBodies.item(0)
    assert (design.timeline.count,component.sketches.count)==baseline[:2]
    assert abs(current.volume-baseline[2])<1e-8
    report['checks'].append('native Undo restored the fixture');save();return True


def begin_edit():
    global edit_volume,edit_value
    custom=component.features.customFeatures.item(0)
    edit_volume=component.bRepBodies.item(0).volume
    key='size'
    edit_value=custom.parameters.itemById(key).value
    app.userInterface.activeSelections.clear();app.userInterface.activeSelections.add(custom)
    app.userInterface.commandDefinitions.itemById(entry.parametric.EDIT_COMMAND_ID).execute()


def edit_preview():
    global session
    session=entry._sessions[-1]
    key='size'
    assert abs(session.inputs[key].value-edit_value)<1e-8
    size_id=session.dimension_id(entry.SIZE_FIELDS,shape)
    session.inputs[size_id].expression=str(edit_value+.05)+' cm'
    session.sync_dimensions(size_id)
    preview('exact');return 'edit preview requested'


def end_edit(accepted):
    assert app.userInterface.activeCommand!=entry.parametric.EDIT_COMMAND_ID
    volume=component.bRepBodies.item(0).volume
    custom=component.features.customFeatures.item(0)
    key='size'
    delta=.05 if accepted else 0
    assert abs(custom.parameters.itemById(key).value-edit_value-delta)<1e-8
    assert (abs(volume-edit_volume)>1e-7) if accepted else (abs(volume-edit_volume)<1e-8)
    fixture['healthy'](design)
    report['checks'].append('Edit Feature '+('OK' if accepted else 'Cancel'));save();return True


def finish():
    assert app.userInterface.activeCommand not in (entry.COMMAND_ID,entry.parametric.EDIT_COMMAND_ID)
    assert report['passed'],report
    doc.close(False);original.activate()
    report['original_unchanged']=(original.name,original.isModified)==original_state
    report['passed']=report['passed'] and report['original_unchanged'];save();return report


save()
app.userInterface.commandDefinitions.itemById(entry.COMMAND_ID).execute()
