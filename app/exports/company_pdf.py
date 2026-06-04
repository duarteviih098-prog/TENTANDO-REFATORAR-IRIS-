"""Colunas persistentes de identidade PDF da empresa."""
from app.db import execute, table_columns
from app.db.schema import _TABLE_COLUMN_CACHE, _TABLE_COLUMNS_CACHE

COMPANY_PDF_COLUMNS = {
    'cliente_pdf': 'TEXT',
    'contratada_pdf': 'TEXT',
    'cnpj_pdf': 'TEXT',
    'cidade_pdf': 'TEXT',
    'responsavel_pdf': 'TEXT',
    'assinatura_esquerda_label': 'TEXT',
    'assinatura_direita_label': 'TEXT',
}



def ensure_company_pdf_columns():
    """Garante as colunas persistentes dos dados cadastrais usados nos PDFs."""
    try:
        existing = table_columns('empresas')
        for column, ddl in COMPANY_PDF_COLUMNS.items():
            if column not in existing:
                execute(f'ALTER TABLE empresas ADD COLUMN {column} {ddl}')
                try:
                    _TABLE_COLUMN_CACHE.pop(('empresas', column), None)
                    _TABLE_COLUMNS_CACHE.pop('empresas', None)
                except Exception:
                    pass
                existing = table_columns('empresas')
        return True
    except Exception as exc:
        print('ensure_company_pdf_columns falhou:', exc)
        return False








