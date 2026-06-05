"""Rotas /controle/* e exportação Excel."""
from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, send_file, url_for

from app.auth.decorators import require_permission
from app.controle.services import fetch_bombas_counts, import_controle_excel, save_bomba
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_now
from app.shared.rows import row_matches_month, row_to_dict
from app.storage.paths import BASE_DIR


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)

def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)

def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)

def current_company_id():
    from app.auth import current_company_id as fn
    return fn()

def company_where(table, prefix=' WHERE '):
    from app.auth import company_where as fn
    return fn(table, prefix)

def company_and(table):
    from app.auth import company_and as fn
    return fn(table)

@require_permission('view_controle')
def controle():
    return redirect(url_for('controle_hub'))

@require_permission('view_controle')
def controle_hub():
    counts = fetch_bombas_counts()
    where_sql, params = company_and('bombas')
    rows_db = query_all(f'SELECT * FROM bombas WHERE 1=1{where_sql} ORDER BY id DESC', tuple(params))
    total = len(rows_db)
    rows = [dict(r) for r in rows_db]
    where_l, params_l = company_and('bombas_locais')
    locais_db = query_all(f'SELECT * FROM bombas_locais WHERE 1=1{where_l} ORDER BY nome', tuple(params_l))
    return render_template('controle_hub.html', counts=counts, total=total, rows=rows, locais=[dict(r) for r in locais_db])

@require_permission('view_controle')
def controle_lista():
    return redirect(url_for('controle_hub'))

@require_permission('view_controle')
def controle_mapa():
    where_sql, params = company_and('bombas')
    rows_db = query_all(
        f'SELECT id, equipamento, modelo, marca, numero_serie, localizacao, destino_retirada, sistema, local_id FROM bombas WHERE 1=1{where_sql} ORDER BY id DESC',
        tuple(params)
    )
    # Locais cadastrados
    where_l, params_l = company_and('bombas_locais')
    locais_db = query_all(f'SELECT * FROM bombas_locais WHERE 1=1{where_l} ORDER BY nome', tuple(params_l))
    return render_template('controle_mapa.html',
        bombas=[dict(r) for r in rows_db],
        locais=[dict(r) for r in locais_db],
    )

@require_permission('view_controle')
def controle_localizacao():
    return redirect(url_for('controle_mapa'))

@require_permission('view_controle')
def controle_historico():
    return redirect(url_for('controle_hub'))

@require_permission('view_controle')
def controle_api_detail(rid):
    where_sql, params = company_and('bombas')
    row = row_to_dict(query_one(f'SELECT * FROM bombas WHERE id=?{where_sql}', tuple([rid]+list(params))))
    if not row:
        return jsonify({'ok': False, 'error': 'Não encontrado'}), 404
    # Buscar movimentações (tabela pode não existir ainda)
    try:
        movs = query_all('SELECT * FROM bombas_movimentacoes WHERE bomba_id=? ORDER BY id DESC LIMIT 20', (rid,))
        row['movimentacoes'] = [dict(m) for m in movs]
    except Exception:
        row['movimentacoes'] = []
    return jsonify(dict(row))

@require_permission('edit_controle')
def controle_movimentar():
    data = request.get_json() or {}
    bomba_id = data.get('bomba_id')
    acao = data.get('acao', '').strip()
    local_destino = data.get('local_destino', '').strip()
    motivo = data.get('motivo', '').strip()
    responsavel = data.get('responsavel', '').strip()
    if not bomba_id or not acao:
        return jsonify({'ok': False, 'error': 'Dados inválidos'}), 400
    empresa_id = current_company_id()
    agora = br_now().strftime('%d/%m/%Y %H:%M')
    # Mapeia ação para localização
    loc_map = {'estoque': 'estoque', 'conserto': 'conserto', 'instalar': 'retirada'}
    nova_loc = loc_map.get(acao, 'estoque')
    # Atualiza bomba
    execute('UPDATE bombas SET localizacao=?, destino_retirada=? WHERE id=? AND empresa_id=?',
            (nova_loc, local_destino if acao == 'instalar' else '', bomba_id, empresa_id))
    # Registra movimentação
    execute('''INSERT INTO bombas_movimentacoes
               (bomba_id, empresa_id, acao, local_destino, motivo, responsavel, data, criado_em)
               VALUES (?,?,?,?,?,?,?,?)''',
            (bomba_id, empresa_id, acao, local_destino, motivo, responsavel, agora, agora))
    clear_view_cache()
    return jsonify({'ok': True})

@require_permission('view_controle')
def controle_locais():
    empresa_id = current_company_id()
    if request.method == 'POST':
        data = request.get_json() or {}
        rid = data.get('id')
        nome = data.get('nome', '').strip()
        tipo = data.get('tipo', '').strip()
        lat = data.get('lat')
        lng = data.get('lng')
        endereco = data.get('endereco', '').strip()
        obs = data.get('observacoes', '').strip()
        agora = br_now().strftime('%d/%m/%Y %H:%M')
        if rid:
            execute('UPDATE bombas_locais SET nome=?,tipo=?,lat=?,lng=?,endereco=?,observacoes=? WHERE id=? AND empresa_id=?',
                    (nome, tipo, lat, lng, endereco, obs, rid, empresa_id))
        else:
            execute('INSERT INTO bombas_locais (empresa_id,nome,tipo,lat,lng,endereco,observacoes,criado_em) VALUES (?,?,?,?,?,?,?,?)',
                    (empresa_id, nome, tipo, lat, lng, endereco, obs, agora))
        return jsonify({'ok': True})
    where_sql, params = company_and('bombas_locais')
    locais = query_all(f'SELECT * FROM bombas_locais WHERE 1=1{where_sql} ORDER BY nome', tuple(params))
    return jsonify({'ok': True, 'locais': [dict(r) for r in locais]})

