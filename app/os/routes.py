"""Rotas /os/* e APIs de O.S. (exceto Campo/PWA — M11)."""
import hmac
import io
import json
import os
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from app.auth import owned_by_current_company, user_has
from app.auth.decorators import is_mobile_request
from app.campo.services import _api_campo_guard, campo_numero_visivel, campo_os_atrasada, campo_os_iniciada, campo_status_finalizado, campo_status_pausado, campo_tecnico_for_os_row, campo_token_for
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_money, br_now, elapsed_label, now_str, only_time_str, parse_br_date, parse_num, time_diff_minutes
from app.shared.months import normalize_month_reference
from app.shared.queries import fetch_sistemas_map, list_page, reset_sqlite_sequence_if_empty
from app.shared.rows import row_get_value, row_matches_month, row_to_dict
from app.storage import backup_company_data

from flask import current_app, flash, jsonify, redirect, render_template, request, send_file, session, url_for

from app.auth.decorators import require_permission
from app.os.pdf import _build_os_pdf
from app.os.services import (
    attach_os_display_numbers,
    os_is_overdue,
    prepare_os_row_for_template,
    save_ativo,
    save_os,
)
from app.storage import missing_attachment_response, normalize_storage_path, storage_or_local_response, sync_os_attachments
from app.storage.attachments import resolve_os_upload_path


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def current_company():
    from app.auth import current_company as fn
    return fn()


def current_user_is_super_admin():
    from app.auth import current_user_is_super_admin as fn
    return fn()


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


def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)


def table_columns(table):
    from app.db import table_columns as fn
    return fn(table)


def ensure_column(table, column, col_type):
    from app.db import ensure_column as fn
    return fn(table, column, col_type)


def select_existing_columns(table, desired, fallback='id'):
    from app.db.schema import select_existing_columns as fn
    return fn(table, desired, fallback=fallback)


@require_permission('view_os_ativos')
def os_ativos():
    rows = list_page('os_ativos')
    return render_template('os_ativos.html', rows=rows, sistemas_map=fetch_sistemas_map())



@require_permission('edit_os')
def os_ativos_save():
    rid = request.form.get('id') or None
    save_ativo(request.form, rid)
    backup_company_data(current_company_id())
    clear_view_cache()
    flash('Ativo salvo.', 'success')
    return redirect(url_for('os_ativos'))



@require_permission('view_os')
def os_redirect():
    """Redireciona /os para o hub."""
    return redirect(url_for('os_hub'))



@require_permission('view_os')
def os_lancamentos():
    """Redireciona para a listagem principal de O.S."""
    return redirect(url_for('os_page') + ('?' + request.query_string.decode() if request.query_string else ''))



