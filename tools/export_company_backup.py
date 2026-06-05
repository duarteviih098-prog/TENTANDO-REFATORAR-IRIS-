#!/usr/bin/env python3
"""Exporta backup JSON de uma empresa (P1 — backup manual).

Uso:
  python tools/export_company_backup.py --empresa-id 1
  python tools/export_company_backup.py --empresa-id 1 --output C:\\backups\\
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def export_company_backup(empresa_id, output_dir=None):
    from app.auth.constants import TENANT_TABLES
    from app.db import ensure_db, query_all, query_one, table_has_column
    from app.shared.formatters import now_str

    ensure_db()
    empresa = query_one('SELECT id, nome FROM empresas WHERE id=?', (empresa_id,))
    if not empresa:
        raise SystemExit(f'Empresa {empresa_id} não encontrada.')

    data = {
        'empresa_id': int(empresa_id),
        'empresa_nome': empresa['nome'],
        'gerado_em': now_str(),
        'tabelas': {},
    }
    for table in sorted(TENANT_TABLES):
        if table_has_column(table, 'empresa_id'):
            rows = query_all(f'SELECT * FROM {table} WHERE empresa_id=? ORDER BY id', (empresa_id,))
            data['tabelas'][table] = [dict(r) for r in rows]

    out_dir = Path(output_dir) if output_dir else ROOT / 'backups'
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_name = ''.join(c if c.isalnum() else '_' for c in str(empresa['nome']))[:40]
    path = out_dir / f'backup_empresa_{empresa_id}_{safe_name}_{stamp}.json'
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(path)
    return path


def main():
    parser = argparse.ArgumentParser(description='Exporta backup JSON por empresa')
    parser.add_argument('--empresa-id', type=int, required=True)
    parser.add_argument('--output', default='', help='Pasta de destino')
    args = parser.parse_args()
    export_company_backup(args.empresa_id, args.output or None)


if __name__ == '__main__':
    main()
