# SPDX-License-Identifier: GPL-3.0-only
"""Install a self-contained local copy, preserving any prior installation."""
import argparse
from datetime import datetime
import json
import hashlib
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parent


def build_archive(root=ROOT):
    """Build the same ZIP on every OS, with a checksum for release verification."""
    version = json.loads((root / 'Perfora/Perfora.manifest').read_text(encoding='utf-8'))['version']
    target = root / ('dist/Perfora-' + version + '.zip')
    target.parent.mkdir(exist_ok=True)
    files = []
    for directory in ('Perfora', 'PerforaSmokeTest', 'tests', 'docs', 'scripts'):
        files.extend(p for p in (root / directory).rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts
                     and p.suffix not in ('.pyc', '.pyo') and p.name != '.DS_Store')
    files.extend(root / name for name in (
        'README.md', 'README.ru.md', 'CONTRIBUTING.md', 'CHANGELOG.md',
        'LICENSE', 'perfora.png', 'install.py'))
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(path.relative_to(root).as_posix(), (2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.zip.sha256').write_text(digest + '  ' + target.name + '\n', encoding='utf-8')
    return target


def default_api_root():
    if sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support/Autodesk'
    elif sys.platform == 'win32':
        import os
        base = Path(os.environ['APPDATA']) / 'Autodesk'
    else:
        raise SystemExit('Fusion поддерживает macOS и Windows. Для ZIP используйте --zip.')
    # Prefer the actual local API location; product-folder naming differs by release.
    candidates = [base / 'Autodesk Fusion/API', base / 'Autodesk Fusion 360/API']
    return next((p for p in candidates if p.exists()), candidates[0])


def copy_directory(source, destination):
    if destination.is_symlink():
        raise SystemExit('Отказ: целевой каталог является символической ссылкой: ' + str(destination))
    if destination.exists():
        backup = destination.with_name(destination.name + '.backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        # Backups outside AddIns/Scripts cannot be auto-discovered by Fusion.
        backup_root = destination.parent.parent / 'PerforaBackups'
        backup_root.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(backup_root / backup.name))
        print('Предыдущая версия:', backup_root / backup.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    print('Установлено:', destination)


def main():
    parser = argparse.ArgumentParser(description='Установка Perfora для Fusion')
    parser.add_argument('--api-root', type=Path, help='Каталог API Fusion')
    parser.add_argument('--zip', action='store_true', help='Только собрать переносимый ZIP')
    args = parser.parse_args()
    if args.zip:
        target = build_archive()
        print(target)
        return
    api_root = args.api_root or default_api_root()
    copy_directory(ROOT / 'Perfora', api_root / 'AddIns/Perfora')
    copy_directory(ROOT / 'PerforaSmokeTest', api_root / 'Scripts/PerforaSmokeTest')
    print('В Fusion: Utilities → Scripts and Add-Ins → Add-Ins → Perfora → Run.')


if __name__ == '__main__':
    main()