@require_permission('view_os')
def os_page():
    filtro_mes = request.args.get('mes','').strip()
    filtro_status = request.args.get('status','').strip().lower()
    filtro_q = request.args.get('q','').strip().lower()
    filtro_componentes = request.args.get('componentes','').strip().lower()
    filtro_tipo_os = request.args.get('tipo_os','').strip()

    # Padrão: mês atual quando nenhum filtro for informado
    if not filtro_mes and not filtro_status and not filtro_q and not filtro_componentes and not filtro_tipo_os:
        filtro_mes = br_now().strftime('%m/%Y')

    where_sql, params = company_where('os_ordens')
    clauses = []
    params = list(params)

    if filtro_q:
        like = f'%{filtro_q}%'
        q_cols = [c for c in ('sistema','equipamento','responsavel','descricao','servico_executado','criticidade') if table_has_column('os_ordens', c)]
        if q_cols:
            clauses.append('(' + ' OR '.join([f"lower(COALESCE({c},'')) LIKE ?" for c in q_cols]) + ')')
            params.extend([like] * len(q_cols))

    if filtro_status == 'andamento':
        if table_has_column('os_ordens', 'status'):
            clauses.append("lower(COALESCE(status,'')) = 'em andamento'")
        if table_has_column('os_ordens', 'finalizada'):
            clauses.append("lower(COALESCE(finalizada,'')) <> 'sim'")
    elif filtro_status == 'pausadas':
        if table_has_column('os_ordens', 'status'):
            clauses.append("lower(COALESCE(status,'')) = 'pausada'")
    elif filtro_status == 'finalizada':
        parts = []
        if table_has_column('os_ordens', 'status'):
            parts.append("lower(COALESCE(status,'')) = 'finalizada'")
        if table_has_column('os_ordens', 'finalizada'):
            parts.append("lower(COALESCE(finalizada,'')) = 'sim'")
        if parts:
            clauses.append('(' + ' OR '.join(parts) + ')')

    if filtro_componentes:
        comp_cols = [c for c in ('troca_componentes','componentes','teve_troca_componentes') if table_has_column('os_ordens', c)]
        if comp_cols:
            sim_expr = '(' + ' OR '.join([f"lower(COALESCE({c},'')) IN ('sim','s','yes','true','1')" for c in comp_cols]) + ')'
            if filtro_componentes in ('sim','s','yes','1'):
                clauses.append(sim_expr)
            elif filtro_componentes in ('nao','não','n','no','0'):
                clauses.append('NOT ' + sim_expr)

    if filtro_tipo_os and table_has_column('os_ordens', 'tipo_os'):
        clauses.append("lower(COALESCE(tipo_os,'')) = ?")
        params.append(filtro_tipo_os.lower())

    if filtro_mes and table_has_column('os_ordens', 'data'):
        # filtro de mês simples pelo texto dd/mm/aaaa; mantém filtro Python como garantia abaixo.
        m = re.search(r'(\d{1,2})\s*/\s*(\d{2,4})', filtro_mes)
        if m:
            mes = int(m.group(1)); ano = int(m.group(2)); ano = ano + 2000 if ano < 100 else ano
            clauses.append("COALESCE(data,'') LIKE ?")
            params.append(f'%/{mes:02d}/{ano}%')

    if clauses:
        where_sql += (' AND ' if where_sql else ' WHERE ') + ' AND '.join(clauses)

    os_cols = select_existing_columns('os_ordens', [
        'id','data','sistema','equipamento','status','finalizada','criticidade','responsavel',
        'data_inicio','data_fim','acumulado_minutos','troca_componentes','teve_troca_componentes',
        'componentes','componentes_descricao','descricao','servico_executado','orcamentos','imagens',
        'teve_terceiro','quem_foi_terceiro','custo_os','observacao_custo','empresa_id',
        'motivo_pausa','motivo_atraso','numero_os','tipo_os'
    ])
    # A lista carrega só uma janela recente/filtrada. Edição baixa o registro completo via /api/os/<id>.
    rows_db = query_all(f'SELECT {os_cols} FROM os_ordens{where_sql} ORDER BY id DESC LIMIT ?', tuple(params + [int(os.getenv('OS_PAGE_LIMIT', '120') or 120)]))

    rows = []
    for idx, row in enumerate(rows_db, start=1):
        item = dict(row)
        try:
            item['orcamentos'] = item.get('orcamentos') if isinstance(item.get('orcamentos'), list) else json.loads(item.get('orcamentos') or '[]')
        except Exception:
            item['orcamentos'] = []
        try:
            item['imagens'] = item.get('imagens') if isinstance(item.get('imagens'), list) else json.loads(item.get('imagens') or '[]')
        except Exception:
            item['imagens'] = []
        item['numero_os'] = item.get('numero_os') or item.get('id')
        item['finalizada'] = (item.get('finalizada') or ('Sim' if str(item.get('status') or '').strip().lower() == 'finalizada' else 'Não')).strip().title()
        item['data_inicio'] = only_time_str(item.get('data_inicio'))
        item['data_fim'] = only_time_str(item.get('data_fim'))
        item['atrasada'] = os_is_overdue(item)
        item['acumulado_minutos'] = int(item.get('acumulado_minutos') or 0)
        running = str(item.get('status') or '').strip().lower() == 'em andamento' and item['finalizada'] != 'Sim'
        item['tempo_decorrido'] = elapsed_label(item.get('data_inicio'), item.get('data_fim'), item.get('acumulado_minutos', 0), running=running)
        if filtro_mes and not row_matches_month(item.get('data'), month_ref=filtro_mes):
            continue
        if filtro_status == 'atrasadas' and not item['atrasada']:
            continue
        rows.append(item)

    def _os_priority_key(item):
        data_parsed = parse_br_date(str(item.get('data') or '')) or datetime.min
        try:
            rid = int(item.get('id') or 0)
        except Exception:
            rid = 0
        status_norm = str(item.get('status') or '').strip().lower()
        finalizada = (str(item.get('finalizada') or '').strip().lower() == 'sim' or status_norm in ('finalizada', 'finalizado', 'entregue'))
        atrasada_aberta = bool(item.get('atrasada')) and not finalizada
        grupo = 0 if atrasada_aberta else (2 if finalizada else 1)
        timestamp = data_parsed.timestamp() if data_parsed != datetime.min else 0
        return (grupo, -timestamp, -rid)

    rows.sort(key=_os_priority_key)

    # Numeração visual da lista: não usa o ID real do banco.
    # Assim a tela não começa em 9/58/etc.; o ID continua preservado em item['id'] para editar/excluir.
    for numero_visual, item in enumerate(rows, start=1):
        item['numero_os'] = numero_visual
        item['display_numero_os'] = numero_visual

    empresa_id = current_company_id()
    tecnicos_campo = [dict(r) for r in query_all(
        """SELECT id, nome, email, telefone, ativo, is_super_admin
           FROM users
           WHERE COALESCE(empresa_id, ?) = ?
             AND ativo=1
             AND COALESCE(is_super_admin,0)=0
             AND lower(COALESCE(perfil,'')) NOT IN ('super_admin','administrador supremo','supremo')
           ORDER BY nome
           LIMIT 120""",
        (empresa_id, empresa_id)
    )]
    return render_template('os.html', rows=rows, filtro_mes=filtro_mes, filtro_status=filtro_status, filtro_q=filtro_q, filtro_componentes=filtro_componentes, filtro_tipo_os=filtro_tipo_os, tecnicos_campo=tecnicos_campo)


# ═══════════════════════════════════════════════════════════════
# HUB DE O.S. — sub-módulos
# ═══════════════════════════════════════════════════════════════



