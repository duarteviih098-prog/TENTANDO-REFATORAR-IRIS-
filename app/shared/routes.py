"""Rotas compartilhadas: health, loading, intro e dashboard."""
import re
from datetime import timedelta
from pathlib import Path
from app.controle.services import fetch_bombas_counts
from app.db.schema import select_existing_columns
from app.os.services import ensure_os_tipo_os_column, os_is_overdue
from app.shared.cache import cached_result
from app.shared.formatters import br_money, br_now, parse_num
from app.shared.months import normalize_month_reference
from app.shared.payments import compute_payments_totals, payment_status_is_paid
from app.shared.queries import fetch_sistemas_map
from app.shared.rows import row_get_value, row_to_dict

from flask import render_template, request, send_from_directory, session

from app.auth.decorators import require_permission
from app.config import PROJECT_ROOT
from app.storage.paths import BASE_DIR


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)

def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)

def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)

def current_company_id():
    from app.auth import current_company_id as fn
    return fn()

def company_where(table, prefix=' WHERE '):
    from app.auth import company_where as fn
    return fn(table, prefix)

def health():
    return 'ok'

def favicon_root():
    from flask import current_app
    static_dir = Path(current_app.static_folder or (BASE_DIR / 'static'))
    for filename in ('favicon_iris.ico', 'favicon.ico', 'icon-192.png'):
        candidate = static_dir / filename
        if candidate.exists() and candidate.is_file():
            mimetype = 'image/vnd.microsoft.icon' if filename.endswith('.ico') else 'image/png'
            return send_from_directory(static_dir, filename, mimetype=mimetype, max_age=0)
    # Não deixa favicon derrubar página nem virar erro vermelho.
    return ('', 204)


def loading():
    return render_template('loading.html')


def campo_loading():
    return render_template('campo_loading.html')


def intro():
    return render_template('intro.html')


