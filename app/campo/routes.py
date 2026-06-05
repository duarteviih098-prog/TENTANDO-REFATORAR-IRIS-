"""Rotas Campo / PWA / gestor mobile."""
import hmac
import io
import json
import os
import re
import uuid
from datetime import datetime
from app.auth import owned_by_current_company, user_has
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_now, elapsed_label, format_phone_br, normalize_phone, now_str, only_time_str, parse_br_date, parse_num, time_diff_minutes
from app.shared.payments import payment_status_is_paid
from app.shared.queries import fetch_sistemas_map, list_page, safe_int_id as _safe_int_id
from app.shared.rows import row_get_value, row_to_dict
from app.storage import backup_company_data

from flask import flash, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from app.auth.decorators import require_permission
from app.campo.services import (
    _api_campo_guard,
    _campo_save_images,
    _campo_valid_files,
    _token_expirado,
    _token_renovar,
    _token_revogar,
    campo_evento_registrar,
    campo_link_com_tecnico,
    campo_link_publico,
    campo_mesmo_tecnico,
    campo_numero_visivel,
    campo_os_atrasada,
    campo_os_iniciada,
    campo_status_finalizado,
    campo_status_pausado,
    campo_tecnico_app_link,
    campo_tecnico_for_os_row,
    campo_tecnico_por_token,
    campo_token_for,
    campo_whatsapp_url,
    campo_whatsapp_url_para_tecnico,
    ensure_campo_eventos_table,
        ensure_campo_tecnicos_email_column,
    ensure_campo_tecnicos_sync_columns,
    get_tecnico_from_token,
    perfil_eh_campo,
    resumo_curto,
    sincronizar_tecnico_usuario,
    sincronizar_usuario_campo,
    usuario_eh_campo_operacional,
)
from app.combustivel.services import save_combustivel
from app.controle.services import save_bomba
from app.os.services import os_is_overdue, prepare_os_row_for_template
from app.pagamentos.services import save_pagamento
from app.storage import (
    company_folder_name,
    ensure_company_storage,
    load_whatsapp_templates,
    save_whatsapp_templates,
    tenant_upload_dir,
    upload_file_to_supabase,
)


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def current_company():
    from app.auth import current_company as fn
    return fn()


def current_user_is_super_admin(user=None):
    from app.auth import current_user_is_super_admin as fn
    return fn(user)


def get_current_user():
    from app.auth import get_current_user as fn
    return fn()


def company_where(table, prefix=' WHERE '):
    from app.auth import company_where as fn
    return fn(table, prefix)


def company_and(table):
    from app.auth import company_and as fn
    return fn(table)


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)


def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)


def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)


def get_conn():
    from app.db import get_conn as fn
    return fn()


def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)


def table_columns(table):
    from app.db import table_columns as fn
    return fn(table)


def select_existing_columns(table, desired, fallback='id'):
    from app.db.schema import select_existing_columns as fn
    return fn(table, desired, fallback=fallback)


def ensure_db():
    from app.db import ensure_db as fn
    return fn()


def tenant_upload_dir(kind, empresa_id=None):
    from app.storage import tenant_upload_dir as fn
    return fn(kind, empresa_id=empresa_id)


def company_folder_name(empresa_id=None):
    from app.storage import company_folder_name as fn
    return fn(empresa_id)


def ensure_company_storage(empresa_id=None):
    from app.storage import ensure_company_storage as fn
    return fn(empresa_id)


def load_whatsapp_templates(empresa_id=None):
    from app.storage import load_whatsapp_templates as fn
    return fn(empresa_id)


def save_whatsapp_templates(items, empresa_id=None):
    from app.storage import save_whatsapp_templates as fn
    return fn(items, empresa_id=empresa_id)


def active_whatsapp_template(tipo, empresa_id=None):
    from app.storage import active_whatsapp_template as fn
    return fn(tipo, empresa_id)


def upload_file_to_supabase(file_storage, storage_path, content_type=None):
    from app.storage import upload_file_to_supabase as fn
    return fn(file_storage, storage_path, content_type)


def pagamentos_query_rows(*args, **kwargs):
    from app.pagamentos.services import pagamentos_query_rows as fn
    return fn(*args, **kwargs)


def api_campo_feed_state():
    """Estado leve da fila de campo para polling inteligente."""
    try:
        empresa_id = current_company_id()
        # Versão baseada em os_ordens + campo_eventos pendentes
        sql_os = "SELECT COUNT(*) AS total, MAX(id) AS max_id FROM os_ordens"
        params_os = []
        if empresa_id:
            sql_os += " WHERE empresa_id=?"
            params_os.append(empresa_id)
        row_os = row_to_dict(query_one(sql_os, tuple(params_os))) or {}
        total = int(row_os.get('total') or 0)
        max_id = int(row_os.get('max_id') or 0)

        # Inclui max id de eventos pendentes para detectar novos popups
        try:
            ensure_campo_eventos_table()
            sql_ev = "SELECT COUNT(*) AS ev_total, MAX(id) AS ev_max FROM campo_eventos WHERE COALESCE(status,'novo')='novo'"
            params_ev = []
            if empresa_id:
                sql_ev += " AND (empresa_id=? OR empresa_id IS NULL OR empresa_id=0)"
                params_ev.append(empresa_id)
            row_ev = row_to_dict(query_one(sql_ev, tuple(params_ev))) or {}
            ev_total = int(row_ev.get('ev_total') or 0)
            ev_max = int(row_ev.get('ev_max') or 0)
        except Exception:
            ev_total = 0
            ev_max = 0

        version = f'{total}-{max_id}-{ev_total}-{ev_max}'
        return jsonify({'ok': True, 'total': total, 'max_id': max_id, 'ev_pending': ev_total, 'version': version})
    except Exception as exc:
        return jsonify({'ok': False, 'total': 0, 'max_id': 0, 'version': '0-0', 'erro': str(exc)}), 200



def api_campo_eventos():
    """Eventos de campo para popup do operador.

    Retorna JSON mesmo quando a sessão expirou. Assim o JavaScript não morre
    tentando interpretar uma página de login como JSON.
    """
    guard = _api_campo_guard('eventos')
    if guard:
        return guard
    empresa_id = current_company_id()
    try:
        ensure_campo_eventos_table()
        sql = """SELECT ce.id, ce.os_id, ce.empresa_id, ce.tipo, ce.titulo, ce.mensagem,
                        ce.status, ce.criado_em,
                        os.status AS os_status,
                        os.finalizada AS os_finalizada,
                        os.numero_os AS os_numero,
                        COALESCE(NULLIF(TRIM(os.numero_os), ''), CAST(os.id AS TEXT), CAST(ce.os_id AS TEXT)) AS numero_visivel
                 FROM campo_eventos ce
                 LEFT JOIN os_ordens os ON os.id=ce.os_id
                 WHERE COALESCE(ce.status,'novo')='novo'"""
        params = []
        if empresa_id:
            sql += " AND (ce.empresa_id=? OR os.empresa_id=? OR ce.empresa_id IS NULL OR ce.empresa_id=0)"
            params.extend([empresa_id, empresa_id])
        sql += " ORDER BY ce.id ASC LIMIT 30"
        rows = [dict(r) for r in query_all(sql, tuple(params))]
        # Recalcula numero_visivel via Python para garantir consistência
        for row in rows:
            os_row = {'id': row.get('os_id'), 'numero_os': row.get('os_numero')}
            row['numero_visivel'] = campo_numero_visivel(os_row, row.get('os_id'))
        return jsonify({'ok': True, 'eventos': rows})
    except Exception as exc:
        _flask_app().logger.exception('Falha ao buscar eventos de campo')
        return jsonify({'ok': False, 'eventos': [], 'erro': str(exc)}), 200