@require_permission('view_os')
def os_paradas():
    """Retorna O.S. abertas/em andamento que estão paradas há mais de 2 horas."""
    where_sql, params = company_where('os_ordens')
    agora = br_now()

    os_cols = select_existing_columns('os_ordens', [
        'id','sistema','equipamento','status','finalizada','responsavel',
        'data','data_inicio','acumulado_minutos','numero_os'
    ])
    rows = query_all(
        f"""SELECT {os_cols} FROM os_ordens{where_sql}
            AND COALESCE(finalizada,'') NOT IN ('Sim','sim')
            AND lower(COALESCE(status,'')) NOT IN ('finalizada','finalizado')
            ORDER BY id DESC LIMIT 100""",
        tuple(params)
    )

    paradas = []
    for r in rows:
        st = str(r.get('status') or '').lower()
        # Considera parada: aberta ou em andamento sem movimentação
        # Usa data de abertura como referência
        data_ref = parse_br_date(r.get('data') or '')
        if not data_ref:
            continue
        horas_parada = (agora - data_ref).total_seconds() / 3600
        # Só notifica se parada há mais de 4 horas e não finalizada
        if horas_parada < 4:
            continue
        paradas.append({
            'id': r.get('id'),
            'sistema': r.get('sistema') or '',
            'equipamento': r.get('equipamento') or '',
            'responsavel': r.get('responsavel') or 'Sem responsável',
            'status': r.get('status') or 'Aberta',
            'numero_os': r.get('numero_os') or r.get('id'),
            'horas': round(horas_parada, 1),
        })

    # Limita a 3 notificações por vez
    return jsonify({'ok': True, 'paradas': paradas[:3]})




@require_permission('view_os')
def os_hub():
    """Hub central do módulo de O.S."""
    where_sql, params = company_where('os_ordens')
    agora = br_now()

    os_cols = select_existing_columns('os_ordens', [
        'id','status','finalizada','criticidade','responsavel',
        'data','acumulado_minutos','data_inicio','data_fim','motivo_atraso'
    ])
    rows_db = query_all(f'SELECT {os_cols} FROM os_ordens{where_sql} ORDER BY id DESC LIMIT 500', tuple(params))

    rows = []
    for r in rows_db:
        item = dict(r)
        item['finalizada'] = (item.get('finalizada') or ('Sim' if str(item.get('status') or '').lower() == 'finalizada' else 'Não')).strip().title()
        item['atrasada'] = os_is_overdue(item)
        rows.append(item)

    total       = len(rows)
    abertas     = sum(1 for r in rows if r['finalizada'] != 'Sim' and str(r.get('status') or '').lower() not in ('em andamento','pausada','finalizada'))
    andamento   = sum(1 for r in rows if str(r.get('status') or '').lower() == 'em andamento' and r['finalizada'] != 'Sim')
    pausadas    = sum(1 for r in rows if str(r.get('status') or '').lower() == 'pausada' and r['finalizada'] != 'Sim')
    finalizadas = sum(1 for r in rows if r['finalizada'] == 'Sim' or str(r.get('status') or '').lower() == 'finalizada')
    atrasadas   = sum(1 for r in rows if r['atrasada'] and r['finalizada'] != 'Sim')

    # Técnicos únicos ativos
    tecnicos_uniq = len(set(r.get('responsavel') or '' for r in rows if r.get('responsavel')))

    return render_template('os_hub.html',
        total=total, abertas=abertas, andamento=andamento,
        pausadas=pausadas, finalizadas=finalizadas, atrasadas=atrasadas,
        tecnicos_ativos=tecnicos_uniq,
    )




@require_permission('view_os')
def os_kanban():
    """Visão Kanban das O.S. por status."""
    where_sql, params = company_where('os_ordens')

    os_cols = select_existing_columns('os_ordens', [
        'id','data','sistema','equipamento','status','finalizada','criticidade',
        'responsavel','descricao','servico_executado','acumulado_minutos',
        'data_inicio','data_fim','numero_os'
    ])
    rows_db = query_all(f'SELECT {os_cols} FROM os_ordens{where_sql} ORDER BY id DESC LIMIT 200', tuple(params))

    from collections import defaultdict
    colunas = {'Aberta': [], 'Em andamento': [], 'Pausada': [], 'Finalizada': []}

    for r in rows_db:
        item = dict(r)
        item['finalizada'] = (item.get('finalizada') or ('Sim' if str(item.get('status') or '').lower() == 'finalizada' else 'Não')).strip().title()
        item['atrasada'] = os_is_overdue(item)
        item['numero_os'] = item.get('numero_os') or item.get('id')
        st = str(item.get('status') or '').strip().lower()
        if item['finalizada'] == 'Sim' or st == 'finalizada':
            colunas['Finalizada'].append(item)
        elif st == 'em andamento':
            colunas['Em andamento'].append(item)
        elif st == 'pausada':
            colunas['Pausada'].append(item)
        else:
            colunas['Aberta'].append(item)

    return render_template('os_kanban.html', colunas=colunas)




