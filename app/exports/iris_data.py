"""Coleta e agregação de dados para relatórios exportados."""
import re
from app.shared.formatters import br_money, br_now, now_str, parse_num
from app.shared.rows import row_get_value, row_to_dict

from app.auth.constants import TENANT_TABLES

def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def current_company():
    from app.auth import current_company as fn
    return fn()


def current_user_is_super_admin():
    from app.auth import current_user_is_super_admin as fn
    return fn()


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)


def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)


def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)


def table_columns(table):
    from app.db import table_columns as fn
    return fn(table)


def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)


def select_existing_columns(table, desired, fallback='id'):
    from app.db.schema import select_existing_columns as fn
    return fn(table, desired, fallback=fallback)


def ensure_column(table, column, col_type):
    from app.db import ensure_column as fn
    return fn(table, column, col_type)


def _iris_normalize(text):
    text = str(text or '').strip()
    repl = {
        'á':'a','à':'a','ã':'a','â':'a','ä':'a',
        'é':'e','ê':'e','è':'e','ë':'e',
        'í':'i','ì':'i','î':'i','ï':'i',
        'ó':'o','ò':'o','õ':'o','ô':'o','ö':'o',
        'ú':'u','ù':'u','û':'u','ü':'u',
        'ç':'c'
    }
    low = text.lower()
    for a,b in repl.items():
        low = low.replace(a,b)
    low = re.sub(r'\s+', ' ', low).strip()
    return low



def _iris_parse_br_float(value):
    try:
        return parse_num(value)
    except Exception:
        txt = str(value or '').replace('R$', '').strip()
        if ',' in txt:
            txt = txt.replace('.', '').replace(',', '.')
        try: return float(txt)
        except Exception: return 0.0



def _iris_rows(table, where='', params=(), order='id DESC', limit=500, global_scope=False):
    """Linhas usadas pela Iris/relatórios SEM vazar dados entre unidades.

    Por padrão, toda tabela multiempresa recebe filtro pela unidade ativa.
    Só uma tela global explícita de Administrador Supremo deve usar global_scope=True.
    """
    sql = f"SELECT * FROM {table}"
    clauses = []
    all_params = []
    if where:
        clauses.append(f"({where})")
        all_params.extend(list(params or ()))
    if (not global_scope) and table in TENANT_TABLES and table_has_column(table, 'empresa_id'):
        empresa_id = current_company_id()
        if empresa_id:
            clauses.append('empresa_id=?')
            all_params.append(empresa_id)
        else:
            clauses.append('empresa_id IS NULL')
    if clauses:
        sql += ' WHERE ' + ' AND '.join(clauses)
    if order:
        sql += " ORDER BY " + order
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [row_to_dict(r) for r in query_all(sql, tuple(all_params))]



def _iris_month_number_from_text(value):
    t = _iris_normalize(value)
    aliases = {
        '01': ['01','1','janeiro','jan'],
        '02': ['02','2','fevereiro','fev'],
        '03': ['03','3','marco','mar'],
        '04': ['04','4','abril','abr'],
        '05': ['05','5','maio','mai'],
        '06': ['06','6','junho','jun'],
        '07': ['07','7','julho','jul'],
        '08': ['08','8','agosto','ago'],
        '09': ['09','9','setembro','set'],
        '10': ['10','outubro','out'],
        '11': ['11','novembro','nov'],
        '12': ['12','dezembro','dez'],
    }
    for num, names in aliases.items():
        for name in names:
            if re.search(rf'(^|\b|/|-){re.escape(name)}($|\b|/|-)', t):
                return num
    return ''



