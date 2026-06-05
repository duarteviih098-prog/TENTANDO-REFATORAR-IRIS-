-- audit_logs
CREATE TABLE audit_logs (
            id SERIAL PRIMARY KEY,
            criado_em TEXT DEFAULT '', usuario_id INTEGER, usuario_nome TEXT DEFAULT '', usuario_email TEXT DEFAULT '',
            acao TEXT DEFAULT '', entidade TEXT DEFAULT '', entidade_id TEXT DEFAULT '', metodo TEXT DEFAULT '', rota TEXT DEFAULT '',
            endpoint TEXT DEFAULT '', resultado TEXT DEFAULT '', detalhes TEXT DEFAULT ''
        , empresa_id INTEGER);

-- bombas
CREATE TABLE bombas (
        id SERIAL PRIMARY KEY,
        tipo TEXT, nome TEXT, modelo TEXT, descricao TEXT, fornecedor TEXT,
        sistema TEXT, equipamento TEXT, valor TEXT, orcamento TEXT,
        em_estoque TEXT, em_conserto TEXT, data_entrada TEXT, data_estimada TEXT,
        data_entrega TEXT, status TEXT, observacoes TEXT
    , localizacao TEXT DEFAULT 'estoque', pedido_aberto TEXT DEFAULT '', previsao_entrega TEXT DEFAULT '', status_entrega TEXT DEFAULT '', data_abertura TEXT DEFAULT '', recebido_em TEXT DEFAULT '', obs TEXT DEFAULT '', destino_retirada TEXT DEFAULT '', empresa_id INTEGER, anexos_json TEXT DEFAULT '[]', numero_serie TEXT DEFAULT '', marca TEXT DEFAULT '', garantia_ate TEXT DEFAULT '', custo_manutencao TEXT DEFAULT '', potencia TEXT DEFAULT '', vazao TEXT DEFAULT '', local_id INTEGER DEFAULT NULL);

-- bombas_locais
CREATE TABLE bombas_locais (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER,
            nome TEXT DEFAULT '',
            tipo TEXT DEFAULT '',
            lat REAL,
            lng REAL,
            endereco TEXT DEFAULT '',
            observacoes TEXT DEFAULT '',
            criado_em TEXT DEFAULT ''
        );

-- bombas_movimentacoes
CREATE TABLE bombas_movimentacoes (
            id SERIAL PRIMARY KEY,
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
        );

-- campo_eventos
CREATE TABLE campo_eventos (
        id SERIAL PRIMARY KEY,
        os_id INTEGER,
        empresa_id INTEGER,
        tipo TEXT DEFAULT '',
        titulo TEXT DEFAULT '',
        mensagem TEXT DEFAULT '',
        status TEXT DEFAULT 'novo',
        criado_em TEXT DEFAULT ''
    );

-- campo_tecnicos
CREATE TABLE campo_tecnicos (
        id SERIAL PRIMARY KEY,
        nome TEXT NOT NULL,
        telefone TEXT DEFAULT '',
        empresa_id INTEGER,
        ativo INTEGER DEFAULT 1,
        criado_em TEXT DEFAULT ''
    , token TEXT DEFAULT '', token_criado_em TEXT DEFAULT '', token_ultimo_uso TEXT DEFAULT '', token_expira_em TEXT DEFAULT '', campo_lat REAL, campo_lng REAL, campo_loc_updated_at TEXT DEFAULT '', campo_os_id INTEGER, foto_perfil TEXT DEFAULT '', email TEXT, user_id INTEGER);

-- combustivel
CREATE TABLE combustivel (
        id SERIAL PRIMARY KEY,
        data TEXT, mes_ref TEXT, modelo_veiculo TEXT, placa TEXT, motorista TEXT,
        km TEXT, custo TEXT, observacoes TEXT
    , empresa_id INTEGER);

-- combustivel_veiculos
CREATE TABLE combustivel_veiculos (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER,
            motorista TEXT NOT NULL,
            modelo TEXT DEFAULT '',
            placa TEXT DEFAULT '',
            ativo INTEGER DEFAULT 1,
            criado_em TEXT DEFAULT ''
        );

-- custos
CREATE TABLE custos (
        id SERIAL PRIMARY KEY,
        sistema TEXT, equipamento TEXT, nr_os TEXT, descricao_os TEXT,
        local TEXT, manutencao TEXT, mes TEXT
    , empresa_id INTEGER);

-- deleted_users
CREATE TABLE deleted_users (
        email TEXT PRIMARY KEY,
        deletado_em TEXT DEFAULT ''
    );

