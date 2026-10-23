# Contributing to Perfora

Keep geometry independent of Fusion. `Perfora/geometry.py` contains layout and clearance logic; `model.py` and `clipping.py` adapt it to Fusion; `preview.py` renders previews; `Perfora.py` owns the command and dialog.

Run `python3 -m unittest discover -s tests -v` for geometry changes. Run `python3 install.py --zip` to check packaging. No pip dependencies are required.

CAD changes also require real Fusion checks. Install the add-in and run `PerforaSmokeTest` from Scripts and Add-Ins. From Fusion's Python console, use an absolute path into your checkout or extracted ZIP:

```python
import runpy
runpy.run_path('/absolute/path/to/Perfora/tests/fusion_shapes_regression.py')
```

Other scenarios: `fusion_clipping_regression.py`, `fusion_preview_performance.py`, `fusion_voronoi_regression.py`, `fusion_dialog_regression.py`, and `fusion_ui_contract.py`. The Voronoi suite checks exact preview/sketch contours, cache invalidation, a translated and rotated plane, an annulus, a concave boundary, rounded-hole areas/volumes, tiny bevel absorption, tangent corners after trimming, and all five operations with rounding. The dialog checks require the add-in to be running. Review each script before running it. CAD scenarios create a separate unsaved document; test reports are written outside the repository.

Before release, verify command startup, all 13 shapes (including Voronoi in the development branch), fast/full previews, boundary trimming, Cancel without residual geometry, Cut, Undo/Redo, document save/reopen, and native Extrude editing. For Voronoi, check Seed/New Pattern, 0% and 100% Irregularity, minimum web, Round Corners on/off, radius changes, and cache invalidation after changing a setting. Record the Fusion version, OS, and actual results; geometry tests alone do not establish CAD correctness.

Keep the command ID, add-in UUID, and document attribute namespace stable unless a deliberate migration is implemented. Use Conventional Commits, for example `fix: preserve clearance around inner boundaries`.
