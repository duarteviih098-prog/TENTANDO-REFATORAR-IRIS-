"""Referências de mês (MM/AAAA) e filtros."""
import re
from datetime import datetime

from app.shared.constants import MESES_PT
from app.shared.formatters import br_now, parse_num
from app.shared.rows import row_get_value, row_matches_month


def normalize_month_reference(raw_value):
    value = str(raw_value or '').strip()
    if not value:
        return ''
    upper = re.sub(r'\s+', ' ', value.upper())
    numeric = re.search(r'(\d{1,2})\s*/\s*(\d{2,4})', upper)
    if numeric:
        month = max(1, min(12, int(numeric.group(1))))
        year = int(numeric.group(2))
        if year < 100:
            year += 2000
        return f"{month:02d}/{year:04d}"
    for month_num, month_name in MESES_PT.items():
        if upper == month_name:
            return f"{month_num:02d}"
        if upper.startswith(month_name + '/') or upper.startswith(month_name + ' '):
            year_match = re.search(r'(\d{4}|\d{2})', upper[len(month_name):])
            if year_match:
                year = int(year_match.group(1))
                if year < 100:
                    year += 2000
                return f"{month_num:02d}/{year:04d}"
            return f"{month_num:02d}"
    return upper

def detect_payments_reference_month(rows, fallback_when=None):
    counts = {}
    for row in (rows or []):
        ref = normalize_month_reference(row_get_value(row, 'pagamento_mes', ''))
        if ref:
            counts[ref] = counts.get(ref, 0) + 1
    if counts:
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    now = fallback_when or datetime.now()
    return f"{now.month:02d}/{now.year:04d}"

def month_reference_matches_selected(raw_value, selected_reference):
    normalized = normalize_month_reference(raw_value)
    selected = normalize_month_reference(selected_reference)
    if not normalized or not selected:
        return False
    if normalized == selected:
        return True
    if len(normalized) == 2 and selected.startswith(normalized + '/'):
        return True
    return False

def month_reference_matches_current(raw_value, when=None):
    value = str(raw_value or '').strip()
    if not value:
        return False
    now = when or datetime.now()
    month = now.month
    year = now.year
    upper = value.upper().strip()
    month_name = MESES_PT.get(month, '')
    numeric_variants = {
        f"{month:02d}/{year}",
        f"{month}/{year}",
        f"{month:02d}/{str(year)[-2:]}",
        f"{month}/{str(year)[-2:]}",
    }
    if upper in numeric_variants:
        return True
    compact = re.sub(r'\s+', ' ', upper)
    if compact == month_name or compact.startswith(f"{month_name}/") or compact.startswith(f"{month_name} "):
        return True
    if month_name in compact and str(year) in compact:
        return True
    return False

def compute_current_month_payments_total(rows, when=None):
    total = 0
    for r in (rows or []):
        if r is None:
            continue
        if hasattr(r, 'keys'):
            keys = set(r.keys())
            valor = r['valor'] if 'valor' in keys else 0
            pagamento_mes = r['pagamento_mes'] if 'pagamento_mes' in keys else ''
        else:
            r = r or {}
            valor = r.get('valor', 0)
            pagamento_mes = r.get('pagamento_mes', '')
        if month_reference_matches_current(pagamento_mes, when=when):
            total += parse_num(valor)
    return total

def current_month_reference(when=None):
    """Mês padrão do sistema para telas mensais: MM/AAAA no fuso do app."""
    now = when or br_now()
    return f"{now.month:02d}/{now.year:04d}"

def month_or_current(value=''):
    """Normaliza mês informado; se vier vazio, usa o mês atual sem apagar histórico."""
    ref = normalize_month_reference(value)
    return ref or current_month_reference()

def filter_rows_by_month(rows, month_ref, month_fields=(), date_fields=()):
    """Filtra linhas por mês mantendo os registros antigos no banco."""
    selected = month_or_current(month_ref)
    filtered = []
    for row in (rows or []):
        values = []
        for field in (month_fields or ()): values.append(row_get_value(row, field, ''))
        for field in (date_fields or ()): values.append(row_get_value(row, field, ''))
        if row_matches_month(*values, month_ref=selected):
            filtered.append(row)
    return filtered
