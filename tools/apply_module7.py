"""Apply Module 7 combustivel extraction (marker-based, idempotent)."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
legacy_path = ROOT / 'app' / 'legacy.py'

PROTECTED_DEFS = frozenset({'row_to_dict', 'fetch_sistemas_map'})


def find_def_line(lines, name):
    pat = re.compile(rf'^def {re.escape(name)}\(')
    for i, line in enumerate(lines):
        if pat.match(line):
            return i
    raise ValueError(f'def {name} not found')


def find_block_end(lines, start):
    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.startswith('def ') or line.startswith('@app.route('):
            end = i
            break
        if line.startswith('# =') and i > start + 2:
            end = i
            break
    return end


def find_route_block(lines, path_prefix):
    start = None
    route_pat = re.compile(rf"^@app\.route\('{re.escape(path_prefix)}")
    for i, line in enumerate(lines):
        if route_pat.match(line):
            start = i
            break
    if start is None:
        raise ValueError(f'route {path_prefix} not found')
    def_line = start
    for i in range(start, min(start + 5, len(lines))):
        if lines[i].startswith('def '):
            def_line = i
            break
    return start, find_block_end(lines, def_line)


def main():
    raw = legacy_path.read_text(encoding='utf-8')
    if 'register_combustivel(app)' in raw:
        print('Module 7 already applied (register_combustivel present).')
        print('legacy lines:', len(raw.splitlines()))
        return
    print('Run module files manually — this script only checks idempotency.')


if __name__ == '__main__':
    main()