@require_permission('view_os')
def os_tecnicos():
    """Painel por técnico — quem está fazendo o quê."""
    where_sql, params = company_where('os_ordens')

    os_cols = select_existing_columns('os_ordens', [
        'id','data','sistema','equipamento','status','finalizada','criticidade',
        'responsavel','descricao','acumulado_minutos','data_inicio','data_fim','numero_os'
    ])
    rows_db = query_all(f'SELECT {os_cols} FROM os_ordens{where_sql} ORDER BY id DESC LIMIT 500', tuple(params))

    from collections import defaultdict
    tecnicos = defaultdict(lambda: {
        'abertas': [], 'andamento': [], 'pausadas': [], 'finalizadas': [],
        'total': 0, 'minutos': 0
    })

    for r in rows_db:
        item = dict(r)
        nome = (item.get('responsavel') or 'Sem responsável').strip()
        item['finalizada'] = (item.get('finalizada') or ('Sim' if str(item.get('status') or '').lower() == 'finalizada' else 'Não')).strip().title()
        item['atrasada'] = os_is_overdue(item)
        item['numero_os'] = item.get('numero_os') or item.get('id')
        st = str(item.get('status') or '').strip().lower()
        t = tecnicos[nome]
        t['total'] += 1
        t['minutos'] += int(item.get('acumulado_minutos') or 0)
        if item['finalizada'] == 'Sim' or st == 'finalizada':
            t['finalizadas'].append(item)
        elif st == 'em andamento':
            t['andamento'].append(item)
        elif st == 'pausada':
            t['pausadas'].append(item)
        else:
            t['abertas'].append(item)

    lista = []
    for nome, t in tecnicos.items():
        horas = t['minutos'] // 60
        mins  = t['minutos'] % 60
        taxa  = round(len(t['finalizadas']) / t['total'] * 100) if t['total'] else 0
        lista.append({
            'nome': nome,
            'iniciais': ''.join(p[0].upper() for p in nome.split()[:2]),
            'total': t['total'],
            'abertas': len(t['abertas']),
            'andamento': len(t['andamento']),
            'pausadas': len(t['pausadas']),
            'finalizadas': len(t['finalizadas']),
            'tempo': f"{horas:02d}:{mins:02d}",
            'taxa_conclusao': taxa,
            'os_ativas': t['andamento'] + t['abertas'],
        })
    lista.sort(key=lambda x: x['andamento'], reverse=True)

    return render_template('os_tecnicos.html', tecnicos=lista)




@require_permission('view_os')
def os_relatorios():
    """Relatórios analíticos de O.S."""
    where_sql, params = company_where('os_ordens')
    agora = br_now()

    os_cols = select_existing_columns('os_ordens', [
        'id','data','sistema','equipamento','status','finalizada','criticidade',
        'responsavel','acumulado_minutos','data_inicio','data_fim','troca_componentes'
    ])
    rows_db = query_all(f'SELECT {os_cols} FROM os_ordens{where_sql} ORDER BY id DESC LIMIT 1000', tuple(params))

    from collections import defaultdict, Counter
    rows = []
    for r in rows_db:
        item = dict(r)
        item['finalizada'] = (item.get('finalizada') or ('Sim' if str(item.get('status') or '').lower() == 'finalizada' else 'Não')).strip().title()
        item['atrasada'] = os_is_overdue(item)
        rows.append(item)

    # Equipamentos que mais geram OS
    equip_count = Counter(r.get('equipamento') or r.get('sistema') or 'Sem identificação' for r in rows)
    top_equipamentos = [{'nome': k, 'total': v} for k, v in equip_count.most_common(10)]

    # Por técnico
    tec_stats = defaultdict(lambda: {'total': 0, 'finalizadas': 0, 'minutos': 0, 'atrasadas': 0})
    for r in rows:
        nome = (r.get('responsavel') or 'Sem responsável').strip()
        t = tec_stats[nome]
        t['total'] += 1
        t['minutos'] += int(r.get('acumulado_minutos') or 0)
        if r['finalizada'] == 'Sim':
            t['finalizadas'] += 1
        if r['atrasada']:
            t['atrasadas'] += 1
    top_tecnicos = sorted([
        {'nome': k, **v,
         'taxa': round(v['finalizadas']/v['total']*100) if v['total'] else 0,
         'tempo_medio': f"{(v['minutos']//v['finalizadas'] if v['finalizadas'] else 0)//60:02d}:{(v['minutos']//v['finalizadas'] if v['finalizadas'] else 0)%60:02d}"}
        for k, v in tec_stats.items()
    ], key=lambda x: x['total'], reverse=True)[:10]

    # Por criticidade
    crit_count = Counter(r.get('criticidade') or 'Não definida' for r in rows)
    por_criticidade = [{'label': k, 'total': v} for k, v in crit_count.most_common()]

    # Tendência 6 meses
    meses_labels, meses_abertas, meses_fechadas = [], [], []
    for i in range(5, -1, -1):
        m = agora.month - i
        y = agora.year
        while m <= 0: m += 12; y -= 1
        ref = f"{m:02d}/{y}"
        meses_labels.append(ref)
        mes_rows = [r for r in rows if (r.get('data') or '').endswith(f'/{m:02d}/{y}') or f'/{m:02d}/{y}' in (r.get('data') or '')]
        meses_abertas.append(len(mes_rows))
        meses_fechadas.append(sum(1 for r in mes_rows if r['finalizada'] == 'Sim'))

    # SLA — % dentro do prazo
    finalizadas_total = sum(1 for r in rows if r['finalizada'] == 'Sim')
    atrasadas_total   = sum(1 for r in rows if r['atrasada'])
    sla = round((finalizadas_total - atrasadas_total) / finalizadas_total * 100) if finalizadas_total else 0

    return render_template('os_relatorios.html',
        top_equipamentos=top_equipamentos,
        top_tecnicos=top_tecnicos,
        por_criticidade=por_criticidade,
        meses_labels=meses_labels,
        meses_abertas=meses_abertas,
        meses_fechadas=meses_fechadas,
        total=len(rows),
        finalizadas_total=finalizadas_total,
        atrasadas_total=atrasadas_total,
        sla=sla,
    )




