"""Gera ZIP limpo para publicar no GitHub (sem dados sensíveis)."""
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / 'dist'
OUT = DIST / 'iris-cost-para-github.zip'

SKIP_DIRS = {
    '.git', '.venv', '__pycache__', 'node_modules', '.cursor', 'dist',
    'static/uploads', 'static/exports',
}
SKIP_FILES = {
    'app.db', '.env', 'config.json',
}
SKIP_SUFFIXES = ('.pyc', '.pyo', '.db-journal')


def should_skip(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = set(rel.parts)
    if parts & SKIP_DIRS:
        return True
    if rel.name in SKIP_FILES:
        return True
    if rel.name.endswith(SKIP_SUFFIXES):
        return True
    if rel.parts[:2] == ('seed', 'app_state.json'):
        return True
    return False


def main():
    DIST.mkdir(exist_ok=True)
    count = 0
    with zipfile.ZipFile(OUT, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(ROOT.rglob('*')):
            if not path.is_file():
                continue
            if should_skip(path):
                continue
            arc = path.relative_to(ROOT).as_posix()
            zf.write(path, arc)
            count += 1
    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f'Wrote {OUT} ({count} files, {size_mb:.2f} MB)')
    print(f'Generated at {datetime.now().strftime("%Y-%m-%d %H:%M")}')


if __name__ == '__main__':
    main()
