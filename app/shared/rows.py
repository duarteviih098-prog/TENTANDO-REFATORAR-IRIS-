"""Utilitários de linha/dict de query."""
import json

from app.shared.formatters import parse_br_date


def row_get_value(row, key, default=None):
    if row is None:
        return default
    if hasattr(row, 'keys'):
        try:
            return row[key] if key in row.keys() else default
        except Exception:
            return default
    if isinstance(row, dict):
        return row.get(key, default)
    return default


def first_of(row, *keys):
    for k in keys:
        if row.get(k) not in (None, ''):
            return str(row.get(k)).strip()
    return ''


def row_matches_month(*values, month_ref=''):
    month_ref = (month_ref or '').strip()
    if not month_ref:
        return True
    for value in values:
        raw = str(value or '').strip()
        if not raw:
            continue
        if raw.endswith(month_ref) or raw == month_ref:
            return True
        parsed = parse_br_date(raw)
        if parsed and parsed.strftime('%m/%Y') == month_ref:
            return True
    return False


def row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for key in ['anexos_orcamento', 'anexos_nf', 'anexos_boleto', 'imagens', 'orcamentos', 'detalhes_json']:
        if key in d:
            try:
                d[key] = json.loads(d[key] or '[]')
            except Exception:
                d[key] = []
    from app.storage.attachments import ATTACHMENT_GROUPS, sync_payment_attachments
    if any(k in d for k in ATTACHMENT_GROUPS.values()):
        d = sync_payment_attachments(d, persist_db=False)
    return d
