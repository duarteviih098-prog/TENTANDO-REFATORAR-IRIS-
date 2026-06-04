"""Regras de negócio do módulo O.S."""
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

import json
import os
import re
import threading
from app.auth import owned_by_current_company, user_has
from app.auth.decorators import is_mobile_request
from app.campo.push import _ensure_push_subscriptions_table, _send_push
from app.shared.cache import clear_view_cache
from app.shared.constants import SISTEMAS_E_EQUIPAMENTOS
from app.shared.formatters import br_money, br_now, elapsed_label, now_str, only_time_str, parse_br_date, parse_num, time_diff_minutes
from app.shared.months import normalize_month_reference
from app.shared.queries import fetch_sistemas_map, list_page, reset_sqlite_sequence_if_empty
from app.shared.rows import row_get_value, row_matches_month, row_to_dict
from app.storage import backup_company_data

from app.db.schema import _TABLE_COLUMN_CACHE, _TABLE_COLUMNS_CACHE
from app.storage.attachments import normalize_os_attachment_list, save_os_files
from app.auth import get_current_user



def prepare_os_row_for_template(row):
    """Prepara uma O.S. para HTML/mobile sem depender de JSON cru."""
    if not row:
        return row
    row = dict(row)
    try:
        imagens = row.get('imagens') if isinstance(row.get('imagens'), list) else json.loads(row.get('imagens') or '[]')
    except Exception:
        imagens = []
    try:
        orcamentos = row.get('orcamentos') if isinstance(row.get('orcamentos'), list) else json.loads(row.get('orcamentos') or '[]')
    except Exception:
        orcamentos = []
    row['imagens_lista'] = [x for x in imagens if str(x or '').strip()]
    row['orcamentos_lista'] = [x for x in orcamentos if str(x or '').strip()]
    try:
        row['tempo_decorrido'] = elapsed_label(row.get('data_inicio'), row.get('data_fim'), row.get('acumulado_minutos'), running=str(row.get('status') or '').strip().lower() == 'em andamento')
    except Exception:
        row['tempo_decorrido'] = ''
    return row











def ensure_os_tipo_os_column():
    """Garante o campo usado só no sistema para classificar a O.S. como Corretiva ou Preventiva.

    Não entra no PDF. É apenas para modal/tela e gráficos do dashboard.
    """
    try:
        if not table_has_column('os_ordens', 'tipo_os'):
            execute('ALTER TABLE os_ordens ADD COLUMN tipo_os TEXT')
            try:
                _TABLE_COLUMN_CACHE.pop(('os_ordens', 'tipo_os'), None)
                _TABLE_COLUMNS_CACHE.pop('os_ordens', None)
            except Exception:
                pass
        return True
    except Exception as exc:
        print('ensure_os_tipo_os_column falhou:', exc)
        return False


















def attach_os_display_numbers(ordens):
    # IMPORTANTE: não reordena aqui.
    # A lista já deve chegar na ordem correta (data/hora/id).
    # Antes esta função ordenava por ID e quebrava o PDF mensal,
    # fazendo dias mais novos aparecerem antes de dias antigos.
    itens = [dict(o) for o in (ordens or [])]
    for idx, item in enumerate(itens, start=1):
        item['numero_os'] = idx
        item['display_numero_os'] = idx
    return itens






def os_is_overdue(row, ref_date=None):
    ref_date = ref_date or br_now().date()
    data = parse_br_date(str(row.get('data') or ''))
    if not data:
        return False
    started = bool(only_time_str(row.get('data_inicio')))
    finished = str(row.get('finalizada') or '').strip().lower() == 'sim'
    return (data.date() < ref_date) and (not started) and (not finished)




def save_ativo(data, rid=None):
    fields = ['nome','tipo','local','descricao','status','criado_em','sistema','equipamento','empresa_id']
    payload = {k:data.get(k,'') for k in fields}
    payload['status'] = (payload.get('status') or 'Não').strip().title()
    payload['criado_em'] = payload['criado_em'] or now_str()
    payload['empresa_id'] = current_company_id()
    vals = [payload.get(k,'') for k in fields]
    if rid:
        execute(f"UPDATE os_ativos SET {','.join(f'{f}=?' for f in fields)} WHERE id=?", vals+[rid])
    else:
        execute(f"INSERT INTO os_ativos({','.join(fields)}) VALUES ({','.join('?'*len(fields))})", vals)




def normalize_os_system_name(value):
    """Padroniza nomes de sistema para evitar duplicidade visual tipo 'porto alegre' x 'Sistema Porto Alegre'."""
    txt = re.sub(r'\s+', ' ', str(value or '').strip())
    if not txt:
        return ''
    for known in SISTEMAS_E_EQUIPAMENTOS.keys():
        if known.strip().lower() == txt.lower():
            return known.strip()
    return txt.title()





