"""Login e recuperação de senha — mensagens visíveis e fluxo funcional."""
import json
import uuid

from app.auth.constants import ALL_PERMISSIONS
from werkzeug.security import generate_password_hash


def test_wrong_password_shows_message_on_login_page(client):
    response = client.post('/login', data={'email': 'naoexiste@test.local', 'senha': 'errada'})
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'inválid' in body.lower() or 'tentativa' in body.lower()


def test_login_page_links_to_forgot_password(client):
    response = client.get('/login')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert '/esqueci-senha' in body


def test_forgot_password_post_works_without_csrf(client, monkeypatch):
    monkeypatch.delenv('SMTP_USER', raising=False)
    monkeypatch.delenv('SMTP_PASS', raising=False)
    response = client.post('/esqueci-senha', data={'email': 'alguem@test.local'})
    assert response.status_code == 200
    body = response.get_data(as_text=True).lower()
    assert 'recuperação por e-mail ainda não está ativa' in body or 'administrador' in body


def test_forgot_password_with_smtp_shows_success_message(client, monkeypatch):
    from app.db import execute

    monkeypatch.setenv('SMTP_USER', 'smtp@test.local')
    monkeypatch.setenv('SMTP_PASS', 'secret')
    monkeypatch.setattr('app.auth.password_reset._send_reset_email', lambda *_a, **_k: True)

    suffix = uuid.uuid4().hex[:6]
    execute(
        """INSERT INTO users(nome,email,senha_hash,perfil,permissions,ativo,criado_em,empresa_id,is_super_admin)
           VALUES (?,?,?,?,?,1,'01/01/2026',NULL,0)""",
        (
            'U',
            f'user-{suffix}@teste.local',
            generate_password_hash('senha123'),
            'admin',
            json.dumps([]),
        ),
    )
    response = client.post('/esqueci-senha', data={'email': f'user-{suffix}@teste.local'})
    assert response.status_code == 200
    body = response.get_data(as_text=True).lower()
    assert 'receberá as instruções' in body or 'enviado' in body


def test_usuarios_save_does_not_crash_with_missing_imports(client):
    from app.db import execute

    super_id = execute(
        """INSERT INTO users(nome,email,senha_hash,perfil,permissions,ativo,criado_em,empresa_id,is_super_admin)
           VALUES (?,?,?,?,?,1,'01/01/2026',NULL,1)""",
        (
            'Suprema',
            'suprema@test.local',
            generate_password_hash('admin123'),
            'super_admin',
            json.dumps(ALL_PERMISSIONS),
        ),
    )
    empresa_id = execute(
        "INSERT INTO empresas(nome,cidade,dominio_email,ativo,criado_em) VALUES (?,?,?,1,'01/01/2026')",
        ('Empresa UX', 'Cidade', 'ux.local'),
    )
    with client.session_transaction() as sess:
        sess['user_id'] = super_id
        sess['empresa_id'] = empresa_id
        sess['selected_empresa_id'] = empresa_id
    client.get('/login')
    with client.session_transaction() as sess:
        csrf = sess.get('_csrf_token', '')
    response = client.post(
        '/usuarios/save',
        data={
            '_csrf_token': csrf,
            'nome': 'Novo Colaborador',
            'email': 'novo@ux.local',
            'senha': 'senha123',
            'perfil': 'padrao',
            'empresa_id': str(empresa_id),
            'ativo': '1',
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
