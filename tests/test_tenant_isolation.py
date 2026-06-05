"""Isolamento multi-empresa — escrita, leitura e anexos."""
import uuid

import pytest


def _other_empresa_and_os(execute):
    suffix = uuid.uuid4().hex[:6]
    other_empresa = execute(
        "INSERT INTO empresas(nome,cidade,dominio_email,ativo,criado_em) VALUES (?,?,?,1,'01/01/2026')",
        (f'Outra-{suffix}', 'C', f'out-{suffix}.local'),
    )
    foreign_os = execute(
        """INSERT INTO os_ordens(numero_os, data, sistema, status, finalizada, empresa_id)
           VALUES ('ISO-1','01/06/2026','ETA','Aberta','Não',?)""",
        (other_empresa,),
    )
    foreign_pag = execute(
        """INSERT INTO pagamentos(fornecedor, valor, status, pagamento_mes, empresa_id)
           VALUES ('Forn X','100','Não','06/2026',?)""",
        (other_empresa,),
    )
    foreign_custo = execute(
        "INSERT INTO custos(sistema, mes, empresa_id) VALUES ('X','06/2026',?)",
        (other_empresa,),
    )
    foreign_comb = execute(
        "INSERT INTO combustivel(data, mes_ref, custo, empresa_id) VALUES ('01/06/2026','06/2026','50',?)",
        (other_empresa,),
    )
    foreign_bomba = execute(
        "INSERT INTO bombas(equipamento, localizacao, empresa_id) VALUES ('B1','estoque',?)",
        (other_empresa,),
    )
    return {
        'empresa_id': other_empresa,
        'os_id': foreign_os,
        'pag_id': foreign_pag,
        'custo_id': foreign_custo,
        'comb_id': foreign_comb,
        'bomba_id': foreign_bomba,
    }


def test_save_os_blocks_cross_tenant(admin_session, flask_app):
    from app.db import execute, query_one
    from app.os.services import save_os

    foreign = _other_empresa_and_os(execute)
    with flask_app.test_request_context('/'):
        from flask import session
        session.update({
            'user_id': admin_session['user_id'],
            'empresa_id': admin_session['empresa_id'],
            'selected_empresa_id': admin_session['empresa_id'],
        })
        with pytest.raises(ValueError, match='sem permissão'):
            save_os({'descricao': 'hack'}, rid=foreign['os_id'])
    assert query_one('SELECT descricao FROM os_ordens WHERE id=?', (foreign['os_id'],))


def test_save_pagamento_blocks_cross_tenant(admin_session, flask_app):
    from app.db import execute, query_one
    from app.pagamentos.services import save_pagamento

    foreign = _other_empresa_and_os(execute)
    with flask_app.test_request_context('/'):
        from flask import session
        session.update({
            'user_id': admin_session['user_id'],
            'empresa_id': admin_session['empresa_id'],
            'selected_empresa_id': admin_session['empresa_id'],
        })
        with pytest.raises(ValueError, match='sem permissão'):
            save_pagamento({'fornecedor': 'hack', 'valor': '9'}, rid=foreign['pag_id'])
    row = query_one('SELECT fornecedor FROM pagamentos WHERE id=?', (foreign['pag_id'],))
    assert row['fornecedor'] == 'Forn X'


def test_save_custo_blocks_cross_tenant(admin_session, flask_app):
    from app.custos.services import save_custo
    from app.db import execute, query_one

    foreign = _other_empresa_and_os(execute)
    with flask_app.test_request_context('/'):
        from flask import session
        session.update({
            'user_id': admin_session['user_id'],
            'empresa_id': admin_session['empresa_id'],
            'selected_empresa_id': admin_session['empresa_id'],
        })
        with pytest.raises(ValueError, match='sem permissão'):
            save_custo({'sistema': 'HACK', 'mes': '06/2026'}, rid=foreign['custo_id'])
    assert query_one('SELECT sistema FROM custos WHERE id=?', (foreign['custo_id'],))['sistema'] == 'X'


def test_save_combustivel_blocks_cross_tenant(admin_session, flask_app):
    from app.combustivel.services import save_combustivel
    from app.db import execute, query_one

    foreign = _other_empresa_and_os(execute)
    with flask_app.test_request_context('/'):
        from flask import session
        session.update({
            'user_id': admin_session['user_id'],
            'empresa_id': admin_session['empresa_id'],
            'selected_empresa_id': admin_session['empresa_id'],
        })
        with pytest.raises(ValueError, match='sem permissão'):
            save_combustivel({'motorista': 'HACK', 'data': '01/06/2026'}, rid=foreign['comb_id'])
    assert query_one('SELECT custo FROM combustivel WHERE id=?', (foreign['comb_id'],))['custo'] == '50'


def test_save_bomba_blocks_cross_tenant(admin_session, flask_app):
    from app.controle.services import save_bomba
    from app.db import execute, query_one

    foreign = _other_empresa_and_os(execute)
    with flask_app.test_request_context('/'):
        from flask import session
        session.update({
            'user_id': admin_session['user_id'],
            'empresa_id': admin_session['empresa_id'],
            'selected_empresa_id': admin_session['empresa_id'],
        })
        with pytest.raises(ValueError, match='sem permissão'):
            save_bomba({'equipamento': 'HACK'}, rid=foreign['bomba_id'])
    assert query_one('SELECT equipamento FROM bombas WHERE id=?', (foreign['bomba_id'],))['equipamento'] == 'B1'


def test_api_pagamentos_get_blocks_cross_tenant(admin_session, client):
    from app.db import execute

    foreign = _other_empresa_and_os(execute)
    response = client.get(f'/api/pagamentos/{foreign["pag_id"]}')
    assert response.status_code == 404


def test_os_orcamento_download_blocks_cross_tenant(admin_session, client):
    from app.db import execute

    foreign = _other_empresa_and_os(execute)
    response = client.get(f'/os/orcamento/{foreign["os_id"]}/0', follow_redirects=False)
    assert response.status_code in (302, 303, 403, 404)
