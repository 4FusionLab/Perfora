# SPDX-License-Identifier: GPL-3.0-only
"""Reproduce 1.0 geometry workloads; optionally compare a compatible baseline."""
import argparse
import hashlib
import importlib.util
import json
import platform
from pathlib import Path
import statistics
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('tiny_circle', 'tiny_triangle', 'rect_circle', 'rect_hexagon',
         'disk_hexagon', 'disk_ellipse', 'annulus_circle', 'disk_circular_circle',
         'dense_hexagon', 'voronoi', 'voronoi_rounded', 'voronoi_disk', 'bounded_voronoi')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def setup(module, name):
    kw = dict(size=.5, gap=.15, margin=.3, slot_length=1., limit=5000)
    if name.startswith('tiny'):
        region = module.rectangle_region(.8, .8)
        kw.update(shape=name.split('_')[1], margin=0)
    elif name == 'dense_hexagon':
        region = module.rectangle_region(12, 25)
        kw.update(shape='hexagon', size=.26, gap=.03, margin=.1)
    elif name == 'bounded_voronoi':
        region = module.rectangle_region(100000, 100000)
        kw.update(shape='voronoi', size=.35, origin_x=1234, origin_y=-2134,
                  spread_radius=1.6, margin=.1)
    else:
        region = (module.disk_region(8 if 'ellipse' in name else 5 if name == 'voronoi_disk' else 12)
                  if name.startswith('disk') or name == 'voronoi_disk' else module.rectangle_region(12, 25))
        if name == 'annulus_circle':
            region = module.Region((module.disk_region(8).loops[0],
                module.Loop(module.disk_region(3).loops[0].points, False)))
        if 'hexagon' in name:
            kw['shape'] = 'hexagon'
        if 'ellipse' in name:
            kw['shape'] = 'ellipse'
        if name.startswith('voronoi'):
            kw.update(shape='voronoi', corner_radius=.05 if 'rounded' in name else 0)
        if 'circular' in name:
            kw.update(layout='circular', tangential_orientation=True)
    return region, module.Settings(**kw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error('--repeat must be positive')
    sources = {'current': ROOT / 'Perfora/geometry.py'}
    if args.baseline:
        sources = {'baseline': args.baseline, **sources}
    modules = {k: load('_benchmark_' + k, p) for k, p in sources.items()}
    report = dict(platform=platform.platform(), python=platform.python_version(),
        sha256={k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in sources.items()}, scenarios=[])
    for name in NAMES:
        samples = {k: [] for k in modules}
        expected = None
        for iteration in range(args.repeat):
            order = list(modules.items())
            if iteration % 2:
                order.reverse()
            for label, module in order:
                region, settings = setup(module, name)
                started = perf_counter()
                cells = module.generate(region, settings)
                samples[label].append(perf_counter() - started)
                fingerprint = repr((cells, module.outline_coordinates(cells, region)))
                if expected is not None and fingerprint != expected:
                    raise RuntimeError('Geometry mismatch: ' + name)
                expected = fingerprint
        medians = {k: statistics.median(v) for k, v in samples.items()}
        row = dict(name=name, cells=len(cells), samples=samples, medians=medians)
        if 'baseline' in medians:
            row['speedup'] = medians['baseline'] / medians['current']
        report['scenarios'].append(row)
        print(name, len(cells), {k: round(v * 1000, 3) for k, v in medians.items()}, flush=True)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
