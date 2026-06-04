"""Helpers de status/total de pagamentos."""
import re

from app.shared.formatters import parse_num
from app.shared.months import month_reference_matches_selected, normalize_month_reference
from app.shared.rows import row_get_value

def payment_status_is_paid(value):
    return str(value or '').strip().lower() in ('sim', 'pago', 'paga', 'ok', 'realizado', 'confirmado')

def compute_payments_totals(rows, selected_reference=None, end_reference=None):
    """Totais de pagamentos, respeitando mês/período quando informado."""
    total = 0.0
    total_pago = 0.0
    total_pendente = 0.0

    selected = normalize_month_reference(selected_reference)
    end = normalize_month_reference(end_reference)

    def month_key(ref):
        ref = normalize_month_reference(ref)
        m = re.search(r'(\d{1,2})\s*/\s*(\d{2,4})', ref or '')
        if not m:
            return None
        month = max(1, min(12, int(m.group(1))))
        year = int(m.group(2))
        if year < 100:
            year += 2000
        return year * 100 + month

    selected_key = month_key(selected)
    end_key = month_key(end)

    for r in (rows or []):
        row_month = normalize_month_reference(row_get_value(r, 'pagamento_mes', row_get_value(r, 'month_ref', '')))

        if selected:
            if end and selected_key and end_key:
                rk = month_key(row_month)
                if rk is None or rk < selected_key or rk > end_key:
                    continue
            elif not month_reference_matches_selected(row_month, selected):
                continue

        valor = parse_num(row_get_value(r, 'valor', 0))
        total += valor
        if payment_status_is_paid(row_get_value(r, 'status', '')):
            total_pago += valor
        else:
            total_pendente += valor

    return total, total_pago, total_pendente