def _iris_match_month(row, month_ref, *fields):
    # Aceita 04/2026, ABRIL, abril/2026 e datas completas.
    # O erro anterior era comparar apenas '04/2026'; pagamentos importados como
    # 'ABRIL' ficavam fora da conta.
    if not month_ref:
        return True
    month_num = ''
    year_ref = ''
    try:
        month_num, year_ref = str(month_ref).split('/')
        month_num = f'{int(month_num):02d}'
    except Exception:
        month_num = _iris_month_number_from_text(month_ref)
    for f in fields:
        val = str(row.get(f) or '').strip()
        if not val:
            continue
        val_norm = _iris_normalize(val)
        if val.endswith(month_ref) or val == month_ref:
            return True
        parsed = parse_br_date(val)
        if parsed and parsed.strftime('%m/%Y') == month_ref:
            return True
        # mês escrito por extenso: ABRIL, abril, abr, etc.
        val_month = _iris_month_number_from_text(val_norm)
        if month_num and val_month == month_num:
            # Se o campo tem ano, ele precisa bater. Se não tem ano, assumimos o ano do recorte atual.
            year_in_val = re.search(r'(20\d{2})', val_norm)
            if (not year_in_val) or (not year_ref) or year_in_val.group(1) == year_ref:
                return True
    return False



def _iris_payment_is_approved(row):
    # No módulo de pagamentos, dinheiro real/aprovado vem tanto em status quanto em aprovado/fluxo.
    joined = _iris_normalize(' '.join(str(row.get(k) or '') for k in ['status','aprovado','fluxo_status','acao']))
    if any(x in joined for x in ['cancelado','reprovado','negado','excluido']):
        return False
    return any(x in joined for x in ['sim','pago','paga','ok','realizado','confirmado','aprovado','pronto para enviar','executado'])



def _iris_official_finance(month_ref='', include_orphans=True):
    """Fonte única de verdade para Iris e PDF mensal.

    Regra da Vi: gasto = pagamentos aprovados + combustível.
    O.S. e Custos NÃO entram no gasto para não duplicar realocações.
    
    `include_orphans=True` inclui pagamentos sem mês quando o recorte é mensal,
    porque a tela de Dashboard atual contabiliza esses lançamentos no total da unidade.
    """
    pagamentos_all = _iris_rows('pagamentos', limit=5000)
    combustivel_all = _iris_rows('combustivel', limit=5000)
    if month_ref:
        pagamentos_month = [r for r in pagamentos_all if _iris_match_month(r, month_ref, 'pagamento_mes')]
        if include_orphans:
            pagamentos_month += [r for r in pagamentos_all if not str(r.get('pagamento_mes') or '').strip() and r not in pagamentos_month]
        combustivel_month = [r for r in combustivel_all if _iris_match_month(r, month_ref, 'mes_ref', 'data')]
    else:
        pagamentos_month = pagamentos_all
        combustivel_month = combustivel_all
    pagamentos_aprovados = [r for r in pagamentos_month if _iris_payment_is_approved(r)]
    pagamentos_total = sum(_iris_parse_br_float(r.get('valor')) for r in pagamentos_aprovados)
    combustivel_total = sum(_iris_parse_br_float(r.get('custo')) for r in combustivel_month)
    return {
        'pagamentos': pagamentos_aprovados,
        'pagamentos_total': pagamentos_total,
        'combustivel_rows': combustivel_month,
        'combustivel_total': combustivel_total,
        'gasto_total': pagamentos_total + combustivel_total,
        'pagamentos_count': len(pagamentos_aprovados),
        'combustivel_count': len(combustivel_month),
    }



def _iris_payment_status(row):
    status = _iris_normalize(row.get('status'))
    fluxo = _iris_normalize(row.get('fluxo_status'))
    if 'pago' in status or 'pago' in fluxo or 'efetuado' in fluxo or 'concluido' in fluxo:
        return 'Pago'
    return 'Em aberto'



