from pathlib import Path

p = Path(__file__).resolve().parent.parent / 'app' / 'pagamentos' / 'services.py'
lines = p.read_text(encoding='utf-8').splitlines(keepends=True)
start = next(i for i, l in enumerate(lines) if l.startswith('SISTEMAS_E_EQUIPAMENTOS'))
end = next(i for i, l in enumerate(lines) if l.startswith('def import_pagamentos_excel'))
extra = [
    '\n',
    'def first_of(row, *keys):\n',
    "    return _legacy('first_of')(row, *keys)\n",
    '\n',
    'def excel_rows_from_upload(file_storage):\n',
    "    return _legacy('excel_rows_from_upload')(file_storage)\n",
    '\n',
    'def sync_payment_attachments(row, persist_db=False):\n',
    '    from app.storage import sync_payment_attachments as fn\n',
    '    return fn(row, persist_db=persist_db)\n',
    '\n',
]
lines = lines[:start] + extra + lines[end:]
p.write_text(''.join(lines), encoding='utf-8')
print('fixed services.py')
