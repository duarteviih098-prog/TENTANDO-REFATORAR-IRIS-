"""Módulo Pagamentos."""
from app.pagamentos.api import register_api_routes
from app.pagamentos.routes import register_routes
from app.pagamentos.services import (
    build_payment_attachment_items,
    ensure_pagamentos_valid_ids,
    import_pagamentos_excel,
    pagamentos_query_rows,
    pagamentos_totais_from_rows,
    prepare_payment_row_for_template,
    save_pagamento,
)


def register_pagamentos(app):
    register_routes(app)
    register_api_routes(app)


__all__ = [
    'register_pagamentos',
    'prepare_payment_row_for_template',
    'build_payment_attachment_items',
    'save_pagamento',
    'import_pagamentos_excel',
    'ensure_pagamentos_valid_ids',
    'pagamentos_query_rows',
    'pagamentos_totais_from_rows',
]