def proximo_numero_os(empresa_id=None):
    """Numeração sequencial por mês — reseta todo mês primeiro dia."""
    try:
        mes_atual = br_now().strftime('%m/%Y')
        if empresa_id:
            row = query_one(
                """SELECT MAX(CAST(numero_os AS INTEGER)) AS n FROM os_ordens
                   WHERE empresa_id=? AND TRIM(COALESCE(numero_os,''))!=''
                   AND (data LIKE ? OR criado_em LIKE ?)""",
                (empresa_id, f'%/{br_now().year}', f'{br_now().strftime("%m/%Y")}%')
            )
            # Fallback: pega pelo campo mes se nenhum com data do mês
            if not row or not (row or {}).get('n'):
                row = query_one(
                    "SELECT MAX(CAST(numero_os AS INTEGER)) AS n FROM os_ordens WHERE empresa_id=? AND TRIM(COALESCE(numero_os,''))!='' AND COALESCE(mes_os,'')=?",
                    (empresa_id, mes_atual)
                )
        else:
            row = query_one(
                "SELECT MAX(CAST(numero_os AS INTEGER)) AS n FROM os_ordens WHERE TRIM(COALESCE(numero_os,''))!='' AND (data LIKE ? OR criado_em LIKE ?)",
                (f'%/{br_now().year}', f'{br_now().strftime("%m/%Y")}%')
            )
        return str(int((row or {}).get('n') or 0) + 1)
    except Exception:
        try:
            row = query_one('SELECT COUNT(*) AS n FROM os_ordens WHERE (? IS NULL OR empresa_id=?)', (empresa_id, empresa_id))
            return str(int((row or {}).get('n') or 0) + 1)
        except Exception:
            return '1'




def renumerar_os_por_mes(empresa_id=None):
    """Renumera todas as OS existentes sequencialmente por mês. Chamado uma vez."""
    try:
        where = 'WHERE empresa_id=?' if empresa_id else 'WHERE 1=1'
        params = (empresa_id,) if empresa_id else ()
        rows = query_all(
            f"SELECT id, data, criado_em FROM os_ordens {where} ORDER BY id ASC",
            params
        )
        # Agrupa por mês
        from collections import defaultdict
        por_mes = defaultdict(list)
        for r in rows:
            data = row_get_value(r, 'data', '') or row_get_value(r, 'criado_em', '') or ''
            # Extrai mm/yyyy
            import re as _re
            m = _re.search(r'(\d{1,2})/(\d{4})', str(data))
            if m:
                mes_key = f"{int(m.group(1)):02d}/{m.group(2)}"
            else:
                mes_key = '00/0000'
            por_mes[mes_key].append(row_get_value(r, 'id'))
        # Renumera
        for mes_key in sorted(por_mes.keys()):
            for idx, os_id in enumerate(por_mes[mes_key], 1):
                execute('UPDATE os_ordens SET numero_os=? WHERE id=?', (str(idx), os_id))
        print(f'Renumeração concluída: {len(rows)} OS em {len(por_mes)} meses')
        return True
    except Exception as exc:
        print(f'Renumeração falhou: {exc}')
        return False




