<p align="center">
  <img src="perfora.png" alt="Perfora — goddess of holes" width="200">
</p>

<h1 align="center">Perfora for Autodesk Fusion</h1>
<p align="center"><strong>Goddess of holes. Precision for Fusion.</strong><br>Hole patterns, ventilation grilles, and perforated panels — without placing every hole by hand.</p>

<p align="center">
  <a href="https://github.com/4FusionLab/Perfora/actions/workflows/ci.yml"><img src="https://github.com/4FusionLab/Perfora/actions/workflows/ci.yml/badge.svg" alt="Build and release checks"></a>
  <a href="https://github.com/4FusionLab/Perfora/releases"><img src="https://img.shields.io/github/v/release/4FusionLab/Perfora?include_prereleases&amp;color=2077bd" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue" alt="GPL-3.0 license"></a>
</p>

<p align="center"><a href="https://github.com/4FusionLab/Perfora/releases/tag/v0.2.0"><strong>Download v0.2.0</strong></a> · <a href="README.ru.md">Русский</a> · <a href="https://github.com/4FusionLab/Perfora/issues">Report a problem</a></p>

> **Experimental release.** Use copies of working designs. Native Windows CAD behavior and complex assemblies still need acceptance testing. Feature archive reopen and subsequent recompute were checked in Fusion on macOS.

## Make the pattern. Keep the native model.

Select a planar face, a closed sketch profile, or a construction plane. Choose a hole shape, set the spacing and edge clearance, and preview the result. Perfora creates ordinary sketch profiles, a native Fusion Extrude, or a parametric Perfora timeline feature.

![Twelve supported hole shapes](docs/assets/hole-shapes.svg)

| Control | What you can do |
| --- | --- |
| Pattern | Rectangular or staggered distribution; web thickness; independent hole and grid rotation; X/Y placement |
| Boundary | Keep complete holes or trim them to the boundary, with an edge offset and clearance around existing openings |
| Output | Hole profiles or a perforated panel; Sketch, native Extrude, or parametric Feature |
| Operation | Join, Cut, Intersect, New Body, New Component |
| Extent | One Side, Two Sides, Symmetric; distance, through-all, or to-object where supported |
| Preview | Cached fast contours for layout; full CAD preview to inspect the extrusion |

See [hole dimensions and geometry notes](docs/PERFORATIONS.md). The interface is in English, using Fusion's native operation names. No third-party Python packages are required.

## Voronoi

**Voronoi** is the thirteenth hole shape, available since 0.2.0. Select **Hole Shape → Voronoi**, then adjust **Cell Spacing**, **Irregularity (%)**, and **Seed**. **New Pattern** advances the seed while keeping the other settings. A seed reproduces the same pattern for the same source and settings.

Cell Spacing controls the nominal distance between sites, rather than the size of every hole. Irregularity ranges from regular square cells at 0% to varied convex polygons at 100%. **Web Thickness** sets the minimum gap between holes; a large web can consume small cells. **Distribution** and **Hole Angle** are hidden in this mode. Pattern rotation, X/Y offsets, edge clearance, exact trimming, Fast/Full Preview, sketch profiles, and native Extrude remain available.

Enable **Round Corners** to add tangent circular fillets to the Voronoi holes. **Corner Radius** sets the maximum radius. Short bevels are absorbed by the rounded contour; the radius is reduced only when the hole is too narrow. Rounding is off by default and preserves the minimum web. Fast Preview follows the same arcs used by the sketch and Extrude. New convex corners at straight and circular trim boundaries are rounded too. Existing concave source corners and elliptical/spline boundary segments retain their exact geometry.

## Parametric Feature

**Type → Feature** creates one **Perfora** node in the timeline. With the add-in running, changing its model parameters or upstream source geometry regenerates the pattern, including the number of holes. Double-click the node or choose **Edit Feature** to edit the pattern, trimming, placement, profile type, and thickness. Expressions can reference Fusion user parameters. OK commits the edit; Cancel restores the previous model.

All 13 shapes, exact trimming, rounded Voronoi holes, Fast/Full Preview, and **Join**, **Cut**, **Intersect**, **New Body** are supported. **Capture Design History** is required. This initial mode supports **Distance** with zero taper and **One Side**, **Two Sides**, **Symmetric**. Source, operation, and target bodies stay fixed during edit. Use Extrude for **All**, **To Object**, taper, or **New Component**.

