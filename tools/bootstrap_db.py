#!/usr/bin/env python3
"""Bootstrap banco vazio com migrations versionadas (P0).

Uso SQLite:
  python tools/bootstrap_db.py --db-path app.db

Uso Postgres (Supabase):
  set DATABASE_URL=postgresql://...
  python tools/bootstrap_db.py
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def bootstrap(db_path=None):
    if db_path:
        os.environ['IRIS_TEST_DB'] = str(Path(db_path).resolve())
        os.environ.pop('DATABASE_URL', None)

    from app.db import ensure_db, migration_status

    ensure_db()
    status = migration_status()
    print('Migrations aplicadas:', status['applied'])
    if status['pending']:
        print('Pendentes:', status['pending'])
        raise SystemExit(1)
    print('Bootstrap concluído.')


def main():
    parser = argparse.ArgumentParser(description='Bootstrap banco IRIS com migrations P0')
    parser.add_argument('--db-path', help='Caminho do SQLite (ignorado se DATABASE_URL estiver definida)')
    args = parser.parse_args()
    bootstrap(db_path=args.db_path)


if __name__ == '__main__':
    main()
