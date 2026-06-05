"""Rotas de exportação — relatório Iris e parse de boleto."""
from flask import flash, jsonify, redirect, request, url_for

from app.auth.decorators import require_permission
from app.exports.jobs import _render_iris_job_wait_page
from app.shared.rows import row_to_dict


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def current_company():
    from app.auth import current_company as fn
    return fn()


def current_user_is_super_admin():
    from app.auth import current_user_is_super_admin as fn
    return fn()


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)


def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)


def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)


def table_columns(table):
    from app.db import table_columns as fn
    return fn(table)


def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)


def select_existing_columns(table, desired, fallback='id'):
    from app.db.schema import select_existing_columns as fn
    return fn(table, desired, fallback=fallback)


def ensure_column(table, column, col_type):
    from app.db import ensure_column as fn
    return fn(table, column, col_type)
@require_permission('edit_pagamentos')
def api_boleto_parse_vencimento():
    f = request.files.get('boleto')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'Nenhum arquivo enviado'}), 400
    try:
        import io as _io
        import re as _re

        import pdfplumber
        data = f.read()
        vencimento = None
        with pdfplumber.open(_io.BytesIO(data)) as pdf:
            text = ''
            for page in pdf.pages[:3]:
                text += (page.extract_text() or '') + ' '
        patterns = [
            r'[Vv]encimento[\s:]*(\d{2}/\d{2}/\d{4})',
            r'[Vv]enc[\s.:]*(\d{2}/\d{2}/\d{4})',
            r'(\d{2}/\d{2}/\d{4})',
        ]
        for pattern in patterns:
            m = _re.search(pattern, text)
            if m:
                candidate = m.group(1)
                parts = candidate.split('/')
                if len(parts) == 3 and int(parts[2]) >= 2020:
                    vencimento = candidate
                    break
        if vencimento:
            return jsonify({'ok': True, 'vencimento': vencimento})
        return jsonify({'ok': False, 'error': 'Não foi possível identificar a data de vencimento'})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500




@require_permission('generate_pdf')
def iris_relatorio_wait(job_id):
    """Página de espera animada para relatório IA."""
    if current_user_is_super_admin():
        job = row_to_dict(query_one('SELECT id, status, arquivo_url, tipo, mes FROM pdf_jobs WHERE id=?', (job_id,)))
    else:
        job = row_to_dict(query_one(
            'SELECT id, status, arquivo_url, tipo, mes FROM pdf_jobs WHERE id=? AND empresa_id=?',
            (job_id, current_company_id())
        ))
    if not job:
        flash('Relatório não encontrado.', 'danger')
        return redirect(url_for('dashboard'))
    if job.get('status') == 'pronto' and job.get('arquivo_url'):
        return redirect(job['arquivo_url'])
    tipo_raw = str(job.get('tipo') or '').replace('iris_', '').title()
    ref = str(job.get('mes') or '')
    sub = ref.split('|')[0] if '|' in ref else ref
    return _render_iris_job_wait_page(job_id, f'Relatório {tipo_raw}', sub)





def register_routes(app):
    rules = [
        ('/api/boleto/parse-vencimento', 'api_boleto_parse_vencimento', api_boleto_parse_vencimento, ['POST']),
        ('/iris/relatorio/<int:job_id>', 'iris_relatorio_wait', iris_relatorio_wait, ['GET']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
