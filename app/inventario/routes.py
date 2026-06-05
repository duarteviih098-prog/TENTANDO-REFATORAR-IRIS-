"""Rotas /inventario/* e API de inventário."""
import json

from flask import flash, jsonify, redirect, render_template, request, url_for

from app.auth.decorators import require_permission
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_now, parse_num
from app.shared.queries import safe_int_id as _safe_int_id
from app.shared.rows import row_get_value, row_to_dict


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def get_current_user():
    from app.auth import get_current_user as fn
    return fn()


def company_where(table, prefix=' WHERE '):
    from app.auth import company_where as fn
    return fn(table, prefix)


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)


def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)


def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)


def ensure_db():
    from app.db.migrations import ensure_db as fn
    return fn()
@require_permission('view_inventario')
def inventario_page():
    return redirect(url_for('inventario_hub'))



@require_permission('view_inventario')
def inventario_hub():
    ensure_db()
    where_sql, params = company_where('inventario_itens')
    rows = [row_to_dict(r) for r in query_all(f'SELECT * FROM inventario_itens{where_sql} ORDER BY nome', tuple(params))]
    empresa_id = current_company_id()
    pedidos = [row_to_dict(r) for r in query_all(
        """SELECT p.*, i.nome as item_nome, i.unidade
           FROM inventario_pedidos p
           LEFT JOIN inventario_itens i ON i.id=p.item_id
           WHERE p.empresa_id=? AND COALESCE(p.status,'pendente')='pendente'
           ORDER BY p.id DESC""",
        (empresa_id,)
    )]
    total_itens = len(rows)
    valor_total = sum(parse_num(r.get('valor_unitario',0)) * parse_num(r.get('quantidade',0)) for r in rows)
    n_baixo = sum(1 for r in rows if parse_num(r.get('quantidade',0)) <= parse_num(r.get('quantidade_minima',0)) > 0)
    n_zerado = sum(1 for r in rows if parse_num(r.get('quantidade',0)) <= 0)
    return render_template('inventario_hub.html',
        rows=rows, pedidos=pedidos,
        total_itens=total_itens, valor_total=valor_total,
        n_baixo=n_baixo, n_zerado=n_zerado, n_pedidos=len(pedidos)
    )



@require_permission('view_inventario')
def inventario_itens():
    ensure_db()
    where_sql, params = company_where('inventario_itens')
    q = request.args.get('q', '').strip()
    categoria = request.args.get('categoria', '').strip()
    rows = [row_to_dict(r) for r in query_all(f'SELECT * FROM inventario_itens{where_sql} ORDER BY nome', tuple(params))]
    categorias = sorted(set(r.get('categoria','') for r in rows if r.get('categoria')))
    if q:
        rows = [r for r in rows if q.lower() in (r.get('nome','') + r.get('categoria','') + r.get('fornecedor','')).lower()]
    if categoria:
        rows = [r for r in rows if r.get('categoria','') == categoria]
    empresa_id = current_company_id()
    where_mov, params_mov = company_where('inventario_movimentos')
    movimentos = [row_to_dict(r) for r in query_all(
        f'SELECT m.*, i.nome as item_nome, i.unidade FROM inventario_movimentos m LEFT JOIN inventario_itens i ON i.id=m.item_id{where_mov} ORDER BY m.id DESC LIMIT 100',
        tuple(params_mov)
    )]
    pedidos = [row_to_dict(r) for r in query_all(
        "SELECT p.*, i.nome as item_nome FROM inventario_pedidos p LEFT JOIN inventario_itens i ON i.id=p.item_id WHERE p.empresa_id=? AND COALESCE(p.status,'pendente')='pendente' ORDER BY p.id DESC",
        (empresa_id,)
    )]
    itens_todos = [row_to_dict(r) for r in query_all(f'SELECT id, nome, unidade FROM inventario_itens{where_sql} ORDER BY nome', tuple(params))]
    total_itens = len(rows)
    valor_total = sum(parse_num(r.get('valor_unitario',0)) * parse_num(r.get('quantidade',0)) for r in rows)
    return render_template('inventario.html',
        rows=rows, movimentos=movimentos, pedidos=pedidos,
        itens_todos=itens_todos, categorias=categorias,
        total_itens=total_itens, valor_total=valor_total,
        q=q, categoria=categoria
    )



