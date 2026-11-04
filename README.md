<p align="center"><img src="perfora.png" alt="Perfora — goddess of holes" width="160"></p>

<h1 align="center">Perfora for Autodesk Fusion</h1>
<p align="center"><strong>Goddess of holes. Precision for Fusion.</strong><br>Create perforations, ventilation grilles, and decorative patterns — without placing every hole by hand.</p>

<p align="center">
  <a href="https://github.com/4FusionLab/Perfora/releases/latest"><img src="https://img.shields.io/github/v/release/4FusionLab/Perfora?label=release" alt="Latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue" alt="GPL-3.0 license"></a>
  <a href="https://github.com/4FusionLab/Perfora/actions/workflows/ci.yml"><img src="https://github.com/4FusionLab/Perfora/actions/workflows/ci.yml/badge.svg" alt="Build"></a>
</p>

<p align="center"><a href="https://github.com/4FusionLab/Perfora/releases/latest"><strong>Download Perfora</strong></a> · <a href="README.ru.md">Русский</a> · <a href="https://github.com/4FusionLab/Perfora/issues">Report an issue</a></p>

Perfora is an open-source **Fusion 360 add-in** for creating procedural perforation, hole patterns, honeycomb ventilation grilles, Voronoi patterns, and perforated CAD panels.

---

## See what you can make

<table>
<tr>
<td width="50%"><img src="docs/assets/examples/honeycomb-panel.jpg" alt="Honeycomb ventilation grille" width="100%"><br><strong>Ventilation grilles</strong><br>Regular, precise openings.</td>
<td width="50%"><img src="docs/assets/examples/voronoi-panel.jpg" alt="Voronoi perforated panel" width="100%"><br><strong>Organic patterns</strong><br>Voronoi and irregular designs.</td>
</tr>
<tr>
<td width="50%"><img src="docs/assets/examples/slotted-disc.jpg" alt="Circular slotted disc" width="100%"><br><strong>Circular layouts</strong><br>Radial and tangential patterns.</td>
<td width="50%"><img src="docs/assets/examples/hole-shapes.jpg" alt="Different hole shapes" width="100%"><br><strong>Shape variety</strong><br>Make the pattern your own.</td>
</tr>
</table>

## What Perfora does

- **Flexible patterns:** 12 repeating hole shapes, 11 distribution families, six organic fields, and Voronoi.
- **Control the boundaries:** adjust spacing, web thickness, edge clearance, rotation, and trimming.
- **Work on your model:** select supported planar or curved faces, sketch profiles, or construction planes.
- **Choose the result:** sketch geometry, Fusion extrusion, or a parametric timeline feature.
- **Preview before applying:** inspect your pattern and adjust it in place.

Feature availability depends on the selected surface and output mode. See [supported combinations and limitations](docs/README_REFERENCE.md#surface-and-distribution-availability).

## Get started

1. Download the add-in from the **[latest release](https://github.com/4FusionLab/Perfora/releases/latest)** and extract the archive to a permanent folder.
2. In Autodesk Fusion, open **Utilities → Scripts and Add-Ins**.
3. Choose **+ → Script or add-in from device**, then select the folder containing `Perfora.py` and `Perfora.manifest`.
4. Select **Perfora → Run**. Find the command in **Design → Solid → Create**, or search for *Perfora* with **S**.

Works with Autodesk Fusion on **Windows and macOS**. Keep the installed folder in place. No separate Python installation is required for this method.

## Learn more

[User guide and detailed reference](docs/README_REFERENCE.md) · [Hole geometry](docs/PERFORATIONS.md) · [Organic patterns](docs/ORGANIC_PATTERNS.md) · [Release notes](docs/releases/v1.1.0.md) · [Changelog](CHANGELOG.md)

[Contributing](CONTRIBUTING.md) · [License](LICENSE) · [Report a problem](https://github.com/4FusionLab/Perfora/issues)

**Other Fusion 360 tools by 4FusionLab:** [Selectra — select similar geometry](https://github.com/4FusionLab/Selectra) · [Ejix — extract solid volumes](https://github.com/4FusionLab/Ejix) · [RuEn — Russian-layout shortcuts](https://github.com/4FusionLab/RuEn) · [Planara — planned surface flattening](https://github.com/4FusionLab/Planara)

## A little workshop mythology

**Perfora**, goddess of holes, guards clean edges and saves makers from repeating the same pattern by hand. She belongs to the original mythology of **[4FusionLab](https://github.com/4FusionLab)**.

<sub>Independent project, not affiliated with or endorsed by Autodesk.</sub>