def _iris_collect_context(month_ref=''):
    pagamentos = _iris_rows('pagamentos', limit=1000)
    os_rows = _iris_rows('os_ordens', limit=1000)
    custos = _iris_rows('custos', limit=1000)
    combustivel = _iris_rows('combustivel', limit=1000)

    if month_ref:
        pagamentos = [r for r in pagamentos if _iris_match_month(r, month_ref, 'pagamento_mes')]
        os_rows = [r for r in os_rows if _iris_match_month(r, month_ref, 'data', 'criado_em')]
        custos = [r for r in custos if _iris_match_month(r, month_ref, 'mes')]
        combustivel = [r for r in combustivel if _iris_match_month(r, month_ref, 'mes_ref', 'data')]

    # Fonte única de verdade: gasto = pagamentos aprovados + combustível.
    # O.S. e custos são alocação interna e NÃO entram no gasto.
    finance = _iris_official_finance(month_ref)
    total_pag = finance['pagamentos_total']
    combustivel_total = finance['combustivel_total']
    pagamentos = finance['pagamentos']
    combustivel = finance['combustivel_rows']
    pago = total_pag
    aberto_rows = [r for r in pagamentos if _iris_payment_status(r) != 'Pago']
    aberto = sum(_iris_parse_br_float(r.get('valor')) for r in aberto_rows)

    by_system_os = {}
    by_unit_os = {}
    by_system_os_cost = {}
    component_by_system = {}
    os_custo_total = 0.0
    for r in os_rows:
        sys = (r.get('sistema') or 'Não informado').strip() or 'Não informado'
        unit = (r.get('equipamento') or r.get('ativo_nome') or 'Não informado').strip() or 'Não informado'
        by_system_os[sys] = by_system_os.get(sys, 0) + 1
        by_unit_os[unit] = by_unit_os.get(unit, 0) + 1
        valor_os = _iris_parse_br_float(r.get('custo_os'))
        if valor_os:
            os_custo_total += valor_os
            by_system_os_cost[sys] = by_system_os_cost.get(sys, 0) + valor_os
        if _iris_normalize(r.get('troca_componentes') or r.get('componentes') or '') in ('sim','s','yes'):
            component_by_system[sys] = component_by_system.get(sys, 0) + 1

    by_system_cost = {}
    # Mantém este agrupamento para relatórios financeiros específicos de pagamentos,
    # mas NÃO usa em "quanto gastamos" porque inclui aberto/previsão.
    for p in pagamentos:
        sys = (p.get('sistema') or 'Não informado').strip() or 'Não informado'
        by_system_cost[sys] = by_system_cost.get(sys, 0) + _iris_parse_br_float(p.get('valor'))

    gasto_realizado_total = total_pag + combustivel_total

    return {
        'month_ref': month_ref,
        'pagamentos': pagamentos,
        'pagamentos_total': total_pag,
        'pagamentos_pago': pago,
        'pagamentos_aberto': aberto,
        'pagamentos_abertos_rows': aberto_rows,
        'combustivel_rows': combustivel,
        'combustivel_total': combustivel_total,
        'os_rows': os_rows,
        'custos_rows': custos,
        'os_total': len(os_rows),
        'os_custo_total': os_custo_total,
        'gasto_realizado_total': gasto_realizado_total,
        'by_system_os': sorted(by_system_os.items(), key=lambda x:x[1], reverse=True),
        'by_unit_os': sorted(by_unit_os.items(), key=lambda x:x[1], reverse=True),
        'by_system_os_cost': sorted(by_system_os_cost.items(), key=lambda x:x[1], reverse=True),
        'by_system_cost': sorted(by_system_cost.items(), key=lambda x:x[1], reverse=True),
        'component_by_system': sorted(component_by_system.items(), key=lambda x:x[1], reverse=True),
    }




def _iris_month_label(month_ref):
    if not month_ref:
        return 'período atual'
    meses = {'01':'janeiro','02':'fevereiro','03':'março','04':'abril','05':'maio','06':'junho','07':'julho','08':'agosto','09':'setembro','10':'outubro','11':'novembro','12':'dezembro'}
    try:
        mm, yyyy = str(month_ref).split('/')
        return f"{meses.get(mm, mm)} de {yyyy}"
    except Exception:
        return str(month_ref)