def api_campo_evento_teste():
    """Disparo manual para validar o popup sem depender do celular."""
    guard = _api_campo_guard('eventos')
    if guard:
        return guard
    empresa_id = current_company_id()
    row = row_to_dict(query_one('SELECT id, numero_os, empresa_id FROM os_ordens WHERE (? IS NULL OR empresa_id=?) ORDER BY id DESC LIMIT 1', (empresa_id, empresa_id)))
    if not row:
        return jsonify({'ok': False, 'erro': 'Nenhuma O.S. encontrada para testar.'}), 200
    eid = campo_evento_registrar(row['id'], row.get('empresa_id') or empresa_id, 'iniciar', '')
    return jsonify({'ok': True, 'event_id': eid})




def gestor_app():
    """App mobile do gestor."""
    if not session.get('user_id'):
        return redirect(url_for('login', next='/gestor/app'))

    user = get_current_user()
    if not user:
        return redirect(url_for('login'))

    # Técnico de campo não acessa o app do gestor
    try:
        if usuario_eh_campo_operacional(user) and not current_user_is_super_admin(user):
            token = campo_token_para_usuario(user)
            if token:
                return redirect(url_for('campo_app', token=token))
    except Exception:
        pass

    empresa_id = current_company_id()

    # Dados do dashboard
    where_sql, params = company_where('os_ordens')

    os_cols = select_existing_columns('os_ordens', [
        'id', 'data', 'sistema', 'equipamento', 'status', 'finalizada',
        'criticidade', 'responsavel', 'data_inicio', 'data_fim',
        'acumulado_minutos', 'motivo_pausa', 'motivo_atraso', 'numero_os',
        'descricao', 'troca_componentes', 'componentes_descricao', 'imagens'
    ])

    rows_db = query_all(
        f'SELECT {os_cols} FROM os_ordens{where_sql} ORDER BY id DESC LIMIT 200',
        tuple(params)
    )

    abertas, andamento, pausadas, atrasadas, finalizadas_hoje = [], [], [], [], []
    hoje = br_now().date()

    for r in rows_db:
        item = row_to_dict(r) or {}
        item['numero_visivel'] = item.get('numero_os') or item.get('id')
        item['link_campo'] = campo_link_publico(item.get('id'), empresa_id)
        finalizada = str(item.get('finalizada') or '').lower() == 'sim'
        status = str(item.get('status') or '').lower()
        atrasada = os_is_overdue(item)
        item['atrasada'] = atrasada

        if finalizada:
            data_os = parse_br_date(str(item.get('data') or ''))
            if data_os and data_os.date() == hoje:
                finalizadas_hoje.append(item)
            continue

        if atrasada:
            atrasadas.append(item)
        elif status == 'pausada':
            pausadas.append(item)
        elif status == 'em andamento':
            andamento.append(item)
        else:
            abertas.append(item)

    # Totais financeiros do mês
    mes_atual = br_now().strftime('%m/%Y')
    where_pag, params_pag = company_where('pagamentos')
    if where_pag:
        pag_sql = f"SELECT valor, tipo_lancamento FROM pagamentos{where_pag} AND pagamento_mes=?"
    else:
        pag_sql = "SELECT valor, tipo_lancamento FROM pagamentos WHERE pagamento_mes=?"
    pag_rows = query_all(pag_sql, tuple(list(params_pag) + [mes_atual]))
    gasto_mes = sum(parse_num(row_get_value(r, 'valor', 0))
                    for r in pag_rows
                    if str(row_get_value(r, 'tipo_lancamento', '') or '').lower() != 'investimento')
    investimento_mes = sum(parse_num(row_get_value(r, 'valor', 0))
                           for r in pag_rows
                           if str(row_get_value(r, 'tipo_lancamento', '') or '').lower() == 'investimento')

    # Combustível do mês
    where_comb, params_comb = company_where('combustivel')
    if where_comb:
        comb_sql = f"SELECT custo FROM combustivel{where_comb} AND mes_ref=?"
    else:
        comb_sql = "SELECT custo FROM combustivel WHERE mes_ref=?"
    comb_rows = query_all(comb_sql, tuple(list(params_comb) + [mes_atual]))
    combustivel_mes = sum(parse_num(row_get_value(r, 'custo', 0)) for r in comb_rows)

    cards = {
        'abertas': len(abertas),
        'andamento': len(andamento),
        'pausadas': len(pausadas),
        'atrasadas': len(atrasadas),
        'finalizadas_hoje': len(finalizadas_hoje),
        'gasto_mes': gasto_mes,
        'investimento_mes': investimento_mes,
        'combustivel_mes': combustivel_mes,
        'mes_ref': mes_atual,
    }

    tecnicos_campo = [dict(r) for r in query_all(
        """SELECT id, nome, telefone FROM campo_tecnicos
           WHERE COALESCE(empresa_id, ?) = ? AND COALESCE(ativo,1)=1
           ORDER BY nome""",
        (empresa_id, empresa_id)
    )]

    # Pagamentos do mês
    pag_rows_full = []
    if user_has('view_pagamentos'):
        where_pag2, params_pag2 = company_where('pagamentos')
        pag_cols = select_existing_columns('pagamentos', [
            'id','fornecedor','descricao_servico','valor','status','pagamento_mes','tipo_lancamento','numero_documento','sc_pedido'
        ])
        pag_rows_full = [row_to_dict(r) for r in query_all(
            f"SELECT {pag_cols} FROM pagamentos{where_pag2} ORDER BY id DESC LIMIT 100",
            tuple(params_pag2)
        )]
        for r in pag_rows_full:
            r['status_fmt'] = 'Pago' if payment_status_is_paid(r.get('status')) else 'Pendente'
            r['valor_fmt'] = br_money(parse_num(r.get('valor', 0)))

    # Combustível do mês
    comb_rows_full = []
    if user_has('view_combustivel'):
        where_c2, params_c2 = company_where('combustivel')
        comb_rows_full = [row_to_dict(r) for r in query_all(
            f"SELECT * FROM combustivel{where_c2} ORDER BY id DESC LIMIT 80",
            tuple(params_c2)
        )]
        for r in comb_rows_full:
            r['custo_fmt'] = br_money(parse_num(r.get('custo', 0)))

    # Bombas/estoque
    bombas_rows = []
    if user_has('view_controle'):
        where_b, params_b = company_where('bombas')
        bombas_rows = [row_to_dict(r) for r in query_all(
            f"SELECT id,equipamento,modelo,localizacao,status,status_entrega,previsao_entrega,fornecedor FROM bombas{where_b} ORDER BY id DESC LIMIT 80",
            tuple(params_b)
        )]

    # Técnicos de campo com link
    tecnicos_lista = []
    if user_has('view_os'):
        for t in tecnicos_campo:
            t2 = dict(t)
            t2['app_link'] = campo_tecnico_app_link(t2.get('id'), empresa_id) if t2.get('id') else ''
            tecnicos_lista.append(t2)

    # Inventário
    inv_rows = []
    inv_pedidos = []
    if user_has('view_inventario'):
        where_inv, params_inv = company_where('inventario_itens')
        inv_rows = [row_to_dict(r) for r in query_all(
            f"SELECT id,nome,categoria,unidade,quantidade,quantidade_minima,localizacao,fornecedor,valor_unitario FROM inventario_itens{where_inv} ORDER BY nome",
            tuple(params_inv)
        )]
        for r in inv_rows:
            r['valor_fmt'] = br_money(parse_num(r.get('valor_unitario', 0))) if r.get('valor_unitario') else ''
            r['baixo'] = parse_num(r.get('quantidade', 0)) <= parse_num(r.get('quantidade_minima', 0)) and parse_num(r.get('quantidade_minima', 0)) > 0
        where_ped, params_ped = company_where('inventario_pedidos')
        inv_pedidos = [row_to_dict(r) for r in query_all(
            f"""SELECT p.*, i.nome as item_nome, i.unidade FROM inventario_pedidos p
                LEFT JOIN inventario_itens i ON i.id=p.item_id{where_ped} AND p.status='pendente'
                ORDER BY p.id DESC LIMIT 50""",
            tuple(params_ped)
        )]

    # Custos
    custos_rows = []
    if user_has('view_custos'):
        where_cu, params_cu = company_where('custos')
        custos_rows = [row_to_dict(r) for r in query_all(
            f"SELECT id,sistema,equipamento,nr_os,descricao_os,mes FROM custos{where_cu} ORDER BY id DESC LIMIT 80",
            tuple(params_cu)
        )]

    return render_template(
        'mobile_gestor.html',
        user=user,
        cards=cards,
        abertas=abertas,
        andamento=andamento,
        pausadas=pausadas,
        atrasadas=atrasadas,
        finalizadas_hoje=finalizadas_hoje,
        tecnicos_campo=tecnicos_campo,
        tecnicos_lista=tecnicos_lista,
        sistemas_map=fetch_sistemas_map(),
        mes_ref=mes_atual,
        pagamentos_rows=pag_rows_full,
        combustivel_rows=comb_rows_full,
        bombas_rows=bombas_rows,
        inv_rows=inv_rows,
        inv_pedidos=inv_pedidos,
        custos_rows=custos_rows,
    )