def api_os_status_updates():
    guard = _api_campo_guard('rows')
    if guard:
        return guard
    empresa_id = current_company_id()
    try:
        sql = """SELECT *
                 FROM os_ordens"""
        params = []
        if empresa_id:
            sql += " WHERE empresa_id=?"
            params.append(empresa_id)
        rows = []
        for r in query_all(sql, tuple(params)):
            item = dict(r)
            finalizada_bool = campo_status_finalizado(item)
            atrasada_bool = campo_os_atrasada(item)
            status_raw = str(item.get('status') or '').strip()

            if finalizada_bool:
                status_label = 'Finalizada'
                status_class = 'status-finalizada'
            elif atrasada_bool:
                status_label = 'Atrasada'
                status_class = 'status-atrasada'
            elif campo_status_pausado(item):
                status_label = 'Pausada'
                status_class = 'status-pausada'
            elif campo_os_iniciada(item):
                status_label = 'Em andamento'
                status_class = 'status-andamento'
            else:
                status_label = status_raw or 'Aberta'
                status_class = 'status-andamento'

            rows.append({
                'id': item.get('id'),
                'numero_os': item.get('numero_os'),
                'numero_visivel': campo_numero_visivel(item, item.get('id')),
                'status': status_raw,
                'status_label': status_label,
                'status_class': status_class,
                'finalizada': 'Sim' if finalizada_bool else 'Não',
                'atrasada': bool(atrasada_bool),
                'acumulado_minutos': item.get('acumulado_minutos') or 0,
                'data_inicio': item.get('data_inicio') or '',
                'data_fim': item.get('data_fim') or '',
            })
        return jsonify({'ok': True, 'rows': rows})
    except Exception as exc:
        current_app.logger.exception('Falha ao buscar status das O.S.')
        return jsonify({'ok': False, 'rows': [], 'erro': str(exc)}), 200


@require_permission('view_os')
def api_os_historico(rid):
    """Retorna linha do tempo da O.S. a partir dos audit_logs."""
    if not owned_by_current_company('os_ordens', rid):
        return jsonify({'ok': False, 'error': 'não encontrado'}), 404

    # Busca a O.S. para pegar dados de criação
    os_row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,))) or {}
    eventos = []

    # Evento de criação — sempre mostra, mesmo sem criado_em
    criado_em = os_row.get('criado_em') or ''
    criador_log = row_to_dict(query_one(
        """SELECT usuario_nome FROM audit_logs
           WHERE entidade='os' AND entidade_id=? AND acao LIKE '%criar%'
           ORDER BY id ASC LIMIT 1""",
        (str(rid),)
    ))
    criador = (criador_log or {}).get('usuario_nome') or os_row.get('criado_por') or 'Sistema'
    eventos.append({
        'quando': criado_em or os_row.get('data') or '',
        'tipo': 'criacao',
        'icone': 'bi-plus-circle-fill',
        'cor': '#2563eb',
        'titulo': 'O.S. aberta',
        'detalhe': f'Criada por {criador}' + (f' em {criado_em}' if criado_em else ''),
        'usuario': criador
    })
    # Busca no audit_logs
    logs = [row_to_dict(r) for r in query_all(
        """SELECT * FROM audit_logs
           WHERE entidade='os' AND entidade_id=?
           ORDER BY id ASC LIMIT 100""",
        (str(rid),)
    )]

    tipo_map = {
        'iniciar': ('bi-play-circle-fill', '#2374d9', 'O.S. iniciada'),
        'pausar': ('bi-pause-circle-fill', '#f4bd19', 'O.S. pausada'),
        'retomar': ('bi-arrow-clockwise', '#2374d9', 'O.S. retomada'),
        'finalizar': ('bi-check-circle-fill', '#22a746', 'O.S. finalizada'),
        'os_save': ('bi-pencil-fill', '#6366f1', 'O.S. editada'),
    }

    for log in logs:
        endpoint = str(log.get('endpoint') or '').lower()
        acao = str(log.get('acao') or '').lower()
        quando = log.get('criado_em') or ''
        usuario = log.get('usuario_nome') or log.get('usuario_email') or 'Sistema'
        resultado = log.get('resultado') or ''

        tipo = 'os_save'
        if 'iniciar' in endpoint or 'iniciar' in acao:
            tipo = 'iniciar'
        elif 'pausar' in endpoint or 'pausar' in acao:
            tipo = 'pausar'
        elif 'retomar' in endpoint or 'retomar' in acao:
            tipo = 'retomar'
        elif 'finalizar' in endpoint or 'finalizar' in acao:
            tipo = 'finalizar'

        icone, cor, titulo = tipo_map.get(tipo, ('bi-pencil-fill', '#6366f1', 'O.S. editada'))

        # Tenta extrair detalhes do payload
        detalhe = ''
        try:
            payload = json.loads(log.get('detalhes') or '{}')
            if isinstance(payload, dict):
                partes = []
                if payload.get('status'):
                    partes.append(f"Status: {payload['status']}")
                if payload.get('motivo_pausa'):
                    partes.append(f"Motivo: {payload['motivo_pausa']}")
                if payload.get('responsavel'):
                    partes.append(f"Responsável: {payload['responsavel']}")
                detalhe = ' • '.join(partes)
        except Exception:
            pass

        eventos.append({
            'quando': quando,
            'tipo': tipo,
            'icone': icone,
            'cor': cor,
            'titulo': titulo,
            'detalhe': detalhe,
            'usuario': usuario,
            'resultado': resultado
        })

    # Eventos do campo_eventos
    campo_evs = [row_to_dict(r) for r in query_all(
        'SELECT * FROM campo_eventos WHERE os_id=? ORDER BY id ASC LIMIT 50', (rid,)
    )]
    campo_tipo_map = {
        'iniciar': ('bi-play-circle-fill', '#2374d9', 'Iniciada pelo técnico'),
        'pausar': ('bi-pause-circle-fill', '#f4bd19', 'Pausada pelo técnico'),
        'retomar': ('bi-arrow-clockwise', '#2374d9', 'Retomada pelo técnico'),
        'finalizar': ('bi-check-circle-fill', '#22a746', 'Finalizada pelo técnico'),
    }
    for ev in campo_evs:
        tipo = str(ev.get('tipo') or '').lower()
        icone, cor, titulo = campo_tipo_map.get(tipo, ('bi-phone-fill', '#6366f1', 'Atualização pelo app'))
        eventos.append({
            'quando': ev.get('criado_em') or '',
            'tipo': tipo,
            'icone': icone,
            'cor': cor,
            'titulo': titulo,
            'detalhe': ev.get('mensagem') or '',
            'usuario': 'App de campo'
        })

    # Ordena por data
    def _sort_key(e):
        from datetime import datetime
        try:
            return datetime.strptime(e['quando'], '%d/%m/%Y %H:%M:%S')
        except Exception:
            return datetime.min

    eventos.sort(key=_sort_key)
    return jsonify({'ok': True, 'eventos': eventos, 'os_id': rid})