@require_permission('view_inventario')
def inventario_pedidos_page():
    ensure_db()
    empresa_id = current_company_id()
    pedidos = [row_to_dict(r) for r in query_all(
        """SELECT p.*, i.nome as item_nome, i.unidade, i.fornecedor as item_fornecedor
           FROM inventario_pedidos p
           LEFT JOIN inventario_itens i ON i.id=p.item_id
           WHERE p.empresa_id=?
           ORDER BY p.id DESC LIMIT 200""",
        (empresa_id,)
    )]
    where_sql, params = company_where('inventario_itens')
    itens_todos = [row_to_dict(r) for r in query_all(f'SELECT id, nome, unidade, fornecedor FROM inventario_itens{where_sql} ORDER BY nome', tuple(params))]
    return render_template('inventario_pedidos.html', pedidos=pedidos, itens_todos=itens_todos)



@require_permission('view_inventario')
def inventario_movimentacoes():
    ensure_db()
    where_mov, params_mov = company_where('inventario_movimentos')
    movimentos = [row_to_dict(r) for r in query_all(
        f'SELECT m.*, i.nome as item_nome, i.unidade, i.categoria FROM inventario_movimentos m LEFT JOIN inventario_itens i ON i.id=m.item_id{where_mov} ORDER BY m.id DESC LIMIT 500',
        tuple(params_mov)
    )]
    return render_template('inventario_movimentacoes.html', movimentos=movimentos)






@require_permission('edit_inventario')
def inventario_save():
    ensure_db()
    rid = int(request.form.get('id') or 0)
    nome = (request.form.get('nome') or '').strip()
    if not nome:
        flash('Informe o nome do item.', 'danger')
        return redirect(url_for('inventario_page'))
    payload = {
        'empresa_id': current_company_id(),
        'nome': nome,
        'categoria': (request.form.get('categoria') or '').strip(),
        'unidade': (request.form.get('unidade') or 'un').strip(),
        'quantidade': parse_num(request.form.get('quantidade') or 0),
        'valor_unitario': (request.form.get('valor_unitario') or '').strip(),
        'fornecedor': (request.form.get('fornecedor') or '').strip(),
        'localizacao': (request.form.get('localizacao') or '').strip(),
        'observacoes': (request.form.get('observacoes') or '').strip(),
        'anexos_json': '[]',
    }
    if rid:
        sets = ', '.join([f'{k}=?' for k in payload if k != 'empresa_id'])
        vals = [payload[k] for k in payload if k != 'empresa_id']
        execute(f'UPDATE inventario_itens SET {sets} WHERE id=? AND empresa_id=?',
                tuple(vals) + (rid, current_company_id()))
        flash('Item atualizado.', 'success')
    else:
        payload['criado_em'] = br_now().strftime('%d/%m/%Y %H:%M')
        cols = ', '.join(payload.keys())
        vals2 = ', '.join(['?' for _ in payload])
        execute(f'INSERT INTO inventario_itens ({cols}) VALUES ({vals2})', tuple(payload.values()))
        flash('Item cadastrado.', 'success')
    clear_view_cache()
    return redirect(url_for('inventario_page'))




@require_permission('delete_inventario')
def inventario_delete_bulk():
    ensure_db()
    data = request.get_json(silent=True) or {}
    ids = [int(i) for i in (data.get('ids') or []) if str(i).isdigit()]
    for rid in ids:
        execute('DELETE FROM inventario_itens WHERE id=? AND empresa_id=?', (rid, current_company_id()))
        execute('DELETE FROM inventario_movimentos WHERE item_id=? AND empresa_id=?', (rid, current_company_id()))
        execute('DELETE FROM inventario_pedidos WHERE item_id=? AND empresa_id=?', (rid, current_company_id()))
    clear_view_cache()
    return jsonify({'ok': True})




@require_permission('view_inventario')
def api_inventario_get(rid):
    ensure_db()
    row = row_to_dict(query_one('SELECT * FROM inventario_itens WHERE id=? AND empresa_id=?', (rid, current_company_id()))) or {}
    if not row:
        return jsonify({'error': 'não encontrado'}), 404
    row['anexos'] = json.loads(row.get('anexos_json') or '[]')
    return jsonify(row)




