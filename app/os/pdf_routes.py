"""Rotas HTTP do PDF de O.S."""
from datetime import datetime

from flask import flash, jsonify, redirect, request, send_file, url_for

from app.auth.decorators import require_permission
from app.os.pdf_builder import _build_os_pdf, _build_os_pdf_mes_buffer
from app.os.pdf_common import (
    PDF_MAX_IMAGES_PER_OS,
    _flask_app,
    company_where,
    current_company_id,
    current_user_is_super_admin,
    query_all,
    query_one,
    select_existing_columns,
)
from app.os.pdf_jobs import (
    _create_pdf_job,
    _render_pdf_job_wait_page,
    _start_pdf_job_thread,
)
from app.os.pdf_support import _pdf_cache_get, _pdf_cache_set
from app.os.services import attach_os_display_numbers
from app.shared.formatters import parse_br_date
from app.shared.rows import row_get_value, row_to_dict
from app.storage import sync_os_attachments


def os_pdf_dia():
    data = (request.args.get('data') or '').strip()
    if not data:
        flash('Informe a data para gerar o relatório.', 'warning')
        return redirect(url_for('os_page'))

    cache_key = f"pdf:dia:{current_company_id()}:{data}:imgs{PDF_MAX_IMAGES_PER_OS}"
    cached = _pdf_cache_get(cache_key)
    if cached:
        return send_file(cached, mimetype='application/pdf', as_attachment=False, download_name=f'rdo_dia_{data.replace("/", "-")}.pdf')

    def _row_date_key(r):
        data_txt = row_get_value(r, 'data', '')
        rid = int(row_get_value(r, 'id', 0) or 0)
        return (parse_br_date(str(data_txt or '')) or datetime.min, rid)

    os_pdf_cols = select_existing_columns('os_ordens', [
        'id','data','sistema','equipamento','ativo_nome','status','finalizada','criticidade','responsavel',
        'data_inicio','data_fim','descricao','servico_executado','imagens','teve_terceiro','quem_foi_terceiro',
        'historico_pausas','motivo_pausa','acumulado_minutos','empresa_id'
    ])
    where_sql, params = company_where('os_ordens')
    params = list(params)
    where_sql += (' AND ' if where_sql else ' WHERE ')
    where_sql += 'data=?'
    params.append(data)

    rows_raw = query_all(f'SELECT {os_pdf_cols} FROM os_ordens{where_sql} ORDER BY id ASC LIMIT 200', tuple(params))
    rows = sorted([sync_os_attachments(row_to_dict(r), persist_db=False) for r in rows_raw], key=_row_date_key)
    rows = attach_os_display_numbers(rows)
    if not rows:
        flash('Nenhuma O.S. encontrada para a data informada.', 'warning')
        return redirect(url_for('os_page'))

    pdf = _build_os_pdf(rows, subtitulo=f'Dia: {data}')
    pdf = _pdf_cache_set(cache_key, pdf)
    return send_file(pdf, mimetype='application/pdf', as_attachment=False, download_name=f'rdo_dia_{data.replace("/", "-")}.pdf')



def os_pdf_mes_sync():
    """Fallback manual: gera PDF mensal na requisição atual.

    Use só para teste/local. No Render, prefira /os/pdf/mes em background.
    """
    mes = (request.args.get('mes') or '').strip()
    if not mes:
        flash('Informe o mês para gerar o relatório.', 'warning')
        return redirect(url_for('os_page'))
    try:
        pdf, mes_norm = _build_os_pdf_mes_buffer(mes, include_all_images=True, use_cache=False)
        return send_file(
            pdf,
            mimetype='application/pdf',
            as_attachment=False,
            download_name=f"rdo_mes_{str(mes_norm).replace('/', '-')}.pdf"
        )
    except Exception as exc:
        _flask_app().logger.exception('Falha ao gerar PDF mensal síncrono de O.S.')
        flash(f'Não foi possível gerar o PDF mensal: {exc}', 'danger')
        return redirect(url_for('os_page'))




def os_pdf_job_status(job_id):
    """Consulta status do PDF em background."""
    if current_user_is_super_admin():
        job = row_to_dict(query_one('SELECT id, status, arquivo_url, storage_path, erro, mes FROM pdf_jobs WHERE id=?', (job_id,)))
    else:
        job = row_to_dict(query_one(
            'SELECT id, status, arquivo_url, storage_path, erro, mes FROM pdf_jobs WHERE id=? AND empresa_id=?',
            (job_id, current_company_id())
        ))
    if not job:
        return jsonify({'status': 'erro', 'erro': 'Job não encontrado.'}), 404
    return jsonify(job)




def os_pdf_mes_job():
    """Endpoint JSON para botão/ajax criar PDF mensal em background."""
    mes = (request.form.get('mes') or request.args.get('mes') or '').strip()
    if not mes and request.is_json:
        payload = request.get_json(silent=True) or {}
        mes = str(payload.get('mes') or '').strip()
    if not mes:
        return jsonify({'ok': False, 'error': 'Informe o mês.'}), 400
    try:
        job_id, mes_norm = _create_pdf_job('mensal_os', mes)
        _start_pdf_job_thread(job_id)
        return jsonify({'ok': True, 'job_id': job_id, 'mes': mes_norm})
    except Exception as exc:
        _flask_app().logger.exception('Falha ao iniciar job JSON de PDF mensal.')
        return jsonify({'ok': False, 'error': str(exc)}), 500




def os_pdf_mes():
    """Cria tarefa em background para PDF mensal e mostra tela de acompanhamento."""
    mes = (request.args.get('mes') or '').strip()
    if not mes:
        flash('Informe o mês para gerar o relatório.', 'warning')
        return redirect(url_for('os_page'))

    try:
        job_id, mes_norm = _create_pdf_job('mensal_os', mes)
        _start_pdf_job_thread(job_id)
        return _render_pdf_job_wait_page(job_id, mes_norm)
    except Exception as exc:
        _flask_app().logger.exception('Falha ao iniciar job de PDF mensal de O.S.')
        flash(f'Não foi possível iniciar o PDF mensal: {exc}', 'danger')
        return redirect(url_for('os_page'))






def register_pdf_routes(app):
    rules = [
        ('/os/pdf/dia', 'os_pdf_dia', os_pdf_dia, ['GET']),
        ('/os/pdf/mes', 'os_pdf_mes', os_pdf_mes, ['GET']),
        ('/os/pdf/mes/job', 'os_pdf_mes_job', os_pdf_mes_job, ['POST']),
        ('/os/pdf/job/<int:job_id>/status', 'os_pdf_job_status', os_pdf_job_status, ['GET']),
        ('/os/pdf/mes/sync', 'os_pdf_mes_sync', os_pdf_mes_sync, ['GET']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, require_permission('generate_pdf')(view), methods=methods)
