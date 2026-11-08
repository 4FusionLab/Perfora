# Distribution v2 visual acceptance study

English | [Русский](README.ru.md)

**Status: offline candidate awaiting user visual acceptance.** The original base is `07e7184` on the separate `codex/distribution-visual-acceptance` branch. The loaded Fusion copy and the parallel organic-shapes branch were not changed. Do not switch the installed add-in to the new modes before accepting the demo. Candidate algorithms are in `Perfora/distribution_fields.py`; the public `geometry.generate()` selects them with `distribution_revision=2`. Revision 1 remains the default. The demo and future Fusion adapter receive the same list of Cell objects; new fields are serialized through the usual Feature payload.

## Decisions to assess

- Preserve the rhythm of the entire field. A spacing conflict changes the pitch or number of rows for the whole field instead of removing individual holes from a regular row. Only whole holes satisfying Edge Offset are selected at the boundary.
- Contour: close each row with an evenly spaced whole number of holes, check chords, and finish filling before reaching narrow remnants near the medial axis. A meaningful solid core remains. The level geometry is the earlier approximate distance field, not an exact CAD offset.
- Fan: use a shared inner radius and radial pitch for all rays. There is no scattering of omitted holes near the apex; the empty arc at the apex is intentional.
- Phyllotaxis: preserve every index of the Vogel spiral. When space is tight, scale the whole field while preserving the golden angle and recognizable parastichies.
- Poisson Disk: retain the existing algorithm. Irregularity is the purpose of this distribution; there is no basis for making it regular.
- Wave: measure arc length from the center of the field, use equal phases for neighboring rows, remain stable when the boundary changes, and optionally orient slots tangentially.
- Chevron: use mirrored pairs instead of conflicting holes at a shared apex. Tangential orientation gives a neat center seam.
- **Running Bond is not an independent family.** Following user feedback, the demo combines it with Staggered as Row Shift. A 1/2 shift matches a checkerboard at equal pitches; 1/3 is a row-shift setting. The installed runtime was not changed.
- Between Curves: use common stations between guides instead of an independent number of holes in each row. When space is tight, change the number of whole columns or rows.

## Reading the demo

The demo shows exact circles Ø 2.5 mm and slots 1.7 × 5.2 mm. Web Thickness is 1.2 mm and Edge Offset is 1.8 mm. The main panel is 120 × 100 mm. Contour uses a rounded noncircular source; Phyllotaxis uses a circle Ø 93 mm. Raster sheets share the same physical scale. The raster sheets show tangential slots, except circles for Phyllotaxis and Poisson Disk; a switch permits direct comparison of the same shapes in every distribution.

The “previous algorithm” runs the actual baseline generator using the same hole sizes, boundary, spacing and motif settings. Its orientation is fixed because it does not follow tangents. The candidate may increase pitch to resolve collisions, affecting hole counts; this is not a promise to retain density. Construction lines are not cuts.

The file includes all 12 entries in the command's LAYOUTS registry: four previous modes and eight new ones. The registry is read without adsk; an unknown mode stops the build instead of being silently skipped. Along Path calls the actual sample_path and generate_path with an analytical arc. Voronoi is a Hole Shape, not a Distribution.

Version 2 is not yet a finished CAD feature: demo sources are explicit; there is no partial-hole Trim, CAD, surface mapping, or new native dialog fields. Circles and slots are checked using exact capsule distances; for other repeating shapes, version 2 checks circumscribed circles and retains conservative packing. Native paths for those shapes need separate validation after the visual direction is accepted. Curved-hole rotation, old Feature compatibility, and seed persistence need a separate stage. Old Features must not silently recompute with the new algorithm.

Circular fills from the center in the shared test: Start Radius = 0, exactly one center hole for a circle or slot. The initial 8 mm demo offset was removed after user feedback. A nonzero Start Radius remains a normal setting of the existing circular generator, not a new restriction.

## Reproduction

```sh
python3 -m unittest discover -s tests -p test_distribution_study.py -v
python3 scripts/visual_distribution_test.py --output /absolute/path/distributions.html
```

The main output is **one standalone HTML file** with all coordinates, source-module hashes and styling. No network or server is needed. It includes an overview, individual distributions, circles/fixed slots/pattern-following slots, comparison of the previous version and candidate, construction lines, and 1/2 or 1/3 row shift.

Geometry, tests and HTML export have no third-party dependencies. Passing a directory instead of `.html` produces an additional set. Only PNG export uses locally installed Pillow and the macOS Helvetica font; these are not add-in dependencies. Export produces `distribution-demo.html` (an interactive fragment), three PNGs, exact coordinates in `data.json`, and measurements in `metrics.json`. Exported results are outside Git and the distribution. The template and generator are in this folder.

Checks include an independent exhaustive pairwise test of actual spacing across all 36 basic combinations, agreement with the public core, determinism, Fan ray continuity, preservation of Phyllotaxis indices, Wave stability when the region is trimmed, shared Between Curves columns, and two additional density levels per distribution. Local performance is not Fusion timing.

## Validation on 25 October 2026

172 local tests passed, including 12 for this study. For 36 basic combinations of all Distributions with circles and slots, an independent exhaustive pairwise comparison of actual contours confirmed Web Thickness and Edge Offset. Source translation/rotation, revision persistence in metadata, the previous default revision and the Circular center were checked. Browser validation confirmed 12 panels, comparison, shape switching, construction lines and Row Shift; there was no horizontal overflow at 360 px. Real CAD/UI checks were intentionally not run.
