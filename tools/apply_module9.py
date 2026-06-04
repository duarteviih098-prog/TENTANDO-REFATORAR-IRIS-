"""Apply Module 9 custos extraction (idempotent check)."""
from pathlib import Path

legacy_path = Path(__file__).resolve().parent.parent / 'app' / 'legacy.py'

if __name__ == '__main__':
    raw = legacy_path.read_text(encoding='utf-8')
    if 'register_custos(app)' in raw:
        print('Module 9 already applied.')
    else:
        print('Run manual extraction — see app/custos/.')
    print('legacy lines:', len(raw.splitlines()))