# APIs mobile leves


@require_permission('edit_pagamentos')
def api_mobile_pag_save():
    try:
        rid = _safe_int_id(request.form.get('id'))
        saved_id = save_pagamento(request.form, request.files, rid)
        clear_view_cache()
        return jsonify({'ok': True, 'id': saved_id})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500




@require_permission('edit_combustivel')
def api_mobile_comb_save():
    try:
        rid = request.form.get('id') or None
        save_combustivel(request.form, rid)
        clear_view_cache()
        return jsonify({'ok': True})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500




@require_permission('edit_controle')
def api_mobile_bomba_save():
    try:
        rid = request.form.get('id') or None
        save_bomba(request.form, rid)
        clear_view_cache()
        return jsonify({'ok': True})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


    """Retorna/cria o token do app mobile para o usuário de campo."""
    try:
        user = row_to_dict(user) if user is not None else {}
        tecnico = campo_tecnico_row_para_usuario(user)

        # Se o perfil já é campo mas ainda não existe técnico, cria/sincroniza agora.
        if not tecnico and perfil_eh_campo(user.get('perfil')):
            tecnico = sincronizar_usuario_campo(
                user.get('id'),
                user.get('nome') or user.get('email') or '',
                user.get('email') or '',
                user.get('telefone') or '',
                user.get('empresa_id') or session.get('empresa_id'),
                user.get('perfil') or 'campo',
                user.get('ativo', 1),
            ) or {}

        if not tecnico or not tecnico.get('id'):
            return ''

        token = str(tecnico.get('token') or '').strip()
        if not token:
            token = campo_tecnico_token_for(tecnico.get('id'), tecnico.get('empresa_id') or user.get('empresa_id'))
        return str(token or '').strip()
    except Exception as exc:
        print('campo_token_para_usuario falhou:', exc)
        return ''




@require_permission('view_os')
def campo_page():
    status_filter = (request.args.get('status') or '').strip().lower()
    rows = list_page('os_ordens', 'id DESC')
    empresa_id = current_company_id()
    ensure_campo_tecnicos_sync_columns()
    # Garante que usuários com perfil de campo também existam na lista do WhatsApp.
    try:
        for u in query_all("""SELECT id, nome, email, telefone, perfil, empresa_id, ativo
                              FROM users
                              WHERE COALESCE(empresa_id, ?) = ?
                                AND COALESCE(ativo,1)=1""", (empresa_id, empresa_id)):
            ud = dict(u)
            if perfil_eh_campo(ud.get('perfil')):
                sincronizar_usuario_campo(ud.get('id'), ud.get('nome'), ud.get('email'), ud.get('telefone'), ud.get('empresa_id') or empresa_id, ud.get('perfil'), ud.get('ativo'))
    except Exception as exc:
        print('Sincronização automática de usuários de campo falhou:', exc)

    tecnicos = [dict(r) for r in query_all(
        """SELECT id, nome, email, telefone, ativo
           FROM campo_tecnicos
           WHERE COALESCE(empresa_id, ?) = ? AND COALESCE(ativo,1)=1
           ORDER BY nome""",
        (empresa_id, empresa_id)
    )]
    for t in tecnicos:
        t['app_link'] = campo_tecnico_app_link(t.get('id'), empresa_id) if t.get('id') else ''
    phone_by_name = {str(t.get('nome') or '').strip().lower(): t for t in tecnicos}
    prepared = []
    for r in rows:
        item = dict(r)
        item['link_campo'] = campo_link_publico(item.get('id'), item.get('empresa_id') or empresa_id)
        item['numero_visivel'] = campo_numero_visivel(item, item.get('id'))
        item['finalizada'] = (item.get('finalizada') or ('Sim' if campo_status_finalizado(item) else 'Não')).strip().title()
        item['atrasada'] = campo_os_atrasada(item)
        status_label = item.get('status') or ('Finalizada' if item.get('finalizada') == 'Sim' else 'Aberta')
        if item.get('finalizada') == 'Sim':
            status_label = 'Finalizada'
        elif item.get('atrasada'):
            status_label = 'Atrasada'
        item['status_label'] = status_label
        if status_filter:
            s_norm = str(status_label or '').strip().lower()
            if status_filter == 'a_enviar' and (s_norm not in ('aberta','pendente','nova') or item.get('atrasada')):
                continue
            if status_filter != 'a_enviar' and status_filter not in s_norm:
                continue
        tecnico = phone_by_name.get(str(item.get('responsavel') or '').strip().lower())
        item['tecnico_id'] = tecnico.get('id') if tecnico else ''
        item['telefone_tecnico'] = tecnico.get('telefone') if tecnico else ''
        item['telefone_tecnico_fmt'] = format_phone_br(item['telefone_tecnico']) if item.get('telefone_tecnico') else ''
        item['email_tecnico'] = tecnico.get('email') if tecnico else ''
        item['descricao_resumo'] = resumo_curto(item.get('descricao'), 110)
        prepared.append(item)
    templates_wpp = load_whatsapp_templates(empresa_id)
    return render_template('campo.html', rows=prepared, tecnicos=tecnicos, status_filter=status_filter, templates_wpp=templates_wpp)