Keep Perfora running to edit or recompute the feature. Large topology changes can invalidate downstream face/edge references. The mode uses Autodesk's [Custom Feature API](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/CustomFeatures_UM.htm), which remains in Preview.

## Install

**Requires Autodesk Fusion on macOS or Windows. No terminal or separate Python installation is needed for the recommended method.** Perfora runs using the Python runtime included with Fusion. Linux is supported for tests and packaging only.

### Recommended: add the folder in Fusion

1. Download **[Perfora-0.2.0.zip](https://github.com/4FusionLab/Perfora/releases/download/v0.2.0/Perfora-0.2.0.zip)** from the [release page](https://github.com/4FusionLab/Perfora/releases/tag/v0.2.0) and extract it to a permanent location.
2. In Fusion, open **Utilities → Scripts and Add-Ins**.
3. Click **+ → Script or add-in from device**.
4. Select the inner **`Perfora`** folder containing **`Perfora.py`** and **`Perfora.manifest`**, not the top-level extracted folder.
5. Select **Perfora** and click **Run**. Optionally enable **Run on Startup**.

Fusion remembers a link to this folder. **Keep it in place: do not move or delete it after adding it.** The command appears in **Design → Solid → Create**, or press **S** and search for **Perfora**.

This folder-linking method is [supported by Autodesk](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/WritingDebugging_UM.htm).

### Optional: installer with automatic backups

If you already have Python 3 installed, you can instead open a terminal in the extracted folder and run:

```sh
# macOS
python3 install.py

# Windows
py -3 install.py
```

The installer copies the add-in to Fusion's API directory and installs the optional CAD smoke-test script. Existing Perfora installations are backed up outside AddIns/Scripts; automatic startup is disabled. It prints the installed location. In Fusion, select **Perfora → Run** in Scripts and Add-Ins; add the printed `Perfora` folder with **+** if it is not listed.

To specify the Fusion API directory: `python3 install.py --api-root "/path/to/Fusion/API"`.

**Updating Perfora:** stop and unlink the old copy before adding the new folder. Restart Fusion before using Feature from a different folder: switching copies with the same add-in UUID in one session can retain the previous Feature owner. Keep one copy running.

**Upgrading from Perforator:** stop and unregister the old add-in before running Perfora. The old folder is not removed automatically. Do not run both versions together; command IDs and document attributes are intentionally compatible.

## Two starting points

**Vent a box wall:** select a planar face → set Hole Shape, Web Thickness, and Edge Offset → Extrude → Holes → Cut → All → check direction and Objects → OK.

**Build a separate grille:** select a closed sketch profile or construction plane → set the pattern → Extrude → Perforated Panel → New Body or New Component → set thickness → OK.

On a construction plane, Boundary defines a centered rectangle or circle. **Trim to Boundary** includes partial holes along the edge; **Edge Offset** remains active.

## Know the limits

- Planar geometry and solid bodies only; curved faces and mesh bodies are unsupported.
- Sketch and Extrude outputs keep a fixed hole layout. Use Feature to regenerate the pattern.
- Native Extrude parameters remain editable in Fusion. Source and Cut/Intersect target bodies must belong to the same component. Editing a component affects all its occurrences.
- The default limit is 1,500 holes, configurable up to 5,000. Dense patterns and full previews take longer. Some rotated shapes use conservative spacing, so the actual web can be wider than requested.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 install.py --zip
```

The build produces `dist/Perfora-0.2.0.zip` and its `.sha256` file. Version comes from the add-in manifest. CI checks geometry and installation on macOS, Windows, and Linux, then publishes new versions as prereleases. Native Fusion checks run separately.

[Contributing and CAD checks](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Release process](docs/PUBLISHING.md)

## A little workshop mythology

Perfora is the goddess of holes, guardian of clean edges, and sworn enemy of repeating the same pattern by hand — from **4FusionLab's own mythology**, with a playful nod to ancient Greece.

[GPL-3.0-only](LICENSE). An independent **4FusionLab** project, not affiliated with or endorsed by Autodesk. Native operation icons are resolved from the user's Fusion installation; Autodesk graphics are not bundled.