-- email_config
CREATE TABLE email_config (
        chave TEXT PRIMARY KEY,
        valor TEXT
    );

-- email_contacts
CREATE TABLE email_contacts (
    id SERIAL PRIMARY KEY,
    area TEXT NOT NULL,
    tipo TEXT NOT NULL,
    nome TEXT NOT NULL,
    emails TEXT NOT NULL,
    observacoes TEXT DEFAULT '',
    created_at TEXT DEFAULT ''
);

-- email_history
CREATE TABLE email_history (
        id SERIAL PRIMARY KEY,
        quando TEXT, tipo TEXT, numero TEXT, destinatario TEXT,
        assunto TEXT, status TEXT, anexos INTEGER, fluxo TEXT
    , remetente TEXT DEFAULT '', cc TEXT DEFAULT '', numero_sc TEXT DEFAULT '', numero_pedido TEXT DEFAULT '', anexos_json TEXT DEFAULT '[]', empresa_id INTEGER, pagamento_id INTEGER);

-- email_monitor_events
CREATE TABLE email_monitor_events (
        id SERIAL PRIMARY KEY,
        quando TEXT,
        source_message_id TEXT UNIQUE,
        remetente TEXT,
        assunto TEXT,
        corpo_resumo TEXT DEFAULT '',
        evento TEXT DEFAULT 'ignorado',
        status_processamento TEXT DEFAULT '',
        numero_sc TEXT DEFAULT '',
        numero_pedido TEXT DEFAULT '',
        pagamento_id INTEGER,
        sugestao_fluxo TEXT DEFAULT '',
        popup_status TEXT DEFAULT 'novo',
        popup_dispensado_em TEXT DEFAULT '',
        detalhes_json TEXT DEFAULT '[]'
    , empresa_id INTEGER, detalhes TEXT DEFAULT '');

-- email_monitor_test_runs
CREATE TABLE email_monitor_test_runs (
        id SERIAL PRIMARY KEY,
        quando TEXT,
        scenario_name TEXT DEFAULT '',
        sender_email TEXT DEFAULT '',
        subject TEXT DEFAULT '',
        body_resumo TEXT DEFAULT '',
        expected_evento TEXT DEFAULT '',
        detected_evento TEXT DEFAULT '',
        expected_sc TEXT DEFAULT '',
        detected_sc TEXT DEFAULT '',
        expected_pedido TEXT DEFAULT '',
        detected_pedido TEXT DEFAULT '',
        expected_pagamento_id INTEGER,
        detected_pagamento_id INTEGER,
        status TEXT DEFAULT '',
        applied INTEGER DEFAULT 0,
        duplicate INTEGER DEFAULT 0,
        detalhes TEXT DEFAULT ''
    , empresa_id INTEGER);

-- email_senders
CREATE TABLE email_senders (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    provider TEXT DEFAULT 'graph',
    ativo INTEGER DEFAULT 1,
    is_default INTEGER DEFAULT 0,
    observacoes TEXT DEFAULT '',
    created_at TEXT DEFAULT ''
);