@require_permission('manage_users')
def campo_tecnico_save():
    ensure_campo_tecnicos_email_column()
    rid = request.form.get('id')
    nome = (request.form.get('nome') or '').strip()
    email_tecnico = (request.form.get('email') or '').strip().lower()
    telefone = normalize_phone(request.form.get('telefone') or '')
    empresa_id = current_company_id()
    if not nome:
        flash('Informe o nome do técnico.', 'danger')
        return redirect(url_for('campo_page'))
    if email_tecnico and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email_tecnico):
        flash('Informe um e-mail válido para o técnico ou deixe em branco.', 'danger')
        return redirect(url_for('campo_page'))
    if rid:
        execute('UPDATE campo_tecnicos SET nome=?, email=?, telefone=?, ativo=1 WHERE id=? AND COALESCE(empresa_id, ?) = ?',
                (nome, email_tecnico, telefone, rid, empresa_id, empresa_id))
        sincronizar_tecnico_usuario(rid, nome, email_tecnico, telefone, empresa_id, 1, request.form.get('senha') or '')
        flash('Técnico atualizado.', 'success')
    else:
        novo_tecnico_id = execute('INSERT INTO campo_tecnicos(nome, email, telefone, empresa_id, ativo, criado_em, token) VALUES (?,?,?,?,?,?,?)',
                (nome, email_tecnico, telefone, empresa_id, 1, now_str(), uuid.uuid4().hex))
        sincronizar_tecnico_usuario(novo_tecnico_id, nome, email_tecnico, telefone, empresa_id, 1, request.form.get('senha') or '')
        flash('Técnico cadastrado.', 'success')
    return redirect(url_for('campo_page'))




@require_permission('manage_users')
def campo_tecnico_revogar_token(rid):
    empresa_id = current_company_id()
    tecnico = row_to_dict(query_one('SELECT id, nome FROM campo_tecnicos WHERE id=? AND COALESCE(empresa_id, ?) = ?', (rid, empresa_id, empresa_id)))
    if not tecnico:
        flash('Técnico não encontrado.', 'danger')
        return redirect(url_for('campo_page'))
    novo_token = _token_revogar(rid)
    flash(f'Token de {tecnico["nome"]} revogado. Um novo link foi gerado.', 'success')
    return redirect(url_for('campo_page'))




@require_permission('manage_users')
def campo_tecnico_delete(rid):
    empresa_id = current_company_id()
    tecnico = row_to_dict(query_one('SELECT id, nome FROM campo_tecnicos WHERE id=? AND COALESCE(empresa_id, ?) = ?', (rid, empresa_id, empresa_id)))
    if not tecnico:
        flash('Técnico não encontrado nesta unidade.', 'danger')
        return redirect(url_for('campo_page'))
    execute('UPDATE campo_tecnicos SET ativo=0 WHERE id=? AND COALESCE(empresa_id, ?) = ?', (rid, empresa_id, empresa_id))
    flash('Técnico removido da lista de campo.', 'success')
    return redirect(url_for('campo_page'))




@require_permission('manage_users')
def campo_template_save():
    empresa_id = current_company_id()
    ensure_company_storage(empresa_id)
    items = load_whatsapp_templates(empresa_id)
    idx_raw = request.form.get('idx')
    try:
        idx = int(idx_raw) if str(idx_raw or '').strip() != '' else None
    except Exception:
        idx = None
    image_url = request.form.get('imagem_url') or ''
    img_file = request.files.get('imagem')
    if img_file and img_file.filename:
        dest_name = f"template_{uuid.uuid4().hex}_{secure_filename(img_file.filename)}"
        dest = tenant_upload_dir('whatsapp_templates', empresa_id) / dest_name
        img_file.save(dest)
        image_url = url_for('static', filename=f"uploads/empresas/{company_folder_name(empresa_id)}/whatsapp_templates/{dest_name}", _external=True)
    item = {
        'nome': (request.form.get('nome') or 'Template WhatsApp').strip(),
        'tipo': (request.form.get('tipo') or 'nova_os').strip(),
        'ativo': request.form.get('ativo') == '1',
        'texto': request.form.get('texto') or '',
        'imagem': image_url
    }
    if item['ativo']:
        for old in items:
            if old.get('tipo') == item['tipo']:
                old['ativo'] = False
    if idx is not None and 0 <= idx < len(items):
        items[idx] = item
    else:
        items.append(item)
    save_whatsapp_templates(items, empresa_id)
    flash('Template do WhatsApp salvo para esta unidade.', 'success')
    return redirect(url_for('campo_page'))




def campo_short_app(token):
    return redirect(url_for('campo_app', token=token))





def campo_app_empty():
    return render_template('campo_app.html', erro='Abra pelo link do técnico enviado no WhatsApp.', tecnico=None, pendentes=[], andamento=[], pausadas=[], atrasadas=[], finalizadas=[]), 404




