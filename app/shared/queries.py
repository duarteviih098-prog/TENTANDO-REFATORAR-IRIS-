"""Queries compartilhadas (list_page, sistemas, IDs)."""
import json
import re

from app.db import USE_POSTGRES, execute, get_conn, query_one, table_columns
from app.db.schema import select_existing_columns
from app.shared.cache import cached_query_all, clear_view_cache
from app.shared.constants import SISTEMAS_E_EQUIPAMENTOS
from app.shared.rows import row_get_value, row_to_dict

def reset_sqlite_sequence_if_empty(table_name):
    if USE_POSTGRES:
        return
    table_name = str(table_name or '').strip()
    if not table_name:
        return
    count_row = query_one(f'SELECT COUNT(*) AS total FROM {table_name}')
    total = int(count_row['total']) if count_row else 0
    if total == 0:
        try:
            execute('DELETE FROM sqlite_sequence WHERE name=?', (table_name,))
        except Exception:
            pass

def fetch_sistemas_map():
    from app.auth import company_and

    sistemas = {k: list(v) for k, v in SISTEMAS_E_EQUIPAMENTOS.items()}
    conn = get_conn()
    try:
        for table in ['bombas', 'os_ativos', 'pagamentos', 'custos', 'os_ordens']:
            try:
                cols = [r['name'] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()]
                if 'sistema' in cols and 'equipamento' in cols:
                    tenant_sql, tenant_params = company_and(table)
                    rows = conn.execute(f"SELECT DISTINCT sistema, equipamento FROM {table} WHERE sistema != '' AND equipamento != ''{tenant_sql}", tuple(tenant_params)).fetchall()
                    for r in rows:
                        sistemas.setdefault(row_get_value(r, 'sistema', ''), [])
                        if row_get_value(r, 'equipamento', '') or row_get_value(r, 'ativo_nome', '') not in sistemas[row_get_value(r, 'sistema', '')]:
                            sistemas[row_get_value(r, 'sistema', '')].append(row_get_value(r, 'equipamento', '') or row_get_value(r, 'ativo_nome', ''))
            except Exception:
                pass
    finally:
        conn.close()
    return dict(sorted(sistemas.items()))

def list_page(table, order='id DESC', limit=120):
    from app.auth import company_where, current_company_id

    """Lista registros de forma leve.

    No Supabase/Render, SELECT * sem limite deixa as abas lentas.
    Mantém compatibilidade com as telas existentes, mas carrega só a janela
    mais recente por padrão. Use limit=None quando realmente precisar tudo.
    """
    where_sql, params = company_where(table)
    fields_by_table = {
        'os_ordens': select_existing_columns('os_ordens', [
            'id','data','sistema','equipamento','status','finalizada','criticidade','responsavel',
            'data_inicio','data_fim','acumulado_minutos','troca_componentes','teve_troca_componentes',
            'componentes','componentes_descricao','descricao','servico_executado','orcamentos','imagens',
            'teve_terceiro','quem_foi_terceiro','custo_os','observacao_custo','empresa_id'
        ]),
        'pagamentos': select_existing_columns('pagamentos', [
            'id','fornecedor','descricao_servico','valor','status','nf_proposta','acao','pagamento_mes',
            'numero_documento','sc_pedido','aprovado','tipo_documento','fluxo_status',
            'anexos_orcamento','anexos_nf','anexos_boleto','empresa_id'
        ]),
        'os_ativos': select_existing_columns('os_ativos', 'id,nome,tipo,local,sistema,equipamento,status,descricao,empresa_id'),
    }
    fields = fields_by_table.get(table, '*')
    sql = f'SELECT {fields} FROM {table}{where_sql} ORDER BY {order}'
    params = list(params)
    if limit is not None:
        sql += ' LIMIT ?'
        params.append(int(limit))
    cache_key = f'list:{table}:{order}:{limit}:{current_company_id()}'
    return cached_query_all(cache_key, sql, tuple(params), ttl=60)

def safe_int_id(value):
    """Converte ID para inteiro positivo; qualquer lixo vira None."""
    try:
        text = str(value or '').strip()
        if not re.fullmatch(r'\d+', text):
            return None
        number = int(text)
        return number if number > 0 else None
    except Exception:
        return None

def _next_numeric_id_for_table(table, conn=None):
    """Próximo ID numérico seguro para tabelas antigas/importadas com ID quebrado."""
    table = str(table or '').strip()
    if table not in ('combustivel', 'custos', 'pagamentos'):
        return 1
    close_conn = False
    if conn is None:
        conn = get_conn()
        close_conn = True
    try:
        rows = conn.execute(f'SELECT id FROM {table}').fetchall()
        max_id = 0
        for row in rows or []:
            rid = safe_int_id(row_get_value(row, 'id', ''))
            if rid and rid > max_id:
                max_id = rid
        return max_id + 1
    finally:
        if close_conn:
            try:
                conn.close()
            except Exception:
                pass

def ensure_valid_ids_for_table(table):
    """Repara registros antigos/importados sem ID válido.

    Isso evita linha fantasma: não seleciona, não abre modal, não edita e não exclui.
    Mantém os dados antigos e só preenche um ID numérico real quando estiver vazio/quebrado.
    """
    table = str(table or '').strip()
    if table not in ('combustivel', 'custos'):
        return 0
    if 'id' not in table_columns(table):
        return 0

    conn = get_conn()
    fixed = 0
    try:
        if USE_POSTGRES:
            rows = conn.execute(
                f"SELECT ctid, id FROM {table} "
                "WHERE id IS NULL OR TRIM(id::text)='' OR id::text !~ '^[0-9]+$'"
            ).fetchall()
            for row in rows or []:
                new_id = _next_numeric_id_for_table(table, conn)
                conn.execute(f'UPDATE {table} SET id=? WHERE ctid=?', (new_id, row_get_value(row, 'ctid')))
                fixed += 1
            try:
                conn.commit()
            except Exception:
                pass
        else:
            rows = conn.execute(
                f"SELECT rowid AS _rowid, id FROM {table} "
                "WHERE id IS NULL OR TRIM(CAST(id AS TEXT))='' OR CAST(id AS TEXT) GLOB '*[^0-9]*'"
            ).fetchall()
            for row in rows or []:
                new_id = _next_numeric_id_for_table(table, conn)
                conn.execute(f'UPDATE {table} SET id=? WHERE rowid=?', (new_id, row_get_value(row, '_rowid')))
                fixed += 1
            conn.commit()

        if fixed:
            clear_view_cache()
        return fixed
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f'ensure_valid_ids_for_table({table}) falhou:', exc)
        return fixed
    finally:
        try:
            conn.close()
        except Exception:
            pass
