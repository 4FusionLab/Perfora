# SPDX-License-Identifier: GPL-3.0-only
"""Offline fixtures only. Hole generation lives in the shared Perfora core."""
import math
from Perfora.geometry import Settings, Loop, Region, rectangle_region
from Perfora.distribution_fields import (NAMES, Field as Study, minimum_gap, _draft, build_field)
from Perfora.geometry import generate as kernel_generate
from dataclasses import replace
from time import perf_counter

def specimen(name):
    if name == 'contour':
        # A smooth noncircular source makes following the boundary observable.
        p = tuple((5.4*math.copysign(abs(math.cos(t))**.65, math.cos(t)),
                   4.4*math.copysign(abs(math.sin(t))**.65, math.sin(t)))
                  for t in (i*math.tau/200 for i in range(200)))
        return Region((Loop(p),))
    if name == 'phyllotaxis':
        return Region((Loop(tuple((4.65*math.cos(i*math.tau/180),4.65*math.sin(i*math.tau/180)) for i in range(180))),))
    return rectangle_region(12, 10)


def settings_for(name,shape='circle',orientation='tangent',row_shift=1/3,seed=7,density='balanced'):
    size=.25 if shape=='circle' else .17
    length=.52
    factor={'airy':1.5,'balanced':1.12,'dense':1.0}[density]
    return Settings(layout=name,shape=shape,size=size,slot_length=length,gap=.12,margin=.18,
        seed=seed,contour_tolerance=.055,limit=5000,bond_shift=row_shift,
        fan_rays=25,fan_angle=math.pi,start_radius=1.15,
        origin_x=0,origin_y=-4.35 if name=='fan' else 0,
        wave_amplitude=.65,wave_length=5.1,chevron_angle=math.radians(28),guide_rows=12,
        guide1=tuple((-5.45+10.9*i/256,-2.6+.75*math.sin(math.tau*i/256-.5)) for i in range(257)),
        guide2=tuple((-5.45+10.9*i/256,2.1+1.05*math.sin(math.tau*i/256+.3)) for i in range(257)),
        along_spacing=((length if shape=='slot' else size)+.12)*factor,
        row_spacing=(size+.12)*factor,distribution_revision=2,layout_orientation=orientation)

def generate(name,shape='circle',density='balanced',orientation='tangent',seed=7,row_shift=1/3):
    s=settings_for(name,shape,orientation,row_shift,seed,density)
    region=specimen(name)
    if name in NAMES:
        result=build_field(region,s)
        # The exporter must use the exact same public entry point as Fusion.
        # Keep construction strokes as diagnostics, never as replacement holes.
        actual=kernel_generate(region,s)
        if actual!=result.cells:raise AssertionError('Visual/runtime kernel mismatch.')
        result.cells=actual
        return result
    strokes=[]
    if name in ('rows','staggered'):
        s=replace(s,layout='grid',staggered=name=='staggered',distribution_revision=1)
    elif name=='circular':
        s=replace(s,layout='circular',start_radius=0,distribution_revision=1,
                  radial_orientation=orientation=='tangent' and shape=='slot')
    elif name=='path':
        from studies.source_fixtures import arc_fixture
        s,stroke=arc_fixture(s,orientation)
        strokes=[stroke]
    else:raise ValueError('Missing fixture for Distribution: '+name)
    started=perf_counter()
    cells=kernel_generate(region,s)
    elapsed=(perf_counter()-started)*1000
    return Study(cells,strokes,region,s,elapsed,1,1,minimum_gap(cells,s.gap))
