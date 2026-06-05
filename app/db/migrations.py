"""Migrations leves (CREATE TABLE / colunas / índices)."""
from app.db import settings
from app.db.queries import execute, query_all
from app.db.schema import ensure_column

USE_POSTGRES = settings.USE_POSTGRES

def ensure_db():
    from app.combustivel.constants import COMBUSTIVEL_VINCULOS
    from app.campo.services import _token_expira_str
    from app.shared.formatters import now_str
    from app.shared.rows import row_to_dict
    """Garante colunas que podem faltar nas tabelas do módulo Outlook e outros."""

    # Colunas do módulo Outlook — evita erro "column does not exist" no PostgreSQL
    _email_history_cols = [
        ('pagamento_id', 'INTEGER'),
        ('fluxo', "TEXT DEFAULT ''"),
        ('remetente', "TEXT DEFAULT ''"),
        ('cc', "TEXT DEFAULT ''"),
        ('numero_sc', "TEXT DEFAULT ''"),
        ('numero_pedido', "TEXT DEFAULT ''"),
        ('anexos_json', "TEXT DEFAULT '[]'"),
    ]
    for col, ddl in _email_history_cols:
        try:
            ensure_column('email_history', col, ddl)
        except Exception as exc:
            print(f'ensure_db email_history.{col} falhou:', exc)

    _email_test_history_cols = [
        ('fluxo', "TEXT DEFAULT ''"),
        ('destinatario', "TEXT DEFAULT ''"),
        ('assunto', "TEXT DEFAULT ''"),
        ('status', "TEXT DEFAULT ''"),
        ('detalhes', "TEXT DEFAULT ''"),
    ]
    for col, ddl in _email_test_history_cols:
        try:
            ensure_column('email_test_history', col, ddl)
        except Exception as exc:
            print(f'ensure_db email_test_history.{col} falhou:', exc)

    _email_monitor_events_cols = [
        ('detalhes', "TEXT DEFAULT ''"),
        ('corpo_resumo', "TEXT DEFAULT ''"),
        ('sugestao_fluxo', "TEXT DEFAULT ''"),
        ('pagamento_id', 'INTEGER'),
        ('popup_status', "TEXT DEFAULT 'novo'"),
        ('source_message_id', "TEXT DEFAULT ''"),
        ('remetente', "TEXT DEFAULT ''"),
        ('numero_sc', "TEXT DEFAULT ''"),
        ('numero_pedido', "TEXT DEFAULT ''"),
        ('evento', "TEXT DEFAULT ''"),
        ('status_processamento', "TEXT DEFAULT ''"),
    ]
    for col, ddl in _email_monitor_events_cols:
        try:
            ensure_column('email_monitor_events', col, ddl)
        except Exception as exc:
            print(f'ensure_db email_monitor_events.{col} falhou:', exc)

    # Outras colunas auxiliares
    for col, ddl in [
        ('data_vencimento', "TEXT DEFAULT ''"),
        ('tipo_lancamento', "TEXT DEFAULT 'Gasto'"),
        ('terceiro_nome',   "TEXT DEFAULT ''"),
    ]:
        try:
            ensure_column('pagamentos', col, ddl)
        except Exception as exc:
            print(f'ensure_db pagamentos.{col} falhou:', exc)

    # Tabela de recebimentos (A Receber)
    try:
        execute("""CREATE TABLE IF NOT EXISTS recebimentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT DEFAULT '',
            descricao TEXT DEFAULT '',
            valor TEXT DEFAULT '',
            status TEXT DEFAULT 'Pendente',
            data_vencimento TEXT DEFAULT '',
            data_recebimento TEXT DEFAULT '',
            mes_referencia TEXT DEFAULT '',
            numero_documento TEXT DEFAULT '',
            observacoes TEXT DEFAULT '',
            empresa_id INTEGER DEFAULT NULL
        )""")
    except Exception as exc:
        print('ensure_db recebimentos falhou:', exc)

    for col, ddl in [
        ('motivo_pausa', "TEXT DEFAULT ''"),
        ('motivo_atraso', "TEXT DEFAULT ''"),
        ('historico_pausas', "TEXT DEFAULT '[]'"),
    ]:
        try:
            ensure_column('os_ordens', col, ddl)
        except Exception as exc:
            print(f'ensure_db os_ordens.{col} falhou:', exc)

    # Localização GPS dos técnicos em campo
    for col, ddl in [
        ('campo_lat', 'REAL'),
        ('campo_lng', 'REAL'),
        ('campo_loc_updated_at', "TEXT DEFAULT ''"),
        ('campo_os_id', 'INTEGER'),
    ]:
        try:
            ensure_column('users', col, ddl)
        except Exception as exc:
            print(f'ensure_db users.{col} falhou:', exc)

    try:
        ensure_column('bombas', 'anexos_json', "TEXT DEFAULT '[]'")
        ensure_column('bombas', 'numero_serie', "TEXT DEFAULT ''")
        ensure_column('bombas', 'marca', "TEXT DEFAULT ''")
        ensure_column('bombas', 'garantia_ate', "TEXT DEFAULT ''")
        ensure_column('bombas', 'custo_manutencao', "TEXT DEFAULT ''")
        ensure_column('bombas', 'potencia', "TEXT DEFAULT ''")
        ensure_column('bombas', 'vazao', "TEXT DEFAULT ''")
        ensure_column('bombas', 'local_id', "INTEGER DEFAULT NULL")
    except Exception: pass

    # Tabela de locais cadastrados (poços, ETAs, sistemas)
    try:
        execute("""CREATE TABLE IF NOT EXISTS bombas_locais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER,
            nome TEXT DEFAULT '',
            tipo TEXT DEFAULT '',
            lat REAL,
            lng REAL,
            endereco TEXT DEFAULT '',
            observacoes TEXT DEFAULT '',
            criado_em TEXT DEFAULT ''
        )""")
    except Exception: pass
    try: ensure_column('bombas_locais', 'tipo', "TEXT DEFAULT ''")
    except Exception: pass

    # Tabela de movimentações
    try:
        execute("""CREATE TABLE IF NOT EXISTS bombas_movimentacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bomba_id INTEGER,
            empresa_id INTEGER,
            acao TEXT DEFAULT '',
            local_destino TEXT DEFAULT '',
            local_id INTEGER,
            motivo TEXT DEFAULT '',
            responsavel TEXT DEFAULT '',
            data TEXT DEFAULT '',
            observacoes TEXT DEFAULT '',
            criado_em TEXT DEFAULT ''
        )""")
    except Exception: pass

    # Tabela de motoristas/veículos para combustível
    try:
        execute("""CREATE TABLE IF NOT EXISTS combustivel_veiculos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER,
            motorista TEXT NOT NULL,
            modelo TEXT DEFAULT '',
            placa TEXT DEFAULT '',
            ativo INTEGER DEFAULT 1,
            criado_em TEXT DEFAULT ''
        )""")
    except Exception as exc:
        print('ensure_db combustivel_veiculos falhou:', exc)

    # Migrar COMBUSTIVEL_VINCULOS para o banco se ainda não estiver lá
    try:
        for empresa_row in (query_all('SELECT id FROM empresas WHERE ativo=1') or []):
            eid = row_to_dict(empresa_row).get('id')
            existentes = [row_to_dict(r).get('motorista','').lower()
                          for r in (query_all('SELECT motorista FROM combustivel_veiculos WHERE empresa_id=? AND ativo=1', (eid,)) or [])]
            for v in COMBUSTIVEL_VINCULOS:
                if v.get('motorista','').lower() not in existentes:
                    execute('INSERT INTO combustivel_veiculos (empresa_id, motorista, modelo, placa, ativo, criado_em) VALUES (?,?,?,?,1,?)',
                            (eid, v.get('motorista',''), v.get('modelo',''), v.get('placa',''), now_str()))
    except Exception as exc:
        print('ensure_db migrar combustivel_veiculos falhou:', exc)

    # Tabelas do módulo Inventário de suprimentos
    if settings.USE_POSTGRES:
        execute("""
            CREATE TABLE IF NOT EXISTS inventario_itens (
                id SERIAL PRIMARY KEY,
                empresa_id INTEGER DEFAULT 0,
                nome TEXT DEFAULT '',
                categoria TEXT DEFAULT '',
                unidade TEXT DEFAULT 'un',
                quantidade REAL DEFAULT 0,
                quantidade_minima REAL DEFAULT 0,
                localizacao TEXT DEFAULT '',
                observacoes TEXT DEFAULT '',
                criado_em TEXT DEFAULT ''
            )
        """)
        execute("""
            CREATE TABLE IF NOT EXISTS inventario_movimentos (
                id SERIAL PRIMARY KEY,
                empresa_id INTEGER DEFAULT 0,
                item_id INTEGER DEFAULT 0,
                tipo TEXT DEFAULT '',
                quantidade REAL DEFAULT 0,
                motivo TEXT DEFAULT '',
                os_id INTEGER DEFAULT 0,
                usuario TEXT DEFAULT '',
                quando TEXT DEFAULT ''
            )
        """)
    else:
        execute("""
            CREATE TABLE IF NOT EXISTS inventario_itens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER DEFAULT 0,
                nome TEXT DEFAULT '',
                categoria TEXT DEFAULT '',
                unidade TEXT DEFAULT 'un',
                quantidade REAL DEFAULT 0,
                quantidade_minima REAL DEFAULT 0,
                localizacao TEXT DEFAULT '',
                observacoes TEXT DEFAULT '',
                criado_em TEXT DEFAULT ''
            )
        """)
        execute("""
            CREATE TABLE IF NOT EXISTS inventario_movimentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER DEFAULT 0,
                item_id INTEGER DEFAULT 0,
                tipo TEXT DEFAULT '',
                quantidade REAL DEFAULT 0,
                motivo TEXT DEFAULT '',
                os_id INTEGER DEFAULT 0,
                usuario TEXT DEFAULT '',
                quando TEXT DEFAULT ''
            )
        """)

    # Tabela de pedidos de compra pendentes
    if settings.USE_POSTGRES:
        execute("""
            CREATE TABLE IF NOT EXISTS inventario_pedidos (
                id SERIAL PRIMARY KEY,
                empresa_id INTEGER DEFAULT 0,
                item_id INTEGER DEFAULT 0,
                quantidade REAL DEFAULT 0,
                fornecedor TEXT DEFAULT '',
                observacoes TEXT DEFAULT '',
                solicitado_por TEXT DEFAULT '',
                solicitado_em TEXT DEFAULT '',
                status TEXT DEFAULT 'pendente'
            )
        """)
    else:
        execute("""
            CREATE TABLE IF NOT EXISTS inventario_pedidos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER DEFAULT 0,
                item_id INTEGER DEFAULT 0,
                quantidade REAL DEFAULT 0,
                fornecedor TEXT DEFAULT '',
                observacoes TEXT DEFAULT '',
                solicitado_por TEXT DEFAULT '',
                solicitado_em TEXT DEFAULT '',
                status TEXT DEFAULT 'pendente'
            )
        """)
    # Colunas extras da tabela inventario_movimentos
    for col, ddl in [
        ('destino', "TEXT DEFAULT ''"),
        ('os_id', "TEXT DEFAULT ''"),
    ]:
        try:
            ensure_column('inventario_movimentos', col, ddl)
        except Exception as exc:
            print(f'ensure_db inventario_movimentos.{col} falhou:', exc)

    # Colunas extras da tabela inventario_itens (adicionadas após criação inicial)
    for col, ddl in [
        ('valor_unitario', "TEXT DEFAULT ''"),
        ('fornecedor', "TEXT DEFAULT ''"),
        ('anexos_json', "TEXT DEFAULT '[]'"),
        ('quantidade_minima', "REAL DEFAULT 0"),
    ]:
        try:
            ensure_column('inventario_itens', col, ddl)
        except Exception as exc:
            print(f'ensure_db inventario_itens.{col} falhou:', exc)

    if settings.USE_POSTGRES:
        for tbl, col in [('email_templates', 'chave'), ('email_config', 'chave'), ('deleted_users', 'email')]:
            try:
                execute(f"ALTER TABLE {tbl} ADD CONSTRAINT {tbl}_{col}_uq UNIQUE ({col})")
            except Exception:
                pass  # já existe, tudo bem

    # Colunas de expiração do token do app de campo
    for col, ddl in [
        ('token_criado_em', "TEXT DEFAULT ''"),
        ('token_ultimo_uso', "TEXT DEFAULT ''"),
        ('token_expira_em', "TEXT DEFAULT ''"),
        ('campo_lat',  'REAL'),
        ('campo_lng',  'REAL'),
        ('campo_loc_updated_at', "TEXT DEFAULT ''"),
        ('campo_os_id', 'INTEGER'),
        ('foto_perfil', "TEXT DEFAULT ''"),
    ]:
        try:
            ensure_column('campo_tecnicos', col, ddl)
        except Exception as exc:
            print(f'ensure_db campo_tecnicos.{col} falhou:', exc)

    # Preenche token_expira_em para tokens existentes sem expiração
    try:
        execute("""UPDATE campo_tecnicos
                   SET token_expira_em=?, token_criado_em=?
                   WHERE TRIM(COALESCE(token,''))!=''
                     AND TRIM(COALESCE(token_expira_em,''))=''""",
                (_token_expira_str(30), now_str()))
    except Exception as exc:
        print('ensure_db: preencher token_expira_em falhou:', exc)
    try:
        execute("UPDATE os_ordens SET numero_os=CAST(id AS TEXT) WHERE TRIM(COALESCE(numero_os,''))=''")
    except Exception as exc:
        print('ensure_db: preencher numero_os falhou:', exc)

    # Tabela de jobs de PDF em background
    try:
        if settings.USE_POSTGRES:
            execute("""CREATE TABLE IF NOT EXISTS pdf_jobs (
                id SERIAL PRIMARY KEY,
                empresa_id INTEGER DEFAULT 0,
                usuario_id INTEGER DEFAULT 0,
                tipo TEXT DEFAULT '',
                mes TEXT DEFAULT '',
                status TEXT DEFAULT 'pendente',
                arquivo_url TEXT DEFAULT '',
                storage_path TEXT DEFAULT '',
                erro TEXT DEFAULT '',
                criado_em TEXT DEFAULT '',
                iniciado_em TEXT DEFAULT '',
                finalizado_em TEXT DEFAULT ''
            )""")
        else:
            execute("""CREATE TABLE IF NOT EXISTS pdf_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER DEFAULT 0,
                usuario_id INTEGER DEFAULT 0,
                tipo TEXT DEFAULT '',
                mes TEXT DEFAULT '',
                status TEXT DEFAULT 'pendente',
                arquivo_url TEXT DEFAULT '',
                storage_path TEXT DEFAULT '',
                erro TEXT DEFAULT '',
                criado_em TEXT DEFAULT '',
                iniciado_em TEXT DEFAULT '',
                finalizado_em TEXT DEFAULT ''
            )""")
        for col, ddl in [
            ('arquivo_url', "TEXT DEFAULT ''"),
            ('storage_path', "TEXT DEFAULT ''"),
            ('erro', "TEXT DEFAULT ''"),
            ('iniciado_em', "TEXT DEFAULT ''"),
            ('finalizado_em', "TEXT DEFAULT ''"),
            ('criado_em', "TEXT DEFAULT ''"),
        ]:
            try:
                ensure_column('pdf_jobs', col, ddl)
            except Exception:
                pass
    except Exception as exc:
        print('ensure_db: criar pdf_jobs falhou:', exc)

    try:
        from app.auth.security_store import ensure_auth_security_tables
        ensure_auth_security_tables()
    except Exception as exc:
        print('ensure_db: auth security tables falhou:', exc)


