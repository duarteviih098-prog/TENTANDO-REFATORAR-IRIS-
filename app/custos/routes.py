"""Rotas /custos/*."""
from flask import flash, redirect, render_template, request, url_for
from app.shared.cache import clear_view_cache
from app.shared.months import filter_rows_by_month, month_or_current
from app.shared.queries import list_page
from app.storage import backup_company_data

from app.auth.decorators import require_permission
from app.custos.services import ensure_custos_valid_ids, import_custos_excel, save_custo


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


@require_permission('view_custos')
def custos():
    ensure_custos_valid_ids()
    todos = str(request.args.get('todos') or '').strip().lower() in ('1', 'true', 'sim', 'yes', 'on')
    mes_informado = (request.args.get('mes') or '').strip()
    filtro_mes = '' if todos else month_or_current(mes_informado)
    rows = list_page('custos')
    if not todos:
        rows = filter_rows_by_month(rows, filtro_mes, month_fields=('mes',))
    return render_template('custos.html', rows=rows, filtro_mes=filtro_mes, todos=todos)


@require_permission('edit_custos')
def custos_save():
    rid = request.form.get('id') or None
    save_custo(request.form, rid)
    backup_company_data(current_company_id())
    clear_view_cache()
    mes_salvo = month_or_current(request.form.get('mes') or '')
    flash('Custo salvo.', 'success')
    return redirect(url_for('custos', mes=mes_salvo))


@require_permission('edit_custos')
def custos_import():
    file = request.files.get('arquivo_excel')
    if not file or not file.filename:
        flash('Selecione um arquivo Excel para importar custos.', 'warning')
        return redirect(url_for('custos'))
    try:
        qtd = import_custos_excel(file)
        clear_view_cache()
        flash(f'Importação de custos concluída: {qtd} linha(s).', 'success')
    except Exception as exc:
        flash(f'Erro ao importar custos: {exc}', 'danger')
    return redirect(url_for('custos'))


def register_routes(app):
    rules = [
        ('/custos', 'custos', custos, ['GET']),
        ('/custos/save', 'custos_save', custos_save, ['POST']),
        ('/custos/import', 'custos_import', custos_import, ['POST']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