def save_os(data, image_files=None, orcamento_files=None, rid=None):
    existing = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (rid,))) if rid else None

    def _existing_json_list_safe(value):
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if value in (None, ''):
            return []
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []

    imagens = normalize_os_attachment_list(_existing_json_list_safe(existing.get('imagens')) if existing else [], prefix='foto_os')
    orcamentos = normalize_os_attachment_list(_existing_json_list_safe(existing.get('orcamentos')) if existing else [], prefix='orcamento_os')
    imagens.extend(save_os_files(image_files, 'foto_os'))
    orcamentos.extend(save_os_files(orcamento_files, 'orcamento_os'))
    ativo_nome = ''
    ativo_id = data.get('ativo_id') or None
    if ativo_id:
        r = query_one('SELECT nome FROM os_ativos WHERE id=?', (ativo_id,))
        ativo_nome = r['nome'] if r else ''
    ensure_os_tipo_os_column()
    fields = ['numero_os','data','ativo_id','ativo_nome','tipo','tipo_os','status','finalizada','criticidade','descricao','data_inicio','data_fim','responsavel','servico_executado','criado_em','sistema','equipamento','imagens','orcamentos','teve_terceiro','quem_foi_terceiro','troca_componentes','componentes_descricao','custo_os','observacao_custo','acumulado_minutos','empresa_id']
    payload = {k:data.get(k,'') for k in fields}
    tipo_os_raw = str(data.get('tipo_os') or (existing or {}).get('tipo_os') or '').strip().title()
    payload['tipo_os'] = 'Corretiva' if tipo_os_raw == 'Corretiva' else ('Preventiva' if tipo_os_raw == 'Preventiva' else '')
    payload['sistema'] = normalize_os_system_name(payload.get('sistema',''))
    payload['equipamento'] = payload.get('equipamento','')
    troca_raw = str(data.get('troca_componentes') or payload.get('troca_componentes') or 'Não').strip().lower()
    payload['troca_componentes'] = 'Sim' if troca_raw in ('sim', 's', 'yes', 'true', '1', 'on') else 'Não'
    payload['componentes_descricao'] = (data.get('componentes_descricao') or data.get('descricao_componentes') or payload.get('componentes_descricao') or '').strip()
    if payload['troca_componentes'] != 'Sim':
        payload['componentes_descricao'] = ''
    payload['custo_os'] = (data.get('custo_os') or payload.get('custo_os') or '').strip()
    payload['observacao_custo'] = (data.get('observacao_custo') or data.get('obs_custo') or payload.get('observacao_custo') or '').strip()
    payload['tipo'] = ''
    payload['ativo_id'] = ativo_id
    payload['ativo_nome'] = ''
    payload['criado_em'] = payload['criado_em'] or (existing.get('criado_em') if existing else now_str())
    payload['imagens'] = json.dumps(imagens, ensure_ascii=False)
    payload['orcamentos'] = json.dumps(orcamentos, ensure_ascii=False)
    payload['empresa_id'] = current_company_id()
    payload['numero_os'] = (data.get('numero_os') or (existing or {}).get('numero_os') or '').strip()
    if not payload['numero_os']:
        payload['numero_os'] = proximo_numero_os(payload['empresa_id'])
    payload['data'] = payload.get('data') or br_now().strftime('%d/%m/%Y')
    payload['data_inicio'] = only_time_str(payload.get('data_inicio'))
    payload['data_fim'] = only_time_str(payload.get('data_fim'))
    existing_finalizada = (existing or {}).get('finalizada', 'Não')
    finalizada = str(data.get('finalizada') or existing_finalizada or 'Não').strip().title()
    iniciar_agora = str(data.get('iniciar_agora') or '').strip().lower() in ('1','on','sim','true','yes')
    agora_hora = br_now().strftime('%H:%M')
    acumulado = int((existing or {}).get('acumulado_minutos') or 0)
    if iniciar_agora and not payload['data_inicio']:
        payload['data_inicio'] = agora_hora
        if finalizada != 'Sim':
            payload['status'] = 'Em andamento'
    existing_status = (existing or {}).get('status', '')
    status_informado = str(data.get('status') or existing_status or '').strip()
    _st = status_informado.lower()
    if _st in ('em andamento','andamento','iniciada','iniciado'):
        status_informado = 'Em andamento'
    elif _st in ('finalizada','finalizado','entregue'):
        status_informado = 'Finalizada'
    elif _st == 'pausada':
        status_informado = 'Pausada'
    elif _st in ('atrasada','em atraso'):
        status_informado = 'Atrasada'
    manual_minutes = None
    manual_finish_informed = bool(payload['data_inicio'] and payload['data_fim'])
    if manual_finish_informed:
        manual_minutes = time_diff_minutes(payload['data_inicio'], payload['data_fim'])
    if manual_minutes is not None:
        acumulado = manual_minutes
    payload['acumulado_minutos'] = acumulado
    # se o usuário informou manualmente início e fim, tratamos como encerrada para respeitar o ajuste manual
    if manual_finish_informed and finalizada != 'Sim':
        finalizada = 'Sim'
    if finalizada == 'Sim':
        payload['finalizada'] = 'Sim'
        payload['status'] = 'Finalizada'
        if not str(payload.get('data_fim') or '').strip():
            payload['data_fim'] = agora_hora
        if not str(payload.get('data_inicio') or '').strip():
            payload['data_inicio'] = agora_hora
        if payload['data_inicio'] and payload['data_fim']:
            payload['acumulado_minutos'] = time_diff_minutes(payload['data_inicio'], payload['data_fim']) or acumulado
    else:
        payload['finalizada'] = 'Não'
        if status_informado:
            payload['status'] = status_informado
        elif payload['data_inicio']:
            payload['status'] = 'Em andamento'
        else:
            payload['status'] = 'Aberta'
        if payload['status'] == 'Finalizada':
            payload['status'] = 'Em andamento'
        # se usuário digitou data_fim manualmente, preserva; se não, deixa vazio em andamento
        if payload['status'] in ('Em andamento', 'Aberta') and not payload['data_fim']:
            payload['data_fim'] = ''
    vals = [payload.get(k,'') for k in fields]
    if rid:
        execute(f"UPDATE os_ordens SET {','.join(f'{f}=?' for f in fields)} WHERE id=?", vals+[rid])
        return int(rid)
    else:
        reset_sqlite_sequence_if_empty('os_ordens')
        # Salva quem criou
        try:
            u = get_current_user() or {}
            if u.get('nome'):
                ensure_column('os_ordens', 'criado_por', "TEXT DEFAULT ''")
                payload['criado_por'] = u.get('nome', '')
                if 'criado_por' not in fields:
                    fields.append('criado_por')
                    vals.append(u.get('nome', ''))
        except Exception:
            pass
        novo_id = execute(f"INSERT INTO os_ordens({','.join(fields)}) VALUES ({','.join('?'*len(fields))})", vals)
        novo_id = int(novo_id or 0)
        # Dispara push notification para técnicos quando OS nova é criada
        if novo_id:
            try:
                _push_nova_os_async(novo_id, dict(zip(fields, vals)))
            except Exception as exc:
                print('Push nova OS falhou (não crítico):', exc)
        return novo_id




