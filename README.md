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

<p align="center"><a href="https://github.com/4FusionLab/Perfora/releases/tag/v0.1.5"><strong>Download v0.1.5</strong></a> · <a href="README.ru.md">Русский</a> · <a href="https://github.com/4FusionLab/Perfora/issues">Report a problem</a></p>

> **Experimental release.** Use copies of working designs. Native Windows CAD behavior, document save/reopen, and complex assemblies still need acceptance testing.

## Make the pattern. Keep the native model.

Select a planar face, a closed sketch profile, or a construction plane. Choose a hole shape, set the spacing and edge clearance, and preview the result. Perfora creates ordinary sketch profiles or a native Fusion Extrude feature.

![Twelve supported hole shapes](docs/assets/hole-shapes.svg)

| Control | What you can do |
| --- | --- |
| Pattern | Rectangular or staggered distribution; web thickness; independent hole and grid rotation; X/Y placement |
| Boundary | Keep complete holes or trim them to the boundary, with an edge offset and clearance around existing openings |
| Output | Hole profiles or a perforated panel; sketch only or an Extrude feature |
| Operation | Join, Cut, Intersect, New Body, New Component |
| Extent | One Side, Two Sides, Symmetric; distance, through-all, or to-object where supported |
| Preview | Cached fast contours for layout; full CAD preview to inspect the extrusion |

See [hole dimensions and geometry notes](docs/PERFORATIONS.md). The interface is in English, using Fusion's native operation names. No third-party Python packages are required.

## Install

**Requires Autodesk Fusion on macOS or Windows.** Python 3 is needed for the installer; the add-in runs using Fusion's own Python runtime. Linux is supported for tests and packaging only.

1. Download **[Perfora-0.1.5.zip](https://github.com/4FusionLab/Perfora/releases/download/v0.1.5/Perfora-0.1.5.zip)** from the [release page](https://github.com/4FusionLab/Perfora/releases/tag/v0.1.5) and extract it.
2. Open a terminal in the extracted folder and run:

   ```sh
   # macOS
   python3 install.py

   # Windows
   py -3 install.py
   ```

3. In Fusion, open **Utilities → Scripts and Add-Ins → Add-Ins**, select **Perfora**, and click **Run**.
4. Find **Perfora** in **Design → Solid → Create**, or press **S** and search.

If Fusion does not list it, add the installed `Perfora` folder with the `+` button. The installer prints its location. Existing Perfora installations are backed up outside AddIns/Scripts; automatic startup is disabled.

To specify the Fusion API directory: `python3 install.py --api-root "/path/to/Fusion/API"`.

**Upgrading from Perforator:** stop and unregister the old add-in before running Perfora. The installer preserves the old directory. Do not run both versions together; command IDs and document attributes are intentionally compatible.

## Two starting points

**Vent a box wall:** select a planar face → set Hole Shape, Web Thickness, and Edge Offset → Extrude → Holes → Cut → All → check direction and Objects → OK.

**Build a separate grille:** select a closed sketch profile or construction plane → set the pattern → Extrude → Perforated Panel → New Body or New Component → set thickness → OK.

On a construction plane, Boundary defines a centered rectangle or circle. **Trim to Boundary** includes partial holes along the edge; **Edge Offset** remains active.

## Know the limits

- Planar geometry and solid bodies only; curved faces and mesh bodies are unsupported.
- There is no custom parametric Perfora feature. Editing the boundary does not regenerate the complete pattern; Edit Feature does not reopen the pattern dialog. Undo or remove the result and run Perfora again to change the layout.
- Native Extrude parameters remain editable in Fusion. Source and Cut/Intersect target bodies must belong to the same component. Editing a component affects all its occurrences.
- The default limit is 1,500 holes, configurable up to 5,000. Dense patterns and full previews take longer. Some rotated shapes use conservative spacing, so the actual web can be wider than requested.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 install.py --zip
```

The build produces `dist/Perfora-0.1.5.zip` and its `.sha256` file. Version comes from the add-in manifest. CI checks geometry and installation on macOS, Windows, and Linux, then publishes new versions as prereleases. Native Fusion checks run separately.

[Contributing and CAD checks](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Release process](docs/PUBLISHING.md)

## A little workshop mythology

Perfora is the goddess of holes, guardian of clean edges, and sworn enemy of repeating the same pattern by hand — from **4FusionLab's own mythology**, with a playful nod to ancient Greece.

[GPL-3.0-only](LICENSE). An independent **4FusionLab** project, not affiliated with or endorsed by Autodesk. Native operation icons are resolved from the user's Fusion installation; Autodesk graphics are not bundled.
