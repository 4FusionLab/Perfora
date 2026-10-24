# Perfora 1.0 benchmarks

Measured on 24 October 2026, macOS arm64, Fusion 2706.1.14 (macOS 27.0.1). These results compare the frozen pre-optimization development snapshot with the optimized geometry shipped in 1.0. Both snapshots already contain Circular, Start Point, Spread Radius, and Tangential placement. **The baseline is not the published 0.2.0 release.** Source fingerprints and raw samples are in [v1.0.0.json](benchmarks/v1.0.0.json).

## Pure Python geometry generation

Each value is the median of three interleaved before/after measurements with a fresh Region and Settings. Index preparation is included. Timed work is `geometry.generate`, excluding rendering, native sketch creation, BRep clipping, and Extrude. Every sample checks identical cells and outline coordinates. A separate 511-case matrix found no differences in cells, coordinates, or matched errors.

| Scenario | Holes | Before, ms | After, ms | Speedup |
| --- | ---: | ---: | ---: | ---: |
| `tiny_circle` | 1 | 0.041 | 0.036 | 1.14× |
| `tiny_triangle` | 1 | 0.060 | 0.052 | 1.17× |
| `rect_circle` | 709 | 6.330 | 3.409 | 1.86× |
| `rect_hexagon` | 709 | 34.005 | 10.588 | 3.21× |
| `disk_hexagon` | 253 | 1282.353 | 96.812 | 13.25× |
| `disk_ellipse` | 45 | 4027.185 | 263.233 | 15.30× |
| `annulus_circle` | 72 | 107.009 | 13.573 | 7.88× |
| `disk_circular_circle` | 223 | 176.663 | 15.299 | 11.55× |
| `dense_hexagon` | 3831 | 178.721 | 53.161 | 3.36× |
| `voronoi` | 1041 | 269.651 | 125.366 | 2.15× |
| `voronoi_rounded` | 1041 | 270.513 | 128.597 | 2.10× |
| `voronoi_disk` | 45 | 195.792 | 34.023 | 5.75× |
| `bounded_voronoi` | 45 | 33.425 | 16.700 | 2.00× |

`rect_*` uses a 120 × 250 mm region; `disk_hexagon` uses a 120 mm diameter; `disk_ellipse` uses an 80 mm diameter. Default hole size is 5 mm, gap 1.5 mm, and edge offset 3 mm. The dense hexagonal case uses 2.6 mm holes and a 0.3 mm gap. `bounded_voronoi` uses an enormous boundary with a 16 mm spread limit to check that candidate generation stays local. Scenario definitions can be rerun with [scripts/benchmark_layout.py](../scripts/benchmark_layout.py).

The 15.30× elliptical result measures this Python generation path only. It is **not** a 15× claim for every command or native solid operation. Tiny workloads have microsecond-level noise; seven additional interleaved batches of 1,000 complete generations showed 37.34 → 30.44 µs for a single circle and 55.70 → 47.44 µs for a single triangle.

## Native Fusion: first Fast Preview and subsequent build

One paired measurement per scenario in the same native Fusion session. Build was measured after Fast Preview: the baseline regenerates cells; the optimized version reuses immutable cells but still rereads the live source and performs native construction. Hole counts, profile areas, and preview coordinates matched (coordinate tolerance 1e-7 cm).

| Scenario | Holes | Fast before → after, s | Build before → after, s |
| --- | ---: | ---: | ---: |
| Hexagons inside a circular boundary | 253 | 1.148 → 0.104 | 2.453 → 2.193 |
| Elliptical holes inside a circular boundary | 45 | 3.424 → 0.262 | 3.683 → 0.263 |
| Small scoped tangential layout | 7 | 0.058 → 0.054 | 0.105 → 0.107 |

The last case has no meaningful build improvement. Native sketch/curve creation can dominate hexagonal patterns. Results depend on hardware, boundary complexity, Fusion version, native API behavior, and caching. No Windows CAD timings or hardware-normalized claims are made.

## Cache and color checks

Native regressions verify that Fast → build reuses cells while current Extrude distances still affect volume, that Holes avoids Panel-only Boolean work, and that source revisions and moved planes invalidate their data. Preview Color changes only presentation. A 709-hexagon test checks all six native RGB values without regenerating cells; its sub-millisecond API timing excludes display refresh and is not an interaction-latency guarantee.

## Reproduce current-generation measurements

```sh
python3 scripts/benchmark_layout.py --repeat 3 --output /tmp/perfora-benchmark.json
python3 scripts/benchmark_layout.py --baseline /path/to/frozen/geometry.py --repeat 3
```

The historical baseline is fingerprinted in the raw data and is intentionally not bundled as another runtime implementation. A baseline argument must point to a compatible snapshot with the same Settings and Region schema. Native measurements require Fusion and `tests/fusion_optimization_regression.py` with a compatible `baseline_path`; Python timings alone do not establish CAD behavior.
