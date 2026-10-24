<p align="center">
  <img src="perfora.png" alt="Perfora — goddess of holes" width="200">
</p>

<h1 align="center">Perfora for Autodesk Fusion</h1>
<p align="center"><strong>Goddess of holes. Precision for Fusion.</strong><br>Hole patterns, ventilation grilles, and perforated panels — without placing every hole by hand.</p>

<p align="center">
  <a href="https://github.com/4FusionLab/Perfora/actions/workflows/ci.yml"><img src="https://github.com/4FusionLab/Perfora/actions/workflows/ci.yml/badge.svg" alt="Build and release checks"></a>
  <a href="https://github.com/4FusionLab/Perfora/releases"><img src="https://img.shields.io/github/v/release/4FusionLab/Perfora?color=2077bd" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue" alt="GPL-3.0 license"></a>
</p>

<p align="center"><a href="https://github.com/4FusionLab/Perfora/releases/tag/v1.0.0"><strong>Download v1.0.0</strong></a> · <a href="README.ru.md">Русский</a> · <a href="https://github.com/4FusionLab/Perfora/issues">Report a problem</a></p>


## Make the pattern. Keep the native model.

Select a planar face, a closed sketch profile, or a construction plane. Choose a hole shape, set the spacing and edge clearance, and preview the result. Perfora creates ordinary sketch profiles, a native Fusion Extrude, or a parametric Perfora timeline feature.

To perforate part of an existing face, draw a closed sketch on that face, finish the sketch, and select its shaded profile in **Profiles**. No Split Face is required. For **Cut** or **Intersect**, the supporting body is selected automatically in **Objects**; check the direction and extent before confirming. Profiles on construction planes still require explicit Objects.

**Perfora 1.0 is the first stable release.** Parametric patterns, circular placement, bounded spread, and faster previews. [What is new →](docs/releases/v1.0.0.md)

## Made with Perfora

<table>
  <tr>
    <td width="50%" valign="top">
      <a href="docs/assets/examples/honeycomb-panel.jpg"><img src="docs/assets/examples/honeycomb-panel.jpg" alt="Blue rectangular grille with hexagonal perforation and four mounting holes" width="100%"></a>
      <p><strong>Honeycomb grille</strong><br>Hexagonal cells, an outer frame, and mounting holes.</p>
    </td>
    <td width="50%" valign="top">
      <a href="docs/assets/examples/voronoi-panel.jpg"><img src="docs/assets/examples/voronoi-panel.jpg" alt="Green rectangular panel with rounded Voronoi perforation" width="100%"></a>
      <p><strong>Rounded Voronoi</strong><br>An irregular pattern with rounded corners and a defined edge.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <a href="docs/assets/examples/slotted-disc.jpg"><img src="docs/assets/examples/slotted-disc.jpg" alt="Orange circular plate with diagonal slots and a central opening" width="100%"></a>
      <p><strong>Slots on a circular boundary</strong><br>Partial slots follow the outer edge and central opening.</p>
    </td>
    <td width="50%" valign="top">
      <a href="docs/assets/examples/hole-shapes.jpg"><img src="docs/assets/examples/hole-shapes.jpg" alt="Six colored panels showing circular, triangular, star, elliptical, diamond, and cross perforations" width="100%"></a>
      <p><strong>A shape for every pattern</strong><br>Circles, triangles, stars, ellipses, diamonds, and crosses.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <a href="docs/assets/examples/v1.0.0/circular-tangential.jpg"><img src="docs/assets/examples/v1.0.0/circular-tangential.jpg" alt="Gold circular grille with tangential slots on concentric rings" width="100%"></a>
      <p><strong>Slots that follow the circle</strong><br>Circular distribution, Tangential orientation, and a clean center opening.</p>
    </td>
    <td width="50%" valign="top">
      <a href="docs/assets/examples/v1.0.0/radial-and-tangential.jpg"><img src="docs/assets/examples/v1.0.0/radial-and-tangential.jpg" alt="Two circular grilles comparing radial and tangential slots" width="100%"></a>
      <p><strong>Choose the direction</strong><br>Radial on the left, Tangential on the right. Fixed orientation is available too.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <a href="docs/assets/examples/v1.0.0/point-scoped-perforation.jpg"><img src="docs/assets/examples/v1.0.0/point-scoped-perforation.jpg" alt="Green plate perforated only inside an off-center circular zone" width="100%"></a>
      <p><strong>Start here. Stop at this radius.</strong><br>Pick a point and limit the spread without drawing a boundary profile.</p>
    </td>
    <td width="50%" valign="top">
      <a href="docs/assets/examples/v1.0.0/profile-region.jpg"><img src="docs/assets/examples/v1.0.0/profile-region.jpg" alt="Blue plate with rounded Voronoi perforation confined to a sketch profile" width="100%"></a>
      <p><strong>Your sketch is the boundary</strong><br>Perforate a profile directly on a solid face. No Split Face.</p>
    </td>
  </tr>
  <tr>
    <td colspan="2" valign="top">
      <a href="docs/assets/examples/v1.0.0/parametric-spread.jpg"><img src="docs/assets/examples/v1.0.0/parametric-spread.jpg" alt="Two panels showing a parametric spread radius change from 16 to 26 millimeters" width="100%"></a>
      <p><strong>Change the parameter. Rebuild the pattern.</strong><br>Spread Radius 16 mm and 26 mm; the right-hand Feature recomputes after editing its model parameter.</p>
    </td>
  </tr>