@require_permission('edit_inventario')
def inventario_movimento():
    ensure_db()
    item_id = int(request.form.get('item_id') or 0)
    tipo = (request.form.get('tipo') or '').strip()
    quantidade = parse_num(request.form.get('quantidade') or 0)
    motivo = (request.form.get('motivo') or '').strip()
    if not item_id or not tipo or quantidade <= 0:
        flash('Preencha todos os campos.', 'danger')
        return redirect(url_for('inventario_page'))
    item = row_to_dict(query_one('SELECT * FROM inventario_itens WHERE id=? AND empresa_id=?', (item_id, current_company_id()))) or {}
    if not item:
        flash('Item não encontrado.', 'danger')
        return redirect(url_for('inventario_page'))
    qtd_atual = parse_num(item.get('quantidade', 0))
    nova_qtd = qtd_atual + quantidade if tipo == 'entrada' else max(0, qtd_atual - quantidade)
    execute('UPDATE inventario_itens SET quantidade=? WHERE id=? AND empresa_id=?', (nova_qtd, item_id, current_company_id()))
    user = get_current_user()
    execute('INSERT INTO inventario_movimentos (empresa_id, item_id, tipo, quantidade, motivo, usuario, quando) VALUES (?,?,?,?,?,?,?)',
            (current_company_id(), item_id, tipo, quantidade, motivo,
             user.get('nome') or user.get('email') or '', br_now().strftime('%d/%m/%Y %H:%M')))
    flash(f'{"Entrada" if tipo == "entrada" else "Saída"} registrada com sucesso.', 'success')
    clear_view_cache()
    return redirect(url_for('inventario_page'))





@require_permission('edit_inventario')
def inventario_pedido_save():
    ensure_db()
    item_id = _safe_int_id(request.form.get('item_id') or 0)
    item_nome_novo = (request.form.get('item_nome_novo') or '').strip()
    quantidade = parse_num(request.form.get('quantidade') or 0)

    if quantidade <= 0:
        flash('Informe a quantidade.', 'danger')
        return redirect(url_for('inventario_page'))

    # Se não selecionou item existente mas digitou nome novo — cria o item
    if not item_id and item_nome_novo:
        unidade = (request.form.get('unidade_nova') or 'un').strip()
        item_id = execute(
            'INSERT INTO inventario_itens (empresa_id, nome, unidade, quantidade, minimo, fornecedor) VALUES (?,?,?,0,0,?)',
            (current_company_id(), item_nome_novo, unidade,
             (request.form.get('fornecedor') or '').strip())
        )
        if not item_id:
            row = query_one('SELECT id FROM inventario_itens WHERE empresa_id=? AND nome=? ORDER BY id DESC LIMIT 1',
                           (current_company_id(), item_nome_novo))
            item_id = row_get_value(row, 'id') if row else None
        if item_id:
            flash(f'Item "{item_nome_novo}" criado e pedido registrado.', 'success')

    if not item_id:
        flash('Selecione um item ou informe o nome do novo item.', 'danger')
        return redirect(url_for('inventario_page'))

    user = get_current_user()
    execute('INSERT INTO inventario_pedidos (empresa_id, item_id, quantidade, fornecedor, observacoes, solicitado_por, solicitado_em, status) VALUES (?,?,?,?,?,?,?,?)',
            (current_company_id(), item_id, quantidade,
             (request.form.get('fornecedor') or '').strip(),
             (request.form.get('observacoes') or '').strip(),
             user.get('nome') or user.get('email') or '',
             br_now().strftime('%d/%m/%Y %H:%M'), 'pendente'))
    if item_nome_novo:
        pass  # já flashou acima
    else:
        flash('Pedido registrado. Confirme o recebimento quando o item chegar.', 'success')
    clear_view_cache()
    return redirect(url_for('inventario_page'))




