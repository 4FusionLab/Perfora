<p align="center"><img src="perfora.png" alt="Перфора — богиня отверстий" width="160"></p>

<h1 align="center">Perfora для Autodesk Fusion</h1>
<p align="center"><strong>Богиня отверстий. Точность в каждой детали.</strong><br>Перфорация, вентиляционные решётки и декоративные узоры — без ручного размещения каждого отверстия.</p>

<p align="center">
  <a href="https://github.com/4FusionLab/Perfora/releases/latest"><img src="https://img.shields.io/github/v/release/4FusionLab/Perfora?label=release" alt="Последний релиз"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue" alt="Лицензия GPL-3.0"></a>
  <a href="https://github.com/4FusionLab/Perfora/actions/workflows/ci.yml"><img src="https://github.com/4FusionLab/Perfora/actions/workflows/ci.yml/badge.svg" alt="Сборка"></a>
</p>

<p align="center"><a href="https://github.com/4FusionLab/Perfora/releases/latest"><strong>Скачать Perfora</strong></a> · <a href="README.md">English</a> · <a href="https://github.com/4FusionLab/Perfora/issues">Сообщить о проблеме</a></p>

---

## Что можно создать

<table>
<tr>
<td width="50%"><img src="docs/assets/examples/honeycomb-panel.jpg" alt="Вентиляционная решётка" width="100%"><br><strong>Вентиляционные решётки</strong><br>Аккуратные повторяющиеся отверстия.</td>
<td width="50%"><img src="docs/assets/examples/voronoi-panel.jpg" alt="Перфорация Вороного" width="100%"><br><strong>Органические узоры</strong><br>Вороной и нерегулярные рисунки.</td>
</tr>
<tr>
<td width="50%"><img src="docs/assets/examples/slotted-disc.jpg" alt="Круговая раскладка прорезей" width="100%"><br><strong>Круговые раскладки</strong><br>Радиальные и тангенциальные узоры.</td>
<td width="50%"><img src="docs/assets/examples/hole-shapes.jpg" alt="Разные формы отверстий" width="100%"><br><strong>Разнообразие форм</strong><br>Настройка рисунка под задачу.</td>
</tr>
</table>

## Возможности

**Perfora** — аддон **Fusion 360** для создания массивов отверстий, сотовой и декоративной перфорации, вентиляционных решёток, узоров Вороного и параметрических панелей.

- **Гибкие узоры:** 12 повторяемых форм отверстий, 11 способов распределения, шесть органических полей и Вороной.
- **Контроль геометрии:** шаг, толщина перемычек, отступы, поворот и обрезка по границе.
- **Работа с моделью:** поддерживаемые плоские и криволинейные грани, профили эскизов и конструкционные плоскости.
- **Разные результаты:** эскиз, штатное выдавливание Fusion или параметрический элемент в истории.
- **Предпросмотр:** настройка узора до создания геометрии.

Доступность возможностей зависит от типа поверхности и режима результата. Подробнее — в [справке по совместимости](docs/README_REFERENCE.ru.md#совместимость-поверхностей-и-раскладок).

## Быстрый старт

1. Скачайте архив из **[последнего релиза](https://github.com/4FusionLab/Perfora/releases/latest)** и распакуйте его в постоянную папку.
2. В Autodesk Fusion откройте **Utilities → Scripts and Add-Ins**.
3. Нажмите **+ → Script or add-in from device** и выберите папку с файлами `Perfora.py` и `Perfora.manifest`.
4. Выберите **Perfora → Run**. Команда доступна в **Design → Solid → Create** и через поиск **S**.

Поддерживаются **Windows и macOS**. Не перемещайте папку после подключения. При таком способе установки отдельный Python не требуется.

## Подробнее

[Подробное руководство](docs/README_REFERENCE.ru.md) · [Геометрия отверстий](docs/PERFORATIONS.md) · [Органические узоры](docs/ORGANIC_PATTERNS.md) · [Что нового в 1.1.0](docs/releases/v1.1.0.md) · [История изменений](CHANGELOG.md)

[Участие в разработке](CONTRIBUTING.md) · [Лицензия](LICENSE) · [Сообщить о проблеме](https://github.com/4FusionLab/Perfora/issues)

**Другие аддоны Fusion 360 от 4FusionLab:** [Selectra — выбор похожей геометрии](https://github.com/4FusionLab/Selectra) · [Ejix — извлечение объёмов](https://github.com/4FusionLab/Ejix) · [RuEn — горячие клавиши при русской раскладке](https://github.com/4FusionLab/RuEn) · [Planara — будущая развёртка поверхностей](https://github.com/4FusionLab/Planara)

## Немного мифологии

**Перфора** — богиня отверстий, хранительница аккуратных кромок и противница ручного повторения узоров. Она входит в авторский пантеон **[4FusionLab](https://github.com/4FusionLab)**.

<sub>Независимый проект, не связанный с Autodesk и не одобренный ею.</sub>