</table>

<details>
<summary>View the twelve regular hole shapes</summary>

![Twelve supported regular hole shapes](docs/assets/hole-shapes.svg)

</details>

| Control | What you can do |
| --- | --- |
| Pattern | Rectangular, staggered, or circular distribution; web thickness; independent hole and grid rotation; X/Y placement |
| Boundary | Keep complete holes or trim them to the boundary, with an edge offset and clearance around existing openings |
| Output | Hole profiles or a perforated panel; Sketch, native Extrude, or parametric Feature (default) |
| Operation | Join, Cut, Intersect, New Body, New Component |
| Extent | One Side, Two Sides, Symmetric; distance, through-all, or to-object where supported |
| Preview | Cached fast contours for layout; full CAD preview to inspect the extrusion |

See [hole dimensions and geometry notes](docs/PERFORATIONS.md). The interface is in English, using Fusion's native operation names. No third-party Python packages are required.

Every numeric field has a default. Leaving a field empty restores its default after about a second, while allowing you to clear and immediately type a replacement. Explicit zero values are preserved, and nonempty invalid expressions are not replaced. Units, equations, and parameters from the current Fusion document are supported; integer fields retain their range limits.

**Type → Feature** is selected by default when opening Perfora. Sketch and Extrude remain available.

**Preview Color** changes Fast Preview contours: Gold (default), Cyan, Magenta, Green, White, or Black. Switch colors to keep contours visible over selected profiles. Color changes reuse the existing graphics and hole layout. Full Preview uses the Fusion model appearance.

Fusion selection highlighting can tint or cover custom graphics while an entity is selected; the thicker contours improve contrast, but Preview Color does not override Fusion selection colors.

## Voronoi

**Voronoi** is the thirteenth hole shape, available since 0.2.0. Select **Hole Shape → Voronoi**, then adjust **Cell Spacing**, **Irregularity (%)**, and **Seed**. **New Pattern** advances the seed while keeping the other settings. A seed reproduces the same pattern for the same source and settings.

Cell Spacing controls the nominal distance between sites, rather than the size of every hole. Irregularity ranges from regular square cells at 0% to varied convex polygons at 100%. **Web Thickness** sets the minimum gap between holes; a large web can consume small cells. **Distribution** and **Hole Angle** are hidden in this mode. Pattern rotation, X/Y offsets, edge clearance, exact trimming, Fast/Full Preview, sketch profiles, and native Extrude remain available.

Enable **Round Corners** to add tangent circular fillets to the Voronoi holes. **Corner Radius** sets the maximum radius. Short bevels are absorbed by the rounded contour; the radius is reduced only when the hole is too narrow. Rounding is off by default and preserves the minimum web. Fast Preview follows the same arcs used by the sketch and Extrude. New convex corners at straight and circular trim boundaries are rounded too. Existing concave source corners and elliptical/spline boundary segments retain their exact geometry.

## Parametric Feature

**Type → Feature** creates one **Perfora** node in the timeline. With the add-in running, changing its model parameters or upstream source geometry regenerates the pattern, including the number of holes. Double-click the node or choose **Edit Feature** to edit the pattern, trimming, placement, profile type, and thickness. Expressions can reference Fusion user parameters. OK commits the edit; Cancel restores the previous model.

All 13 shapes, exact trimming, rounded Voronoi holes, Fast/Full Preview, and **Join**, **Cut**, **Intersect**, **New Body** are supported. **Capture Design History** is required. This initial mode supports **Distance** with zero taper and **One Side**, **Two Sides**, **Symmetric**. Source, operation, and target bodies stay fixed during edit. Use Extrude for **All**, **To Object**, taper, or **New Component**.

Keep Perfora running to edit or recompute the feature. Large topology changes can invalidate downstream face/edge references. The mode uses Autodesk's [Custom Feature API](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/CustomFeatures_UM.htm), which remains in Preview.

The unreleased working copy fixes Feature Cut losing its target when an upstream face shrinks with **Trim to Boundary** and a nonzero **Edge Offset**. The regression covers a box height change from 70 mm to 20 mm and back, including rounded Voronoi holes. This fix is not included in the published 1.0.0 archive.

## Pattern origin and spread

**Start Point** is available for Staggered, Rectangular, Circular, and Voronoi. Use the native Select control to pick a sketch point, model vertex, or construction point; points on other planes are projected onto Profiles. Clear the selection for automatic placement. X/Y Offset add displacement from this point (in pattern axes for grids/Voronoi, sketch axes for Circular).