@require_permission('edit_inventario')
def inventario_mover_para_pedido():
    ensure_db()
    ids = request.form.getlist('item_ids')
    if not ids:
        flash('Selecione ao menos um item.', 'danger')
        return redirect(url_for('inventario_page'))
    user = get_current_user()
    movidos = 0
    for item_id in ids:
        try:
            item_id = int(item_id)
        except Exception:
            continue
        item = row_to_dict(query_one('SELECT * FROM inventario_itens WHERE id=? AND empresa_id=?', (item_id, current_company_id()))) or {}
        if not item:
            continue
        qtd = parse_num(item.get('quantidade', 0))
        # Cria pedido pendente com a quantidade atual
        execute('INSERT INTO inventario_pedidos (empresa_id, item_id, quantidade, fornecedor, observacoes, solicitado_por, solicitado_em, status) VALUES (?,?,?,?,?,?,?,?)',
                (current_company_id(), item_id, qtd if qtd > 0 else 1,
                 item.get('fornecedor') or '',
                 'Migrado do estoque — aguardando confirmação de recebimento',
                 user.get('nome') or user.get('email') or '',
                 br_now().strftime('%d/%m/%Y %H:%M'), 'pendente'))
        # Zera quantidade no estoque
        execute('UPDATE inventario_itens SET quantidade=0 WHERE id=? AND empresa_id=?', (item_id, current_company_id()))
        movidos += 1
    clear_view_cache()
    flash(f'{movidos} item(s) movido(s) para "Aguardando recebimento". Confirme quando chegarem.', 'success')
    return redirect(url_for('inventario_page'))




@require_permission('edit_inventario')
def inventario_pedido_receber_lote():
    ensure_db()
    pids = request.form.getlist('pedido_ids')
    if not pids:
        flash('Selecione ao menos um pedido.', 'danger')
        return redirect(url_for('inventario_page'))
    user = get_current_user()
    recebidos = 0
    for pid in pids:
        try:
            pid = int(pid)
        except Exception:
            continue
        pedido = row_to_dict(query_one('SELECT * FROM inventario_pedidos WHERE id=? AND empresa_id=?', (pid, current_company_id()))) or {}
        status = (pedido.get('status') or 'pendente')
        if not pedido or status not in ('pendente', ''):
            continue
        quantidade = parse_num(pedido.get('quantidade') or 0)
        item_id = int(pedido.get('item_id') or 0)
        item = row_to_dict(query_one('SELECT * FROM inventario_itens WHERE id=? AND empresa_id=?', (item_id, current_company_id()))) or {}
        if item:
            nova_qtd = parse_num(item.get('quantidade', 0)) + quantidade
            execute('UPDATE inventario_itens SET quantidade=? WHERE id=? AND empresa_id=?', (nova_qtd, item_id, current_company_id()))
        execute('INSERT INTO inventario_movimentos (empresa_id, item_id, tipo, quantidade, motivo, destino, usuario, quando) VALUES (?,?,?,?,?,?,?,?)',
                (current_company_id(), item_id, 'entrada', quantidade,
                 f'Recebimento em lote — pedido #{pid}', '',
                 user.get('nome') or user.get('email') or '',
                 br_now().strftime('%d/%m/%Y %H:%M')))
        execute("UPDATE inventario_pedidos SET status='recebido' WHERE id=? AND empresa_id=?", (pid, current_company_id()))
        recebidos += 1
    clear_view_cache()
    flash(f'{recebidos} pedido(s) recebido(s) e adicionado(s) ao estoque.', 'success')
    return redirect(url_for('inventario_page'))




@require_permission('edit_inventario')
def inventario_retirada():
    ensure_db()
    item_id = int(request.form.get('item_id') or 0)
    quantidade = parse_num(request.form.get('quantidade') or 0)
    destino = (request.form.get('destino') or '').strip()
    os_id = request.form.get('os_id') or ''
    motivo = (request.form.get('motivo') or '').strip()
    if not item_id or quantidade <= 0:
        flash('Informe o item e a quantidade.', 'danger')
        return redirect(url_for('inventario_page'))
    item = row_to_dict(query_one('SELECT * FROM inventario_itens WHERE id=? AND empresa_id=?', (item_id, current_company_id()))) or {}
    if not item:
        flash('Item não encontrado.', 'danger')
        return redirect(url_for('inventario_page'))
    nova_qtd = max(0, parse_num(item.get('quantidade', 0)) - quantidade)
    execute('UPDATE inventario_itens SET quantidade=? WHERE id=? AND empresa_id=?', (nova_qtd, item_id, current_company_id()))
    user = get_current_user()
    motivo_full = motivo or destino or 'Retirada'
    if os_id:
        motivo_full = f'O.S. #{os_id} — {motivo_full}'
    execute('INSERT INTO inventario_movimentos (empresa_id, item_id, tipo, quantidade, motivo, destino, os_id, usuario, quando) VALUES (?,?,?,?,?,?,?,?,?)',
            (current_company_id(), item_id, 'saida', quantidade, motivo_full, destino, os_id,
             user.get('nome') or user.get('email') or '',
             br_now().strftime('%d/%m/%Y %H:%M')))
    flash(f'Retirada de {int(quantidade)} unidade(s) registrada.', 'success')
    clear_view_cache()
    return redirect(url_for('inventario_page'))




