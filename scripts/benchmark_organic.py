# SPDX-License-Identifier: GPL-3.0-only
"""Reproducible pure-Python organic timings; not Fusion CAD acceptance."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from Perfora import geometry as geo, organic
from Perfora.cache import GeometryCache


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat',type=int,default=3)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not 1<=args.repeat<=20:parser.error('--repeat must be 1–20')
    report=dict(python=platform.python_version(),os=platform.platform(),native_cad=False,cases=[])
    region=geo.rectangle_region(5.,4.)
    base=geo.Settings(size=.45,gap=.055,margin=.07,clip_boundary=True,organic_open=60)
    for shape in geo.ORGANIC_SHAPES:
        organic.reaction.cache_clear()
        samples=[];settings=replace(base,shape=shape);cache=GeometryCache()
        for i in range(args.repeat):
            t=perf_counter();cells=geo.generate(region,settings);samples.append(perf_counter()-t)
        cache.resolve(region,settings);t=perf_counter();cache.resolve(region,settings);cached=perf_counter()-t
        report['cases'].append(dict(shape=shape,holes=len(cells),edges=sum(1 if c.shape=='circle' else len(c.contour) for c in cells),
            seconds=samples,median_seconds=statistics.median(samples),cache_seconds=cached,settings=settings.__dict__))
    text=json.dumps(report,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text)
    print(text)


if __name__=='__main__':main()