@require_permission('view_dashboard')
def dashboard():
    def _parse_periodo():
        """Resolve os parâmetros de período do request em (mes_inicio, mes_fim, modo, label)."""
        agora = br_now()
        periodo = (request.args.get('periodo') or '').strip().lower()
        mes_ini = normalize_month_reference(request.args.get('mes') or '')
        mes_fim = normalize_month_reference(request.args.get('mes_fim') or '')

        def _mes_rel(meses_atras):
            d = agora - timedelta(days=30 * meses_atras)
            return f"{d.month:02d}/{d.year:04d}"

        if periodo == 'tudo':
            return '', '', 'tudo', 'Tudo'
        if periodo == 'ano':
            ini = f"01/{agora.year:04d}"
            fim = f"{agora.month:02d}/{agora.year:04d}"
            return ini, fim, 'ano', f"Ano {agora.year}"
        if periodo == '6m':
            ini = _mes_rel(5)
            fim = f"{agora.month:02d}/{agora.year:04d}"
            return ini, fim, '6m', 'Últimos 6 meses'
        if periodo == '3m':
            ini = _mes_rel(2)
            fim = f"{agora.month:02d}/{agora.year:04d}"
            return ini, fim, '3m', 'Últimos 3 meses'
        if mes_ini and mes_fim:
            return mes_ini, mes_fim, 'custom', f"{mes_ini} a {mes_fim}"
        if mes_ini:
            return mes_ini, mes_ini, 'mes', mes_ini
        # padrão: mês atual
        mes_atual = f"{agora.month:02d}/{agora.year:04d}"
        return mes_atual, mes_atual, 'mes_atual', mes_atual

    mes_ini, mes_fim, modo, periodo_label = _parse_periodo()

    def _mes_key(ref):
        if not ref:
            return None
        ref = str(ref).strip()
        # Formato dd/mm/yyyy (data da O.S.)
        m = re.match(r'^\d{1,2}/(\d{1,2})/(\d{4})$', ref)
        if m:
            month = max(1, min(12, int(m.group(1))))
            return int(m.group(2)) * 100 + month
        # Formato mm/yyyy ou m/yyyy
        m = re.match(r'^(\d{1,2})/(\d{4})$', ref)
        if m:
            month = max(1, min(12, int(m.group(1))))
            return int(m.group(2)) * 100 + month
        # Tenta normalize e extrai
        ref2 = normalize_month_reference(ref)
        m = re.search(r'(\d{1,2})\s*/\s*(\d{2,4})', ref2 or '')
        if not m:
            return None
        month = max(1, min(12, int(m.group(1))))
        year = int(m.group(2))
        if year < 100: year += 2000
        return year * 100 + month

    ini_key = _mes_key(mes_ini)
    fim_key = _mes_key(mes_fim)

    def _in_periodo(ref):
        if modo == 'tudo': return True
        key = _mes_key(normalize_month_reference(ref))
        if key is None: return False
        if ini_key and fim_key:
            return ini_key <= key <= fim_key
        if ini_key:
            return key == ini_key
        return True

    def build_dashboard_payload():
        bombas_counts = fetch_bombas_counts()

        def tenant_rows(table, fields='*', limit=500):
            where_sql, params = company_where(table)
            sql = f'SELECT {fields} FROM {table}{where_sql}'
            if table_has_column(table, 'id'):
                sql += ' ORDER BY id DESC'
            if limit:
                sql += ' LIMIT ?'
                params = list(params) + [int(limit)]
            return query_all(sql, tuple(params))

        def tenant_count(table):
            where_sql, params = company_where(table)
            row = query_one(f'SELECT COUNT(*) AS c FROM {table}{where_sql}', tuple(params))
            return int(row_get_value(row, 'c', 0) or 0)

        # Busca TUDO e filtra em Python — garante que qualquer formato de mês é aceito
        pagamentos_rows_all = tenant_rows('pagamentos',
            select_existing_columns('pagamentos', 'id,status,valor,fornecedor,pagamento_mes,tipo_lancamento'), limit=5000)
        ensure_os_tipo_os_column()
        os_fields = select_existing_columns('os_ordens', [
            'tipo_os', 'sistema', 'troca_componentes', 'teve_troca_componentes', 'equipamento',
            'ativo_nome', 'componentes_descricao', 'componentes', 'status', 'finalizada',
            'data', 'data_inicio', 'prazo', 'previsao', 'data_prevista'
        ])
        os_rows_all = tenant_rows('os_ordens', os_fields, limit=2000)
        combustivel_rows_all = tenant_rows('combustivel',
            select_existing_columns('combustivel', 'custo,mes_ref,data'), limit=2000)
        custos_rows_all = tenant_rows('custos',
            select_existing_columns('custos', 'id,mes'), limit=2000)
        bombas_entrega_rows = tenant_rows('bombas',
            select_existing_columns('bombas', 'status_entrega'))

        # ── Filtra por período ──────────────────────────────────────────
        pagamentos_rows = [r for r in pagamentos_rows_all
                           if _in_periodo(row_get_value(r, 'pagamento_mes', ''))]

        _CAMPOS_DATA_OS = ('data', 'data_inicio', 'data_fim', 'data_prevista', 'prazo')

        def _os_in_periodo(r):
            if modo == 'tudo':
                return True
            for campo in _CAMPOS_DATA_OS:
                val = row_get_value(r, campo, '')
                if val and _in_periodo(str(val)):
                    return True
            return False

        # O.S. sempre mostram TUDO — gráficos operacionais são independentes do período financeiro
        os_rows_db = list(os_rows_all)

        combustivel_mes_rows = [r for r in combustivel_rows_all
                                if modo == 'tudo' or _in_periodo(row_get_value(r, 'mes_ref', '') or row_get_value(r, 'data', ''))]
        custos_mes_rows = [r for r in custos_rows_all
                           if modo == 'tudo' or _in_periodo(row_get_value(r, 'mes', ''))]

        stats = {
            'controle': tenant_count('bombas'),
            'combustivel': tenant_count('combustivel'),
            'pagamentos': tenant_count('pagamentos'),
            'custos': tenant_count('custos'),
            'ordens_os': tenant_count('os_ordens'),
            'ativos_os': tenant_count('os_ativos'),
            'bombas_estoque': bombas_counts['em_estoque'],
            'bombas_conserto': bombas_counts['em_conserto'],
            'bombas_atrasadas': bombas_counts['atrasadas'],
        }

        # ── Totais financeiros do período ───────────────────────────────
        total_pag, valor_pago_mes, valor_pendente = compute_payments_totals(pagamentos_rows)
        investimento_mes = sum(
            parse_num(row_get_value(r, 'valor', 0))
            for r in pagamentos_rows
            if str(row_get_value(r, 'tipo_lancamento', '') or '').strip().lower() == 'investimento'
        )
        gasto_mes = total_pag - investimento_mes
        total_comb = sum(parse_num(row_get_value(r, 'custo', 0)) for r in combustivel_mes_rows)
        custos_mes_total = len(custos_mes_rows)
        pagamentos_pendentes = sum(1 for r in pagamentos_rows
                                   if not payment_status_is_paid(row_get_value(r, 'status', '')))
        pagamentos_realizados = len(pagamentos_rows) - pagamentos_pendentes

        # ── O.S. filtradas ──────────────────────────────────────────────
        sistemas = {}
        os_atrasadas_por_sistema = {}
        componentes_por_sistema = {}
        componentes_por_tipo = {}
        equipamentos_criticos = {}
        total_com_troca = 0
        os_status_operacional = {'Em andamento': 0, 'Pausadas': 0, 'Atrasadas': 0}
        os_tipo_counts = {'Corretiva': 0, 'Preventiva': 0}

        for r in os_rows_db:
            item = dict(r)
            tipo_os_item = str(item.get('tipo_os') or '').strip().title()
            if tipo_os_item in os_tipo_counts:
                os_tipo_counts[tipo_os_item] += 1
            sistema = item.get('sistema') or 'Sem sistema'
            sistemas[sistema] = sistemas.get(sistema, 0) + 1
            troca_comp = str(item.get('troca_componentes') or item.get('teve_troca_componentes') or '').strip().lower()
            houve_troca = troca_comp in ('sim', 's', 'yes', 'true', '1')
            equipamento = (item.get('equipamento') or item.get('ativo_nome') or 'Equipamento não informado').strip()
            if houve_troca:
                total_com_troca += 1
                componentes_por_sistema[sistema] = componentes_por_sistema.get(sistema, 0) + 1
                desc_comp = (item.get('componentes_descricao') or '').strip()
                partes = [p.strip(' .;,-').title() for p in re.split(r'[,;\n/]+', desc_comp) if p.strip(' .;,-')]
                if not partes:
                    partes = ['Troca sem descrição']
                for parte in partes[:6]:
                    componentes_por_tipo[parte] = componentes_por_tipo.get(parte, 0) + 1
                equipamentos_criticos[equipamento] = equipamentos_criticos.get(equipamento, 0) + 3
            else:
                equipamentos_criticos.setdefault(equipamento, 0)
            status_os = str(item.get('status') or '').strip().lower()
            if os_is_overdue(item):
                os_status_operacional['Atrasadas'] += 1
                os_atrasadas_por_sistema[sistema] = os_atrasadas_por_sistema.get(sistema, 0) + 1
                equipamentos_criticos[equipamento] = equipamentos_criticos.get(equipamento, 0) + 2
            if status_os == 'pausada':
                os_status_operacional['Pausadas'] += 1
                equipamentos_criticos[equipamento] = equipamentos_criticos.get(equipamento, 0) + 1
            elif status_os == 'em andamento' and str(item.get('finalizada') or '').strip().lower() != 'sim':
                os_status_operacional['Em andamento'] += 1
            equipamentos_criticos[equipamento] = equipamentos_criticos.get(equipamento, 0) + 1

        bombas_entrega = {'Em andamento': 0, 'Entregue': 0, 'Em atraso': 0}
        for r in bombas_entrega_rows:
            status_entrega = str(row_get_value(r, 'status_entrega', '') or '').strip().lower()
            if 'atraso' in status_entrega: bombas_entrega['Em atraso'] += 1
            elif 'entregue' in status_entrega: bombas_entrega['Entregue'] += 1
            else: bombas_entrega['Em andamento'] += 1

        # ── Gráficos de tendência: respeita o período ────────────────────
        valores_pagos_por_mes = {}
        gasto_por_mes = {}
        investimento_por_mes = {}

        # Para "tudo" e períodos > 1 mês: mostra todos os meses dentro do range
        # Para mês único: mostra só aquele mês
        for r in pagamentos_rows_all if modo == 'tudo' else pagamentos_rows:
            mes = row_get_value(r, 'pagamento_mes', '') or 'Sem mês'
            mes_norm = normalize_month_reference(mes) or mes
            val = parse_num(row_get_value(r, 'valor', 0))
            valores_pagos_por_mes[mes_norm] = valores_pagos_por_mes.get(mes_norm, 0) + val
            tipo_lanc = str(row_get_value(r, 'tipo_lancamento', '') or '').strip().lower()
            if tipo_lanc == 'investimento':
                investimento_por_mes[mes_norm] = investimento_por_mes.get(mes_norm, 0) + val
            else:
                gasto_por_mes[mes_norm] = gasto_por_mes.get(mes_norm, 0) + val

        bombas_local = {'Em estoque': bombas_counts['em_estoque'], 'Em conserto': bombas_counts['em_conserto']}

        def top_items(d, n=6):
            return dict(sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:n])

        def sort_mes_map(data):
            def key_mes(item):
                mes = normalize_month_reference(item[0])
                m = re.match(r'^(\d{2})/(\d{4})$', mes)
                if m: return (int(m.group(2)), int(m.group(1)))
                m = re.match(r'^(\d{2})$', mes)
                if m: return (0, int(m.group(1)))
                return (9999, 99)
            return dict(sorted(data.items(), key=key_mes))

        top_componentes = top_items(componentes_por_tipo)
        top_equipamentos = top_items(equipamentos_criticos)
        perc_troca = round((total_com_troca / len(os_rows_db) * 100), 1) if os_rows_db else 0

        stats.update({
            'pagamentos_pendentes': pagamentos_pendentes,
            'pagamentos_realizados': pagamentos_realizados,
            'valor_pendente': valor_pendente,
            'valor_pago_mes': valor_pago_mes,
            'combustivel_mes_total': total_comb,
            'custos_mes_total': custos_mes_total,
            'pagamentos_mes_referencia': periodo_label,
            'os_andamento': os_status_operacional['Em andamento'],
            'os_pausadas': os_status_operacional['Pausadas'],
            'componentes_total': total_com_troca,
            'componentes_percentual': perc_troca,
        })

        dashboard_cards = {
            'os_em_andamento': os_status_operacional['Em andamento'],
            'os_pausadas': os_status_operacional['Pausadas'],
            'os_atrasadas': os_status_operacional['Atrasadas'],
            'bombas_estoque': bombas_counts['em_estoque'],
            'bombas_conserto': bombas_counts['em_conserto'],
            'valor_pendente': gasto_mes,
            'investimento_mes': investimento_mes,
            'combustivel_mes_total': total_comb,
            'custos_mes_total': custos_mes_total,
            'componentes_total': total_com_troca,
            'componentes_percentual': perc_troca,
            'pagamentos_mes_referencia': periodo_label,
        }

        dashboard_data = {
            'cards': dashboard_cards,
            'stats': stats,
            'periodo_label': periodo_label,
            'modo': modo,
            'os_status_labels': list(bombas_entrega.keys()),
            'os_status_values': list(bombas_entrega.values()),
            'os_tipo_labels': list(os_tipo_counts.keys()),
            'os_tipo_values': list(os_tipo_counts.values()),
            'os_sistema_labels': list(top_items(sistemas).keys()),
            'os_sistema_values': list(top_items(sistemas).values()),
            'os_atrasadas_labels': list(top_items(os_atrasadas_por_sistema).keys()) or ['Sem atrasos'],
            'os_atrasadas_values': list(top_items(os_atrasadas_por_sistema).values()) or [0],
            'componentes_sistema_labels': list(top_items(componentes_por_sistema).keys()) or ['Sem trocas'],
            'componentes_sistema_values': list(top_items(componentes_por_sistema).values()) or [0],
            'componentes_tipo_labels': list(top_componentes.keys()) or ['Sem dados'],
            'componentes_tipo_values': list(top_componentes.values()) or [0],
            'equipamentos_criticos_labels': list(top_equipamentos.keys()) or ['Sem dados'],
            'equipamentos_criticos_values': list(top_equipamentos.values()) or [0],
            'pagamentos_labels': ['Não pago', 'Pago'],
            'pagamentos_values': [pagamentos_pendentes, pagamentos_realizados],
            'pagamentos_mes_labels': list(sort_mes_map(valores_pagos_por_mes).keys()) or ['Sem mês'],
            'pagamentos_mes_values': list(sort_mes_map(valores_pagos_por_mes).values()) or [0],
            'gasto_mes_labels': list(sort_mes_map(gasto_por_mes).keys()) or ['Sem mês'],
            'gasto_mes_values': list(sort_mes_map(gasto_por_mes).values()) or [0],
            'investimento_mes_labels': list(sort_mes_map(investimento_por_mes).keys()) or ['Sem mês'],
            'investimento_mes_values': list(sort_mes_map(investimento_por_mes).values()) or [0],
            'bombas_local_labels': list(bombas_local.keys()),
            'bombas_local_values': list(bombas_local.values()),
            'alerts': [
                {'title': 'Bombas em estoque', 'value': bombas_counts['em_estoque'], 'level': 'ok' if bombas_counts['em_estoque'] else 'warning'},
                {'title': 'Bombas em conserto', 'value': bombas_counts['em_conserto'], 'level': 'info' if bombas_counts['em_conserto'] else 'ok'},
                {'title': 'O.S. em atraso', 'value': sum(os_atrasadas_por_sistema.values()), 'level': 'danger' if os_atrasadas_por_sistema else 'ok'},
                {'title': 'Pagamentos no período', 'value': br_money(total_pag), 'level': 'info' if total_pag else 'ok'},
                {'title': 'Combustível no período', 'value': br_money(total_comb), 'level': 'info' if total_comb else 'ok'},
                {'title': 'Custos no período', 'value': custos_mes_total, 'level': 'info' if custos_mes_total else 'ok'},
            ]
        }
        return {'stats': stats, 'total_pag': total_pag, 'total_comb': total_comb, 'dashboard_data': dashboard_data}

    cache_key = f'view:dashboard:{current_company_id()}:{modo}:{mes_ini}:{mes_fim}'
    payload = cached_result(cache_key, build_dashboard_payload, ttl=60)
    if not isinstance(payload, dict):
        payload = {}
    dashboard_data = payload.get('dashboard_data') or {}
    cards = dashboard_data.get('cards') or {}
    defaults = {
        'os_em_andamento': 0, 'os_pausadas': 0, 'os_atrasadas': 0,
        'bombas_estoque': 0, 'bombas_conserto': 0,
        'valor_pendente': 0, 'combustivel_mes_total': 0, 'custos_mes_total': 0,
        'componentes_total': 0, 'componentes_percentual': 0,
    }
    defaults.update(cards)
    dashboard_data['cards'] = defaults
    dashboard_data.setdefault('alerts', [])
    dashboard_data.setdefault('os_tipo_labels', ['Corretiva', 'Preventiva'])
    dashboard_data.setdefault('os_tipo_values', [0, 0])
    dashboard_data['periodo_label'] = periodo_label
    dashboard_data['modo'] = modo
    dashboard_data['mes_ini'] = mes_ini
    dashboard_data['mes_fim'] = mes_fim
    payload['dashboard_data'] = dashboard_data
    payload['now_hour'] = br_now().hour
    payload['current_user'] = row_to_dict(query_one('SELECT nome FROM users WHERE id=?', (session.get('user_id'),)) or {})
    return render_template('dashboard.html', **payload)


def register_routes(app):
    for rule, endpoint, view, methods, options in [
        ('/health', 'health', health, ['GET'], {}),
        ('/favicon.ico', 'favicon_root', favicon_root, ['GET'], {}),
        ('/loading', 'loading', loading, ['GET'], {}),
        ('/campo/loading', 'campo_loading', campo_loading, ['GET'], {}),
        ('/', 'intro', intro, ['GET'], {}),
        ('/home', 'dashboard', dashboard, ['GET'], {}),
    ]:
        app.add_url_rule(rule, endpoint, view, methods=methods, **options)

    app.add_url_rule('/home', 'home_page', dashboard, methods=['GET'])
    app.add_url_rule('/', 'index', intro, methods=['GET'])