@require_permission('edit_inventario')
def inventario_pedido_receber(pid):
    ensure_db()
    pedido = row_to_dict(query_one('SELECT * FROM inventario_pedidos WHERE id=? AND empresa_id=?', (pid, current_company_id()))) or {}
    if not pedido:
        flash('Pedido não encontrado.', 'danger')
        return redirect(url_for('inventario_page'))
    quantidade = parse_num(request.form.get('quantidade') or pedido.get('quantidade') or 0)
    item_id = int(pedido.get('item_id') or 0)
    item = row_to_dict(query_one('SELECT * FROM inventario_itens WHERE id=? AND empresa_id=?', (item_id, current_company_id()))) or {}
    if item:
        nova_qtd = parse_num(item.get('quantidade', 0)) + quantidade
        execute('UPDATE inventario_itens SET quantidade=? WHERE id=? AND empresa_id=?', (nova_qtd, item_id, current_company_id()))
    user = get_current_user()
    execute('INSERT INTO inventario_movimentos (empresa_id, item_id, tipo, quantidade, motivo, usuario, quando) VALUES (?,?,?,?,?,?,?)',
            (current_company_id(), item_id, 'entrada', quantidade,
             f'Recebimento de pedido #{pid}',
             user.get('nome') or user.get('email') or '',
             br_now().strftime('%d/%m/%Y %H:%M')))
    execute("UPDATE inventario_pedidos SET status='recebido' WHERE id=? AND empresa_id=?", (pid, current_company_id()))
    flash(f'Recebimento confirmado! {int(quantidade)} unidade(s) adicionadas ao estoque.', 'success')
    clear_view_cache()
    return redirect(url_for('inventario_page'))




@require_permission('edit_inventario')
def inventario_pedido_cancelar(pid):
    ensure_db()
    execute("UPDATE inventario_pedidos SET status='cancelado' WHERE id=? AND empresa_id=?", (pid, current_company_id()))
    flash('Pedido cancelado.', 'success')
    clear_view_cache()
    return redirect(url_for('inventario_page'))





def register_routes(app):
    rules = [
        ('/inventario', 'inventario_page', inventario_page, ['GET']),
        ('/inventario/hub', 'inventario_hub', inventario_hub, ['GET']),
        ('/inventario/itens', 'inventario_itens', inventario_itens, ['GET']),
        ('/inventario/pedidos', 'inventario_pedidos_page', inventario_pedidos_page, ['GET']),
        ('/inventario/movimentacoes', 'inventario_movimentacoes', inventario_movimentacoes, ['GET']),
        ('/inventario/save', 'inventario_save', inventario_save, ['POST']),
        ('/inventario/delete', 'inventario_delete_bulk', inventario_delete_bulk, ['POST']),
        ('/api/inventario/<int:rid>', 'api_inventario_get', api_inventario_get, ['GET']),
        ('/inventario/movimento', 'inventario_movimento', inventario_movimento, ['POST']),
        ('/inventario/pedido/save', 'inventario_pedido_save', inventario_pedido_save, ['POST']),
        ('/inventario/mover-para-pedido', 'inventario_mover_para_pedido', inventario_mover_para_pedido, ['POST']),
        ('/inventario/pedido/receber-lote', 'inventario_pedido_receber_lote', inventario_pedido_receber_lote, ['POST']),
        ('/inventario/retirada', 'inventario_retirada', inventario_retirada, ['POST']),
        ('/inventario/pedido/receber/<int:pid>', 'inventario_pedido_receber', inventario_pedido_receber, ['POST']),
        ('/inventario/pedido/cancelar/<int:pid>', 'inventario_pedido_cancelar', inventario_pedido_cancelar, ['POST']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
