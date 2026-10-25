# SPDX-License-Identifier: GPL-3.0-only
"""Analytic source fixtures; production sampling/generation are never copied."""
import ast
from dataclasses import replace
import math
from pathlib import Path
from types import SimpleNamespace as Point
from Perfora.curve_layout import sample_path


def distribution_registry():
    """Read the actual native command registry without importing adsk."""
    tree=ast.parse((Path(__file__).resolve().parents[1]/'Perfora/Perfora.py').read_text())
    layouts=[]
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='LAYOUTS' for t in node.targets):
            layouts=list(ast.literal_eval(node.value))
        elif isinstance(node,ast.AugAssign) and isinstance(node.target,ast.Name) and node.target.id=='LAYOUTS':
            layouts.extend(ast.literal_eval(node.value))
    if not layouts:raise ValueError('Missing native Distribution registry.')
    return tuple(layouts)


class ArcEvaluator:
    """Same minimal evaluator protocol consumed by the Fusion path adapter.

    A circle arc has analytic lengths/tangents; this avoids approximate demo
    reimplementations of either arc-length placement or source sampling.
    """
    radius=4.1
    start=-.3
    end=math.pi+.3

    def getParameterExtents(self):return True,self.start,self.end
    def getLengthAtParameter(self,a,b):return True,(b-a)*self.radius
    def getParameterAtLength(self,a,length):return True,a+length/self.radius
    def getPointAtParameter(self,t):return True,Point(x=self.radius*math.cos(t),y=self.radius*math.sin(t)-1.4,z=0.)
    def getFirstDerivative(self,t):return True,Point(x=-self.radius*math.sin(t),y=self.radius*math.cos(t),z=0.)
    def getStrokes(self,a,b,tolerance):
        count=math.ceil((b-a)/(2*math.acos(1-tolerance/self.radius)))
        return True,[self.getPointAtParameter(a+(b-a)*i/count)[1] for i in range(count+1)]


def arc_fixture(settings,orientation):
    s=replace(settings,layout='path',distribution_revision=1,origin_x=None,origin_y=None,
              start_radius=0,
              path_orientation=orientation,path_spacing=max(settings.slot_length if settings.shape=='slot' else settings.size,.25)+settings.gap+.03,
              path_start=.2,path_end=.2)
    evaluator=ArcEvaluator()
    samples=sample_path(evaluator,s,lambda p:(p.x,p.y,p.z),lambda p:(p.x,p.y,p.z))
    stroke=tuple((p.x,p.y) for p in evaluator.getStrokes(evaluator.start,evaluator.end,.005)[1])
    return replace(s,path_samples=samples),stroke
