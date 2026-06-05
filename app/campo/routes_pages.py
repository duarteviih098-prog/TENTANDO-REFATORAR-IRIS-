"""Páginas Campo / PWA / WhatsApp."""
import re
import uuid

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from app.auth.decorators import require_permission
from app.auth.services import user_has
from app.campo.routes_common import (
    company_and,
    company_folder_name,
    company_where,
    current_company_id,
    current_user_is_super_admin,
    ensure_company_storage,
    execute,
    get_current_user,
    load_whatsapp_templates,
    query_all,
    query_one,
    save_whatsapp_templates,
    select_existing_columns,
    tenant_upload_dir,
)
from app.campo.services import (
    _token_expirado,
    _token_renovar,
    _token_revogar,
    campo_link_com_tecnico,
    campo_link_publico,
    campo_numero_visivel,
    campo_os_atrasada,
    campo_os_iniciada,
    campo_status_finalizado,
    campo_status_pausado,
    campo_tecnico_app_link,
    campo_tecnico_for_os_row,
    campo_token_para_usuario,
    campo_whatsapp_url,
    campo_whatsapp_url_para_tecnico,
    ensure_campo_tecnicos_email_column,
    ensure_campo_tecnicos_sync_columns,
    perfil_eh_campo,
    resumo_curto,
    sincronizar_tecnico_usuario,
    sincronizar_usuario_campo,
    usuario_eh_campo_operacional,
)
from app.os.services import os_is_overdue
from app.shared.formatters import br_money, br_now, format_phone_br, normalize_phone, now_str, parse_br_date, parse_num
from app.shared.payments import payment_status_is_paid
from app.shared.queries import fetch_sistemas_map, list_page
from app.shared.rows import row_get_value, row_to_dict


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



