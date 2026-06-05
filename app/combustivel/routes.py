"""Rotas /combustivel/*."""
from flask import flash, jsonify, redirect, render_template, request, send_file, url_for

from app.auth.decorators import require_permission
from app.combustivel.services import (
    combustivel_duplicado,
    ensure_combustivel_valid_ids,
    get_comb_vinculos,
    import_combustivel_excel,
    save_combustivel,
)
from app.os.pdf import excel_file, table_pdf
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_money, now_str, parse_num
from app.shared.months import filter_rows_by_month, month_or_current
from app.shared.queries import list_page
from app.shared.queries import safe_int_id as _safe_int_id
from app.shared.rows import row_get_value, row_to_dict


def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)


def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


@require_permission('view_combustivel')
def combustivel():
    ensure_combustivel_valid_ids()
    todos = str(request.args.get('todos') or '').strip().lower() in ('1', 'true', 'sim', 'yes', 'on')
    mes_informado = (request.args.get('mes') or '').strip()
    filtro_mes = '' if todos else month_or_current(mes_informado)
    rows = list_page('combustivel')
    if not todos:
        rows = filter_rows_by_month(rows, filtro_mes, month_fields=('mes_ref',), date_fields=('data',))
    total = sum(parse_num(row_get_value(r, 'custo', 0)) for r in rows)
    empresa_id = current_company_id()
    comb_vinculos = get_comb_vinculos(empresa_id)
    return render_template(
        'combustivel.html',
        rows=rows,
        total=total,
        filtro_mes=filtro_mes,
        todos=todos,
        comb_vinculos=comb_vinculos,
    )


@require_permission('edit_combustivel')
def combustivel_veiculos_page():
    empresa_id = current_company_id()
    if request.method == 'POST':
        acao = request.form.get('acao') or 'salvar'
        if acao == 'excluir':
            rid = _safe_int_id(request.form.get('id'))
            if rid:
                execute('UPDATE combustivel_veiculos SET ativo=0 WHERE id=? AND empresa_id=?', (rid, empresa_id))
                flash('Veículo removido.', 'success')
        else:
            rid = _safe_int_id(request.form.get('id'))
            motorista = (request.form.get('motorista') or '').strip()
            modelo = (request.form.get('modelo') or '').strip()
            placa = (request.form.get('placa') or '').strip()
            if not motorista:
                flash('Motorista é obrigatório.', 'danger')
            elif rid:
                execute(
                    'UPDATE combustivel_veiculos SET motorista=?, modelo=?, placa=? WHERE id=? AND empresa_id=?',
                    (motorista, modelo, placa, rid, empresa_id),
                )
                flash('Veículo atualizado.', 'success')
            else:
                execute(
                    'INSERT INTO combustivel_veiculos (empresa_id, motorista, modelo, placa, ativo, criado_em) VALUES (?,?,?,?,1,?)',
                    (empresa_id, motorista, modelo, placa, now_str()),
                )
                flash('Veículo cadastrado.', 'success')
        return redirect(url_for('combustivel_veiculos_page'))

    veiculos = get_comb_vinculos(empresa_id)
    try:
        veiculos_db = [row_to_dict(r) for r in query_all(
            'SELECT * FROM combustivel_veiculos WHERE empresa_id=? AND ativo=1 ORDER BY motorista', (empresa_id,)
        )]
    except Exception:
        veiculos_db = []
    return render_template(
        'combustivel.html',
        rows=list_page('combustivel'),
        total=0,
        filtro_mes=month_or_current(''),
        todos=False,
        comb_vinculos=veiculos,
        veiculos_db=veiculos_db,
        aba='veiculos',
    )


@require_permission('edit_combustivel')
def combustivel_save():
    rid = request.form.get('id') or None
    forcar_duplicado = str(request.form.get('forcar_duplicado') or '').strip().lower() in ('1', 'true', 'sim', 'yes', 'on')
    ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    duplicado = combustivel_duplicado(request.form, rid)
    if duplicado and not forcar_duplicado:
        msg = 'Esse lançamento de combustível já existe no sistema. Deseja salvar mesmo assim?'
        if ajax:
            return jsonify({'ok': False, 'duplicado': True, 'message': msg})
        flash('⚠️ ' + msg, 'warning')
        return redirect(url_for('combustivel'))
    try:
        save_combustivel(request.form, rid)
    except ValueError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('combustivel'))
    clear_view_cache()
    flash('Lançamento de combustível salvo.', 'success')
    mes_salvo = month_or_current(request.form.get('mes_ref') or '')
    if ajax:
        return jsonify({'ok': True, 'redirect': url_for('combustivel', mes=mes_salvo)})
    return redirect(url_for('combustivel', mes=mes_salvo))


@require_permission('edit_combustivel')
def combustivel_import():
    file = request.files.get('arquivo_excel')
    if not file or not file.filename:
        flash('Selecione um arquivo Excel para importar combustível.', 'warning')
        return redirect(url_for('combustivel'))
    try:
        qtd = import_combustivel_excel(file)
        clear_view_cache()
        flash(f'Importação de combustível concluída: {qtd} linha(s).', 'success')
    except Exception as exc:
        flash(f'Erro ao importar combustível: {exc}', 'danger')
    return redirect(url_for('combustivel'))


@require_permission('generate_pdf')
def combustivel_pdf():
    rows = list_page('combustivel')
    headers = ['Data', 'Mês', 'Modelo', 'Placa', 'Motorista', 'KM', 'Custo']
    data = [(r['data'], r['mes_ref'], r['modelo_veiculo'], r['placa'], r['motorista'], r['km'], br_money(r['custo'])) for r in rows]
    return send_file(table_pdf('Combustível', headers, data), mimetype='application/pdf', as_attachment=True, download_name='combustivel.pdf')


@require_permission('generate_excel')
def combustivel_excel():
    rows = list_page('combustivel')
    headers = ['Data', 'Mês', 'Modelo', 'Placa', 'Motorista', 'KM', 'Custo', 'Observações']
    data = [(r['data'], r['mes_ref'], r['modelo_veiculo'], r['placa'], r['motorista'], r['km'], parse_num(r['custo']), r['observacoes']) for r in rows]
    return send_file(
        excel_file('Combustivel', headers, data),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='combustivel.xlsx',
    )


def register_routes(app):
    rules = [
        ('/combustivel', 'combustivel', combustivel, ['GET']),
        ('/combustivel/veiculos', 'combustivel_veiculos_page', combustivel_veiculos_page, ['GET', 'POST']),
        ('/combustivel/save', 'combustivel_save', combustivel_save, ['POST']),
        ('/combustivel/import', 'combustivel_import', combustivel_import, ['POST']),
        ('/combustivel/pdf', 'combustivel_pdf', combustivel_pdf, ['GET']),
        ('/combustivel/excel', 'combustivel_excel', combustivel_excel, ['GET']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
