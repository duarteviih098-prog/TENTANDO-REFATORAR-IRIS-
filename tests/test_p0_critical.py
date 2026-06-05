"""Testes P0 — rotas críticas, migrations e PDF smoke."""
import io

from app.auth.constants import ALL_PERMISSIONS


def test_migrations_applied_on_empty_db(flask_app):
    from app.db import migration_status, query_one

    status = migration_status()
    assert '001' in status['applied']
    assert status['pending'] == []
    row = query_one("SELECT name FROM sqlite_master WHERE type='table' AND name='empresas'")
    assert row is not None


def test_os_save_creates_record(admin_session, client):
    response = client.post(
        '/os/save',
        data={
            '_csrf_token': admin_session['csrf_token'],
            'data': '01/06/2026',
            'sistema': 'ETA Teste',
            'equipamento': 'Bomba 1',
            'status': 'Aberta',
            'finalizada': 'Não',
            'descricao': 'Teste P0',
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    from app.db import query_one

    row = query_one(
        'SELECT id, sistema, empresa_id FROM os_ordens WHERE empresa_id=? ORDER BY id DESC LIMIT 1',
        (admin_session['empresa_id'],),
    )
    assert row is not None
    assert 'eta' in str(row['sistema']).lower()


def test_pagamentos_save_creates_record(admin_session, client):
    response = client.post(
        '/pagamentos/save',
        data={
            '_csrf_token': admin_session['csrf_token'],
            'fornecedor': 'Fornecedor P0',
            'descricao_servico': 'Serviço teste',
            'valor': '100,00',
            'status': 'Pendente',
            'pagamento_mes': '06/2026',
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    from app.db import query_one

    row = query_one(
        'SELECT id, fornecedor FROM pagamentos WHERE empresa_id=? ORDER BY id DESC LIMIT 1',
        (admin_session['empresa_id'],),
    )
    assert row is not None
    assert 'Fornecedor' in str(row['fornecedor'])


def test_inventario_hub_loads(admin_session, client):
    response = client.get('/inventario/hub')
    assert response.status_code == 200
    body = response.get_data(as_text=True).lower()
    assert 'invent' in body


def test_campo_feed_state_json(admin_session, client):
    response = client.get('/api/campo/feed-state')
    assert response.status_code == 200
    data = response.get_json()
    assert data.get('ok') is True
    assert 'version' in data


def test_pdf_build_returns_bytes(admin_session, flask_app):
    from app.os.pdf_builder import _build_os_pdf

    with flask_app.test_request_context('/'):
        from flask import session

        session['empresa_id'] = admin_session['empresa_id']
        session['selected_empresa_id'] = admin_session['empresa_id']
        pdf = _build_os_pdf(
            [{
                'id': 1,
                'numero_os': '1',
                'data': '01/06/2026',
                'sistema': 'ETA',
                'equipamento': 'Bomba',
                'status': 'Aberta',
                'finalizada': 'Não',
                'criticidade': 'Normal',
                'responsavel': 'Técnico',
                'descricao': 'Teste',
                'servico_executado': '',
                'imagens': '[]',
                'teve_terceiro': 'Não',
                'quem_foi_terceiro': '',
                'data_inicio': '',
                'data_fim': '',
                'historico_pausas': '[]',
                'empresa_id': admin_session['empresa_id'],
            }],
            subtitulo='Teste P0',
        )
    assert isinstance(pdf, io.BytesIO)
    pdf.seek(0)
    assert pdf.read(4) == b'%PDF'


def test_permissions_constants_complete():
    assert 'view_os' in ALL_PERMISSIONS
    assert 'edit_pagamentos' in ALL_PERMISSIONS
    assert 'view_inventario' in ALL_PERMISSIONS