def campo_app(token):
    token = str(token or '').strip().strip('/')
    tecnico = row_to_dict(query_one('SELECT * FROM campo_tecnicos WHERE TRIM(token)=? AND ativo=1', (token,))) or {}

    if not tecnico:
        return render_template(
            'campo_app.html',
            erro='Link do app inválido ou técnico inativo.',
            tecnico=None,
            pendentes=[],
            andamento=[],
            pausadas=[],
            atrasadas=[],
            finalizadas=[],
            token=token
        ), 200

    # Verifica expiração do token
    if _token_expirado(tecnico):
        return render_template(
            'campo_app.html',
            erro='Seu link de acesso expirou. Entre em contato com o administrador para receber um novo link.',
            tecnico=None,
            pendentes=[],
            andamento=[],
            pausadas=[],
            atrasadas=[],
            finalizadas=[],
            token=token
        ), 200

    # Renova o token a cada acesso (mantém ativo por mais 30 dias)
    try:
        _token_renovar(tecnico['id'])
    except Exception:
        pass

    empresa_id = tecnico.get('empresa_id') or current_company_id() or 0
    tecnico_nome = str(tecnico.get('nome') or '').strip()
    tecnico_email = str(tecnico.get('email') or '').strip()

    rows = [dict(r) for r in query_all("""SELECT * FROM os_ordens
                                          WHERE COALESCE(empresa_id, ?) = ?
                                          ORDER BY id DESC""", (empresa_id, empresa_id))]

    pendentes, andamento, pausadas, atrasadas, finalizadas = [], [], [], [], []

    def _norm(v):
        return str(v or '').strip().lower()

    for item in rows:
        item['link_campo'] = campo_link_com_tecnico(item.get('id'), token, item.get('empresa_id') or empresa_id)
        item['link_mobile'] = item['link_campo']
        item['numero_visivel'] = campo_numero_visivel(item, item.get('id'))

        status = _norm(item.get('status'))
        responsavel = _norm(item.get('responsavel'))
        finalizada = campo_status_finalizado(item)
        pausada = campo_status_pausado(item)
        iniciada = campo_os_iniciada(item)

        minha = (
            bool(responsavel) and (
                responsavel == _norm(tecnico_nome)
                or responsavel == _norm(tecnico_email)
            )
        )

        atrasada = campo_os_atrasada(item)
        item['atrasada'] = bool(atrasada)
        item['responsavel_label'] = item.get('responsavel') or 'Disponível para equipe'

        # ===============================
        # CLASSIFICAÇÃO OFICIAL DO APP CAMPO
        # ===============================
        # 1) Finalizada nunca entra em atraso/disponíveis/andamento.
        #    Fica no histórico do técnico dono. Se não houver dono gravado, aparece para todos
        #    para não sumir O.S. finalizada pelo desktop.
        if finalizada:
            if minha or not responsavel:
                finalizadas.append(item)
            continue

        # 2) Atrasada aparece para TODOS os técnicos.
        if atrasada:
            atrasadas.append(item)
            continue

        # 2b) Pausada aparece para TODOS os técnicos — alguém precisa poder retomar.
        if pausada and iniciada:
            pausadas.append(item)
            if minha:
                andamento.append(item)
            continue

        # 3) Sem início = disponível/pendente para todos os técnicos.
        if not iniciada:
            pendentes.append(item)
            continue

        # 4) Em andamento = técnico dono + todos podem ver para retomar se necessário.
        andamento.append(item)

    return render_template(
        'campo_app.html',
        erro=None,
        tecnico=tecnico,
        pendentes=pendentes,
        andamento=andamento,
        pausadas=pausadas,
        atrasadas=atrasadas,
        finalizadas=finalizadas,
        token=token
    )




@require_permission('view_os')
def campo_whatsapp(rid):
    where_sql, params = company_and('os_ordens')
    row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?' + where_sql, tuple([rid] + params)))
    if not row:
        flash('O.S. não encontrada nesta unidade.', 'danger')
        return redirect(url_for('campo_page'))
    telefone = request.args.get('telefone', '').strip()
    tecnico_id = request.args.get('tecnico_id', '').strip()
    tecnico = {}
    empresa_id = row.get('empresa_id') or current_company_id()
    if tecnico_id and tecnico_id.isdigit():
        tecnico = row_to_dict(query_one('SELECT * FROM campo_tecnicos WHERE id=? AND COALESCE(empresa_id, ?) = ? AND ativo=1', (int(tecnico_id), empresa_id, empresa_id))) or {}
        telefone = tecnico.get('telefone') or telefone
    if not telefone:
        tecnico = campo_tecnico_for_os_row(row)
        telefone = (tecnico or {}).get('telefone') or ''
    if not telefone:
        flash('Este responsável ainda não tem WhatsApp cadastrado. Cadastre o telefone na aba Campo / WhatsApp.', 'warning')
        return redirect(url_for('campo_page'))
    if tecnico and tecnico.get('id'):
        return redirect(campo_whatsapp_url_para_tecnico(row, tecnico))
    return redirect(campo_whatsapp_url(row, telefone))




@require_permission('view_os')
def campo_whatsapp_equipe(rid):
    where_sql, params = company_and('os_ordens')
    row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?' + where_sql, tuple([rid] + params)))
    if not row:
        flash('O.S. não encontrada nesta unidade.', 'danger')
        return redirect(url_for('campo_page'))
    empresa_id = row.get('empresa_id') or current_company_id()
    tecnicos = [dict(t) for t in query_all("""SELECT id, nome, email, telefone, token
           FROM campo_tecnicos WHERE COALESCE(empresa_id, ?) = ? AND ativo=1 ORDER BY nome""", (empresa_id, empresa_id))]
    links = []
    for t in tecnicos:
        if not (t.get('telefone') or '').strip():
            continue
        links.append({'nome': t.get('nome') or 'Técnico', 'telefone': format_phone_br(t.get('telefone') or ''), 'url': campo_whatsapp_url_para_tecnico(row, t)})
    if not links:
        flash('Nenhum técnico ativo com WhatsApp cadastrado.', 'warning')
        return redirect(url_for('campo_page'))
    numero = campo_numero_visivel(row, row.get('id'))
    html_links = ''.join([f'<a class="btn" href="{item["url"]}" target="_blank" rel="noopener">Enviar para {item["nome"]} <small>{item["telefone"]}</small></a>' for item in links])
    return '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Avisar equipe - O.S. #{}</title><style>body{{font-family:Inter,Arial,sans-serif;background:#eef4fb;margin:0;padding:24px;color:#17233b}}.card{{max-width:680px;margin:auto;background:#fff;border-radius:22px;padding:22px;box-shadow:0 16px 42px rgba(31,51,84,.12)}}h1{{margin:0 0 8px;font-size:1.45rem}}p{{color:#60708a;margin:0 0 18px;line-height:1.4}}.btn{{display:flex;justify-content:space-between;gap:10px;align-items:center;margin:10px 0;padding:13px 15px;border-radius:15px;text-decoration:none;background:#18a85b;color:#fff;font-weight:900}}.btn small{{opacity:.88;font-weight:700}}.back{{display:inline-block;margin-top:14px;color:#2f6fb4;text-decoration:none;font-weight:800}}</style></head><body><div class="card"><h1>Avisar equipe - O.S. #{}</h1><p>Clique em cada técnico para abrir o WhatsApp com a mensagem pronta. A O.S. aparece no app de todos; quem tocar em <b>Iniciar</b> primeiro assume.</p>{}<a class="back" href="{}">← voltar</a></div></body></html>'.format(numero, numero, html_links, url_for('campo_page'))




