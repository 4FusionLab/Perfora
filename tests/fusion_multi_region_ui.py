# SPDX-License-Identifier: GPL-3.0-only
"""Future interactive acceptance. Leaves the registered command open.

Run with runpy and keep the returned namespace. result_mode is profiles,
extrude, or feature (default). Call preview('fast'), preview('exact'), then
click real OK/Cancel and call finish(True/False). A ready report is not a pass.
Not executed during offline development.
"""
import json
from pathlib import Path
import runpy
import sys
import traceback

import adsk.core
import adsk.fusion

root=Path(__file__).resolve().parents[1]
entry=globals().get('entry') or next(m for m in tuple(sys.modules.values())
    if str(getattr(m,'__file__',''))==str(root/'Perfora/Perfora.py'))
mode=globals().get('result_mode','feature')
assert mode in ('profiles','extrude','feature')
app=adsk.core.Application.get()
original=app.activeDocument
original_design=adsk.fusion.Design.cast(app.activeProduct)
original_state=(original_design.timeline.count,sum(b.volume for b in original_design.rootComponent.bRepBodies))
fixture=runpy.run_path(str(root/'PerforaSmokeTest/PerforaSmokeTest.py'))
definition=app.userInterface.commandDefinitions.itemById(entry.COMMAND_ID)
assert definition,'Run the registered add-in from this checkout first'
doc=app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
design=adsk.fusion.Design.cast(app.activeProduct)
comp=design.rootComponent
body,face=fixture['plate'](comp)
boundary=comp.sketches.addWithoutEdges(face)
for x in (-.95,.95):
    boundary.sketchCurves.sketchCircles.addByCenterRadius(entry.model.point((x,0)),.8)
selected=list(boundary.profiles)
assert len(selected)==2
baseline=(design.timeline.count,comp.sketches.count,body.volume)
report=dict(stage='opening',passed=False,result_mode=mode,fusion=app.version,addon=str(entry.__file__))
output=Path.home()/'Library/Logs/Perfora/multi-region-ui.json'
output.parent.mkdir(parents=True,exist_ok=True)
lifetime=[]
session=None


def save():
    output.write_text(json.dumps(report,indent=2))


class Activate(adsk.core.CommandEventHandler):
    def __init__(self,s):
        super().__init__()
        self.s,self.done=s,False
    def notify(self,args):
        if self.done:return
        self.done=True
        try:
            s=self.s
            s.updating=True
            try:
                s.inputs['preview'].value=False
                s.inputs['result'].listItems.item(next(i for i,(key,_) in enumerate(entry.RESULTS) if key==mode)).isSelected=True
                s.inputs['source'].clearSelection()
                for source in selected:s.inputs['source'].addSelection(source)
                s.inputs['size'].expression='2.5 mm'
                s.inputs['gap'].expression='1.2 mm'
                s.inputs['margin'].expression='.8 mm'
                s.inputs['clip_boundary'].value=True
                s.inputs['reverse'].value=True
            finally:
                s.updating=False
            s.update_visibility()
            sources,settings,cfg=s.read()
            assert len(sources)==2 and len(cfg['bodies'])==1
            assert s.inputs['source_info'].isVisible
            assert entry.model.native(cfg['bodies'][0])==body
            report.update(stage='ready',selected_regions=len(sources),objects=len(cfg['bodies']))
        except Exception:
            report.update(stage='failed',error=traceback.format_exc())
        save()


class Created(adsk.core.CommandCreatedEventHandler):
    def notify(self,args):
        global session
        try:
            session=entry._sessions[-1]
            assert session.command==args.command
            session.inputs['preview'].value=False
            handler=Activate(session)
            lifetime.append(handler)
            args.command.activate.add(handler)
        except Exception:
            report.update(stage='failed',error=traceback.format_exc())
            save()


def preview(kind='fast'):
    assert session is not None and kind in ('fast','exact')
    session.inputs['preview_mode'].listItems.item(0 if kind=='fast' else 1).isSelected=True
    session.inputs['preview'].value=True
    session.update_visibility()
    session.command.doExecutePreview()
    assert not session.preview_error,session.preview_error
    expected='Fast preview.' if kind=='fast' else {'profiles':'Sketch ready.','extrude':'Extrude ready.','feature':'Feature ready.'}[mode]
    assert expected in (session._status_text or ''),'Preview has not completed: '+str(session._status_text)
    report['preview_'+kind]=dict(status=session._status_text,
        holes=len(session.renderer.cells or ()),seconds=session.renderer.last_seconds)
    save()
    return report['preview_'+kind]


def finish(created=False):
    try:
        assert app.userInterface.activeCommand!=entry.COMMAND_ID,'Click the real OK or Cancel first'
        assert report['stage']=='ready',report
        if created:
            if mode=='profiles':
                assert abs(body.volume-baseline[2])<1e-9
                assert comp.sketches.count==baseline[1]+2
            elif mode=='extrude':
                assert body.isSolid and 0<body.volume<baseline[2]
                assert comp.features.extrudeFeatures.count==3
            else:
                assert comp.features.customFeatures.count==1
                custom=comp.features.customFeatures.item(0)
                assert len(entry.parametric.source_entities(custom))==2
                assert custom.healthState==adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState
                assert body.isSolid and 0<body.volume<baseline[2]
        else:
            assert (design.timeline.count,comp.sketches.count)==baseline[:2]
            assert abs(body.volume-baseline[2])<1e-9
        report.update(passed=True,stage='complete',transaction='created' if created else 'cancelled')
    except Exception:
        report.update(passed=False,stage='failed',error=traceback.format_exc())
    finally:
        definition.commandCreated.remove(handler)
        doc.close(False)
        original.activate()
        report['original_unchanged']=(original_design.timeline.count,sum(b.volume for b in original_design.rootComponent.bRepBodies))==original_state
        report['passed']=report['passed'] and report['original_unchanged']
        save()
    return report


handler=Created()
lifetime.append(handler)
definition.commandCreated.add(handler)
definition.execute()