def ensure_indexes():
    """Cria índices nas tabelas principais para acelerar queries frequentes.
    Usa IF NOT EXISTS — seguro rodar múltiplas vezes."""
    indexes = [
        # pagamentos
        ("idx_pagamentos_empresa",       "pagamentos(empresa_id)"),
        ("idx_pagamentos_status",        "pagamentos(status)"),
        ("idx_pagamentos_mes",           "pagamentos(pagamento_mes)"),
        ("idx_pagamentos_vencimento",    "pagamentos(data_vencimento)"),
        ("idx_pagamentos_tipo",          "pagamentos(tipo_lancamento)"),
        ("idx_pagamentos_empresa_mes",   "pagamentos(empresa_id, pagamento_mes)"),
        ("idx_pagamentos_empresa_status","pagamentos(empresa_id, status)"),
        # os_ordens
        ("idx_os_empresa",              "os_ordens(empresa_id)"),
        ("idx_os_status",               "os_ordens(status)"),
        ("idx_os_finalizada",           "os_ordens(finalizada)"),
        ("idx_os_responsavel",          "os_ordens(responsavel)"),
        ("idx_os_data",                 "os_ordens(data)"),
        ("idx_os_empresa_status",       "os_ordens(empresa_id, status)"),
        ("idx_os_empresa_data",         "os_ordens(empresa_id, data)"),
        # custos
        ("idx_custos_empresa",          "custos(empresa_id)"),
        # users
        ("idx_users_empresa",           "users(empresa_id)"),
        ("idx_users_ativo",             "users(ativo)"),
    ]
    for idx_name, idx_cols in indexes:
        try:
            execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_cols}", ())
        except Exception:
            pass  # tabela pode não existir ainda — ignora silenciosamente
