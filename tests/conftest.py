"""Fixtures compartilhadas de teste."""
import json
import os
import tempfile
import uuid

import pytest
from werkzeug.security import generate_password_hash

# Banco isolado por sessão de testes (antes de importar o app).
_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix='.db')
os.close(_fd)
if not os.getenv('DATABASE_URL', '').startswith('postgresql'):
    os.environ['IRIS_TEST_DB'] = _TEST_DB_PATH
os.environ.setdefault('SECRET_KEY', 'test-secret-key-with-32-chars-minimum-ok')


def _clear_schema_cache(*tables):
    from app.db import schema as db_schema

    if tables:
        for table in tables:
            db_schema._TABLE_COLUMNS_CACHE.pop(table, None)
            stale = [k for k in db_schema._TABLE_COLUMN_CACHE if k[0] == table]
            for key in stale:
                db_schema._TABLE_COLUMN_CACHE.pop(key, None)
    else:
        db_schema._TABLE_COLUMNS_CACHE.clear()
        db_schema._TABLE_COLUMN_CACHE.clear()


def ensure_test_schema():
    from app.db.migration_runner import apply_pending_migrations

    apply_pending_migrations()
    _clear_schema_cache()


@pytest.fixture(scope='session')
def flask_app():
    from app import app as application

    application.config.update(TESTING=True)
    ensure_test_schema()
    return application


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def admin_session(client):
    """Empresa + usuário admin com todas as permissões."""
    from app.auth.constants import ALL_PERMISSIONS
    from app.db import execute

    suffix = uuid.uuid4().hex[:8]
    empresa_id = execute(
        "INSERT INTO empresas(nome,cidade,dominio_email,ativo,criado_em) VALUES (?,?,?,1,'01/01/2026')",
        (f'Teste-{suffix}', 'Cidade', f'teste-{suffix}.local'),
    )
    user_id = execute(
        """INSERT INTO users(nome,email,senha_hash,perfil,permissions,ativo,criado_em,empresa_id,is_super_admin)
           VALUES (?,?,?,?,?,1,'01/01/2026',?,0)""",
        (
            'Admin Teste',
            f'admin-{suffix}@teste.local',
            generate_password_hash('senha-teste-123'),
            'admin',
            json.dumps(ALL_PERMISSIONS),
            empresa_id,
        ),
    )
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['empresa_id'] = empresa_id
        sess['selected_empresa_id'] = empresa_id
    client.get('/inventario/hub')
    with client.session_transaction() as sess:
        csrf = sess.get('_csrf_token', '')
    return {
        'empresa_id': empresa_id,
        'user_id': user_id,
        'email': f'admin-{suffix}@teste.local',
        'csrf_token': csrf,
    }