def campo_tecnico(rid, token):
    row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,)))
    if not row:
        return render_template('campo_tecnico.html', erro='O.S. não encontrada.', row=None), 404
    empresa_id = row.get('empresa_id') or 0
    expected = campo_token_for(rid, empresa_id)
    if not hmac.compare_digest(str(token or ''), expected):
        return render_template('campo_tecnico.html', erro='Link inválido ou expirado.', row=None), 403

    tecnico_token = request.values.get('tecnico_token') or request.args.get('tecnico_token') or ''
    tecnico_app = campo_tecnico_por_token(tecnico_token, empresa_id) if tecnico_token else {}

    def _img_count(row_dict):
        try:
            return len(json.loads(row_dict.get('imagens') or '[]'))
        except Exception:
            return 0

    if request.method == 'POST':
        acao = request.form.get('acao')
        if not acao:
            if request.form.get('campo_problema') and request.form.get('servico_executado'):
                acao = 'finalizar'
            else:
                acao = 'salvar'
        agora = br_now()
        now_hora = agora.strftime('%H:%M')
        now_full = agora.strftime('%d/%m/%Y %H:%M')

        status = row.get('status') or 'Aberta'
        finalizada = row.get('finalizada') or 'Não'
        data_inicio = only_time_str(row.get('data_inicio'))
        data_fim = only_time_str(row.get('data_fim'))
        acumulado = int(row.get('acumulado_minutos') or 0)

        # Helper: adiciona evento ao historico_pausas (JSON)
        # Sempre lê direto do banco para evitar duplicação com dados stale
        def _hist_add(acao_hist, motivo=''):
            try:
                r_atual = row_to_dict(query_one('SELECT historico_pausas FROM os_ordens WHERE id=?', (rid,))) or {}
                hist = json.loads(r_atual.get('historico_pausas') or '[]')
            except Exception:
                hist = []
            evento = {'acao': acao_hist, 'quando': now_full}
            if motivo:
                evento['motivo'] = motivo
            if acao_hist == 'iniciado' and any(e.get('acao') == 'iniciado' for e in hist):
                return
            if acao_hist == 'finalizado' and any(e.get('acao') == 'finalizado' for e in hist):
                return
            hist.append(evento)
            execute('UPDATE os_ordens SET historico_pausas=? WHERE id=?',
                    (json.dumps(hist, ensure_ascii=False), rid))

        try:
            imagens = json.loads(row.get('imagens') or '[]')
        except Exception:
            imagens = []

        if acao == 'iniciar':
            if finalizada == 'Sim':
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, erro='Esta O.S. já foi finalizada.')

            responsavel_atual = str(row.get('responsavel') or '').strip()
            if responsavel_atual and tecnico_app and not campo_mesmo_tecnico(responsavel_atual, tecnico_app):
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, erro=f'Esta O.S. já foi assumida por {responsavel_atual}.')

            # data_inicio guarda data+hora completa para rastreio
            if not data_inicio or str(status).strip().lower() == 'pausada':
                data_inicio = now_full
            status = 'Em andamento'
            finalizada = 'Não'
            data_fim = ''
            responsavel_novo = responsavel_atual
            if tecnico_app:
                responsavel_novo = (tecnico_app.get('nome') or tecnico_app.get('email') or responsavel_atual or '').strip()

            if tecnico_app:
                conn = get_conn()
                try:
                    cur = conn.execute("""UPDATE os_ordens
                                          SET responsavel=?, status=?, finalizada=?, data_inicio=?, data_fim=?
                                          WHERE id=? AND COALESCE(empresa_id, ?) = ?
                                            AND (TRIM(COALESCE(responsavel,'')) = ''
                                                 OR lower(trim(COALESCE(responsavel,''))) = lower(trim(?))
                                                 OR lower(trim(COALESCE(responsavel,''))) = lower(trim(?)))""",
                                       (responsavel_novo, status, finalizada, data_inicio, data_fim, rid, empresa_id, empresa_id, tecnico_app.get('nome') or '', tecnico_app.get('email') or ''))
                    changed = getattr(cur, 'rowcount', None)
                    conn.commit()
                finally:
                    try: conn.close()
                    except Exception: pass
                if changed == 0:
                    row_bloqueada = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,))) or row
                    dono = row_bloqueada.get('responsavel') or 'outro técnico'
                    return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row_bloqueada), token=token, tecnico_token=tecnico_token, erro=f'Essa O.S. já foi assumida por {dono}.')
            else:
                execute("""UPDATE os_ordens SET status=?, finalizada=?, data_inicio=?, data_fim=? WHERE id=?""", (status, finalizada, data_inicio, data_fim, rid))

            # Registra no histórico: só "iniciado" na primeira vez
            # "retomado" é gravado exclusivamente pela ação retomar
            row_atual = row_to_dict(query_one('SELECT historico_pausas FROM os_ordens WHERE id=?', (rid,))) or {}
            hist_atual = json.loads(row_atual.get('historico_pausas') or '[]')
            if not any(e.get('acao') == 'iniciado' for e in hist_atual):
                _hist_add('iniciado', f'Responsável: {responsavel_novo or "não informado"}')
            campo_evento_registrar(rid, empresa_id, 'iniciar', f"Responsável: {responsavel_novo or 'não informado'}.")
            clear_view_cache()
            row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,)))
            return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, sucesso='Atendimento iniciado. O tempo começou a contar.', erro=None)

        if acao == 'pausar':
            if finalizada == 'Sim':
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, erro='Esta O.S. já foi finalizada.')
            if data_inicio and str(status).strip().lower() == 'em andamento':
                acumulado += time_diff_minutes(only_time_str(data_inicio), now_hora) or 0
            status = 'Pausada'
            finalizada = 'Não'
            data_fim = now_full  # data+hora completa
            motivo_pausa = str(request.form.get('motivo_pausa') or '').strip()
            execute("""UPDATE os_ordens
                       SET status=?, finalizada=?, data_fim=?, acumulado_minutos=?, motivo_pausa=?
                       WHERE id=?""",
                    (status, finalizada, data_fim, acumulado, motivo_pausa, rid))
            _hist_add('pausado', motivo_pausa)
            campo_evento_registrar(rid, empresa_id, 'pausar', motivo_pausa or '')
            clear_view_cache()
            row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,)))
            return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, sucesso='Atendimento pausado. O contador foi interrompido.', erro=None)

        if acao == 'justificar_atraso':
            motivo_atraso = str(request.form.get('motivo_atraso') or '').strip()
            execute('UPDATE os_ordens SET motivo_atraso=? WHERE id=?', (motivo_atraso, rid))
            clear_view_cache()
            row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,)))
            return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, sucesso='Justificativa registrada com sucesso.', erro=None)

        if acao == 'retomar':
            if finalizada == 'Sim':
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, erro='Esta O.S. já foi finalizada.')
            status = 'Em andamento'
            finalizada = 'Não'
            data_inicio = now_full  # data+hora completa
            data_fim = ''
            execute("""UPDATE os_ordens
                       SET status=?, finalizada=?, data_inicio=?, data_fim=?
                       WHERE id=?""",
                    (status, finalizada, data_inicio, data_fim, rid))
            _hist_add('retomado')
            campo_evento_registrar(rid, empresa_id, 'retomar', '')
            clear_view_cache()
            row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,)))
            return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, sucesso='Atendimento retomado. O tempo voltou a contar.', erro=None)

        if acao == 'finalizar' or (acao == 'salvar' and request.form.get('campo_problema') and request.form.get('servico_executado')):
            if finalizada == 'Sim' or str(status).strip().lower() in ('finalizada', 'finalizado'):
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, erro='Esta O.S. já foi finalizada.')
            acao = 'finalizar'

        if acao == 'finalizar':
            problema = (request.form.get('campo_problema') or '').strip()
            servico = (request.form.get('servico_executado') or '').strip()
            funcionando = (request.form.get('campo_funcionando') or '').strip()
            troca = 'Sim' if str(request.form.get('troca_componentes') or '').lower() in ('sim','s','1','true','on') else 'Não'
            componentes = (request.form.get('componentes_descricao') or '').strip() if troca == 'Sim' else ''
            teve_terceiro = 'Sim' if str(request.form.get('teve_terceiro') or '').lower() in ('sim','s','1','true','on') else 'Não'
            quem_foi_terceiro = (request.form.get('quem_foi_terceiro') or '').strip() if teve_terceiro == 'Sim' else ''
            fotos_enviadas = _campo_valid_files('imagens') + _campo_valid_files('foto1') + _campo_valid_files('foto2') + _campo_valid_files('foto3')

            if not problema:
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, erro='Informe qual foi o problema.')
            if not servico:
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, erro='Informe o que foi feito.')
            if funcionando not in ('Sim', 'Não'):
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, erro='Informe se já está funcionando.')

            imagens_existentes = [img for img in (imagens or []) if str(img or '').strip()]
            total_fotos_previsto = len(imagens_existentes) + len(fotos_enviadas)
            if total_fotos_previsto < 2:
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, erro=f'Envie pelo menos 2 fotos para finalizar. Recebidas agora: {len(fotos_enviadas)}.')
            if len(fotos_enviadas) > 3 or total_fotos_previsto > 3:
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, erro='Envie no máximo 3 fotos no total.')

            novas_fotos = _campo_save_images(fotos_enviadas, empresa_id)
            imagens = imagens_existentes + novas_fotos
            if len(imagens) < 2:
                return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, erro=f'Não consegui salvar as fotos no servidor. Verifique sua conexão e tente novamente. Salvas: {len(imagens)}.')

            if str(status).strip().lower() != 'pausada' and data_inicio:
                acumulado += time_diff_minutes(only_time_str(data_inicio), now_hora) or 0
            if not data_inicio:
                data_inicio = now_full

            status = 'Finalizada'
            finalizada = 'Sim'
            data_fim = now_full  # data+hora completa
            execute("""UPDATE os_ordens
                       SET status=?, finalizada=?, data_inicio=?, data_fim=?, acumulado_minutos=?,
                           servico_executado=?, troca_componentes=?, componentes_descricao=?, imagens=?,
                           campo_problema=?, campo_funcionando=?, campo_finalizado_em=?,
                           teve_terceiro=?, quem_foi_terceiro=?
                       WHERE id=?""",
                    (status, finalizada, data_inicio, data_fim, acumulado, servico, troca, componentes,
                     json.dumps(imagens, ensure_ascii=False), problema, funcionando, now_full,
                     teve_terceiro, quem_foi_terceiro, rid))
            _hist_add('finalizado', f'Tempo total: {elapsed_label("", "", acumulado, running=False)}')
            campo_evento_registrar(rid, empresa_id, 'finalizar', f"Tempo total: {elapsed_label('', '', acumulado, running=False)}.")
            clear_view_cache()
            row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,)))
            return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, sucesso='Atendimento finalizado com sucesso.', erro=None)

    return render_template('campo_tecnico.html', row=prepare_os_row_for_template(row), token=token, tecnico_token=tecnico_token, erro=None)




