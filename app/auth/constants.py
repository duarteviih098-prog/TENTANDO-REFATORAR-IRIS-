"""Permissões, papéis e tabelas multi-empresa."""
import json

PERMISSION_LABELS = {
    'view_dashboard': 'Ver aba Inicial',
    'view_controle': 'Ver Estoque de bombas',
    'view_combustivel': 'Ver Combustível',
    'view_pagamentos': 'Ver Pagamentos',
    'view_custos': 'Ver Custos',
    'view_os': 'Ver O.S.',
    'view_os_ativos': 'Ver Ativos da O.S.',
    'view_outlook': 'Ver Outlook / Histórico',
    'view_inventario': 'Ver Inventário de suprimentos',
    'edit_inventario': 'Editar Inventário',
    'delete_inventario': 'Excluir Inventário',
    'create_os': 'Criar O.S.',
    'edit_os': 'Editar/Iniciar/Finalizar O.S.',
    'delete_os': 'Excluir O.S.',
    'upload_os_photos': 'Anexar fotos da O.S.',
    'upload_budget_files': 'Anexar orçamento/NF',
    'view_budget_files': 'Ver orçamento/NF',
    'download_os': 'Baixar pacote/PDF da O.S.',
    'generate_pdf': 'Gerar PDF',
    'generate_excel': 'Gerar Excel',
    'edit_combustivel': 'Editar Combustível',
    'delete_combustivel': 'Excluir Combustível',
    'edit_pagamentos': 'Editar Pagamentos',
    'delete_pagamentos': 'Excluir Pagamentos',
    'edit_custos': 'Editar Custos',
    'delete_custos': 'Excluir Custos',
    'edit_controle': 'Editar Estoque',
    'delete_controle': 'Excluir Estoque',
    'manage_users': 'Gerenciar usuários e permissões',
}
ALL_PERMISSIONS = list(PERMISSION_LABELS.keys())
ROLE_PERMISSIONS = {
    # Administrador da empresa vê e opera quase tudo da própria empresa, mas NÃO cria empresas/usuários.
    'admin': [p for p in ALL_PERMISSIONS if p != 'manage_users'],
    # Gestor: acompanha painéis, relatórios e módulos principais, sem poder administrativo global.
    'gestor': [
        'view_dashboard','view_controle','view_combustivel','view_pagamentos','view_custos','view_os','view_os_ativos','view_outlook',
        'view_budget_files','download_os','generate_pdf','generate_excel',
        'edit_combustivel','edit_pagamentos','edit_custos','edit_controle','edit_os','upload_os_photos','upload_budget_files'
    ],
    # Usuário padrão: usa o sistema no dia a dia, com visão ampla, mas sem exclusões/permissões sensíveis.
    'padrao': [
        'view_dashboard','view_controle','view_combustivel','view_pagamentos','view_custos','view_os','view_os_ativos',
        'view_budget_files','download_os','generate_pdf','generate_excel',
        'edit_combustivel','edit_pagamentos','edit_custos','edit_controle','edit_os','upload_os_photos'
    ],
    # Colaborador de campo: foco em O.S. e anexos/fotos.
    'campo': ['view_os','edit_os','upload_os_photos'],
    # Compatibilidade com versões antigas.
    'chefe': [
        'view_dashboard','view_combustivel','view_pagamentos','view_custos','view_os',
        'view_budget_files','download_os','generate_pdf','generate_excel'
    ],
}
ROLE_LABELS = {
    'super_admin': 'Administrador Supremo',
    'campo': 'Colaborador de campo',
    'admin': 'Administrador de empresa',
    'gestor': 'Gestor',
    'padrao': 'Usuário padrão',
    'chefe': 'Gestor',
}

def normalize_permissions(value):
    if isinstance(value, list):
        items = value
    else:
        try:
            items = json.loads(value or '[]')
        except Exception:
            items = []
    return [p for p in items if p in ALL_PERMISSIONS]

TENANT_TABLES = {
    'users', 'bombas', 'combustivel', 'pagamentos', 'custos', 'os_ativos', 'os_ordens',
    'email_history', 'email_monitor_events', 'email_test_history', 'email_monitor_test_runs',
    'recebimentos', 'inventario_itens', 'inventario_movimentos', 'inventario_pedidos',
    'campo_tecnicos', 'campo_eventos', 'push_subscriptions', 'audit_logs',
    'pdf_jobs', 'combustivel_veiculos', 'bombas_locais', 'bombas_movimentacoes',
}
