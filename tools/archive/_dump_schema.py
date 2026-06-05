"""Dump SQLite schema from app.db (one-shot helper)."""
import sqlite3
import sys
from pathlib import Path

db = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / 'app.db'
if not db.exists():
    print('missing', db)
    raise SystemExit(1)
conn = sqlite3.connect(db)
tables = [
    r[0]
    for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
]
for t in tables:
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)
    ).fetchone()[0]
    print(f'-- {t}')
    print(sql + ';')
    print()
