# Working on Perfora

[Русская версия](AGENTS.ru.md)

Perfora is a 4FusionLab Autodesk Fusion add-in for perforating planar regions. The MVP is implemented; develop the existing tool while preserving current workflows and performance.

## Communication and documentation

- Communicate with the user in Russian. Write plans, including in plan mode, in Russian. Write documents in English and maintain separate Russian versions of documentation; intermediate working notes do not require translation.
- Add-in UI, error messages and names of created model elements are English, using Fusion terminology: Profiles, Extrude, Join, Cut, Intersect, New Body, New Component, OK, Cancel.
- Read the relevant module and inspect the working tree before changes. Preserve user changes and parallel work.
- Consult `README.md` and `README.ru.md` for current capabilities and limits; update both when behavior changes.
- Use `docs/PERFORATIONS.md` for hole dimensions and types, `CONTRIBUTING.md` for checks, and `docs/PUBLISHING.md` before publication.

## MVP boundaries

- Source: a planar face, closed sketch profile, or construction plane with a specified region.
- Result: ordinary sketch profiles or native Extrude with operation, direction, extent and target-body choices.
- Preserve existing shapes and layout parameters. When adding a shape, support it in profiles, Fast/Full Preview, trimming and Extrude.
- **Trim to Boundary** retains partial openings. **Edge Offset** remains active: trim against the boundary with the offset, including existing inner cutouts.
- Identical parameters must produce matching contours in preview and final model.
- Sketch and Extrude fix the grid at creation; native Extrude is edited using Fusion. Feature creates a parametric Custom Feature: preserve its parameters, dependencies, recompute and Edit Feature. Both READMEs describe mode limitations.

## Architecture

| File | Responsibility |
| --- | --- |
| `Perfora/geometry.py` | Independent 2D geometry, shapes, pitch, layout and clearances; no `adsk` import |
| `Perfora/model.py` | Sources, sketches, profiles and native Extrude |
| `Perfora/feature.py` | Custom Feature parameters, dependencies, lifecycle and recompute |
| `Perfora/solid.py` | Exact temporary straight-extrusion body without creating timeline nodes |
| `Perfora/clipping.py` | Exact trimming with temporary BRep operations and boundary offset |
| `Perfora/preview.py` | Layout cache, coordinate system and batched Fast Preview graphics |
| `Perfora/Perfora.py` | Command, dialog, event handlers and session lifecycle |
| `Perfora/ui_resources.py` | Locate native icons in the current Fusion installation with text fallback |
| `PerforaSmokeTest/` | Checks inside real Fusion |
| `install.py` | Local installation with backup and ZIP build |

- The geometry kernel uses Fusion internal units: centimeters. Handle unit conversion and user expressions explicitly at the API boundary.
- The add-in runs on Python supplied by Fusion without third-party runtime dependencies.
- Preserve compatibility: command ID `DiegoV_Perforator`, manifest UUID and attribute namespace `DiegoV.Perforator` were intentionally retained after renaming. Changing them requires a considered migration.
- Compute the numeric version of release ZIPs using GitVersion; do not rewrite checked-in `Perfora/Perfora.manifest` for a release. Preserve PolyForm Noncommercial 1.0.0 and corresponding SPDX headers.

## Fusion API and UI

- For SDK/API questions, syntax, configuration and API-specific errors use Context7: first `resolve-library-id`, then `query-docs` for the selected ID and specific question. If Fusion documentation is absent or incomplete, check official Autodesk documentation and installed Fusion API definitions. Mark unverified assumptions.
- Context7 is not required for pure refactoring, geometry algorithms or documentation edits.
- Build the dialog with native CommandInputs. Compare changes with real Extrude and Pattern: labels, icons, grouping, field visibility and confirmation buttons.
- Resolve native graphics through `ui_resources.py` from the current installation; retain the text fallback. Do not copy Autodesk resources into the distribution.
- `CommandInput.name` is read-only: for changing labels use existing paired fields with visibility switching and synchronized expressions.
- Do not relocate nested-group folding without Fusion validation: it previously caused `the group cannot be folded`.
- Retain event-handler references until session end. Account for selected entities disappearing during cancellation and release temporary resources.

## Performance and geometry