def api_campo_localizacao():
    """Recebe lat/lng do técnico em campo e atualiza na tabela campo_tecnicos."""
    try:
        data = request.get_json(silent=True) or {}
        lat = data.get('lat') or request.form.get('lat')
        lng = data.get('lng') or request.form.get('lng')
        os_id = data.get('os_id') or request.form.get('os_id')
        tecnico_token_qs = request.args.get('tecnico_token') or data.get('tecnico_token') or ''

        if not lat or not lng:
            return jsonify({'ok': False, 'error': 'lat/lng obrigatórios'}), 400

        tecnico_id = None

        # 1. Pelo tecnico_token (token do técnico em campo_tecnicos.token)
        if tecnico_token_qs:
            tc = campo_tecnico_por_token(tecnico_token_qs)
            if tc:
                tecnico_id = tc.get('id')

        # 2. Pelo responsavel da OS
        if not tecnico_id and os_id:
            try:
                os_row = row_to_dict(query_one(
                    'SELECT responsavel, empresa_id FROM os_ordens WHERE id=? LIMIT 1', (int(os_id),)
                ) or {})
                resp = os_row.get('responsavel') or ''
                if resp:
                    ct = row_to_dict(query_one(
                        'SELECT id FROM campo_tecnicos WHERE (nome=? OR email=?) AND ativo=1 LIMIT 1',
                        (resp, resp)
                    ) or {})
                    if ct:
                        tecnico_id = ct.get('id')
            except Exception:
                pass

        if not tecnico_id:
            _flask_app().logger.error('GPS ignorado: tecnico_token=%s os_id=%s responsavel_tentado=%s',
                           tecnico_token_qs, os_id,
                           (query_one('SELECT responsavel FROM os_ordens WHERE id=? LIMIT 1', (int(os_id),)) or {}).get('responsavel','?') if os_id else '?')
            return jsonify({'ok': True, 'warn': 'Tecnico nao identificado', 'token_recebido': tecnico_token_qs[:8] if tecnico_token_qs else 'vazio'})

        agora_iso = br_now().strftime('%Y-%m-%d %H:%M:%S')
        execute(
            'UPDATE campo_tecnicos SET campo_lat=?, campo_lng=?, campo_loc_updated_at=?, campo_os_id=? WHERE id=?',
            (float(lat), float(lng), agora_iso, int(os_id) if os_id else None, tecnico_id)
        )
        _flask_app().logger.warning('GPS salvo OK: tecnico_id=%s lat=%s lng=%s token=%s', tecnico_id, lat, lng, tecnico_token_qs[:8] if tecnico_token_qs else 'vazio')
        return jsonify({'ok': True})
    except Exception as exc:
        _flask_app().logger.error('api_campo_localizacao erro: %s', exc)
        return jsonify({'ok': False, 'error': str(exc)}), 500




@require_permission('view_os')
def api_campo_gps_debug():
    """Diagnóstico do GPS — ver o que está na tabela campo_tecnicos."""
    try:
        empresa_id = current_company_id()
        # Ver colunas da tabela
        cols = list(table_columns('campo_tecnicos'))
        # Ver todos os técnicos ativos
        rows = [row_to_dict(r) for r in (query_all(
            'SELECT id, nome, email, ativo, token, campo_lat, campo_lng, campo_loc_updated_at, campo_os_id FROM campo_tecnicos WHERE empresa_id=? LIMIT 10',
            (empresa_id,)
        ) or [])]
        return jsonify({
            'ok': True,
            'empresa_id': empresa_id,
            'colunas_disponiveis': cols,
            'tem_campo_lat': 'campo_lat' in cols,
            'tem_campo_lng': 'campo_lng' in cols,
            'tem_campo_loc_updated_at': 'campo_loc_updated_at' in cols,
            'tecnicos': rows,
            'total': len(rows)
        })
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)})