-- email_templates
CREATE TABLE email_templates (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

-- email_test_history
CREATE TABLE email_test_history (
        id SERIAL PRIMARY KEY,
        quando TEXT,
        provider TEXT,
        sender_email TEXT,
        target_email TEXT,
        flow TEXT,
        status TEXT,
        detalhes TEXT DEFAULT '',
        anexos_json TEXT DEFAULT '[]'
    , empresa_id INTEGER, fluxo TEXT DEFAULT '', destinatario TEXT DEFAULT '', assunto TEXT DEFAULT '');

-- empresas
CREATE TABLE empresas (
        id SERIAL PRIMARY KEY,
        nome TEXT NOT NULL UNIQUE,
        cidade TEXT DEFAULT '',
        dominio_email TEXT DEFAULT '',
        ativo INTEGER DEFAULT 1,
        criado_em TEXT DEFAULT ''
    , cliente_pdf TEXT, contratada_pdf TEXT, cnpj_pdf TEXT, cidade_pdf TEXT, responsavel_pdf TEXT, assinatura_esquerda_label TEXT, assinatura_direita_label TEXT);

-- inventario_itens
CREATE TABLE inventario_itens (
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
            , valor_unitario TEXT DEFAULT '', fornecedor TEXT DEFAULT '', anexos_json TEXT DEFAULT '[]');

-- inventario_movimentos
CREATE TABLE inventario_movimentos (
                id SERIAL PRIMARY KEY,
                empresa_id INTEGER DEFAULT 0,
                item_id INTEGER DEFAULT 0,
                tipo TEXT DEFAULT '',
                quantidade REAL DEFAULT 0,
                motivo TEXT DEFAULT '',
                os_id INTEGER DEFAULT 0,
                usuario TEXT DEFAULT '',
                quando TEXT DEFAULT ''
            , destino TEXT DEFAULT '');

-- inventario_pedidos
CREATE TABLE inventario_pedidos (
                id SERIAL PRIMARY KEY,
                empresa_id INTEGER DEFAULT 0,
                item_id INTEGER DEFAULT 0,
                quantidade REAL DEFAULT 0,
                fornecedor TEXT DEFAULT '',
                observacoes TEXT DEFAULT '',
                solicitado_por TEXT DEFAULT '',
                solicitado_em TEXT DEFAULT '',
                status TEXT DEFAULT 'pendente'
            );

-- login_attempts
CREATE TABLE login_attempts (
            ip TEXT PRIMARY KEY,
            attempt_count INTEGER DEFAULT 0,
            first_at REAL NOT NULL,
            blocked_until REAL DEFAULT 0
        );

-- os_ativos
CREATE TABLE os_ativos (
        id SERIAL PRIMARY KEY,
        nome TEXT NOT NULL, tipo TEXT, local TEXT, descricao TEXT,
        status TEXT DEFAULT 'Ativo', criado_em TEXT, sistema TEXT, equipamento TEXT
    , empresa_id INTEGER);

-- os_ordens
CREATE TABLE os_ordens (
        id SERIAL PRIMARY KEY,
        data TEXT, ativo_id INTEGER, ativo_nome TEXT, tipo TEXT, status TEXT,
        criticidade TEXT, descricao TEXT, data_inicio TEXT, data_fim TEXT,
        responsavel TEXT, servico_executado TEXT, criado_em TEXT,
        sistema TEXT, equipamento TEXT, imagens TEXT,
        teve_terceiro TEXT, quem_foi_terceiro TEXT
    , finalizada TEXT DEFAULT 'NÒo', acumulado_minutos INTEGER DEFAULT 0, orcamentos TEXT DEFAULT '[]', empresa_id INTEGER, troca_componentes TEXT DEFAULT 'NÒo', componentes_descricao TEXT DEFAULT '', custo_os TEXT DEFAULT '', observacao_custo TEXT DEFAULT '', campo_problema TEXT DEFAULT '', campo_funcionando TEXT DEFAULT '', campo_finalizado_em TEXT DEFAULT '', numero_os TEXT DEFAULT '', motivo_pausa TEXT DEFAULT '', motivo_atraso TEXT DEFAULT '', historico_pausas TEXT DEFAULT '[]');

-- pagamentos
CREATE TABLE pagamentos (
        id SERIAL PRIMARY KEY,
        sistema TEXT, equipamento TEXT, fornecedor TEXT, descricao_servico TEXT,
        status TEXT, nf_proposta TEXT, valor TEXT, acao TEXT, pagamento_mes TEXT,
        sc_pedido TEXT, aprovado TEXT, tipo_documento TEXT, numero_documento TEXT,
        fluxo_status TEXT, popup_dispensado_contabil TEXT,
        anexos_orcamento TEXT, anexos_nf TEXT, anexos_boleto TEXT
    , empresa_id INTEGER, data_vencimento TEXT DEFAULT '', tipo_lancamento TEXT DEFAULT 'Gasto', terceiro_nome TEXT DEFAULT '');

-- password_reset_tokens
CREATE TABLE password_reset_tokens (
            token TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            expires_at REAL NOT NULL,
            created_at TEXT DEFAULT ''
        );

-- pdf_jobs
CREATE TABLE pdf_jobs (
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
            );

-- recebimentos
CREATE TABLE recebimentos (
            id SERIAL PRIMARY KEY,
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
        );

-- users
CREATE TABLE users (id SERIAL PRIMARY KEY, nome TEXT NOT NULL, email TEXT NOT NULL UNIQUE, senha_hash TEXT NOT NULL, perfil TEXT DEFAULT 'campo', permissions TEXT DEFAULT '[]', ativo INTEGER DEFAULT 1, criado_em TEXT DEFAULT '', empresa_id INTEGER, is_super_admin INTEGER DEFAULT 0, telefone TEXT DEFAULT '', campo_lat REAL, campo_lng REAL, campo_loc_updated_at TEXT DEFAULT '', campo_os_id INTEGER);