- **Shared kernel:** Fusion and the web demo execute the same Perfora geometry sources for all shapes and Distributions. Browser code handles input and display; layout and clearance algorithms remain in the Python kernel. Generate examples and thumbnails with that kernel too. The web version is for quick checks and does not require export.
- **Fast visual checks:** the web demo is the standard bench before CAD acceptance. When changing a pattern, rebuild the demo and check browser results against the shared kernel: parameters, coordinates/contours, clearances, seed and algorithm revision. Build and verification steps are in `demo/README.md`. Web checks supplement mandatory Fusion acceptance.
- Fast Preview uses caching and batched Custom Graphics. Opening a section or changing field visibility must not trigger a complete CAD build.
- Invalidate geometry cache when the source or layout-affecting parameters change. Full Preview and final construction must use current Extrude parameters.
- Do not add attributes to every hole edge: this previously caused large delays on hexagons due to Fusion entity tracking. Preserve the existing separation of boundary and cell attributes.
- Verify contour conversion to world coordinates on a translated and rotated plane. Use an explicit basis via `sketchToModelSpace`; replacing it with an inverse matrix without validation previously displaced preview.
- Project and annotate the boundary before enabling `sketch.isComputeDeferred`; otherwise projection can appear empty even though curves appear later.
- Preserve exact arcs and inner contours during trimming. Check minimum web and offset with tolerance, rotation and partial cells accounted for.

## Result verification

Choose checks for the affected behavior. Local tests and a successful ZIP build do not establish CAD or Fusion UI behavior.

```sh
python3 -m unittest discover -s tests -v
python3 install.py --zip
```

- Geometry change: local tests plus relevant `tests/fusion_shapes_regression.py` and `tests/fusion_clipping_regression.py` scenarios inside Fusion.
- Preview or cache change: `tests/fusion_preview_performance.py`; check a dense hexagon grid, contour positions and dialog responsiveness. Record cell count and measured time.
- Command or dialog change: `tests/fusion_dialog_regression.py`, `tests/fusion_ui_contract.py` and visual inspection. Check switching affected modes and real OK and Cancel without residual geometry.
- Installation or packaging: build the ZIP and verify contents and installation to a separate temporary `--api-root`, including backup on repeat installation.
- Icon change: preserve the user's original and transparency; prepare 16/32/64 sizes. Fusion caches resources; when needed use a new directory and restart only the add-in. Check the button on the real panel.
- Before release perform acceptance from `CONTRIBUTING.md`, including Undo/Redo, save and reopen, and native Extrude editing. State actual Fusion version and OS; macOS results do not establish Windows behavior.
- Distinguish local verification, installed-copy verification and UI observation in reports. Do not treat historical reports as validation of the current build.

## Working with user applications

- By default create a separate unsaved document for CAD tests. Use the current user document when the task authorizes it; preserve its geometry and do not save it without a request.
- Verify which add-in copy is actually loaded. Installing files alone does not update the executing module or icon cache.
- Use available MCP tools first for Fusion, browsers and other applications. Move to Computer Use only when MCP cannot perform the required action or verification. Verify actual outcomes after actions; a toggle state alone does not prove the add-in started.
- If computation hangs, first try normal cancellation. Force-quitting and restarting Fusion with user documents require separate agreement.
- For websites prefer connected DevTools or a specific tab with narrow requests. Verify real connectivity; use screenshots for visual checks. Do not enable remote debugging or restart a browser solely to save tokens without agreement.

## Git and publication

- Use Conventional Commits; default new-branch prefix is `codex/`.
- Change sources and workflows only within task scope and through reviewable Git history. Direct ZIP publication and manual tag creation are prohibited; automatic GitHub Release after runtime changes in `main` is already authorized. Details: `.github/RELEASE_POLICY.md` and `docs/PUBLISHING.md`.
- Keep caches, local reports, secrets and installation backups out of commits and distributions. Package with the standard `install.py`.

## Shared 4FusionLab engineering contract

- Organization rules and shared CI components are documented in [4FusionLab/.github](https://github.com/4FusionLab/.github/blob/main/AGENTS.md) and [Release Platform](https://github.com/4FusionLab/.github/blob/main/RELEASE_PLATFORM.md). These product-specific rules apply in addition.
- Before edits inspect existing Git changes, documentation, automated checks and Autodesk Fusion compatibility. Do not delete user data or change existing command IDs, manifest UUID or add-in structure without a migration plan.
- Use Conventional Commits for ordinary development; a small PR with CI is preferred, though direct push to `main` is allowed by repository policy. Do not rewrite history or modify published tags/artifacts.
- **Automatic releases occur only for shipped product changes**: push or merge to `main` → check `.github/release-paths.txt` → tests → GitVersion 6.8.2 → new immutable tag and GitHub Release. Do not create tags manually; changes to README, documentation, tests, workflows or `AGENTS.md` must not independently publish a release.
- Pin shared GitHub Actions to the **exact SHA** of a reviewed `4FusionLab/.github` commit, not `@main`. Package, manifest, SHA-256, release notes and version must agree; do not overwrite existing releases.
- Passing unit tests and building a ZIP **does not prove** operation in installed Autodesk Fusion. Record actual CAD acceptance and OS separately for Fusion API and UI changes.
- Preserve existing English and Russian documentation, licenses, limitations and project-specific workflows. Do not publish secrets, personal CAD documents, tokens or local-machine artifacts.