@require_permission('edit_controle')
def controle_locais_delete(rid):
    empresa_id = current_company_id()
    execute('DELETE FROM bombas_locais WHERE id=? AND empresa_id=?', (rid, empresa_id))
    return jsonify({'ok': True})

@require_permission('delete_controle')
def controle_delete():
    data = request.get_json() or {}
    rid = data.get('id')
    if not rid:
        return jsonify({'ok': False}), 400
    where_sql, params = company_and('bombas')
    execute(f'DELETE FROM bombas WHERE id=?{where_sql}', tuple([rid]+list(params)))
    clear_view_cache()
    return jsonify({'ok': True})


@require_permission('generate_excel')
def controle_excel():
    q = request.args.get('q','').strip()
    filtro_local = request.args.get('localizacao','').strip().lower()
    filtro_mes = request.args.get('mes','').strip()
    sql = 'SELECT * FROM bombas WHERE 1=1'
    params = []
    tenant_sql, tenant_params = company_and('bombas')
    sql += tenant_sql
    params.extend(tenant_params)
    if q:
        sql += ' AND (equipamento LIKE ? OR modelo LIKE ? OR fornecedor LIKE ? OR pedido_aberto LIKE ? OR observacoes LIKE ? OR obs LIKE ?)' 
        params.extend([f'%{q}%'] * 6)
    if filtro_local in ('estoque','conserto','retirada'):
        sql += ' AND localizacao=?'
        params.append(filtro_local)
    sql += ' ORDER BY id DESC'
    rows = [dict(r) for r in query_all(sql, tuple(params))]
    if filtro_mes:
        rows = [r for r in rows if row_matches_month(r.get('data_abertura'), r.get('previsao_entrega'), r.get('recebido_em'), month_ref=filtro_mes)]
    try:
        import pandas as pd
    except Exception:
        flash('Pandas/OpenPyXL não estão instalados para gerar Excel.', 'danger')
        return redirect(url_for('controle', q=q, localizacao=filtro_local, mes=filtro_mes))
    export_rows = []
    for r in rows:
        export_rows.append({
            'ID': r.get('id',''),
            'Equipamento': r.get('equipamento',''),
            'Modelo': r.get('modelo',''),
            'Fornecedor': r.get('fornecedor',''),
            'Valor': r.get('valor',''),
            'Pedido aberto': r.get('pedido_aberto',''),
            'Orçamento': r.get('orcamento',''),
            'Localização': r.get('localizacao',''),
            'Destino retirada': r.get('destino_retirada',''),
            'Previsão entrega': r.get('previsao_entrega') or r.get('data_estimada',''),
            'Recebido em': r.get('recebido_em') or r.get('data_entrega',''),
            'Status entrega': r.get('status_entrega',''),
            'Status': r.get('status',''),
            'Sistema': r.get('sistema',''),
            'OBS': r.get('obs') or r.get('observacoes',''),
        })
    if not export_rows:
        export_rows = [{'Sem dados': 'Nenhum registro encontrado para os filtros atuais.'}]
    df = pd.DataFrame(export_rows)
    out_path = BASE_DIR / 'static' / 'exports'
    out_path.mkdir(parents=True, exist_ok=True)
    filename = f"controle_bombas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    file_path = out_path / filename
    df.to_excel(file_path, index=False)
    return send_file(file_path, as_attachment=True, download_name=filename)


@require_permission('edit_controle')
def controle_save():
    rid = request.form.get('id') or None
    save_bomba(request.form, rid)
    clear_view_cache()
    flash('Registro salvo no controle de estoque de bombas.', 'success')
    destino = request.form.get('localizacao') or request.args.get('localizacao') or ''
    return redirect(url_for('controle', localizacao=destino))


def controle_import():
    file = request.files.get('arquivo_excel')
    if not file or not file.filename:
        flash('Selecione um arquivo Excel para importar estoque de bombas.', 'warning')
        return redirect(url_for('controle'))
    try:
        qtd = import_controle_excel(file)
        clear_view_cache()
        flash(f'Importação de estoque/conserto concluída: {qtd} linha(s).', 'success')
    except Exception as exc:
        flash(f'Erro ao importar estoque de bombas: {exc}', 'danger')
    return redirect(url_for('controle'))


def register_routes(app):
    rules = [
        ('/controle', 'controle', controle, ['GET']),
        ('/controle/hub', 'controle_hub', controle_hub, ['GET']),
        ('/controle/lista', 'controle_lista', controle_lista, ['GET']),
        ('/controle/mapa', 'controle_mapa', controle_mapa, ['GET']),
        ('/controle/localizacao', 'controle_localizacao', controle_localizacao, ['GET']),
        ('/controle/historico', 'controle_historico', controle_historico, ['GET']),
        ('/controle/api/<int:rid>', 'controle_api_detail', controle_api_detail, ['GET']),
        ('/controle/movimentar', 'controle_movimentar', controle_movimentar, ['POST']),
        ('/controle/locais', 'controle_locais', controle_locais, ['GET', 'POST']),
        ('/controle/locais/<int:rid>', 'controle_locais_delete', controle_locais_delete, ['DELETE']),
        ('/controle/delete', 'controle_delete', controle_delete, ['POST']),
        ('/controle_excel', 'controle_excel', controle_excel, ['GET']),
        ('/controle/save', 'controle_save', controle_save, ['POST']),
        ('/controle/import', 'controle_import', controle_import, ['POST']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