@require_permission('view_os')
def api_os_detail(rid):
    """Retorna JSON com todos os campos da OS para o modal de detalhe."""
    where_sql, params = company_and('os_ordens')
    row = row_to_dict(query_one(
        f'SELECT * FROM os_ordens WHERE id=? {where_sql}',
        tuple([rid] + params)
    ))
    if not row:
        return jsonify({'ok': False, 'erro': 'O.S. não encontrada'}), 404
    return jsonify({
        'ok': True,
        'id': row.get('id') or rid,
        'teve_terceiro': row.get('teve_terceiro') or 'Não',
        'quem_foi_terceiro': row.get('quem_foi_terceiro') or '',
        'troca_componentes': row.get('troca_componentes') or 'Não',
        'componentes_descricao': row.get('componentes_descricao') or '',
        'servico_executado': row.get('servico_executado') or '',
        'campo_problema': row.get('campo_problema') or '',
        'campo_funcionando': row.get('campo_funcionando') or '',
        'campo_finalizado_em': row.get('campo_finalizado_em') or '',
        'status': row.get('status') or '',
        'finalizada': row.get('finalizada') or 'Não',
        'responsavel': row.get('responsavel') or '',
        'sistema': row.get('sistema') or '',
        'equipamento': row.get('equipamento') or '',
        'descricao': row.get('descricao') or '',
        'data': row.get('data') or '',
        'data_inicio': row.get('data_inicio') or '',
        'data_fim': row.get('data_fim') or '',
        'criticidade': row.get('criticidade') or '',
        'tipo_os': row.get('tipo_os') or '',
        'custo_os': row.get('custo_os') or '',
        'observacao_custo': row.get('observacao_custo') or '',
        'motivo_pausa': row.get('motivo_pausa') or '',
        'motivo_atraso': row.get('motivo_atraso') or '',
        'acumulado_minutos': row.get('acumulado_minutos') or 0,
    })




@require_permission('view_os')
def os_save():
    rid = request.form.get('id') or None
    if rid and not user_has('edit_os'):
        flash('Você não tem permissão para editar O.S.', 'danger')
        return _redirect_pos_os()
    if not rid and not user_has('create_os'):
        flash('Você não tem permissão para criar O.S.', 'danger')
        return _redirect_pos_os()
    image_files = request.files.getlist('imagens') if user_has('upload_os_photos') or user_has('edit_os') else []
    orcamento_files = request.files.getlist('orcamentos') if user_has('upload_budget_files') else []
    saved_id = save_os(request.form, image_files, orcamento_files, rid)
    backup_company_data(current_company_id())
    clear_view_cache()

    # WhatsApp: aceita vários nomes de botão/campo para não depender de um HTML específico.
    submit_values = ' '.join(str(v or '') for v in request.form.values()).lower()
    enviar_auto = (
        str(request.form.get('enviar_whatsapp_auto') or '').strip().lower() in ('1', 'on', 'sim', 'true', 'yes')
        or str(request.form.get('enviar_whatsapp') or '').strip().lower() in ('1', 'on', 'sim', 'true', 'yes')
        or str(request.form.get('whatsapp') or '').strip().lower() in ('1', 'on', 'sim', 'true', 'yes')
        or 'whatsapp' in submit_values
    )
    if enviar_auto and saved_id:
        row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (saved_id,))) or {}
        tecnico = campo_tecnico_for_os_row(row)
        if tecnico.get('telefone'):
            flash('O.S. salva. Abrindo WhatsApp do técnico selecionado.', 'success')
            return redirect(url_for('campo_whatsapp', rid=saved_id))
        flash('O.S. salva. Abrindo aviso para a equipe de campo.', 'success')
        return redirect(url_for('campo_whatsapp_equipe', rid=saved_id))

    flash('O.S. salva.', 'success')
    return _redirect_pos_os()



