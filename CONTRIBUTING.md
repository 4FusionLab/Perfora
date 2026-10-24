# Contributing to Perfora

Keep geometry independent of Fusion. `Perfora/geometry.py` contains layout and clearance logic; `model.py` and `clipping.py` adapt it to Fusion; `preview.py` renders previews; `Perfora.py` owns the command and dialog.

Run `python3 -m unittest discover -s tests -v` for geometry changes. Run `python3 install.py --zip` to check packaging. No pip dependencies are required.

CAD changes also require real Fusion checks. Install the add-in and run `PerforaSmokeTest` from Scripts and Add-Ins. From Fusion's Python console, use an absolute path into your checkout or extracted ZIP:

```python
import runpy
runpy.run_path('/absolute/path/to/Perfora/tests/fusion_shapes_regression.py')
```

Other scenarios: `fusion_clipping_regression.py`, `fusion_preview_performance.py`, `fusion_voronoi_regression.py`, `fusion_dialog_regression.py`, and `fusion_ui_contract.py`. The Voronoi suite checks exact preview/sketch contours, cache invalidation, a translated and rotated plane, an annulus, a concave boundary, rounded-hole areas/volumes, tiny bevel absorption, tangent corners after trimming, and all five operations with rounding. The dialog checks require the add-in to be running. Run `fusion_feature_regression.py` against the registered add-in from the same checkout: Custom Feature definitions require its manifest UUID and cannot be validated by importing a standalone test package. Review each script before running it. CAD scenarios create a separate unsaved document; test reports are written outside the repository.

Before release, verify command startup, all 13 shapes, including Voronoi, fast/full previews, boundary trimming, Cancel without residual geometry, Cut, Undo/Redo, document save/reopen, and native Extrude editing. For Voronoi, check Seed/New Pattern, 0% and 100% Irregularity, minimum web, Round Corners on/off, radius changes, and cache invalidation after changing a setting. For Feature, check parameter and upstream-boundary changes, different hole counts, user-parameter expressions, Edit Feature OK/Cancel, Full Preview rollback, Undo/Redo, and native archive reopen with subsequent recompute. Source, operation, and target bodies remain fixed during edit; the initial mode supports straight Distance extents and Join/Cut/Intersect/New Body. Record the Fusion version, OS, and actual results; geometry tests alone do not establish CAD correctness.

The Feature regression also builds and recomputes all 13 shapes, checks offset/direction bounds, and rejects unsupported extents, taper, and New Component. To test an installed copy, pass its registered folder with `init_globals={'addon_path': '/absolute/API/AddIns/Perfora'}`. Start a fresh Fusion session and load only that copy: switching linked copies with the same manifest UUID in one session can retain the first Custom Feature owner's registration and report that its extension is not running. A reload from the same path and a clean launch are separate checks.

For UI acceptance, run `fusion_ui_contract.py` with `init_globals={'result_mode': 'profiles'}` for Sketch, `'extrude'` for Extrude, or `'feature'` for Feature. Add `'registered_command': True` to exercise the installed `DiegoV_Perforator` command. After clicking the real OK or Cancel button, call `finish(True)` or `finish(False)` in the returned namespace; a report at `stage='ready'` alone does not prove the transaction passed. Keep each report before starting another scenario.

Keep the command ID, add-in UUID, and document attribute namespace stable unless a deliberate migration is implemented. Use Conventional Commits, for example `fix: preserve clearance around inner boundaries`.


For Circular distribution, run `fusion_circular_regression.py` as well: all 12 repeating shapes, ring placement and contour agreement, cache invalidation, a translated/rotated plane, annular trimming with Edge Offset, panel volume, and all five native operations. In the dialog, check Start Radius, Fixed/Radial orientation, Tangential orientation, Start Point selection/clearing, offsets relative to the picked point, switching to/from Voronoi, Fast/Full Preview, OK, and Cancel without residual geometry. Noncircular rings use conservative enclosing bounds; Start Radius measures hole centers, not a guaranteed solid hub.

Numeric inputs use native StringValueCommandInputs backed by hidden ValueCommandInputs because ValueCommandInput hides empty edits behind its last valid expression. `fusion_ui_contract.py` checks default restoration for all 36 fields, unitless integers, explicit zero, invalid nonempty text, units, and document parameters. Also clear a visible field in the UI, wait for its default to return, then clear and immediately type a replacement; test a command cancellation with a pending reset and ensure no late callback affects another document.

For point-based Circular placement, run `fusion_center_regression.py`: preview/sketch agreement, anchor replacement and clearing, cache reuse, projected points on a translated/rotated plane, vertex/construction points, assembly coordinates, tangential trimming/extrusion, and Feature dependency recompute where supported. In the real dialog, select a point, switch distribution and shape, test Fast/Full Preview, OK and Cancel; in Edit Feature, replace/clear the point and verify both commit and cancellation.

Global Start Point and Spread Radius must work for Staggered, Rectangular, Circular, and Voronoi. Check zero/unlimited radius, a point off the Profiles plane, positive radius with/without Trim to Boundary and Edge Offset, radius-driven Feature recompute, and bounded performance on a large source. Numeric defaults now cover 36 fields.

For optimization work, run `fusion_optimization_regression.py` with the registered add-in. It checks shared cells with current Extrude parameters, lazy Panel switching, retry after a real Boolean target mutation, separate source/inset/spread invalidation, a moved source plane, and Feature cache/recompute. Optional `baseline_path` points to a frozen pre-change Perfora package for paired native geometry/timing comparisons. Do not package that snapshot. Run the normal shape, clipping, Voronoi, circular, origin, preview, dialog, and Feature regressions as applicable; finish with real Full Preview, OK and Cancel.

Only immutable 2D cells cross Fast Preview/final build through `GeometryCache`. Native clipping bodies remain renderer-owned; final CAD rereads its source and performs its own exact trim. Do not cache output bodies, extrusion configuration, or rolled-back source sketches. The cache holds one successful entry and is cleared with the command.

For sketch profiles drawn directly on solid faces, run `fusion_profile_face_regression.py`: horizontal/vertical support, inner loops, Trim to Boundary on/off, Fast Preview/profile/Cut agreement, timeline restoration, and Feature recompute after editing the source diameter and hole size. Run `fusion_ui_contract.py` with `source_profile=True` and `registered_command=True` for automatic Objects selection, Full Preview, actual OK and Cancel without residual geometry.

Stable acceptance: run `fusion_release_acceptance.py` from the Fusion Python console with `result_mode='feature'`, then repeat with `'extrude'`. Use the registered add-in from that checkout (or pass `addon_path`). After real OK call `verify_created()`, perform native Undo and call `verify_undo()`, perform native Redo and call `finish()`. The final check edits a model parameter, exports/reopens a local F3D, recomputes again, and restores the original document. Local archive reopen is distinct from cloud save/reopen.

Run `scripts/benchmark_layout.py --repeat 3` to reproduce current geometry scenarios. Historical before/after samples, methodology, baseline fingerprints, and caveats live in `docs/BENCHMARKS.md`. Product screenshots are generated in real Fusion with `scripts/capture_release_examples.py`; inspect every exported image before publication.
