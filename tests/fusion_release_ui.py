# SPDX-License-Identifier: GPL-3.0-only
"""Interactive integration acceptance. Call finish only after real OK/Cancel.

Inputs: kind='plane'/'cylinder'/'cone'/'freeform', regions=1/2,
layout='running_bond', result_mode='feature'/'extrude'/'profiles'.
Uses only a disposable document and restores the original after finish.
"""
import json
from pathlib import Path
import runpy
import sys
import traceback
import adsk.core
import adsk.fusion

root=Path(__file__).resolve().parents[1]
entry=next(m for m in tuple(sys.modules.values()) if str(getattr(m,'__file__',''))==str(root/'Perfora/Perfora.py'))
app=adsk.core.Application.get();original=app.activeDocument
original_state=(original.name,original.isModified)
fixture=runpy.run_path(str(root/'tests/fusion_release_integration.py'),init_globals={'only_cases':('__fixtures_only__',)})
kind=globals().get('kind','cylinder');regions=globals().get('regions',2)
layout=globals().get('layout','running_bond');mode=globals().get('result_mode','feature')
doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
design=adsk.fusion.Design.cast(app.activeProduct);component=design.rootComponent
selected=[];bodies=[]
if kind=='plane':
    planar=runpy.run_path(str(root/'PerforaSmokeTest/PerforaSmokeTest.py'))
    body,face=planar['plate'](component);bodies.append(body)
    if regions==2:
        sketch=component.sketches.addWithoutEdges(face)
        for x in (-.95,.95):sketch.sketchCurves.sketchCircles.addByCenterRadius(entry.model.point((x,0)),.8)
        selected=list(sketch.profiles);sketch.isVisible=False
    else:selected=[face]
else:
    for i in range(regions):
        body,face=fixture['face_fixture'](component,kind,4*i);bodies.append(body);selected.append(face)

baseline=(design.timeline.count,component.sketches.count,tuple(b.volume for b in bodies))
output=Path.home()/'Library/Logs/Perfora/release-ui.json'
report=dict(passed=False,stage='opening',kind=kind,regions=regions,layout=layout,result_mode=mode,fusion=app.version)
lifetime=[];session=None

def save():output.write_text(json.dumps(report,indent=2))

class Activate(adsk.core.CommandEventHandler):
    def __init__(self,s):super().__init__();self.s=s;self.done=False
    def notify(self,args):
        if self.done:return
        self.done=True;s=self.s
        try:
            s.updating=True
            try:
                d=s.inputs;d['preview'].value=False
                d['source'].clearSelection()
                for source in selected:assert d['source'].addSelection(source)
                d['result'].listItems.item(next(i for i,(key,_) in enumerate(entry.RESULTS) if key==mode)).isSelected=True
                d['operation'].listItems.item(1).isSelected=True
                d['size'].expression='3.5 mm';s.sync_dimensions('size')
                d['gap'].expression='3 mm';d['margin'].expression='1.2 mm'
                d['clip_boundary'].value=True;d['distance1'].expression='2 mm';d['reverse'].value=True
                d['bodies'].clearSelection()
                for body in bodies:d['bodies'].addSelection(body)
            finally:s.updating=False
            s.update_visibility()
            key='layout' if kind=='plane' else 'surface_layout'
            choices=entry.LAYOUTS if kind=='plane' else s.surface_choices
            s.inputs[key].listItems.item(next(i for i,(k,_) in enumerate(choices) if k==layout)).isSelected=True
            s.update_visibility()
            source,settings,cfg=s.read()
            assert isinstance(source,list)==(regions>1)
            assert settings.layout==layout
            if kind!='plane':
                assert not s.inputs['layout'].isVisible and s.inputs['surface_layout'].isVisible
                assert 'chevron' not in dict(choices) if kind in ('cone','cylinder') else 'chevron' in dict(choices)
            report.update(stage='ready',choices=[label for _,label in choices],settings=str(settings))
            app.activeViewport.fit()
        except Exception:report.update(stage='failed',error=traceback.format_exc())
        save()

class Created(adsk.core.CommandCreatedEventHandler):
    def notify(self,args):
        global session
        session=entry._sessions[-1]
        handler=Activate(session);lifetime.append(handler);args.command.activate.add(handler)


def preview(kind='fast'):
    assert report['stage']=='ready',report
    session.inputs['preview_mode'].listItems.item(0 if kind=='fast' else 1).isSelected=True
    session.inputs['preview'].value=True
    session.command.doExecutePreview()
    report['preview_requested']=kind;save()


def check_preview():
    assert not session.preview_error,session.preview_error
    assert session._status_text and 'holes.' in session._status_text,session._status_text
    report['preview_status']=session._status_text;save();return report['preview_status']


def verify_undo():
    assert app.userInterface.activeCommand != entry.COMMAND_ID
    assert (design.timeline.count, component.sketches.count) == baseline[:2]
    assert all(abs(b.volume-before)<1e-8 for b,before in zip(bodies,baseline[2]))
    report['undo_passed']=True;save();return True


def finish(created):
    try:
        assert app.userInterface.activeCommand!=entry.COMMAND_ID
        assert report['stage']=='ready',report
        if created:
            if mode=='profiles':
                assert component.sketches.count==baseline[1]+regions
                assert all(abs(b.volume-before)<1e-8 for b,before in zip(bodies,baseline[2]))
            else:
                assert all(b.isSolid and 0<b.volume<before for b,before in zip(bodies,baseline[2]))
                if mode=='feature':
                    custom=component.features.customFeatures.item(0);fixture['healthy'](custom)
                    assert len(entry.parametric.source_entities(custom))==regions
        else:
            assert (design.timeline.count,component.sketches.count)==baseline[:2]
            assert all(abs(b.volume-before)<1e-8 for b,before in zip(bodies,baseline[2]))
        assert component.customGraphicsGroups.count==0
        if created and report.get('undo_passed'): report['redo_passed']=True
        report.update(passed=True,stage='complete',transaction='created' if created else 'cancelled')
    except Exception:report.update(passed=False,stage='failed',error=traceback.format_exc())
    finally:
        definition.commandCreated.remove(created_handler)
        doc.close(False);original.activate()
        report['original_unchanged']=(original.name,original.isModified)==original_state
        report['passed']=report['passed'] and report['original_unchanged'];save()
    return report

definition=app.userInterface.commandDefinitions.itemById(entry.COMMAND_ID)
created_handler=Created();lifetime.append(created_handler)
definition.commandCreated.add(created_handler)
save();definition.execute()