def os_imagem_visualizar(rid, idx):
    """Mostra foto da O.S. sem depender cegamente da URL pública do Supabase.

    - Se o arquivo ainda estiver local, entrega local.
    - Se estiver no Supabase, redireciona para a URL pública correta.
    - No link público do técnico, aceita o token da O.S. em ?token=.
    """
    row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,))) or {}
    if not row:
        return missing_attachment_response('foto')

    token = request.args.get('token') or ''
    empresa_id = row.get('empresa_id') or 0
    token_ok = bool(token) and hmac.compare_digest(str(token), campo_token_for(rid, empresa_id))
    logged_ok = False
    try:
        logged_ok = bool(session.get('user_id')) and owned_by_current_company('os_ordens', rid)
    except Exception:
        logged_ok = False
    if not token_ok and not logged_ok:
        return ('Acesso não autorizado.', 403)

    row = sync_os_attachments(row, persist_db=True)
    imagens = list(row.get('imagens') or [])
    if idx < 0 or idx >= len(imagens):
        return missing_attachment_response('foto')
    stored = imagens[idx]
    return storage_or_local_response(
    stored,
    as_attachment=False,
    download_name=Path(
        normalize_storage_path(
            stored,
            kind='os',
            empresa_id=empresa_id
        )
    ).name or f'foto_os_{rid}_{idx+1}',
    kind='os',
    empresa_id=empresa_id
)




@require_permission('view_budget_files')
def os_orcamento_download(rid, idx):
    row = sync_os_attachments(row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,))) or {}, persist_db=True)
    orcamentos = list(row.get('orcamentos') or [])
    if idx < 0 or idx >= len(orcamentos):
        flash('Orçamento não encontrado.', 'danger')
        return redirect(url_for('os_page'))
    stored = orcamentos[idx]
    return storage_or_local_response(stored, as_attachment=True, download_name=Path(normalize_storage_path(stored)).name or 'orcamento')





@require_permission('edit_os')
def api_os_attachment_delete():
    payload = request.get_json(silent=True) or {}
    rid = payload.get('id')
    kind = str(payload.get('kind') or '').strip().lower()
    idx = payload.get('index')
    if not str(rid).isdigit() or kind not in ('imagens', 'orcamentos') or not str(idx).lstrip('-').isdigit():
        return jsonify({'ok': False, 'error': 'Parâmetros inválidos.'}), 400
    rid = int(rid)
    idx = int(idx)
    row = sync_os_attachments(row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,))) or {}, persist_db=True)
    if not row or not owned_by_current_company('os_ordens', rid):
        return jsonify({'ok': False, 'error': 'O.S. não encontrada.'}), 404
    try:
        arquivos = row.get(kind) if isinstance(row.get(kind), list) else json.loads(row.get(kind) or '[]')
        arquivos = list(arquivos or [])
    except Exception:
        arquivos = []
    if idx < 0 or idx >= len(arquivos):
        return jsonify({'ok': False, 'error': 'Anexo não encontrado.'}), 404
    removido = arquivos.pop(idx)
    execute(f'UPDATE os_ordens SET {kind}=? WHERE id=?', (json.dumps(arquivos, ensure_ascii=False), rid))
    try:
        full = resolve_os_upload_path(removido)
        if full and full.exists() and full.is_file():
            full.unlink(missing_ok=True)
    except Exception:
        pass
    clear_view_cache()
    refreshed = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,))) or {}
    try:
        imagens = json.loads(refreshed.get('imagens') or '[]')
    except Exception:
        imagens = []
    try:
        orcamentos = json.loads(refreshed.get('orcamentos') or '[]')
    except Exception:
        orcamentos = []
    return jsonify({'ok': True, 'imagens': imagens, 'orcamentos': orcamentos})


@require_permission('generate_pdf')
def os_pdf_individual(rid):
    where_sql, params = company_and('os_ordens')
    row = query_one('SELECT * FROM os_ordens WHERE id=?' + where_sql, tuple([rid] + params))
    if not row:
        flash('O.S. não encontrada.', 'danger')
        return redirect(url_for('os_page'))
    row = sync_os_attachments(row_to_dict(row) or {}, persist_db=True)
    numero_pdf = row_to_dict(row).get('numero_os') or rid
    return send_file(
        _build_os_pdf([row], titulo='RDO - ORDEM DE SERVIÇO', subtitulo=f'O.S.: {numero_pdf}'),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'os_{numero_pdf}.pdf',
    )