**Spread Radius** limits perforation to a circular zone around that origin, including the offsets. **0 mm** fills the selected boundary. Positive values need no additional sketch profile: select a face or construction plane, pick a point, and enter a radius. The source boundary and existing openings still constrain the result. Edge Offset also applies to the spread boundary. With Trim to Boundary off, only whole holes fit; with it on, partial holes are trimmed exactly to the zone. Perforated Panel retains the source panel outside the perforation zone.

New Feature nodes expose Spread Radius as a Fusion model parameter, including expressions. Point dependencies and the radius drive recompute. Older nodes remain editable but cannot gain additional native model parameters through the current API; recreate a node if it needs the new parameter in Fusion's Parameters dialog.

## Circular distribution

**Distribution → Circular** places holes on concentric rings. It supports all 12 repeating shapes; Voronoi keeps its own distribution. Available in the stable 1.0 release.

- **Start Radius** measures the first ring to hole centers. At 0, the pattern starts with one center hole; a positive value omits that hole. This does not specify a solid central zone: holes may extend inside the first ring.
- Holes per ring and radial spacing are automatic, based on the shape size and **Web Thickness**. Chord spacing preserves the web across each ring's closing seam. Noncircular shapes use conservative enclosing bounds, so actual webs can be wider than requested.
- **Orientation → Fixed** keeps holes parallel; **Radial** rotates each hole with its radial position. **Tangential** follows the circumference. **Hole Angle** adds a rotation in all three modes. Orientation is hidden for circles.
- **Start Point** uses Fusion's native Select control: pick a sketch point, model vertex, or construction point. Points on other planes are projected onto the Profiles plane. Clear the selection to use the outer boundary's bounding-box center. **X Offset / Y Offset** move the pattern relative to the selected point or automatic center, in sketch axes without periodic wrapping. **Pattern Angle** rotates the pattern about this center without moving the center itself.
- **Edge Offset**, internal openings, **Trim to Boundary**, Fast/Full Preview, profiles and Extrude operations remain available. In Feature mode, the selected point is a dependency: moving it recomputes the pattern, and Edit Feature can replace or clear it. Ring radii and spacing are set before trimming; changing the boundary can move the pattern with its bounding-box center.

## Performance

Measured before/after results include **3.424 → 0.262 s** for a 45-hole elliptical Fast Preview and **1.148 → 0.104 s** for 253 hexagons in a circular region. These are paired measurements in Fusion on macOS, not universal speed guarantees. [Benchmark data, scenarios, and methodology →](docs/BENCHMARKS.md)

Fast Preview and final creation reuse the current command's prepared hole layout. Changing extrusion settings still applies the current values to the final result. Changes to the source geometry, plane, point, radius, or layout invalidate the corresponding data. Clipped hole previews defer panel-only Boolean work until Perforated Panel is selected. Small simple patterns keep a direct clearance-check path.

The optimizations preserve hole contours, clearance checks, Voronoi Seed, and exact trimming. Building many native sketch curves and profiles can still dominate the total time; geometry-generation speedups do not apply uniformly to the whole command.

## Install

**Requires Autodesk Fusion on macOS or Windows. No terminal or separate Python installation is needed for the recommended method.** Perfora runs using the Python runtime included with Fusion. Linux is supported for tests and packaging only.

### Recommended: add the folder in Fusion

1. Download **[Perfora-1.0.0.zip](https://github.com/4FusionLab/Perfora/releases/download/v1.0.0/Perfora-1.0.0.zip)** from the [release page](https://github.com/4FusionLab/Perfora/releases/tag/v1.0.0) and extract it to a permanent location.
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

Native CAD acceptance is recorded for Fusion 2706.1.14 on macOS 27.0.1, including local F3D reopen. Windows CI checks Python code and installation; native Windows Fusion CAD, cloud save/reopen, and complex assemblies are not claimed as tested.

- Edge Offset must leave a valid inset; touching or intersecting offset loops can be rejected by Fusion.
- Planar geometry and solid bodies only; curved faces and mesh bodies are unsupported.
- Sketch and Extrude outputs keep a fixed hole layout. Use Feature to regenerate the pattern.
- Native Extrude parameters remain editable in Fusion. Source and Cut/Intersect target bodies must belong to the same component. Editing a component affects all its occurrences.
- The default limit is 1,500 holes, configurable up to 5,000. Dense patterns and full previews take longer. Some rotated shapes use conservative spacing, so the actual web can be wider than requested.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 install.py --zip
```

The build produces `dist/Perfora-1.0.0.zip` and its `.sha256` file. Version comes from the add-in manifest. CI checks geometry and installation on macOS, Windows, and Linux, then publishes verified 1.x versions as stable releases marked Latest. The earlier 0.x versions remain prereleases. Native Fusion checks run separately.

[Contributing and CAD checks](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Release process](docs/PUBLISHING.md)

## A little workshop mythology

Perfora is the goddess of holes, guardian of clean edges, and sworn enemy of repeating the same pattern by hand — from **4FusionLab's own mythology**, with a playful nod to ancient Greece.

[GPL-3.0-only](LICENSE). An independent **4FusionLab** project, not affiliated with or endorsed by Autodesk. Native operation icons are resolved from the user's Fusion installation; Autodesk graphics are not bundled.