@require_permission('view_os')
def api_campo_tecnicos_mapa():
    """Retorna posições dos técnicos ativos em campo para o mapa do dashboard."""
    try:
        empresa_id = current_company_id()
        from datetime import datetime as _dt, timedelta as _td
        # Formato ISO para comparação correta no PostgreSQL
        limite_iso = (br_now() - _td(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')

        where = """WHERE campo_lat IS NOT NULL AND campo_lng IS NOT NULL
                   AND campo_loc_updated_at IS NOT NULL AND campo_loc_updated_at != ''
                   AND campo_loc_updated_at > ? AND ativo=1"""
        params = [limite_iso]
        if empresa_id:
            where += ' AND empresa_id=?'
            params.append(empresa_id)

        rows = query_all(
            f'SELECT id, nome, email, campo_lat, campo_lng, campo_loc_updated_at, campo_os_id FROM campo_tecnicos {where}',
            tuple(params)
        )

        tecnicos = []
        for r in rows:
            r = row_to_dict(r)
            nome = r.get('nome') or r.get('email') or 'Técnico'
            # Iniciais para avatar
            partes = nome.strip().split()
            iniciais = (partes[0][0] + (partes[-1][0] if len(partes) > 1 else '')).upper()
            # Cor do avatar baseada no ID
            cores = ['#2563eb','#7c3aed','#059669','#d97706','#dc2626','#0891b2','#be185d']
            cor = cores[int(r.get('id') or 0) % len(cores)]
            # Info da O.S. ativa
            os_info = {}
            if r.get('campo_os_id'):
                os_row = row_to_dict(query_one(
                    'SELECT numero_os, sistema, equipamento, status FROM os_ordens WHERE id=?',
                    (r['campo_os_id'],)
                ) or {})
                if os_row:
                    os_info = {
                        'numero': os_row.get('numero_os') or r['campo_os_id'],
                        'sistema': os_row.get('sistema') or '',
                        'equipamento': os_row.get('equipamento') or '',
                        'status': os_row.get('status') or '',
                    }
            tecnicos.append({
                'id': r.get('id'),
                'nome': nome,
                'iniciais': iniciais,
                'cor': cor,
                'lat': r.get('campo_lat'),
                'lng': r.get('campo_lng'),
                'updated_at': r.get('campo_loc_updated_at') or '',
                'os': os_info,
                'foto_url': r.get('foto_perfil') or '',
            })

        return jsonify({'ok': True, 'tecnicos': tecnicos})
    except Exception as exc:
        return jsonify({'ok': False, 'tecnicos': [], 'error': str(exc)})




def api_campo_tecnico_foto():
    """Upload de foto de perfil do técnico (feito pelo próprio técnico no app de campo)."""
    tecnico = get_tecnico_from_token()
    if not tecnico:
        return jsonify({'ok': False, 'error': 'Não autenticado'}), 401
    tid = tecnico.get('id')
    if not tid:
        return jsonify({'ok': False, 'error': 'Técnico inválido'}), 400
    f = request.files.get('foto')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'Nenhuma foto enviada'}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ('.jpg','.jpeg','.png','.webp'):
        return jsonify({'ok': False, 'error': 'Formato inválido. Use JPG, PNG ou WEBP.'}), 400
    # Salva em static/fotos_perfil/
    pasta = os.path.join(_flask_app().static_folder, 'fotos_perfil')
    os.makedirs(pasta, exist_ok=True)
    nome_arquivo = f'tecnico_{tid}{ext}'
    caminho = os.path.join(pasta, nome_arquivo)
    f.save(caminho)
    url = f'/static/fotos_perfil/{nome_arquivo}'
    execute('UPDATE campo_tecnicos SET foto_perfil=? WHERE id=?', (url, tid))
    return jsonify({'ok': True, 'foto_url': url})


def api_campo_tecnico_foto_delete():
    """Remove foto de perfil do técnico."""
    tecnico = get_tecnico_from_token()
    if not tecnico:
        return jsonify({'ok': False, 'error': 'Não autenticado'}), 401
    tid = tecnico.get('id')
    foto = tecnico.get('foto_perfil') or ''
    if foto and foto.startswith('/static/fotos_perfil/'):
        caminho = os.path.join(_flask_app().static_folder, foto.lstrip('/static/'))
        try:
            os.remove(caminho)
        except OSError:
            pass
    execute('UPDATE campo_tecnicos SET foto_perfil=? WHERE id=?', ('', tid))
    return jsonify({'ok': True})


def api_campo_evento_visto(eid):
    guard = _api_campo_guard('eventos')
    if guard:
        return guard
    empresa_id = current_company_id()
    try:
        ensure_campo_eventos_table()
        if empresa_id:
            execute("""UPDATE campo_eventos SET status='visto'
                       WHERE id=? AND (empresa_id=? OR empresa_id IS NULL OR empresa_id=0)""", (eid, empresa_id))
        else:
            execute("UPDATE campo_eventos SET status='visto' WHERE id=?", (eid,))
    except Exception as exc:
        _flask_app().logger.exception('Falha ao marcar evento de campo como visto')
        return jsonify({'ok': False, 'erro': str(exc)}), 200
    return jsonify({'ok': True})





def _flask_app():
    from app.runtime import flask_app
    return flask_app()


def register_routes(app):
    from app.auth.decorators import require_permission
    rules = [
        ('/api/campo/feed-state', 'api_campo_feed_state', api_campo_feed_state, ['GET']),
        ('/api/campo/eventos', 'api_campo_eventos', api_campo_eventos, ['GET']),
        ('/api/campo/eventos/<int:eid>/visto', 'api_campo_evento_visto', api_campo_evento_visto, ['POST']),
        ('/api/campo/eventos/teste', 'api_campo_evento_teste', api_campo_evento_teste, ['POST']),
        ('/gestor/app', 'gestor_app', gestor_app, ['GET']),
        ('/api/mobile/pagamentos/save', 'api_mobile_pag_save', api_mobile_pag_save, ['POST']),
        ('/api/mobile/combustivel/save', 'api_mobile_comb_save', api_mobile_comb_save, ['POST']),
        ('/api/mobile/bomba/save', 'api_mobile_bomba_save', api_mobile_bomba_save, ['POST']),
        ('/campo', 'campo_page', campo_page, ['GET']),
        ('/campo/tecnico/save', 'campo_tecnico_save', campo_tecnico_save, ['POST']),
        ('/campo/tecnico/revogar/<int:rid>', 'campo_tecnico_revogar_token', campo_tecnico_revogar_token, ['POST']),
        ('/campo/tecnico/delete/<int:rid>', 'campo_tecnico_delete', campo_tecnico_delete, ['POST']),
        ('/campo/templates/save', 'campo_template_save', campo_template_save, ['POST']),
        ('/c/<token>', 'campo_short_app', campo_short_app, ['GET', 'POST']),
        ('/campo/app/', 'campo_app_empty', campo_app_empty, ['GET', 'POST']),
        ('/campo/app/<path:token>', 'campo_app', campo_app, ['GET', 'POST']),
        ('/campo/whatsapp/<int:rid>', 'campo_whatsapp', campo_whatsapp, ['GET']),
        ('/campo/whatsapp/equipe/<int:rid>', 'campo_whatsapp_equipe', campo_whatsapp_equipe, ['GET']),
        ('/os/<int:rid>/campo/<token>', 'campo_tecnico', campo_tecnico, ['GET', 'POST']),
        ('/api/campo/localizacao', 'api_campo_localizacao', api_campo_localizacao, ['POST']),
        ('/api/campo/gps-debug', 'api_campo_gps_debug', api_campo_gps_debug, ['GET']),
        ('/api/campo/tecnicos-mapa', 'api_campo_tecnicos_mapa', api_campo_tecnicos_mapa, ['GET']),
        ('/api/campo/tecnico/foto', 'api_campo_tecnico_foto', api_campo_tecnico_foto, ['POST']),
        ('/api/campo/tecnico/foto', 'api_campo_tecnico_foto_delete', api_campo_tecnico_foto_delete, ['DELETE']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