@require_permission('download_os')
def os_download_pacote(rid):
    where_sql, params = company_and('os_ordens')
    raw_row = query_one('SELECT * FROM os_ordens WHERE id=?' + where_sql, tuple([rid] + params))
    row = sync_os_attachments(row_to_dict(raw_row) or {}, persist_db=True)
    if not row:
        flash('O.S. não encontrada.', 'danger')
        return redirect(url_for('os_page'))
    zip_buf = io.BytesIO()
    pdf_buf = _build_os_pdf([row], titulo='RDO - ORDEM DE SERVIÇO', subtitulo=f'O.S.: {rid}')
    pdf_buf.seek(0)
    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f'OS_{rid}.pdf', pdf_buf.read())
        for i, stored in enumerate(row.get('orcamentos') or [], start=1):
            data, name = (stored)
            if data:
                zf.writestr(f'orcamentos/{i:02d}_{name}', data)
    zip_buf.seek(0)
    return send_file(zip_buf, mimetype='application/zip', as_attachment=True, download_name=f'OS_{rid}_pdf_e_orcamentos.zip')




@require_permission('edit_os')
def os_action(action, rid):
    hora = br_now().strftime('%H:%M')
    where_sql, params = company_and('os_ordens')
    atual = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?' + where_sql, tuple([rid] + params))) or {}
    if not atual:
        flash('O.S. não encontrada na unidade ativa.', 'danger')
        return redirect(url_for('os_page'))
    acumulado = int(atual.get('acumulado_minutos') or 0)
    inicio_atual = only_time_str(atual.get('data_inicio'))
    if action == 'iniciar':
        # reinicia a contagem do trecho atual sem apagar o acumulado anterior
        execute('UPDATE os_ordens SET data_inicio=?, status=?, finalizada=?, data_fim=? WHERE id=?', (hora if str(atual.get('status') or '').strip().lower() == 'pausada' else (inicio_atual or hora), 'Em andamento', 'Não', '', rid))
    elif action == 'pausar':
        if inicio_atual:
            acumulado += time_diff_minutes(inicio_atual, hora) or 0
        motivo_pausa = str(request.form.get('motivo_pausa') or '').strip()
        execute('UPDATE os_ordens SET status=?, finalizada=?, data_fim=?, acumulado_minutos=?, motivo_pausa=? WHERE id=?', ('Pausada', 'Não', hora, acumulado, motivo_pausa, rid))
    elif action == 'justificar_atraso':
        motivo_atraso = str(request.form.get('motivo_atraso') or '').strip()
        execute('UPDATE os_ordens SET motivo_atraso=? WHERE id=?', (motivo_atraso, rid))
    elif action == 'finalizar':
        if str(atual.get('status') or '').strip().lower() != 'pausada' and inicio_atual:
            acumulado += time_diff_minutes(inicio_atual, hora) or 0
        execute('UPDATE os_ordens SET data_inicio=?, data_fim=?, status=?, finalizada=?, acumulado_minutos=? WHERE id=?', (inicio_atual or hora, hora, 'Finalizada', 'Sim', acumulado, rid))
    clear_view_cache()
    flash(f'O.S. {action} com sucesso.', 'success')
    return redirect(url_for('os_page'))





def _redirect_pos_os():
    """Redireciona para o app mobile se veio do celular, senão para O.S. desktop."""
    if is_mobile_request() and session.get('user_id'):
        return redirect(url_for('gestor_app'))
    return redirect(url_for('os_page'))




def register_routes(app):
    rules = [
        ('/os/ativos', 'os_ativos', os_ativos, ['GET']),
        ('/os/ativos/save', 'os_ativos_save', os_ativos_save, ['POST']),
        ('/os', 'os_redirect', os_redirect, ['GET']),
        ('/os/lancamentos', 'os_lancamentos', os_lancamentos, ['GET']),
        ('/os/lista', 'os_page', os_page, ['GET']),
        ('/api/os/paradas', 'os_paradas', os_paradas, ['GET']),
        ('/os/hub', 'os_hub', os_hub, ['GET']),
        ('/os/kanban', 'os_kanban', os_kanban, ['GET']),
        ('/os/tecnicos', 'os_tecnicos', os_tecnicos, ['GET']),
        ('/os/relatorios', 'os_relatorios', os_relatorios, ['GET']),
        ('/api/os/status-updates', 'api_os_status_updates', api_os_status_updates, ['GET']),
        ('/api/os/<int:rid>', 'api_os_detail', api_os_detail, ['GET']),
        ('/api/os/<int:rid>/historico', 'api_os_historico', api_os_historico, ['GET']),
        ('/os/save', 'os_save', os_save, ['POST']),
        ('/os/imagem/<int:rid>/<int:idx>', 'os_imagem_visualizar', os_imagem_visualizar, ['GET']),
        ('/os/orcamento/<int:rid>/<int:idx>', 'os_orcamento_download', os_orcamento_download, ['GET']),
        ('/api/os/attachment/delete', 'api_os_attachment_delete', api_os_attachment_delete, ['POST']),
        ('/os/pdf/<int:rid>', 'os_pdf_individual', os_pdf_individual, ['GET']),
        ('/os/download/<int:rid>', 'os_download_pacote', os_download_pacote, ['GET']),
        ('/os/<action>/<int:rid>', 'os_action', os_action, ['POST']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
